"""Microsoft Teams kanalı — Incoming Webhook'a MessageCard JSON POST eder."""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class TeamsChannel(NotificationChannel):
    name = "teams"

    @staticmethod
    def _card(title: str, text: str) -> dict:
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": title,
            "themeColor": "0076D7",
            "title": title,
            "text": text,
        }

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        url = cfg.get("webhook_url")
        if not url:
            return False
        with http_client(cfg) as client:
            client.post(url, json=self._card(event.title, event.text)).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        if not cfg.get("webhook_url"):
            return False, "Teams Webhook URL tanımlı değil"
        try:
            with http_client(cfg) as client:
                client.post(cfg["webhook_url"],
                            json=self._card("JUMBO test", "✅ JUMBO test bildirimi (Teams)")).raise_for_status()
            return True, "Teams webhook'una test mesajı gönderildi"
        except Exception as exc:
            return False, f"Gönderilemedi: {str(exc)[:200]}"
