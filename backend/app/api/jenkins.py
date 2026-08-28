"""Jenkins tetikleme uçları. Görme (jobs/builds) varsayılan admin+allviewer'a açık; Ayarlar >
Erişim'den (access.deployments_all_roles) tüm rollere açılabilir. Tetikleme (trigger) HER
DURUMDA admin-only — canlı sertifika dağıtımını başlatan hassas aksiyon.

NetScaler cert-deploy bu genel tetiğin bir kullanımıdır — frontend 'Dağıt' butonu bu uca
{job: <netscaler_job>, params: {CERTKEY, VAULT_PATH, ...}} gönderir. Custody yok.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_page_access, require_role
from app.db.models import User
from app.db.session import get_db
from app.services.audit import log_action
from app.services.jenkins_client import JenkinsClient

router = APIRouter(prefix="/api/jenkins", tags=["jenkins"])


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db),
             _: User = Depends(require_page_access("deployments"))):
    """Tetiklenebilir Jenkins job adları (genel 'Job Tetikle' arayüzü için)."""
    client = JenkinsClient(db)
    if not client.is_available():
        return {"jobs": []}
    try:
        return {"jobs": client.list_jobs()}
    except Exception as exc:  # noqa: BLE001 — graceful: UI'da boş liste + hata mesajı
        raise HTTPException(status_code=502, detail=f"Jenkins iş listesi alınamadı: {exc}")


@router.get("/job/{job}/builds")
def job_builds(job: str, db: Session = Depends(get_db),
               _: User = Depends(require_page_access("deployments"))):
    """Bir job'un son build'leri (Dağıtım sayfası canlı geçmişi). Erişilemezse boş liste + 502."""
    client = JenkinsClient(db)
    if not client.is_available():
        return {"builds": []}
    try:
        return {"builds": client.recent_builds(job)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Jenkins build geçmişi alınamadı: {exc}")


@router.post("/trigger")
def trigger(request: Request, payload: dict = Body(...),
            db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Genel tetik: {job: str, params: {ad: değer}}. Admin. Audit'e yazılır (parametre adları)."""
    job = (payload.get("job") or "").strip()
    params = payload.get("params") or {}
    if not job:
        raise HTTPException(status_code=400, detail="'job' gerekli")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="'params' bir nesne olmalı")
    # Jenkins buildWithParameters string bekler
    str_params = {str(k): str(v) for k, v in params.items()}
    ok, message = JenkinsClient(db).trigger_job(job, str_params)
    log_action(db, user.username, "trigger", "jenkins_job", job,
               {"params": sorted(str_params.keys()), "ok": ok}, request)
    db.commit()
    return {"success": ok, "message": message}
