"""Jenkins entegrasyonu — JUMBO job'ları TETİKLER (genel: herhangi bir job + parametre).

NetScaler cert-deploy bunun bir kullanımıdır: 'netscaler_job' job'u CERTKEY (domain başına) +
VAULT_PATH ile tetiklenir. CUSTODY YOK — JUMBO yalnız tetikler; özel anahtar Vault→Jenkins→NITRO
yolunu izler, JUMBO'ya hiç girmez.

Ayarlar > Jenkins sekmesi alanları (base_url, username, api_token, ...) burada okunur.
  - health(): bağlantı + kimlik testi ("Bağlantıyı Test Et")
  - list_jobs(): tetiklenebilir job adları (genel arayüz için)
  - trigger_job(job, params): buildWithParameters ile tetikler (CSRF crumb otomatik)
"""

import httpx
from sqlalchemy.orm import Session

from app.services.settings_service import get_category


class JenkinsClient:
    name = "jenkins"

    def __init__(self, db: Session):
        self.config = get_category(db, "jenkins", mask_secrets=False)

    def _base(self) -> str:
        return (self.config.get("base_url") or "").rstrip("/")

    def _auth(self) -> tuple[str, str] | None:
        user = self.config.get("username") or ""
        token = self.config.get("api_token") or ""
        return (user, token) if user else None

    def _client(self) -> httpx.Client:
        # Egress-gated (proxy_url), tek Client içinde cookie (JSESSIONID) paylaşılır → crumb + POST
        # aynı oturumda doğrulanır. verify: https'te skip_cert_verify ile kapatılabilir (YALNIZ dev).
        return httpx.Client(
            base_url=self._base(),
            auth=self._auth(),
            proxy=(self.config.get("proxy_url") or None),
            timeout=float(self.config.get("timeout_seconds") or 15),
            verify=not bool(self.config.get("skip_cert_verify")),
            headers={"User-Agent": "JUMBO-CLM/jenkins"},
            follow_redirects=True,
        )

    def is_available(self) -> bool:
        return bool(self.config.get("enabled") and self.config.get("base_url"))

    def _crumb(self, client: httpx.Client) -> dict:
        """CSRF crumb (etkinse). API token ile gerekmez; parola ile gerekir. Aynı client → cookie paylaşımı."""
        try:
            r = client.get("/crumbIssuer/api/json")
            if r.status_code == 200:
                d = r.json()
                return {d["crumbRequestField"]: d["crumb"]}
        except httpx.HTTPError:
            pass
        return {}

    def health(self) -> tuple[bool, str]:
        if not self.is_available():
            return False, "Jenkins entegrasyonu etkin değil (adres veya 'enabled' eksik)"
        try:
            with self._client() as c:
                r = c.get("/api/json?tree=mode,nodeName")
                if r.status_code in (401, 403):
                    return False, f"Jenkins kimlik doğrulama başarısız (HTTP {r.status_code}) — kullanıcı/token?"
                if r.status_code != 200:
                    return False, f"Jenkins erişilemedi (HTTP {r.status_code})"
        except httpx.HTTPError as exc:
            return False, f"Jenkins bağlantı hatası: {exc}"
        return True, "Jenkins erişilebilir, kimlik doğrulandı"

    def list_jobs(self) -> list[str]:
        with self._client() as c:
            r = c.get("/api/json?tree=jobs[name]")
            r.raise_for_status()
            return [j["name"] for j in r.json().get("jobs", []) if j.get("name")]

    def recent_builds(self, job: str, limit: int = 8) -> list[dict]:
        """Son build'ler (numara/sonuç/çalışıyor/zaman/süre) — Dağıtım sayfası geçmişi için."""
        with self._client() as c:
            r = c.get(f"/job/{job}/api/json",
                      params={"tree": f"builds[number,result,building,timestamp,duration]{{0,{limit}}}"})
            r.raise_for_status()
            return [{
                "number": b.get("number"),
                "result": b.get("result"),
                "building": b.get("building"),
                "timestamp": b.get("timestamp"),
                "duration": b.get("duration"),
            } for b in r.json().get("builds", [])]

    def trigger_job(self, job: str, params: dict) -> tuple[bool, str]:
        """Job'u buildWithParameters ile tetikler → (ok, kullanıcıya mesaj[+kuyruk konumu])."""
        if not job:
            return False, "Job adı boş"
        if not self.is_available():
            return False, "Jenkins entegrasyonu etkin değil"
        try:
            with self._client() as c:
                headers = self._crumb(c)
                r = c.post(f"/job/{job}/buildWithParameters", data=params, headers=headers)
                if r.status_code in (200, 201):
                    queue = r.headers.get("Location", "")
                    tail = queue.rstrip("/").rsplit("/", 1)[-1] if queue else ""
                    return True, f"'{job}' tetiklendi" + (f" (kuyruk #{tail})" if tail else "")
                if r.status_code == 404:
                    return False, f"Job bulunamadı: '{job}'"
                if r.status_code in (401, 403):
                    return False, f"Yetki/CSRF hatası (HTTP {r.status_code}) — kullanıcı/token veya crumb?"
                return False, f"Tetikleme başarısız (HTTP {r.status_code})"
        except httpx.HTTPError as exc:
            return False, f"Jenkins bağlantı hatası: {exc}"
