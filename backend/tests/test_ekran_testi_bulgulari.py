"""Ekran testinde bulunan sorunlar (v3.8.9).

1. Anasayfa "Toplam Sertifika" pasife alınmış kayıtları saymaz.
2. Anasayfa süresi dolmuş SERTİFİKA sayısını ayrıca verir (domaine bağlı olmasa da).
3. Zincir çekilemeyince ham işletim sistemi mesajı yerine Türkçe açıklama döner.
4. Önizleme, üst sertifika aynı dosyadaysa "bulunamadı" demez.
5. Önizleme eskinin uygulama bağlantılarını da listeler (değişiklik talebi önerisinin kapsamı).
"""

import socket
import ssl
from datetime import datetime, timedelta

from app.db.models import Certificate
from app.db.session import SessionLocal
from app.services.live_check import describe_connection_error
from tests import certgen


def _import(client, h, pem_text):
    return client.post("/api/certificates/import", headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")})


def _preview(client, h, pem_text):
    r = client.post("/api/certificates/import/preview", headers=h,
                    files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return r.json()


def test_dashboard_counts_only_active_and_expired_certificates(client, auth_headers):
    h = auth_headers
    before = client.get("/api/dashboard", headers=h).json()

    ca, ca_key = certgen.make_ca("Dash CA")
    expired, _ = certgen.make_leaf(ca, ca_key, "dash-expired.test",
                                   not_before=datetime.now() - timedelta(days=400), days=30)
    r = _import(client, h, certgen.pem(expired) + certgen.pem(ca))
    assert r.status_code == 200, r.text
    after = client.get("/api/dashboard", headers=h).json()
    assert after["total_certificates"] == before["total_certificates"] + 2
    assert after["expired_certificates"] == before["expired_certificates"] + 1

    # Pasife alınan kayıt toplamdan ve süresi dolmuş sayısından düşer
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    with SessionLocal() as db:
        db.get(Certificate, leaf_id).is_active = False
        db.commit()
    final = client.get("/api/dashboard", headers=h).json()
    assert final["total_certificates"] == before["total_certificates"] + 1
    assert final["expired_certificates"] == before["expired_certificates"]


def test_connection_errors_are_explained_in_turkish():
    dns = describe_connection_error(socket.gaierror(8, "nodename nor servname provided, or not known"),
                                    "yok.ornek.local", 443)
    assert dns.startswith("'yok.ornek.local' adresi DNS'te bulunamadı")
    assert "Teknik ayrıntı" in dns  # ham mesaj destek için sonda korunur

    assert "zaman aşımı" in describe_connection_error(socket.timeout("timed out"), "a.test", 443)
    assert "reddetti" in describe_connection_error(ConnectionRefusedError(61, "refused"), "a.test", 8443)
    assert "TLS el sıkışması" in describe_connection_error(ssl.SSLError("wrong version"), "a.test", 443)
    assert describe_connection_error(RuntimeError("x"), "a.test", 443).startswith(
        "a.test:443 adresine bağlanılamadı")


def test_probe_chain_unreachable_message_is_turkish(client, auth_headers):
    r = client.post("/api/domains/probe-chain", headers=auth_headers,
                    json={"domain": "olmayan-adres.invalid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reachable"] is False
    assert "DNS'te bulunamadı" in body["error"], body["error"]


def test_preview_finds_parent_in_same_file(client, auth_headers):
    root, root_key = certgen.make_ca("Ayni Dosya Root")
    inter, inter_key = certgen.make_intermediate(root, root_key, "Ayni Dosya Intermediate")
    leaf, _ = certgen.make_leaf(inter, inter_key, "ayni-dosya.test")
    rows = {p["cert_type"]: p for p in _preview(
        client, auth_headers, certgen.pem(leaf) + certgen.pem(inter) + certgen.pem(root))}
    assert rows["leaf"]["resolved_parent_name"] == "Ayni Dosya Intermediate (bu dosyada)"
    assert rows["intermediate"]["resolved_parent_name"] == "Ayni Dosya Root (bu dosyada)"
    assert rows["leaf"]["resolved_parent_id"] is None  # henüz envanterde yok
    assert rows["root"]["resolved_parent_name"] is None


def test_preview_lists_app_bindings_of_predecessor(client, auth_headers):
    h = auth_headers
    tid = client.post("/api/teams", headers=h,
                      json={"name": "SY-Onizleme", "type": "SY", "email": "onizleme@test"}).json()["id"]
    app_id = client.post("/api/applications", headers=h,
                         json={"app_name": "OnizlemeApp", "server_name": "onizleme",
                               "sy_team_id": tid}).json()["id"]
    ca, ca_key = certgen.make_ca("Onizleme CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "onizleme.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "onizleme.test", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": v1_id}).status_code == 200

    row = _preview(client, h, certgen.pem(v2))[0]
    assert row["renewal_of_id"] == v1_id
    assert row["renewal_of_apps"] == ["OnizlemeApp (trust store)"]
