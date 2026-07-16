"""Bellek içi test sertifikası üretimi.

Yenileme senaryoları için: aynı anahtar verilirse aynı SKI'li ikinci sertifika
(anahtar korunarak yenileme), verilmezse aynı subject+issuer / yeni anahtar
(tipik Vault rotasyonu) üretilebilir.
"""

from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509.oid import NameOID


def make_key(bits: int = 2048):
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn: str, key=None, not_before: datetime | None = None, days: int = 3650, sig_hash=None):
    key = key or make_key()
    nb = not_before or datetime(2026, 1, 1)
    cert = (x509.CertificateBuilder()
            .subject_name(_name(cn)).issuer_name(_name(cn))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(nb).not_valid_after(nb + timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                           critical=False)
            .sign(key, sig_hash or hashes.SHA256()))
    return cert, key


def make_leaf(ca_cert, ca_key, cn: str, key=None, not_before: datetime | None = None,
              days: int = 397, san: list[str] | None = None, sig_hash=None):
    key = key or make_key()
    nb = not_before or datetime(2026, 1, 1)
    builder = (x509.CertificateBuilder()
               .subject_name(_name(cn)).issuer_name(ca_cert.subject)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(nb).not_valid_after(nb + timedelta(days=days))
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                              critical=False)
               .add_extension(
                   x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                   critical=False))
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in san]), critical=False)
    return builder.sign(ca_key, sig_hash or hashes.SHA256()), key


def pem(cert) -> str:
    return cert.public_bytes(Encoding.PEM).decode()


def key_pem(key) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
