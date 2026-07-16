"""ServiceNow kanalı — Table API ile bir incident (olay kaydı) açar.

`POST {instance_url}/api/now/table/incident` (Basic Auth). Süre uyarısı → urgency Orta, süresi geçmiş →
urgency Yüksek. Test, incident AÇMADAN bağlantı+kimliği doğrular (incident tablosuna küçük bir GET).
ServiceNow bulut örneği kapalı ağda erişilemeyebilir → egress-gated (opsiyonel proxy) + graceful.
"""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class ServiceNowChannel(NotificationChannel):
    name = "servicenow"

    @staticmethod
    def _incident(event: NotifyEvent) -> dict:
        # ServiceNow urgency/impact: 1=Yüksek, 2=Orta, 3=Düşük. Süresi geçmiş = Yüksek.
        urgency = "1" if event.kind == "expired" else "2"
        return {
            "short_description": event.title[:160],
            "description": event.text,
            "urgency": urgency,
            "impact": urgency,
        }

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        base = (cfg.get("instance_url") or "").rstrip("/")
        user = cfg.get("username")
        if not base or not user:
            return False
        with http_client(cfg) as client:
            client.post(f"{base}/api/now/table/incident", json=self._incident(event),
                        auth=(user, cfg.get("password") or "")).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        base = (cfg.get("instance_url") or "").rstrip("/")
        user = cfg.get("username")
        if not base or not user:
            return False, "ServiceNow instance URL / kullanıcı tanımlı değil"
        try:
            # Incident AÇMADAN doğrula: incident tablosundan tek kayıt oku (kimlik + erişim testi).
            with http_client(cfg) as client:
                client.get(f"{base}/api/now/table/incident", params={"sysparm_limit": 1},
                           auth=(user, cfg.get("password") or "")).raise_for_status()
            return True, "ServiceNow bağlantısı doğrulandı (incident açılmadı)"
        except Exception as exc:
            return False, f"Bağlanılamadı: {str(exc)[:200]}"
