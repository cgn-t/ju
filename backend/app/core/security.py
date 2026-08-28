import hashlib
import hmac
from datetime import datetime, timedelta
from app.core.timeutil import utcnow

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Yetki tier'ı (yüksek = daha çok yetki). viewer VE allviewer salt-okur (0) — aralarındaki fark
# YETKİ değil KAPSAM'dır (viewer takım-kapsamlı, allviewer global; bkz. domain_scope_team_ids).
ROLE_LEVELS = {"viewer": 0, "allviewer": 0, "editor": 1, "admin": 2}
# NOT: "none" bilinçli olarak ROLE_LEVELS'ta YOK → ROLE_LEVELS.get("none", -1) == -1 < viewer(0) →
# rolsüz kullanıcı her require_role'de otomatik 403 alır ("rol atanmadıysa hiçbir şey" kuralı).

# Doğrudan atanabilen (users.role kolonuna yazılan) geçerli roller.
VALID_ROLES = {"admin", "editor", "viewer", "allviewer"}


def effective_role(db: Session, user: User) -> str:
    """Kullanıcının ETKİN yetki rolü. TEK GERÇEK KAYNAK artık users.role kolonudur (admin
    'Kullanıcılar' sekmesinden doğrudan atar). Roller:
      • admin     — global tam yetki (edit + görme)
      • editor    — takım-kapsamlı: yalnız kendi SY ekiplerini görür VE düzenler
      • viewer    — takım-kapsamlı: yalnız kendi SY ekiplerini görür, düzenleyemez (sertifikalar global)
      • allviewer — global salt-okur: her şeyi görür, düzenleyemez
    Kapsam (hangi SY ekipleri) daima SY takım üyeliğinden gelir (bkz. domain_scope_team_ids);
    editor/viewer için ayrıca bir SY takımına üyelik gerekir, aksi halde kapsamı boştur.
    users.role tanınmayan/boş ise (henüz atanmamış) → 'none' (hiçbir şey göremez)."""
    stored = (user.role or "").strip().lower()
    return stored if stored in VALID_ROLES else "none"


def _is_sha256_hex(value: str) -> bool:
    """Değer standart bir SHA-256 hex digest'i mi (64 karakter, tümü hex)?"""
    return len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def hash_password(password: str) -> str:
    """Şifreyi STANDART tuzsuz SHA-256 hex ile hash'ler (prod users.password biçimi).
    Yeni yazılan tüm lokal şifreler bu biçimdedir (64 karakter küçük harf hex)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain: str, hashed: str | None) -> bool:
    """Geçişli doğrulama:
      • SHA-256 hex (yeni/prod biçimi) → sabit-zamanlı karşılaştırma (case-insensitive; prod farklı
        harf düzeni tutabilir).
      • bcrypt ($2...) → eski dev kullanıcıları için passlib fallback (kimse kilitlenmez).
      • boş/tanınmayan → temiz başarısızlık (500 yerine False)."""
    if not hashed:
        return False
    if _is_sha256_hex(hashed):
        computed = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return hmac.compare_digest(computed, hashed.lower())
    if hashed.startswith("$2"):  # legacy bcrypt
        try:
            return pwd_context.verify(plain, hashed)
        except ValueError:
            return False
    return False


def is_local_password(hashed: str | None) -> bool:
    """Kullanıcının GERÇEK yerel şifresi var mı? Yeni biçim SHA-256 hex (64 karakter) VEYA eski
    bcrypt (geçiş) → yerel. Karar auth_source etiketine DEĞİL, hash'in biçimine dayanır. Boş/None/
    tanınmayan değerler yerel sayılmaz → LDAP'a düşer (LDAP kullanıcıları password_hash="" ile işaretli)."""
    if not hashed:
        return False
    return _is_sha256_hex(hashed) or hashed.startswith("$2")


def create_access_token(username: str, role: str) -> str:
    settings = get_settings()
    expire = utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Oturum geçersiz veya süresi dolmuş",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_error
    except JWTError:
        raise credentials_error
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user is None:
        raise credentials_error
    # Rolü users.role'den normalize edip transient yerleştir (büyük harf/boşluk temizlenir, geçersiz
    # değer → 'none'). set_committed_value dirty İŞARETLEMEZ → yazma uçlarındaki commit kolona geri yazmaz.
    set_committed_value(user, "role", effective_role(db, user))
    return user


def require_role(minimum: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS[minimum]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user

    return checker


def user_team_ids(db: Session, user: User) -> set[int]:
    """Kullanıcının üye olduğu YALNIZ SY tipi ekiplerin id kümesi (ADMIN/VIEWER hariç). Tüm çağıranlar
    bunu domain/proposal `sy_team_id` (daima SY) ile karşılaştırır → SY-only filtre semantiği netleştirir."""
    from app.db.models import Team, UserTeam
    return {r.team_id for r in db.query(UserTeam)
            .join(Team, Team.id == UserTeam.team_id)
            .filter(UserTeam.user_id == user.id, Team.type == "SY").all()}


def domain_scope_team_ids(db: Session, user: User) -> set[int] | None:
    """Görünürlük kapsamı. None → GLOBAL (admin veya allviewer: her şeyi görür). Aksi halde
    (editor/viewer/none) yalnız KENDİ SY ekiplerinin id kümesi → yalnız o ekiplerin domain/
    uygulamalarını görür (none → boş küme, hiçbir şey). Kullanım:
    `if scope is not None: q.filter(Model.sy_team_id.in_(scope or {-1}))` (referans: proposals.list)."""
    if user.role in ("admin", "allviewer"):
        return None
    return user_team_ids(db, user)


def can_manage_team_resource(db: Session, user: User, sy_team_id: int | None) -> bool:
    """Bir SY ekibine ait kaynağı (domain eşlemesi, mTLS bağımlılığı) doğrudan
    değiştirebilme yetkisi. ONAY HATTIYLA TUTARLI (require_team_or_admin ile aynı kural):
    admin her zaman; SAHİPSİZ kaynak (sy_team_id NULL) YALNIZ admin (aksi halde editör
    elle detach+attach ile, öneri yolundaki admin-onayını atlardı); sahipli kaynak yalnız
    o ekibin üyesi. Onay hattını baypas eden elle mutasyonları kaynağın sahibine kilitler."""
    if user.role == "admin":
        return True
    if sy_team_id is None:
        return False
    return sy_team_id in user_team_ids(db, user)


def require_team_or_admin(proposal_id: int, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> User:
    """Bir devir önerisini yalnız domain sahibi SY ekibinin EDİTÖR üyesi VEYA admin
    onaylar/reddeder (onay = sertifika devrini UYGULAR, bir yazma işlemidir). Öneri
    sy_team_id'si NULL ise (sahipsiz domain) yalnız admin.

    ÖNEMLİ: rol artık SY üyeliğinden BAĞIMSIZ (users.role tek kaynak). Bir SY ekibine kapsam
    için eklenmiş 'viewer' (Ekip İzleyici, salt-okur) onaylayamaz — bu yüzden üyeliğe EK OLARAK
    editor-tier yetki şartı aranır (aksi halde salt-okur kullanıcı en kritik yazmayı yapardı)."""
    from app.db.models import TransferProposal

    if user.role == "admin":
        return user
    # Salt-okur roller (viewer/allviewer/none) onaylayamaz — SY üyesi olsalar bile
    if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS["editor"]:
        raise HTTPException(status_code=403,
                            detail="Devir önerisini yalnız Ekip Editörü veya admin onaylayabilir")
    prop = db.get(TransferProposal, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Devir önerisi bulunamadı")
    if prop.sy_team_id is None:
        raise HTTPException(status_code=403,
                            detail="Sahipsiz domain — bu öneriyi yalnız admin onaylayabilir")
    if prop.sy_team_id not in user_team_ids(db, user):
        raise HTTPException(status_code=403,
                            detail="Bu öneriyi yalnız domain'in SY ekibi editörü veya admin onaylar")
    return user


# 4 kısıtlı sayfa (Uyum/Devir Önerisi/Keşif/Dağıtım) → Ayarlar > Erişim kategorisindeki switch adı.
PAGE_SETTING_KEY = {
    "policy": "policy_all_roles",
    "proposals": "proposals_all_roles",
    "discovery": "discovery_all_roles",
    "deployments": "deployments_all_roles",
}


def page_visible(db: Session, user: User, page: str) -> bool:
    """Uyum/Devir Önerisi/Keşif/Dağıtım sayfa görünürlüğü. admin VE allviewer HER ZAMAN görür
    (allviewer zaten 'her şeyi görür, düzenleyemez' diye tasarlanmış — bu 4 sayfa istisna değil;
    domain_scope_team_ids'in admin+allviewer'ı eş tuttuğu kuralla tutarlı). Devir Önerisi'nde
    ayrıca SY üyeliği olan HER ZAMAN kendi ekibinin tekliflerini görür — onay mekanizması
    (require_team_or_admin) bu fonksiyondan tamamen BAĞIMSIZ, burada dokunulmuyor; bu yalnız
    LİSTEYİ görebilme kapısı. Bunların dışında yalnız Ayarlar > Erişim'deki ilgili switch açıksa
    (settings_service 'access' kategorisi) görünür."""
    if user.role in ("admin", "allviewer"):
        return True
    if page == "proposals" and user_team_ids(db, user):
        return True
    from app.services.settings_service import get_category
    return bool(get_category(db, "access").get(PAGE_SETTING_KEY[page]))


def require_page_access(page: str, minimum: str = "viewer"):
    """require_role + page_visible birleşik dependency factory. `minimum`: sayfa içindeki belirli
    bir MUTASYON ucu (ör. Keşif adopt/ignore) için görünürlükten AYRI ikinci bir rol tabanı."""
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not page_visible(db, user, page):
            raise HTTPException(status_code=403, detail="Bu sayfa yalnız yöneticilere açık")
        if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS[minimum]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user
    return checker
