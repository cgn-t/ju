from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User
from app.db.session import get_db
from app.services import ldap_auth
from app.services.audit import log_action
from app.services.settings_service import DEFAULTS, get_category, save_category

router = APIRouter(prefix="/api/settings", tags=["settings"])

VALID_CATEGORIES = set(DEFAULTS.keys())


@router.get("/{category}")
def read_settings(category: str, db: Session = Depends(get_db),
                  _: User = Depends(require_role("admin"))):
    if category not in VALID_CATEGORIES:
        return {}
    return get_category(db, category, mask_secrets=True)


@router.put("/{category}")
def write_settings(request: Request, category: str, values: dict = Body(...),
                   db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if category not in VALID_CATEGORIES:
        return {}
    allowed = set(DEFAULTS[category].keys())
    filtered = {k: v for k, v in values.items() if k in allowed}
    save_category(db, category, filtered)
    log_action(db, user.username, "update", "app_settings", category,
               {"fields": sorted(filtered.keys())}, request)
    db.commit()
    return get_category(db, category, mask_secrets=True)


@router.post("/ldap/test")
def ldap_test(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    ok, message = ldap_auth.test_connection(db)
    return {"success": ok, "message": message}


@router.post("/vault/test")
def vault_test(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    from app.services.providers.vault import VaultProvider
    ok, message = VaultProvider(db).health()
    return {"success": ok, "message": message}


@router.post("/jenkins/test")
def jenkins_test(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    from app.services.jenkins_client import JenkinsClient
    ok, message = JenkinsClient(db).health()
    return {"success": ok, "message": message}


@router.post("/{category}/notify-test")
def channel_test(category: str, db: Session = Depends(get_db),
                 _: User = Depends(require_role("admin"))):
    """Bildirim kanalına (slack/teams/webhook/…) kısa bir test mesajı gönderir → {success, message}.
    Egress-gated + graceful: erişilemezse success=False + neden döner (çökmez)."""
    from app.services.notify import get_channel
    channel = get_channel(category)
    if channel is None:
        raise HTTPException(status_code=404, detail="Bilinmeyen bildirim kanalı")
    ok, message = channel.test(get_category(db, category, mask_secrets=False))
    return {"success": ok, "message": message}
