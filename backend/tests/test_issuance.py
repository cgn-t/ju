"""Otomatik CA sertifika alımı (issuance) — Vault PKI sign_csr akışı, onay-kapılı/zero-touch,
CN/SAN doğrulaması, RBAC, ve mevcut renewal/devir önerisi hattına besleme regresyonu.

VaultProvider.sign_csr GERÇEK Vault'a bağlanmaz — test_deployment_engine.py'nin JenkinsClient
fake'i deseninde monkeypatch edilir (unit seviyesi; lab/vault'a karşı gerçek entegrasyon ayrı
elle doğrulanır, bkz. plan dosyası "Doğrulama" bölümü)."""

from app.db.models import Certificate, CertificateDomainMap
from app.db.session import SessionLocal
from app.services.providers.base import IssuedCertificate
from app.services.providers.vault import VaultProvider
from tests import certgen


def _sy_team(client, h, name):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _editor_in(client, h, username, team_id):
    client.post("/api/users", headers=h, json={
        "username": username, "password": "x", "role": "editor", "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=h).json()
               if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=h, json={"user_id": uid})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _domain(client, h, name, sy_team_id=None, **extra):
    body = {"domain": name, **extra}
    if sy_team_id:
        body["sy_team_id"] = sy_team_id
    r = client.post("/api/domains", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _enable_issuance(client, h):
    cfg = client.get("/api/settings/issuance", headers=h).json()
    cfg["enabled"] = True
    assert client.put("/api/settings/issuance", headers=h, json=cfg).status_code == 200


def _create_profile(client, h, name, enabled=True):
    r = client.post("/api/issuance/profiles", headers=h, json={
        "name": name, "ca_type": "vault_pki", "enabled": enabled,
        "vault_mount": "pki_int", "vault_role": "jumbo-demo"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _install_vault_fake(monkeypatch, cert_pem, ca_pem=None, *, exc=None):
    def fake_sign_csr(self, csr_pem, common_name, sans, ttl_hours=None, *, mount=None, role=None):
        if exc:
            raise exc
        return IssuedCertificate(pem_certificate=cert_pem, ca_chain_pem=ca_pem)
    monkeypatch.setattr(VaultProvider, "sign_csr", fake_sign_csr)


def _run_pending():
    from app.services.notifier import run_pending_issuance
    run_pending_issuance()


def _get_request(client, h, request_id):
    rows = client.get("/api/issuance", headers=h).json()
    return next(r for r in rows if r["id"] == request_id)


# ---------------------------------------------------------------------------
# 1. Uçtan uca onay-kapılı akış: yeni domain, önceden sertifikası yok
# ---------------------------------------------------------------------------

def test_full_flow_approval_gated_creates_mapping(client, auth_headers, monkeypatch):
    h = auth_headers
    _enable_issuance(client, h)
    tid = _sy_team(client, h, "SY-Iss-Full")
    eh = _editor_in(client, h, "iss_ed_full", tid)
    dom_id = _domain(client, h, "iss-full.example.com", tid)
    profile_id = _create_profile(client, h, "vault-full")

    ca_cert, ca_key = certgen.make_ca("Test Root Full")
    leaf_cert, _ = certgen.make_leaf(ca_cert, ca_key, "iss-full.example.com",
                                     san=["iss-full.example.com"])
    _install_vault_fake(monkeypatch, certgen.pem(leaf_cert), certgen.pem(ca_cert))

    r = client.post("/api/issuance", headers=eh, json={"domain_id": dom_id, "profile_id": profile_id})
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "pending_approval"
    assert req["zero_touch"] is False
    assert req["common_name"] == "iss-full.example.com"

    # İkinci istek açmaya çalışmak 409 vermeli (açık istek zaten var)
    r2 = client.post("/api/issuance", headers=eh, json={"domain_id": dom_id, "profile_id": profile_id})
    assert r2.status_code == 409

    assert client.post(f"/api/issuance/{req['id']}/csr", headers=eh,
                       json={"csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\ndummy\n"}
                       ).status_code == 200

    r = client.post(f"/api/issuance/{req['id']}/approve", headers=eh)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    # İkinci onay 409 (atomik CAS)
    assert client.post(f"/api/issuance/{req['id']}/approve", headers=eh).status_code == 409

    _run_pending()

    issued = _get_request(client, h, req["id"])
    assert issued["status"] == "issued", issued
    assert issued["result_cert_id"] is not None

    db = SessionLocal()
    try:
        cert = db.get(Certificate, issued["result_cert_id"])
        assert cert.source == "issuance"
        mapping = (db.query(CertificateDomainMap)
                  .filter_by(certificate_id=cert.id, domain_id=dom_id, mapping_type="server")
                  .first())
        assert mapping is not None, "ilk alımda öncül yok → doğrudan server eşlemesi kurulmalı"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Yenileme (renewal) hattına besleme regresyonu: aynı subject+issuer, farklı anahtar
#    → renewal.propose ile devir önerisi üretilmeli, mevcut sertifika ANINDA değişmemeli.
# ---------------------------------------------------------------------------

def test_finalize_reuses_renewal_pipeline_creates_proposal(client, auth_headers, monkeypatch):
    h = auth_headers
    _enable_issuance(client, h)
    tid = _sy_team(client, h, "SY-Iss-Renew")
    eh = _editor_in(client, h, "iss_ed_renew", tid)
    dom_id = _domain(client, h, "iss-renew.example.com", tid)
    profile_id = _create_profile(client, h, "vault-renew")

    from datetime import datetime as _dt

    ca_cert, ca_key = certgen.make_ca("Test Root Renew")
    old_leaf, _ = certgen.make_leaf(ca_cert, ca_key, "iss-renew.example.com",
                                    san=["iss-renew.example.com"], not_before=_dt(2026, 1, 1))
    files = {"file": ("chain.pem", (certgen.pem(old_leaf) + certgen.pem(ca_cert)).encode(),
                      "application/x-pem-file")}
    r = client.post("/api/certificates/import", headers=h, files=files)
    assert r.status_code == 200, r.text
    old_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    assert client.post(f"/api/domains/{dom_id}/certificates", headers=h,
                       json={"certificate_id": old_id, "mapping_type": "server"}).status_code == 200

    # YENİ anahtarla aynı subject+issuer, DAHA GEÇ valid_from (find_predecessors yön koruması
    # yalnız valid_from'u yeniden ESKİ kayıtları öncül sayar) → subject+issuer sinyaliyle yakalanır
    new_leaf, _ = certgen.make_leaf(ca_cert, ca_key, "iss-renew.example.com",
                                    san=["iss-renew.example.com"], not_before=_dt(2026, 3, 1))
    _install_vault_fake(monkeypatch, certgen.pem(new_leaf), certgen.pem(ca_cert))

    r = client.post("/api/issuance", headers=eh, json={"domain_id": dom_id, "profile_id": profile_id})
    req_id = r.json()["id"]
    client.post(f"/api/issuance/{req_id}/csr", headers=eh, json={"csr_pem": "dummy"})
    client.post(f"/api/issuance/{req_id}/approve", headers=eh)
    _run_pending()

    issued = _get_request(client, h, req_id)
    assert issued["status"] == "issued"
    new_id = issued["result_cert_id"]
    assert new_id != old_id

    # Öncül tespit edildiği için DOĞRUDAN eşleme kurulmamalı — devir önerisi (pending) üretilmeli
    db = SessionLocal()
    try:
        mapping = (db.query(CertificateDomainMap)
                  .filter_by(domain_id=dom_id, mapping_type="server").first())
        assert mapping.certificate_id == old_id, \
            "onay-kapılı akışta onaydan ÖNCE eşleme DEĞİŞMEMELİ (JUMBO'nun devir felsefesi)"
    finally:
        db.close()

    proposals = client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
    prop = next(p for p in proposals if p["old_cert_id"] == old_id and p["new_cert_id"] == new_id)
    assert prop["via"] == "issuance"

    # SY ekibi öneriyi onaylar → mevcut renewal.apply_proposal hattı devreye girer
    assert client.post(f"/api/proposals/{prop['id']}/approve", headers=eh).status_code == 200
    db = SessionLocal()
    try:
        mapping = (db.query(CertificateDomainMap)
                  .filter_by(domain_id=dom_id, mapping_type="server").first())
        assert mapping.certificate_id == new_id
        assert db.get(Certificate, old_id).is_active is False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. Zero-touch: hem CA çağrısı hem sonucun uygulanması onaysız geçer
# ---------------------------------------------------------------------------

def test_zero_touch_skips_approval_and_applies_immediately(client, auth_headers, monkeypatch):
    h = auth_headers
    _enable_issuance(client, h)
    tid = _sy_team(client, h, "SY-Iss-ZT")
    dom_id = _domain(client, h, "iss-zt.example.com", tid)
    # zero_touch admin-only — admin PUT ile açar
    assert client.put(f"/api/domains/{dom_id}", headers=h,
                      json={"issuance_zero_touch": True}).status_code == 200
    profile_id = _create_profile(client, h, "vault-zt")

    ca_cert, ca_key = certgen.make_ca("Test Root ZT")
    leaf_cert, _ = certgen.make_leaf(ca_cert, ca_key, "iss-zt.example.com", san=["iss-zt.example.com"])
    _install_vault_fake(monkeypatch, certgen.pem(leaf_cert), certgen.pem(ca_cert))

    r = client.post("/api/issuance", headers=h, json={"domain_id": dom_id, "profile_id": profile_id})
    req = r.json()
    assert req["status"] == "approved", "zero-touch: onay adımı ATLANMALI"
    assert req["zero_touch"] is True

    client.post(f"/api/issuance/{req['id']}/csr", headers=h, json={"csr_pem": "dummy"})
    _run_pending()

    issued = _get_request(client, h, req["id"])
    assert issued["status"] == "issued"
    db = SessionLocal()
    try:
        mapping = (db.query(CertificateDomainMap)
                  .filter_by(domain_id=dom_id, mapping_type="server").first())
        assert mapping is not None and mapping.certificate_id == issued["result_cert_id"], \
            "zero-touch: eşleme İNSAN ONAYI OLMADAN uygulanmalı"
    finally:
        db.close()


def test_non_admin_cannot_enable_zero_touch(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Iss-ZTGuard")
    eh = _editor_in(client, h, "iss_ed_ztguard", tid)
    dom_id = _domain(client, h, "iss-ztguard.example.com", tid)
    r = client.put(f"/api/domains/{dom_id}", headers=eh, json={"issuance_zero_touch": True})
    assert r.status_code == 403
    r2 = client.post("/api/domains", headers=eh,
                     json={"domain": "iss-ztguard2.example.com", "sy_team_id": tid,
                          "issuance_zero_touch": True})
    assert r2.status_code == 403


# ---------------------------------------------------------------------------
# 4. Sonuç doğrulama: CA yanıtı istekle eşleşmiyorsa envantere GİRMEZ
# ---------------------------------------------------------------------------

def test_cn_mismatch_fails_without_polluting_inventory(client, auth_headers, monkeypatch):
    h = auth_headers
    _enable_issuance(client, h)
    tid = _sy_team(client, h, "SY-Iss-Mismatch")
    eh = _editor_in(client, h, "iss_ed_mismatch", tid)
    dom_id = _domain(client, h, "iss-mismatch.example.com", tid)
    profile_id = _create_profile(client, h, "vault-mismatch")

    ca_cert, ca_key = certgen.make_ca("Test Root Mismatch")
    wrong_leaf, _ = certgen.make_leaf(ca_cert, ca_key, "baska-domain.example.com",
                                      san=["baska-domain.example.com"])
    _install_vault_fake(monkeypatch, certgen.pem(wrong_leaf), certgen.pem(ca_cert))

    r = client.post("/api/issuance", headers=eh, json={"domain_id": dom_id, "profile_id": profile_id})
    req_id = r.json()["id"]
    client.post(f"/api/issuance/{req_id}/csr", headers=eh, json={"csr_pem": "dummy"})
    client.post(f"/api/issuance/{req_id}/approve", headers=eh)
    _run_pending()

    failed = _get_request(client, h, req_id)
    assert failed["status"] == "failed"
    assert "eşleşmiyor" in (failed["last_error"] or "")
    assert failed["result_cert_id"] is None

    db = SessionLocal()
    try:
        assert db.query(CertificateDomainMap).filter_by(domain_id=dom_id).first() is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. Global kill-switch: issuance.enabled=False iken execute_request no-op
# ---------------------------------------------------------------------------

def test_global_kill_switch_blocks_execution(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Iss-Kill")
    eh = _editor_in(client, h, "iss_ed_kill", tid)
    dom_id = _domain(client, h, "iss-kill.example.com", tid)
    profile_id = _create_profile(client, h, "vault-kill")

    cfg = client.get("/api/settings/issuance", headers=h).json()
    cfg["enabled"] = False
    assert client.put("/api/settings/issuance", headers=h, json=cfg).status_code == 200

    called = {"n": 0}

    def fake_sign_csr(self, *a, **kw):
        called["n"] += 1
        raise AssertionError("kill-switch kapalıyken CA çağrısı YAPILMAMALI")
    monkeypatch.setattr(VaultProvider, "sign_csr", fake_sign_csr)

    r = client.post("/api/issuance", headers=eh, json={"domain_id": dom_id, "profile_id": profile_id})
    req_id = r.json()["id"]
    client.post(f"/api/issuance/{req_id}/csr", headers=eh, json={"csr_pem": "dummy"})
    client.post(f"/api/issuance/{req_id}/approve", headers=eh)
    _run_pending()

    assert called["n"] == 0
    still_approved = _get_request(client, h, req_id)
    assert still_approved["status"] == "approved"


# ---------------------------------------------------------------------------
# 6. RBAC
# ---------------------------------------------------------------------------

def test_profile_write_is_admin_only_but_listing_is_not(client, auth_headers):
    """Yazma (create/update/delete) admin-only; OKUMA editor+ — SY editörü kendi domaininde
    hangi CA profilini seçeceğini görebilmeli (IssuanceProfileOut hassas alan döndürmez)."""
    h = auth_headers
    tid = _sy_team(client, h, "SY-Iss-RbacProfile")
    eh = _editor_in(client, h, "iss_ed_rbacprofile", tid)
    assert client.get("/api/issuance/profiles", headers=eh).status_code == 200
    assert client.post("/api/issuance/profiles", headers=eh,
                       json={"name": "x", "ca_type": "vault_pki"}).status_code == 403


def test_cross_team_editor_cannot_create_or_approve(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Iss-Own")
    other_tid = _sy_team(client, h, "SY-Iss-Other")
    other_eh = _editor_in(client, h, "iss_ed_other", other_tid)
    dom_id = _domain(client, h, "iss-own.example.com", tid)
    profile_id = _create_profile(client, h, "vault-cross")

    r = client.post("/api/issuance", headers=other_eh,
                    json={"domain_id": dom_id, "profile_id": profile_id})
    assert r.status_code == 403

    owner_eh = _editor_in(client, h, "iss_ed_own", tid)
    r = client.post("/api/issuance", headers=owner_eh,
                    json={"domain_id": dom_id, "profile_id": profile_id})
    req_id = r.json()["id"]
    assert client.post(f"/api/issuance/{req_id}/approve", headers=other_eh).status_code == 403
