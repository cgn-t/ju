"""Otomatik CA sertifika alımı (issuance) — CA profil yönetimi + istek onay hattı.

Onay UX'i (atomik CAS approve/reject/cancel) `app/api/proposals.py` deseninin KOPYASIDIR — neden
ayrı bir tablo/uç kümesi olduğu `app/services/issuance.py` docstring'inde açıklanır. `/approve`
gerçek CA çağrısını SENKRON YAPMAZ (yalnız durumu 'approved'a çevirir) — asıl çağrı
`notifier.run_pending_issuance` scheduler job'undan yapılır (CA gecikmesi isteği bloklamasın)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.schemas import (
    IssuanceCsrSubmit,
    IssuanceProfileCreate,
    IssuanceProfileOut,
    IssuanceProfileUpdate,
    IssuanceRequestCreate,
    IssuanceRequestOut,
    ProposalDecision,
)
from app.core.crypto import get_fernet
from app.core.security import (
    ROLE_LEVELS,
    can_manage_team_resource,
    require_issuance_team_or_admin,
    require_page_access,
    require_role,
    user_team_ids,
)
from app.core.timeutil import utcnow
from app.db.models import Domain, IssuanceProfile, IssuanceRequest, User
from app.db.session import get_db
from app.services import issuance as issuance_service
from app.services.audit import log_action
from app.services.settings_service import get_category

router = APIRouter(prefix="/api/issuance", tags=["issuance"])

_SECRET_FIELDS = ("acme_account_key", "eab_hmac_key")


# ---- CA profilleri — YAZMA admin-only (Vault/Jenkins ayarlarıyla aynı hassasiyet), OKUMA
# editor+ (SY editörünün kendi domaininde hangi profili seçeceğini görebilmesi için;
# IssuanceProfileOut hiçbir zaman hassas alan (acme_account_key/eab_hmac_key) döndürmez).

@router.get("/profiles", response_model=list[IssuanceProfileOut])
def list_profiles(db: Session = Depends(get_db), _: User = Depends(require_role("editor"))):
    return db.query(IssuanceProfile).order_by(IssuanceProfile.name).all()


@router.post("/profiles", response_model=IssuanceProfileOut)
def create_profile(request: Request, body: IssuanceProfileCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    f = get_fernet()
    data = body.model_dump()
    for field in _SECRET_FIELDS:
        value = data.pop(field, None)
        if value:
            if not f:
                raise HTTPException(status_code=400,
                                    detail="FERNET_KEY tanımlı değil — hassas alan şifrelenemez")
            data[field] = f.encrypt(value.encode()).decode()
    profile = IssuanceProfile(**data, created_by=user.username)
    db.add(profile)
    db.flush()
    log_action(db, user.username, "create", "issuance_profiles", profile.id,
              {"name": profile.name, "ca_type": profile.ca_type}, request)
    db.commit()
    db.refresh(profile)
    return profile


@router.put("/profiles/{profile_id}", response_model=IssuanceProfileOut)
def update_profile(request: Request, profile_id: int, body: IssuanceProfileUpdate,
                   db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    profile = db.get(IssuanceProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="CA profili bulunamadı")
    f = get_fernet()
    data = body.model_dump(exclude_unset=True)
    for field in _SECRET_FIELDS:
        if field in data:
            value = data.pop(field)
            if value:
                if not f:
                    raise HTTPException(status_code=400,
                                        detail="FERNET_KEY tanımlı değil — hassas alan şifrelenemez")
                setattr(profile, field, f.encrypt(value.encode()).decode())
    for key, value in data.items():
        setattr(profile, key, value)
    profile.updated_at = utcnow()
    log_action(db, user.username, "update", "issuance_profiles", profile.id,
              {"fields": sorted(data.keys())}, request)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/profiles/{profile_id}")
def delete_profile(request: Request, profile_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    profile = db.get(IssuanceProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="CA profili bulunamadı")
    in_use = db.query(Domain).filter(Domain.issuance_profile_id == profile_id).count()
    if in_use:
        raise HTTPException(status_code=400,
                            detail=f"Bu profil {in_use} domain tarafından kullanılıyor — önce başka bir profile taşıyın")
    open_requests = (db.query(IssuanceRequest)
                     .filter(IssuanceRequest.profile_id == profile_id,
                             IssuanceRequest.status.in_(issuance_service.OPEN_STATUSES)).count())
    if open_requests:
        raise HTTPException(status_code=400,
                            detail=f"Bu profile bağlı {open_requests} açık istek var — önce sonuçlandırın")
    db.delete(profile)
    log_action(db, user.username, "delete", "issuance_profiles", profile_id, None, request)
    db.commit()
    return {"detail": "Silindi"}


# ---- İstekler ----

def _can_decide(user: User) -> bool:
    return ROLE_LEVELS.get(user.role, -1) >= ROLE_LEVELS["editor"]


def _to_out(db: Session, req: IssuanceRequest, team_ids: set[int], is_admin: bool,
           is_editor: bool = False) -> IssuanceRequestOut:
    domain = db.get(Domain, req.domain_id)
    profile = db.get(IssuanceProfile, req.profile_id)
    can = is_admin or (is_editor and req.sy_team_id is not None and req.sy_team_id in team_ids)
    return IssuanceRequestOut(
        id=req.id, domain_id=req.domain_id, domain_name=domain.domain if domain else None,
        profile_id=req.profile_id, profile_name=profile.name if profile else None,
        sy_team_id=req.sy_team_id, sy_team_name=req.sy_team.name if req.sy_team else None,
        status=req.status, method=req.method, common_name=req.common_name,
        sans=json.loads(req.sans) if req.sans else [], has_csr=bool(req.csr_pem),
        requested_ttl_hours=req.requested_ttl_hours, challenge_type=req.challenge_type,
        attempt_count=req.attempt_count, last_error=req.last_error,
        result_cert_id=req.result_cert_id,
        result_cert_name=req.result_cert.name if req.result_cert else None,
        trigger=req.trigger, zero_touch=req.zero_touch, created_by=req.created_by,
        created_at=req.created_at, decided_by=req.decided_by, decided_at=req.decided_at,
        submitted_at=req.submitted_at, finished_at=req.finished_at, note=req.note,
        can_decide=can and req.status == "pending_approval")


@router.get("", response_model=list[IssuanceRequestOut])
def list_requests(status: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require_page_access("issuance"))):
    """Admin hepsini görür; diğerleri yalnız üye oldukları SY ekibinin isteklerini
    (require_page_access('issuance') — SY üyeleri bu ayardan bağımsız kendi isteklerini
    her zaman görür, alakasız kullanıcılar yalnız Ayarlar>Erişim açıksa)."""
    is_admin = user.role == "admin"
    team_ids = user_team_ids(db, user)
    q = db.query(IssuanceRequest)
    if status:
        q = q.filter(IssuanceRequest.status == status)
    if not is_admin:
        q = q.filter(IssuanceRequest.sy_team_id.in_(team_ids or {-1}))
    rows = q.order_by(IssuanceRequest.created_at.desc()).all()
    return [_to_out(db, r, team_ids, is_admin, _can_decide(user)) for r in rows]


@router.post("", response_model=IssuanceRequestOut)
def create_issuance_request(request: Request, body: IssuanceRequestCreate,
                            db: Session = Depends(get_db),
                            user: User = Depends(require_role("editor"))):
    domain = db.get(Domain, body.domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain bulunamadı")
    if not can_manage_team_resource(db, user, domain.sy_team_id):
        raise HTTPException(status_code=403, detail="Bu domain için istek açma yetkiniz yok")
    profile_id = body.profile_id or domain.issuance_profile_id
    if profile_id is None:
        profile_id = get_category(db, "issuance", mask_secrets=False).get("default_profile_id")
    if profile_id is None:
        raise HTTPException(status_code=400,
                            detail="CA profili belirtilmedi ve varsayılan profil tanımlı değil")
    profile = db.get(IssuanceProfile, profile_id)
    if profile is None or not profile.enabled:
        raise HTTPException(status_code=400, detail="CA profili bulunamadı veya kapalı")
    if issuance_service.has_open_request(db, domain.id):
        raise HTTPException(status_code=409, detail="Bu domain için zaten açık bir istek var")
    req = issuance_service.create_request(db, domain, profile, username=user.username, trigger="manual")
    log_action(db, user.username, "issuance_request_create", "issuance_requests", req.id,
              {"domain": domain.domain, "profile": profile.name}, request)
    db.commit()
    db.refresh(req)
    team_ids = user_team_ids(db, user)
    return _to_out(db, req, team_ids, user.role == "admin", _can_decide(user))


@router.post("/{request_id}/csr", response_model=IssuanceRequestOut)
def submit_csr(request: Request, request_id: int, body: IssuanceCsrSubmit,
              db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    req = db.get(IssuanceRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="İstek bulunamadı")
    if not can_manage_team_resource(db, user, req.sy_team_id):
        raise HTTPException(status_code=403, detail="Bu isteğe CSR ekleme yetkiniz yok")
    try:
        issuance_service.submit_csr(db, req, body.csr_pem, username=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(req)
    team_ids = user_team_ids(db, user)
    return _to_out(db, req, team_ids, user.role == "admin", _can_decide(user))


@router.post("/{request_id}/approve", response_model=IssuanceRequestOut)
def approve_request(request: Request, request_id: int, body: ProposalDecision | None = None,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_issuance_team_or_admin)):
    """Yalnız durumu 'approved'a çevirir — gerçek CA çağrısı SENKRON YAPILMAZ (bkz. modül
    docstring'i). Yarış koşuluna karşı yalnız pending_approval→approved atomik geçişte ilerler."""
    req = db.get(IssuanceRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="İstek bulunamadı")
    updated = (db.query(IssuanceRequest)
              .filter(IssuanceRequest.id == request_id,
                      IssuanceRequest.status == "pending_approval")
              .update({"status": "approved", "decided_by": user.username, "decided_at": utcnow(),
                       "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu istek zaten karara bağlanmış")
    log_action(db, user.username, "issuance_approve", "issuance_requests", request_id, None, request)
    db.commit()
    db.refresh(req)
    team_ids = user_team_ids(db, user)
    return _to_out(db, req, team_ids, user.role == "admin", _can_decide(user))


@router.post("/{request_id}/reject", response_model=IssuanceRequestOut)
def reject_request(request: Request, request_id: int, body: ProposalDecision | None = None,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_issuance_team_or_admin)):
    req = db.get(IssuanceRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="İstek bulunamadı")
    updated = (db.query(IssuanceRequest)
              .filter(IssuanceRequest.id == request_id,
                      IssuanceRequest.status == "pending_approval")
              .update({"status": "rejected", "decided_by": user.username, "decided_at": utcnow(),
                       "note": body.note if body else None}))
    if not updated:
        raise HTTPException(status_code=409, detail="Bu istek zaten karara bağlanmış")
    log_action(db, user.username, "issuance_reject", "issuance_requests", request_id, None, request)
    db.commit()
    db.refresh(req)
    team_ids = user_team_ids(db, user)
    return _to_out(db, req, team_ids, user.role == "admin", _can_decide(user))


@router.post("/{request_id}/cancel", response_model=IssuanceRequestOut)
def cancel_request(request: Request, request_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role("editor"))):
    """Onaydan farklı: SY üyeliği gerektirmez YALNIZCA oluşturan/sahibi ekip/admin içinse —
    proposals.py::cancel_proposal ile aynı yetki deseni (broken-access-control önleme)."""
    req = db.get(IssuanceRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="İstek bulunamadı")
    if not (user.role == "admin"
            or req.created_by == user.username
            or (req.sy_team_id is not None and req.sy_team_id in user_team_ids(db, user))):
        raise HTTPException(status_code=403,
                            detail="Bu isteği yalnız oluşturan, sahibi SY ekibi üyesi veya admin iptal edebilir")
    updated = (db.query(IssuanceRequest)
              .filter(IssuanceRequest.id == request_id,
                      IssuanceRequest.status.in_(("pending_approval", "approved")))
              .update({"status": "cancelled", "decided_by": user.username, "decided_at": utcnow()}))
    if not updated:
        raise HTTPException(status_code=409, detail="Yalnız açık istekler iptal edilebilir")
    log_action(db, user.username, "issuance_cancel", "issuance_requests", request_id, None, request)
    db.commit()
    db.refresh(req)
    team_ids = user_team_ids(db, user)
    return _to_out(db, req, team_ids, user.role == "admin", _can_decide(user))
