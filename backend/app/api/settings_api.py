import logging

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
    # Saat/aralık ayarları yeniden başlatma beklemeden devreye girsin (bkz. notifier._CATEGORY_JOBS)
    from app.services import notifier
    try:
        notifier.reschedule_from_settings(category)
    except Exception:
        logging.getLogger(__name__).exception("Zamanlama güncellenemedi: %s", category)
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


@router.post("/smtp/test")
def smtp_test(request: Request, body: dict = Body(default={}), db: Session = Depends(get_db),
              user: User = Depends(require_role("admin"))):
    """KAYDEDİLMİŞ SMTP ayarlarıyla YALNIZ verilen adrese (boşsa admin'in kendi e-postasına) kısa
    bir test maili gönderir → {success, message}. Kuyruk ve yedek adres KULLANILMAZ: amaç ayarı
    doğrulamak, bu yüzden sunucunun gerçek hatası (bağlantı/STARTTLS/SSL/şifre/alıcı reddi)
    olduğu gibi döner. Gerçek paydaşlara hiçbir uyarı gitmez."""
    from app.core.emails import split_emails
    from app.services import notifier
    cfg = get_category(db, "smtp", mask_secrets=False)
    to = split_emails((body or {}).get("to") or user.email)
    if not to:
        raise HTTPException(status_code=400, detail="Test maili için bir alıcı adresi girin")
    if not cfg.get("host"):
        raise HTTPException(status_code=400, detail="SMTP sunucusu tanımlı değil — önce ayarları kaydedin")
    subject, text, html_body = notifier.render_smtp_test_mail(cfg, user.username)
    try:
        refused = notifier._send_mail(cfg, to, subject, text, html_body)
        if refused:
            ok, message = False, f"Sunucu şu alıcıları reddetti: {notifier._refused_note(refused)}"
        else:
            ok, message = True, f"Test maili gönderildi: {', '.join(to)}"
    except Exception as exc:
        ok, message = False, f"Gönderilemedi: {type(exc).__name__}: {exc}"
    _log_test(request, user, "smtp", ok, message)
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
