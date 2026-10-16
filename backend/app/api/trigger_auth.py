"""Dış tetikleme yetkisi — X-API-Key (dış otomasyon) VEYA admin JWT (UI).

Bildirim uçları (`/api/notifications/*-run`, anahtar: smtp.trigger_api_key) ve toplu canlı
doğrulama (`/api/domains/live-check-run`, anahtar: live_check.trigger_api_key) aynı korumayı
kullanır. Her özelliğin AYRI anahtarı vardır (en az yetki): mail anahtarı taramayı açamaz.
Anahtar BOŞSA o özellik için dış tetikleme kapalıdır (yalnız admin JWT çalışır).
"""

import hmac
import logging
import threading
import time

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import ROLE_LEVELS, get_current_user
from app.db.session import get_db
from app.services.audit import log_standalone
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)
EXTERNAL_ACTOR = "external-api"

# auto_error=False: Authorization başlığı yoksa 401 FIRLATMAZ (X-API-Key yoluna düşebilelim)
_oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Kaba-kuvvet freni (in-memory, process başına): bu uç JWT'siz erişilebilir olduğundan
# sınırsız anahtar denemesine izin verme. Basit sabit pencere: 60 sn'de >10 BAŞARISIZ
# anahtar denemesi → 429. Restart'ta sıfırlanır (kabul edilir; kalıcı kilit backlog'da).
_FAIL_WINDOW_SECONDS = 60
_FAIL_LIMIT = 10
_RUN_COOLDOWN_SECONDS = 60  # başarılı iki DIŞ tetikleme arası asgari süre (mail-spam freni)
_guard_lock = threading.Lock()
_failed_attempts: list[float] = []
_last_external_run: dict[str, float] = {}  # uç adı → son başarılı dış tetikleme (monotonic)


def external_cooldown(endpoint: str, seconds: int = _RUN_COOLDOWN_SECONDS) -> None:
    """Aynı ucun art arda DIŞ tetiklemeleri arasında asgari bekleme (aksi halde 429)."""
    now = time.monotonic()
    with _guard_lock:
        if now - _last_external_run.get(endpoint, 0.0) < seconds:
            raise HTTPException(status_code=429, detail="Az önce tetiklendi — lütfen bekleyin")
        _last_external_run[endpoint] = now


def _register_failed_attempt() -> None:
    now = time.monotonic()
    with _guard_lock:
        _failed_attempts[:] = [t for t in _failed_attempts if now - t < _FAIL_WINDOW_SECONDS]
        _failed_attempts.append(now)


def _too_many_failures() -> bool:
    now = time.monotonic()
    with _guard_lock:
        _failed_attempts[:] = [t for t in _failed_attempts if now - t < _FAIL_WINDOW_SECONDS]
        return len(_failed_attempts) >= _FAIL_LIMIT


def _keys_match(provided: str, expected: str) -> bool:
    """Sabit-zamanlı karşılaştırma — BYTES üzerinden: hmac.compare_digest iki str ile
    yalnız ASCII kabul eder; non-ASCII başlık/anahtar (ör. Türkçe karakter) TypeError →
    HTTP 500 üretirdi (review bulgusu, reprolu). Bytes karşılaştırması her değerle çalışır.

    Latin-1 kurtarma: HTTP başlıkları Starlette'te latin-1 çözülür; istemci UTF-8 bayt
    gönderirse (curl'de Türkçe karakterli anahtar) str mojibake olur. latin-1'e geri
    kodlayıp UTF-8 çözmek orijinali kurtarır → Türkçe anahtarlar da çalışır."""
    try:
        exp = expected.encode("utf-8")
        if hmac.compare_digest(provided.encode("utf-8", errors="replace"), exp):
            return True
        try:
            recovered = provided.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(recovered.encode("utf-8"), exp)
    except Exception:
        return False


def trigger_actor(category: str, label: str):
    """FastAPI bağımlılığı üretir: `category.trigger_api_key` ile eşleşen X-API-Key VEYA admin
    JWT. Audit için aktör adı döner (dış anahtar → 'external-api')."""
    def dependency(request: Request,
                   x_api_key: str | None = Header(None, alias="X-API-Key"),
                   token: str | None = Depends(_oauth2_optional),
                   db: Session = Depends(get_db)) -> str:
        return _resolve_actor(request, x_api_key, token, db, category, label)
    return dependency


def _resolve_actor(request: Request, x_api_key: str | None, token: str | None, db: Session,
                   category: str, label: str) -> str:
    if x_api_key is not None:
        if _too_many_failures():
            raise HTTPException(status_code=429,
                                detail="Çok fazla başarısız deneme — sonra tekrar deneyin")
        expected = get_category(db, category, mask_secrets=False).get("trigger_api_key") or ""
        # Boş anahtar dış tetiklemeyi KAPATIR (boş==boş eşleşmesine izin verme).
        if expected and _keys_match(x_api_key, expected):
            return EXTERNAL_ACTOR
        _register_failed_attempt()
        logger.warning("Geçersiz %s API anahtarı denemesi (ip=%s)", label,
                       request.client.host if request.client else "?")
        log_standalone(EXTERNAL_ACTOR, "login_failed", category, None,
                       {"reason": f"Geçersiz {label} API anahtarı", "endpoint": request.url.path},
                       request)
        raise HTTPException(status_code=401, detail="Geçersiz API anahtarı")
    if token is not None:
        user = get_current_user(token=token, db=db)  # geçersiz/bayat token → 401
        if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS["admin"]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user.username
    raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli "
                        "(admin oturumu veya X-API-Key başlığı)")


