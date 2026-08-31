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

    @staticmethod
    def _job_path(job: str) -> str:
        """Kalifiye job adını ('Folder/Sub/job') Jenkins REST yoluna çevirir: job/Folder/job/Sub/job/job.
        Klasörsüz job'larda (çoğunluk) tek segment olduğundan davranış DEĞİŞMEZ."""
        segments = [s for s in job.split("/") if s]
        return "/".join(f"job/{s}" for s in segments)

    def _list_jobs_recursive(self, c: httpx.Client, folder: str, depth: int = 0) -> list[str]:
        """Bir klasörün (veya kökün) içindeki job'ları listeler; alt klasörlere (Folder eklentisi)
        OTOMATİK iner — kullanıcı yeni bir alt klasör açtığında ayar değiştirmesi gerekmez.
        depth, olası döngü/aşırı derinliğe karşı güvenlik sınırı (Jenkins klasör yapıları sığdır)."""
        if depth > 5:
            return []
        path = f"/{self._job_path(folder)}" if folder else ""
        r = c.get(f"{path}/api/json", params={"tree": "jobs[name,_class]"})
        r.raise_for_status()
        result: list[str] = []
        for j in r.json().get("jobs", []):
            name = j.get("name")
            if not name:
                continue
            full = f"{folder}/{name}" if folder else name
            if "folder" in (j.get("_class") or "").lower():
                result.extend(self._list_jobs_recursive(c, full, depth + 1))
            else:
                result.append(full)
        return result

    def list_jobs(self) -> list[str]:
        """Tetiklenebilir job adları — 'jobs_folder' ayarlanmışsa YALNIZ o klasörün altından
        (alt klasörler dahil, özyinelemeli), boşsa Jenkins kökünden taranır."""
        folder = (self.config.get("jobs_folder") or "").strip().strip("/")
        with self._client() as c:
            return self._list_jobs_recursive(c, folder)

    def recent_builds(self, job: str, limit: int = 8) -> list[dict]:
        """Son build'ler (numara/sonuç/çalışıyor/zaman/süre) — Dağıtım sayfası geçmişi için."""
        with self._client() as c:
            r = c.get(f"/{self._job_path(job)}/api/json",
                      params={"tree": f"builds[number,result,building,timestamp,duration]{{0,{limit}}}"})
            r.raise_for_status()
            return [{
                "number": b.get("number"),
                "result": b.get("result"),
                "building": b.get("building"),
                "timestamp": b.get("timestamp"),
                "duration": b.get("duration"),
            } for b in r.json().get("builds", [])]

    def _trigger(self, job: str, params: dict) -> tuple[bool, str, str | None]:
        """Ortak tetikleme: buildWithParameters + CSRF crumb → (ok, mesaj, ham kuyruk Location URL'i).
        trigger_job/trigger_job_tracked bunu sarar — istek gövdesi/hata mesajları TEK yerde."""
        if not job:
            return False, "Job adı boş", None
        if not self.is_available():
            return False, "Jenkins entegrasyonu etkin değil", None
        try:
            with self._client() as c:
                headers = self._crumb(c)
                r = c.post(f"/{self._job_path(job)}/buildWithParameters", data=params, headers=headers)
                if r.status_code in (200, 201):
                    queue = r.headers.get("Location", "") or None
                    tail = queue.rstrip("/").rsplit("/", 1)[-1] if queue else ""
                    return True, f"'{job}' tetiklendi" + (f" (kuyruk #{tail})" if tail else ""), queue
                if r.status_code == 404:
                    return False, f"Job bulunamadı: '{job}'", None
                if r.status_code in (401, 403):
                    return False, f"Yetki/CSRF hatası (HTTP {r.status_code}) — kullanıcı/token veya crumb?", None
                return False, f"Tetikleme başarısız (HTTP {r.status_code})", None
        except httpx.HTTPError as exc:
            return False, f"Jenkins bağlantı hatası: {exc}", None

    def trigger_job(self, job: str, params: dict) -> tuple[bool, str]:
        """Job'u buildWithParameters ile tetikler → (ok, kullanıcıya mesaj[+kuyruk konumu]).
        Genel/manuel tetikleme ucu (`/api/jenkins/trigger`) için — imza DEĞİŞMEDİ."""
        ok, message, _queue = self._trigger(job, params)
        return ok, message

    def trigger_job_tracked(self, job: str, params: dict) -> tuple[bool, str, str | None]:
        """trigger_job ile AYNI tetikleme, ama ham kuyruk Location URL'ini de döner —
        deployment_engine build numarasını çözüp poll edebilsin diye (bkz. resolve_queue_item)."""
        return self._trigger(job, params)

    def resolve_queue_item(self, queue_url: str) -> int | None:
        """Kuyruk konumunu (trigger_job_tracked'ın döndürdüğü Location URL'i) build numarasına
        çözer. Henüz kuyrukta ise None; kuyruktan İPTAL edildiyse -1; başladıysa build numarası."""
        try:
            with self._client() as c:
                r = c.get(f"{queue_url.rstrip('/')}/api/json")
                if r.status_code != 200:
                    return None
                data = r.json()
                if data.get("cancelled"):
                    return -1
                executable = data.get("executable")
                if executable and executable.get("number") is not None:
                    return int(executable["number"])
                return None
        except httpx.HTTPError:
            return None

    def job_parameters(self, job: str) -> list[dict]:
        """Job'un tanımlı parametreleri (ad/tip/varsayılan/açıklama/seçenekler) — akış editöründe
        'job seç → parametreler otomatik gelsin' adımı için. Job'da parametre tanımı yoksa [].

        DİKKAT: `ParametersDefinitionProperty` gerçek Jenkins'te (özellikle Pipeline/WorkflowJob)
        `property[]` altında döner — `actions[]` DEĞİL (bir mock sunucuyla doğrulanıp gerçek
        Jenkins'e karşı test edilince ortaya çıktı; `actions[]` her zaman BOŞ kalıyordu)."""
        with self._client() as c:
            r = c.get(f"/{self._job_path(job)}/api/json",
                      params={"tree": "property[parameterDefinitions[name,type,"
                                       "defaultParameterValue[value],description,choices]]"})
            r.raise_for_status()
            for prop in r.json().get("property", []) or []:
                defs = prop.get("parameterDefinitions")
                if defs:
                    return [{
                        "name": d.get("name"),
                        "type": d.get("type"),
                        "default": (d.get("defaultParameterValue") or {}).get("value"),
                        "description": d.get("description"),
                        "choices": d.get("choices"),
                    } for d in defs if d.get("name")]
            return []

    def console_url(self, job: str, number: int) -> str:
        """Bir build'in Jenkins konsol log sayfasının tam URL'i — UI'da yeni sekmede açmak için."""
        return f"{self._base()}/{self._job_path(job)}/{number}/console"

    def build_status(self, job: str, number: int) -> dict:
        """Tek bir build'in durumu (sonuç/çalışıyor mu) — poll_running_runs bunu kullanır."""
        with self._client() as c:
            r = c.get(f"/{self._job_path(job)}/{number}/api/json", params={"tree": "result,building"})
            r.raise_for_status()
            data = r.json()
            return {"result": data.get("result"), "building": bool(data.get("building"))}
