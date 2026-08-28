"""Canlı doğrulama testleri: gerçek bir TLS sunucusu ayağa kaldırıp
leaf sertifikayı sunar, live-check'in match/mismatch/unreachable durumlarını doğrular.

Sunulan sertifika ÇALIŞMA ANINDA `certgen` ile üretilir (statik bir fixture dosyası
DEĞİL) — böylece geçerlilik penceresi her zaman "şu an"a göre ayarlanır ve zaman
ilerledikçe (fixture sertifikasının süresi dolarak) test kırılmaz."""

import socket
import ssl
import threading
from datetime import datetime, timedelta

import pytest

from app.services.live_check import parse_target
from tests import certgen


def test_parse_target_variants():
    assert parse_target("trade.aaakkk.com") == ("trade.aaakkk.com", 443)
    assert parse_target("xxx.aaakkk.com:8228(Bloomberg)") == ("xxx.aaakkk.com", 8228)
    assert parse_target("*.aaakkk.com")[0] is None
    assert parse_target("")[0] is None
    assert parse_target("host.aaakkk.com:bozukport") == ("host.aaakkk.com", 443)


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """Çalışma anında üretilen bir leaf sertifikayı sunan minimal TLS sunucusu.
    (port, sertifika_pem) döner — testler bu PEM'i JUMBO'ya kendileri import eder
    (paylaşılan test DB'sindeki başka bir testin sertifikasına bağımlı olmaz)."""
    ca, ca_key = certgen.make_ca("Live Check Test CA")
    leaf, leaf_key = certgen.make_leaf(
        ca, ca_key, "live-check-test.local",
        not_before=datetime.utcnow() - timedelta(days=1), days=3650,
        san=["live-check-test.local"])
    leaf_pem = certgen.pem(leaf)

    cert_dir = tmp_path_factory.mktemp("tls_server_certs")
    cert_path = cert_dir / "leaf.pem"
    key_path = cert_dir / "leaf.key"
    cert_path.write_text(leaf_pem)
    key_path.write_text(certgen.key_pem(leaf_key))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
    stop = threading.Event()

    def serve():
        server.settimeout(0.3)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                context.wrap_socket(conn, server_side=True).close()
            except Exception:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port, leaf_pem
    stop.set()
    thread.join(timeout=2)
    server.close()


def _make_domain(client, auth_headers, name):
    r = client.post("/api/domains", headers=auth_headers, json={"domain": name})
    assert r.status_code == 200
    return r.json()["id"]


def _import_pem(client, auth_headers, filename, pem_text):
    r = client.post("/api/certificates/import", headers=auth_headers,
                    files={"file": (filename, pem_text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def test_live_check_match(client, auth_headers, tls_server):
    port, served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port}")
    # Sunucunun SUNDUĞU sertifikayı BİZZAT import ediyoruz — "envanterdeki ilk leaf'i al"
    # gibi kırılgan bir varsayıma değil, doğrudan aynı sertifikaya bağlıyız.
    leaf_id = _import_pem(client, auth_headers, "served-leaf.pem", served_pem)
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": leaf_id, "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["live_check_status"] == "match"
    assert "matched_certificate" in (r.json()["live_check_detail"] or "")


def test_live_check_mismatch(client, auth_headers, tls_server):
    port, _served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port}(yanlis-esleme)")
    # Sunulandan FARKLI, bu teste özel taze bir sertifika üretip eşliyoruz — paylaşılan
    # DB'de "herhangi bir root sertifika var mı" varsayımına bağımlı olmadan.
    other_ca, other_ca_key = certgen.make_ca("Mismatch Test CA")
    other_leaf, _ = certgen.make_leaf(other_ca, other_ca_key, "other-cert.local",
                                      not_before=datetime.utcnow(), days=365,
                                      san=["other-cert.local"])
    other_id = _import_pem(client, auth_headers, "other.pem", certgen.pem(other_leaf))
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": other_id, "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "mismatch"


def test_live_check_no_mapping(client, auth_headers, tls_server):
    port, _served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port} (eslemesiz)")
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "no_mapping"


def test_live_check_unreachable(client, auth_headers):
    domain_id = _make_domain(client, auth_headers, "127.0.0.1:1")  # kapalı port
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "unreachable"


def test_live_check_wildcard_not_checkable(client, auth_headers):
    domain_id = _make_domain(client, auth_headers, "*.jumbo-test.com")
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "not_checkable"
