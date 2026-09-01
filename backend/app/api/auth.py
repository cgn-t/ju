from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.schemas import LoginRequest, TokenResponse, UserOut
from app.core.security import (PAGE_SETTING_KEY, create_access_token, effective_role,
                                get_current_user, is_local_password, nav_visible, page_visible,
                                verify_password)
from app.db.models import Team, User, UserTeam
from app.db.session import get_db
from app.services import ldap_auth
from app.services.audit import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _login(db: Session, username: str, password: str, request: Request | None) -> TokenResponse:
    username = username.strip()
    user = db.query(User).filter(User.username == username).first()

    authenticated = False
    # Yerel (bcrypt-hash'li) şifresi olan kullanıcı YALNIZ yerelden doğrulanır; LDAP'a düşmez
    # (yanlış şifre → 401). Karar auth_source etiketine değil, gerçek hash'in varlığına dayanır —
    # çünkü auth_source'un DB server_default'u 'ldap' olduğundan legacy/ORM-dışı satırlar yanlış
    # etiketlenip yerel şifreleri olduğu halde LDAP'a düşebiliyordu.
    if user and is_local_password(user.password_hash):
        authenticated = verify_password(password, user.password_hash)
    else:
        # Yerel şifre yok (kullanıcı hiç tanımlı değil veya LDAP hesabı) → AD'ye sor
        result = ldap_auth.authenticate(db, username, password)
        if result.success:
            authenticated = True
            if user is None:
                # RBAC: LDAP kullanıcısı role='none' (yetkisiz) oluşur → hiçbir şey göremez. Yetki AD
                # grubundan DEĞİL, admin'in JUMBO'da rol atamasından gelir (role='none' AÇIKÇA verilir;
                # aksi halde models default'u 'viewer' devreye girip yanlış yetki verirdi).
                # Prod users.email NOT NULL → AD mail boşsa placeholder (seed ile aynı desen).
                # is_active=True AÇIKÇA verilir: kolonun default'u Python-side (flush'ta uygulanır);
                # flush'suz taze nesnede is_active=None kalır ve aşağıdaki `not user.is_active`
                # kontrolü İLK LDAP girişini her zaman 401'e düşürürdü (yerel LDAP E2E'de yakalandı).
                user = User(username=username, auth_source="ldap", is_active=True, role="none",
                            email=result.email or f"{username}@jumbo.local",
                            full_name=result.full_name, password_hash="")  # prod password NOT NULL
                db.add(user)
            else:
                # AD'den rol TÜRETME (result.role tüketilmez); yalnız profil bilgisini tazele.
                user.email = result.email or user.email
                user.full_name = result.full_name or user.full_name

    if not authenticated or user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

    user.last_login = utcnow()
    log_action(db, user.username, "login", "users", user.id, request=request)
    db.commit()
    # Yanıt rolü users.role kolonundan gelir (effective_role normalize eder) — rolsüz kullanıcı 'none'.
    role = effective_role(db, user)
    token = create_access_token(user.username, role)
    return TokenResponse(access_token=token, username=user.username, role=role,
                         full_name=user.full_name, email=user.email)


@router.post("/login", response_model=TokenResponse)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return _login(db, form.username, form.password, request)


@router.post("/login-json", response_model=TokenResponse)
def login_json(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    return _login(db, body.username, body.password, request)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Giriş yapmış kullanıcı + ekip üyelikleri. GET /users (_user_out) ile AYNI semantik:
    sy_team_* YALNIZ SY tipi ekipler (domain formu auto-fill bunu SY varsayar — eskiden tüm
    üyelikler konuyor, ADMIN/VIEWER üyesi kullanıcıda auto-fill'i bozuyordu), team_* tüm tipler."""
    memberships = (db.query(Team).join(UserTeam, UserTeam.team_id == Team.id)
                   .filter(UserTeam.user_id == user.id).all())
    out = UserOut.model_validate(user)
    sy = [t for t in memberships if t.type == "SY"]
    out.sy_team_ids = [t.id for t in sy]
    out.sy_team_names = [t.name for t in sy]
    out.team_ids = [t.id for t in memberships]
    out.team_names = [t.name for t in memberships]
    out.page_access = {page: page_visible(db, user, page) for page in PAGE_SETTING_KEY}
    # Üst navigasyon linki görünürlüğü — page_access'ten FARKI: SY üyeliği carve-out'u yok
    # (bkz. nav_visible). Route erişimi/onay iş akışı page_access ile değişmeden çalışır.
    out.nav_page_access = {page: nav_visible(db, user, page) for page in PAGE_SETTING_KEY}
    return out
