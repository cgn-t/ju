"""Sertifika detayındaki PEM'den okunan ek bilgiler (SPKI pin, doğrulama tipi, OCSP/CRL, KU, BC, SCT)."""

import base64
import hashlib
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from app.services.cert_extras import pem_extras
from tests.certgen import make_ca, make_key, pem


def _leaf_with_extensions(ca, ca_key):
    key = make_key()
    now = datetime(2026, 1, 1)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ext.ornek.local")]))
            .issuer_name(ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=200))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.CertificatePolicies([x509.PolicyInformation(x509.ObjectIdentifier("2.23.140.1.2.2"), None)]),
                           critical=False)
            .add_extension(x509.AuthorityInformationAccess([
                x509.AccessDescription(AuthorityInformationAccessOID.OCSP, x509.UniformResourceIdentifier("http://ocsp.ornek.local")),
                x509.AccessDescription(AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier("http://ca.ornek.local/ca.crt")),
            ]), critical=False)
            .add_extension(x509.CRLDistributionPoints([x509.DistributionPoint(
                [x509.UniformResourceIdentifier("http://crl.ornek.local/ca.crl")], None, None, None)]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return cert, key


def test_pem_extras_reads_all_fields():
    ca, ca_key = make_ca("Ext Test CA")
    cert, key = _leaf_with_extensions(ca, ca_key)
    e = pem_extras(pem(cert))
    spki = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    assert e["spki_pin_sha256"] == base64.b64encode(hashlib.sha256(spki).digest()).decode()
    assert e["validation_type"] == "OV"
    assert e["ocsp_urls"] == ["http://ocsp.ornek.local"]
    assert e["ca_issuers_urls"] == ["http://ca.ornek.local/ca.crt"]
    assert e["crl_urls"] == ["http://crl.ornek.local/ca.crl"]
    assert e["key_usage"] == ["digitalSignature", "keyEncipherment"]
    assert e["basic_constraints_ca"] is False
    assert e["sct_count"] == 0
    assert e["signature_algorithm"] == "sha256WithRSAEncryption"


def test_pem_extras_ca_and_missing_pem():
    ca, _ = make_ca("Ext Root CA")
    e = pem_extras(pem(ca))
    assert e["basic_constraints_ca"] is True
    assert e["validation_type"] is None and e["ocsp_urls"] == []
    assert pem_extras(None) is None
    assert pem_extras("bozuk") is None


def test_certificate_detail_returns_extras(client, auth_headers):
    ca, ca_key = make_ca("Ext API CA")
    cert, _ = _leaf_with_extensions(ca, ca_key)
    r = client.post("/api/certificates/import", headers=auth_headers,
                    files={"file": ("c.pem", pem(cert))}, data={"creator": "", "environment": "prod"})
    assert r.status_code == 200, r.text
    cid = next(c["id"] for c in client.get("/api/certificates", headers=auth_headers).json()
               if c["name"] == "ext.ornek.local")
    d = client.get(f"/api/certificates/{cid}", headers=auth_headers).json()
    assert d["extras"]["validation_type"] == "OV"
    assert d["extras"]["crl_urls"] == ["http://crl.ornek.local/ca.crl"]
