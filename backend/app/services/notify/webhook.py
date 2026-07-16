"""Generic Webhook kanalı — yapılandırılabilir bir URL'e tam olay JSON'ını POST eder.

ServiceNow-dışı her entegrasyon (PagerDuty, Opsgenie, kendi API'niz…) buradan beslenebilir.
`auth_header` "Başlık: değer" biçiminde opsiyonel kimlik başlığıdır (ör. "Authorization: Bearer xxx").
"""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class WebhookChannel(NotificationChannel):
    name = "webhook"

    @staticmethod
    def _headers(cfg: dict) -> dict:
        auth = (cfg.get("auth_header") or "").strip()
        if auth and ":" in auth:
            key, val = auth.split(":", 1)
            return {key.strip(): val.strip()}
        return {}

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        url = cfg.get("url")
        if not url:
            return False
        payload = {
            "kind": event.kind,
            "certificate": event.cert_name,
            "days_left": event.days_left,
            "title": event.title,
            "text": event.text,
            **event.fields,
        }
        with http_client(cfg) as client:
            client.post(url, json=payload, headers=self._headers(cfg)).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        if not cfg.get("url"):
            return False, "Webhook URL tanımlı değil"
        try:
            with http_client(cfg) as client:
                r = client.post(cfg["url"],
                                json={"kind": "test", "title": "JUMBO test",
                                      "text": "✅ JUMBO test bildirimi (Webhook)"},
                                headers=self._headers(cfg))
                r.raise_for_status()
            return True, f"Webhook'a test isteği gönderildi (HTTP {r.status_code})"
        except Exception as exc:
            return False, f"Gönderilemedi: {str(exc)[:200]}"
