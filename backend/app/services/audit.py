"""Denetim kaydı (AuditLog) yazımı ve okunur hale getirme yardımcıları.

DETAY SÖZLEŞMESİ (details = JSON metin, geriye uyumlu):
  • update  → {"changes": {"alan": {"old": x, "new": y}, ...}, ...ek bağlam}
  • delete  → {"snapshot": {...silinmeden önceki kimlik alanları}, ...}
  • diğer   → serbest bağlam alanları (eski kayıtlar da bu biçimdedir)
Sır alanları ASLA açık yazılmaz — `MASK` + "masked": true.

KATEGORİ: prod AuditLog şemasına kolon eklenmez; kategori `action` (+ `system` kullanıcısı)
üzerinden türetilir — tek kaynak ACTION_CATEGORY / category_of / category_filter.
"""

import functools
import json
import time
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from fastapi import Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db.models import AuditLog

MASK = "••••"
SYSTEM_USER = "system"

# Alan adında bunlardan biri geçiyorsa değer maskelenir (password, bind_password, api_token,
# client_secret, private_key ...). "keystore" gibi düz alanlar etkilenmesin diye "key" tek başına YOK.
_SECRET_HINTS = ("password", "secret", "token", "private_key", "api_key", "fernet")

# İşlem → kategori. Listede olmayan işlemler "changes" sayılır; `system` kullanıcısının
# yaptığı her şey (kategorisi security değilse) "system" kategorisine düşer.
ACTION_CATEGORY: dict[str, str] = {
    # Onay & Devir
    "propose": "approval", "approve": "approval", "propose_reject": "approval",
    "propose_cancel": "approval", "supersede_apply": "approval", "trusted_add_apply": "approval",
    # Güvenlik
    "login": "security", "login_failed": "security", "add_member": "security",
    "remove_member": "security",
    # Sistem
    "job_summary": "system", "test": "system", "live_check_run": "system",
    "notify_run": "system", "revocation_run": "system", "revocation_check": "system",
    "scan": "system", "duplicate_detected": "system", "notify": "system",
}
# Tabloya göre güvenlik sayılan değişiklikler (kullanıcı/rol/ayar)
_SECURITY_TABLES = ("users", "user_teams", "teams", "app_settings")
CATEGORIES = ("changes", "approval", "security", "system")


def is_secret(field: str) -> bool:
    f = field.lower()
    return any(h in f for h in _SECRET_HINTS)


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _same(a, b) -> bool:
    a, b = _jsonable(a), _jsonable(b)
    # "" ile None aynı kabul — formlar boş alanı "" gönderir, DB'de NULL'dır
    if a in ("", None) and b in ("", None):
        return True
    return a == b


def _entry(field: str, old, new, force_secret: bool = False) -> dict:
    if force_secret or is_secret(field):
        return {"old": MASK if old not in (None, "") else None,
                "new": MASK if new not in (None, "") else None, "masked": True}
    return {"old": _jsonable(old), "new": _jsonable(new)}


def diff_fields(obj, changes: dict) -> dict:
    """`setattr`'dan ÖNCE çağrılır: yalnız gerçekten değişen alanlar için
    {"alan": {"old": eski, "new": yeni}} döner. Sırlar maskelenir."""
    out = {}
    for field, new in changes.items():
        old = getattr(obj, field, None)
        if not _same(old, new):
            out[field] = _entry(field, old, new)
    return out


def diff_dicts(old: dict, new: dict, secret_keys: set[str] | frozenset = frozenset()) -> dict:
    """İki sözlük arasındaki fark (ör. ayar kategorisi). Yalnız `new`'deki anahtarlar;
    `secret_keys`'tekiler (adı sır gibi görünmese de) maskelenir."""
    return {k: _entry(k, old.get(k), v, k in secret_keys)
            for k, v in new.items() if not _same(old.get(k), v)}


def label_ids(db: Session, diff: dict) -> dict:
    """Kimlik alanlarına okunur ad ekler ("sy_team_id": 3 → "old_label": "SY-Ağ"). Yerinde günceller."""
    from app.db.models import Application, Certificate, Domain, Team
    models = {"team_id": (Team, "name"), "app_id": (Application, "name"),
              "domain_id": (Domain, "domain"), "cert_id": (Certificate, "name"),
              "parent_id": (Certificate, "name")}
    for field, entry in diff.items():
        spec = next((v for k, v in models.items() if field == k or field.endswith("_" + k)), None)
        if spec is None or entry.get("masked"):
            continue
        model, attr = spec
        for side in ("old", "new"):
            val = entry.get(side)
            if isinstance(val, int):
                row = db.get(model, val)
                if row is not None:
                    entry[f"{side}_label"] = getattr(row, attr)
    return diff


def snapshot(obj, fields: tuple[str, ...]) -> dict:
    """Silinmeden önce kaydın kimlik alanları — silinen kaydın ne olduğu sonradan anlaşılsın."""
    snap = {}
    for f in fields:
        v = getattr(obj, f, None)
        if v not in (None, ""):
            snap[f] = MASK if is_secret(f) else _jsonable(v)
    return snap


def category_of(action: str, table_name: str | None, username: str | None) -> str:
    cat = ACTION_CATEGORY.get(action)
    if cat is None:
        cat = "security" if table_name in _SECURITY_TABLES else "changes"
    if username == SYSTEM_USER and cat != "security":
        return "system"
    return cat


def category_filter(category: str):
    """category_of'un SQL karşılığı (aynı kurallar)."""
    mapped = {cat: [a for a, c in ACTION_CATEGORY.items() if c == cat] for cat in CATEGORIES}
    all_mapped = list(ACTION_CATEGORY)
    not_system = or_(AuditLog.username.is_(None), AuditLog.username != SYSTEM_USER)
    if category == "security":
        return or_(AuditLog.action.in_(mapped["security"]),
                   and_(AuditLog.action.notin_(all_mapped), AuditLog.table_name.in_(_SECURITY_TABLES)))
    if category == "approval":
        return and_(AuditLog.action.in_(mapped["approval"]), not_system)
    if category == "system":
        return or_(AuditLog.action.in_(mapped["system"]),
                   and_(AuditLog.username == SYSTEM_USER,
                        AuditLog.action.notin_(mapped["security"]),
                        or_(AuditLog.action.in_(all_mapped),
                            AuditLog.table_name.notin_(_SECURITY_TABLES))))
    # changes
    return and_(AuditLog.action.notin_(all_mapped), AuditLog.table_name.notin_(_SECURITY_TABLES),
                not_system)


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def log_action(db: Session, username: str, action: str, table_name: str,
               record_id: str | int | None = None, details: dict | list | str | None = None,
               request: Request | None = None) -> None:
    """Mutasyon işlemlerini audit_log tablosuna yazar. Çağıran commit eder."""
    # dict VE list JSON'a serileştirilir — DB sürücüleri (pymssql/sqlite) ham list/dict bind edemez.
    if isinstance(details, (dict, list)):
        details = json.dumps(details, ensure_ascii=False, default=str)
    db.add(AuditLog(
        username=username,
        action=action,
        table_name=table_name,
        # Prod AuditLog.RecordID NOT NULL → kayıt-bağımsız işlemlerde (ör. vault_sync) "" yaz.
        record_id=str(record_id) if record_id is not None else "",
        details=details,
        ip_address=client_ip(request),
    ))


def log_standalone(username: str, action: str, table_name: str,
                   record_id: str | int | None = None, details: dict | None = None,
                   request: Request | None = None) -> None:
    """Kendi oturumunda yazıp commit eder — çağıranın transaction'ı geri alınsa da (ör. başarısız
    giriş 401, arka plan işi) kayıt kalır. Audit yazımı asla asıl işi bozmaz."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        log_action(db, username, action, table_name, record_id, details, request)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def audited_job(job: str):
    """Zamanlanmış iş sarmalayıcısı: iş BAŞINA tek özet satırı (`job_summary`, kullanıcı `system`).
    İş bir dict döndürür ({"status": "ok"|"error"|"skipped", ...sayılar}); "skipped" (özellik
    kapalı) ve None kaydedilmez — günlük gürültü olmasın. Süre otomatik eklenir."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                log_standalone(SYSTEM_USER, "job_summary", "jobs", job,
                               {"job": job, "status": "error", "error": str(exc)[:300],
                                "duration_s": round(time.monotonic() - started, 1)})
                raise
            if isinstance(result, dict) and result.get("status") != "skipped":
                log_standalone(SYSTEM_USER, "job_summary", "jobs", job,
                               {"job": job, **result,
                                "duration_s": round(time.monotonic() - started, 1)})
            return result
        return wrapper
    return deco


def scan_run_summary(run) -> dict:
    """ScanRun (keşif/CT) → iş özeti."""
    return {"status": "error" if run.status == "error" else "ok", "run_id": run.id,
            "targets": run.targets_scanned, "reachable": run.hosts_reachable,
            "new_findings": run.new_findings, **({"error": run.error[:300]} if run.error else {})}
