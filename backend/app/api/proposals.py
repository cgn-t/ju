"""Sertifika değişiklik talepleri — onay hattı.

JUMBO hiçbir devri kendiliğinden uygulamaz; her devir bir TransferProposal olur ve
domain sahibi SY ekibinin (veya admin) onayını bekler. Onay = uygula (apply_proposal),
tek mutasyon kapısı. Reddet/İptal önerileri kapatır, hiçbir mutasyon yapmaz.
"""

from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.api.paging import MAX_PAGE_SIZE
from app.api.schemas import ProposalDecision, ProposalPage, TransferProposalOut
from app.core.textmatch import ci_like
from app.core.security import (
    ROLE_LEVELS,
    require_page_access,
    require_role,
    require_team_or_admin,
    user_team_ids,
)
from app.db.models import Application, Certificate, Domain, TransferProposal, User
from app.db.session import get_db
from app.services import cert_parser, renewal
from app.services.audit import log_action

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


def _can_decide(user: User) -> bool:
    """Öneriyi onaylayabilme yetkisi rol tier'ından: yalnız editor+ (viewer/allviewer salt-okur).
    Kapsam (SY üyeliği) ayrıca gereklidir; bu yalnız YETKİ tier kapısıdır (require_team_or_admin ile eş)."""
    return ROLE_LEVELS.get(user.role, -1) >= ROLE_LEVELS["editor"]


def _full_name(db: Session, username: str | None) -> str | None:
    """Önerenin Ad Soyad'ı (LDAP girişinde dolar). İstek oturumu başına önbellekli —
    liste ucunda aynı kullanıcı için tekrar sorgu atılmaz."""
    if not username or username == "system":
        return None
    cache = db.info.setdefault("_proposal_full_names", {})
    if username not in cache:
        cache[username] = db.query(User.full_name).filter(User.username == username).scalar()
    return cache[username]


def _to_out(db: Session, p: TransferProposal, team_ids: set[int], is_admin: bool,
            is_editor: bool = False) -> TransferProposalOut:
    old = db.get(Certificate, p.old_cert_id)
    new = db.get(Certificate, p.new_cert_id)
    dom = db.get(Domain, p.domain_id) if p.domain_id else None
    app_row = db.get(Application, p.app_id) if p.app_id else None
    # Karar yetkisi = admin VEYA (editor-tier VE öneri SY ekibinin üyesi). viewer/allviewer
    # SY üyesi olsa bile onaylayamaz (require_team_or_admin ile birebir aynı kural).
    can = is_admin or (is_editor and p.sy_team_id is not None and p.sy_team_id in team_ids)
    dates = {}
    if p.kind == "date_fix" and new is not None:
        pem = cert_parser.pem_dates(new.pem_certificate)
        dates = dict(record_valid_from=new.valid_from, record_valid_to=new.valid_to,
                     cert_valid_from=pem[0] if pem else None, cert_valid_to=pem[1] if pem else None)
    return TransferProposalOut(**dates,
        id=p.id, old_cert_id=p.old_cert_id, old_cert_name=old.name if old else None,
        new_cert_id=p.new_cert_id, new_cert_name=new.name if new else None,
        domain_id=p.domain_id, domain_name=dom.domain if dom else None,
        mapping_type=p.mapping_type, app_dependency_id=p.app_dependency_id,
        app_id=p.app_id, app_name=app_row.app_name if app_row else None, kind=p.kind or "transfer",
        sy_team_id=p.sy_team_id, sy_team_name=p.sy_team.name if p.sy_team else None,
        status=p.status, signal=p.signal, via=p.via, live_seen=p.live_seen,
        created_by=p.created_by, created_by_name=_full_name(db, p.created_by),
        created_at=p.created_at, decided_by=p.decided_by,
        decided_at=p.decided_at, note=p.note, can_decide=can and p.status == "pending")


@router.get("", response_model=list[TransferProposalOut])
def list_proposals(status: str | None = "pending", mine: bool = False,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_page_access("proposals"))):
    """Değişiklik talepleri. Admin VE allviewer (Genel İzleyici) hepsini görür; diğerleri yalnız
    üye oldukları SY ekibinin (sy_team_id) önerilerini. mine=true admin/allviewer için de
    yalnız kendi ekiplerini süzer. Görünürlük: require_page_access('proposals') — SY üyeleri
    kendi tekliflerini her zaman görür, alakasız kullanıcılar yalnız Ayarlar>Erişim açıksa
    (bkz. security.page_visible). allviewer salt-okurdur — düzenleme/onay yetkisi vermez,
    bkz. _can_decide/require_team_or_admin (domain_scope_team_ids ile tutarlı: admin+allviewer=global)."""
    can_see_all = user.role in ("admin", "allviewer")  # GÖRÜNÜRLÜK kapsamı: admin+allviewer
    team_ids = user_team_ids(db, user)
    q = db.query(TransferProposal)
    if status:
        q = q.filter(TransferProposal.status == status)
    if not can_see_all or mine:
        # Sahipsiz (sy_team_id NULL) öneriler yalnız admin/allviewer'a görünür
        q = q.filter(TransferProposal.sy_team_id.in_(team_ids or {-1}))
    rows = q.order_by(TransferProposal.created_at.desc()).all()
    # Sertifikası silinmiş orphan önerileri gösterme (savunma amaçlı; delete zaten temizler).
    # _to_out'a GERÇEK admin geçilir (can_see_all DEĞİL) — allviewer can_decide=True ALMASIN;
    # onay yetkisi yalnız admin/editor-tier'a aittir (bkz. _can_decide, require_team_or_admin).
    return [_to_out(db, p, team_ids, user.role == "admin", _can_decide(user)) for p in rows
            if db.get(Certificate, p.old_cert_id) and db.get(Certificate, p.new_cert_id)]


_STATUSES = ("pending", "approved", "applied", "rejected", "cancelled")
_KINDS = ("transfer", "date_fix", "server_add", "server_remove", "trusted_add")


def _visible(db: Session, user: User, mine: bool = False):
    """list_proposals ile aynı görünürlük + yetim (sertifikası silinmiş) taleplerin dışlanması."""
    can_see_all = user.role in ("admin", "allviewer")
    team_ids = user_team_ids(db, user)
    old_c, new_c = aliased(Certificate), aliased(Certificate)
    q = (db.query(TransferProposal)
         .join(old_c, old_c.id == TransferProposal.old_cert_id)
         .join(new_c, new_c.id == TransferProposal.new_cert_id))
    if not can_see_all or mine:
        q = q.filter(TransferProposal.sy_team_id.in_(team_ids or {-1}))
    return q, team_ids, old_c, new_c


@router.get("/page", response_model=ProposalPage)
def page_proposals(page: int = Query(0, ge=0), size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
                   status: str = "pending", kind: str | None = None,
                   domain_id: int | None = None, sy_team_id: int | None = None,
                   via: str | None = None, live_seen: bool | None = None,
                   decidable: bool = False, mine: bool = False, q: str | None = None,
                   sort: str = "created_at", dir: str = "desc",
                   db: Session = Depends(get_db),
                   user: User = Depends(require_page_access("proposals"))):
    """Değişiklik Talepleri — filtreli ve sayfalı liste. Filtreler: durum (pending|approved|
    applied|rejected|cancelled|all), tür, domain, SY ekip, kaynak (via), canlıda görüldü,
    yalnız karar verebileceklerim, metin araması (domain, sertifika ve uygulama adı).
    counts = durum sekmelerinin sayıları (durum hariç diğer filtrelerle); facets.kind = tür sayıları.
    Görünürlük ve can_decide kuralı list_proposals ile birebir aynı."""
    base, team_ids, old_c, new_c = _visible(db, user, mine)
    if domain_id is not None:
        base = base.filter(TransferProposal.domain_id == domain_id)
    if sy_team_id is not None:
        base = base.filter(TransferProposal.sy_team_id == sy_team_id)
    if via:
        base = base.filter(TransferProposal.via == via)
    if live_seen is not None:
        base = base.filter(TransferProposal.live_seen == live_seen)
    if decidable:
        if user.role != "admin":
            if not _can_decide(user):
                base = base.filter(TransferProposal.id == -1)
            else:
                base = base.filter(TransferProposal.sy_team_id.in_(team_ids or {-1}))
    if q:
        like = f"%{q.strip()}%"
        dom_ids = db.query(Domain.id).filter(ci_like(Domain.domain, like))
        app_ids = db.query(Application.id).filter(ci_like(Application.app_name, like))
        base = base.filter(ci_like(old_c.name, like) | ci_like(new_c.name, like)
                           | TransferProposal.domain_id.in_(dom_ids)
                           | TransferProposal.app_id.in_(app_ids))
    # Durum sekmeleri: diğer filtreler uygulanmış, durum filtresi uygulanmamış
    counts = {st: 0 for st in _STATUSES}
    for st, n in (base.with_entities(TransferProposal.status, func.count(TransferProposal.id))
                  .group_by(TransferProposal.status).all()):
        counts[st] = n
    counts["all"] = sum(counts[st] for st in _STATUSES)
    if status != "all":
        base = base.filter(TransferProposal.status == (status if status in _STATUSES else "pending"))
    kinds = {k: 0 for k in _KINDS}
    for k, n in (base.with_entities(TransferProposal.kind, func.count(TransferProposal.id))
                 .group_by(TransferProposal.kind).all()):
        kinds[k or "transfer"] = kinds.get(k or "transfer", 0) + n
    kinds["all"] = sum(kinds.values())
    if kind:
        base = base.filter(TransferProposal.kind == kind)
    total = base.count()
    last = max(0, (total - 1) // size) if total else 0
    page = min(page, last)
    if sort == "domain":
        order = Domain.domain
        base = base.outerjoin(Domain, Domain.id == TransferProposal.domain_id)
    else:
        order = TransferProposal.created_at
    order = order.desc() if dir == "desc" else order.asc()
    rows = base.order_by(order, TransferProposal.id.desc()).offset(page * size).limit(size).all()
    is_editor = _can_decide(user)
    items = [_to_out(db, p, team_ids, user.role == "admin", is_editor) for p in rows]
    domain_name = None
    if domain_id is not None:
        d = db.get(Domain, domain_id)
        domain_name = d.domain if d else None
    return ProposalPage(items=items, total=total, page=page, size=size, counts=counts,
                        facets={"kind": kinds}, domain_name=domain_name)


@router.get("/counts")
def proposal_counts(db: Session = Depends(get_db),
                    user: User = Depends(require_page_access("proposals"))):
    """Menü rozeti için hafif sayaç: bekleyen (görünen) ve bu kullanıcının karar verebileceği."""
    base, team_ids, _, _ = _visible(db, user)
    base = base.filter(TransferProposal.status == "pending")
    visible = base.count()
    if user.role == "admin":
        decidable = visible
    elif _can_decide(user):
        decidable = base.filter(TransferProposal.sy_team_id.in_(team_ids or {-1})).count()
    else:
        decidable = 0
    return {"pending": visible, "decidable": decidable}


@router.get("/{proposal_id}", response_model=TransferProposalOut)
def get_proposal(proposal_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_page_access("proposals"))):
    """Tek talep (sayfada görünmeyen bir talebin inceleme penceresi doğrudan açılabilsin)."""
    base, team_ids, _, _ = _visible(db, user)
    prop = base.filter(TransferProposal.id == proposal_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    return _to_out(db, prop, team_ids, user.role == "admin", _can_decide(user))


@router.get("/{proposal_id}/group", response_model=list[TransferProposalOut])
def proposal_group(proposal_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_page_access("proposals"))):
    """Bu önerinin ait olduğu devrin (aynı old→new cert) TÜM bekleyen domain önerileri.
    Tek sertifika çok domaine bağlıysa her domain kendi SY'since ayrı onaylanır; bu uç,
    kullanıcının KARAR VEREMEYECEĞİ kardeş domainleri de listeler (yalnız farkındalık —
    sertifikanın SAN'ı zaten tüm domainleri açığa vurduğu için ek ifşa değildir).
    Erişim: yalnız bu öneriyi görebilen (admin/allviewer veya sahibi SY üyesi) grubu çekebilir."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    can_see_all = user.role in ("admin", "allviewer")  # GÖRÜNÜRLÜK kapsamı: admin+allviewer
    team_ids = user_team_ids(db, user)
    if not (can_see_all or (prop.sy_team_id is not None and prop.sy_team_id in team_ids)):
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    rows = (db.query(TransferProposal)
            .filter(TransferProposal.old_cert_id == prop.old_cert_id,
                    TransferProposal.new_cert_id == prop.new_cert_id,
                    TransferProposal.status == "pending")
            .order_by(TransferProposal.id.asc()).all())
    # _to_out'a GERÇEK admin geçilir (can_see_all DEĞİL) — allviewer can_decide=True ALMASIN.
    return [_to_out(db, p, team_ids, user.role == "admin", _can_decide(user)) for p in rows
            if db.get(Certificate, p.old_cert_id) and db.get(Certificate, p.new_cert_id)]


def _audit_ctx(db: Session, prop: TransferProposal, note: str | None = None) -> dict:
    """Karar kayıtları için okunur bağlam: hangi devir, hangi domain/uygulama, gerekçe."""
    old, new = db.get(Certificate, prop.old_cert_id), db.get(Certificate, prop.new_cert_id)
    dom = db.get(Domain, prop.domain_id) if prop.domain_id else None
    ctx = {"old_id": prop.old_cert_id, "new_id": prop.new_cert_id,
           "old_name": old.name if old else None, "new_name": new.name if new else None,
           "domain": dom.domain if dom else None, "mapping_type": prop.mapping_type,
           "kind": prop.kind, "via": prop.via}
    if note:
        ctx["note"] = note
    return {k: v for k, v in ctx.items() if v is not None}


@router.post("/{proposal_id}/approve", response_model=TransferProposalOut)
def approve_proposal(request: Request, proposal_id: int, body: ProposalDecision | None = None,
                     db: Session = Depends(get_db), user: User = Depends(require_team_or_admin)):
    """Öneriyi onaylar ve devri UYGULAR. Yarış koşuluna karşı yalnız pending→approved
    atomik geçişte ilerler; ikinci eşzamanlı onay 409 alır."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    # Atomik durum geçişi: pending değilse başkası karara bağlamıştır
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status == "pending")
               .update({"status": "approved", "decided_by": user.username,
                        "decided_at": utcnow(),
                        "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu talep zaten karara bağlanmış")
    db.flush()
    db.refresh(prop)
    log_action(db, user.username, "approve", "transfer_proposals", proposal_id,
               _audit_ctx(db, prop, body.note if body else None), request)
    renewal.apply_proposal(db, prop, user.username, request)
    db.commit()
    team_ids = user_team_ids(db, user)
    return _to_out(db, prop, team_ids, user.role == "admin", _can_decide(user))


@router.post("/{proposal_id}/reject", response_model=TransferProposalOut)
def reject_proposal(request: Request, proposal_id: int, body: ProposalDecision | None = None,
                    db: Session = Depends(get_db), user: User = Depends(require_team_or_admin)):
    """Öneriyi reddeder — hiçbir mutasyon olmaz, eski sertifika bu domain için aktif kalır."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status == "pending")
               .update({"status": "rejected", "decided_by": user.username,
                        "decided_at": utcnow(),
                        "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu talep zaten karara bağlanmış")
    log_action(db, user.username, "propose_reject", "transfer_proposals", proposal_id,
               _audit_ctx(db, prop, body.note if body else None), request)
    db.commit()
    db.refresh(prop)
    return _to_out(db, prop, user_team_ids(db, user), user.role == "admin", _can_decide(user))


@router.post("/{proposal_id}/cancel", response_model=TransferProposalOut)
def cancel_proposal(request: Request, proposal_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_role("editor"))):
    """Öneriyi iptal eder (yanlış öneri / yeni sertifika iptali). Onaydan farklı: SY üyeliği
    gerektirmez, çünkü hiçbir devir uygulanmaz — yalnız öneri kapatılır."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Değişiklik talebi bulunamadı")
    # YETKİ (broken-access-control önleme): iptal de bir durum mutasyonudur; sahibi olmayan bir SY
    # ekibinin editörü, başka ekibin bekleyen kararını kapatmamalı. Yalnız admin, MANUEL önerinin
    # OLUŞTURANI veya sahibi SY ekibinin üyesi iptal edebilir.
    # created_by istisnası YALNIZ via='manual' önerilerde geçerli: manuel supersede zaten tetikleyenin
    # eski cert'in bağlı olduğu bir SY ekibine üye olmasını şart koşar (certificates.py:287-297).
    # OTOMATİK yollar (import/vault-sync) created_by'ı kapsamsız tetikleyene yazar — o istisnayla
    # kapsam-dışı bir editör başka ekibin (SKI/subject eşleşmesiyle üretilmiş) önerisini kapatabilirdi.
    if not (user.role == "admin"
            or (prop.via == "manual" and prop.created_by == user.username)
            or (prop.sy_team_id is not None and prop.sy_team_id in user_team_ids(db, user))):
        raise HTTPException(status_code=403,
                            detail="Bu talebi yalnız oluşturan, sahibi SY ekibi üyesi veya admin iptal edebilir")
    # ATOMİK durum geçişi (approve/reject ile aynı desen): yalnız hâlâ AÇIK (pending/approved)
    # ise iptal et. Eşzamanlı approve/reject ile yarışta lost-update'i önler — aksi halde
    # blind UPDATE ... WHERE id=? bir 'applied'/'rejected' kaydı 'cancelled'a ezerdi.
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status.in_(("pending", "approved")))
               .update({"status": "cancelled", "decided_by": user.username,
                        "decided_at": utcnow()}))
    if not updated:
        raise HTTPException(status_code=409, detail="Yalnız açık talepler iptal edilebilir")
    log_action(db, user.username, "propose_cancel", "transfer_proposals", proposal_id,
               _audit_ctx(db, prop), request)
    db.commit()
    db.refresh(prop)
    return _to_out(db, prop, user_team_ids(db, user), user.role == "admin", _can_decide(user))
