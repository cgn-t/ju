"""Sertifika dosyalarını (PEM/DER/PFX) parse edip alanları çıkarır ve
SKI/AKI eşleşmesiyle zincir (parent) ilişkisini kurar."""

import base64
import re
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7, pkcs12
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
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


def _san_names(cert: x509.Certificate) -> list[str]:
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return ([str(v) for v in san_ext.get_values_for_type(x509.DNSName)]
            + [str(v) for v in san_ext.get_values_for_type(x509.IPAddress)])


def _common_name(name: x509.Name) -> str:
    cn = name.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return cn[0].value if cn else name.rfc4514_string()


def _display_name(cert: x509.Certificate) -> str:
    """Listede görünen ad: CN; CN yoksa (adı yalnız SAN'da olan modern sertifikalar) ilk SAN,
    o da yoksa subject DN'i. Konu tamamen boşsa parmak izinin başı — kayıt asla adsız kalmaz."""
    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if cn and str(cn[0].value).strip():
        return cn[0].value
    san = _san_names(cert)
    if san:
        return san[0]
    dn = cert.subject.rfc4514_string()
    if dn:
        return dn
    return "Adsız sertifika " + _hex_colon(cert.fingerprint(hashes.SHA256()))[:11]


_HOST_RE = re.compile(r"^(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$|^localhost$")


def _is_self_signed_server(cert: x509.Certificate) -> bool:
    """Kendinden imzalı SUNUCU sertifikası mı? `openssl req -x509` ve cihazların (iLO, firewall,
    yük dengeleyici…) ürettiği varsayılan sertifikalar CA:TRUE işaretli gelir ama CA değildir:
    sertifika imzalamak için değil, kendi adresini sunmak için üretilmiştir. Gerçek kök CA'lar
    SAN'da host adı taşımaz, sunucu adı biçiminde CN'le de çıkmaz."""
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        ku = None
    if _san_names(cert):
        return True
    if ku is None:
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        if cn and _HOST_RE.match(str(cn[0].value).strip()):
            return True
    return False


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
    try:
        if not cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
            # CA:TRUE ama imza yetkisi yok (bazı cihaz/yanlış şablon sunucu sertifikaları): sertifika
            # imzalayamaz → kim imzalamış olursa olsun uç sertifikadır (RFC 5280 §4.2.1.3).
            return "leaf"
    except x509.ExtensionNotFound:
        pass
    if cert.issuer != cert.subject:
        return "intermediate"
    if _is_self_signed_server(cert):
        return "leaf"
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
    san = ", ".join(_san_names(cert)) or None

    pk_type, key_size, key_curve = _public_key_info(cert)
    return ParsedCertificate(
        name=_display_name(cert),
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


_PEM_BLOCK = re.compile(
    r"-----BEGIN (?:TRUSTED |X509 )?CERTIFICATE-----(.*?)-----END (?:TRUSTED |X509 )?CERTIFICATE-----",
    re.S)
_PFX_PASSWORD_REQUIRED = "Bu PFX dosyası parola korumalı. PFX parolasını girin."
_PFX_PASSWORD_WRONG = "PFX parolası hatalı. Parolayı kontrol edip yeniden deneyin."


def _decode_text(data: bytes) -> bytes:
    """Windows Notepad'in 'Unicode' (UTF-16) kaydı dahil metin dosyalarını UTF-8'e çevirir.
    Ham ikili (DER/PFX) içerik olduğu gibi döner."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16").encode()
        except UnicodeDecodeError:
            return data
    if len(data) > 64 and data[1:40:2] == b"\x00" * 20:  # BOM'suz UTF-16LE metin
        try:
            return data.decode("utf-16-le").encode()
        except UnicodeDecodeError:
            return data
    return data


def _first_der(blob: bytes) -> bytes:
    """Bir DER SEQUENCE'ın kendisini döndürür (arkasındaki ek veriyi atar). OpenSSL'in
    'TRUSTED CERTIFICATE' biçimi sertifikanın ardına güven ayarlarını ekler."""
    if len(blob) < 2 or blob[0] != 0x30:
        return blob
    first = blob[1]
    if first < 0x80:
        return blob[: 2 + first]
    n = first & 0x7F
    length = int.from_bytes(blob[2: 2 + n], "big")
    return blob[: 2 + n + length]


def _pem_blocks(text: str) -> list[x509.Certificate]:
    certs = []
    for body in _PEM_BLOCK.findall(text):
        der = base64.b64decode("".join(body.split()))
        certs.append(x509.load_der_x509_certificate(_first_der(der)))
    return certs


def _looks_like_pfx(data: bytes) -> bool:
    """PKCS#12 yapısı: SEQUENCE { INTEGER 3, SEQUENCE { OID pkcs7-data … } }."""
    if len(data) < 8 or data[0] != 0x30:
        return False
    i = 2 + (data[1] & 0x7F if data[1] & 0x80 else 0)
    return data[i: i + 3] == b"\x02\x01\x03"


def _parse_binary(data: bytes, password: str | None) -> list[x509.Certificate]:
    try:
        return [x509.load_der_x509_certificate(data)]
    except ValueError:
        pass
    try:
        return pkcs7.load_der_pkcs7_certificates(data)
    except ValueError:
        pass
    try:
        _, cert, additional = pkcs12.load_key_and_certificates(
            data, password.encode() if password else None)
    except Exception:
        if _looks_like_pfx(data):
            raise ValueError(_PFX_PASSWORD_WRONG if password else _PFX_PASSWORD_REQUIRED)
        raise ValueError(
            "Dosya formatı tanınamadı. PEM, DER, P7B veya PFX/P12 yükleyin "
            "(PFX için parola gerekebilir).")
    return ([cert] if cert else []) + list(additional or [])


def parse_upload(data: bytes, password: str | None = None) -> list[ParsedCertificate]:
    """Yüklenen dosyayı formatı otomatik algılayarak parse eder.
    PEM birden çok sertifika içerebilir (fullchain); hepsi döndürülür.
    Desteklenen metin biçimleri: PEM (CERTIFICATE / TRUSTED CERTIFICATE / X509 CERTIFICATE),
    PEM PKCS7, başlıksız base64 (DER/P7B/PFX'in metin hali); UTF-8 veya UTF-16 kayıtlı."""
    data = _decode_text(data)
    text = data.decode("utf-8", errors="ignore")
    if "-----BEGIN PKCS7-----" in text and "CERTIFICATE-----" not in text:
        certs = pkcs7.load_pem_pkcs7_certificates(data)
    elif _PEM_BLOCK.search(text):
        certs = _pem_blocks(text)
    else:
        compact = "".join(text.split())
        raw = None
        if len(compact) > 64 and re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
            try:
                raw = base64.b64decode(compact, validate=True)
            except ValueError:
                raw = None
        certs = _parse_binary(raw if raw is not None else data, password)
    if not certs:
        raise ValueError("Dosyada sertifika bulunamadı")
    parsed = [parse_x509(c) for c in certs]
    _promote_file_signers(certs, parsed)
    return parsed


def is_self_signed(issuer: str | None, subject: str | None, aki: str | None, ski: str | None) -> bool:
    """Kendi kendini imzalamış sertifika (kök ya da kendinden imzalı sunucu): yayıncısı kendisidir,
    zincirde üstü OLAMAZ. issuer==subject ve AKI yok ya da kendi SKI'si (anahtar geçişi için
    üretilen self-issued ara CA'da AKI≠SKI'dir, o hariç)."""
    return bool(subject) and issuer == subject and (not aki or aki == ski)


def _signed_by(child: x509.Certificate, parent: x509.Certificate) -> bool:
    try:
        child.verify_directly_issued_by(parent)
        return True
    except Exception:
        return False


def _promote_file_signers(certs: list[x509.Certificate], parsed: list[ParsedCertificate]) -> None:
    """Uzantılarından 'uç' sanılan kendinden imzalı sertifika (uzantısız v1 kök, KU'suz ve CN'i
    alan adı gibi kök, SAN taşıyan kök) aynı dosyadaki başka bir sertifikayı imzalamışsa CA'dır
    → 'root'. Kendinden imzalı çocuk (aynı anahtarla yenilenmiş sunucu sertifikası) kanıt sayılmaz."""
    for i, p in enumerate(parsed):
        if p.cert_type != "leaf" or not is_self_signed(p.issuer, p.subject, p.authority_key_identifier,
                                                       p.subject_key_identifier):
            continue
        for j, child in enumerate(parsed):
            if j == i or child.issuer != p.subject or is_self_signed(
                    child.issuer, child.subject, child.authority_key_identifier,
                    child.subject_key_identifier):
                continue
            if _signed_by(certs[j], certs[i]):
                p.cert_type = "root"
                break


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
    Aynı anahtarın hem kendinden imzalı kökü hem çapraz imzalı kopyası varsa (ör. yeni kök +
    eski kökün imzaladığı kopyası) aktif KÖK seçilir: kısa yol odur; kopya seçilirse zincir
    eski köke çıkar ve domaine erken bitecek eski kök bağlanırdı.
    """
    if not ski:
        return None
    q = db.query(Certificate).filter(Certificate.subject_key_identifier == ski)
    if exclude_id is not None:
        q = q.filter(Certificate.id != exclude_id)
    candidates = q.order_by(Certificate.is_active.desc(),
                            Certificate.valid_to.desc(),
                            Certificate.id.desc()).all()
    if not candidates:
        return None
    return min(candidates, key=lambda c: (not c.is_active,
                                          normalize_cert_type(c.cert_type) != "root"))


def _issued_by(child_pem: str | None, parent_pem: str | None) -> bool:
    if not child_pem or not parent_pem:
        return False
    try:
        child = x509.load_pem_x509_certificate(child_pem.encode())
        child.verify_directly_issued_by(x509.load_pem_x509_certificate(parent_pem.encode()))
        return True
    except Exception:
        return False


def find_ca_by_issuer(db: Session, issuer: str, child_pem: str | None,
                      exclude_id: int | None = None) -> Certificate | None:
    """AKI uzantısı OLMAYAN eski sertifikalar için yayıncıyı bulur: subject'i çocuğun issuer'ı
    olan CA kayıtları arasından, imzası gerçekten doğrulanan ilki (aktif ve bitişi en geç önce)."""
    q = db.query(Certificate).filter(Certificate.subject == issuer)
    if exclude_id is not None:
        q = q.filter(Certificate.id != exclude_id)
    for cand in q.order_by(Certificate.is_active.desc(), Certificate.valid_to.desc(),
                           Certificate.id.desc()).all():
        # 'Uç' sanılan kendinden imzalı kayıt da aday: imzası doğrulanıyorsa aslında kök CA'dır
        # (resolve_parent onu 'root'a yükseltir).
        if (normalize_cert_type(cand.cert_type) != "leaf" or _row_self_signed(cand)) \
                and _issued_by(child_pem, cand.pem_certificate):
            return cand
    return None


def _row_self_signed(row: Certificate) -> bool:
    return is_self_signed(row.issuer, row.subject, row.authority_key_identifier,
                          row.subject_key_identifier)


def _promote_to_root(row: Certificate) -> None:
    """Başka bir sertifikayı imzaladığı görülen, 'uç' kayıtlı kendinden imzalı sertifika kök CA'dır."""
    if normalize_cert_type(row.cert_type) == "leaf" and _row_self_signed(row):
        row.cert_type = "root"


def resolve_parent(db: Session, parsed: ParsedCertificate | Certificate,
                   exclude_id: int | None = None) -> int | None:
    """AKI → mevcut kayıtların SKI'siyle eşleşiyorsa parent id döner. AKI yoksa issuer DN'i
    ve imza doğrulamasıyla aranır. Kayıtlı bir Certificate satırı da verilebilir (aynı alanlar);
    `exclude_id` o kaydı (ör. silinmekte olan üst sertifikayı) aday dışı bırakır."""
    if normalize_cert_type(parsed.cert_type) == "root" or is_self_signed(
            parsed.issuer, parsed.subject, parsed.authority_key_identifier,
            parsed.subject_key_identifier):
        # Kendinden imzalı sertifikanın üstü yoktur. (Aynı anahtarla yenilenmiş kendinden imzalı
        # sunucu sertifikaları aynı SKI'yi taşır; eskiden birbirinin 'üstü' olarak bağlanıyordu.)
        return None
    if parsed.authority_key_identifier:
        parent = find_ca_by_ski(db, parsed.authority_key_identifier, exclude_id=exclude_id)
    else:
        parent = find_ca_by_issuer(db, parsed.issuer, parsed.pem_certificate, exclude_id=exclude_id)
    if parent is None or (isinstance(parsed, Certificate) and parent.id == parsed.id):
        return None
    _promote_to_root(parent)
    return parent.id


def resolve_server_chain(cert: Certificate) -> tuple[list[Certificate], bool]:
    """cert'ten (leaf) başlayıp `parent` ilişkisiyle yukarı çıkar.

    (zincir, tamam_mı) döner — zincir leaf→...→en üst CA sırasıyla, cert ilk eleman.
    'tamam_mı': en üstteki kayıt self-signed (issuer==subject) ise True; aksi halde
    intermediate/root envanterde EKSİK demektir (yalnız bulunabilen kısım döner,
    reddetmek çağıranın işi değil — bkz. domains.py::attach_certificate)."""
    chain = [cert]
    seen = {cert.id}
    current = cert
    while current.parent is not None and current.parent.id not in seen:
        current = current.parent
        chain.append(current)
        seen.add(current.id)
    complete = current.issuer == current.subject
    return chain, complete


def relink_children(db: Session, cert: Certificate) -> int:
    """Yeni eklenen bir CA sertifikasının SKI'sine işaret eden yetim kayıtları bağlar.

    Yetimler doğrudan yeni eklenen kayda değil, o SKI için deterministik 'en iyi'
    CA'ya bağlanır (aynı SKI'li eski/yeni CA'larda sıra bağımlılığını önler).
    Ebeveyni zaten olan çocuklara dokunulmaz — aynı SKI'li CA'lar kriptografik
    olarak eşdeğerdir, mevcut bağları koparmak sürpriz yaratır.
    """
    _promote_if_signed_orphans(db, cert)
    linked = _relink_aki_less(db, cert)
    if not cert.subject_key_identifier:
        return linked
    best = find_ca_by_ski(db, cert.subject_key_identifier)
    if best is None:
        return linked
    orphans = [o for o in (
        db.query(Certificate)
        .filter(
            Certificate.parent_id.is_(None),
            Certificate.authority_key_identifier == cert.subject_key_identifier,
            Certificate.id != best.id,
        )
        .all()
    ) if not _row_self_signed(o)]  # kendinden imzalı kaydın üstü olmaz
    for orphan in orphans:
        orphan.parent_id = best.id
    if orphans:
        _promote_to_root(best)
    return len(orphans) + linked


def _promote_if_signed_orphans(db: Session, cert: Certificate) -> None:
    """Yeni eklenen 'uç' kayıtlı kendinden imzalı sertifika, envanterdeki üstsüz bir sertifikayı
    imzalamışsa kök CA'dır → önce 'root' yapılır ki çocukları ona bağlanabilsin."""
    if normalize_cert_type(cert.cert_type) != "leaf" or not _row_self_signed(cert) or not cert.subject:
        return
    q = db.query(Certificate).filter(Certificate.parent_id.is_(None),
                                     Certificate.issuer == cert.subject,
                                     Certificate.id != cert.id)
    for cand in q.all():
        if _row_self_signed(cand):
            continue
        if cand.authority_key_identifier and cand.authority_key_identifier != cert.subject_key_identifier:
            continue
        if _issued_by(cand.pem_certificate, cert.pem_certificate):
            cert.cert_type = "root"
            return


def _relink_aki_less(db: Session, cert: Certificate) -> int:
    """AKI'siz yetimler: issuer'ı bu CA'nın subject'i olan ve imzası bu CA ile doğrulananlar."""
    if normalize_cert_type(cert.cert_type) == "leaf" or not cert.subject:
        return 0
    orphans = (db.query(Certificate)
               .filter(Certificate.parent_id.is_(None),
                       Certificate.authority_key_identifier.is_(None),
                       Certificate.issuer == cert.subject,
                       Certificate.id != cert.id).all())
    count = 0
    for orphan in orphans:
        if orphan.issuer == orphan.subject and normalize_cert_type(orphan.cert_type) == "root":
            continue
        if _issued_by(orphan.pem_certificate, cert.pem_certificate):
            orphan.parent_id = cert.id
            count += 1
    return count
