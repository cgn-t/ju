"""Bildirim uçları — süre uyarılarını tetikleme (UI butonu VEYA dış otomasyon).

Günlük 08:00 cron'una ek olarak tarama iki yoldan ANINDA tetiklenebilir:
  • UI (Settings → SMTP → "Şimdi Gönder"): admin JWT ile.
  • DIŞ ARAÇ (cron, zamanlayıcı, izleme sistemi): SMTP ayarlarındaki
    `trigger_api_key` değerini `X-API-Key` başlığında göndererek — login gerekmez:
        curl -X POST https://<host>/api/notifications/expiry-run \
             -H "X-API-Key: <anahtar>"
    Anahtar BOŞSA dış tetikleme kapalıdır (yalnız admin JWT çalışır). Dış tetikte tarama arka
    planda yürür (202) ve tekrar-önleme geçerlidir; durum: GET .../expiry-run/status.

Tetiklenince: bitişine `expiry_warning_days`'ten az gün kalan her sertifika için
paydaşlara AYRI AYRI mail gönderilir — sahibi (oluşturan kullanıcı), bağlı domainlerin
SY ekipleri, client olarak bağlı uygulamaların sahibi SY ekipleri
(bkz. notifier._expiry_stakeholders)."""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.schemas import MailHistoryDetailOut, MailHistoryListOut, MailHistoryOut
from app.api.trigger_auth import EXTERNAL_ACTOR, external_cooldown, trigger_actor
from app.core.security import require_role
from app.db.models import Certificate, Domain, MailQueue, Notification, User
from app.db.session import get_db
from app.core.timeutil import time_window
from app.services import job_lock, mail_history, notifier
from app.services.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_trigger_actor = trigger_actor("smtp", "bildirim")


# Uç → ortak DB kilidi adı (bkz. job_lock). Zamanlanmış iş, ekrandaki buton ve dış tetik aynı
# adı kullanır: aynı tarama aynı anda iki yerde (iki pod / iki cluster) çalışmaz.
_JOBS = {
    "expiry-run": (notifier.JOB_EXPIRY_MAIL, notifier.send_expiry_notifications),
    "expired-run": (notifier.JOB_EXPIRED_MAIL, notifier.send_expired_notifications),
    "proposal-run": (notifier.JOB_PROPOSAL_MAIL, notifier.send_pending_proposal_notifications),
}
_BUSY = "Bu mail taraması şu anda çalışıyor (bu ya da başka bir sunucuda) — bitince tekrar deneyin"


def _external_scan(scan_fn, endpoint: str, request_meta: dict) -> dict:
    """Dış tetik gövdesi (arka plan thread'i, kendi session'ı). Tekrar-önleme AÇIK (force=False):
    araç zaman aşımına düşüp tekrar denerse aynı kişilere ikinci mail gitmez."""
    from app.db.session import SessionLocal
    from app.services.audit import log_standalone

    db = SessionLocal()
    try:
        result = scan_fn(db, force=False)
    finally:
        db.close()
    summary = {"checked": result["checked"], "sent": result["sent"], "skipped": result["skipped"]}
    log_standalone(EXTERNAL_ACTOR, "notify", "notifications", None,
                   {"endpoint": endpoint, **summary, **request_meta})
    return {"status": "ok", "enabled": result["enabled"], **summary, "message": result["message"]}


def _run_scan(endpoint: str, request: Request, actor: str, db: Session):
    """Ortak tetikleme akışı.
      • Ekrandaki buton (admin JWT): tarama hemen çalışır, sonuç döner (force=True: "Şimdi
        Gönder" tekrar-önlemeyi atlar, her zaman gönderir).
      • Dış araç (X-API-Key): uç-bazlı cooldown → tarama ARKA PLANDA başlar, 202 hemen döner
        (çok mailde ön kapı zaman aşımı olmasın); tekrar-önleme geçerlidir. Durum:
        GET /api/notifications/<uç>/status. Dış anahtar düşük yetkilidir: yalnız sayısal özet.
    Aynı tarama başka yerde sürüyorsa 409."""
    job_name, scan_fn = _JOBS[endpoint]
    if actor == EXTERNAL_ACTOR:
        external_cooldown(endpoint)  # mail-spam freni
        meta = {"ip": request.client.host if request.client else None}
        started = job_lock.start_in_background(
            job_name, lambda: _external_scan(scan_fn, endpoint, meta), triggered_by=actor)
        if not started:
            raise HTTPException(status_code=409, detail=_BUSY)
        return JSONResponse(status_code=202, content={
            "status": "started", "triggered_by": actor,
            "status_url": f"/api/notifications/{endpoint}/status"})

    lock = job_lock.JobLock(job_name)
    if not lock.acquire():
        raise HTTPException(status_code=409, detail=_BUSY)
    holder: dict = {}

    def body() -> dict:
        holder["result"] = scan_fn(db, force=True)
        r = holder["result"]
        return {"status": "ok", "checked": r["checked"], "sent": r["sent"], "skipped": r["skipped"]}
    job_lock.run_job(job_name, body, triggered_by=actor, lock=lock)
    result = holder["result"]
    log_action(db, actor, "notify", "notifications", None,
               {"endpoint": endpoint, "checked": result["checked"],
                "sent": result["sent"], "skipped": result["skipped"]}, request)
    db.commit()
    return result


def _status(endpoint: str, actor: str) -> dict:
    return job_lock.job_status(_JOBS[endpoint][0])


@router.post("/expiry-run")
def run_expiry_notifications(request: Request, actor: str = Depends(_trigger_actor),
                             db: Session = Depends(get_db)):
    """SÜRESİ YAKLAŞAN sertifikalar (bitişe expiry_warning_days'ten az kalan) için
    paydaşlara ayrı ayrı bilgilendirme maili gönderir."""
    return _run_scan("expiry-run", request, actor, db)


@router.post("/expired-run")
def run_expired_notifications(request: Request, actor: str = Depends(_trigger_actor),
                              db: Session = Depends(get_db)):
    """SÜRESİ GEÇMİŞ ama JUMBO'da hâlâ AKTİF (güncellenmemiş) sertifikalar için
    paydaşlara 'JUMBO'da güncelleyin' hatırlatması gönderir."""
    return _run_scan("expired-run", request, actor, db)


@router.post("/proposal-run")
def run_proposal_notifications(request: Request, actor: str = Depends(_trigger_actor),
                               db: Session = Depends(get_db)):
    """Onay kuyruğunda BEKLEYEN değişiklik talepleri için ilgili SY ekiplerine (ekip başına tek mail)
    hatırlatma gönderir. Dış otomasyon (X-API-Key) veya admin JWT tetikler; ayarlardaki
    auto_proposal_reminder_enabled bayrağından ETKİLENMEZ — çağrıldığında her zaman çalışır."""
    return _run_scan("proposal-run", request, actor, db)


@router.get("/expiry-run/status")
def expiry_run_status(actor: str = Depends(_trigger_actor)):
    """Son süre uyarısı taramasının durumu (hangi sunucuda çalışırsa çalışsın aynı)."""
    return _status("expiry-run", actor)


@router.get("/expired-run/status")
def expired_run_status(actor: str = Depends(_trigger_actor)):
    """Son süresi geçmiş hatırlatması taramasının durumu."""
    return _status("expired-run", actor)


@router.get("/proposal-run/status")
def proposal_run_status(actor: str = Depends(_trigger_actor)):
    """Son değişiklik talebi hatırlatmasının durumu."""
    return _status("proposal-run", actor)


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
        mail_type: str | None = None,        # expiry | expired | revoked | deactivated | proposal | other
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
