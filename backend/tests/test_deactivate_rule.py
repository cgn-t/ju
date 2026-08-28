"""Pasife alma iş kuralı: SERVER olarak domaine bağlı sertifika pasife ALINAMAZ (409).
Client/Trusted bağı engellemez. Server bağı halefe devredilince pasife alınabilir."""

from datetime import datetime

from tests import certgen


def _import(client, h, pem_text, *, supersede=False):
    return client.post("/api/certificates/import", headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")},
                       data={"supersede": "true"} if supersede else {})


def _leaf(r):
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _domain(client, h, name):
    return client.post("/api/domains", headers=h, json={"domain": name}).json()["id"]


def _attach(client, h, dom, cid, mapping_type):
    r = client.post(f"/api/domains/{dom}/certificates", headers=h,
                    json={"certificate_id": cid, "mapping_type": mapping_type})
    assert r.status_code == 200, r.text


def _deactivate(client, h, cid):
    return client.post(f"/api/certificates/{cid}/deactivate", headers=h)


def _is_active(client, h, cid):
    return client.get(f"/api/certificates/{cid}", headers=h).json()["is_active"]


def test_server_bound_cannot_deactivate_via_endpoint(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("CA deact-srv")
    leaf, _ = certgen.make_leaf(ca, ca_key, "deact-srv.test", not_before=datetime(2026, 1, 1))
    cid = _leaf(_import(client, h, certgen.pem(leaf) + certgen.pem(ca)))
    _attach(client, h, _domain(client, h, "deact-srv.test"), cid, "server")

    r = _deactivate(client, h, cid)
    assert r.status_code == 409, r.text
    assert "SERVER" in r.json()["detail"]
    assert _is_active(client, h, cid) is True, "server-bağlı cert aktif kalmalı"


def test_server_bound_cannot_deactivate_via_put(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("CA deact-put")
    leaf, _ = certgen.make_leaf(ca, ca_key, "deact-put.test", not_before=datetime(2026, 1, 1))
    cid = _leaf(_import(client, h, certgen.pem(leaf) + certgen.pem(ca)))
    _attach(client, h, _domain(client, h, "deact-put.test"), cid, "server")

    r = client.put(f"/api/certificates/{cid}", headers=h, json={"is_active": False})
    assert r.status_code == 409, r.text
    assert _is_active(client, h, cid) is True, "PUT is_active=false de server-bağlıyken engellenmeli"


def test_client_bound_can_deactivate(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("CA deact-cli")
    leaf, _ = certgen.make_leaf(ca, ca_key, "deact-cli.test", not_before=datetime(2026, 1, 1))
    cid = _leaf(_import(client, h, certgen.pem(leaf) + certgen.pem(ca)))
    _attach(client, h, _domain(client, h, "deact-cli.test"), cid, "client")  # server DEĞİL

    assert _deactivate(client, h, cid).status_code == 200
    assert _is_active(client, h, cid) is False, "client-bağlı cert pasife alınabilmeli"


def test_trusted_bound_can_deactivate(client, auth_headers):
    h = auth_headers
    tid = client.post("/api/teams", headers=h,
                      json={"name": "Deact-Trust-SY", "type": "SY", "email": "dt@t"}).json()["id"]
    app_id = client.post("/api/applications", headers=h,
                         json={"app_name": "DeactTrustApp", "server_name": "x",
                               "sy_team_id": tid}).json()["id"]
    ca, ca_key = certgen.make_ca("CA deact-tr")
    leaf, _ = certgen.make_leaf(ca, ca_key, "deact-tr.test", not_before=datetime(2026, 1, 1))
    cid = _leaf(_import(client, h, certgen.pem(leaf) + certgen.pem(ca)))
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": cid}).status_code == 200  # yalnız trusted

    assert _deactivate(client, h, cid).status_code == 200
    assert _is_active(client, h, cid) is False, "trusted-bağlı cert pasife alınabilmeli"


def test_deactivatable_after_server_binding_transferred(client, auth_headers):
    """Server bağı halefe devredilince eski cert artık server-bağsız → pasife alınabilir."""
    h = auth_headers
    ca, ca_key = certgen.make_ca("CA deact-xfer")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "deact-xfer.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "deact-xfer.test", key=key, not_before=datetime(2026, 6, 1))
    v1_id = _leaf(_import(client, h, certgen.pem(v1) + certgen.pem(ca)))
    dom = _domain(client, h, "deact-xfer.test")
    _attach(client, h, dom, v1_id, "server")

    # devir öncesi: server-bağlı → 409
    assert _deactivate(client, h, v1_id).status_code == 409

    v2_id = _leaf(_import(client, h, certgen.pem(v2), supersede=True))
    p = next(p for p in client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
             if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id)
    assert client.post(f"/api/proposals/{p['id']}/approve", headers=h).status_code == 200

    # devir sonrası: v1 artık server-bağsız → pasife alınabilir
    assert _deactivate(client, h, v1_id).status_code == 200
    assert _is_active(client, h, v1_id) is False
