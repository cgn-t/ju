"""Certificate Transparency (crt.sh) izleme — keşfin ikinci yarısı.

Envanter domainlerini crt.sh JSON API'sinden sorgular; CT loglarında GÖRÜNEN ama envanterde OLMAYAN
(ağdan hiç görülmemiş) sertifikaları "shadow" bulgu (DiscoveredCertificate, origin="ct") olarak kaydeder.
Aktif ağ taramasının (discovery.py) tersine ağa TLS bağlantısı kurmaz — yalnız CT loglarını okur.

EGRESS: crt.sh'e DIŞ İNTERNET ERİŞİMİ gerekir. Kapalı banka/OpenShift ağında erişilemeyebilir → özellik
varsayılan KAPALI, opsiyonel forward proxy (proxy_url), ve erişilemezse graceful degrade (ScanRun.error'a
yazılır, çökme yok; diğer domainler işlenmeye devam eder). Sertifika ÜRETİMİ/YENİLEMESİ burada YOK.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import DiscoveredCertificate, Domain, ScanRun
from app.services.cert_parser import ParsedCertificate, find_existing, parse_x509
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)

CRTSH_BASE = "https://crt.sh/"
# RFC 6962 §3.1 CT "poison" uzantısı — bir precertificate'i işaretler. Precert'ler gerçekten sunulan
# sertifika DEĞİLDİR (yalnız issuance niyeti); shadow gürültüsünü azaltmak için atlanır.
_CT_POISON_OID = ObjectIdentifier("1.3.6.1.4.1.11129.2.4.3")


def get_config(db: Session) -> dict:
    return get_category(db, "ct", mask_secrets=False)


def _client(config: dict) -> httpx.Client:
    """crt.sh için httpx istemcisi. proxy_url verilmişse forward proxy üzerinden gider (kapalı ağ)."""
    return httpx.Client(
        proxy=(config.get("proxy_url") or None),
        timeout=float(config.get("timeout_seconds") or 15),
        headers={"User-Agent": "JUMBO-CLM/ct-monitor"},
        follow_redirects=True,
    )


def _query_host(domain_value: str | None, match_wildcards: bool) -> str | None:
    """Envanter domain değerinden crt.sh'e sorulacak host'u çıkarır. '(...)' etiketi ve ':port' atılır.
    '*.aaakkk.com' → match_wildcards ise 'aaakkk.com', değilse atlanır."""
    v = re.sub(r"\(.*?\)", "", domain_value or "").strip()
    v = v.split(":")[0].strip()
    if not v:
        return None
    if v.startswith("*."):
        return v[2:].lower() if match_wildcards else None
    if v.startswith("*"):
        return None
    return v.lower()


def domains_to_query(db: Session, config: dict) -> list[str]:
    """Envanter Domain'lerinden benzersiz sorgu host'ları (max_domains ile sınırlı)."""
    match_wildcards = bool(config.get("match_wildcards", True))
    max_domains = int(config.get("max_domains") or 0)
    hosts: list[str] = []
    seen: set[str] = set()
    for dom in db.query(Domain).all():
        host = _query_host(dom.domain, match_wildcards)
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    if max_domains > 0 and len(hosts) > max_domains:
        logger.warning("CT: domain sayısı max_domains=%s sınırına ulaştı, kalan %s atlandı",
                       max_domains, len(hosts) - max_domains)
        hosts = hosts[:max_domains]
    return hosts


def query_crtsh(host: str, client: httpx.Client) -> list[dict]:
    """crt.sh JSON API'sinden bir host'un CT giriş listesini çeker. Ağ/parse hatası YÜKSELİR
    (çağıran per-domain yakalar). Boş yanıt → []."""
    resp = client.get(CRTSH_BASE, params={"q": host, "output": "json"})
    resp.raise_for_status()
    text = resp.text.strip()
    if not text:
        return []
    return resp.json()


def download_cert(crtsh_id: str, client: httpx.Client) -> x509.Certificate:
    """crt.sh '?d=<id>' ile tek sertifikayı indirir (PEM ya da DER)."""
    resp = client.get(CRTSH_BASE, params={"d": str(crtsh_id)})
    resp.raise_for_status()
    data = resp.content
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError:
        return x509.load_der_x509_certificate(data)


def _is_precertificate(cert: x509.Certificate) -> bool:
    try:
        cert.extensions.get_extension_for_oid(_CT_POISON_OID)
        return True
    except x509.ExtensionNotFound:
        return False


def _fetch_and_parse(crtsh_id: str, client: httpx.Client) -> tuple[ParsedCertificate, str] | None:
    """Bir CT girişini indirip parse eder. Precert / indirme / parse hatası → None (atla).
    YALNIZ ağ + CPU; DB'ye DOKUNMAZ (thread havuzunda güvenli çalışır)."""
    try:
        cert = download_cert(crtsh_id, client)
        if _is_precertificate(cert):
            return None
        return parse_x509(cert), str(crtsh_id)
    except Exception:
        return None


def _upsert_ct_finding(db: Session, domain: str, parsed: ParsedCertificate,
                       crtsh_id: str) -> tuple[bool, str]:
    """CT bulgusunu ekler/günceller (host=domain, port=0, origin='ct'). Kullanıcı kararı verilmiş
    (adopted/ignored) bulguların status'una DOKUNULMAZ. Döner: (yeni_mi, status)."""
    in_inventory = find_existing(db, parsed) is not None
    status = "in_inventory" if in_inventory else "new"
    now = utcnow()
    finding = (db.query(DiscoveredCertificate)
               .filter(DiscoveredCertificate.host == domain,
                       DiscoveredCertificate.port == 0,
                       DiscoveredCertificate.fingerprint_sha256 == parsed.fingerprint_sha256)
               .first())
    if finding is not None:
        finding.last_seen_at = now
        if finding.status not in ("adopted", "ignored"):
            finding.status = status
        if not finding.crtsh_id and crtsh_id:
            finding.crtsh_id = crtsh_id
        return False, finding.status
    finding = DiscoveredCertificate(
        host=domain, port=0, origin="ct", crtsh_id=crtsh_id,
        fingerprint_sha256=parsed.fingerprint_sha256, name=parsed.name, issuer=parsed.issuer,
        subject=parsed.subject, san=parsed.san, serial_number=parsed.serial_number,
        valid_from=parsed.valid_from, valid_to=parsed.valid_to,
        pem_certificate=parsed.pem_certificate, status=status, sy_team_id=None,
        first_seen_at=now, last_seen_at=now)
    db.add(finding)
    return True, status


def _execute_ct_scan(db: Session, run: ScanRun) -> ScanRun:
    """CT taramasını yürütür. Her domain için crt.sh sorgulanır; indirme/parse ağ I/O thread havuzunda,
    DB yazımı YALNIZ ana thread'de. Bir domain erişilemezse hatası kaydedilir, diğerleri sürer."""
    config = get_config(db)
    max_entries = int(config.get("max_entries_per_domain") or 100)
    concurrency = max(1, int(config.get("concurrency") or 4))

    hosts = domains_to_query(db, config)
    run.targets_scanned = len(hosts)
    run.status = "running"
    db.commit()

    reachable = 0
    new_count = 0
    errors: list[str] = []

    with _client(config) as client:
        for host in hosts:
            try:
                entries = query_crtsh(host, client)
            except Exception as exc:
                errors.append(f"{host}: {type(exc).__name__}")
                logger.warning("CT: %s sorgulanamadı: %s", host, exc)
                continue
            reachable += 1

            # crt.sh kendi id'siyle tekilleştir; en yeni girişlerden max_entries kadarını işle.
            ids: list[str] = []
            seen_ids: set[str] = set()
            for e in entries:
                cid = str(e.get("id") or "").strip()
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    ids.append(cid)
            if len(ids) > max_entries:
                ids = ids[:max_entries]

            parsed_results: list[tuple[ParsedCertificate, str]] = []
            if ids:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = {pool.submit(_fetch_and_parse, cid, client): cid for cid in ids}
                    for fut in as_completed(futures):
                        r = fut.result()
                        if r is not None:
                            parsed_results.append(r)

            for parsed, cid in parsed_results:
                created, status = _upsert_ct_finding(db, host, parsed, cid)
                if created and status == "new":
                    new_count += 1
            db.commit()

    run.hosts_reachable = reachable
    run.new_findings = new_count
    run.finished_at = utcnow()
    run.status = "done"
    if errors:
        run.error = ("; ".join(errors))[:500]
    db.commit()
    logger.info("CT taraması bitti: %s domain, %s erişilebilir, %s yeni shadow bulgu",
                run.targets_scanned, run.hosts_reachable, run.new_findings)
    return run


def run_ct_scan(db: Session, trigger: str = "manual", created_by: str | None = None) -> ScanRun:
    """Senkron CT taraması (verilen session'da). Testler ve doğrudan çağrılar için."""
    run = ScanRun(status="running", trigger=trigger, kind="ct", created_by=created_by)
    db.add(run)
    db.flush()
    return _execute_ct_scan(db, run)


def run_ct_scan_by_id(run_id: int) -> None:
    """Arka plan thread girişi: önceden oluşturulmuş CT ScanRun'ı KENDİ session'ında yürütür."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        run = db.get(ScanRun, run_id)
        if run is None:
            return
        _execute_ct_scan(db, run)
    except Exception as exc:
        db.rollback()
        logger.exception("CT taraması hatası (run #%s)", run_id)
        run = db.get(ScanRun, run_id)
        if run is not None:
            run.status = "error"
            run.error = str(exc)[:500]
            run.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def run_ct_scan_job() -> None:
    """Zamanlanmış gece işi (APScheduler). Yalnız CT izleme ETKİNSE çalışır."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        config = get_config(db)
        if not config.get("enabled"):
            logger.info("CT izleme kapalı — zamanlanmış tarama atlandı")
            return
        run = ScanRun(status="running", trigger="schedule", kind="ct")
        db.add(run)
        db.commit()
        _execute_ct_scan(db, run)
    except Exception:
        db.rollback()
        logger.exception("Zamanlanmış CT taraması hatası")
    finally:
        db.close()
