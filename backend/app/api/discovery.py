"""Ağ keşfi (network discovery) API.

TÜM keşif uçları ADMIN-ONLY (kullanıcı kararı: "Keşif kısmı sadece admin rolüne görünsün"). Bulgu
görüntüleme, benimseme/yok sayma, hedef yönetimi, tarama tetikleme ve yerel-CIDR önerisi — hepsi admin.
Aktif tarama yalnız admin'in açık isteğiyle (POST /scan) veya gece cron'uyla çalışır; motor güvenlik
sınırlarını (tanımlı portlar, max_hosts, eşzamanlılık) uygular (bkz. services/discovery.py).
"""

import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.schemas import (
    DiscoveredCertificateDetail,
    DiscoveredCertificateOut,
    ScanRunOut,
    ScanTargetCreate,
    ScanTargetOut,
    ScanTargetUpdate,
)
from app.core.security import require_role
from app.core.timeutil import utcnow
from app.db.models import (
    Certificate,
    DiscoveredCertificate,
    Domain,
    ScanRun,
    ScanTarget,
    Team,
    User,
)
from app.db.session import get_db
from app.services import ct_monitor, discovery
from app.services.audit import log_action
from app.services.cert_parser import (
    find_existing,
    parse_pem_text,
    parse_x509,
    relink_children,
    resolve_parent,
)
from app.services.live_check import fetch_served_chain

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


# ---- yardımcılar ----
def _days_left(finding: DiscoveredCertificate) -> int | None:
    if finding.valid_to is None:
        return None
    return (finding.valid_to - utcnow()).days


def _matched_map(db: Session, findings: list[DiscoveredCertificate]) -> dict[str, Certificate]:
    """Bulguların fingerprint'lerini envanterdeki sertifikaya (varsa) toplu eşler."""
    fps = {f.fingerprint_sha256 for f in findings if f.fingerprint_sha256}
    if not fps:
        return {}
    rows = (db.query(Certificate)
            .filter(Certificate.fingerprint_sha256.in_(fps)).all())
    return {c.fingerprint_sha256: c for c in rows}


def _team_map(db: Session, findings: list[DiscoveredCertificate]) -> dict[int, str]:
    """Bulguların sy_team_id'lerini ekip adına toplu eşler (FK yok, okuma anında çözülür)."""
    ids = {f.sy_team_id for f in findings if f.sy_team_id is not None}
    if not ids:
        return {}
    return {t.id: t.name for t in db.query(Team).filter(Team.id.in_(ids)).all()}


def _finding_out(finding: DiscoveredCertificate, matched: dict[str, Certificate],
                 teams: dict[int, str], *, detail: bool = False):
    cert = matched.get(finding.fingerprint_sha256)
    common = dict(
        id=finding.id, host=finding.host, port=finding.port,
        fingerprint_sha256=finding.fingerprint_sha256, name=finding.name,
        issuer=finding.issuer, subject=finding.subject, san=finding.san,
        serial_number=finding.serial_number, valid_from=finding.valid_from,
        valid_to=finding.valid_to, days_left=_days_left(finding), status=finding.status,
        origin=finding.origin,
        matched_certificate_id=cert.id if cert else None,
        matched_certificate_name=cert.name if cert else None,
        sy_team_id=finding.sy_team_id,
        sy_team_name=teams.get(finding.sy_team_id) if finding.sy_team_id else None,
        first_seen_at=finding.first_seen_at, last_seen_at=finding.last_seen_at, note=finding.note)
    if detail:
        return DiscoveredCertificateDetail(pem_certificate=finding.pem_certificate,
                                           crtsh_id=finding.crtsh_id, **common)
    return DiscoveredCertificateOut(**common)


def _target_out(t: ScanTarget) -> ScanTargetOut:
    return ScanTargetOut(
        id=t.id, name=t.name, kind=t.kind, value=t.value, ports=t.ports, enabled=t.enabled,
        sy_team_id=t.sy_team_id, sy_team_name=t.sy_team.name if t.sy_team else None,
        created_at=t.created_at, updated_at=t.updated_at)


# ---- Bulgular (findings) — GLOBAL görünür ----
@router.get("/findings", response_model=list[DiscoveredCertificateOut])
def list_findings(status: str | None = Query(None), only_new: bool = False,
                  origin: str | None = Query(None),
                  db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Keşif bulguları. status ile süz (new|in_inventory|adopted|ignored); only_new=true → yalnız shadow;
    origin ile süz (network=aktif tarama | ct=crt.sh)."""
    q = db.query(DiscoveredCertificate)
    if only_new:
        q = q.filter(DiscoveredCertificate.status == "new")
    elif status:
        q = q.filter(DiscoveredCertificate.status == status)
    if origin:
        q = q.filter(DiscoveredCertificate.origin == origin)
    findings = q.order_by(DiscoveredCertificate.last_seen_at.desc()).all()
    matched = _matched_map(db, findings)
    teams = _team_map(db, findings)
    return [_finding_out(f, matched, teams) for f in findings]


@router.get("/findings/{finding_id}", response_model=DiscoveredCertificateDetail)
def get_finding(finding_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_role("admin"))):
    finding = db.get(DiscoveredCertificate, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")
    return _finding_out(finding, _matched_map(db, [finding]), _team_map(db, [finding]), detail=True)


@router.post("/findings/{finding_id}/adopt")
def adopt_finding(request: Request, finding_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    """Bulguyu envantere alır ve zinciri SKI/AKI ile hiyerarşiye bağlar.

    Ağ bulgusunda (canlı endpoint) benimseme anında sunulan TÜM zincir canlı çekilir → leaf
    + intermediate'ler birlikte envantere girer (tıpkı domain chain-import gibi). Ancak canlı zincir
    çekilemezse VEYA endpoint artık BU bulgunun leaf'ini sunmuyorsa (rotate) saklı PEM'e düşülür —
    yani keşfedilen sertifika her hâlükârda envantere alınır, adopt asla çökmez. CT bulgusunda
    (port=0) canlı bağlantı yoktur; doğrudan saklı PEM parse edilir. Zaten envanterdeki sertifikalar
    atlanır; bulgu 'adopted' işaretlenir."""
    finding = db.get(DiscoveredCertificate, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")

    is_ct = finding.origin == "ct"
    parsed_list: list | None = None
    chain_fetched = False
    # Ağ bulgusu + gerçek port → canlı zinciri çekmeyi dene (intermediate'ler de bağlansın).
    if not is_ct and finding.port:
        try:
            candidate = [parse_x509(c) for c in fetch_served_chain(finding.host, finding.port)]
            # Endpoint hâlâ BU bulgunun leaf'ini mi sunuyor? Rotate etmişse canlı zinciri KULLANMA,
            # saklı PEM'e düş → keşfedilen sertifikayı aynen al (yanlış cert'i envantere sokma).
            if any(p.fingerprint_sha256 == finding.fingerprint_sha256 for p in candidate):
                parsed_list, chain_fetched = candidate, True
        except Exception:
            parsed_list = None  # erişilemez / eski Python (get_unverified_chain yok) → saklı PEM'e düş
    if parsed_list is None:
        if not finding.pem_certificate:
            raise HTTPException(status_code=400,
                                detail="Bu bulgunun saklı PEM'i yok, envantere alınamaz")
        try:
            parsed_list = parse_pem_text(finding.pem_certificate)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    # Önce CA'lar eklensin ki leaf parent bulabilsin (domain chain-import ile aynı sıra).
    parsed_list.sort(key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type])

    # "Oluşturan" (creator) = bulguyu üreten tarama hedefinin SY ekibi; ekip yoksa işlemi yapan kullanıcı.
    # (Kullanıcı kuralı: hedefe hangi takımı verdiysem envanterdeki kayıt da aynı ekiple oluşsun.)
    creator = user.username
    if finding.sy_team_id is not None:
        team = db.get(Team, finding.sy_team_id)
        if team is not None:
            creator = team.name

    src = "ct" if is_ct else "discovery"
    note = (f"CT logunda bulundu (crt.sh): {finding.host}"
            if is_ct else f"Ağ keşfi ile bulundu: {finding.host}:{finding.port}")
    created_names: list[str] = []
    for parsed in parsed_list:
        if find_existing(db, parsed):
            continue
        cert = Certificate(**parsed.__dict__, creator=creator, source=src, notes=note)
        cert.parent_id = resolve_parent(db, parsed)
        db.add(cert)
        db.flush()
        relink_children(db, cert)
        log_action(db, user.username, "import", "certificates", cert.id,
                   {"name": cert.name, "via": "discovery-adopt",
                    "endpoint": f"{finding.host}:{finding.port}", "chain": chain_fetched}, request)
        created_names.append(cert.name)

    finding.status = "adopted"
    log_action(db, user.username, "adopt", "discovered_certificates", finding.id,
               {"host": finding.host, "port": finding.port, "created": created_names,
                "chain": chain_fetched}, request)
    db.commit()
    if not created_names:
        return {"created": [], "message": "Sertifika(lar) zaten envanterde; bulgu 'Envantere Alındı' işaretlendi"}
    src_label = "CT log" if is_ct else "ağ keşfi"
    suffix = " — zincir canlı çekilip bağlandı" if chain_fetched else ""
    return {"created": created_names,
            "message": f"{len(created_names)} sertifika envantere alındı (kaynak: {src_label}){suffix}"}


@router.post("/findings/{finding_id}/ignore")
def ignore_finding(request: Request, finding_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    """Bulguyu 'yok sayıldı' işaretler — yeniden taramada status'u DEĞİŞMEZ (bilinçli göz ardı)."""
    finding = db.get(DiscoveredCertificate, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")
    finding.status = "ignored"
    log_action(db, user.username, "ignore", "discovered_certificates", finding.id,
               {"host": finding.host, "port": finding.port}, request)
    db.commit()
    return {"status": "ignored"}


# ---- Tarama hedefleri (targets) — admin ----
@router.get("/targets", response_model=list[ScanTargetOut])
def list_targets(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    rows = db.query(ScanTarget).order_by(ScanTarget.id.asc()).all()
    return [_target_out(t) for t in rows]


@router.post("/targets", response_model=ScanTargetOut)
def create_target(request: Request, body: ScanTargetCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    _validate_target(body.kind, body.value, body.ports)
    if body.sy_team_id is not None and db.get(Team, body.sy_team_id) is None:
        raise HTTPException(status_code=400, detail="Geçersiz SY ekip")
    t = ScanTarget(name=body.name, kind=body.kind,
                   value=(body.value or None) if body.kind != "inventory" else None,
                   ports=body.ports or None, enabled=body.enabled, sy_team_id=body.sy_team_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    log_action(db, user.username, "create", "scan_targets", t.id,
               {"name": t.name, "kind": t.kind, "value": t.value}, request)
    db.commit()
    return _target_out(t)


@router.put("/targets/{target_id}", response_model=ScanTargetOut)
def update_target(request: Request, target_id: int, body: ScanTargetUpdate,
                  db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    t = db.get(ScanTarget, target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Hedef bulunamadı")
    if body.value is not None or body.ports is not None:
        _validate_target(t.kind, body.value if body.value is not None else t.value,
                         body.ports if body.ports is not None else t.ports)
    if body.name is not None:
        t.name = body.name
    if body.value is not None:
        t.value = body.value or None
    if body.ports is not None:
        t.ports = body.ports or None
    if body.enabled is not None:
        t.enabled = body.enabled
    if body.sy_team_id is not None:
        if db.get(Team, body.sy_team_id) is None:
            raise HTTPException(status_code=400, detail="Geçersiz SY ekip")
        t.sy_team_id = body.sy_team_id
    log_action(db, user.username, "update", "scan_targets", t.id, {"name": t.name}, request)
    db.commit()
    db.refresh(t)
    return _target_out(t)


@router.delete("/targets/{target_id}")
def delete_target(request: Request, target_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    t = db.get(ScanTarget, target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Hedef bulunamadı")
    db.delete(t)
    log_action(db, user.username, "delete", "scan_targets", target_id, {"name": t.name}, request)
    db.commit()
    return {"deleted": True}


@router.post("/targets/detect-local")
def detect_local(_: User = Depends(require_role("admin"))):
    """Container'ın yerel /24'ünü ÖNERİ olarak döner (otomatik eklemez)."""
    return discovery.detect_local_cidr()


def _validate_target(kind: str, value: str | None, ports: str | None) -> None:
    """Hedefi kaydetmeden önce doğrular: CIDR/host değeri ve portlar parse edilebilir mi, CIDR devasa mı."""
    if ports and not discovery.parse_ports(ports):
        raise HTTPException(status_code=400, detail="Geçersiz port listesi (ör. '443,8443')")
    if kind == "inventory":
        return
    if not value:
        raise HTTPException(status_code=400, detail=f"'{kind}' hedefi için değer gerekli")
    if kind == "cidr":
        import ipaddress
        try:
            net = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz CIDR (ör. '10.1.2.0/24')")
        if net.num_addresses > discovery.MAX_CIDR_ADDRESSES:
            raise HTTPException(status_code=400, detail=(
                f"CIDR çok büyük ({net.num_addresses} adres). En fazla "
                f"{discovery.MAX_CIDR_ADDRESSES} adres (≈/16) — daha küçük aralıklara bölün."))


# ---- Tarama çalıştırma ----
@router.post("/scan")
def trigger_scan(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin"))):
    """Taramayı arka planda başlatır (admin'in açık isteği; global 'enabled' bayrağından bağımsız).
    ScanRun kaydı hemen oluşturulur; motor ayrı bir thread'de kendi session'ında yürür."""
    if not db.query(ScanTarget).filter(ScanTarget.enabled == True).first():  # noqa: E712
        raise HTTPException(status_code=400, detail="Etkin tarama hedefi yok — önce hedef ekleyin")
    run = ScanRun(status="running", trigger="manual", created_by=user.username)
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    log_action(db, user.username, "scan", "scan_runs", run_id, {"trigger": "manual"}, request)
    db.commit()
    threading.Thread(target=discovery.run_scan_by_id, args=(run_id,), daemon=True).start()
    return {"run_id": run_id, "message": "Ağ taraması başlatıldı — sonuçlar bittikçe bulgulara yansır"}


@router.post("/ct-scan")
def trigger_ct_scan(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin"))):
    """CT (crt.sh) taramasını arka planda başlatır (admin'in açık isteği; global 'ct.enabled'dan bağımsız).
    Envanter domainleri crt.sh'ten sorgulanır; DIŞ İNTERNET/proxy erişimi yoksa ScanRun'a hata yazılır
    (bulgu üretilmeden) — bu bilinçli: kapalı ağda özellik sessizce başarısız olur, çökmez."""
    if not db.query(Domain).first():
        raise HTTPException(status_code=400, detail="Envanterde domain yok — CT için önce domain ekleyin")
    run = ScanRun(status="running", trigger="manual", kind="ct", created_by=user.username)
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    log_action(db, user.username, "ct-scan", "scan_runs", run_id, {"trigger": "manual"}, request)
    db.commit()
    threading.Thread(target=ct_monitor.run_ct_scan_by_id, args=(run_id,), daemon=True).start()
    return {"run_id": run_id, "message": "CT taraması başlatıldı — sonuçlar bittikçe bulgulara yansır"}


@router.get("/runs", response_model=list[ScanRunOut])
def list_runs(limit: int = Query(10, ge=1, le=100), kind: str | None = Query(None),
              db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    q = db.query(ScanRun)
    if kind:
        q = q.filter(ScanRun.kind == kind)
    return q.order_by(ScanRun.started_at.desc()).limit(limit).all()
