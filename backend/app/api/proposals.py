"""Sertifika devir önerileri — onay hattı.

JUMBO hiçbir devri kendiliğinden uygulamaz; her devir bir TransferProposal olur ve
domain sahibi SY ekibinin (veya admin) onayını bekler. Onay = uygula (apply_proposal),
tek mutasyon kapısı. Reddet/İptal önerileri kapatır, hiçbir mutasyon yapmaz.
"""

from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.schemas import ProposalDecision, TransferProposalOut
from app.core.security import (
    ROLE_LEVELS,
    require_page_access,
    require_role,
    require_team_or_admin,
    user_team_ids,
)
from app.db.models import Application, Certificate, Domain, TransferProposal, User
from app.db.session import get_db
from app.services import renewal
from app.services.audit import log_action

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


def _can_decide(user: User) -> bool:
    """Öneriyi onaylayabilme yetkisi rol tier'ından: yalnız editor+ (viewer/allviewer salt-okur).
    Kapsam (SY üyeliği) ayrıca gereklidir; bu yalnız YETKİ tier kapısıdır (require_team_or_admin ile eş)."""
    return ROLE_LEVELS.get(user.role, -1) >= ROLE_LEVELS["editor"]


def _to_out(db: Session, p: TransferProposal, team_ids: set[int], is_admin: bool,
            is_editor: bool = False) -> TransferProposalOut:
    old = db.get(Certificate, p.old_cert_id)
    new = db.get(Certificate, p.new_cert_id)
    dom = db.get(Domain, p.domain_id) if p.domain_id else None
    app_row = db.get(Application, p.app_id) if p.app_id else None
    # Karar yetkisi = admin VEYA (editor-tier VE öneri SY ekibinin üyesi). viewer/allviewer
    # SY üyesi olsa bile onaylayamaz (require_team_or_admin ile birebir aynı kural).
    can = is_admin or (is_editor and p.sy_team_id is not None and p.sy_team_id in team_ids)
    return TransferProposalOut(
        id=p.id, old_cert_id=p.old_cert_id, old_cert_name=old.name if old else None,
        new_cert_id=p.new_cert_id, new_cert_name=new.name if new else None,
        domain_id=p.domain_id, domain_name=dom.domain if dom else None,
        mapping_type=p.mapping_type, app_dependency_id=p.app_dependency_id,
        app_id=p.app_id, app_name=app_row.app_name if app_row else None, kind=p.kind or "transfer",
        sy_team_id=p.sy_team_id, sy_team_name=p.sy_team.name if p.sy_team else None,
        status=p.status, signal=p.signal, via=p.via, live_seen=p.live_seen,
        created_by=p.created_by, created_at=p.created_at, decided_by=p.decided_by,
        decided_at=p.decided_at, note=p.note, can_decide=can and p.status == "pending")


@router.get("", response_model=list[TransferProposalOut])
def list_proposals(status: str | None = "pending", mine: bool = False,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_page_access("proposals"))):
    """Devir önerileri. Admin hepsini görür; diğerleri yalnız üye oldukları SY ekibinin
    (sy_team_id) önerilerini. mine=true admin için de yalnız kendi ekiplerini süzer.
    Görünürlük: require_page_access('proposals') — SY üyeleri kendi tekliflerini her zaman
    görür, alakasız kullanıcılar yalnız Ayarlar>Erişim açıksa (bkz. security.page_visible)."""
    is_admin = user.role == "admin"
    team_ids = user_team_ids(db, user)
    q = db.query(TransferProposal)
    if status:
        q = q.filter(TransferProposal.status == status)
    if not is_admin or mine:
        # Sahipsiz (sy_team_id NULL) öneriler yalnız admin'e görünür
        q = q.filter(TransferProposal.sy_team_id.in_(team_ids or {-1}))
    rows = q.order_by(TransferProposal.created_at.desc()).all()
    # Sertifikası silinmiş orphan önerileri gösterme (savunma amaçlı; delete zaten temizler)
    return [_to_out(db, p, team_ids, is_admin, _can_decide(user)) for p in rows
            if db.get(Certificate, p.old_cert_id) and db.get(Certificate, p.new_cert_id)]


@router.get("/{proposal_id}/group", response_model=list[TransferProposalOut])
def proposal_group(proposal_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_page_access("proposals"))):
    """Bu önerinin ait olduğu devrin (aynı old→new cert) TÜM bekleyen domain önerileri.
    Tek sertifika çok domaine bağlıysa her domain kendi SY'since ayrı onaylanır; bu uç,
    kullanıcının KARAR VEREMEYECEĞİ kardeş domainleri de listeler (yalnız farkındalık —
    sertifikanın SAN'ı zaten tüm domainleri açığa vurduğu için ek ifşa değildir).
    Erişim: yalnız bu öneriyi görebilen (admin veya sahibi SY üyesi) grubu çekebilir."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
    is_admin = user.role == "admin"
    team_ids = user_team_ids(db, user)
    if not (is_admin or (prop.sy_team_id is not None and prop.sy_team_id in team_ids)):
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
    rows = (db.query(TransferProposal)
            .filter(TransferProposal.old_cert_id == prop.old_cert_id,
                    TransferProposal.new_cert_id == prop.new_cert_id,
                    TransferProposal.status == "pending")
            .order_by(TransferProposal.id.asc()).all())
    return [_to_out(db, p, team_ids, is_admin, _can_decide(user)) for p in rows
            if db.get(Certificate, p.old_cert_id) and db.get(Certificate, p.new_cert_id)]


@router.post("/{proposal_id}/approve", response_model=TransferProposalOut)
def approve_proposal(request: Request, proposal_id: int, body: ProposalDecision | None = None,
                     db: Session = Depends(get_db), user: User = Depends(require_team_or_admin)):
    """Öneriyi onaylar ve devri UYGULAR. Yarış koşuluna karşı yalnız pending→approved
    atomik geçişte ilerler; ikinci eşzamanlı onay 409 alır."""
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
    # Atomik durum geçişi: pending değilse başkası karara bağlamıştır
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status == "pending")
               .update({"status": "approved", "decided_by": user.username,
                        "decided_at": utcnow(),
                        "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu öneri zaten karara bağlanmış")
    db.flush()
    db.refresh(prop)
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
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status == "pending")
               .update({"status": "rejected", "decided_by": user.username,
                        "decided_at": utcnow(),
                        "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu öneri zaten karara bağlanmış")
    log_action(db, user.username, "propose_reject", "transfer_proposals", proposal_id,
               {"old_id": prop.old_cert_id, "new_id": prop.new_cert_id}, request)
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
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
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
                            detail="Bu öneriyi yalnız oluşturan, sahibi SY ekibi üyesi veya admin iptal edebilir")
    # ATOMİK durum geçişi (approve/reject ile aynı desen): yalnız hâlâ AÇIK (pending/approved)
    # ise iptal et. Eşzamanlı approve/reject ile yarışta lost-update'i önler — aksi halde
    # blind UPDATE ... WHERE id=? bir 'applied'/'rejected' kaydı 'cancelled'a ezerdi.
    updated = (db.query(TransferProposal)
               .filter(TransferProposal.id == proposal_id,
                       TransferProposal.status.in_(("pending", "approved")))
               .update({"status": "cancelled", "decided_by": user.username,
                        "decided_at": utcnow()}))
    if not updated:
        raise HTTPException(status_code=409, detail="Yalnız açık öneriler iptal edilebilir")
    log_action(db, user.username, "propose_cancel", "transfer_proposals", proposal_id,
               {"old_id": prop.old_cert_id, "new_id": prop.new_cert_id}, request)
    db.commit()
    db.refresh(prop)
    return _to_out(db, prop, user_team_ids(db, user), user.role == "admin", _can_decide(user))
