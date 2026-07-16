"""Zoom Team Chat kanalı — 'Incoming Webhook' uygulamasının uç noktasına JSON POST eder.

Zoom Marketplace'teki 'Incoming Webhook Chatbot'tan bir Endpoint URL + Verification Token alınır. İstek
`Authorization: <token>` başlığıyla, gövdesi `{"content": {...}}` biçiminde gönderilir. Zoom bulut SaaS'tır
→ kapalı ağda opsiyonel forward proxy gerekebilir (graceful).
"""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class ZoomChannel(NotificationChannel):
    name = "zoom"

    @staticmethod
    def _headers(cfg: dict) -> dict:
        token = (cfg.get("token") or "").strip()
        return {"Authorization": token} if token else {}

    @staticmethod
    def _payload(title: str, text: str) -> dict:
        return {"content": {"head": {"text": title},
                            "body": [{"type": "message", "text": text}]}}

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        url = cfg.get("webhook_url")
        if not url:
            return False
        with http_client(cfg) as client:
            client.post(url, json=self._payload(event.title, event.text),
                        headers=self._headers(cfg)).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        if not cfg.get("webhook_url"):
            return False, "Zoom Webhook URL tanımlı değil"
        try:
            with http_client(cfg) as client:
                client.post(cfg["webhook_url"],
                            json=self._payload("JUMBO test", "✅ JUMBO test bildirimi (Zoom)"),
                            headers=self._headers(cfg)).raise_for_status()
            return True, "Zoom webhook'una test mesajı gönderildi"
        except Exception as exc:
            return False, f"Gönderilemedi: {str(exc)[:200]}"
