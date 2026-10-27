import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Unicode, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.textmatch import ci_equals, ci_like
from app.api.schemas import (
    AuditListOut,
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
from app.db.models import (Application, AuditLog, Certificate, DeploymentFlow, Domain, ScanTarget, Tag,
                            Team, TransferProposal, User, UserTeam)
from app.core.timeutil import ISTANBUL, ist_day_start_utc, ist_to_utc, utcnow
from app.db.session import get_db
from app.services.audit import (CATEGORIES, MASK, category_filter, category_of, diff_fields, log_action,
                                snapshot)
from app.services.audit_labels import meta as audit_labels_meta
from app.services.audit_labels import parse_details, summarize

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
    pw_changed = False
    if "password" in changes:
        password = changes.pop("password")
        if password:
            user.password_hash = hash_password(password)
            pw_changed = True
    # BREAK-GLASS: rol düşürme VEYA pasife alma son aktif admin'i düşürüyorsa engelle.
    new_role = changes.get("role")
    new_active = changes.get("is_active")
    if (new_role is not None or new_active is not None) and _would_orphan_admin(
            db, user, new_role=new_role, new_active=new_active):
        raise HTTPException(status_code=400,
                            detail="Son aktif admin'in rolü/erişimi düşürülemez (önce başka bir admin atayın)")
    diff = diff_fields(user, changes)
    if pw_changed:
        diff["password"] = {"old": MASK, "new": MASK, "masked": True}
    for key, value in changes.items():
        setattr(user, key, value)
    log_action(db, admin.username, "update", "users", user.id,
               {"username": user.username, "changes": diff}, request)
    db.commit()
    return _user_out(db, user)


@router.get("/users/{user_id}/directory")
def user_directory(user_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_role("admin"))):
    """Bir kullanıcının LDAP/AD bilgileri — yalnız yönetici (Kullanıcılar > detay)."""
    from app.api.auth import directory_for
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return directory_for(db, user)


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
    log_action(db, admin.username, "delete", "users", user.id,
               {"username": user.username,
                "snapshot": snapshot(user, ("username", "full_name", "email", "role", "auth_source",
                                            "is_active"))}, request)
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/teams", response_model=list[TeamOut])
def list_teams(type: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(Team)
    if type:
        q = q.filter(Team.type == type)
    teams = q.order_by(Team.name).all()
    if user.role != "admin":
        return teams  # sayılar yalnız yönetim ekranı (admin) için

    def counts(col_team, col_id):
        return dict(db.query(col_team, func.count(col_id)).filter(col_team.isnot(None))
                    .group_by(col_team).all())
    members = counts(UserTeam.team_id, UserTeam.user_id)
    # Sahiplik SY ya da UG kolonu üzerinden (silme kuralıyla aynı)
    dom_sy, dom_ug = counts(Domain.sy_team_id, Domain.id), counts(Domain.ug_team_id, Domain.id)
    app_sy, app_ug = counts(Application.sy_team_id, Application.id), counts(Application.ug_team_id, Application.id)
    out = []
    for t in teams:
        item = TeamOut.model_validate(t)
        item.member_count = members.get(t.id, 0)
        item.domain_count = dom_sy.get(t.id, 0) + dom_ug.get(t.id, 0)
        item.app_count = app_sy.get(t.id, 0) + app_ug.get(t.id, 0)
        out.append(item)
    return out


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
    old_name = team.name
    new_name = (changes.get("name") or "").strip() or None
    if "name" in changes:
        if new_name is None:
            raise HTTPException(status_code=400, detail="Ekip adı boş olamaz")
        changes["name"] = new_name
        clash = (db.query(Team).filter(Team.id != team.id, Team.type == team.type,
                                       ci_equals(Team.name, new_name)).first())
        if clash is not None:
            raise HTTPException(status_code=400, detail=f"'{clash.name}' adında bir ekip zaten var")
    diff = diff_fields(team, changes)
    for key, value in changes.items():
        setattr(team, key, value)
    details = {"name": team.name, "changes": diff}
    # Sertifikanın "Oluşturan Ekip" alanı SY ekibinin ADINI metin olarak tutar (sahiplik mailleri ve
    # düzenleme yetkisi bu adla eşleşir). Ad değişince bu sertifikalar da yeni adı almalı; yoksa
    # ekipten kopar, sahip ekip mail alamaz.
    if team.type == "SY" and new_name is not None and new_name != old_name:
        moved = (db.query(Certificate).filter(Certificate.creator == old_name)
                 .update({Certificate.creator: new_name}, synchronize_session=False))
        details["certificates_creator_renamed"] = moved
    log_action(db, admin.username, "update", "teams", team.id, details, request)
    db.commit()
    return team


@router.delete("/teams/{team_id}")
def delete_team(request: Request, team_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    """Ekip siler (yalnız admin). ADMIN/VIEWER tekilleri silinemez. Domain/uygulama/değişiklik talebi
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
            parts.append(f"{prop} değişiklik talebi")
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
    member = db.get(User, body.user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    exists = db.query(UserTeam).filter_by(user_id=body.user_id, team_id=team_id).first()
    if exists is None:
        db.add(UserTeam(user_id=body.user_id, team_id=team_id))
        log_action(db, admin.username, "add_member", "user_teams", team_id,
                   {"user_id": body.user_id, "member": member.username, "team": team.name}, request)
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
               {"user_id": user_id, "member": target.username if target else None,
                "team": team.name if team else None}, request)
    db.delete(row)
    db.commit()
    return {"ok": True}


_IST = ISTANBUL
AUDIT_LIST_LIMIT = 1000


def _csv_list(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


# Prod AuditLog.Details NTEXT'tir; SQL Server LOWER(ntext)'e izin vermez (ilike → LOWER(...) LIKE
# → hata 8116). NVARCHAR(MAX)'e CAST ile aranır — şema değişmez, ORM'in oluşturduğu
# nvarchar(max) kolonda da aynen çalışır. DİKKAT: UnicodeText KULLANMA — MSSQL dialect'i onu
# NTEXT'e derler; uzunluksuz Unicode() → NVARCHAR(max).
_DETAILS_TEXT = cast(AuditLog.details, Unicode())


def _user_like(like: str):
    """Audit kullanıcı araması: kullanıcı adı ya da users.full_name eşleşmesi."""
    by_name = select(User.username).where(ci_like(User.full_name, like))
    return or_(ci_like(AuditLog.username, like), AuditLog.username.in_(by_name))


def _audit_query(db: Session, *, date_from: date | None = None, date_to: date | None = None,
                 category: str | None = None, username: str | None = None, actor: str | None = None,
                 action: str | None = None, table_name: str | None = None,
                 record_id: str | None = None, q: str | None = None, ip: str | None = None,
                 record: str | None = None, details: str | None = None,
                 since_hours: int | None = None, start: datetime | None = None,
                 end: datetime | None = None):
    """Ortak audit filtresi (liste + export + facets). Tarihler İSTANBUL günüdür; date_to GÜN
    SONUNA kadar dâhildir. action/table_name virgülle çoklu değer alır."""
    qry = db.query(AuditLog)
    if date_from:
        qry = qry.filter(AuditLog.created_at >= ist_day_start_utc(date_from))
    if date_to:
        qry = qry.filter(AuditLog.created_at < ist_day_start_utc(date_to + timedelta(days=1)))
    if since_hours:  # kayan pencere (ör. son 24 saat) — gün sınırından bağımsız
        qry = qry.filter(AuditLog.created_at >= utcnow() - timedelta(hours=since_hours))
    # Mutlak aralık (saat hassasiyetinde; Grafana tarzı seçici). Saat dilimi yoksa İSTANBUL kabul edilir.
    if start:
        qry = qry.filter(AuditLog.created_at >= ist_to_utc(start))
    if end:
        qry = qry.filter(AuditLog.created_at <= ist_to_utc(end))
    if category in CATEGORIES:
        qry = qry.filter(category_filter(category))
    if username:  # kullanıcı adı VEYA Ad Soyad (ör. "Ahmet Yıldız")
        qry = qry.filter(_user_like(f"%{username}%"))
    if actor:  # tam eşleşme — kullanıcı detayındaki "son işlemler"
        qry = qry.filter(AuditLog.username == actor)
    if actions := _csv_list(action):
        qry = qry.filter(AuditLog.action.in_(actions))
    if tables := _csv_list(table_name):
        qry = qry.filter(AuditLog.table_name.in_(tables))
    if record_id:
        qry = qry.filter(AuditLog.record_id == record_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(ci_like(_DETAILS_TEXT, like), ci_like(AuditLog.record_id, like),
                             _user_like(like)))
    if ip:
        qry = qry.filter(ci_like(AuditLog.ip_address, f"%{ip}%"))
    if record:  # "Kayıt" kolonu: kimlik birebir VEYA ad detayda geçiyor (ör. web.aa.com)
        qry = qry.filter(or_(AuditLog.record_id == record, ci_like(_DETAILS_TEXT, f"%{record}%")))
    if details:  # "Değişiklik" kolonu: yalnız detay metni
        qry = qry.filter(ci_like(_DETAILS_TEXT, f"%{details}%"))
    return qry


_LABEL_MODELS = {
    "certificates": (Certificate, "name"), "SSLCertificates": (Certificate, "name"),
    "domains": (Domain, "domain"), "applications": (Application, "app_name"),
    "users": (User, "username"), "teams": (Team, "name"), "user_teams": (Team, "name"),
    "tags": (Tag, "name"), "scan_targets": (ScanTarget, "name"),
    "deployment_flows": (DeploymentFlow, "name"),
}
_LABEL_KEYS = ("name", "domain", "app_name", "username", "job", "category", "target")


def _record_labels(db: Session, rows: list[AuditLog], parsed: dict[int, object]) -> dict[int, str]:
    """Kayıt kimliği → okunur ad. Önce detaydaki ad (o anki ad; silinen kayıtta da durur),
    yoksa tablodan TOPLU çözüm (tablo başına tek sorgu)."""
    labels: dict[int, str] = {}
    pending: dict[str, set[int]] = {}
    for r in rows:
        d = parsed.get(r.id)
        if isinstance(d, dict):
            if r.table_name == "transfer_proposals" and (d.get("old_name") or d.get("new_name")):
                labels[r.id] = f"{d.get('old_name') or '?'} → {d.get('new_name') or '?'}"
                continue
            snap = d.get("snapshot") if isinstance(d.get("snapshot"), dict) else {}
            val = next((src[k] for src in (d, snap) for k in _LABEL_KEYS
                        if isinstance(src.get(k), str) and src.get(k)), None)
            if val:
                labels[r.id] = val
                continue
        if r.table_name in _LABEL_MODELS and (r.record_id or "").isdigit():
            pending.setdefault(r.table_name, set()).add(int(r.record_id))
    resolved: dict[tuple[str, int], str] = {}
    for table, ids in pending.items():
        model, attr = _LABEL_MODELS[table]
        for rid, val in db.query(model.id, getattr(model, attr)).filter(model.id.in_(ids)).all():
            resolved[(table, rid)] = val
    for r in rows:
        if r.id not in labels and (r.record_id or "").isdigit():
            if (val := resolved.get((r.table_name, int(r.record_id)))):
                labels[r.id] = val
    return labels


def _to_audit_out(db: Session, rows: list[AuditLog]) -> list[AuditOut]:
    parsed = {r.id: parse_details(r.details) for r in rows}
    labels = _record_labels(db, rows, parsed)
    usernames = {r.username for r in rows if r.username}
    names = dict(db.query(User.username, User.full_name)
                 .filter(User.username.in_(usernames), User.full_name.isnot(None)).all()) if usernames else {}
    out = []
    for r in rows:
        item = AuditOut.model_validate(r)
        item.user_full_name = names.get(r.username) or None
        item.category = category_of(r.action, r.table_name, r.username)
        item.summary = summarize(r.action, parsed[r.id])
        item.record_label = labels.get(r.id)
        out.append(item)
    return out


@router.get("/audit/meta")
def audit_meta(_: User = Depends(require_role("admin"))):
    """UI etiketleri (işlem/nesne/alan/kategori) — tek kaynak services/audit_labels."""
    return audit_labels_meta()


@router.get("/audit", response_model=AuditListOut)
def list_audit(limit: int = Query(AUDIT_LIST_LIMIT, ge=1, le=AUDIT_LIST_LIMIT),
               category: str | None = None, username: str | None = None, actor: str | None = None,
               action: str | None = None, table_name: str | None = None,
               record_id: str | None = None, q: str | None = None, ip: str | None = None,
               record: str | None = None, details: str | None = None,
               date_from: date | None = None, date_to: date | None = None,
               since_hours: int | None = Query(None, ge=1, le=24 * 366),
               start: datetime | None = None, end: datetime | None = None,
               db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Filtreye uyan EN YENİ `limit` kayıt (varsayılan/en çok 1000). Sınır filtreden SONRA
    uygulanır → eski bir kayıt filtreyle yine bulunur. Daha fazlası için tarih aralığı + CSV."""
    # limit Query ile [1,1000] arası doğrulanır — negatif limit MSSQL'de geçersiz TOP/FETCH → 500 olurdu.
    rows = (_audit_query(db, date_from=date_from, date_to=date_to, category=category,
                         username=username, actor=actor, action=action, table_name=table_name,
                         record_id=record_id, q=q, ip=ip, record=record,
                         details=details, since_hours=since_hours,
                         start=start, end=end)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1).all())
    capped = len(rows) > limit
    return AuditListOut(items=_to_audit_out(db, rows[:limit]), capped=capped, limit=limit)


@router.get("/audit/{entry_id:int}", response_model=AuditOut)
def get_audit_entry(entry_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_role("admin"))):
    """Tek kayıt — URL'de açık kalan detay paneli, liste filtresinde olmasa da yüklenebilsin."""
    row = db.get(AuditLog, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    return _to_audit_out(db, [row])[0]


@router.get("/audit/facets")
def audit_facets(date_from: date | None = None, date_to: date | None = None,
                 since_hours: int | None = Query(None, ge=1, le=24 * 366),
                 start: datetime | None = None, end: datetime | None = None,
                 db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Filtre menüleri için seçenekler + kayıt sayıları (seçili tarih aralığında).
    Kategori sayaçları sekmelerde gösterilir."""
    base = lambda: _audit_query(db, date_from=date_from, date_to=date_to,  # noqa: E731
                                since_hours=since_hours, start=start, end=end)

    def grouped(col):
        return [{"value": v, "count": c} for v, c in
                base().with_entities(col, func.count(AuditLog.id)).group_by(col)
                .order_by(func.count(AuditLog.id).desc()).all() if v]

    categories = {cat: base().filter(category_filter(cat)).count() for cat in CATEGORIES}
    return {"actions": grouped(AuditLog.action), "tables": grouped(AuditLog.table_name),
            "users": grouped(AuditLog.username), "categories": categories,
            "total": sum(categories.values())}


@router.get("/audit/export")
def export_audit(category: str | None = None, username: str | None = None,
                 action: str | None = None, table_name: str | None = None,
                 record_id: str | None = None, q: str | None = None, ip: str | None = None,
                 record: str | None = None, details: str | None = None,
                 date_from: date | None = None, date_to: date | None = None,
                 since_hours: int | None = Query(None, ge=1, le=24 * 366),
                 start: datetime | None = None, end: datetime | None = None,
                 db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Seçili tarih aralığı (+ AYNI filtreler) için tüm denetim kayıtlarını CSV olarak indirir.
    Tarih aralığı limitin yerini alır → limit YOK (aralık sınırlar; aylık rapor). UTF-8 BOM ile
    Excel'de TR karakterler doğru açılır. Zaman İstanbul saatidir (ekranla aynı)."""
    rows = (_audit_query(db, date_from=date_from, date_to=date_to, category=category,
                         username=username, action=action, table_name=table_name,
                         record_id=record_id, q=q, ip=ip, record=record,
                         details=details, since_hours=since_hours,
                         start=start, end=end)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).all())
    labels = audit_labels_meta()
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM → Excel TR karakterleri doğru açar
    writer = csv.writer(buf)
    writer.writerow(["Tarih (İstanbul)", "Kullanıcı", "Ad Soyad", "Kategori", "İşlem", "Nesne", "Kayıt",
                     "Değişiklik", "Detay (ham)", "IP"])
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start:chunk_start + 500]
        for r in _to_audit_out(db, chunk):
            ts = (r.created_at.replace(tzinfo=timezone.utc).astimezone(_IST)
                  .strftime("%Y-%m-%d %H:%M:%S")) if r.created_at else ""
            writer.writerow([
                ts, r.username, r.user_full_name or "", labels["categories"].get(r.category, r.category),
                labels["actions"].get(r.action, r.action),
                labels["tables"].get(r.table_name, r.table_name),
                r.record_label or r.record_id or "", r.summary or "", r.details or "",
                r.ip_address or "",
            ])
    fname = f"audit_{date_from or 'all'}_{date_to or 'all'}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
