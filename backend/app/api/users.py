import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuditOut,
    MemberAdd,
    TeamCreate,
    TeamMemberOut,
    TeamOut,
    TeamUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.core.security import effective_role, get_current_user, hash_password, require_role
from app.db.models import Application, AuditLog, Domain, Team, TransferProposal, User, UserTeam
from app.db.session import get_db
from app.services.audit import log_action

router = APIRouter(prefix="/api", tags=["users"])


def _user_out(db: Session, user: User) -> UserOut:
    """UserOut'u etkin rol (users.role kolonu) + takım üyelikleriyle doldurur. sy_team_* yalnız SY tipi
    (domain formu auto-fill + editor/viewer kapsamı); team_* tüm tipler (UsersTab rozetleri)."""
    memberships = (db.query(Team)
                   .join(UserTeam, UserTeam.team_id == Team.id)
                   .filter(UserTeam.user_id == user.id).all())
    out = UserOut.model_validate(user)
    out.role = effective_role(db, user)  # users.role kolonu değil, ÜYELİKTEN türetilmiş tier
    sy = [t for t in memberships if t.type == "SY"]
    out.sy_team_ids = [t.id for t in sy]
    out.sy_team_names = [t.name for t in sy]
    out.team_ids = [t.id for t in memberships]
    out.team_names = [t.name for t in memberships]
    return out


def _would_orphan_admin(db: Session, user: User, *, new_role: str | None = None,
                        new_active: bool | None = None) -> bool:
    """user şu an AKTİF bir admin (users.role='admin') VE verilen işlem (rol düşürme, pasife alma,
    silme) sonrası başka aktif admin kalmıyorsa True → break-glass koruması (yönetici kilitlenmesini
    önler). new_role/new_active = işlem sonrası hedef durum (silme için new_active=False geçin)."""
    from sqlalchemy import func
    cur_role = (user.role or "").strip().lower()
    if cur_role != "admin" or not user.is_active:
        return False  # user zaten admin/aktif değil → onu değiştirmek son admin'i düşürmez
    eff_role = (new_role if new_role is not None else cur_role)
    eff_active = (new_active if new_active is not None else user.is_active)
    if eff_role == "admin" and eff_active:
        return False  # işlemden sonra hâlâ aktif admin
    others = (db.query(User).filter(
        User.is_active == True,
        func.lower(func.coalesce(User.role, "")) == "admin",
        User.id != user.id).count())
    return others == 0


@router.get("/users", response_model=list[UserOut])
def list_users(limit: int | None = Query(None, ge=1, le=5000), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    # limit/offset OPSİYONEL: verilmezse tüm liste döner (mevcut davranış korunur).
    return [_user_out(db, u) for u in
            db.query(User).order_by(User.username).offset(offset).limit(limit).all()]


@router.post("/users", response_model=UserOut)
def create_user(request: Request, body: UserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kayıtlı")
    if body.auth_source == "local" and not body.password:
        raise HTTPException(status_code=400, detail="Lokal kullanıcı için şifre zorunlu")
    # Prod users.email NOT NULL → boşsa seed ile aynı placeholder (main.py ensure_initial_admin).
    email = body.email or f"{body.username}@jumbo.local"
    # RBAC: rol users.role kolonundan gelir. Verilmezse 'none' → yetkisiz (admin sonra rol atar).
    # editor/viewer için kapsam ayrıca SY takım üyeliğinden gelir (Ekip Üyelikleri'nden eklenir).
    user = User(username=body.username, email=email, full_name=body.full_name,
                auth_source=body.auth_source, role=body.role or "none",
                password_hash=hash_password(body.password) if body.password else "")  # prod password NOT NULL → ldap'ta ""
    db.add(user)
    db.flush()
    log_action(db, admin.username, "create", "users", user.id,
               {"username": user.username, "role": user.role}, request)
    db.commit()
    return _user_out(db, user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(request: Request, user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    # role/is_active için AÇIK null 'dokunma' demektir (schema sözleşmesi). exclude_unset açık
    # null'u koruduğundan, bunları elemezsek {"role": null} kolona NULL yazıp son admin'i orphan
    # eder VE break-glass guard'ını atlardı (new_role=None → guard koşulu False kalır).
    for k in ("role", "is_active"):
        if k in changes and changes[k] is None:
            del changes[k]
    if "password" in changes:
        password = changes.pop("password")
        if password:
            user.password_hash = hash_password(password)
    # BREAK-GLASS: rol düşürme VEYA pasife alma son aktif admin'i düşürüyorsa engelle.
    new_role = changes.get("role")
    new_active = changes.get("is_active")
    if (new_role is not None or new_active is not None) and _would_orphan_admin(
            db, user, new_role=new_role, new_active=new_active):
        raise HTTPException(status_code=400,
                            detail="Son aktif admin'in rolü/erişimi düşürülemez (önce başka bir admin atayın)")
    for key, value in changes.items():
        setattr(user, key, value)
    log_action(db, admin.username, "update", "users", user.id, sorted(changes.keys()), request)
    db.commit()
    return _user_out(db, user)


@router.delete("/users/{user_id}")
def delete_user(request: Request, user_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz")
    if _would_orphan_admin(db, user, new_active=False):  # silme = son etkin admin'i kaldırma
        raise HTTPException(status_code=400, detail="Son aktif admin silinemez")
    log_action(db, admin.username, "delete", "users", user.id, {"username": user.username}, request)
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/teams", response_model=list[TeamOut])
def list_teams(type: str | None = None, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    q = db.query(Team)
    if type:
        q = q.filter(Team.type == type)
    return q.order_by(Team.name).all()


@router.post("/teams", response_model=TeamOut)
def create_team(request: Request, body: TeamCreate, db: Session = Depends(get_db),
                user: User = Depends(require_role("admin"))):
    # ADMIN/VIEWER sistemde TEKİLDİR (startup'ta seed) — elle oluşturulamaz; yalnız SY/UG üretilir.
    if body.type in ("ADMIN", "VIEWER"):
        raise HTTPException(status_code=400,
                            detail="ADMIN/VIEWER takımları sistemde tekildir ve elle oluşturulamaz")
    team = Team(**body.model_dump())
    db.add(team)
    db.flush()
    log_action(db, user.username, "create", "teams", team.id, {"name": team.name}, request)
    db.commit()
    return team


@router.put("/teams/{team_id}", response_model=TeamOut)
def update_team(request: Request, team_id: int, body: TeamUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    """Ekip bilgisini (özellikle bildirim e-postasını) günceller. Yalnız admin.
    SY ekip e-postası, bağlı domainli sertifika pasife alındığında bilgilendirme
    gönderilecek adrestir."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Ekip bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(team, key, value)
    log_action(db, admin.username, "update", "teams", team.id, changes, request)
    db.commit()
    return team


@router.delete("/teams/{team_id}")
def delete_team(request: Request, team_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    """Ekip siler (yalnız admin). ADMIN/VIEWER tekilleri silinemez. Domain/uygulama/devir önerisi
    ile ilişkili ekip silinemez (FK bütünlüğü) — önce ilişkiler kaldırılmalı. Ekibin üyelik
    satırları (user_teams) beraberinde temizlenir."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Ekip bulunamadı")
    if team.type in ("ADMIN", "VIEWER"):
        raise HTTPException(status_code=400,
                            detail="Yönetici/İzleyici takımları sistem tekilidir ve silinemez")
    # Sahiplik/öneri referansı olan ekip silinemez (MSSQL FK bloğunu net mesaja çevir)
    dom = db.query(Domain).filter(
        (Domain.sy_team_id == team_id) | (Domain.ug_team_id == team_id)).count()
    app = db.query(Application).filter(
        (Application.sy_team_id == team_id) | (Application.ug_team_id == team_id)).count()
    prop = db.query(TransferProposal).filter(TransferProposal.sy_team_id == team_id).count()
    if dom or app or prop:
        parts = []
        if dom:
            parts.append(f"{dom} domain")
        if app:
            parts.append(f"{app} uygulama")
        if prop:
            parts.append(f"{prop} devir önerisi")
        raise HTTPException(status_code=400,
                            detail=f"Ekip {', '.join(parts)} ile ilişkili — önce bu ilişkileri kaldırın")
    db.query(UserTeam).filter(UserTeam.team_id == team_id).delete(synchronize_session=False)
    log_action(db, admin.username, "delete", "teams", team_id, {"name": team.name}, request)
    db.delete(team)
    db.commit()
    return {"ok": True}


# ---- SY ekip üyeliği (admin yönetir) ----
@router.get("/teams/{team_id}/members", response_model=list[TeamMemberOut])
def list_team_members(team_id: int, db: Session = Depends(get_db),
                      _: User = Depends(require_role("admin"))):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Ekip bulunamadı")
    rows = (db.query(User).join(UserTeam, UserTeam.user_id == User.id)
            .filter(UserTeam.team_id == team_id).order_by(User.username).all())
    return rows


@router.post("/teams/{team_id}/members", response_model=list[TeamMemberOut])
def add_team_member(request: Request, team_id: int, body: MemberAdd,
                    db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Ekip bulunamadı")
    if db.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    exists = db.query(UserTeam).filter_by(user_id=body.user_id, team_id=team_id).first()
    if exists is None:
        db.add(UserTeam(user_id=body.user_id, team_id=team_id))
        log_action(db, admin.username, "add_member", "user_teams", team_id,
                   {"user_id": body.user_id, "team": team.name}, request)
        db.commit()
    rows = (db.query(User).join(UserTeam, UserTeam.user_id == User.id)
            .filter(UserTeam.team_id == team_id).order_by(User.username).all())
    return rows


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_team_member(request: Request, team_id: int, user_id: int,
                       db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    row = db.query(UserTeam).filter_by(user_id=user_id, team_id=team_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Üyelik bulunamadı")
    # RBAC break-glass: ADMIN takımından son aktif üyeyi çıkarma engellenir (yönetici kilitlenmesi).
    team = db.get(Team, team_id)
    target = db.get(User, user_id)
    if team is not None and team.type == "ADMIN" and target is not None and _would_orphan_admin(db, target):
        raise HTTPException(status_code=400,
                            detail="ADMIN takımının son aktif üyesi çıkarılamaz (önce başka bir ADMIN ekleyin)")
    log_action(db, admin.username, "remove_member", "user_teams", team_id,
               {"user_id": user_id}, request)
    db.delete(row)
    db.commit()
    return {"ok": True}


def _audit_query(db: Session, date_from: date | None, date_to: date | None,
                 table_name: str | None, username: str | None):
    """Ortak audit filtresi (liste + export). date_to GÜN SONUNA kadar dâhildir (< ertesi gün 00:00)."""
    q = db.query(AuditLog)
    if date_from:
        q = q.filter(AuditLog.created_at >= datetime(date_from.year, date_from.month, date_from.day))
    if date_to:
        end = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
        q = q.filter(AuditLog.created_at < end)
    if table_name:
        q = q.filter(AuditLog.table_name == table_name)
    if username:
        q = q.filter(AuditLog.username.ilike(f"%{username}%"))
    return q.order_by(AuditLog.created_at.desc())


@router.get("/audit", response_model=list[AuditOut])
def list_audit(limit: int = Query(200, ge=1, le=1000), table_name: str | None = None,
               username: str | None = None, date_from: date | None = None, date_to: date | None = None,
               db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    # limit Query ile [1,1000] arası doğrulanır — negatif limit MSSQL'de geçersiz TOP/FETCH → 500 olurdu.
    return _audit_query(db, date_from, date_to, table_name, username).limit(limit).all()


@router.get("/audit/export")
def export_audit(table_name: str | None = None, username: str | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Seçili tarih aralığı (+ filtreler) için tüm denetim kayıtlarını CSV olarak indirir. Tarih aralığı
    limitin yerini alır → limit YOK (aralık sınırlar). UTF-8 BOM ile Excel'de TR karakterler doğru açılır."""
    rows = _audit_query(db, date_from, date_to, table_name, username).all()
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM → Excel TR karakterleri doğru açar
    writer = csv.writer(buf)
    writer.writerow(["Tarih (UTC)", "Kullanıcı", "İşlem", "Tablo", "Kayıt", "Detay", "IP"])
    for r in rows:
        writer.writerow([
            r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else "",
            r.username, r.action, r.table_name, r.record_id or "", r.details or "", r.ip_address or "",
        ])
    fname = f"audit_{date_from or 'all'}_{date_to or 'all'}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
