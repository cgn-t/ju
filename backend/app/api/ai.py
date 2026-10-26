"""AI asistanı uçları: durum (simge görünsün mü), soru-cevap ve Ayarlar'daki bağlantı testi."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User
from app.db.session import get_db
from app.services import ai_assistant
from app.services.audit import log_standalone
from app.services.settings_service import get_category

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def ai_status(db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    """Simge yalnız AI açık ve ayarları tamamken görünür. Sır içermez."""
    cfg = get_category(db, "ai", mask_secrets=True)
    return {"enabled": ai_assistant.is_available(cfg),
            "name": cfg.get("assistant_name") or "Jumbo AI"}


@router.post("/chat")
def ai_chat(request: Request, body: dict = Body(...), db: Session = Depends(get_db),
            user: User = Depends(require_role("viewer"))):
    """body: {"messages": [{"role": "user"|"assistant", "content": str}, ...], "page": "/domains"}
    → {"answer", "tools_used", "tool_mode"}. AI yalnız OKUR; araçlar bu kullanıcının yetkisiyle çalışır."""
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages listesi gerekli")
    page = body.get("page") if isinstance(body.get("page"), str) else None
    question = next((str(m.get("content") or "") for m in reversed(messages)
                     if isinstance(m, dict) and m.get("role") == "user"), "")
    try:
        result = ai_assistant.ask(db, user, [m for m in messages if isinstance(m, dict)], page)
    except ai_assistant.AiError as exc:
        log_standalone(user.username, "ai_ask", "ai", None,
                       {"question": question[:500], "success": False, "error": str(exc)[:300]}, request)
        raise HTTPException(status_code=400, detail=str(exc))
    log_standalone(user.username, "ai_ask", "ai", None,
                   {"question": question[:500], "success": True,
                    "tools": sorted(set(result["tools_used"]))}, request)
    return result


@router.post("/test")
def ai_test(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    ok, message = ai_assistant.health(db)
    log_standalone(user.username, "test", "app_settings", "ai",
                   {"target": "ai", "success": ok, "message": message[:500]}, request)
    return {"success": ok, "message": message}
