"""Regresyon test dokümanları için sahte (yalnız test amaçlı) X.509 sertifika materyali üretir.

backend/tests/certgen.py ile aynı yöntemi kullanır. Sertifikaların süresi dolduğunda
(leaf'ler ~397 gün geçerli) bu script yeniden çalıştırılarak materyal tazelenebilir:

    cd backend && .venv/bin/python ../docs/regresyon-sertifikalari/uret.py

Çıktılar bu script ile aynı klasöre yazılır. ÜRETİLEN HİÇBİR SERTİFİKA/ANAHTAR GERÇEK
DEĞİLDİR — yalnız JUMBO regresyon testlerinde manuel kullanım içindir.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.x509.oid import NameOID

OUT = Path(__file__).parent


def make_key(bits: int = 2048):
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn: str, key=None, not_before: datetime | None = None, days: int = 3650):
    key = key or make_key()
    nb = not_before or datetime(2026, 1, 1)
    cert = (x509.CertificateBuilder()
            .subject_name(_name(cn)).issuer_name(_name(cn))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(nb).not_valid_after(nb + timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return cert, key


def make_intermediate(root_cert, root_key, cn: str, key=None,
                      not_before: datetime | None = None, days: int = 1825):
    """Root'un imzaladığı bir ara CA — leaf'ler buna karşı imzalanabilir (gerçek 3-seviye zincir)."""
    key = key or make_key()
    nb = not_before or datetime(2026, 1, 1)
    cert = (x509.CertificateBuilder()
            .subject_name(_name(cn)).issuer_name(root_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(nb).not_valid_after(nb + timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
                critical=False)
            .sign(root_key, hashes.SHA256()))
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
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
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


def write(name: str, content: str):
    (OUT / name).write_text(content)
    print(f"  {name}")


def main():
    print("Kök CA...")
    ca, ca_key = make_ca("JUMBO Devir Test Root CA")
    write("root-ca.pem", pem(ca))
    write("root-ca.key", key_pem(ca_key))

    print("Devir/trust-store serisi (v1 -> v2 -> v3, ortak anahtar)...")
    shared_key = make_key()
    write("leaf-shared.key", key_pem(shared_key))

    v1, _ = make_leaf(ca, ca_key, "devir-test.jumbo.local", key=shared_key,
                       not_before=datetime(2026, 1, 1), san=["devir-test.jumbo.local"])
    write("leaf-v1.pem", pem(v1))
    write("leaf-v1-fullchain.pem", pem(v1) + pem(ca))

    v2, _ = make_leaf(ca, ca_key, "devir-test.jumbo.local", key=shared_key,
                       not_before=datetime(2026, 6, 1), san=["devir-test.jumbo.local"])
    write("leaf-v2.pem", pem(v2))

    v3, _ = make_leaf(ca, ca_key, "devir-test.jumbo.local", key=shared_key,
                       not_before=datetime(2026, 9, 1), san=["devir-test.jumbo.local"])
    write("leaf-v3.pem", pem(v3))

    print("Mail zamanlama demoları (süre uyarısı / süresi geçmiş)...")
    now = datetime.now(timezone.utc)
    exp_soon, exp_soon_key = make_leaf(
        ca, ca_key, "sure-uyarisi-test.jumbo.local",
        not_before=now - timedelta(days=1), days=10,
        san=["sure-uyarisi-test.jumbo.local"])
    write("leaf-expiring-soon.pem", pem(exp_soon))
    write("leaf-expiring-soon.key", key_pem(exp_soon_key))

    expired, expired_key = make_leaf(
        ca, ca_key, "suresi-gecmis-test.jumbo.local",
        not_before=now - timedelta(days=400), days=30,
        san=["suresi-gecmis-test.jumbo.local"])
    write("leaf-expired.pem", pem(expired))
    write("leaf-expired.key", key_pem(expired_key))

    print("Zincir-bilinçli 'server' eşlemesi demosu (tam zincir: leaf+intermediate+root)...")
    chain_root, chain_root_key = make_ca("JUMBO Zincir Test Root CA")
    write("chain-root.pem", pem(chain_root))
    write("chain-root.key", key_pem(chain_root_key))
    chain_inter, chain_inter_key = make_intermediate(
        chain_root, chain_root_key, "JUMBO Zincir Test Intermediate CA")
    write("chain-intermediate.pem", pem(chain_inter))
    write("chain-intermediate.key", key_pem(chain_inter_key))
    chain_leaf, chain_leaf_key = make_leaf(
        chain_inter, chain_inter_key, "zincir-test.jumbo.local",
        san=["zincir-test.jumbo.local"])
    write("chain-leaf.pem", pem(chain_leaf))
    write("chain-leaf.key", key_pem(chain_leaf_key))
    write("chain-fullchain.pem", pem(chain_leaf) + pem(chain_inter) + pem(chain_root))

    print("Eksik zincir demosu (CA'sı envantere HİÇ aktarılmayan tekil leaf)...")
    lonewolf_ca, lonewolf_ca_key = make_ca("JUMBO Lonewolf Test CA")
    lonewolf_leaf, lonewolf_leaf_key = make_leaf(
        lonewolf_ca, lonewolf_ca_key, "lonewolf-test.jumbo.local",
        san=["lonewolf-test.jumbo.local"])
    write("lonewolf-leaf.pem", pem(lonewolf_leaf))
    write("lonewolf-leaf.key", key_pem(lonewolf_leaf_key))
    # lonewolf-ca.pem KASITLI OLARAK yazılmıyor/import edilmiyor — "zincir envanterde yok" senaryosu.

    print("Politika motoru demosu (zayıf 1024-bit RSA anahtar)...")
    weak_key = make_key(bits=1024)
    weak, _ = make_leaf(ca, ca_key, "zayif-anahtar-test.jumbo.local", key=weak_key,
                         not_before=datetime(2026, 1, 1),
                         san=["zayif-anahtar-test.jumbo.local"])
    write("leaf-weak-key.pem", pem(weak))
    write("leaf-weak-key.key", key_pem(weak_key))

    print("Tamamlandı.")


if __name__ == "__main__":
    main()
