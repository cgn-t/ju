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
import threading
from datetime import datetime, timezone
from app.core.timeutil import utcnow

from cryptography import x509
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
from app.db.models import Certificate, Domain
from app.services.audit import audited_job
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
    """Domain'i canlı kontrol eder, sonucu domain kaydına yazar. Çağıran commit eder.

    Zincir-bilinçli: sunulan TÜM zincir (leaf→root) çekilir; her cert_type kendi eşlenmiş
    'server' havuzuyla karşılaştırılır (leaf↔leaf, intermediate↔intermediate, root↔root —
    birbirine karıştırılmaz). AYNI TLS bağlantısının sonucu, zincir senkronizasyonu için de
    (root/intermediate rotasyonu dahil devir tespiti) yeniden kullanılır — ikinci bağlantı
    açılmaz (bkz. sync_domain_chain_certs)."""
    from app.services.chain_sync import sync_domain_chain_certs

    host, port = parse_target(domain.domain)
    checked_at = utcnow()

    if host is None:
        domain.live_check_status = "not_checkable"
        domain.live_check_detail = json.dumps(
            {"reason": "Wildcard veya boş domain — doğrudan bağlanılamaz"}, ensure_ascii=False)
        domain.live_check_at = checked_at
        return domain

    # Deterministik: aynı tipte birden çok eşlemede aktif ve bitişi en geç olan kayıt
    # havuzda kazanır (artan sırayla gezilir, sonuncu yazan kalır)
    bound_by_type: dict[str, dict[str, Certificate]] = {}
    server_mappings = sorted(
        (m for m in domain.certificate_mappings
         if m.mapping_type == "server" and m.certificate.fingerprint_sha256),
        key=lambda m: (m.certificate.is_active, m.certificate.valid_to or datetime.min))
    for m in server_mappings:
        bound_by_type.setdefault(normalize_cert_type(m.certificate.cert_type), {})[
            m.certificate.fingerprint_sha256] = m.certificate

    try:
        served_raw = fetch_served_chain(host, port)
    except Exception as exc:
        domain.live_check_status = "unreachable"
        domain.live_check_detail = json.dumps(
            {"host": host, "port": port, "error": str(exc)[:300]}, ensure_ascii=False)
        domain.live_check_at = checked_at
        return domain
    served_list = [parse_x509(c) for c in served_raw]
    leaf_served = served_list[0]  # el sıkışmada ilk sunulan her zaman uç (leaf) sertifikadır

    detail = {
        "host": host,
        "port": port,
        "served_cn": leaf_served.name,
        "served_serial": leaf_served.serial_number,
        "served_fingerprint": leaf_served.fingerprint_sha256,
        "served_valid_to": leaf_served.valid_to.isoformat(),
    }
    if not bound_by_type:
        domain.live_check_status = "no_mapping"
        detail["reason"] = "Domain'e server sertifikası eşlenmemiş — sunulan sertifika envanter dışı"
    else:
        levels: dict[str, dict] = {}
        for served in served_list:
            pool = bound_by_type.get(served.cert_type)
            if not pool:
                continue  # bu tip domaine hiç eşlenmemiş — karşılaştırılamaz, mismatch sayılmaz
            if served.fingerprint_sha256 in pool:
                matched = pool[served.fingerprint_sha256]
                if matched.valid_to is not None and matched.valid_to < checked_at:
                    # Eşleşiyor ama süresi dolmuş — bunu yeşil göstermek yanıltıcı olur
                    levels[served.cert_type] = {"status": "mismatch", "matched_certificate": matched.name,
                                                "reason": "SÜRESİ DOLMUŞ"}
                else:
                    levels[served.cert_type] = {"status": "match", "matched_certificate": matched.name}
            else:
                levels[served.cert_type] = {"status": "mismatch"}
        served_types = {s.cert_type for s in served_list}
        if "root" in bound_by_type and "root" not in served_types:
            # Protokol kısıtı: sunucu el sıkışmada pratikte root GÖNDERMEZ (istemci zaten trust
            # store'unda tutar) — bu kod hatası değil; genel durumu BOZMA, yalnız bilgilendir.
            # Root rotasyonu yalnız içe aktarma/senkronizasyon anında (chain_sync) yakalanır.
            detail["root_note"] = ("Root sertifika TLS el sıkışmasında sunulmaz (protokol kısıtı) — "
                                   "canlı doğrulanamaz; rotasyonu yalnız içe aktarma/senkronizasyon "
                                   "sırasında yakalanır.")
        if not levels:
            domain.live_check_status = "no_mapping"
            detail["reason"] = "Sunulan sertifikaların hiçbiri domaine eşlenmiş bir tiple örtüşmüyor"
        else:
            detail["levels"] = levels
            if any(lv["status"] == "mismatch" for lv in levels.values()):
                domain.live_check_status = "mismatch"
                detail["expected"] = [c.name for pool in bound_by_type.values() for c in pool.values()]
                detail["reason"] = "Sunulan zincirin bir veya daha fazla seviyesi eşlenmiş sertifikadan farklı"
            else:
                domain.live_check_status = "match"

    # Devir kanıtı: sunulan HER sertifika kendi tipiyle bekleyen bir devir önerisinin
    # HALEFİ ise (eşli olsun olmasın) 'canlıda görüldü' işaretlenir — SY'ye güvenli onay
    # sinyali. Hiçbir devir uygulanmaz; onay hattı korunur.
    seen = _record_live_evidence(db, domain, served_list)
    if seen:
        detail["superseded_live_seen"] = seen

    # Zincir senkronizasyonu: sunulan zincir envantere işlenir ve HER cert_type için ayrı
    # ayrı devir tespiti yapılır (root/intermediate rotasyonu dahil — proaktif, import
    # beklemeden). import_chain ile AYNI ortak mantık (chain_sync); ikinci TLS bağlantısı
    # açılmaz, yukarıda zaten çekilen served_raw yeniden kullanılır.
    sync = sync_domain_chain_certs(db, domain, served_raw, username="system", request=None,
                                   via="live-check", live=True)
    if sync.superseded:
        detail["chain_sync_superseded"] = sync.superseded
    if sync.added:
        detail["proposed_add"] = sync.added
    if sync.removed:
        detail["proposed_remove"] = sync.removed

    domain.live_check_detail = json.dumps(detail, ensure_ascii=False)
    domain.live_check_at = checked_at
    return domain


def _record_live_evidence(db: Session, domain: Domain, served_list: list) -> list[str]:
    """ONAY MODELİ: Canlı doğrulama artık HİÇBİR devri kendiliğinden tamamlamaz —
    ne pasife alır ne eşleme siler. Yalnızca 'yeni sertifika sunucuda gerçekten
    görüldü' KANITINI işler: sunulan HER sertifika (fingerprint) envanterde bir kayda
    denk geliyorsa ve o kayıt bu domaine ait bekleyen bir devir önerisinin HALEFİ ise
    live_seen=True işaretlenir. Yeni öneriler (ekleme/değişiklik/kaldırma) YALNIZ bu domain
    için zincir uzlaştırmasında (chain_sync, live=True) üretilir. Gerçek değişiklik yalnız
    SY onayıyla olur."""
    from app.db.models import Certificate, TransferProposal

    seen: list[str] = []
    now = utcnow()
    for served in served_list:
        if not served.fingerprint_sha256:
            continue
        served_cert = (db.query(Certificate)
                       .filter(Certificate.fingerprint_sha256 == served.fingerprint_sha256).first())
        if served_cert is None:
            continue

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

    return seen


# Toplu tarama TEK seferde bir kez çalışır (gece cron + dış tetik çakışmasın). Son çalıştırmanın
# durumu süreç belleğinde tutulur (dış otomasyon /live-check-run/status ile izler).
_bulk_lock = threading.Lock()
_bulk_state: dict = {"running": False}


def _now_iso() -> str:
    """UTC, saat dilimi işaretli ISO — tarayıcı yerel saat sanıp 3 saat kaydırmasın."""
    return utcnow().replace(tzinfo=timezone.utc).isoformat()


def _scan_all_domains() -> dict:
    """Tüm domainleri sırayla canlı kontrol eder (ayar kontrolü YOK — çağıran karar verir)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        domains = db.query(Domain).all()
        counts: dict[str, int] = {}
        mismatched: list[str] = []
        errors = 0
        for domain in domains:
            try:
                check_domain(db, domain)
                db.commit()
                counts[domain.live_check_status or "?"] = counts.get(domain.live_check_status or "?", 0) + 1
                if domain.live_check_status == "mismatch":
                    mismatched.append(domain.domain)
            except Exception:
                db.rollback()
                errors += 1
                logger.exception("Canlı kontrol hatası: %s", domain.domain)
        return {"status": "error" if errors else "ok", "total": len(domains), "by_status": counts,
                "errors": errors, "mismatched": mismatched[:50]}
    finally:
        db.close()


def _run_holding_lock(triggered_by: str) -> dict:
    """Kilit ÇAĞIRANDA alınmış olmalı; tarama bitince (hata olsa da) bırakılır."""
    _bulk_state.update(running=True, triggered_by=triggered_by, started_at=_now_iso(),
                       finished_at=None, result=None)
    result = None
    try:
        result = {**_scan_all_domains(), "triggered_by": triggered_by}
        return result
    except Exception as exc:
        result = {"status": "error", "error": str(exc)[:300], "triggered_by": triggered_by}
        raise
    finally:
        _bulk_state.update(running=False, finished_at=_now_iso(), result=result)
        _bulk_lock.release()


@audited_job("Canlı doğrulama")
def check_all_domains() -> dict:
    """Zamanlanmış günlük tarama: tüm domainleri canlı kontrol eder. 'live_check.enabled'
    kapalıysa atlanır (Keşif/CT/İptal ile aynı patern) — manuel tetik (/domains/{id}/live-check)
    ve dış tetik (/domains/live-check-run) bundan bağımsız her zaman çalışır."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_category

    db = SessionLocal()
    try:
        enabled = get_category(db, "live_check", mask_secrets=False).get("enabled")
    finally:
        db.close()
    if not enabled:
        logger.info("Canlı doğrulama kapalı — zamanlanmış tarama atlandı")
        return {"status": "skipped"}
    if not _bulk_lock.acquire(blocking=False):
        logger.info("Toplu canlı doğrulama zaten çalışıyor — zamanlanmış tarama atlandı")
        return {"status": "skipped"}
    return _run_holding_lock("schedule")


@audited_job("Canlı doğrulama (tetiklenen)")
def _triggered_run(triggered_by: str) -> dict:
    return _run_holding_lock(triggered_by)


def start_bulk_run(triggered_by: str) -> bool:
    """Toplu taramayı ARKA PLANDA başlatır (HTTP isteği beklemez — çok domainde ön kapı
    zaman aşımına düşmesin). Kilit burada alınır, iş parçacığı bitince bırakır; zaten
    çalışıyorsa False döner (eşzamanlı iki istek ikinci bir tarama başlatamaz)."""
    if not _bulk_lock.acquire(blocking=False):
        return False
    _bulk_state.update(running=True, triggered_by=triggered_by, started_at=_now_iso(),
                       finished_at=None, result=None)
    try:
        threading.Thread(target=_triggered_run, args=(triggered_by,), daemon=True,
                         name="live-check-bulk").start()
    except Exception:
        _bulk_lock.release()
        raise
    return True


def bulk_run_status() -> dict:
    return dict(_bulk_state)
