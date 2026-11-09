"""Veritabanı Değişiklikleri sayfası uçları (v3.9.38). Yalnız admin ve yalnız DB_CONSOLE=1
olan ortamda; kapalıyken 404 döner (sayfanın varlığı bile görünmez). Ayrıntı:
app/services/db_console.py."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User
from app.db.session import get_db
from app.services import db_console

router = APIRouter(prefix="/api/db-console", tags=["db-console"])


def _require_enabled() -> None:
    if not db_console.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("")
def status(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    _require_enabled()
    return {**db_console.info(db), "history": db_console.history(db)}


@router.post("/analyze")
def analyze(body: dict = Body(...), _: User = Depends(require_role("admin"))):
    _require_enabled()
    sql = str((body or {}).get("sql") or "")
    return {"warnings": db_console.warnings_for(sql), "confirm_word": db_console.CONFIRM_WORD}


@router.post("/run")
def run(request: Request, body: dict = Body(...), db: Session = Depends(get_db),
        user: User = Depends(require_role("admin"))):
    """body: {"sql": str, "title": str, "dry_run": bool, "confirm": str}."""
    _require_enabled()
    body = body or {}
    sql = str(body.get("sql") or "")
    title = str(body.get("title") or "").strip()[:200]
    dry_run = bool(body.get("dry_run"))
    if not sql.strip():
        raise HTTPException(status_code=400, detail="SQL boş")
    if len(sql) > db_console.MAX_SQL_LEN:
        raise HTTPException(status_code=400, detail="SQL çok uzun (en fazla 100.000 karakter)")
    if not title:
        raise HTTPException(status_code=400, detail="Değişiklik adı zorunlu")
    warnings = db_console.warnings_for(sql)
    if warnings and not dry_run and str(body.get("confirm") or "").strip() != db_console.CONFIRM_WORD:
        raise HTTPException(status_code=400,
                            detail=f"Bu SQL riskli ifade içeriyor; onay için {db_console.CONFIRM_WORD} yazın")
    try:
        return db_console.run(db, user, sql, title, dry_run, request)
    except db_console.ConsoleBusy:
        raise HTTPException(status_code=409, detail="Başka bir admin şu anda SQL çalıştırıyor; biraz sonra tekrar deneyin")
