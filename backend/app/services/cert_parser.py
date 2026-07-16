"""Sertifika dosyalarını (PEM/DER/PFX) parse edip alanları çıkarır ve
SKI/AKI eşleşmesiyle zincir (parent) ilişkisini kurar."""

from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7, pkcs12
from sqlalchemy.orm import Session

from app.db.models import Certificate


@dataclass
class ParsedCertificate:
    name: str
    serial_number: str
    issuer: str
    subject: str
    subject_key_identifier: str | None
    authority_key_identifier: str | None
    cert_type: str  # root|intermediate|leaf
    valid_from: datetime
    valid_to: datetime
    pem_certificate: str
    extended_key_usage: str | None
    san: str | None  # SubjectAltName listesi (virgülle ayrık)
    fingerprint_sha256: str  # sertifikanın benzersiz kimliği — duplicate kontrolü bununla yapılır
    # Kripto özellikleri (politika/uyum + PQC envanteri). Certificate modelinde AYNI adlı kolonlar
    # olmalı — 5 çağrı noktası Certificate(**parsed.__dict__) kullanır (aksi halde TypeError).
    key_size: int | None            # RSA modülüs bit / EC eğri boyu / EdDSA sabiti
    public_key_type: str | None     # RSA|EC|Ed25519|Ed448|DSA
    key_curve: str | None           # EC eğri adı (secp256r1…), else None
    signature_hash: str | None      # sha256|sha1|md5 … (EdDSA'da None)


def _hex_colon(data: bytes) -> str:
    return ":".join(f"{b:02X}" for b in data)


def _serial_hex(serial: int) -> str:
    # RFC 5280 §4.1.2.2: seri numarası pozitif tamsayı OLMALI. Bozuk/legacy sertifikalar yüksek biti
    # set edilerek kodlandığında cryptography bunu NEGATİF int çözer; işaretsiz octet temsilinden
    # yeniden kurup kanonik hex üret (aksi halde '-1F..' gibi bozuk kimlik yazılırdı).
    if serial < 0:
        nbytes = (serial.bit_length() + 8) // 8
        serial = int.from_bytes(serial.to_bytes(nbytes, "big", signed=True), "big", signed=False)
    raw = f"{serial:X}"
    if len(raw) % 2:
        raw = "0" + raw
    return ":".join(raw[i : i + 2] for i in range(0, len(raw), 2))


def _common_name(name: x509.Name) -> str:
    cn = name.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return cn[0].value if cn else name.rfc4514_string()


def _classify(cert: x509.Certificate) -> str:
    is_ca = False
    try:
        is_ca = cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        # basicConstraints yok (eski v1 CA / trust anchor, RFC 5280 §4.2.1.9) → keyUsage.keyCertSign'a düş.
        try:
            is_ca = cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign
        except x509.ExtensionNotFound:
            is_ca = False
    if not is_ca:
        return "leaf"
    if cert.issuer != cert.subject:
        return "intermediate"
    # issuer==subject: GERÇEK kök (self-signed) yalnız AKI yoksa veya AKI==SKI ise. Aksi halde bu,
    # anahtar-geçişi (key rollover) için üretilmiş SELF-ISSUED ara CA'dır → resolve_parent öncülünü
    # arayabilsin diye 'root' değil 'intermediate' say.
    try:
        aki = cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value.key_identifier
    except x509.ExtensionNotFound:
        aki = None
    try:
        ski = cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest
    except x509.ExtensionNotFound:
        ski = None
    return "root" if (aki is None or aki == ski) else "intermediate"


def _public_key_info(cert: x509.Certificate) -> tuple[str | None, int | None, str | None]:
    """(public_key_type, key_size, key_curve) çıkarır. Politika/uyum ve PQC envanteri için."""
    pub = cert.public_key()
    if isinstance(pub, rsa.RSAPublicKey):
        return "RSA", pub.key_size, None
    if isinstance(pub, ec.EllipticCurvePublicKey):
        return "EC", pub.curve.key_size, pub.curve.name
    if isinstance(pub, ed25519.Ed25519PublicKey):
        return "Ed25519", 256, None
    if isinstance(pub, ed448.Ed448PublicKey):
        return "Ed448", 448, None
    if isinstance(pub, dsa.DSAPublicKey):
        return "DSA", pub.key_size, None
    return None, None, None


def _signature_hash(cert: x509.Certificate) -> str | None:
    """İmza özet algoritması adı (sha256/sha1/…). EdDSA'da özet yoktur → None."""
    try:
        algo = cert.signature_hash_algorithm
    except UnsupportedAlgorithm:
        return None
    return getattr(algo, "name", None)


def parse_x509(cert: x509.Certificate) -> ParsedCertificate:
    ski = aki = None
    try:
        ski = _hex_colon(cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest)
    except x509.ExtensionNotFound:
        pass
    try:
        aki_value = cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
        if aki_value.key_identifier:
            aki = _hex_colon(aki_value.key_identifier)
    except x509.ExtensionNotFound:
        pass
    eku = None
    try:
        ekus = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        # Bilinen OID'lerde dostça ad (serverAuth...), bilinmeyende gerçek OID'i koru (RFC 5280
        # §4.2.1.12: anlamlı olan OID'dir). u._name tanınmayanlarda 'Unknown OID' döndürür.
        eku = ", ".join(u.dotted_string if u._name == "Unknown OID" else u._name for u in ekus)
    except x509.ExtensionNotFound:
        pass
    san = None
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        entries = [str(v) for v in san_ext.get_values_for_type(x509.DNSName)]
        entries += [str(v) for v in san_ext.get_values_for_type(x509.IPAddress)]
        san = ", ".join(entries) if entries else None
    except x509.ExtensionNotFound:
        pass

    pk_type, key_size, key_curve = _public_key_info(cert)
    return ParsedCertificate(
        name=_common_name(cert.subject),
        serial_number=_serial_hex(cert.serial_number),
        issuer=cert.issuer.rfc4514_string(),
        subject=cert.subject.rfc4514_string(),
        subject_key_identifier=ski,
        authority_key_identifier=aki,
        cert_type=_classify(cert),
        valid_from=cert.not_valid_before_utc.replace(tzinfo=None),
        valid_to=cert.not_valid_after_utc.replace(tzinfo=None),
        pem_certificate=cert.public_bytes(Encoding.PEM).decode(),
        extended_key_usage=eku,
        san=san,
        fingerprint_sha256=_hex_colon(cert.fingerprint(hashes.SHA256())),
        key_size=key_size,
        public_key_type=pk_type,
        key_curve=key_curve,
        signature_hash=_signature_hash(cert),
    )


def parse_upload(data: bytes, password: str | None = None) -> list[ParsedCertificate]:
    """Yüklenen dosyayı formatı otomatik algılayarak parse eder.
    PEM birden çok sertifika içerebilir (fullchain); hepsi döndürülür."""
    certs: list[x509.Certificate] = []
    text = data.decode("utf-8", errors="ignore")
    if "-----BEGIN CERTIFICATE-----" in text:
        certs = x509.load_pem_x509_certificates(data)
    elif "-----BEGIN PKCS7-----" in text:
        certs = pkcs7.load_pem_pkcs7_certificates(data)
    else:
        try:
            certs = [x509.load_der_x509_certificate(data)]
        except ValueError:
            try:
                certs = pkcs7.load_der_pkcs7_certificates(data)
            except ValueError:
                try:
                    _, cert, additional = pkcs12.load_key_and_certificates(
                        data, password.encode() if password else None
                    )
                    if cert:
                        certs.append(cert)
                    certs.extend(additional or [])
                except Exception:
                    raise ValueError(
                        "Dosya formatı tanınamadı. PEM, DER, P7B veya PFX/P12 yükleyin "
                        "(PFX için parola gerekebilir)."
                    )
    if not certs:
        raise ValueError("Dosyada sertifika bulunamadı")
    return [parse_x509(c) for c in certs]


def parse_pem_text(pem_text: str) -> list[ParsedCertificate]:
    return parse_upload(pem_text.encode())


def find_existing(db: Session, parsed: ParsedCertificate) -> Certificate | None:
    """Mükerrer kontrolü: SHA-256 fingerprint sertifikanın gerçek kimliğidir.

    SKI ASLA tekillik şartı değildir — aynı anahtarla yenilenen sertifika aynı SKI'yi
    taşır ve yeni bir kayıt olarak eklenebilmelidir. (SerialNumber yalnız aynı CA
    içinde benzersizdir; eski fingerprint'siz kayıtlar için serial+issuer'a düşülür.)
    """
    existing = db.query(Certificate).filter(
        Certificate.fingerprint_sha256 == parsed.fingerprint_sha256).first()
    if existing:
        return existing
    return db.query(Certificate).filter(
        Certificate.fingerprint_sha256.is_(None),
        Certificate.serial_number == parsed.serial_number,
        Certificate.issuer == parsed.issuer,
    ).first()


def find_ca_by_ski(db: Session, ski: str | None, exclude_id: int | None = None) -> Certificate | None:
    """SKI'si verilen 'en iyi' CA kaydını deterministik seçer.

    Aynı anahtarla yenilenmiş CA'lar aynı SKI'yi taşıdığından birden fazla aday
    olabilir; aktif ve bitişi en geç olan tercih edilir (id ile kararlı tie-break).
    """
    if not ski:
        return None
    q = db.query(Certificate).filter(Certificate.subject_key_identifier == ski)
    if exclude_id is not None:
        q = q.filter(Certificate.id != exclude_id)
    return q.order_by(Certificate.is_active.desc(),
                      Certificate.valid_to.desc(),
                      Certificate.id.desc()).first()


def resolve_parent(db: Session, parsed: ParsedCertificate) -> int | None:
    """AKI → mevcut kayıtların SKI'siyle eşleşiyorsa parent id döner."""
    if not parsed.authority_key_identifier or parsed.cert_type == "root":
        return None
    parent = find_ca_by_ski(db, parsed.authority_key_identifier)
    return parent.id if parent else None


def relink_children(db: Session, cert: Certificate) -> int:
    """Yeni eklenen bir CA sertifikasının SKI'sine işaret eden yetim kayıtları bağlar.

    Yetimler doğrudan yeni eklenen kayda değil, o SKI için deterministik 'en iyi'
    CA'ya bağlanır (aynı SKI'li eski/yeni CA'larda sıra bağımlılığını önler).
    Ebeveyni zaten olan çocuklara dokunulmaz — aynı SKI'li CA'lar kriptografik
    olarak eşdeğerdir, mevcut bağları koparmak sürpriz yaratır.
    """
    if not cert.subject_key_identifier:
        return 0
    best = find_ca_by_ski(db, cert.subject_key_identifier)
    if best is None:
        return 0
    orphans = (
        db.query(Certificate)
        .filter(
            Certificate.parent_id.is_(None),
            Certificate.authority_key_identifier == cert.subject_key_identifier,
            Certificate.id != best.id,
        )
        .all()
    )
    for orphan in orphans:
        orphan.parent_id = best.id
    return len(orphans)
