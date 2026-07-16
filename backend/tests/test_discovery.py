"""Ağ keşfi (network discovery) testleri.

Kapsam: CIDR genişletme + max_hosts kırpma; shadow (new) vs in_inventory ayrımı; benimseme (adopt)
envantere alır (source=discovery); idempotent upsert (last_seen güncellenir, kullanıcı kararı korunur);
hedef doğrulama; yetki kapıları (bulgular global-viewer, hedef/tarama admin-only, adopt editor+).

Ağ I/O yapılmaz: discovery.scan_endpoint monkeypatch'lenerek sentetik sertifikalar 'sunulur'.
"""

import pytest

from app.db.models import Certificate, DiscoveredCertificate, ScanRun, ScanTarget
from app.db.session import SessionLocal
from app.services import discovery
from app.services.cert_parser import parse_x509
from tests import certgen


@pytest.fixture(autouse=True)
def _clean_discovery(client):
    """Her testten önce keşif tablolarını temizler (session-kapsamlı DB izolasyonu)."""
    db = SessionLocal()
    try:
        db.query(DiscoveredCertificate).delete()
        db.query(ScanTarget).delete()
        db.query(ScanRun).delete()
        db.commit()
    finally:
        db.close()
    yield


def _mk_user(client, admin, username, role):
    r = client.post("/api/users", headers=admin, json={
        "username": username, "password": "pw12345", "role": role, "auth_source": "local"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login(client, username, password="pw12345"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _add_host_target(value, ports="443"):
    db = SessionLocal()
    try:
        db.add(ScanTarget(name=value, kind="host", value=value, ports=ports, enabled=True))
        db.commit()
    finally:
        db.close()


def _serve(monkeypatch, mapping):
    """(host,port) → x509 cert eşlemesini scan_endpoint yerine koyar (ağ I/O yok)."""
    served = {k: parse_x509(v) for k, v in mapping.items()}
    monkeypatch.setattr(discovery, "scan_endpoint", lambda h, p, t: served.get((h, p)))


def _serve_chain(monkeypatch, mapping):
    """(host,port) → [x509 cert,...] zincirini adopt'ın canlı çekişi (fetch_served_chain) yerine koyar.
    fetch_served_chain HAM x509 döndürür (adopt kendisi parse_x509 uygular). Eşleşmeyen endpoint
    offline sayılır (ConnectionError) → adopt saklı PEM'e düşer. Ağ I/O yok."""
    from app.api import discovery as discovery_api
    served = {k: list(v) for k, v in mapping.items()}

    def fake(host, port):
        chain = served.get((host, port))
        if chain is None:
            raise ConnectionError("offline (test)")
        return chain

    monkeypatch.setattr(discovery_api, "fetch_served_chain", fake)


def _import(client, headers, pem_text):
    files = {"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")}
    r = client.post("/api/certificates/import", headers=headers, files=files)
    assert r.status_code == 200, r.text
    return r.json()


# ---- expand_targets ----
def test_expand_targets_cidr_and_max_hosts(client):
    db = SessionLocal()
    try:
        db.add(ScanTarget(name="net", kind="cidr", value="10.9.8.0/29", ports="443,8443", enabled=True))
        db.commit()
        # /29 → 6 kullanılabilir host × 2 port = 12 (üçlü: host, port, sy_team_id)
        full = discovery.expand_targets(db, {"default_ports": "443", "max_hosts": 100})
        assert len(full) == 12
        assert ("10.9.8.1", 443, None) in full and ("10.9.8.6", 8443, None) in full
        # max_hosts sınırı kırpar
        capped = discovery.expand_targets(db, {"default_ports": "443", "max_hosts": 5})
        assert len(capped) == 5
    finally:
        db.close()


def test_expand_targets_rejects_huge_cidr(client):
    db = SessionLocal()
    try:
        db.add(ScanTarget(name="big", kind="cidr", value="10.0.0.0/8", ports="443", enabled=True))
        db.commit()
        # devasa CIDR atlanır (log) → hiç hedef üretilmez
        assert discovery.expand_targets(db, {"default_ports": "443", "max_hosts": 100}) == []
    finally:
        db.close()


# ---- tarama: shadow vs envanterde ----
def test_scan_flags_shadow_and_known(client, auth_headers, monkeypatch):
    ca, ca_key = certgen.make_ca("Disc CA")
    known, _ = certgen.make_leaf(ca, ca_key, "known.local")
    shadow, _ = certgen.make_leaf(ca, ca_key, "shadow.local")
    _import(client, auth_headers, certgen.pem(known) + certgen.pem(ca))  # envantere al

    _add_host_target("10.0.0.1")   # known sunacak
    _add_host_target("10.0.0.2")   # shadow sunacak
    _serve(monkeypatch, {("10.0.0.1", 443): known, ("10.0.0.2", 443): shadow})

    db = SessionLocal()
    run = discovery.run_scan(db)
    db.close()
    assert run.status == "done"
    assert run.hosts_reachable == 2
    assert run.new_findings == 1  # yalnız shadow yeni bulgu

    findings = {f["name"]: f for f in client.get("/api/discovery/findings", headers=auth_headers).json()}
    assert findings["known.local"]["status"] == "in_inventory"
    assert findings["known.local"]["matched_certificate_id"] is not None
    assert findings["shadow.local"]["status"] == "new"
    assert findings["shadow.local"]["matched_certificate_id"] is None


# ---- benimseme (adopt) ----
def test_adopt_creates_inventory_cert(client, auth_headers, monkeypatch):
    ca, ca_key = certgen.make_ca("Adopt CA")
    shadow, _ = certgen.make_leaf(ca, ca_key, "adopt.local")
    _add_host_target("10.0.1.1")
    _serve(monkeypatch, {("10.0.1.1", 443): shadow})

    db = SessionLocal()
    discovery.run_scan(db)
    db.close()

    only_new = client.get("/api/discovery/findings", headers=auth_headers,
                          params={"only_new": True}).json()
    assert len(only_new) == 1 and only_new[0]["name"] == "adopt.local"
    fid = only_new[0]["id"]

    _serve_chain(monkeypatch, {})  # endpoint offline → saklı leaf PEM'e düş (tek sertifika)
    r = client.post(f"/api/discovery/findings/{fid}/adopt", headers=auth_headers)
    assert r.status_code == 200 and r.json()["created"] == ["adopt.local"]

    cert = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["name"] == "adopt.local")
    assert cert["source"] == "discovery"

    # yeniden tarama: kullanıcı kararı korunur (adopted), envanter eşleşmesi görünür
    _serve(monkeypatch, {("10.0.1.1", 443): shadow})
    db = SessionLocal()
    run = discovery.run_scan(db)
    db.close()
    assert run.new_findings == 0
    f = next(f for f in client.get("/api/discovery/findings", headers=auth_headers).json()
             if f["name"] == "adopt.local")
    assert f["status"] == "adopted"
    assert f["matched_certificate_id"] is not None


# ---- hedef ekibi benimsenen sertifikaya taşınır (Oluşturan) ----
def test_adopt_carries_target_team(client, auth_headers, monkeypatch):
    tid = client.post("/api/teams", headers=auth_headers,
                      json={"name": "Keşif SY", "type": "SY"}).json()["id"]
    db = SessionLocal()
    db.add(ScanTarget(name="teamed", kind="host", value="10.0.4.1", ports="443",
                      enabled=True, sy_team_id=tid))
    db.commit()
    db.close()
    ca, ck = certgen.make_ca("Team CA")
    leaf, _ = certgen.make_leaf(ca, ck, "teamed.local")
    _serve(monkeypatch, {("10.0.4.1", 443): leaf})
    db = SessionLocal()
    discovery.run_scan(db)
    db.close()

    f = client.get("/api/discovery/findings", headers=auth_headers).json()[0]
    assert f["sy_team_name"] == "Keşif SY"   # bulgu hedefin ekibini taşır
    _serve_chain(monkeypatch, {})            # endpoint offline → saklı leaf'e düş
    r = client.post(f"/api/discovery/findings/{f['id']}/adopt", headers=auth_headers)
    assert r.status_code == 200
    cert = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["name"] == "teamed.local")
    assert cert["creator"] == "Keşif SY"     # Oluşturan = hedefin SY ekibi (admin username değil)


# ---- benimseme: ağ bulgusunda canlı zincir çekilip intermediate'ler de bağlanır ----
def test_adopt_fetches_and_links_full_chain(client, auth_headers, monkeypatch):
    ca, ck = certgen.make_ca("Chain Adopt CA")
    leaf, _ = certgen.make_leaf(ca, ck, "chainadopt.local")
    _add_host_target("10.0.5.1")
    _serve(monkeypatch, {("10.0.5.1", 443): leaf})   # tarama yalnız leaf'i görür/saklar

    db = SessionLocal()
    discovery.run_scan(db)
    db.close()
    fid = next(f["id"] for f in client.get("/api/discovery/findings", headers=auth_headers,
                                            params={"only_new": True}).json())

    # benimseme anında endpoint TÜM zinciri (leaf+CA) sunar → ikisi de envantere girmeli, leaf CA'ya bağlanmalı
    _serve_chain(monkeypatch, {("10.0.5.1", 443): [leaf, ca]})
    r = client.post(f"/api/discovery/findings/{fid}/adopt", headers=auth_headers)
    assert r.status_code == 200
    assert set(r.json()["created"]) == {"chainadopt.local", "Chain Adopt CA"}

    db = SessionLocal()
    try:
        leaf_row = db.query(Certificate).filter_by(name="chainadopt.local").first()
        ca_row = db.query(Certificate).filter_by(name="Chain Adopt CA").first()
        assert leaf_row is not None and ca_row is not None
        assert leaf_row.cert_type == "leaf" and ca_row.cert_type in ("root", "intermediate")
        assert leaf_row.parent_id == ca_row.id       # zincir SKI/AKI ile bağlandı
        assert leaf_row.source == "discovery"
    finally:
        db.close()


# ---- idempotent upsert ----
def test_scan_upsert_is_idempotent(client, auth_headers, monkeypatch):
    ca, ca_key = certgen.make_ca("Idem CA")
    shadow, _ = certgen.make_leaf(ca, ca_key, "idem.local")
    _add_host_target("10.0.2.1")
    _serve(monkeypatch, {("10.0.2.1", 443): shadow})

    for _ in range(2):
        db = SessionLocal()
        discovery.run_scan(db)
        db.close()

    same = [f for f in client.get("/api/discovery/findings", headers=auth_headers).json()
            if f["host"] == "10.0.2.1"]
    assert len(same) == 1  # mükerrer bulgu yok

    db = SessionLocal()
    run = discovery.run_scan(db)
    db.close()
    assert run.new_findings == 0  # üçüncü tarama yeni bulgu üretmez


def test_ignore_persists_across_rescan(client, auth_headers, monkeypatch):
    ca, ca_key = certgen.make_ca("Ign CA")
    shadow, _ = certgen.make_leaf(ca, ca_key, "ignore.local")
    _add_host_target("10.0.3.1")
    _serve(monkeypatch, {("10.0.3.1", 443): shadow})
    db = SessionLocal(); discovery.run_scan(db); db.close()

    fid = client.get("/api/discovery/findings", headers=auth_headers).json()[0]["id"]
    assert client.post(f"/api/discovery/findings/{fid}/ignore", headers=auth_headers).status_code == 200

    _serve(monkeypatch, {("10.0.3.1", 443): shadow})
    db = SessionLocal(); discovery.run_scan(db); db.close()
    f = client.get("/api/discovery/findings", headers=auth_headers).json()[0]
    assert f["status"] == "ignored"  # yeniden taramada 'new'e dönmez


# ---- hedef doğrulama ----
def test_target_validation_and_crud(client, auth_headers):
    a = auth_headers
    assert client.post("/api/discovery/targets", headers=a,
                       json={"name": "inv", "kind": "inventory"}).status_code == 200
    assert client.post("/api/discovery/targets", headers=a,
                       json={"name": "h", "kind": "host"}).status_code == 400  # value gerekli
    assert client.post("/api/discovery/targets", headers=a,
                       json={"name": "h", "kind": "host", "value": "1.2.3.4",
                             "ports": "abc"}).status_code == 400  # geçersiz port
    assert client.post("/api/discovery/targets", headers=a,
                       json={"name": "big", "kind": "cidr", "value": "10.0.0.0/8"}).status_code == 400
    r = client.post("/api/discovery/targets", headers=a,
                    json={"name": "ok", "kind": "cidr", "value": "192.168.5.0/24"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert client.put(f"/api/discovery/targets/{tid}", headers=a,
                      json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/discovery/targets/{tid}", headers=a).status_code == 200


# ---- yetki kapıları ----
def test_auth_gates(client, auth_headers):
    """Keşif TAMAMEN admin-only (kullanıcı kararı): viewer ve editor hiçbir keşif ucuna erişemez (403)."""
    _mk_user(client, auth_headers, "disc_viewer", "viewer")
    _mk_user(client, auth_headers, "disc_editor", "editor")
    vh = _login(client, "disc_viewer")
    eh = _login(client, "disc_editor")

    for h in (vh, eh):  # non-admin: TÜM uçlar 403
        assert client.get("/api/discovery/findings", headers=h).status_code == 403
        assert client.get("/api/discovery/runs", headers=h).status_code == 403
        assert client.get("/api/discovery/targets", headers=h).status_code == 403
        assert client.post("/api/discovery/targets", headers=h,
                           json={"name": "x", "kind": "inventory"}).status_code == 403
        assert client.post("/api/discovery/scan", headers=h).status_code == 403
        assert client.post("/api/discovery/findings/999999/adopt", headers=h).status_code == 403
        assert client.post("/api/discovery/findings/999999/ignore", headers=h).status_code == 403

    # admin: rol geçer → findings 200; scan (etkin hedef yok) 400; olmayan bulgu adopt 404
    assert client.get("/api/discovery/findings", headers=auth_headers).status_code == 200
    assert client.post("/api/discovery/scan", headers=auth_headers).status_code == 400
    assert client.post("/api/discovery/findings/999999/adopt", headers=auth_headers).status_code == 404
