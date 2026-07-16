"""Canlı doğrulama testleri: gerçek bir TLS sunucusu ayağa kaldırıp
leaf sertifikayı sunar, live-check'in match/mismatch/unreachable durumlarını doğrular."""

import socket
import ssl
import threading
from pathlib import Path

import pytest

from app.services.live_check import parse_target

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_target_variants():
    assert parse_target("trade.aaakkk.com") == ("trade.aaakkk.com", 443)
    assert parse_target("xxx.aaakkk.com:8228(Bloomberg)") == ("xxx.aaakkk.com", 8228)
    assert parse_target("*.aaakkk.com")[0] is None
    assert parse_target("")[0] is None
    assert parse_target("host.aaakkk.com:bozukport") == ("host.aaakkk.com", 443)


@pytest.fixture(scope="module")
def tls_server():
    """tests/fixtures leaf sertifikasını sunan minimal TLS sunucusu."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(FIXTURES / "leaf.pem", FIXTURES / "leaf.key")
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
    yield port
    stop.set()
    thread.join(timeout=2)
    server.close()


def _make_domain(client, auth_headers, name):
    r = client.post("/api/domains", headers=auth_headers, json={"domain": name})
    assert r.status_code == 200
    return r.json()["id"]


def test_live_check_match(client, auth_headers, tls_server):
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{tls_server}")
    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf")
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": leaf["id"], "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["live_check_status"] == "match"
    assert "matched_certificate" in (r.json()["live_check_detail"] or "")


def test_live_check_mismatch(client, auth_headers, tls_server):
    # Root'u server olarak eşle — sunulan leaf ile uyuşmamalı
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{tls_server}(yanlis-esleme)")
    root = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "root")
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": root["id"], "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "mismatch"


def test_live_check_no_mapping(client, auth_headers, tls_server):
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{tls_server} (eslemesiz)")
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
