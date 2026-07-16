import csv
import io
from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    ChainImportOut,
    ChainProbeCert,
    ChainProbeOut,
    ChainProbeRequest,
    DomainCreate,
    DomainOut,
    DomainUpdate,
    MappedCertOut,
    MappingCreate,
)
from app.core.security import (
    can_manage_team_resource,
    domain_scope_team_ids,
    require_role,
    user_team_ids,
)
from app.db.models import (
    AppDependency,
    Certificate,
    CertificateDomainMap,
    Domain,
    Team,
    TransferProposal,
    User,
)
from app.db.session import get_db
from app.services import cert_parser, renewal
from app.services.audit import log_action
from app.services.live_check import check_domain, fetch_served_chain, parse_target

router = APIRouter(prefix="/api/domains", tags=["domains"])


def _days_left(valid_to: datetime | None) -> int | None:
    return (valid_to - utcnow()).days if valid_to else None


def _to_out(domain: Domain, db: Session | None = None,
            precomputed_pending: int | None = None) -> DomainOut:
    out = DomainOut.model_validate(domain)
    # Liste yolunda sayaç tek GROUP BY ile önceden hesaplanır (N+1 önleme); tekil GET'te db ile sayılır.
    if precomputed_pending is not None:
        out.pending_proposals = precomputed_pending
    elif db is not None:
        from app.db.models import TransferProposal
        out.pending_proposals = (db.query(TransferProposal)
                                 .filter(TransferProposal.domain_id == domain.id,
                                         TransferProposal.status == "pending").count())
    certs = []
    server_days = client_days = None
    for m in domain.certificate_mappings:
        days = _days_left(m.certificate.valid_to)
        certs.append(MappedCertOut(
            certificate_id=m.certificate_id,
            name=m.certificate.name,
            mapping_type=m.mapping_type,
            valid_to=m.certificate.valid_to,
            days_left=days,
            serial_number=m.certificate.serial_number,
            subject_key_identifier=m.certificate.subject_key_identifier,
        ))
        if days is not None:
            if m.mapping_type == "server":
                server_days = days if server_days is None else min(server_days, days)
            else:
                client_days = days if client_days is None else min(client_days, days)
    out.certificates = certs
    out.server_days_left = server_days
    out.client_days_left = client_days
    return out


def _query(db: Session):
    return db.query(Domain).options(
        joinedload(Domain.certificate_mappings).joinedload(CertificateDomainMap.certificate),
        joinedload(Domain.sy_team),
        joinedload(Domain.ug_team),
    )


@router.get("", response_model=list[DomainOut])
def list_domains(search: str | None = None,
                 limit: int | None = Query(None, ge=1, le=5000), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    # RBAC: SY editör yalnız KENDİ ekiplerinin domainlerini görür; admin/viewer global. none 403.
    # limit/offset OPSİYONEL: verilmezse tüm liste döner (mevcut davranış korunur).
    q = _query(db)
    if search:
        like = f"%{search}%"
        q = q.filter(Domain.domain.ilike(like) | Domain.cert_owner.ilike(like)
                     | Domain.external_company.ilike(like))
    scope = domain_scope_team_ids(db, user)
    if scope is not None:
        q = q.filter(Domain.sy_team_id.in_(scope or {-1}))
    domains = q.order_by(Domain.domain).offset(offset).limit(limit).all()
    # Bekleyen öneri sayıları tek sorguda (N+1 yerine): domain_id → count
    from sqlalchemy import func

    from app.db.models import TransferProposal
    pending = dict(db.query(TransferProposal.domain_id, func.count())
                   .filter(TransferProposal.status == "pending")
                   .group_by(TransferProposal.domain_id).all())
    return [_to_out(d, precomputed_pending=pending.get(d.id, 0)) for d in domains]


CSV_TEAM_FIELDS = {"sy": "SY", "ug": "UG"}
CSV_PLAIN_FIELDS = ("external_address", "cert_owner", "lb_update", "env_update", "waf_update",
                    "external_company", "info", "mail_addresses", "action_required",
                    "ssl_pinning", "keystore", "servers_to_update")


@router.post("/import-csv")
def import_csv(request: Request, file: UploadFile = File(...),
               db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    """Toplu domain yükleme. Zorunlu kolon: domain. Opsiyonel: sy, ug (takım adları),
    external_address, cert_owner, mail_addresses, external_company, info, lb_update,
    env_update, waf_update, action_required, ssl_pinning, keystore, servers_to_update.
    Var olan domain adları atlanır; sy/ug takımları yoksa oluşturulur."""
    try:
        content = file.file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
    except Exception:
        raise HTTPException(status_code=400, detail="CSV okunamadı (UTF-8 olmalı)")
    if not rows or "domain" not in {(f or "").strip().lower() for f in (reader.fieldnames or [])}:
        raise HTTPException(status_code=400, detail="CSV'de 'domain' kolonu bulunamadı")

    def get_or_create_team(name: str | None, type_: str) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        team = db.query(Team).filter_by(name=name, type=type_).first()
        if team is None:
            team = Team(name=name, type=type_)
            db.add(team)
            db.flush()
        return team.id

    created, skipped, errors = 0, 0, []
    for i, raw in enumerate(rows, start=2):  # 1. satır başlık
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = row.get("domain", "")
        if not name:
            errors.append(f"Satır {i}: domain boş")
            continue
        if db.query(Domain).filter_by(domain=name).first():
            skipped += 1
            continue
        domain = Domain(
            domain=name,
            sy_team_id=get_or_create_team(row.get("sy"), "SY"),
            ug_team_id=get_or_create_team(row.get("ug"), "UG"),
            **{f: (row.get(f) or None) for f in CSV_PLAIN_FIELDS},
        )
        db.add(domain)
        created += 1
    log_action(db, user.username, "import", "domains", None,
               {"file": file.filename, "created": created, "skipped": skipped}, request)
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors[:20]}


@router.post("/probe-chain", response_model=ChainProbeOut)
def probe_chain(body: ChainProbeRequest, db: Session = Depends(get_db),
                _: User = Depends(require_role("editor"))):
    """Domain'e canlı TLS bağlantısı kurup sunulan sertifika zincirini ÖNİZLER (kaydetmez).
    Her sertifika için envanterde zaten kayıtlı olup olmadığı işaretlenir."""
    host, port = parse_target(body.domain)
    if host is None:
        return ChainProbeOut(reachable=False,
                             error="Wildcard veya boş domain — doğrudan bağlanılamaz")
    try:
        chain = fetch_served_chain(host, port)
    except Exception as exc:
        return ChainProbeOut(reachable=False, host=host, port=port, error=str(exc)[:300])

    certs = []
    for parsed in (cert_parser.parse_x509(c) for c in chain):
        existing = cert_parser.find_existing(db, parsed)
        certs.append(ChainProbeCert(
            name=parsed.name,
            cert_type=parsed.cert_type,
            serial_number=parsed.serial_number,
            subject_key_identifier=parsed.subject_key_identifier,
            fingerprint_sha256=parsed.fingerprint_sha256,
            valid_to=parsed.valid_to,
            days_left=_days_left(parsed.valid_to),
            already_exists=existing is not None,
            existing_id=existing.id if existing else None,
        ))
    return ChainProbeOut(reachable=True, host=host, port=port, certificates=certs)


@router.post("/{domain_id}/import-chain", response_model=ChainImportOut)
def import_chain(request: Request, domain_id: int, supersede: bool = False,
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("editor"))):
    """Domain'in canlıda sunduğu zinciri çekip envantere aktarır: var olanlar atlanır,
    yeniler SKI/AKI ile hiyerarşiye bağlanır, uç (leaf) sertifika domain'e 'server'
    olarak eşlenir (yalnız domain boşsa — devir değil). Domainde zaten aktif server
    varsa ONAY MODELİ gereği anında devir YAPILMAZ; SY onayına düşen öneri üretilir."""
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # attach/detach ile tutarlı: SY sahibi domainde eşleme mutasyonu sahibine kilitli
    if not can_manage_team_resource(db, user, domain.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu domainin eşlemesini yalnız sahibi SY ekibi veya admin değiştirir")
    host, port = parse_target(domain.domain)
    if host is None:
        raise HTTPException(status_code=400,
                            detail="Wildcard veya boş domain'e doğrudan bağlanılamaz")
    try:
        chain = fetch_served_chain(host, port)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TLS bağlantısı kurulamadı: {str(exc)[:200]}")

    parsed_list = [cert_parser.parse_x509(c) for c in chain]
    leaf_fp = parsed_list[0].fingerprint_sha256  # el sıkışmada ilk sunulan = uç sertifika
    # Önce CA'lar eklensin ki leaf parent bulabilsin
    parsed_list.sort(key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type])

    created, existing_names = [], []
    leaf_row: Certificate | None = None
    for parsed in parsed_list:
        row = cert_parser.find_existing(db, parsed)
        if row is not None:
            existing_names.append(row.name)
        else:
            row = Certificate(**parsed.__dict__, creator=user.username, source="live")
            row.parent_id = cert_parser.resolve_parent(db, parsed)
            db.add(row)
            db.flush()
            cert_parser.relink_children(db, row)
            log_action(db, user.username, "import", "certificates", row.id,
                       {"name": row.name, "via": f"live-chain {domain.domain}"}, request)
            created.append(row.name)
        if parsed.fingerprint_sha256 == leaf_fp:
            leaf_row = row

    mapped_server = None
    superseded_names: list[str] = []
    if leaf_row is not None:
        already = db.query(CertificateDomainMap).filter_by(
            certificate_id=leaf_row.id, domain_id=domain.id, mapping_type="server").first()
        # Domainde leaf_row dışında AKTİF başka bir server sertifikası var mı?
        existing_servers = (db.query(CertificateDomainMap).join(
            Certificate, Certificate.id == CertificateDomainMap.certificate_id)
            .filter(CertificateDomainMap.domain_id == domain.id,
                    CertificateDomainMap.mapping_type == "server",
                    CertificateDomainMap.certificate_id != leaf_row.id,
                    Certificate.is_active == True).all())
        proposed_old_ids: set[int] = set()
        if supersede:
            # ONAY MODELİ: sertifika canlıdan çekilmiş olsa da (deploy kanıtlı) devir
            # yine SY onayı bekler; öneri live_seen=True kanıtıyla doğar.
            for old in renewal.find_predecessors(
                    db, cert_type=leaf_row.cert_type,
                    fingerprint_sha256=leaf_row.fingerprint_sha256,
                    subject_key_identifier=leaf_row.subject_key_identifier,
                    subject=leaf_row.subject, issuer=leaf_row.issuer,
                    valid_from=leaf_row.valid_from, exclude_id=leaf_row.id):
                made = renewal.propose(db, leaf_row, old, username=user.username, request=request,
                                       via="import-chain", live_seen=True,
                                       signal=renewal.renewal_signal(
                                           old, subject_key_identifier=leaf_row.subject_key_identifier,
                                           subject=leaf_row.subject, issuer=leaf_row.issuer))
                proposed_old_ids.add(old.id)
                if made:
                    superseded_names.append(old.name)
        # Öncül olarak yakalanmayan mevcut server sertifikaları da devir önerisi olur
        for m in existing_servers:
            if m.certificate_id not in proposed_old_ids:
                p = renewal.propose_attach_transfer(db, leaf_row, m.certificate, domain, "server",
                                                    username=user.username, request=request)
                if p is not None:
                    superseded_names.append(m.certificate.name)
        # Doğrudan server eşlemesi YALNIZ domainde hiç aktif server yokken (ilk kurulum,
        # devir değil) eklenir; aksi halde devir önerisi onaylanınca eşleme taşınır
        if already is None and not existing_servers:
            db.add(CertificateDomainMap(certificate_id=leaf_row.id, domain_id=domain.id,
                                        mapping_type="server"))
            log_action(db, user.username, "create", "certificate_domain_map", None,
                       {"domain": domain.domain, "cert": leaf_row.name, "type": "server",
                        "via": "live-chain"}, request)
            mapped_server = leaf_row.name
    db.commit()
    return ChainImportOut(created=created, existing=existing_names,
                          mapped_server=mapped_server, superseded=superseded_names)


@router.get("/{domain_id}", response_model=DomainOut)
def get_domain(domain_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_role("viewer"))):
    domain = _query(db).filter(Domain.id == domain_id).first()
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # RBAC: kapsam dışıysa VARLIĞI GİZLE (403 değil 404) — başka ekibin domain id'si sızmasın.
    scope = domain_scope_team_ids(db, user)
    if scope is not None and domain.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    return _to_out(domain, db)


@router.post("", response_model=DomainOut)
def create_domain(request: Request, body: DomainCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_role("editor"))):
    # ONAY MODELİ: bir editör domaini yalnız ÜYE OLDUĞU SY ekibine atayabilir
    # (aksi halde başka ekibin domainini üretip sahipliği kötüye kullanabilirdi).
    # Admin her ekibe atayabilir; sahipsiz (SY yok) domain herkese serbest.
    if (user.role != "admin" and body.sy_team_id is not None
            and body.sy_team_id not in user_team_ids(db, user)):
        raise HTTPException(status_code=403,
                            detail="Domaini yalnız üye olduğunuz bir SY ekibine atayabilirsiniz")
    domain = Domain(**body.model_dump())
    db.add(domain)
    db.flush()
    log_action(db, user.username, "create", "domains", domain.id, {"domain": domain.domain}, request)
    db.commit()
    return _to_out(domain)


@router.put("/{domain_id}", response_model=DomainOut)
def update_domain(request: Request, domain_id: int, body: DomainUpdate,
                  db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # KAPSAM: SY editör yalnız GÖRDÜĞÜ (kendi ekiplerinin) domainini değiştirebilir.
    # get_domain ile aynı 404 — kapsam dışı id'nin varlığı dahi sızmaz (IDOR koruması).
    scope = domain_scope_team_ids(db, user)
    if scope is not None and domain.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    # ONAY MODELİ: SAHİPLİK (sy_team_id/ug_team_id) yalnız admin tarafından değiştirilir.
    # Aksi halde bir editör domaini kendi ekibine geçirip önerisini kendisi onaylayabilirdi.
    if user.role != "admin":
        for owner_field in ("sy_team_id", "ug_team_id"):
            if owner_field in changes and changes[owner_field] != getattr(domain, owner_field):
                raise HTTPException(status_code=403,
                                    detail="Domain sahipliğini (SY/UG ekip) yalnız admin değiştirebilir")
    # Öneri sahibi (sy_team_id) OLUŞTURULURKEN snapshot alınır; domaine sonradan sahip atanınca
    # zaten açık olan öneriler "sahipsiz" kalıp yalnız admin'e görünürdü → yeni sahip kendi
    # domaininin bekleyen önerisini onaylayamazdı. Değişikliği uygulamadan ÖNCE tespit et.
    sy_changed = ("sy_team_id" in changes and changes["sy_team_id"] != domain.sy_team_id)
    for key, value in changes.items():
        setattr(domain, key, value)
    if sy_changed:
        # ONAY MODELİ senkron: bu domain'in HÂLÂ AÇIK (pending/approved) devir önerilerini yeni
        # sahibe taşı. Terminal öneriler (applied/rejected/cancelled) tarih olarak korunur.
        db.query(TransferProposal).filter(
            TransferProposal.domain_id == domain.id,
            TransferProposal.status.in_(("pending", "approved")),
        ).update({TransferProposal.sy_team_id: domain.sy_team_id}, synchronize_session=False)
    log_action(db, user.username, "update", "domains", domain.id, changes, request)
    db.commit()
    return _to_out(domain)


@router.delete("/{domain_id}")
def delete_domain(request: Request, domain_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_role("editor"))):
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # KAPSAM: update_domain ile aynı kural — kapsam dışı kayda silme de 404 (yıkıcı IDOR koruması).
    scope = domain_scope_team_ids(db, user)
    if scope is not None and domain.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # FK NO ACTION (MSSQL uyumu): domain silinmeden önce ona bağlı devir önerilerini elle temizle.
    # Domain silinince eşlemeleri ve app-bağımlılıkları DB-cascade ile düşer; ama bu bağımlılıklara
    # veya domaine referans veren öneriler önce silinmeli, yoksa MSSQL FK'yi bloklar.
    dep_ids = [d.id for d in db.query(AppDependency.id)
               .filter(AppDependency.target_domain_id == domain.id).all()]
    cond = TransferProposal.domain_id == domain.id
    if dep_ids:
        cond = cond | TransferProposal.app_dependency_id.in_(dep_ids)
    db.query(TransferProposal).filter(cond).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "domains", domain.id, {"domain": domain.domain}, request)
    db.delete(domain)
    db.commit()
    return {"ok": True}


@router.post("/{domain_id}/live-check", response_model=DomainOut)
def live_check(domain_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_role("editor"))):
    """Domain'in gerçekte sunduğu sertifikayı çekip eşlenmiş server sertifikalarıyla
    karşılaştırır (drift detection). Sonuç domain kaydına YAZILIR → salt-okur viewer çalıştıramaz;
    SY editör yalnız kendi domaini, admin hepsi (can_manage_team_resource ile tutarlı)."""
    domain = _query(db).filter(Domain.id == domain_id).first()
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    if not can_manage_team_resource(db, user, domain.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu domainin canlı doğrulamasını yalnız sahibi SY ekibi veya admin çalıştırır")
    check_domain(db, domain)
    db.commit()
    return _to_out(domain)


@router.post("/{domain_id}/certificates", response_model=DomainOut)
def attach_certificate(request: Request, domain_id: int, body: MappingCreate,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    domain = db.get(Domain, domain_id)
    cert = db.get(Certificate, body.certificate_id)
    if domain is None or cert is None:
        raise HTTPException(status_code=404, detail="Domain veya sertifika bulunamadı")
    # ONAY MODELİ: SY sahibi olan domainin eşlemesini yalnız o ekibin üyesi/admin
    # doğrudan değiştirebilir (detach+attach ile onay atlanmasın)
    if not can_manage_team_resource(db, user, domain.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu domainin sertifika eşlemesini yalnız sahibi SY ekibi veya admin değiştirir")
    exists = db.query(CertificateDomainMap).filter_by(
        certificate_id=cert.id, domain_id=domain.id, mapping_type=body.mapping_type).first()
    if exists:
        raise HTTPException(status_code=409, detail="Bu eşleme zaten mevcut")
    # ONAY MODELİ — baypas kapatma: bu domainde aynı tipte başka bir sertifika EŞLİYSE
    # yeni eşleme eklemek fiilen DEVİRDİR (detach+attach ya da pause+attach ile onay
    # atlanmasın — is_active FİLTRESİ YOK; pasife alınıp eklenmesi de devir sayılır).
    # Doğrudan eklenmez; devir önerisi üretilir ve SY onayına düşer.
    collision = (db.query(CertificateDomainMap)
                 .filter(CertificateDomainMap.domain_id == domain.id,
                         CertificateDomainMap.mapping_type == body.mapping_type,
                         CertificateDomainMap.certificate_id != cert.id).first())
    if collision is not None:
        prop = renewal.propose_attach_transfer(
            db, cert, collision.certificate, domain, body.mapping_type,
            username=user.username, request=request)
        if prop is None:
            # RED KALICI: bu granülün devri daha önce REDDEDİLDİ — rutin attach yeniden açamaz.
            db.rollback()
            raise HTTPException(status_code=409, detail=(
                f"'{domain.domain}' için bu devir ({collision.certificate.name} → {cert.name}) "
                f"daha önce reddedildi ve kalıcıdır. Yeniden önermek gerekiyorsa sertifika "
                f"detayından 'Devir Öner' ile bilinçli olarak yeniden başlatın."))
        db.commit()
        return JSONResponse(status_code=202, content={
            "status": "proposal_created", "proposal_id": prop.id,
            "message": f"'{domain.domain}' zaten aktif bir {body.mapping_type} sertifikası "
                       f"({collision.certificate.name}) taşıyor. Doğrudan değiştirilemez — "
                       f"devir önerisi oluşturuldu, SY ekibi onayı bekleniyor."})
    db.add(CertificateDomainMap(certificate_id=cert.id, domain_id=domain.id,
                                mapping_type=body.mapping_type))
    log_action(db, user.username, "create", "certificate_domain_map", None,
               {"domain": domain.domain, "cert": cert.name, "type": body.mapping_type}, request)
    db.commit()
    return _to_out(_query(db).filter(Domain.id == domain_id).first())


@router.delete("/{domain_id}/certificates/{cert_id}")
def detach_certificate(request: Request, domain_id: int, cert_id: int, mapping_type: str,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    mapping = db.query(CertificateDomainMap).filter_by(
        certificate_id=cert_id, domain_id=domain_id, mapping_type=mapping_type).first()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Eşleme bulunamadı")
    domain = db.get(Domain, domain_id)
    # ONAY MODELİ: SY sahibi domainin eşlemesini kaldırma da sahibine kilitli
    # (detach+attach ile onaysız devir vektörünü kapatır)
    if not can_manage_team_resource(db, user, domain.sy_team_id if domain else None):
        raise HTTPException(status_code=403,
                            detail="Bu domainin eşlemesini yalnız sahibi SY ekibi veya admin kaldırır")
    log_action(db, user.username, "delete", "certificate_domain_map", mapping.id,
               {"domain_id": domain_id, "cert_id": cert_id, "type": mapping_type}, request)
    db.delete(mapping)
    db.commit()
    return {"ok": True}
