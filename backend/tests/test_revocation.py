"""İptal (revocation) OCSP/CRL denetimi testleri.

Kapsam: GERÇEK OCSP yanıtı (GOOD/REVOKED) ve CRL üretip check_ocsp/check_crl parse'ını doğrular;
uç/issuer yoksa 'unknown' (graceful); ağ hatası → 'unknown'; endpoint durumu kaydeder; gece işi
enabled=False iken atlar; yetki (revocation-check editor+, batch admin-only).

Egress yapılmaz: httpx istemcisi sahte (_FakeClient) ile değiştirilir.
"""

from datetime import datetime, timedelta

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509 import ocsp

from app.db.models import Certificate
from app.db.session import SessionLocal
from app.services import revocation
from tests import certgen


class _FakeResp:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class _FakeClient:
    """httpx.Client yerine: post/get sabit içerik döner ya da verilen istisnayı fırlatır."""
    def __init__(self, content: bytes = b"", exc: Exception | None = None):
        self._content = content
        self._exc = exc

    def post(self, url, content=None, headers=None):
        if self._exc:
            raise self._exc
        return _FakeResp(self._content)

    def get(self, url):
        if self._exc:
            raise self._exc
        return _FakeResp(self._content)

    def close(self):
        return None


def _x509(cert) -> x509.Certificate:
    return x509.load_pem_x509_certificate(certgen.pem(cert).encode())


def _ocsp_der(leaf, issuer, issuer_key, status: ocsp.OCSPCertStatus) -> bytes:
    now = datetime(2026, 6, 1)
    revoked = status == ocsp.OCSPCertStatus.REVOKED
    b = (ocsp.OCSPResponseBuilder()
         .add_response(cert=leaf, issuer=issuer, algorithm=hashes.SHA1(), cert_status=status,
                       this_update=now, next_update=now + timedelta(days=1),
                       revocation_time=(now - timedelta(days=10)) if revoked else None,
                       revocation_reason=(x509.ReasonFlags.key_compromise) if revoked else None)
         .responder_id(ocsp.OCSPResponderEncoding.NAME, issuer))
    return b.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def _crl_der(issuer, issuer_key, revoked_serials: list[int]) -> bytes:
    now = datetime(2026, 6, 1)
    b = (x509.CertificateRevocationListBuilder()
         .issuer_name(issuer.subject).last_update(now).next_update(now + timedelta(days=7)))
    for serial in revoked_serials:
        b = b.add_revoked_certificate(
            x509.RevokedCertificateBuilder().serial_number(serial).revocation_date(now).build())
    return b.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


# ---- OCSP parse ----
def test_check_ocsp_good_and_revoked():
    ca, ck = certgen.make_ca("Rev CA")
    leaf, _ = certgen.make_leaf(ca, ck, "rev.example")
    leaf_x, issuer_x = _x509(leaf), _x509(ca)

    good = _ocsp_der(leaf_x, issuer_x, ck, ocsp.OCSPCertStatus.GOOD)
    assert revocation.check_ocsp(leaf_x, issuer_x, "http://ocsp", _FakeClient(good))[0] == "good"

    revoked = _ocsp_der(leaf_x, issuer_x, ck, ocsp.OCSPCertStatus.REVOKED)
    status, detail = revocation.check_ocsp(leaf_x, issuer_x, "http://ocsp", _FakeClient(revoked))
    assert status == "revoked"
    assert detail.get("reason") == "key_compromise"


def test_check_ocsp_network_error_is_unknown():
    ca, ck = certgen.make_ca("Rev CA2")
    leaf, _ = certgen.make_leaf(ca, ck, "rev2.example")
    st, _ = revocation.check_ocsp(_x509(leaf), _x509(ca), "http://ocsp",
                                  _FakeClient(exc=httpx.ConnectError("blocked")))
    assert st == "unknown"


# ---- CRL parse ----
def test_check_crl_good_and_revoked():
    ca, ck = certgen.make_ca("CRL CA")
    leaf, _ = certgen.make_leaf(ca, ck, "crl.example")
    leaf_x, issuer_x = _x509(leaf), _x509(ca)

    revoked_der = _crl_der(issuer_x, ck, [leaf_x.serial_number])
    assert revocation.check_crl(leaf_x, "http://crl", _FakeClient(revoked_der))[0] == "revoked"

    good_der = _crl_der(issuer_x, ck, [])
    assert revocation.check_crl(leaf_x, "http://crl", _FakeClient(good_der))[0] == "good"


# ---- orchestration: uç yoksa unknown (certgen leaf'inde AIA/CRL yok) ----
def test_check_certificate_unknown_without_endpoints():
    ca, ck = certgen.make_ca("Plain CA")
    leaf, _ = certgen.make_leaf(ca, ck, "plain.example")
    cert = Certificate(pem_certificate=certgen.pem(leaf), cert_type="leaf")
    db = SessionLocal()
    try:
        status, _ = revocation.check_certificate(db, cert, _FakeClient(), {"method": "ocsp_then_crl"})
    finally:
        db.close()
    assert status == "unknown"


# ---- endpoint + kalıcılık + yetki ----
def _import(client, headers, pem_text):
    files = {"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")}
    assert client.post("/api/certificates/import", headers=headers, files=files).status_code == 200


def _mk_user(client, admin, username, role):
    assert client.post("/api/users", headers=admin, json={
        "username": username, "password": "pw12345", "role": role,
        "auth_source": "local"}).status_code == 200


def _login(client, username):
    r = client.post("/api/auth/login-json", json={"username": username, "password": "pw12345"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_revocation_endpoint_persists_and_auth(client, auth_headers, monkeypatch):
    # Gerçek egress gerekmesin: check_certificate'i sabit 'good' döndür.
    monkeypatch.setattr(revocation, "check_certificate",
                        lambda db, cert, cl, config: ("good", {"method": "ocsp"}))
    ca, ck = certgen.make_ca("EP CA")
    leaf, _ = certgen.make_leaf(ca, ck, "endpoint.example")
    _import(client, auth_headers, certgen.pem(leaf) + certgen.pem(ca))
    cid = next(c["id"] for c in client.get("/api/certificates", headers=auth_headers).json()
               if c["name"] == "endpoint.example")

    r = client.post(f"/api/certificates/{cid}/revocation-check", headers=auth_headers)
    assert r.status_code == 200 and r.json()["revocation_status"] == "good"
    detail = client.get(f"/api/certificates/{cid}", headers=auth_headers).json()
    assert detail["revocation_status"] == "good" and detail["revocation_checked_at"]

    # yetki: viewer denetleyemez (editor+); batch admin-only
    _mk_user(client, auth_headers, "rev_viewer", "viewer")
    _mk_user(client, auth_headers, "rev_editor", "editor")
    vh, eh = _login(client, "rev_viewer"), _login(client, "rev_editor")
    assert client.post(f"/api/certificates/{cid}/revocation-check", headers=vh).status_code == 403
    assert client.post(f"/api/certificates/{cid}/revocation-check", headers=eh).status_code == 200
    assert client.post("/api/certificates/revocation-run", headers=eh).status_code == 403
    assert client.post("/api/certificates/revocation-run", headers=auth_headers).status_code == 200


def test_revocation_job_skips_when_disabled(client, monkeypatch):
    called: list[int] = []
    monkeypatch.setattr(revocation, "run_check",
                        lambda *a, **k: called.append(1) or ("good", {}))
    revocation.check_all_certificates()  # revocation.enabled varsayılan False → run_check çağrılmamalı
    assert called == []
