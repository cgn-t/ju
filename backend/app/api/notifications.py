"""Bildirim uçları — süre uyarılarını tetikleme (UI butonu VEYA dış otomasyon).

Günlük 08:00 cron'una ek olarak tarama iki yoldan ANINDA tetiklenebilir:
  • UI (Settings → SMTP → "Şimdi Gönder"): admin JWT ile.
  • DIŞ ARAÇ (cron, zamanlayıcı, izleme sistemi): SMTP ayarlarındaki
    `trigger_api_key` değerini `X-API-Key` başlığında göndererek — login gerekmez:
        curl -X POST https://<host>/api/notifications/expiry-run \
             -H "X-API-Key: <anahtar>"
    Anahtar BOŞSA dış tetikleme kapalıdır (yalnız admin JWT çalışır).

Tetiklenince: bitişine `expiry_warning_days`'ten az gün kalan her sertifika için
paydaşlara AYRI AYRI mail gönderilir — sahibi (oluşturan kullanıcı), bağlı domainlerin
SY ekipleri, client olarak bağlı uygulamaların sahibi SY ekipleri
(bkz. notifier._expiry_stakeholders)."""

import hmac
import logging
import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import ROLE_LEVELS, get_current_user
from app.db.session import get_db
from app.services import notifier
from app.services.audit import log_action
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

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


def _trigger_actor(request: Request,
                   x_api_key: str | None = Header(None, alias="X-API-Key"),
                   token: str | None = Depends(_oauth2_optional),
                   db: Session = Depends(get_db)) -> str:
    """Tetikleme yetkisi: X-API-Key (dış otomasyon) VEYA admin JWT (UI). Audit için
    aktör adı döner. API anahtarı yalnız bu ucu açar."""
    if x_api_key is not None:
        if _too_many_failures():
            raise HTTPException(status_code=429,
                                detail="Çok fazla başarısız deneme — sonra tekrar deneyin")
        expected = get_category(db, "smtp", mask_secrets=False).get("trigger_api_key") or ""
        # Boş anahtar dış tetiklemeyi KAPATIR (boş==boş eşleşmesine izin verme).
        if expected and _keys_match(x_api_key, expected):
            return "external-api"
        _register_failed_attempt()
        logger.warning("Geçersiz bildirim API anahtarı denemesi (ip=%s)",
                       request.client.host if request.client else "?")
        raise HTTPException(status_code=401, detail="Geçersiz API anahtarı")
    if token is not None:
        user = get_current_user(token=token, db=db)  # geçersiz/bayat token → 401
        if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS["admin"]:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok")
        return user.username
    raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli "
                        "(admin oturumu veya X-API-Key başlığı)")


def _run_scan(scan_fn, endpoint: str, request: Request, actor: str, db: Session) -> dict:
    """Ortak tetikleme akışı: dış aktörde uç-bazlı cooldown → tarama (force=True: 7 günlük
    tekrar-önleme atlanır, manuel/dış tetikleme her zaman gönderir) → audit → yanıt.
    Dış anahtar düşük yetkilidir: sertifika adları / alıcı e-postaları gibi envanter
    detayı AYIKLANIR — yalnız sayısal özet döner (admin JWT tam detay alır)."""
    if actor == "external-api":
        # Mail-spam freni: aynı ucun art arda dış tetiklemeleri arasında asgari bekleme.
        now = time.monotonic()
        with _guard_lock:
            if now - _last_external_run.get(endpoint, 0.0) < _RUN_COOLDOWN_SECONDS:
                raise HTTPException(status_code=429,
                                    detail="Tarama az önce çalıştı — lütfen bekleyin")
            _last_external_run[endpoint] = now

    result = scan_fn(db, force=True)
    log_action(db, actor, "notify", "notifications", None,
               {"endpoint": endpoint, "checked": result["checked"],
                "sent": result["sent"], "skipped": result["skipped"]}, request)
    db.commit()

    if actor == "external-api":
        return {"enabled": result["enabled"], "checked": result["checked"],
                "sent": result["sent"], "skipped": result["skipped"],
                "message": result["message"]}
    return result


@router.post("/expiry-run")
def run_expiry_notifications(request: Request, actor: str = Depends(_trigger_actor),
                             db: Session = Depends(get_db)):
    """SÜRESİ YAKLAŞAN sertifikalar (bitişe expiry_warning_days'ten az kalan) için
    paydaşlara ayrı ayrı bilgilendirme maili gönderir."""
    return _run_scan(notifier.send_expiry_notifications, "expiry-run", request, actor, db)


@router.post("/expired-run")
def run_expired_notifications(request: Request, actor: str = Depends(_trigger_actor),
                              db: Session = Depends(get_db)):
    """SÜRESİ GEÇMİŞ ama JUMBO'da hâlâ AKTİF (güncellenmemiş) sertifikalar için
    paydaşlara 'JUMBO'da güncelleyin' hatırlatması gönderir."""
    return _run_scan(notifier.send_expired_notifications, "expired-run", request, actor, db)
