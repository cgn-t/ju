"""Canlı endpoint doğrulama (drift detection).

Domain'in gerçekte sunduğu sertifikayı (domain:port, SNI ile) çekip DB'de o domain'e
'server' olarak eşlenmiş sertifikalarla SHA-256 fingerprint üzerinden karşılaştırır.
"Sertifika yenilendi ama sunucuya deploy edilmedi" veya "envanterde olmayan sertifika
sunuluyor" durumlarını yakalar.
"""

import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
from datetime import datetime, timezone
from app.core.timeutil import utcnow

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
from app.db.models import Certificate, Domain
from app.services.audit import audited_job
from app.services.cert_parser import find_ca_by_issuer, find_ca_by_ski, parse_x509

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 6


def parse_target(domain_value: str) -> tuple[str | None, int]:
    """Domain alanından bağlanılacak host:port'u çıkarır.

    Örnekler: "trade.aaakkk.com" → (trade.aaakkk.com, 443)
              "xxx.aaakkk.com:8228(Bloomberg)" → (xxx.aaakkk.com, 8228)
              "https://trade.aaakkk.com/giris" → (trade.aaakkk.com, 443)
              "[2001:db8::1]:8443" → (2001:db8::1, 8443)
              "*.aaakkk.com" → (None, 443)  — wildcard'a bağlanılamaz
    """
    value = re.sub(r"\(.*?\)", "", (domain_value or "")).strip()
    # Tarayıcıdan kopyalanan adres: şema, kullanıcı bilgisi ve yol/sorgu kısmı atılır
    value = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", value)
    value = re.split(r"[/?#]", value, maxsplit=1)[0]
    value = value.rpartition("@")[2].strip()
    if not value or value.startswith("*"):
        return None, 443
    if value.startswith("["):  # IPv6: [adres]:port
        host, _, rest = value[1:].partition("]")
        port_str = rest[1:] if rest.startswith(":") else ""
    elif value.count(":") > 1:  # köşeli parantezsiz IPv6, port yok
        host, port_str = value, ""
    else:
        host, _, port_str = value.partition(":")
    host = host.strip()
    try:
        port = int(port_str) if port_str.strip() else 443
    except ValueError:
        port = 443
    return (host or None), port


def _probe_context(captured: list[bytes]) -> ssl.SSLContext:
    """Yalnız sertifikayı OKUMAK için TLS bağlamı: doğrulama yok, eski protokoller (TLS 1.0/1.1)
    ve zayıf şifreler açık — süresi geçmiş sertifikalar en çok bu eski sistemlerde bulunur.
    Güven kararı burada verilmez; bağlantı üzerinden veri gönderilmez.

    `captured`: el sıkışmada gelen Certificate mesajları (TLS ≤1.2'de açık metin). Sunucu
    istemci sertifikası zorunlu tuttuğu için el sıkışma yarıda kesilse bile sunucunun
    sertifikası bu mesajdan okunur."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        context.set_ciphers("ALL:@SECLEVEL=0")
    except (ValueError, ssl.SSLError):
        pass
    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)

    def _on_message(conn, direction, version, content_type, msg_type, data):
        if (direction == "read" and content_type == ssl._TLSContentType.HANDSHAKE
                and msg_type == ssl._TLSMessageType.CERTIFICATE
                and version != ssl.TLSVersion.TLSv1_3):
            captured.append(bytes(data))

    context._msg_callback = _on_message
    return context


def _certs_from_handshake(messages: list[bytes]) -> list[x509.Certificate]:
    """TLS ≤1.2 Certificate mesajı: tip(1) uzunluk(3) liste-uzunluğu(3) {uzunluk(3) DER}*"""
    for msg in messages:
        body = msg[4:] if len(msg) > 4 and msg[0] == 11 else msg
        total = int.from_bytes(body[:3], "big")
        pos, end, certs = 3, min(3 + total, len(body)), []
        while pos + 3 <= end:
            n = int.from_bytes(body[pos:pos + 3], "big")
            pos += 3
            certs.append(x509.load_der_x509_certificate(body[pos:pos + n]))
            pos += n
        if certs:
            return certs
    return []


def _handshake(host: str, port: int, timeout: float) -> tuple[bytes | None, list | None]:
    captured: list[bytes] = []
    context = _probe_context(captured)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                leaf_der = tls.getpeercert(binary_form=True)
                raw_chain = tls.get_unverified_chain() if hasattr(tls, "get_unverified_chain") else None
                return leaf_der, raw_chain
    except (ssl.SSLError, ConnectionResetError, BrokenPipeError):
        certs = _certs_from_handshake(captured)
        if certs:
            logger.info("%s:%s el sıkışmayı tamamlamadı (ör. istemci sertifikası zorunlu); "
                        "sunucu sertifikası el sıkışma mesajından okundu", host, port)
            return None, [c.public_bytes(serialization.Encoding.DER) for c in certs]
        raise


def fetch_served_certificate(host: str, port: int, timeout: float = TIMEOUT_SECONDS) -> x509.Certificate:
    """Sertifika doğrulaması yapmadan (self-signed/iç CA olabilir) sunulan sertifikayı çeker."""
    return fetch_served_chain(host, port, timeout)[0]


def fetch_served_chain(host: str, port: int, timeout: float = TIMEOUT_SECONDS) -> list[x509.Certificate]:
    """Sunucunun el sıkışmada sunduğu TÜM zinciri (leaf → root sırasıyla) doğrulamasız çeker.

    get_unverified_chain Python 3.13+ gerektirir; yoksa yalnız leaf ile devam edilir.
    Dönen öğeler sürüme göre DER bytes veya ssl.Certificate olabilir — ikisi de desteklenir.
    """
    leaf_der, raw_chain = _handshake(host, port, timeout)
    certs: list[x509.Certificate] = []
    for item in raw_chain or []:
        der = item if isinstance(item, bytes) else item.public_bytes(ssl.ENCODING_DER)
        certs.append(x509.load_der_x509_certificate(der))
    if not certs:
        if not leaf_der:
            raise ssl.SSLError("Sunucu sertifika göndermedi")
        certs = [x509.load_der_x509_certificate(leaf_der)]
    return certs


def _cert_names(cert: x509.Certificate) -> tuple[list[str], list[str]]:
    """Sertifikanın kapsadığı DNS adları ve IP adresleri (SAN; SAN yoksa CN)."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = [n.lower().rstrip(".") for n in san.get_values_for_type(x509.DNSName)]
        ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        if dns or ips:
            return dns, ips
    except x509.ExtensionNotFound:
        pass
    cns = [str(a.value).lower().rstrip(".") for a in cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)]
    return cns, []


def _dns_match(pattern: str, host: str) -> bool:
    if pattern == host:
        return True
    # Wildcard yalnız en soldaki TEK etiketi kapsar: *.ornek.com → www.ornek.com (ornek.com ve a.b.ornek.com değil)
    if pattern.startswith("*.") and "." in host:
        first, rest = host.split(".", 1)
        return bool(first) and rest == pattern[2:]
    return False


def host_name_warning(host: str, cert: x509.Certificate) -> str | None:
    """Sunulan sertifika bağlanılan adresi kapsamıyorsa açıklama döner, kapsıyorsa None.

    Aynı sunucuda birden çok site varken sunucuda tanımlı olmayan bir ad yazılırsa sunucu
    başka bir sitenin (varsayılan) sertifikasını verir; bu sertifika domaine sessizce
    bağlanmamalı."""
    target = host.strip().lower().rstrip(".")
    try:
        target = target.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    try:
        # IP adresiyle bağlanıldığında sunucuya ad (SNI) gitmez; sunucu her zaman kendi tek
        # sertifikasını verir ve iç sistemlerin çoğunda bu sertifika IP'yi listelemez —
        # "başka sitenin sertifikası" riski yoktur, kontrol edilmez.
        ipaddress.ip_address(target.strip("[]"))
        return None
    except ValueError:
        pass
    dns, ips = _cert_names(cert)
    if any(_dns_match(p, target) for p in dns):
        return None
    names = ", ".join((dns + ips)[:5]) or "ad yok"
    return (f"Sunucunun verdiği sertifika '{host}' adresini kapsamıyor (sertifikadaki adlar: {names}). "
            "Sunucu bu adres için başka bir sitenin sertifikasını veriyor olabilir; adresi kontrol edin.")


def missing_intermediate(db: Session, served_list: list) -> str | None:
    """Yarım zincir: sunulan bir sertifikanın yayıncısı zincirde yok ve envanterde bu yayıncı
    bir ARA sertifika ise adını döner. Yayıncı kök ise sunulmaması normaldir (istemci kökü
    kendi tutar). Yayıncı envanterde hiç yoksa kök mü ara mı bilinemez; uyarı verilmez."""
    served_skis = {p.subject_key_identifier for p in served_list if p.subject_key_identifier}
    served_subjects = {p.subject for p in served_list}
    for p in served_list:
        if p.cert_type == "root" or p.issuer == p.subject:
            continue
        if (p.authority_key_identifier and p.authority_key_identifier in served_skis) \
                or p.issuer in served_subjects:
            continue
        if p.authority_key_identifier:
            parent = find_ca_by_ski(db, p.authority_key_identifier)
        else:
            parent = find_ca_by_issuer(db, p.issuer, p.pem_certificate)
        if parent is not None and normalize_cert_type(parent.cert_type) == "intermediate":
            return parent.name
    return None


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
    name_warning = host_name_warning(host, served_raw[0])

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

    # Yarım zincir: sunucu ara sertifikayı göndermiyor. Tarayıcılar eksik ara sertifikayı
    # çoğu zaman kendileri indirir ama Java, mobil ve API istemcileri bağlantı kuramaz.
    # Öneri üretilmez (düzeltme sunucuda yapılır); başka bir uyumsuzluk yoksa durum sarı olur.
    gap = missing_intermediate(db, served_list)
    if gap:
        detail["chain_warning"] = (f"Sunucu ara sertifikayı göndermiyor ({gap}). Tarayıcılar çoğu "
                                   f"zaman açar ama Java, mobil ve API istemcileri bağlantı "
                                   f"kuramayabilir; ara sertifika sunucuya kurulmalı.")
        if domain.live_check_status == "match":
            domain.live_check_status = "chain_incomplete"
            detail["reason"] = detail["chain_warning"]

    # Sunucuda envanterde PASİF olan bir sertifika sunuluyorsa (yerine yenisi geçmiş ama
    # sunucuya kurulmamış) durum yeşil görünmemeli: pasif sertifika bağlanamaz, sunucu güncellenmeli.
    inactive_served = [
        c.name for c in (db.query(Certificate)
                         .filter(Certificate.fingerprint_sha256.in_(
                             [s.fingerprint_sha256 for s in served_list]),
                                 Certificate.is_active == False).all())]  # noqa: E712
    if inactive_served:
        domain.live_check_status = "mismatch"
        detail["inactive_served"] = inactive_served
        detail["reason"] = ("Sunucuda envanterde PASİF olan sertifika sunuluyor: "
                            + ", ".join(inactive_served) + " — sunucudaki sertifika güncellenmeli")

    # Sunulan sertifika yazılan adresi kapsamıyorsa (ör. sunucu tanımadığı ad için varsayılan
    # sitenin sertifikasını verdi) not düşülür; domaine zaten bilerek bağlanmamışsa durum
    # yeşil olamaz ve zincir senkronizasyonu bu sertifikayı öneri olarak da getirmez.
    leaf_bound = any(leaf_served.fingerprint_sha256 in pool for pool in bound_by_type.values())
    if name_warning:
        detail["name_warning"] = name_warning
        if not leaf_bound:
            domain.live_check_status = "mismatch"
            if "inactive_served" not in detail:
                detail["reason"] = name_warning

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
    if not name_warning or leaf_bound:
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
