"""Mail Gönderim Geçmişi sorgu katmanı (liste + sayaçlar + tekrar deneme).

İki kaynak birleşik gösterilir:
  • notifications: karar/kuyruğa alınma anında yazılan kayıt. mail_queue_id doluysa GERÇEK durum
    ve zaman ilişkili mail_queue satırından okunur; NULL ise doğrudan gönderim başarılıdır ('sent').
  • mail_queue: bir notifications satırına BAĞLI OLMAYAN pending/failed satırlar (bağlılar zaten
    yukarıda gerçek durumuyla görünür — mükerrer olmasın). Bağlılık NOT EXISTS ile SQL'de bulunur.

Durum / tür / zaman filtreleri SQL'de, LİMİTTEN ÖNCE uygulanır (eskiden durum filtresi limit
sonrası Python'da uygulandığından son 200 bildirimin dışındaki başarısız mailler görünmüyordu).

MAIL TÜRÜ şemada yok — konu satırı sabit şablonlardan üretildiği için (notifier.make_subject vb.)
konudan türetilir; aynı kurallar SQL'de CASE ifadesi olarak da kullanılır (filtre + sayaç).
"""

from datetime import datetime

from sqlalchemy import case, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.textmatch import ci_like
from app.db.models import Certificate, Domain, MailQueue, Notification

# Tür → konu kalıpları (şablondaki yazımla birebir; eski ASCII şablonlar da dahil)
TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("revoked", ("İPTAL EDİLMİŞ",)),
    ("expired", ("SÜRESİ GEÇMİŞ",)),
    ("expiry", ("Sertifika süresi doluyor", "Sertifika suresi doluyor",
                "Domain bitiş tarihi yaklaşıyor", "Domain bitis tarihi yaklasiyor")),
    ("deactivated", ("pasife alındı",)),
    ("proposal", ("devir önerisi",)),
]
MAIL_TYPES = [t for t, _ in TYPE_RULES] + ["other"]
STATUSES = ("sent", "pending", "failed")


def classify(subject: str | None) -> str:
    s = subject or ""
    for mail_type, needles in TYPE_RULES:
        if any(n in s for n in needles):
            return mail_type
    return "other"


def type_case(col):
    return case(*[(or_(*[col.like(f"%{n}%") for n in needles]), literal(t))
                  for t, needles in TYPE_RULES], else_=literal("other"))


def stakeholder_of(subject: str | None, queue_stakeholder: str | None = None) -> str | None:
    """Paydaş etiketi: kuyrukta ayrı kolon; bildirimde konunun ' → ' sonrasında."""
    if queue_stakeholder:
        return queue_stakeholder
    if subject and " → " in subject:
        return subject.rsplit(" → ", 1)[1].strip() or None
    return None


def recipients_of(raw: str | None) -> list[str]:
    return [r.strip() for r in (raw or "").split(",") if r.strip()]


class _Filters:
    def __init__(self, *, channel=None, status=None, mail_type=None, q=None, recipient=None,
                 subject=None, record=None, lo: datetime | None = None, hi: datetime | None = None):
        self.channel, self.status, self.mail_type = channel, status, mail_type
        self.q, self.recipient, self.subject, self.record = q, recipient, subject, record
        self.lo, self.hi = lo, hi


def _notif_query(db: Session, f: _Filters, *, ignore_status=False, ignore_type=False):
    eff_status = func.coalesce(MailQueue.status, literal("sent"))
    ts = func.coalesce(MailQueue.sent_at, MailQueue.created_at, Notification.sent_at)
    mtype = type_case(Notification.subject)
    q = (db.query(Notification, Certificate.name, Domain.domain, MailQueue)
         .outerjoin(Certificate, Certificate.id == Notification.certificate_id)
         .outerjoin(Domain, Domain.id == Notification.domain_id)
         .outerjoin(MailQueue, MailQueue.id == Notification.mail_queue_id))
    if f.channel:
        # Kanal kolonu sonradan eklendi: eski satırlarda NULL — onlar e-postadır
        cond = Notification.channel == f.channel
        if f.channel == "email":
            cond = or_(cond, Notification.channel.is_(None))
        q = q.filter(cond)
    if f.status and not ignore_status:
        q = q.filter(eff_status == f.status)
    if f.mail_type and not ignore_type:
        q = q.filter(mtype == f.mail_type)
    if f.q:
        like = f"%{f.q}%"
        q = q.filter(or_(ci_like(Notification.recipient, like), ci_like(Notification.subject, like),
                         ci_like(Certificate.name, like), ci_like(Domain.domain, like)))
    if f.recipient:
        q = q.filter(ci_like(Notification.recipient, f"%{f.recipient}%"))
    if f.subject:
        q = q.filter(ci_like(Notification.subject, f"%{f.subject}%"))
    if f.record:
        like = f"%{f.record}%"
        q = q.filter(or_(ci_like(Certificate.name, like), ci_like(Domain.domain, like)))
    if f.lo is not None:
        q = q.filter(ts >= f.lo)
    if f.hi is not None:
        q = q.filter(ts <= f.hi)
    return q, eff_status, mtype, ts


def _queue_query(db: Session, f: _Filters, *, ignore_status=False, ignore_type=False):
    """Bağımsız (bir bildirime bağlı OLMAYAN) teslim edilmemiş kuyruk satırları."""
    if f.channel not in (None, "", "email"):
        return None
    if not ignore_status and f.status and f.status not in ("pending", "failed"):
        return None
    ts = func.coalesce(MailQueue.sent_at, MailQueue.created_at)
    mtype = type_case(MailQueue.subject)
    linked = exists(select(Notification.id).where(Notification.mail_queue_id == MailQueue.id))
    q = (db.query(MailQueue, Certificate.name, Domain.domain)
         .outerjoin(Certificate, Certificate.id == MailQueue.certificate_id)
         .outerjoin(Domain, Domain.id == MailQueue.domain_id)
         .filter(MailQueue.status.in_(("pending", "failed")), ~linked))
    if f.status and not ignore_status:
        q = q.filter(MailQueue.status == f.status)
    if f.mail_type and not ignore_type:
        q = q.filter(mtype == f.mail_type)
    if f.q:
        like = f"%{f.q}%"
        q = q.filter(or_(ci_like(MailQueue.to_addresses, like), ci_like(MailQueue.subject, like),
                         ci_like(Certificate.name, like), ci_like(Domain.domain, like)))
    if f.recipient:
        q = q.filter(ci_like(MailQueue.to_addresses, f"%{f.recipient}%"))
    if f.subject:
        q = q.filter(ci_like(MailQueue.subject, f"%{f.subject}%"))
    if f.record:
        like = f"%{f.record}%"
        q = q.filter(or_(ci_like(Certificate.name, like), ci_like(Domain.domain, like)))
    if f.lo is not None:
        q = q.filter(ts >= f.lo)
    if f.hi is not None:
        q = q.filter(ts <= f.hi)
    return q, mtype, ts


def list_history(db: Session, f: _Filters, limit: int) -> tuple[list[dict], bool]:
    """Filtreye uyan EN YENİ `limit` kayıt + sınır aşıldı mı (capped)."""
    out: list[dict] = []
    q, _, _, ts = _notif_query(db, f)
    for n, cname, dname, mq in q.order_by(ts.desc()).limit(limit + 1).all():
        if mq is not None:
            status, queued_at, delivered_at = mq.status, mq.created_at, mq.sent_at
            error, attempts = mq.last_error, mq.attempts
        else:
            status, queued_at, delivered_at, error, attempts = "sent", n.sent_at, n.sent_at, None, None
        out.append(dict(
            id=n.id, source="notification", certificate_id=n.certificate_id, certificate_name=cname,
            domain_id=n.domain_id, domain_name=dname, recipient=n.recipient, subject=n.subject,
            days_left=n.days_left, channel=n.channel or "email", status=status, error=error, attempts=attempts,
            sent_at=delivered_at or queued_at, queued_at=queued_at, delivered_at=delivered_at,
            mail_type=classify(n.subject), stakeholder=stakeholder_of(n.subject),
            recipients=recipients_of(n.recipient), retryable=_retryable(mq)))
    qq = _queue_query(db, f)
    if qq is not None:
        q2, _, ts2 = qq
        for i, cname, dname in q2.order_by(ts2.desc()).limit(limit + 1).all():
            out.append(dict(
                id=i.id, source="queue", certificate_id=i.certificate_id, certificate_name=cname,
                domain_id=i.domain_id, domain_name=dname, recipient=i.to_addresses, subject=i.subject,
                days_left=i.days_left, channel="email", status=i.status, error=i.last_error,
                attempts=i.attempts, sent_at=i.sent_at or i.created_at, queued_at=i.created_at,
                delivered_at=i.sent_at, mail_type=classify(i.subject),
                stakeholder=stakeholder_of(i.subject, i.stakeholder),
                recipients=recipients_of(i.to_addresses), retryable=_retryable(i)))
    out.sort(key=lambda r: r["sent_at"] or datetime.min, reverse=True)
    return out[:limit], len(out) > limit


def facets(db: Session, f: _Filters) -> dict:
    """Sekme ve filtre menüsü sayaçları. Durum sayaçları durum filtresi HARİÇ, tür sayaçları tür
    filtresi HARİÇ diğer tüm filtrelere göre hesaplanır (sekmeler arası geçişte sayılar anlamlı kalsın)."""
    status_counts = {s: 0 for s in STATUSES}
    q, eff_status, _, _ = _notif_query(db, f, ignore_status=True)
    for st, c in q.with_entities(eff_status, func.count(Notification.id)).group_by(eff_status).all():
        status_counts[st] = status_counts.get(st, 0) + c
    qq = _queue_query(db, f, ignore_status=True)
    if qq is not None:
        q2 = qq[0]
        for st, c in q2.with_entities(MailQueue.status, func.count(MailQueue.id)).group_by(MailQueue.status).all():
            status_counts[st] = status_counts.get(st, 0) + c

    type_counts = {t: 0 for t in MAIL_TYPES}
    q, _, mtype, _ = _notif_query(db, f, ignore_type=True)
    for t, c in q.with_entities(mtype, func.count(Notification.id)).group_by(mtype).all():
        type_counts[t] = type_counts.get(t, 0) + c
    qq = _queue_query(db, f, ignore_type=True)
    if qq is not None:
        q2, mtype2, _ = qq
        for t, c in q2.with_entities(mtype2, func.count(MailQueue.id)).group_by(mtype2).all():
            type_counts[t] = type_counts.get(t, 0) + c
    return {"statuses": status_counts, "types": type_counts, "total": sum(status_counts.values())}


def _retryable(mq: MailQueue | None) -> bool:
    """Başarısız ve alıcısı belli bir kuyruk satırı yeniden kuyruğa alınabilir. Hiç denenemeyen
    (alıcı bilinmeyen) hata kayıtları tekrar gönderilemez."""
    return bool(mq is not None and mq.status == "failed" and "@" in (mq.to_addresses or ""))


def queue_row_for(db: Session, source: str, item_id: int) -> MailQueue | None:
    if source == "queue":
        return db.get(MailQueue, item_id)
    if source == "notification":
        n = db.get(Notification, item_id)
        return db.get(MailQueue, n.mail_queue_id) if n is not None and n.mail_queue_id else None
    return None


def requeue(mq: MailQueue) -> None:
    """Başarısız maili kuyruğa geri al: periyodik kuyruk boşaltma işi yeniden dener."""
    mq.status = "pending"
    mq.attempts = 0
    mq.last_error = None

