"""Canlı doğrulama ek kontrolleri: DNS kaydı, Çoklu IP, CAA, OCSP Stapling.

Gerçek ağa çıkılmaz: TLS sunucuları 127.0.0.1/127.0.0.2 üzerinde çalışma anında açılır, DNS
yanıtları (A/AAAA, CAA) sahte fonksiyonlarla verilir. OCSP Stapling için sunucu pyOpenSSL ile
gerçek bir OCSP yanıtını el sıkışmada gönderir."""

import json
import socket
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID
from OpenSSL import SSL

from app.services import endpoint_checks, live_check
from app.services.cert_parser import parse_x509
from tests import certgen


@pytest.fixture
def checks_on(monkeypatch):
    monkeypatch.setattr(endpoint_checks, "ENABLED", True)


def _leaf(cn, ca, ca_key, ocsp_url=None, issuer_name=None):
    key = certgen.make_key()
    nb = datetime.utcnow() - timedelta(days=1)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
         .issuer_name(issuer_name or ca.subject)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(nb).not_valid_after(nb + timedelta(days=300))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False))
    if ocsp_url:
        b = b.add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(
            AuthorityInformationAccessOID.OCSP, x509.UniformResourceIdentifier(ocsp_url))]), critical=False)
    return b.sign(ca_key, hashes.SHA256()), key


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextmanager
def _server(addr, port, cert, key, staple: bytes | None = None):
    """pyOpenSSL TLS sunucusu; `staple` verilirse istemci isteyince OCSP yanıtını el sıkışmada yollar."""
    ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
    ctx.use_certificate(cert)
    ctx.use_privatekey(key)
    if staple is not None:
        ctx.set_ocsp_server_callback(lambda conn, data: staple)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((addr, port))
    srv.listen(5)
    stop = threading.Event()

    def serve():
        srv.settimeout(0.3)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                conn.settimeout(None)  # pyOpenSSL: zaman aşımlı soket bloklamayan davranır
                tls = SSL.Connection(ctx, conn)
                tls.set_accept_state()
                tls.do_handshake()
                tls.shutdown()
            except Exception:
                pass
            finally:
                conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)
        srv.close()


def _ocsp_good(leaf, ca, ca_key, next_update=None):
    now = datetime.utcnow()
    b = (ocsp.OCSPResponseBuilder()
         .add_response(cert=leaf, issuer=ca, algorithm=hashes.SHA1(),
                       cert_status=ocsp.OCSPCertStatus.GOOD, this_update=now - timedelta(hours=1),
                       next_update=next_update or now + timedelta(days=3),
                       revocation_time=None, revocation_reason=None)
         .responder_id(ocsp.OCSPResponderEncoding.HASH, ca))
    return b.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


# ---- Çoklu IP ----
def test_multi_ip_detects_server_with_other_cert():
    ca, ca_key = certgen.make_ca("Multi IP CA")
    new, new_key = _leaf("multi.test", ca, ca_key)
    old, old_key = _leaf("multi.test", ca, ca_key)
    port = _free_port()
    with _server("127.0.0.1", port, new, new_key), _server("127.0.0.2", port, old, old_key):
        new_fp = parse_x509(new).fingerprint_sha256
        res = endpoint_checks.check_multi_ip("multi.test", port, ["127.0.0.1", "127.0.0.2"], new_fp, {new_fp})
        assert res["status"] == "different"
        assert [r["result"] for r in res["ips"]] == ["same", "different"]
        assert "127.0.0.2" in res["note"]
        # Eski sertifika hâlâ domaine bağlıysa (ör. yenileme talebi bekliyor) kırmızı sayılmaz
        old_fp = parse_x509(old).fingerprint_sha256
        res2 = endpoint_checks.check_multi_ip("multi.test", port, ["127.0.0.1", "127.0.0.2"], new_fp,
                                              {new_fp, old_fp})
        assert res2["status"] == "same" and res2["ips"][1]["result"] == "other_bound"


def test_multi_ip_single_ip_and_unreachable():
    assert endpoint_checks.check_multi_ip("x.test", 443, ["10.0.0.1"], "fp", set()) is None
    ca, ca_key = certgen.make_ca("Multi IP CA 2")
    leaf, key = _leaf("multi2.test", ca, ca_key)
    port = _free_port()
    with _server("127.0.0.1", port, leaf, key):
        fp = parse_x509(leaf).fingerprint_sha256
        res = endpoint_checks.check_multi_ip("multi2.test", port, ["127.0.0.1", "127.0.0.3"], fp, {fp})
    assert res["status"] == "same"
    assert res["ips"][1]["result"] == "unreachable"
    assert "bağlanılamadı" in res["note"]


# ---- CAA ----
def _issuer(org):
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                      x509.NameAttribute(NameOID.COMMON_NAME, f"{org} TLS RSA CA")])


def test_caa_allowed_not_allowed_none(monkeypatch):
    ca, ca_key = certgen.make_ca("CAA CA")
    leaf, _ = _leaf("www.caa.test", ca, ca_key, issuer_name=_issuer("DigiCert Inc"))

    monkeypatch.setattr(endpoint_checks, "_caa_lookup",
                        lambda h: ("caa.test", [(0, "issue", "digicert.com"), (0, "iodef", "mailto:x@caa.test")], True))
    r = endpoint_checks.check_caa("www.caa.test", leaf)
    assert r["status"] == "allowed" and r["domain"] == "caa.test"

    monkeypatch.setattr(endpoint_checks, "_caa_lookup",
                        lambda h: ("caa.test", [(0, "issue", "letsencrypt.org")], True))
    r = endpoint_checks.check_caa("www.caa.test", leaf)
    assert r["status"] == "not_allowed" and "letsencrypt.org" in r["note"]

    monkeypatch.setattr(endpoint_checks, "_caa_lookup", lambda h: (None, [], True))
    assert endpoint_checks.check_caa("www.caa.test", leaf)["status"] == "none"
    monkeypatch.setattr(endpoint_checks, "_caa_lookup", lambda h: (None, [], False))
    assert endpoint_checks.check_caa("www.caa.test", leaf)["status"] == "unknown"
    # issue ";" → hiçbir CA'ya izin yok
    monkeypatch.setattr(endpoint_checks, "_caa_lookup", lambda h: ("caa.test", [(0, "issue", ";")], True))
    assert endpoint_checks.check_caa("www.caa.test", leaf)["status"] == "not_allowed"


def test_caa_wildcard_uses_issuewild_and_brand_alias(monkeypatch):
    ca, ca_key = certgen.make_ca("CAA CA 2")
    key = certgen.make_key()
    nb = datetime.utcnow()
    wild = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "*.caa.test")]))
            .issuer_name(_issuer("Sectigo Limited")).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(nb).not_valid_after(nb + timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("*.caa.test")]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    monkeypatch.setattr(endpoint_checks, "_caa_lookup", lambda h: (
        "caa.test", [(0, "issue", "digicert.com"), (0, "issuewild", "comodoca.com")], True))
    r = endpoint_checks.check_caa("api.caa.test", wild)
    assert r["status"] == "allowed" and r["allowed"] == ["comodoca.com"]


# ---- OCSP Stapling ----
def test_ocsp_stapling_states():
    ca, ca_key = certgen.make_ca("Stapling CA")
    port = _free_port()
    leaf, key = _leaf("staple.test", ca, ca_key, ocsp_url="http://ocsp.staple.test")
    with _server("127.0.0.1", port, leaf, key, staple=_ocsp_good(leaf, ca, ca_key)):
        r = endpoint_checks.check_ocsp_stapling("127.0.0.1", port, leaf)
    assert r["status"] == "stapled" and r["cert_status"] == "good"

    port2 = _free_port()
    with _server("127.0.0.1", port2, leaf, key):
        r = endpoint_checks.check_ocsp_stapling("127.0.0.1", port2, leaf)
    assert r["status"] == "not_stapled"

    port3 = _free_port()
    old = _ocsp_good(leaf, ca, ca_key, next_update=datetime.utcnow() - timedelta(minutes=5))
    with _server("127.0.0.1", port3, leaf, key, staple=old):
        r = endpoint_checks.check_ocsp_stapling("127.0.0.1", port3, leaf)
    assert r["status"] == "stale"

    no_ocsp, _ = _leaf("noocsp.test", ca, ca_key)
    assert endpoint_checks.check_ocsp_stapling("127.0.0.1", 1, no_ocsp)["status"] == "not_applicable"


# ---- DNS ----
def test_dns_check_and_skip_rules(monkeypatch):
    monkeypatch.setattr(endpoint_checks.socket, "getaddrinfo",
                        lambda h, p, type=0: [(0, 0, 0, "", ("10.1.1.1", 0)), (0, 0, 0, "", ("10.1.1.1", 0)),
                                              (0, 0, 0, "", ("10.1.1.2", 0))])
    r = endpoint_checks.check_dns("dns.test")
    assert r["status"] == "ok" and r["ips"] == ["10.1.1.1", "10.1.1.2"]

    def fail(*a, **k):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(endpoint_checks.socket, "getaddrinfo", fail)
    assert endpoint_checks.check_dns("yok.test")["status"] == "missing"
    # IP ve tek etiketli adlarda DNS kontrolü yapılmaz
    monkeypatch.setattr(endpoint_checks, "ENABLED", True)
    assert endpoint_checks.dns_only("10.0.0.1") is None
    assert endpoint_checks.dns_only("localhost") is None
    assert endpoint_checks.dns_only("yok.test")["status"] == "missing"


# ---- uçtan uca: domain canlı doğrulaması ----
def _import(client, headers, pem_text):
    r = client.post("/api/certificates/import", headers=headers,
                    files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def test_live_check_includes_extra_checks_and_flags_stray_ip(client, auth_headers, monkeypatch, checks_on):
    ca, ca_key = certgen.make_ca("E2E Multi CA")
    new, new_key = _leaf("e2e-multi.test", ca, ca_key, ocsp_url="http://ocsp.e2e.test")
    old, old_key = _leaf("e2e-multi.test", ca, ca_key)
    port = _free_port()
    d = client.post("/api/domains", headers=auth_headers, json={"domain": f"e2e-multi.test:{port}"}).json()
    cid = _import(client, auth_headers, certgen.pem(new))
    client.post(f"/api/domains/{d['id']}/certificates", headers=auth_headers,
                json={"certificate_id": cid, "mapping_type": "server"})

    monkeypatch.setattr(live_check, "fetch_served_chain",
                        lambda host, port: [live_check.fetch_leaf_via("127.0.0.1", host, port)])
    monkeypatch.setattr(endpoint_checks, "check_dns",
                        lambda h: {"status": "ok", "ips": ["127.0.0.1", "127.0.0.2"], "note": "DNS kaydı var"})
    monkeypatch.setattr(endpoint_checks, "_caa_lookup", lambda h: (None, [], True))
    monkeypatch.setattr(endpoint_checks, "_fetch_stapled",
                        lambda host, port, address=None: _ocsp_good(new, ca, ca_key))

    with _server("127.0.0.1", port, new, new_key), _server("127.0.0.2", port, old, old_key):
        r = client.post(f"/api/domains/{d['id']}/live-check", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    detail = json.loads(body["live_check_detail"])
    assert body["live_check_status"] == "mismatch"
    assert detail["multi_ip"]["status"] == "different"
    assert "127.0.0.2" in detail["reason"]
    assert detail["dns"]["status"] == "ok"
    assert detail["caa"]["status"] == "none"
    assert detail["ocsp_stapling"]["status"] == "stapled"

    # Tek IP: aynı sertifika → yeşil kalır, ek kontroller yine eklenir
    monkeypatch.setattr(endpoint_checks, "check_dns",
                        lambda h: {"status": "ok", "ips": ["127.0.0.1"], "note": "DNS kaydı var"})
    with _server("127.0.0.1", port, new, new_key):
        r = client.post(f"/api/domains/{d['id']}/live-check", headers=auth_headers)
    detail = json.loads(r.json()["live_check_detail"])
    assert r.json()["live_check_status"] == "match"
    assert "multi_ip" not in detail and detail["caa"]["status"] == "none"


def test_unreachable_reports_missing_dns(client, auth_headers, monkeypatch, checks_on):
    d = client.post("/api/domains", headers=auth_headers, json={"domain": "silinmis-kayit.test"}).json()

    def fail(host, port):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(live_check, "fetch_served_chain", fail)
    monkeypatch.setattr(endpoint_checks, "check_dns",
                        lambda h: {"status": "missing", "ips": [], "note": "DNS'te bulunamadı"})
    r = client.post(f"/api/domains/{d['id']}/live-check", headers=auth_headers)
    detail = json.loads(r.json()["live_check_detail"])
    assert r.json()["live_check_status"] == "unreachable"
    assert detail["dns"]["status"] == "missing"
