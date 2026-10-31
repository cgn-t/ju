"""Regresyon Testi uçları (yalnız admin). Ayrıntı: app/services/regression.py.

Otomatik kontroller yalnız okur; koşular ve işaretler Audit Log'a yazılır (yeni tablo yok)."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User
from app.db.session import get_db
from app.services import regression

router = APIRouter(prefix="/api/regression", tags=["regression"])


def _run_or_404(db: Session, run_id: str) -> dict:
    run = regression.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Test bulunamadı")
    return run


@router.get("/catalog")
def catalog(_: User = Depends(require_role("admin"))):
    return {**regression.catalog(), "total": regression.scenario_count(), "version": regression.app_version()}


@router.get("/checks")
def checks(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Kontrol listesi ve en son otomatik kontrol sonucu (hangi teste bağlı olursa olsun)."""
    return {"checks": regression.check_list(), "last": regression.last_auto(db)}


@router.post("/checks/run")
def run_checks(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
               user: User = Depends(require_role("admin"))):
    """Otomatik kontrolleri çalıştırır. Hiçbir kayıt değiştirilmez, mail gönderilmez; yalnız
    sonuç Audit Log'a yazılır. body.run_id verilirse sonuç o teste bağlanır."""
    run_id = (body or {}).get("run_id") or None
    if run_id:
        _run_or_404(db, run_id)
    results = regression.run_checks(db, request.headers.get("authorization"))
    regression.save_auto(db, user, run_id, results, request)
    return regression.last_auto(db, run_id) if run_id else regression.last_auto(db)


@router.get("/runs")
def runs(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return regression.list_runs(db)


@router.post("/runs")
def start_run(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
              user: User = Depends(require_role("admin"))):
    return regression.start_run(db, user, (body or {}).get("title"), request)


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return _run_or_404(db, run_id)


@router.post("/runs/{run_id}/marks")
def mark(run_id: str, request: Request, body: dict = Body(...), db: Session = Depends(get_db),
         user: User = Depends(require_role("admin"))):
    """body: {"scenario": "MAIL-A1", "result": "pass"|"fail"|"skip"|null, "note": str}.
    result boş ise işaret kaldırılır."""
    run = _run_or_404(db, run_id)
    if run["finished_at"]:
        raise HTTPException(status_code=409, detail="Bu test bitirildi; yeni bir test başlatın")
    scenario = str(body.get("scenario") or "")
    if scenario not in regression.scenario_index():
        raise HTTPException(status_code=400, detail="Bilinmeyen senaryo")
    result = body.get("result") or None
    if result is not None and result not in regression.RESULTS:
        raise HTTPException(status_code=400, detail="Sonuç Geçti, Kaldı ya da Atlandı olmalı")
    return regression.mark(db, user, run_id, scenario, result, body.get("note"), request)


@router.post("/runs/{run_id}/finish")
def finish(run_id: str, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_role("admin"))):
    run = _run_or_404(db, run_id)
    if run["finished_at"]:
        return run
    return regression.finish_run(db, user, run_id, request)


# ---------------------------------------------------------------- Test Hazırlığı (v3.9.28)
# Yalnız admin ve yalnız REGRESSION_TOOLS=1 iken (test/preprod). Kapalıyken uçlar 404 döner,
# ekran sekmeyi göstermez.
from fastapi.responses import Response  # noqa: E402

from app.services import regression_lab  # noqa: E402
from app.services.audit import log_action  # noqa: E402


def _lab_on():
    if not regression_lab.enabled():
        raise HTTPException(status_code=404, detail="Test Hazırlığı bu ortamda kapalı (REGRESSION_TOOLS)")


@router.get("/lab")
def lab_status(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    if not regression_lab.enabled():
        return {"enabled": False}
    return regression_lab.status(db)


def _lab_log(db: Session, user: User, step: str, request: Request):
    log_action(db, user.username, "regression_lab", "regression", None, {"step": step}, request)
    db.commit()


@router.post("/lab/certs")
def lab_generate(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _lab_on()
    regression_lab.generate_and_store(db, user.username)
    _lab_log(db, user, "Test sertifikaları üretildi", request)
    return regression_lab.status(db)


@router.get("/lab/files/{name}")
def lab_file(name: str, db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    _lab_on()
    data = regression_lab.file_bytes(db, name)
    if data is None:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/lab/zip")
def lab_zip(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    _lab_on()
    data = regression_lab.zip_bytes(db)
    if data is None:
        raise HTTPException(status_code=404, detail="Önce test sertifikalarını üretin")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="jumbo-test-dosyalari.zip"'})


@router.post("/lab/sites/start")
def lab_sites_start(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _lab_on()
    try:
        regression_lab.start_sites(db, user.username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _lab_log(db, user, f"Test siteleri açıldı ({regression_lab.SITE_HOURS} saat)", request)
    return regression_lab.status(db)


@router.post("/lab/sites/stop")
def lab_sites_stop(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _lab_on()
    regression_lab.stop_sites(db)
    _lab_log(db, user, "Test siteleri kapatıldı", request)
    return regression_lab.status(db)


@router.post("/lab/sites/renewed")
def lab_sites_renewed(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    _lab_on()
    on = bool((body or {}).get("renewed"))
    regression_lab.set_renewed(db, on)
    _lab_log(db, user, "9444 yenilenmiş sertifikayı sunuyor" if on else "9444 eski sertifikayı sunuyor", request)
    return regression_lab.status(db)


@router.post("/lab/data")
def lab_data(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
             user: User = Depends(require_role("admin"))):
    _lab_on()
    regression_lab.prepare_data(db, user.username, (body or {}).get("emails") or {})
    _lab_log(db, user, "Test ekipleri ve hesapları hazırlandı", request)
    return regression_lab.status(db)


@router.post("/lab/all")
def lab_all(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
            user: User = Depends(require_role("admin"))):
    """Hepsini Hazırla: sertifikalar + siteler + ekip/hesaplar."""
    _lab_on()
    regression_lab.generate_and_store(db, user.username)
    regression_lab.start_sites(db, user.username)
    regression_lab.prepare_data(db, user.username, (body or {}).get("emails") or {})
    _lab_log(db, user, "Test ortamı hazırlandı (sertifikalar, siteler, ekipler, hesaplar)", request)
    return regression_lab.status(db)


@router.get("/lab/cleanup")
def lab_cleanup_preview(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    _lab_on()
    return regression_lab.cleanup_preview(db)


@router.post("/lab/cleanup")
def lab_cleanup(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    _lab_on()
    return regression_lab.cleanup(db, user, request)
