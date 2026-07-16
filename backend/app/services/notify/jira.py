"""Jira kanalı — REST API ile bir issue (talep/görev) açar.

`POST {base_url}/rest/api/2/issue`. v2 uç noktası hem Jira Cloud hem Server/Data Center'da düz-metin
`description` kabul eder (v3 ADF gerektirir → v2 seçildi). Kimlik iki modda:
  - basic  → (kullanıcı, token) : Cloud'da e-posta+API token, DC'de kullanıcı+şifre
  - bearer → Authorization: Bearer <PAT> : Jira Data Center kişisel erişim token'ı (telekom yaygını)
Test issue AÇMADAN `/myself` ile kimliği doğrular. Cloud dış SaaS → egress-gated (proxy) + graceful.
"""

from app.services.notify.base import NotificationChannel, NotifyEvent, http_client


class JiraChannel(NotificationChannel):
    name = "jira"

    @staticmethod
    def _auth_headers(cfg: dict) -> tuple:
        """(auth, headers) döner. bearer modda auth=None + Authorization başlığı; aksi halde Basic."""
        if (cfg.get("auth_mode") or "basic").lower() == "bearer":
            return None, {"Authorization": f"Bearer {cfg.get('api_token') or ''}"}
        return (cfg.get("username") or "", cfg.get("api_token") or ""), {}

    @staticmethod
    def _issue(cfg: dict, event: NotifyEvent) -> dict:
        return {"fields": {
            "project": {"key": cfg.get("project_key")},
            "summary": event.title[:250],
            "description": event.text,
            "issuetype": {"name": cfg.get("issue_type") or "Task"},
        }}

    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base or not cfg.get("project_key"):
            return False
        auth, headers = self._auth_headers(cfg)
        with http_client(cfg) as client:
            client.post(f"{base}/rest/api/2/issue", json=self._issue(cfg, event),
                        auth=auth, headers=headers).raise_for_status()
        return True

    def test(self, cfg: dict) -> tuple[bool, str]:
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base or not cfg.get("project_key"):
            return False, "Jira base URL / proje anahtarı tanımlı değil"
        try:
            # Issue AÇMADAN doğrula: /myself kimliği + erişimi test eder.
            auth, headers = self._auth_headers(cfg)
            with http_client(cfg) as client:
                client.get(f"{base}/rest/api/2/myself", auth=auth, headers=headers).raise_for_status()
            return True, "Jira bağlantısı doğrulandı (issue açılmadı)"
        except Exception as exc:
            return False, f"Bağlanılamadı: {str(exc)[:200]}"
