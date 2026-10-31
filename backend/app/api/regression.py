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
