"""Bildirim kanalları (e-posta DIŞI): Slack / Teams / Webhook / ... .

E-posta paydaş-bazlı kalır (notifier._dispatch_cert_mails); bu kanallar bir olayı yapılandırılmış bir
hedefe (webhook/oda) YAYINLAR. Yeni kanal eklemek = ilgili modülü yazıp CHANNELS listesine eklemek +
settings_service.DEFAULTS'a bir kategori koymak (admin GET/PUT + /notify-test otomatik gelir).

Faz 1: slack, teams, webhook. Faz 2: servicenow, zoom. Faz 3: jabber/XMPP. + jira (talep/issue).
"""

from app.services.notify.base import NotificationChannel, NotifyEvent
from app.services.notify.jabber import JabberChannel
from app.services.notify.jira import JiraChannel
from app.services.notify.servicenow import ServiceNowChannel
from app.services.notify.slack import SlackChannel
from app.services.notify.teams import TeamsChannel
from app.services.notify.webhook import WebhookChannel
from app.services.notify.zoom import ZoomChannel

CHANNELS: list[NotificationChannel] = [
    SlackChannel(), TeamsChannel(), WebhookChannel(),
    ServiceNowChannel(), JiraChannel(), ZoomChannel(), JabberChannel(),
]
_BY_NAME = {c.name: c for c in CHANNELS}


def get_channel(name: str) -> NotificationChannel | None:
    """Ayar kategorisi adına göre kanalı döner (yoksa None)."""
    return _BY_NAME.get(name)


__all__ = ["CHANNELS", "NotificationChannel", "NotifyEvent", "get_channel"]
