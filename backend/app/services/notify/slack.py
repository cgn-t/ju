"""Slack kanalı — Incoming Webhook URL'ine JSON POST eder."""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class SlackChannel(NotificationChannel):
    name = "slack"

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        url = cfg.get("webhook_url")
        if not url:
            return False
        with http_client(cfg) as client:
            client.post(url, json={"text": f"*{event.title}*\n{event.text}"}).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        if not cfg.get("webhook_url"):
            return False, "Slack Webhook URL tanımlı değil"
        try:
            with http_client(cfg) as client:
                client.post(cfg["webhook_url"],
                            json={"text": "✅ JUMBO test bildirimi (Slack)"}).raise_for_status()
            return True, "Slack webhook'una test mesajı gönderildi"
        except Exception as exc:
            return False, f"Gönderilemedi: {str(exc)[:200]}"
