"""Tarayıcıların güvendiği genel kök sertifikalar (Mozilla listesi, certifi paketi).

Bazı sunucular zincirde kök sertifikanın *çapraz imzalı* kopyasını da gönderir: aynı ad ve
aynı anahtar, ama başka (genelde eski) bir kökün imzası. Bu kopya teknik olarak ara
sertifikadır; tarayıcı ise kökün kendinden imzalı halini güven listesinde bulduğu için
zinciri orada bitirir ve kopyanın üstündeki sertifikaları kullanmaz.
"""
from functools import lru_cache

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import NameOID


def _spki(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)


@lru_cache(maxsize=1)
def _public_roots() -> frozenset[tuple[bytes, bytes]]:
    """(subject DER, açık anahtar DER) çiftleri; paket yoksa boş küme (işaretleme yapılmaz)."""
    try:
        import certifi
        with open(certifi.where(), "rb") as fh:
            roots = x509.load_pem_x509_certificates(fh.read())
    except Exception:
        return frozenset()
    return frozenset((c.subject.public_bytes(), _spki(c)) for c in roots)


def common_name(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attrs[0].value) if attrs else name.rfc4514_string()


def is_cross_signed_public_root(cert: x509.Certificate) -> bool:
    """Başka bir CA'nın imzaladığı, ama adı ve anahtarı genel bir kökle aynı olan kopya mı?"""
    if cert.subject == cert.issuer:
        return False
    return (cert.subject.public_bytes(), _spki(cert)) in _public_roots()


def first_cross_signed_root(chain: list[x509.Certificate]) -> int | None:
    """Sunulan zincirde (uç → kök) ilk çapraz imzalı kök kopyasının sırası; tarayıcı orada
    durur, sonrakiler eski cihazlar için gönderilen ek zincirdir. Yoksa None."""
    for i, cert in enumerate(chain[1:], start=1):
        if is_cross_signed_public_root(cert):
            return i
    return None
