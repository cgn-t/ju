from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.models import User
from app.db.session import get_db
from app.services import ldap_auth
from app.services.audit import diff_dicts, log_action, log_standalone
from app.services.settings_service import DEFAULTS, SENSITIVE_KEYS, get_category, save_category

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
    secret_keys = {k for k in filtered if f"{category}.{k}" in SENSITIVE_KEYS}
    before = get_category(db, category, mask_secrets=False)
    # Maskeli yer tutucu geri geldiyse (save_category de dokunmaz) değişiklik sayılmaz
    effective = {k: v for k, v in filtered.items() if not (k in secret_keys and v == "********")}
    save_category(db, category, filtered)
    log_action(db, user.username, "update", "app_settings", category,
               {"category": category, "changes": diff_dicts(before, effective, secret_keys)}, request)
    db.commit()
    return get_category(db, category, mask_secrets=True)


def _log_test(request: Request, user: User, target: str, ok: bool, message: str) -> None:
    """Bağlantı/kanal testleri ayrı oturumda kaydedilir (testin kendisi DB'ye yazmaz)."""
    log_standalone(user.username, "test", "app_settings", target,
                   {"target": target, "success": ok, "message": str(message)[:500]}, request)


@router.post("/ldap/test")
def ldap_test(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    ok, message = ldap_auth.test_connection(db)
    _log_test(request, user, "ldap", ok, message)
    return {"success": ok, "message": message}


@router.post("/vault/test")
def vault_test(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    from app.services.providers.vault import VaultProvider
    ok, message = VaultProvider(db).health()
    _log_test(request, user, "vault", ok, message)
    return {"success": ok, "message": message}


@router.post("/jenkins/test")
def jenkins_test(request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    from app.services.jenkins_client import JenkinsClient
    ok, message = JenkinsClient(db).health()
    _log_test(request, user, "jenkins", ok, message)
    return {"success": ok, "message": message}


@router.post("/{category}/notify-test")
def channel_test(request: Request, category: str, db: Session = Depends(get_db),
                 user: User = Depends(require_role("admin"))):
    """Bildirim kanalına (slack/teams/webhook/…) kısa bir test mesajı gönderir → {success, message}.
    Egress-gated + graceful: erişilemezse success=False + neden döner (çökmez)."""
    from app.services.notify import get_channel
    channel = get_channel(category)
    if channel is None:
        raise HTTPException(status_code=404, detail="Bilinmeyen bildirim kanalı")
    ok, message = channel.test(get_category(db, category, mask_secrets=False))
    _log_test(request, user, f"{category} bildirim kanalı", ok, message)
    return {"success": ok, "message": message}
