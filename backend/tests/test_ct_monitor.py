"""Certificate Transparency (crt.sh) izleme testleri.

Kapsam: CT bulgusu envanterde yoksa shadow (origin=ct, host=domain, port=0) / varsa in_inventory;
precertificate atlanır; bir domain erişilemezse (egress engeli) tarama ÇÖKMEZ — hatayı kaydedip diğer
domainleri işler (graceful degrade); enabled=False iken gece işi atlar; ct-scan ucu admin-only.

Egress yapılmaz: ct_monitor.query_crtsh ve download_cert monkeypatch'lenerek sahte bir crt.sh 'sunulur'.
"""

from datetime import datetime

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

from app.db.models import DiscoveredCertificate, ScanRun
from app.db.session import SessionLocal
from app.services import ct_monitor
from tests import certgen


@pytest.fixture(autouse=True)
def _clean_ct(client):
    """Her testten önce keşif bulgu/çalıştırma tablolarını temizler. Domain'lere DOKUNMAZ: DB
    session-kapsamlı ve paylaşımlıdır; domain toplu silmek önceki testlerin domain_certificates
    eşleşmelerini öksüz bırakır (mapping.domain=None). Testler önceden var olan domainlere dayanıklıdır
    (crt.sh monkeypatch'i eşlenmemiş host'lar için [] döner → onlar bulgu üretmez)."""
    db = SessionLocal()
    try:
        db.query(DiscoveredCertificate).delete()
        db.query(ScanRun).delete()
        db.commit()
    finally:
        db.close()
    yield


def _mk_user(client, admin, username, role):
    r = client.post("/api/users", headers=admin, json={
        "username": username, "password": "pw12345", "role": role, "auth_source": "local"})
    assert r.status_code == 200, r.text


def _login(client, username, password="pw12345"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _add_domain(client, headers, domain):
    r = client.post("/api/domains", headers=headers, json={"domain": domain})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import(client, headers, pem_text):
    files = {"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")}
    r = client.post("/api/certificates/import", headers=headers, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _serve_ct(monkeypatch, mapping):
    """host → [(crtsh_id, x509cert), ...] eşlemesini crt.sh yerine koyar (egress yok)."""
    entries = {host: [{"id": cid} for cid, _ in items] for host, items in mapping.items()}
    certs = {cid: cert for items in mapping.values() for cid, cert in items}
    monkeypatch.setattr(ct_monitor, "query_crtsh", lambda host, client: entries.get(host, []))
    monkeypatch.setattr(ct_monitor, "download_cert", lambda cid, client: certs[cid])


def _make_precert(ca_cert, ca_key, cn: str):
    """CT poison uzantılı precertificate — CT taramasında ATLANMALI (gerçek sunulan cert değildir)."""
    key = certgen.make_key()
    return (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2027, 1, 1))
            .add_extension(x509.PrecertPoison(), critical=True)
            .sign(ca_key, hashes.SHA256()))


# ---- shadow vs envanterde ----
def test_ct_scan_flags_shadow_and_known(client, auth_headers, monkeypatch):
    ca, ck = certgen.make_ca("CT CA")
    known, _ = certgen.make_leaf(ca, ck, "known.example.com")
    shadow, _ = certgen.make_leaf(ca, ck, "shadow.example.com")
    _import(client, auth_headers, certgen.pem(known) + certgen.pem(ca))  # yalnız known envanterde
    _add_domain(client, auth_headers, "known.example.com")
    _add_domain(client, auth_headers, "shadow.example.com")

    _serve_ct(monkeypatch, {
        "known.example.com": [("1", known)],
        "shadow.example.com": [("2", shadow)],
    })

    db = SessionLocal()
    run = ct_monitor.run_ct_scan(db)
    db.close()
    assert run.status == "done"
    assert run.kind == "ct"
    # NOT: paylaşımlı DB'de başka testlerden domain kalabilir (crt.sh monkeypatch'i onlar için [] döner);
    # bu yüzden yalnız BENİM shadow'um yeni bulgudur.
    assert run.new_findings == 1

    findings = {f["name"]: f for f in
                client.get("/api/discovery/findings", headers=auth_headers,
                           params={"origin": "ct"}).json()}
    assert findings["known.example.com"]["status"] == "in_inventory"
    assert findings["known.example.com"]["origin"] == "ct"
    assert findings["known.example.com"]["port"] == 0           # CT bulgusunda endpoint yok
    assert findings["known.example.com"]["matched_certificate_id"] is not None
    assert findings["shadow.example.com"]["status"] == "new"
    assert findings["shadow.example.com"]["matched_certificate_id"] is None


# ---- precertificate atlanır ----
def test_ct_skips_precertificates(client, auth_headers, monkeypatch):
    ca, ck = certgen.make_ca("CT PreCA")
    precert = _make_precert(ca, ck, "poison.example.com")
    _add_domain(client, auth_headers, "poison.example.com")
    _serve_ct(monkeypatch, {"poison.example.com": [("7", precert)]})

    db = SessionLocal()
    run = ct_monitor.run_ct_scan(db)
    db.close()
    assert run.new_findings == 0  # poison → atlandı, bulgu yok
    assert client.get("/api/discovery/findings", headers=auth_headers,
                      params={"origin": "ct"}).json() == []


# ---- egress engeli: graceful degrade ----
def test_ct_scan_graceful_on_egress_failure(client, auth_headers, monkeypatch):
    ca, ck = certgen.make_ca("CT CA2")
    good, _ = certgen.make_leaf(ca, ck, "reachable.example.com")
    _add_domain(client, auth_headers, "reachable.example.com")
    _add_domain(client, auth_headers, "blocked.example.com")

    def fake_query(host, _client):
        if host == "blocked.example.com":
            raise httpx.ConnectError("egress blocked")
        if host == "reachable.example.com":
            return [{"id": "9"}]
        return []  # paylaşımlı DB'deki diğer domainler bulgu üretmesin
    monkeypatch.setattr(ct_monitor, "query_crtsh", fake_query)
    monkeypatch.setattr(ct_monitor, "download_cert", lambda cid, _client: good)

    db = SessionLocal()
    run = ct_monitor.run_ct_scan(db)
    db.close()
    assert run.status == "done"                       # bir domain erişilemese de ÇÖKMEZ
    assert run.error and "blocked.example.com" in run.error
    names = [f["name"] for f in
             client.get("/api/discovery/findings", headers=auth_headers,
                        params={"origin": "ct"}).json()]
    assert "reachable.example.com" in names            # erişilen domain işlendi


# ---- gece işi enabled=False iken atlar ----
def test_ct_job_skips_when_disabled(client):
    ct_monitor.run_ct_scan_job()  # ct.enabled varsayılan False → run oluşturulmamalı
    db = SessionLocal()
    try:
        assert db.query(ScanRun).count() == 0
    finally:
        db.close()


# ---- yetki: ct-scan admin-only ----
def test_ct_scan_auth_gates(client, auth_headers):
    _mk_user(client, auth_headers, "ct_viewer", "viewer")
    _mk_user(client, auth_headers, "ct_editor", "editor")
    for h in (_login(client, "ct_viewer"), _login(client, "ct_editor")):
        assert client.post("/api/discovery/ct-scan", headers=h).status_code == 403

    # admin: rol geçer → domain varken (paylaşımlı DB'de en az bir domain mevcut) 200
    _add_domain(client, auth_headers, "any.example.com")
    assert client.post("/api/discovery/ct-scan", headers=auth_headers).status_code == 200
