"""Ağ keşfi (network discovery) — aktif tarama.

Tanımlı hedeflerden (CIDR aralığı / tekil host / envanter domainleri) TLS handshake ile SUNULAN
sertifikayı çeker, envanterle (fingerprint) karşılaştırır ve envanterde OLMAYAN ("shadow")
sertifikaları kalıcı bulgu (DiscoveredCertificate) olarak kaydeder.

GÜVENLİK/OPERASYON: Aktif tarama port-scan gibi görünür. Bu yüzden yalnız TANIMLI portlara TLS
handshake yapılır (tam port taraması YOK), eşzamanlılık ve toplam host sayısı sınırlanır, devasa CIDR
reddedilir. Keşif varsayılan KAPALIdır; hedef VLAN'lar için ağ/güvenlik ekibi onayı ve container→VLAN
firewall/routing izni gerekir. Sertifika ÜRETİMİ/YENİLEMESİ burada YOK — yalnız envanterleme.
"""

import ipaddress
import logging
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import Certificate, DiscoveredCertificate, Domain, ScanRun, ScanTarget
from app.services.cert_parser import ParsedCertificate, find_existing, parse_x509
from app.services.live_check import fetch_served_certificate, parse_target
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)

# Tek bir CIDR hedefinin üretebileceği azami adres sayısı (≈ /16). Daha büyük ağlar (kurumsal /8-/12)
# yanlışlıkla girilirse reddedilir — toplam max_hosts sınırından ayrı, tekil hedef güvenlik freni.
MAX_CIDR_ADDRESSES = 65536


def get_config(db: Session) -> dict:
    return get_category(db, "discovery", mask_secrets=False)


def parse_ports(raw: str | None) -> list[int]:
    """'443,8443, 9443' → [443, 8443, 9443]. Geçersiz/aralık dışı atlanır."""
    ports: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            p = int(part)
        except ValueError:
            continue
        if 1 <= p <= 65535 and p not in ports:
            ports.append(p)
    return ports


def expand_targets(db: Session, config: dict) -> list[tuple[str, int, int | None]]:
    """Etkin ScanTarget'ları (host, port, sy_team_id) üçlülerine genişletir. sy_team_id, o hedefi
    üreten ScanTarget'ın SY ekibidir (benimsemede sertifikanın "Oluşturan"ı olur). Aynı (host,port)
    birden çok hedeften gelirse İLK hedefin ekibi kalır. Toplam sayı max_hosts ile SINIRLANIR; kesilen
    kısım log'lanır (sessiz kırpma yok). Devasa CIDR'ler atlanıp uyarı verilir."""
    default_ports = parse_ports(config.get("default_ports")) or [443]
    max_hosts = int(config.get("max_hosts") or 4096)

    targets: list[tuple[str, int, int | None]] = []
    seen: set[tuple[str, int]] = set()
    truncated = False

    def add(host: str | None, port: int, team_id: int | None) -> bool:
        """Hedefi ekler; max_hosts'a ulaşıldıysa False döner (dur işareti)."""
        nonlocal truncated
        if not host:
            return True
        key = (host, port)
        if key in seen:
            return True
        if len(targets) >= max_hosts:
            truncated = True
            return False
        seen.add(key)
        targets.append((host, port, team_id))
        return True

    rows = db.query(ScanTarget).filter(ScanTarget.enabled == True).all()  # noqa: E712 (MSSQL: == True)
    for t in rows:
        ports = parse_ports(t.ports) or default_ports
        if t.kind == "inventory":
            for dom in db.query(Domain).all():
                host, port = parse_target(dom.domain)
                if not add(host, port, t.sy_team_id):
                    break
            if truncated:
                break
            continue
        if t.kind == "host":
            host, _ = parse_target(t.value or "")
            for port in ports:
                if not add(host, port, t.sy_team_id):
                    break
            if truncated:
                break
            continue
        if t.kind == "cidr":
            try:
                net = ipaddress.ip_network((t.value or "").strip(), strict=False)
            except ValueError:
                logger.warning("Keşif: geçersiz CIDR atlandı: %r (hedef #%s)", t.value, t.id)
                continue
            if net.num_addresses > MAX_CIDR_ADDRESSES:
                logger.warning("Keşif: çok büyük CIDR atlandı (%s adres > %s): %s",
                               net.num_addresses, MAX_CIDR_ADDRESSES, t.value)
                continue
            hosts = net.hosts() if net.num_addresses > 2 else net  # /31,/32 için tüm adresler
            stop = False
            for ip in hosts:
                for port in ports:
                    if not add(str(ip), port, t.sy_team_id):
                        stop = True
                        break
                if stop:
                    break
            if truncated:
                break

    if truncated:
        logger.warning("Keşif: hedef sayısı max_hosts=%s sınırına ulaştı, kalan hedefler ATLANDI "
                       "(daha küçük CIDR veya daha yüksek max_hosts kullanın).", max_hosts)
    return targets


def scan_endpoint(host: str, port: int, timeout: float) -> ParsedCertificate | None:
    """Tek endpoint'i tarar: TLS'te sunulan leaf sertifikayı parse eder. Erişilemezse None (bulgu yok)."""
    try:
        return parse_x509(fetch_served_certificate(host, port, timeout))
    except Exception:
        return None


def _upsert_finding(db: Session, host: str, port: int, parsed: ParsedCertificate,
                    sy_team_id: int | None) -> tuple[bool, str]:
    """Bulguyu ekler/günceller. Döner: (yeni_mi, status). Kullanıcı kararı verilmiş (adopted/ignored)
    bulguların status'una DOKUNULMAZ; yalnız last_seen_at güncellenir. sy_team_id (hedefin ekibi)
    ilk kez set edilir; sonra None'sa geriye doldurulur (mevcut ekip ezilmez)."""
    in_inventory = find_existing(db, parsed) is not None
    status = "in_inventory" if in_inventory else "new"
    now = utcnow()
    finding = (db.query(DiscoveredCertificate)
               .filter(DiscoveredCertificate.host == host,
                       DiscoveredCertificate.port == port,
                       DiscoveredCertificate.fingerprint_sha256 == parsed.fingerprint_sha256)
               .first())
    if finding is not None:
        finding.last_seen_at = now
        if finding.status not in ("adopted", "ignored"):
            finding.status = status
        if finding.sy_team_id is None and sy_team_id is not None:
            finding.sy_team_id = sy_team_id
        return False, finding.status
    finding = DiscoveredCertificate(
        host=host, port=port, fingerprint_sha256=parsed.fingerprint_sha256,
        name=parsed.name, issuer=parsed.issuer, subject=parsed.subject, san=parsed.san,
        serial_number=parsed.serial_number, valid_from=parsed.valid_from, valid_to=parsed.valid_to,
        pem_certificate=parsed.pem_certificate, status=status, sy_team_id=sy_team_id,
        first_seen_at=now, last_seen_at=now)
    db.add(finding)
    return True, status


def _execute_scan(db: Session, run: ScanRun) -> ScanRun:
    """Verilen ScanRun için taramayı yürütür. Ağ I/O thread havuzunda (bloklayan socket + timeout);
    DB yazımı YALNIZ ana thread'de (Session thread-safe değildir)."""
    config = get_config(db)
    targets = expand_targets(db, config)
    run.targets_scanned = len(targets)
    run.status = "running"
    db.commit()

    timeout = float(config.get("timeout_seconds") or 6)
    concurrency = max(1, int(config.get("concurrency") or 32))

    results: list[tuple[str, int, int | None, ParsedCertificate]] = []
    if targets:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_map = {pool.submit(scan_endpoint, host, port, timeout): (host, port, team_id)
                          for host, port, team_id in targets}
            for fut in as_completed(future_map):
                host, port, team_id = future_map[fut]
                parsed = fut.result()
                if parsed is not None:
                    results.append((host, port, team_id, parsed))

    new_count = 0
    for host, port, team_id, parsed in results:
        created, status = _upsert_finding(db, host, port, parsed, team_id)
        if created and status == "new":
            new_count += 1

    run.hosts_reachable = len(results)
    run.new_findings = new_count
    run.finished_at = utcnow()
    run.status = "done"
    db.commit()
    logger.info("Keşif taraması bitti: %s hedef, %s erişilebilir, %s yeni shadow bulgu",
                run.targets_scanned, run.hosts_reachable, run.new_findings)
    return run


def run_scan(db: Session, trigger: str = "manual", created_by: str | None = None) -> ScanRun:
    """Senkron tarama (verilen session'da). Testler ve doğrudan çağrılar için."""
    run = ScanRun(status="running", trigger=trigger, created_by=created_by)
    db.add(run)
    db.flush()
    return _execute_scan(db, run)


def run_scan_by_id(run_id: int) -> None:
    """Arka plan thread girişi: önceden oluşturulmuş ScanRun'ı KENDİ session'ında yürütür."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        run = db.get(ScanRun, run_id)
        if run is None:
            return
        _execute_scan(db, run)
    except Exception as exc:
        db.rollback()
        logger.exception("Keşif taraması hatası (run #%s)", run_id)
        run = db.get(ScanRun, run_id)
        if run is not None:
            run.status = "error"
            run.error = str(exc)[:500]
            run.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def run_scan_job() -> None:
    """Zamanlanmış gece işi (APScheduler). Yalnız keşif ETKİNSE çalışır."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        config = get_config(db)
        if not config.get("enabled"):
            logger.info("Keşif kapalı — zamanlanmış tarama atlandı")
            return
        run = ScanRun(status="running", trigger="schedule")
        db.add(run)
        db.commit()
        _execute_scan(db, run)
    except Exception:
        db.rollback()
        logger.exception("Zamanlanmış keşif taraması hatası")
    finally:
        db.close()


def detect_local_cidr() -> dict:
    """Container'ın birincil IPv4'ünü ve /24 ağını ÖNERİ olarak döner (otomatik eklemez).
    OpenShift'te bu pod SDN adresidir — asıl sunucu VLAN'ları değildir; yalnız başlangıç tohumu."""
    ip = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP 'connect' paket GÖNDERMEZ; yalnız route'un kaynak arayüz IP'sini seçtirir.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = None
    finally:
        sock.close()
    if not ip:
        return {"local_ip": None, "suggested_cidr": None,
                "note": "Yerel IP tespit edilemedi (varsayılan route yok olabilir)."}
    network = ipaddress.ip_interface(f"{ip}/24").network
    return {"local_ip": ip, "suggested_cidr": str(network),
            "note": ("Bu, container'ın kendi /24'üdür (OpenShift'te pod ağı). Sunucu VLAN'ları "
                     "genelde ayrıdır — asıl kapsam için o VLAN CIDR'lerini ekleyin.")}
