"""Canlı endpoint doğrulama (drift detection).

Domain'in gerçekte sunduğu sertifikayı (domain:port, SNI ile) çekip DB'de o domain'e
'server' olarak eşlenmiş sertifikalarla SHA-256 fingerprint üzerinden karşılaştırır.
"Sertifika yenilendi ama sunucuya deploy edilmedi" veya "envanterde olmayan sertifika
sunuluyor" durumlarını yakalar.
"""

import json
import logging
import re
import socket
import ssl
from datetime import datetime
from app.core.timeutil import utcnow

from cryptography import x509
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
from app.db.models import Domain
from app.services.cert_parser import parse_x509

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6


def parse_target(domain_value: str) -> tuple[str | None, int]:
    """Domain alanından bağlanılacak host:port'u çıkarır.

    Örnekler: "trade.aaakkk.com" → (trade.aaakkk.com, 443)
              "xxx.aaakkk.com:8228(Bloomberg)" → (xxx.aaakkk.com, 8228)
              "*.aaakkk.com" → (None, 443)  — wildcard'a bağlanılamaz
    """
    value = re.sub(r"\(.*?\)", "", (domain_value or "")).strip()
    if not value or value.startswith("*"):
        return None, 443
    host, _, port_str = value.partition(":")
    host = host.strip()
    try:
        port = int(port_str) if port_str.strip() else 443
    except ValueError:
        port = 443
    return (host or None), port


def fetch_served_certificate(host: str, port: int, timeout: float = TIMEOUT_SECONDS) -> x509.Certificate:
    """Sertifika doğrulaması yapmadan (self-signed/iç CA olabilir) sunulan sertifikayı çeker."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("Sunucu sertifika göndermedi")
    return x509.load_der_x509_certificate(der)


def fetch_served_chain(host: str, port: int) -> list[x509.Certificate]:
    """Sunucunun el sıkışmada sunduğu TÜM zinciri (leaf → root sırasıyla) doğrulamasız çeker.

    get_unverified_chain Python 3.13+ gerektirir; yoksa yalnız leaf ile devam edilir.
    Dönen öğeler sürüme göre DER bytes veya ssl.Certificate olabilir — ikisi de desteklenir.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            leaf_der = tls.getpeercert(binary_form=True)
            raw_chain = tls.get_unverified_chain() if hasattr(tls, "get_unverified_chain") else None
    certs: list[x509.Certificate] = []
    for item in raw_chain or []:
        der = item if isinstance(item, bytes) else item.public_bytes(ssl.ENCODING_DER)
        certs.append(x509.load_der_x509_certificate(der))
    if not certs:
        if not leaf_der:
            raise ssl.SSLError("Sunucu sertifika göndermedi")
        certs = [x509.load_der_x509_certificate(leaf_der)]
    return certs


def check_domain(db: Session, domain: Domain) -> Domain:
    """Domain'i canlı kontrol eder, sonucu domain kaydına yazar. Çağıran commit eder."""
    host, port = parse_target(domain.domain)
    checked_at = utcnow()

    if host is None:
        domain.live_check_status = "not_checkable"
        domain.live_check_detail = json.dumps(
            {"reason": "Wildcard veya boş domain — doğrudan bağlanılamaz"}, ensure_ascii=False)
        domain.live_check_at = checked_at
        return domain

    # Deterministik: aynı fingerprint'li birden çok eşlemede aktif ve bitişi en geç
    # olan kayıt dict'te kazanır (artan sırayla gezilir, sonuncu yazan kalır)
    server_mappings = sorted(
        (m for m in domain.certificate_mappings
         if m.mapping_type == "server" and m.certificate.fingerprint_sha256),
        key=lambda m: (m.certificate.is_active, m.certificate.valid_to or datetime.min))
    server_fingerprints = {m.certificate.fingerprint_sha256: m.certificate
                           for m in server_mappings}

    try:
        served = parse_x509(fetch_served_certificate(host, port))
    except Exception as exc:
        domain.live_check_status = "unreachable"
        domain.live_check_detail = json.dumps(
            {"host": host, "port": port, "error": str(exc)[:300]}, ensure_ascii=False)
        domain.live_check_at = checked_at
        return domain

    detail = {
        "host": host,
        "port": port,
        "served_cn": served.name,
        "served_serial": served.serial_number,
        "served_fingerprint": served.fingerprint_sha256,
        "served_valid_to": served.valid_to.isoformat(),
    }
    if not server_fingerprints:
        domain.live_check_status = "no_mapping"
        detail["reason"] = "Domain'e server sertifikası eşlenmemiş — sunulan sertifika envanter dışı"
    elif served.fingerprint_sha256 in server_fingerprints:
        matched = server_fingerprints[served.fingerprint_sha256]
        if matched.valid_to is not None and matched.valid_to < checked_at:
            # Envanterle eşleşiyor ama süresi dolmuş bir sertifika sunuluyor —
            # bunu yeşil göstermek yanıltıcı olur
            domain.live_check_status = "mismatch"
            detail["matched_certificate"] = matched.name
            detail["reason"] = "Sunulan sertifika envanterde eşli ama SÜRESİ DOLMUŞ"
        else:
            domain.live_check_status = "match"
            detail["matched_certificate"] = matched.name
    else:
        domain.live_check_status = "mismatch"
        detail["expected"] = [c.name for c in server_fingerprints.values()]
        detail["reason"] = "Sunulan sertifika, eşlenmiş server sertifikalarından hiçbiriyle uyuşmuyor"

    # Devir kanıtı: sunulan sertifika bekleyen bir devir önerisinin HALEFİ ise (eşli
    # olsun olmasın) 'canlıda görüldü' işaretlenir — SY'ye güvenli onay sinyali.
    # Hiçbir devir uygulanmaz; onay hattı korunur.
    seen = _record_live_evidence(db, domain, served.fingerprint_sha256)
    if seen:
        detail["superseded_live_seen"] = seen
    domain.live_check_detail = json.dumps(detail, ensure_ascii=False)
    domain.live_check_at = checked_at
    return domain


def _record_live_evidence(db: Session, domain: Domain, served_fingerprint: str | None) -> list[str]:
    """ONAY MODELİ: Canlı doğrulama artık HİÇBİR devri kendiliğinden tamamlamaz —
    ne pasife alır ne eşleme siler. Yalnızca 'yeni sertifika sunucuda gerçekten
    görüldü' KANITINI işler: sunulan sertifika (fingerprint) envanterde bir kayda
    denk geliyorsa ve o kayıt bu domaine ait bekleyen bir devir önerisinin HALEFİ ise
    live_seen=True işaretlenir; henüz öneri yoksa ama bu domainde başka aktif server
    eşlemeli öncül varsa öneri üretilir. Gerçek devir yalnız SY onayıyla olur."""
    from app.db.models import Certificate, TransferProposal
    from app.services import renewal

    if not served_fingerprint:
        return []
    served_cert = (db.query(Certificate)
                   .filter(Certificate.fingerprint_sha256 == served_fingerprint).first())
    if served_cert is None:
        return []

    seen: list[str] = []
    now = utcnow()

    # 1) Bu domaine ait, halefi served_cert olan bekleyen önerileri kanıtla
    props = (db.query(TransferProposal)
             .filter(TransferProposal.new_cert_id == served_cert.id,
                     TransferProposal.domain_id == domain.id,
                     TransferProposal.status == "pending").all())
    for p in props:
        if not p.live_seen:
            p.live_seen = True
            p.live_seen_at = now
        old = db.get(Certificate, p.old_cert_id)
        seen.append(old.name if old else f"#{p.old_cert_id}")

    # 2) Hiç öneri yoksa: bu domainde served_cert dışında aktif server eşlemeli
    #    öncül var mı? Varsa onlar için öneri üret (live_seen kanıtıyla)
    if not props:
        for m in list(domain.certificate_mappings):
            old = m.certificate
            if (old.id != served_cert.id and old.is_active
                    and normalize_cert_type(old.cert_type) == "leaf"
                    and m.mapping_type == "server"):
                renewal.propose(db, served_cert, old, username="system", request=None,
                                via="live-check", live_seen=True)
                seen.append(old.name)
    return seen


def check_all_domains() -> None:
    """Zamanlanmış günlük tarama: tüm domainleri canlı kontrol eder."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        domains = db.query(Domain).all()
        for domain in domains:
            try:
                check_domain(db, domain)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Canlı kontrol hatası: %s", domain.domain)
    finally:
        db.close()
