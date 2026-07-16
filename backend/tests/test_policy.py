"""Sertifika uyum (politika) motoru testleri.

Kapsam: kural birimleri (weak_key/weak_signature/excessive_validity/untrusted_issuer, null=ihlal değil);
parse_x509 kripto çıkarımı (RSA/EC/Ed25519); rapor entegrasyonu (zayıf cert import → /policy/report);
yetki (rapor viewer+, config admin-only).

NOT: DB session-kapsamlı ve paylaşımlıdır → rapor TÜM aktif envanteri değerlendirir. Bu yüzden
entegrasyon iddiaları global toplamlara değil, BENİM sertifikalarımın ihlallerine bakar.
"""

from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import NameOID

from app.db.models import Certificate
from app.services import policy
from app.services.cert_parser import parse_x509
from tests import certgen

BASE_CFG = {"enabled": True, "enforce_ca_allowlist": False, "ca_allowlist": [],
            "min_rsa_bits": 2048, "min_ec_bits": 256, "banned_sig_hashes": ["sha1", "md5"],
            "max_validity_days": 398}


def _cert(**kw) -> Certificate:
    """DB'siz (transient) sentetik sertifika — evaluate_certificate saf okur."""
    d = dict(cert_type="leaf", issuer="CN=Some CA", public_key_type="RSA", key_size=2048,
             signature_hash="sha256", valid_from=datetime(2026, 1, 1), valid_to=datetime(2027, 1, 1))
    d.update(kw)
    return Certificate(**d)


def _rules(cert, cfg=BASE_CFG):
    return {v["rule"] for v in policy.evaluate_certificate(cert, cfg)}


# ---- kural birimleri ----
def test_weak_rsa_key():
    assert "weak_key" in _rules(_cert(key_size=1024))
    assert "weak_key" not in _rules(_cert(key_size=2048))


def test_weak_ec_key():
    assert "weak_key" in _rules(_cert(public_key_type="EC", key_size=192))
    assert "weak_key" not in _rules(_cert(public_key_type="EC", key_size=256))


def test_weak_signature():
    assert "weak_signature" in _rules(_cert(signature_hash="sha1"))
    assert "weak_signature" in _rules(_cert(signature_hash="SHA1"))  # büyük/küçük duyarsız
    assert "weak_signature" not in _rules(_cert(signature_hash="sha256"))


def test_excessive_validity_leaf_only():
    long_leaf = _cert(valid_from=datetime(2026, 1, 1), valid_to=datetime(2030, 1, 1))
    assert "excessive_validity" in _rules(long_leaf)
    # CA meşru olarak uzun ömürlüdür → ihlal değil
    long_ca = _cert(cert_type="root", valid_from=datetime(2026, 1, 1), valid_to=datetime(2040, 1, 1))
    assert "excessive_validity" not in _rules(long_ca)


def test_untrusted_issuer():
    cfg = {**BASE_CFG, "enforce_ca_allowlist": True, "ca_allowlist": ["Trusted Root"]}
    assert "untrusted_issuer" in _rules(_cert(issuer="CN=Evil CA"), cfg)
    assert "untrusted_issuer" not in _rules(_cert(issuer="CN=Trusted Root CA"), cfg)
    # allowlist boşsa zorlanmaz; enforce kapalıysa hiç bakılmaz
    assert "untrusted_issuer" not in _rules(_cert(issuer="CN=X"),
                                            {**BASE_CFG, "enforce_ca_allowlist": True, "ca_allowlist": []})
    assert "untrusted_issuer" not in _rules(_cert(issuer="CN=Evil"), BASE_CFG)


def test_null_crypto_not_violation():
    """Kontrol edilmemiş (null) kripto alanları İHLAL DEĞİL (yanlış-pozitif önlemi)."""
    assert _rules(_cert(key_size=None, public_key_type=None, signature_hash=None)) == set()


# ---- parse_x509 kripto çıkarımı ----
def _selfsigned(key, cn: str, sig_hash):
    nb = datetime(2026, 1, 1)
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    return (x509.CertificateBuilder().subject_name(n).issuer_name(n)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(nb).not_valid_after(nb + timedelta(days=365))
            .sign(key, sig_hash))


def test_parse_extracts_rsa():
    ca, ck = certgen.make_ca("RSA CA")
    leaf, _ = certgen.make_leaf(ca, ck, "rsa.example")
    p = parse_x509(leaf)
    assert p.public_key_type == "RSA" and p.key_size == 2048 and p.signature_hash == "sha256"


def test_parse_extracts_ec_and_ed25519():
    p_ec = parse_x509(_selfsigned(ec.generate_private_key(ec.SECP256R1()), "ec.example", hashes.SHA256()))
    assert p_ec.public_key_type == "EC" and p_ec.key_size == 256 and p_ec.key_curve == "secp256r1"
    # Ed25519: imza özet algoritması YOK → signature_hash None (asla banned sayılmamalı)
    p_ed = parse_x509(_selfsigned(ed25519.Ed25519PrivateKey.generate(), "ed.example", None))
    assert p_ed.public_key_type == "Ed25519" and p_ed.signature_hash is None
    assert p_ed.key_size == 256


# ---- rapor entegrasyonu ----
def _import(client, headers, pem_text):
    files = {"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")}
    r = client.post("/api/certificates/import", headers=headers, files=files)
    assert r.status_code == 200, r.text


def test_report_flags_weak_certs(client, auth_headers):
    # NOT: SHA-1 İMZALAMA modern OpenSSL'de reddedilir → weak_signature yalnız birim testte; burada
    # uçtan-uca boru hattı weak_key (RSA-1024) ve excessive_validity (uzun ömür) ile doğrulanır.
    ca, ck = certgen.make_ca("Policy CA")
    weak_key_leaf, _ = certgen.make_leaf(ca, ck, "weakkey.example", key=certgen.make_key(1024))
    long_leaf, _ = certgen.make_leaf(ca, ck, "longlife.example", days=1500)  # >398 gün
    good_leaf, _ = certgen.make_leaf(ca, ck, "good.example")
    for c in (weak_key_leaf, long_leaf, good_leaf):
        _import(client, auth_headers, certgen.pem(c) + certgen.pem(ca))

    rep = client.get("/api/policy/report", headers=auth_headers).json()
    by_name = {v["name"]: v for v in rep["violations"]}
    assert "weak_key" in by_name["weakkey.example"]["rules"]
    assert "excessive_validity" in by_name["longlife.example"]["rules"]
    assert "good.example" not in by_name              # uyumlu → ihlal listesinde yok
    assert rep["rule_counts"].get("weak_key", 0) >= 1
    assert rep["enabled"] is True


def test_certificate_policy_endpoint(client, auth_headers):
    ca, ck = certgen.make_ca("Single CA")
    leaf, _ = certgen.make_leaf(ca, ck, "single1024.example", key=certgen.make_key(1024))
    _import(client, auth_headers, certgen.pem(leaf) + certgen.pem(ca))
    cid = next(c["id"] for c in client.get("/api/certificates", headers=auth_headers).json()
               if c["name"] == "single1024.example")
    r = client.get(f"/api/policy/certificates/{cid}", headers=auth_headers).json()
    assert r["compliant"] is False
    assert any(v["rule"] == "weak_key" for v in r["violations"])


# ---- yetki ----
def _mk_user(client, admin, username, role):
    assert client.post("/api/users", headers=admin, json={
        "username": username, "password": "pw12345", "role": role,
        "auth_source": "local"}).status_code == 200


def test_policy_auth_and_config(client, auth_headers):
    _mk_user(client, auth_headers, "pol_viewer", "viewer")
    r = client.post("/api/auth/login-json", json={"username": "pol_viewer", "password": "pw12345"})
    vh = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert client.get("/api/policy/report", headers=vh).status_code == 200      # rapor viewer+
    # config admin-only
    assert client.put("/api/settings/policy", headers=vh,
                      json={"min_rsa_bits": 3072}).status_code == 403
    assert client.put("/api/settings/policy", headers=auth_headers,
                      json={"min_rsa_bits": 3072}).status_code == 200
