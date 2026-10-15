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
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.api.schemas import MailHistoryDetailOut, MailHistoryListOut, MailHistoryOut
from app.core.security import ROLE_LEVELS, get_current_user, require_role
from app.db.models import Certificate, Domain, MailQueue, Notification, User
from app.db.session import get_db
from app.core.timeutil import time_window
from app.services import mail_history, notifier
from app.services.audit import log_action, log_standalone
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
        log_standalone("external-api", "login_failed", "notifications", None,
                       {"reason": "Geçersiz bildirim API anahtarı", "endpoint": request.url.path},
                       request)
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


@router.post("/proposal-run")
def run_proposal_notifications(request: Request, actor: str = Depends(_trigger_actor),
                               db: Session = Depends(get_db)):
    """Onay kuyruğunda BEKLEYEN devir önerileri için ilgili SY ekiplerine (ekip başına tek mail)
    hatırlatma gönderir. Dış otomasyon (X-API-Key) veya admin JWT tetikler; ayarlardaki
    auto_proposal_reminder_enabled bayrağından ETKİLENMEZ — çağrıldığında her zaman gönderir."""
    return _run_scan(notifier.send_pending_proposal_notifications, "proposal-run", request, actor, db)


MAIL_HISTORY_LIMIT = 1000


def _history_filters(channel, status, mail_type, q, recipient, subject, record,
                     since_hours, start, end, date_from, date_to) -> mail_history._Filters:
    lo, hi = time_window(since_hours=since_hours, start=start, end=end,
                         date_from=date_from, date_to=date_to)
    return mail_history._Filters(
        channel=channel or None, status=status if status in mail_history.STATUSES else None,
        mail_type=mail_type if mail_type in mail_history.MAIL_TYPES else None,
        q=q or None, recipient=recipient or None, subject=subject or None, record=record or None,
        lo=lo, hi=hi)


@router.get("/history", response_model=MailHistoryListOut)
def list_mail_history(
        limit: int = Query(MAIL_HISTORY_LIMIT, ge=1, le=MAIL_HISTORY_LIMIT),
        channel: str | None = None,          # vars. frontend 'email' gönderir; boş = tüm kanallar
        status: str | None = None,           # sent | pending | failed
        mail_type: str | None = None,        # expiry | expired | deactivated | proposal | other
        q: str | None = None,                # genel arama: alıcı / konu / sertifika / domain
        search: str | None = None,           # (geriye uyum: q ile aynı)
        recipient: str | None = None, subject: str | None = None, record: str | None = None,
        since_hours: int | None = Query(None, ge=1, le=24 * 366),
        start: datetime | None = None, end: datetime | None = None,   # İstanbul saati
        date_from: date | None = None, date_to: date | None = None,   # İstanbul günü
        db: Session = Depends(get_db),
        _: User = Depends(require_role("admin"))):
    """Admin MAIL GÖNDERİM GEÇMİŞİ — filtreye uyan en yeni `limit` (≤1000) kayıt. Tüm filtreler
    (durum dahil) SQL'de, limitten ÖNCE uygulanır. Ayrıntı: services/mail_history."""
    f = _history_filters(channel, status, mail_type, q or search, recipient, subject, record,
                         since_hours, start, end, date_from, date_to)
    items, capped = mail_history.list_history(db, f, limit)
    return MailHistoryListOut(items=[MailHistoryOut(**r) for r in items], capped=capped, limit=limit)


@router.get("/history/facets")
def mail_history_facets(
        channel: str | None = None, status: str | None = None, mail_type: str | None = None,
        q: str | None = None, recipient: str | None = None, subject: str | None = None,
        record: str | None = None,
        since_hours: int | None = Query(None, ge=1, le=24 * 366),
        start: datetime | None = None, end: datetime | None = None,
        date_from: date | None = None, date_to: date | None = None,
        db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Sekme (durum) ve tür filtresi sayaçları — liste ile aynı filtreler."""
    f = _history_filters(channel, status, mail_type, q, recipient, subject, record,
                         since_hours, start, end, date_from, date_to)
    return mail_history.facets(db, f)


@router.post("/history/{source}/{item_id}/retry")
def retry_mail(request: Request, source: str, item_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    """Başarısız maili yeniden kuyruğa alır (pending, deneme sayacı sıfırlanır); periyodik kuyruk
    boşaltma işi gönderir. Alıcısı bilinmeyen (hiç denenemeyen) hata kayıtları alınamaz."""
    mq = mail_history.queue_row_for(db, source, item_id)
    if mq is None:
        raise HTTPException(status_code=404, detail="Bu kayda bağlı bir kuyruk satırı yok")
    if not mail_history._retryable(mq):
        raise HTTPException(status_code=409, detail="Yalnız alıcısı belli BAŞARISIZ mailler yeniden kuyruğa alınabilir")
    prev_error = mq.last_error
    mail_history.requeue(mq)
    log_action(db, user.username, "mail_retry", "mail_queue", mq.id,
               {"subject": mq.subject, "recipients": mail_history.recipients_of(mq.to_addresses),
                "previous_error": (prev_error or "")[:300]}, request)
    db.commit()
    return {"ok": True, "status": mq.status}


@router.get("/history/{source}/{item_id}", response_model=MailHistoryDetailOut)
def get_mail_history_detail(source: str, item_id: int, db: Session = Depends(get_db),
                            _: User = Depends(require_role("admin"))):
    """Tek bir mail geçmişi kaydının TAM detayı — liste ekranındaki satıra tıklanınca çağrılır.
    source='notification' → mail_queue_id doluysa (queue_enabled akışı) GERÇEK durum/zaman ve
    gövde ilişkili mail_queue satırından okunur; NULL ise doğrudan gönderim başarılıdır (gövde
    saklanmaz, yalnız özet alanları kalıcıdır). source='queue' → doğrudan mail_queue satırı,
    gövde her zaman dolu (henüz teslim edilmemiş/başarısız mail kuyrukta saklanır)."""
    if source == "notification":
        n = db.get(Notification, item_id)
        if n is None:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        cname = db.get(Certificate, n.certificate_id).name if n.certificate_id else None
        dname = db.get(Domain, n.domain_id).domain if n.domain_id else None
        mq = db.get(MailQueue, n.mail_queue_id) if n.mail_queue_id else None
        if mq is not None:
            status, error, attempts = mq.status, mq.last_error, mq.attempts
            queued_at, delivered_at = mq.created_at, mq.sent_at
            body_text, body_html = mq.body_text, mq.body_html
        else:
            status, error, attempts = "sent", None, None
            queued_at = delivered_at = n.sent_at
            body_text = body_html = None
        return MailHistoryDetailOut(
            id=n.id, source="notification", certificate_id=n.certificate_id,
            certificate_name=cname, domain_id=n.domain_id, domain_name=dname,
            recipient=n.recipient, subject=n.subject, days_left=n.days_left,
            channel=n.channel or "email", status=status, error=error, attempts=attempts,
            sent_at=delivered_at or queued_at, queued_at=queued_at, delivered_at=delivered_at,
            body_text=body_text, body_html=body_html, mail_type=mail_history.classify(n.subject),
            stakeholder=mail_history.stakeholder_of(n.subject),
            recipients=mail_history.recipients_of(n.recipient), retryable=mail_history._retryable(mq))
    if source == "queue":
        i = db.get(MailQueue, item_id)
        if i is None:
            raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
        cname = db.get(Certificate, i.certificate_id).name if i.certificate_id else None
        dname = db.get(Domain, i.domain_id).domain if i.domain_id else None
        return MailHistoryDetailOut(
            id=i.id, source="queue", certificate_id=i.certificate_id, certificate_name=cname,
            domain_id=i.domain_id, domain_name=dname, recipient=i.to_addresses,
            subject=i.subject, days_left=i.days_left, channel="email", status=i.status,
            error=i.last_error, attempts=i.attempts, sent_at=i.sent_at or i.created_at,
            queued_at=i.created_at, delivered_at=i.sent_at,
            body_text=i.body_text, body_html=i.body_html, mail_type=mail_history.classify(i.subject),
            stakeholder=mail_history.stakeholder_of(i.subject, i.stakeholder),
            recipients=mail_history.recipients_of(i.to_addresses), retryable=mail_history._retryable(i))
    raise HTTPException(status_code=400, detail="Geçersiz source (notification|queue olmalı)")
