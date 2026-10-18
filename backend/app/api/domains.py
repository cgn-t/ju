import io
import json
from datetime import datetime

import openpyxl
from app.core.textmatch import ci_equals, ci_like, fold
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
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
from app.api.trigger_auth import EXTERNAL_ACTOR, external_cooldown, trigger_actor
from app.core.certtype import cert_type_filter, normalize_cert_type
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
from app.services.audit import diff_fields, label_ids, log_action, snapshot
from app.services.chain_sync import sync_domain_chain_certs
from app.services.dependencies import fill_unwatched_dependencies
from app.services import live_check as live_check_service
from app.services.live_check import (check_domain, describe_connection_error, fetch_served_chain,
                                     host_name_warning, parse_target)

router = APIRouter(prefix="/api/domains", tags=["domains"])


def _days_left(valid_to: datetime | None) -> int | None:
    return (valid_to - utcnow()).days if valid_to else None


_MAPPING_ORDER = {"server": 0, "client": 1}
_TYPE_ORDER = {"leaf": 0, "intermediate": 1, "root": 2}


def _chain_depth(cert, limit: int = 10) -> int:
    """Köke kadar parent (yayıncı) adım sayısı — döngüye karşı sınırlı."""
    n, seen = 0, {cert.id}
    while cert.parent_id is not None and n < limit:
        cert = cert.parent
        if cert is None or cert.id in seen:
            break
        seen.add(cert.id)
        n += 1
    return n


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
    depth: dict[int, int] = {}
    for m in domain.certificate_mappings:
        days = _days_left(m.certificate.valid_to)
        depth[m.certificate_id] = _chain_depth(m.certificate)
        certs.append(MappedCertOut(
            certificate_id=m.certificate_id,
            name=m.certificate.name,
            mapping_type=m.mapping_type,
            cert_type=normalize_cert_type(m.certificate.cert_type),
            valid_to=m.certificate.valid_to,
            days_left=days,
            serial_number=m.certificate.serial_number,
            subject_key_identifier=m.certificate.subject_key_identifier,
            is_active=bool(m.certificate.is_active),
        ))
        if days is not None:
            if m.mapping_type == "server":
                server_days = days if server_days is None else min(server_days, days)
            else:
                client_days = days if client_days is None else min(client_days, days)
    # Zincir sırası: server → client; her grupta leaf → intermediate → root (eşleme ekleme
    # sırasından bağımsız — zincir içe aktarmada root, intermediate'tan önce bağlanabilir).
    # Birden çok intermediate varsa leaf'e yakın olan (köke uzak, derinliği büyük) önce gelir.
    certs.sort(key=lambda c: (_MAPPING_ORDER.get(c.mapping_type, 9), _TYPE_ORDER.get(c.cert_type, 9),
                              -depth.get(c.certificate_id, 0), (c.name or "").lower()))
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


_live_check_trigger = trigger_actor("live_check", "canlı doğrulama")


@router.post("/live-check-run", status_code=202)
def run_live_check_all(request: Request, actor: str = Depends(_live_check_trigger),
                       db: Session = Depends(get_db)):
    """TOPLU canlı doğrulamayı tetikler (gece taramasıyla aynı iş). Dış otomasyon
    (`X-API-Key: <live_check.trigger_api_key>`) veya admin JWT. Gece taraması ayarı
    (live_check.enabled) bunu ETKİLEMEZ. Tarama ARKA PLANDA çalışır — yanıt hemen döner (202);
    ilerleme/sonuç `GET /api/domains/live-check-run/status` ve Audit Log'da (Zamanlanmış iş).
    Zaten çalışıyorsa 409."""
    if actor == EXTERNAL_ACTOR:
        external_cooldown("live-check-run")
    if not live_check_service.start_bulk_run(actor):
        raise HTTPException(status_code=409, detail="Toplu canlı doğrulama zaten çalışıyor")
    log_action(db, actor, "live_check_run", "domains", None, {"scope": "all"}, request)
    db.commit()
    return {"status": "started", "triggered_by": actor,
            "status_url": "/api/domains/live-check-run/status"}


@router.get("/live-check-run/status")
def live_check_all_status(actor: str = Depends(_live_check_trigger)):
    """Son toplu canlı doğrulamanın durumu: running, triggered_by, started_at, finished_at ve
    bittiyse sayısal özet (toplam / durum dağılımı / hata). Dış anahtara domain adları dönmez."""
    state = live_check_service.bulk_run_status()
    result = state.get("result")
    if actor == EXTERNAL_ACTOR and isinstance(result, dict):
        state["result"] = {k: v for k, v in result.items() if k != "mismatched"}
    return state


@router.get("", response_model=list[DomainOut])
def list_domains(search: str | None = None,
                 limit: int | None = Query(None, ge=1, le=5000), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    # RBAC: SY editör yalnız KENDİ ekiplerinin domainlerini görür; admin/viewer global. none 403.
    # limit/offset OPSİYONEL: verilmezse tüm liste döner (mevcut davranış korunur).
    q = _query(db)
    if search:
        like = f"%{search}%"
        q = q.filter(ci_like(Domain.domain, like) | ci_like(Domain.cert_owner, like)
                     | ci_like(Domain.external_company, like))
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


@router.post("/import-excel")
def import_excel(request: Request, file: UploadFile = File(...),
                 db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    """Toplu domain yükleme (.xlsx). 1. satır başlık, altındaki satırlar veri. Zorunlu kolon:
    domain. Opsiyonel: sy, ug (takım adları), external_address, cert_owner, mail_addresses,
    external_company, info, lb_update, env_update, waf_update, action_required, ssl_pinning,
    keystore, servers_to_update. Var olan domain adları atlanır. sy/ug takımı Jumbo'da
    yoksa satır EKLENMEZ ve hata listesinde bildirilir: eskiden sessizce yeni takım açılıyordu,
    yanlış yazılan ad (ör. Türkçe harfsiz "ODEME SISTEMLERI") e-postası olmayan ikiz bir takım
    doğuruyor ve süre uyarıları yedek adrese düşüyordu."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.file.read()), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        headers = [str(h) if h is not None else "" for h in (header_row or ())]
        rows = []
        for values in rows_iter:
            if values is None or all(v is None for v in values):
                continue  # Excel'de sık görülen tamamen boş satır — atla
            rows.append(dict(zip(headers, (("" if v is None else str(v)) for v in values))))
    except Exception:
        raise HTTPException(status_code=400, detail="Excel okunamadı (.xlsx olmalı)")
    if not rows or "domain" not in {(h or "").strip().lower() for h in headers}:
        raise HTTPException(status_code=400, detail="Excel'de 'domain' kolonu bulunamadı")

    # Takım adı Türkçe I/İ ve büyük/küçük harf farkı gözetmeden eşleşir ("ödeme sistemleri" →
    # "Ödeme Sistemleri"). Python'da katlanır: SQLite ile MSSQL aynı sonucu verir.
    teams_by_key = {(tm.type, fold(tm.name.strip())): tm.id for tm in db.query(Team).all()}

    def find_team(name: str | None, type_: str) -> tuple[int | None, str | None]:
        """(takım id, hata). Ad boşsa (None, None)."""
        name = (name or "").strip()
        if not name:
            return None, None
        team_id = teams_by_key.get((type_, fold(name)))
        if team_id is None:
            return None, f"'{name}' adlı {type_} ekibi bulunamadı"
        return team_id, None

    created, skipped, errors = 0, 0, []
    for i, raw in enumerate(rows, start=2):  # 1. satır başlık
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = row.get("domain", "")
        if not name:
            errors.append(f"Satır {i}: domain boş")
            continue
        # Büyük/küçük harf farkı da ikiz sayılır (aynı dosyada iki kez geçen satır dahil)
        if db.query(Domain.id).filter(ci_equals(Domain.domain, name)).first():
            skipped += 1
            continue
        sy_id, sy_err = find_team(row.get("sy"), "SY")
        ug_id, ug_err = find_team(row.get("ug"), "UG")
        if sy_err or ug_err:
            errors.append(f"Satır {i} ({name}): " + ", ".join(e for e in (sy_err, ug_err) if e)
                          + ". Domain eklenmedi; ekibi Ayarlar > Ekipler'de oluşturun ya da adını düzeltin.")
            continue
        domain = Domain(
            domain=name,
            sy_team_id=sy_id,
            ug_team_id=ug_id,
            **{f: (row.get(f) or None) for f in CSV_PLAIN_FIELDS},
        )
        db.add(domain)
        db.flush()  # oturum autoflush=False: dosyadaki sonraki ikiz satır bu kaydı görsün
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
        return ChainProbeOut(reachable=False, host=host, port=port, error=describe_connection_error(exc, host, port))

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
    return ChainProbeOut(reachable=True, host=host, port=port, certificates=certs,
                         name_warning=host_name_warning(host, chain[0]))


@router.post("/{domain_id}/import-chain", response_model=ChainImportOut)
def import_chain(request: Request, domain_id: int, supersede: bool = False,
                 environment: str | None = Query(None),
                 allow_name_mismatch: bool = False,
                 db: Session = Depends(get_db),
                 user: User = Depends(require_role("editor"))):
    """Domain'in canlıda sunduğu zinciri çekip envantere aktarır: var olanlar atlanır,
    yeniler SKI/AKI ile hiyerarşiye bağlanır, uç (leaf) sertifika domain'e 'server'
    olarak eşlenir (yalnız domain boşsa — devir değil). Domainde zaten aktif server
    varsa ONAY MODELİ gereği anında devir YAPILMAZ; SY onayına düşen öneri üretilir.

    `environment` (prod|test, opsiyonel): otomatik yollar (live-check, keşif) bunu bilemez;
    yalnız burada bir insan import'u tetiklediği için elle belirtilebilir. YALNIZ bu istekte
    YENİ oluşturulan sertifikalara uygulanır — zaten envanterde olan kayıtların ortamı
    ASLA ezilmez (bkz. chain_sync.sync_domain_chain_certs)."""
    if environment not in (None, "", "prod", "test"):
        raise HTTPException(status_code=400, detail="environment yalnız 'prod' veya 'test' olabilir")
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    # attach/detach ile tutarlı: SY sahibi domainde eşleme mutasyonu sahibine kilitli
    if not can_manage_team_resource(db, user, domain.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu domainin sertifika bağlantısını yalnız sahibi SY ekibi veya admin değiştirir")
    host, port = parse_target(domain.domain)
    if host is None:
        raise HTTPException(status_code=400,
                            detail="Wildcard veya boş domain'e doğrudan bağlanılamaz")
    try:
        chain = fetch_served_chain(host, port)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=describe_connection_error(exc, host, port))
    # Sunucu, yazılan adres için başka bir sitenin sertifikasını verdiyse (aynı sunucuda çok site,
    # adres sunucuda tanımlı değil) hiçbir şey eklenmez; kullanıcı bilerek onaylarsa devam edilir.
    name_warning = host_name_warning(host, chain[0])
    if name_warning and not allow_name_mismatch:
        raise HTTPException(status_code=409, detail=name_warning)
    if name_warning:
        # Eylem adı ≤20 karakter: prod AuditLog.Action NVARCHAR(20) (MSSQL uzun değeri reddeder)
        log_action(db, user.username, "name_mismatch_ok", "domains", domain.id,
                   {"domain": domain.domain, "warning": name_warning}, request)

    # Zinciri envantere işler ve HER cert_type için ayrı ayrı server eşlemesini senkronize
    # eder (leaf/intermediate/root bağımsız — ortak mantık chain_sync, live-check de kullanır).
    sync = sync_domain_chain_certs(db, domain, chain, username=user.username, request=request,
                                   via="import-chain", environment=environment or None)
    leaf_row = sync.leaf_row
    if supersede and leaf_row is not None and leaf_row.is_active:
        # ONAY MODELİ: sertifika canlıdan çekilmiş olsa da (deploy kanıtlı) devir yine SY
        # onayı bekler; öneri live_seen=True kanıtıyla doğar. Yalnız leaf'e özeldir ve YALNIZ bu
        # domain kapsamındadır (domain_id) — öncülün diğer domainlerine yayılmaz;
        # propose()'un idempotent kontrolü sayesinde aynı granül ikinci kez önerilmez.
        for old in renewal.find_predecessors(
                db, cert_type=leaf_row.cert_type,
                fingerprint_sha256=leaf_row.fingerprint_sha256,
                subject_key_identifier=leaf_row.subject_key_identifier,
                subject=leaf_row.subject, issuer=leaf_row.issuer,
                valid_from=leaf_row.valid_from, exclude_id=leaf_row.id):
            made = renewal.propose(db, leaf_row, old, username=user.username, request=request,
                                   via="import-chain", live_seen=True, domain_id=domain.id,
                                   signal=renewal.renewal_signal(
                                       old, subject_key_identifier=leaf_row.subject_key_identifier,
                                       subject=leaf_row.subject, issuer=leaf_row.issuer))
            if made:
                sync.superseded.append(old.name)
    db.commit()
    return ChainImportOut(created=sync.created, existing=sync.existing,
                          mapped_server=sync.mapped.get("leaf"), superseded=sync.superseded,
                          added=sync.added, removed=sync.removed, inactive=sync.inactive)


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



def _ensure_unique_domain(db: Session, name: str | None, exclude_id: int | None = None) -> None:
    """Aynı domain ikinci kez kaydedilmez (büyük/küçük harf farkı dahil: `WWW.x` = `www.x`).
    İkiz kayıt mailleri ve değişiklik taleplerini iki domain arasında böler. Var olan ikizlere dokunmaz."""
    name = (name or "").strip()
    if not name:
        return
    q = db.query(Domain.id).filter(ci_equals(Domain.domain, name))
    if exclude_id is not None:
        q = q.filter(Domain.id != exclude_id)
    if q.first() is not None:
        raise HTTPException(status_code=409, detail=f"Bu domain zaten kayıtlı: {name}")

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
    data = body.model_dump()
    data["domain"] = data["domain"].strip()
    _ensure_unique_domain(db, data["domain"])
    domain = Domain(**data)
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
    if changes.get("domain") is not None:
        changes["domain"] = changes["domain"].strip()
        if changes["domain"] != domain.domain:
            _ensure_unique_domain(db, changes["domain"], exclude_id=domain.id)
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
    diff = label_ids(db, diff_fields(domain, changes))
    for key, value in changes.items():
        setattr(domain, key, value)
    if sy_changed:
        # ONAY MODELİ senkron: bu domain'in HÂLÂ AÇIK (pending/approved) değişiklik taleplerini yeni
        # sahibe taşı. Terminal öneriler (applied/rejected/cancelled) tarih olarak korunur.
        db.query(TransferProposal).filter(
            TransferProposal.domain_id == domain.id,
            TransferProposal.status.in_(("pending", "approved")),
        ).update({TransferProposal.sy_team_id: domain.sy_team_id}, synchronize_session=False)
    log_action(db, user.username, "update", "domains", domain.id,
               {"domain": domain.domain, "changes": diff}, request)
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
    # FK NO ACTION (MSSQL uyumu): domain silinmeden önce ona bağlı değişiklik taleplerini elle temizle.
    # Domain silinince eşlemeleri ve app-bağımlılıkları DB-cascade ile düşer; ama bu bağımlılıklara
    # veya domaine referans veren öneriler önce silinmeli, yoksa MSSQL FK'yi bloklar.
    dep_ids = [d.id for d in db.query(AppDependency.id)
               .filter(AppDependency.target_domain_id == domain.id).all()]
    cond = TransferProposal.domain_id == domain.id
    if dep_ids:
        cond = cond | TransferProposal.app_dependency_id.in_(dep_ids)
    db.query(TransferProposal).filter(cond).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "domains", domain.id,
               {"domain": domain.domain,
                "snapshot": snapshot(domain, ("domain", "cert_owner", "ug_team_name", "notify_days",
                                              "mail_addresses", "external_address")),
                "certificates": [f"{m.certificate.name} ({m.mapping_type})"
                                 for m in domain.certificate_mappings if m.certificate]}, request)
    db.delete(domain)
    db.commit()
    return {"ok": True}


@router.post("/{domain_id}/live-check", response_model=DomainOut)
def live_check(request: Request, domain_id: int, db: Session = Depends(get_db),
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
    try:
        detail = json.loads(domain.live_check_detail or "{}")
    except ValueError:
        detail = {}
    log_action(db, user.username, "live_check_run", "domains", domain.id,
               {"domain": domain.domain, "status": domain.live_check_status,
                "served_cn": detail.get("served_cn"), "reason": detail.get("reason"),
                "proposals": detail.get("superseded_live_seen") or detail.get("chain_sync_superseded"),
                "proposed_add": detail.get("proposed_add"),
                "proposed_remove": detail.get("proposed_remove")},
               request)
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
                            detail="Bu domainin sertifika bağlantısını yalnız sahibi SY ekibi veya admin değiştirir")
    exists = db.query(CertificateDomainMap).filter_by(
        certificate_id=cert.id, domain_id=domain.id, mapping_type=body.mapping_type).first()
    if exists:
        raise HTTPException(status_code=409, detail="Bu bağlantı zaten mevcut")
    # İş kuralı: domaine bağlı sertifika pasif olamaz (bkz. _ensure_deactivatable)
    if not cert.is_active:
        raise HTTPException(status_code=400, detail=(
            f"'{cert.name}' pasif durumda; pasif sertifika domaine bağlanamaz. Önce sertifikayı "
            f"aktife alın ya da güncel sertifikayı seçin."))

    if body.mapping_type == "client":
        # TRUSTED: zincir zorunluluğu yok — leaf/intermediate/root teker teker bağlanabilir.
        # ONAY MODELİ — baypas kapatma: bu domainde aynı tipte başka bir sertifika EŞLİYSE
        # yeni eşleme eklemek fiilen DEVİRDİR (detach+attach ya da pause+attach ile onay
        # atlanmasın — is_active FİLTRESİ YOK; pasife alınıp eklenmesi de devir sayılır).
        # Yalnız AYNI seviyedeki (root/intermediate/leaf) client sertifika çakışmadır — farklı
        # seviyeler trust olarak birlikte durabilir; root → leaf gibi değişiklik talebi ÜRETİLMEZ.
        cert_level = normalize_cert_type(cert.cert_type)
        collision = next(
            (m for m in (db.query(CertificateDomainMap)
                         .filter(CertificateDomainMap.domain_id == domain.id,
                                 CertificateDomainMap.mapping_type == "client",
                                 CertificateDomainMap.certificate_id != cert.id).all())
             if normalize_cert_type(m.certificate.cert_type) == cert_level), None)
        if collision is not None:
            prop = renewal.propose_attach_transfer(
                db, cert, collision.certificate, domain, "client",
                username=user.username, request=request)
            if prop is None:
                # RED KALICI: bu granülün devri daha önce REDDEDİLDİ — rutin attach yeniden açamaz.
                db.rollback()
                raise HTTPException(status_code=409, detail=(
                    f"'{domain.domain}' için bu değişiklik ({collision.certificate.name} → {cert.name}) "
                    f"daha önce reddedildi ve kalıcıdır. Yeniden önermek gerekiyorsa sertifika "
                    f"detayından 'Değişiklik Talebi Oluştur' ile bilinçli olarak yeniden başlatın."))
            db.commit()
            return JSONResponse(status_code=202, content={
                "status": "proposal_created", "proposal_id": prop.id,
                "message": f"'{domain.domain}' zaten aktif bir client sertifikası "
                           f"({collision.certificate.name}) taşıyor. Doğrudan değiştirilemez — "
                           f"değişiklik talebi oluşturuldu, SY ekibi onayı bekleniyor."})
        db.add(CertificateDomainMap(certificate_id=cert.id, domain_id=domain.id, mapping_type="client"))
        log_action(db, user.username, "create", "certificate_domain_map", None,
                   {"domain": domain.domain, "cert": cert.name, "type": "client"}, request)
        db.commit()
        return _to_out(_query(db).filter(Domain.id == domain_id).first())

    # mapping_type == "server": zincir-bilinçli — leaf seçilir, intermediate/root otomatik
    # çözülüp birlikte bağlanır; her cert_type kendi havuzuyla (leaf↔leaf, root↔root)
    # karşılaştırılır (bkz. plan: live_check/import_chain'deki aynı kök hatanın düzeltmesi).
    if normalize_cert_type(cert.cert_type) != "leaf":
        raise HTTPException(status_code=400,
                            detail="Server olarak yalnız leaf (uç) sertifika seçilir; zincir "
                                   "otomatik eklenir.")
    chain, complete = cert_parser.resolve_server_chain(cert)
    warning = None if complete else (
        "Zincir eksik: intermediate/root envanterde yok — yalnızca bulunabilen seviyeler "
        "bağlandı. Yenileme takibi ve canlı doğrulama bu seviyeler için şimdilik sınırlı "
        "kalacak; zincir ileride içe aktarılırsa otomatik tamamlanır.")
    passive_parents = [m.name for m in chain if not m.is_active]
    if passive_parents:
        chain = [m for m in chain if m.is_active]
        note = (f"Zincirdeki pasif sertifika(lar) bağlanmadı: {', '.join(passive_parents)}.")
        warning = f"{warning} {note}" if warning else note

    # Aynı zincirde AYNI tipten birden fazla sertifika olabilir (ör. gerçek 2 katmanlı
    # ara-CA hiyerarşisi, ya da eski istemcilerle uyum için sunulan çapraz-imzalı bir
    # "root" kopyası — kendi kendini imzalamadığından 'intermediate' sayılır). Bu üyeler
    # birbirinin çakışma adayı DEĞİLDİR; yalnız bu zincirin DIŞINDA kalan (önceden, başka
    # bir zincirden bağlanmış) aynı tipteki bir sertifika gerçek bir rotasyon/çakışma sayılır.
    chain_ids = {m.id for m in chain}

    proposals: list[tuple[str, object]] = []  # (cert_type, TransferProposal)
    for member in chain:
        member_type = normalize_cert_type(member.cert_type)
        if db.query(CertificateDomainMap).filter_by(
                certificate_id=member.id, domain_id=domain.id, mapping_type="server").first():
            continue  # bu seviye zaten bağlı (ör. önceki bir attach/import ile)
        collision = (db.query(CertificateDomainMap)
                     .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
                     .filter(CertificateDomainMap.domain_id == domain.id,
                             CertificateDomainMap.mapping_type == "server",
                             CertificateDomainMap.certificate_id.notin_(chain_ids),
                             cert_type_filter(Certificate.cert_type, member_type)).first())
        if collision is not None:
            prop = renewal.propose_attach_transfer(
                db, member, collision.certificate, domain, "server",
                username=user.username, request=request)
            if prop is None:
                if member_type == "leaf":
                    # RED KALICI (leaf) — bugünkü davranışla aynı: sert 409.
                    db.rollback()
                    raise HTTPException(status_code=409, detail=(
                        f"'{domain.domain}' için bu değişiklik ({collision.certificate.name} → "
                        f"{member.name}) daha önce reddedildi ve kalıcıdır. Yeniden önermek "
                        f"gerekiyorsa sertifika detayından 'Değişiklik Talebi Oluştur' ile bilinçli olarak "
                        f"yeniden başlatın."))
                continue  # intermediate/root reddi leaf attach'ini bloklamaz
            proposals.append((member_type, prop))
        else:
            db.add(CertificateDomainMap(certificate_id=member.id, domain_id=domain.id,
                                        mapping_type="server"))
            log_action(db, user.username, "create", "certificate_domain_map", None,
                       {"domain": domain.domain, "cert": member.name, "type": "server"}, request)

    if proposals:
        db.commit()
        return JSONResponse(status_code=202, content={
            "status": "proposal_created",
            "proposal_ids": [p.id for _, p in proposals],
            "message": (f"'{domain.domain}' zaten aktif server sertifikası taşıyan seviye(ler) "
                       f"var ({', '.join(t for t, _ in proposals)}). Doğrudan değiştirilemez — "
                       f"değişiklik talebi oluşturuldu, SY ekibi onayı bekleniyor."
                       + (f" {warning}" if warning else ""))})
    # domaine bu server leaf'i bağlanmadan önce eklenmiş (izlediği sertifikası boş) mTLS
    # bağımlılıkları artık bu sertifikayı izlesin — uygulama sahibi süre uyarısı alsın
    fill_unwatched_dependencies(db, domain.id)
    db.commit()
    out = jsonable_encoder(_to_out(_query(db).filter(Domain.id == domain_id).first()))
    if warning:
        out["warning"] = warning
    return JSONResponse(status_code=200, content=out)


@router.delete("/{domain_id}/certificates/{cert_id}")
def detach_certificate(request: Request, domain_id: int, cert_id: int, mapping_type: str,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    mapping = db.query(CertificateDomainMap).filter_by(
        certificate_id=cert_id, domain_id=domain_id, mapping_type=mapping_type).first()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Bağlantı bulunamadı")
    domain = db.get(Domain, domain_id)
    # ONAY MODELİ: SY sahibi domainin eşlemesini kaldırma da sahibine kilitli
    # (detach+attach ile onaysız devir vektörünü kapatır)
    if not can_manage_team_resource(db, user, domain.sy_team_id if domain else None):
        raise HTTPException(status_code=403,
                            detail="Bu domainin sertifika bağlantısını yalnız sahibi SY ekibi veya admin kaldırır")
    log_action(db, user.username, "delete", "certificate_domain_map", mapping.id,
               {"domain_id": domain_id, "cert_id": cert_id, "type": mapping_type}, request)
    db.delete(mapping)
    db.commit()
    return {"ok": True}
