"""Kanal dağıtımı: bir sertifika olayını enabled kanallara YAYINLAR (e-postadan bağımsız).

Kanal-bazlı 7-gün tekrar-önleme (Notification.channel) — mail dedup'ıyla çakışmaz. Bir kanal patlarsa
loglanır, diğerleri sürer (graceful). Config her kanal için bir kez okunur (secret'lar çözülür).
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import Notification
from app.services.notify import CHANNELS
from app.services.notify.base import NotifyEvent
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)


def _build_event(cert, kind: str) -> NotifyEvent:
    days_left = (cert.valid_to - utcnow()).days if cert.valid_to else 0
    end = f"{cert.valid_to:%Y-%m-%d}" if cert.valid_to else "—"
    if kind == "expired":
        title = f"🔴 SÜRESİ GEÇMİŞ: {cert.name} ({-days_left} gün önce doldu)"
        text = (f"Sertifika JUMBO'da hâlâ AKTİF görünüyor. Seri: {cert.serial_number or '—'} · "
                f"Bitiş: {end} UTC. Lütfen JUMBO envanterini güncelleyin.")
    else:
        title = f"⚠️ Süre doluyor: {cert.name} ({days_left} gün kaldı)"
        text = (f"Seri: {cert.serial_number or '—'} · Bitiş: {end} UTC · Kalan: {days_left} gün. "
                f"Yenileme sürecini başlatmanız önerilir.")
    return NotifyEvent(
        kind=kind, cert_id=cert.id, cert_name=cert.name, days_left=days_left,
        title=title, text=text,
        fields={"serial_number": cert.serial_number,
                "valid_to": cert.valid_to.isoformat() if cert.valid_to else None},
    )


def _enabled_channels(db: Session):
    """[(channel, cfg)] — yalnız etkin kanallar; config bir kez okunur (secret'lar açık)."""
    out = []
    for ch in CHANNELS:
        cfg = get_category(db, ch.name, mask_secrets=False)
        if ch.is_enabled(cfg):
            out.append((ch, cfg))
    return out


def notify_certs(db: Session, certs: list, *, kind: str, force: bool = False) -> dict:
    """Her sertifikayı etkin kanallara gönderir. force=False → son 7 günde aynı (cert,kanal) için
    bildirim varsa atlar. Kanal hatası diğerlerini durdurmaz."""
    channels = _enabled_channels(db)
    names = [ch.name for ch, _ in channels]
    if not channels or not certs:
        return {"channels": names, "sent": 0, "skipped": 0}

    sent = skipped = 0
    for cert in certs:
        event = _build_event(cert, kind)
        for ch, cfg in channels:
            if not force:
                recent = (db.query(Notification)
                          .filter(Notification.certificate_id == cert.id,
                                  Notification.channel == ch.name,
                                  Notification.sent_at >= utcnow() - timedelta(days=7))
                          .first())
                if recent:
                    skipped += 1
                    continue
            try:
                if ch.send(cfg, event):
                    db.add(Notification(certificate_id=cert.id, channel=ch.name, recipient=ch.name,
                                        subject=event.title, days_left=event.days_left))
                    db.commit()
                    sent += 1
                else:
                    skipped += 1
            except Exception:
                db.rollback()
                logger.exception("Kanal bildirimi gönderilemedi: %s → %s", cert.name, ch.name)
                skipped += 1
    return {"channels": names, "sent": sent, "skipped": skipped}
