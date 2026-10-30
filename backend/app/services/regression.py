"""Regresyon Testi (yalnız admin, v3.9.27): Jumbo'nun içinden sürüm öncesi kontrol.

Üç parça:
  1. Otomatik kontroller: veritabanı, bağlantılar (AD, SMTP, AI, wiki, Vault, Jenkins),
     zamanlanmış işler, veri tutarlılığı, rol yetkileri ve ana sayfaların verisi. Hepsi YALNIZ
     OKUR: mail gönderilmez, kayıt eklenmez/değiştirilmez (preprod verisi bozulmasın).
  2. Elle test listesi: paylaşılan regresyon listelerinden üretilen senaryolar
     (app/data/regresyon_senaryolari.json; listeler güncellenince proje klasöründeki
     admin-regresyon/katalog_uret.py ile yeniden üretilir). Test eden kişi her satırı Geçti / Kaldı / Atlandı
     diye işaretler, not ekler.
  3. AI yardımı: ai_assistant'taki regresyon araçları bu modüldeki koşu bilgisini okur.

Sonuçlar YENİ TABLO GEREKTİRMEDEN Audit Log'a yazılır (veritabanı değişikliği yok):
  regression_start  → koşu açıldı   (record_id = koşu no, details: başlık, sürüm)
  regression_mark   → senaryo işareti (details: senaryo, sonuç, not) — en son işaret geçerlidir
  regression_end    → koşu bitti    (details: sayılar)
  regression_auto   → otomatik kontrol sonucu (details: koşu no, sonuçlar)
"""

import json
import secrets
import smtplib
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.routing import APIRoute
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import ISTANBUL, utcnow
from app.db.models import AuditLog, Base, User
from app.db.session import engine
from app.services.audit import log_action
from app.services.settings_service import get_category

CATALOG_FILE = Path(__file__).resolve().parents[1] / "data" / "regresyon_senaryolari.json"
TABLE = "regression"
RESULTS = ("pass", "fail", "skip")
RESULT_LABELS = {"pass": "Geçti", "fail": "Kaldı", "skip": "Atlandı"}
MAX_NOTE = 1000
MAX_TITLE = 200
SLOW_MS = 3000           # bir sayfanın verisi bundan uzun sürerse sarı
CLOCK_SKEW_S = 120       # sunucu ile veritabanı saati arasındaki izin verilen fark


# ---------------------------------------------------------------- katalog
@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))


def scenario_index() -> dict[str, dict]:
    out = {}
    for sec in catalog()["sections"]:
        for sc in sec["scenarios"]:
            out[sc["id"]] = {**sc, "section": sec["title"]}
    return out


def scenario_count() -> int:
    return sum(len(s["scenarios"]) for s in catalog()["sections"])


def app_version() -> str:
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------- otomatik kontroller
# Her kontrol (durum, mesaj) döndürür. Durum: ok | warn | fail | skip
def _db(db: Session):
    started = time.monotonic()
    db.execute(text("SELECT 1")).scalar()
    ms = int((time.monotonic() - started) * 1000)
    if engine.dialect.name != "mssql":
        return "warn", f"Bağlantı var ({ms} ms), ama veritabanı {engine.dialect.name}: canlıdaki MSSQL değil"
    coll = db.execute(text("SELECT CONVERT(varchar(128), DATABASEPROPERTYEX(DB_NAME(), 'Collation'))")).scalar()
    if coll != "Turkish_CI_AS":
        return "warn", f"Bağlantı var ({ms} ms), sıralama {coll}: canlıda Turkish_CI_AS"
    return "ok", f"MSSQL bağlantısı var ({ms} ms), sıralama Turkish_CI_AS"


def _schema(db: Session):
    insp = inspect(engine)
    have = {t.lower(): t for t in insp.get_table_names()}
    missing_tables, missing_cols = [], []
    for table in Base.metadata.sorted_tables:
        real = have.get(table.name.lower())
        if real is None:
            missing_tables.append(table.name)
            continue
        cols = {c["name"].lower() for c in insp.get_columns(real)}
        missing_cols += [f"{table.name}.{c.name}" for c in table.columns if c.name.lower() not in cols]
    if missing_tables or missing_cols:
        parts = ([f"eksik tablo: {', '.join(missing_tables)}"] if missing_tables else []) + \
                ([f"eksik kolon: {', '.join(missing_cols[:10])}"] if missing_cols else [])
        return "fail", "; ".join(parts)
    return "ok", f"{len(Base.metadata.sorted_tables)} tablonun tüm kolonları yerinde"


def _clock(db: Session):
    if engine.dialect.name != "mssql":
        return "skip", "Yalnız MSSQL'de denetlenir"
    db_now = db.execute(text("SELECT GETUTCDATE()")).scalar()
    skew = abs((utcnow() - db_now).total_seconds())
    if skew > CLOCK_SKEW_S:
        return "warn", f"Sunucu saati veritabanından {int(skew)} sn farklı"
    return "ok", f"Fark {int(skew)} sn"


def _job_lock(db: Session):
    from app.services import job_lock
    if engine.dialect.name != "mssql":
        return "skip", "Yalnız MSSQL'de (çoklu pod) denetlenir"
    lock = job_lock.JobLock("regression-probe")
    try:
        got = lock.acquire()
    finally:
        lock.release()
    if job_lock._mssql_disabled:
        return "fail", "sp_getapplock kullanılamıyor: birden fazla pod varsa işler çakışabilir"
    return ("ok", "sp_getapplock çalışıyor") if got else ("warn", "Kilit şu an başka bir işte")


def _secrets(db: Session):
    s = get_settings()
    if s.jwt_secret == "change-me-in-production":
        return "fail", "JWT_SECRET varsayılan değerde"
    if not s.fernet_key:
        return "warn", "FERNET_KEY tanımlı değil: şifreler veritabanında şifrelenmeden saklanır"
    return "ok", "JWT_SECRET ve FERNET_KEY tanımlı"


def _admins(db: Session):
    n = db.query(User).filter(User.role == "admin", User.is_active == True).count()  # noqa: E712
    if n == 0:
        return "fail", "Aktif yönetici yok"
    return "ok", f"{n} aktif yönetici"


def _ldap(db: Session):
    from app.services import ldap_auth
    if not get_category(db, "ldap", mask_secrets=True).get("enabled"):
        return "skip", "AD girişi kapalı"
    ok, msg = ldap_auth.test_connection(db)
    return ("ok" if ok else "fail"), msg


def _smtp(db: Session):
    """Bağlanır, gerekiyorsa STARTTLS ve giriş yapar; MAİL GÖNDERMEZ."""
    cfg = get_category(db, "smtp", mask_secrets=False)
    if not cfg.get("enabled"):
        return "skip", "Mail gönderimi kapalı"
    if not cfg.get("host") or not cfg.get("from_address"):
        return "fail", "Sunucu ya da gönderen adresi boş"
    if cfg.get("use_ssl"):
        conn = smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port") or 465), timeout=15)
    else:
        conn = smtplib.SMTP(cfg["host"], int(cfg.get("port") or 25), timeout=15)
    with conn as smtp:
        if cfg.get("use_tls") and not cfg.get("use_ssl"):
            smtp.starttls()
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg.get("password") or "")
        smtp.noop()
    if not cfg.get("fallback_address"):
        return "warn", f"{cfg['host']} bağlantısı başarılı, ama yedek adres boş"
    return "ok", f"{cfg['host']} bağlantısı ve giriş başarılı (mail gönderilmedi)"


def _ai(db: Session):
    from app.services import ai_assistant
    if not ai_assistant.is_available(get_category(db, "ai", mask_secrets=True)):
        return "skip", "AI asistanı kapalı"
    ok, msg = ai_assistant.health(db)
    return ("ok" if ok else "fail"), msg


def _wiki(db: Session):
    from app.services import wiki
    cfg = get_category(db, "ai", mask_secrets=False)
    if not wiki.is_configured(cfg):
        return "skip", "Kullanım Kılavuzu wiki linki tanımlı değil"
    try:
        guide = wiki.pages(db, cfg)
    except wiki.WikiError as exc:
        return "fail", str(exc)
    return ("ok", f"{len(guide)} sayfa okundu") if guide else ("warn", "Wiki boş döndü")


def _vault(db: Session):
    if not get_category(db, "vault", mask_secrets=True).get("enabled"):
        return "skip", "Vault kapalı"
    from app.services.providers.vault import VaultProvider
    ok, msg = VaultProvider(db).health()
    return ("ok" if ok else "fail"), msg


def _jenkins(db: Session):
    if not get_category(db, "jenkins", mask_secrets=True).get("enabled"):
        return "skip", "Jenkins kapalı"
    from app.services.jenkins_client import JenkinsClient
    ok, msg = JenkinsClient(db).health()
    return ("ok" if ok else "fail"), msg


def _jobs(db: Session):
    from app.services.team_summary import system_health
    jobs = [j for j in system_health(db)["jobs"] if j["enabled"]]
    errors = [f"{j['label']}: {j['summary']}" for j in jobs if j["status"] == "error"]
    never = [j["label"] for j in jobs if not j["status"]]
    if errors:
        return "fail", "; ".join(errors)
    if never:
        return "warn", f"Açık ama henüz çalışmamış: {', '.join(never)}"
    return "ok", f"Açık {len(jobs)} işin son çalışması başarılı" if jobs else "Açık zamanlanmış iş yok"


def _scheduler(db: Session):
    from app.services.notifier import scheduler
    if not scheduler.running:
        return "warn", "Zamanlayıcı bu pod'da çalışmıyor"
    return "ok", f"Zamanlayıcı çalışıyor ({len(scheduler.get_jobs())} iş)"


def _mail_week(db: Session):
    from app.services.team_summary import system_health
    m = system_health(db)["mail_week"]
    if m["failed"] or m["refused"]:
        return "warn", (f"Son 7 günde {m['sent']} gönderildi, {m['failed']} başarısız, "
                        f"{m['refused']} kısmen reddedildi (Mail Gönderim Geçmişi'ne bakın)")
    return "ok", f"Son 7 günde {m['sent']} mail gönderildi, hata yok"


def _missing(db: Session):
    from app.services.team_summary import system_health
    m = system_health(db)["missing"]
    labels = {"domains_without_team": "ekipsiz domain", "certs_without_recipient": "mail alıcısı olmayan sertifika",
              "apps_without_team": "ekipsiz uygulama", "teams_without_email": "e-postasız ekip"}
    found = [f"{m[k]} {v}" for k, v in labels.items() if m.get(k)]
    return ("warn", ", ".join(found)) if found else ("ok", "Eksik bilgi yok")


def _chain(db: Session):
    from app.services import chain_repair
    issues = chain_repair.check(db)
    if issues:
        return "warn", f"{len(issues)} sertifikada tür ya da üst sertifika düzeltmesi öneriliyor (SSL Sertifikaları > Zincir kontrolü)"
    return "ok", "Zincir bağları ve sertifika türleri tutarlı"


# Rol yetkileri: kodda tanımlı uçlar incelenir (kayıt açılmaz). Bu işlemler YALNIZ admine açık olmalı.
ADMIN_ONLY = [
    ("GET", "/api/settings/{category}"), ("PUT", "/api/settings/{category}"),
    ("POST", "/api/settings/smtp/test"), ("POST", "/api/settings/ldap/test"),
    ("GET", "/api/users"), ("POST", "/api/users"), ("PUT", "/api/users/{user_id}"),
    ("DELETE", "/api/users/{user_id}"), ("POST", "/api/teams"), ("PUT", "/api/teams/{team_id}"),
    ("DELETE", "/api/teams/{team_id}"), ("POST", "/api/teams/{team_id}/members"),
    ("DELETE", "/api/teams/{team_id}/members/{user_id}"), ("GET", "/api/audit"),
    ("GET", "/api/audit/export"), ("GET", "/api/notifications/history"),
    ("DELETE", "/api/certificates/{cert_id}"), ("POST", "/api/certificates/chain-check/apply"),
    ("GET", "/api/system/health"), ("POST", "/api/ai/test"),
    ("GET", "/api/regression/checks"), ("POST", "/api/regression/checks/run"),
    ("POST", "/api/regression/runs"), ("POST", "/api/regression/runs/{run_id}/marks"),
]
# Girişsiz açık olabilecek uçlar
PUBLIC = {("POST", "/api/auth/login"), ("POST", "/api/auth/login-json"), ("GET", "/api/health")}


def _routes() -> list[APIRoute]:
    from app.api import (ai, applications, auth, certificates, dashboard, deployments, discovery, domains,
                         jenkins, notifications, policy, proposals, settings_api, summary, tags, users)
    from app.api import regression as regression_api
    mods = (auth, certificates, domains, dashboard, applications, settings_api, users, proposals,
            notifications, tags, discovery, policy, jenkins, deployments, summary, ai, regression_api)
    return [r for m in mods for r in m.router.routes if isinstance(r, APIRoute)]


def _guards(dep, out: set[str]) -> set[str]:
    """Bir ucun bağımlılık ağacından korumaları toplar: 'role:<en düşük rol>', 'login', 'api-key'."""
    for sub in dep.dependencies:
        call = sub.call
        name = getattr(call, "__name__", type(call).__name__)
        if name == "checker" and call.__closure__:
            out |= {f"role:{c.cell_contents}" for c in call.__closure__ if isinstance(c.cell_contents, str)}
        elif name in ("get_current_user", "OAuth2PasswordBearer", "require_team_or_admin"):
            out.add("login")
        elif name == "dependency":   # trigger_auth: kullanıcı oturumu ya da X-API-Key
            out.add("api-key")
        _guards(sub, out)
    return out


def _auth_all(db: Session):
    open_routes = []
    routes = _routes()
    for r in routes:
        for m in r.methods - {"HEAD", "OPTIONS"}:
            if (m, r.path) not in PUBLIC and not _guards(r.dependant, set()):
                open_routes.append(f"{m} {r.path}")
    if open_routes:
        return "fail", f"Girişsiz açık uç: {', '.join(open_routes[:8])}"
    return "ok", f"{len(routes)} ucun hepsi giriş istiyor (giriş sayfası hariç)"


def _admin_only(db: Session):
    by_key = {(m, r.path): r for r in _routes() for m in r.methods}
    wrong = []
    for key in ADMIN_ONLY:
        r = by_key.get(key)
        if r is None:
            wrong.append(f"{key[0]} {key[1]} bulunamadı")
        elif "role:admin" not in _guards(r.dependant, set()):
            wrong.append(f"{key[0]} {key[1]}")
    if wrong:
        return "fail", f"Yönetici dışındakilere açık: {', '.join(wrong)}"
    return "ok", f"Ayarlar, kullanıcılar, Audit Log gibi {len(ADMIN_ONLY)} işlemin hepsi yalnız yöneticiye açık"


# Ana sayfaların verisi: ekrandaki istekler bu yöneticinin oturumuyla, uygulamanın içinden yapılır.
PAGES = [
    ("Anasayfa", "/api/dashboard"), ("SSL Sertifikaları", "/api/certificates/page"),
    ("Domainler", "/api/domains/page"), ("Uygulamalar", "/api/applications/page"),
    ("Değişiklik Talepleri", "/api/proposals/page"), ("Sertifika Haritası", "/api/cert-map"),
    ("Uyum", "/api/policy/counts"), ("Keşif", "/api/discovery/findings/page"),
    ("Dağıtım", "/api/deployments/flows"), ("Genel Durum", "/api/summary/teams"),
    ("Sistem Sağlığı", "/api/system/health"), ("Kullanıcılar", "/api/users"), ("Ekipler", "/api/teams"),
    ("Audit Log", "/api/audit?limit=20"), ("Mail Gönderim Geçmişi", "/api/notifications/history?limit=20"),
    ("Etiketler", "/api/tags"), ("AI durumu", "/api/ai/status"),
]


def _page_checks(authorization: str | None) -> list[dict]:
    from fastapi.testclient import TestClient

    from app.main import app
    out = []
    if not authorization:
        return [{"id": "pages", "group": "Sayfalar", "title": "Ana sayfalar", "status": "skip",
                 "message": "Oturum bilgisi yok", "ms": 0}]
    client = TestClient(app, raise_server_exceptions=False)   # lifespan çalışmaz; yalnız istek
    for i, (label, path) in enumerate(PAGES):
        started = time.monotonic()
        try:
            r = client.get(path, headers={"Authorization": authorization})
            ms = int((time.monotonic() - started) * 1000)
            if r.status_code != 200:
                status, msg = "fail", f"HTTP {r.status_code}: {r.text[:200]}"
            elif ms > SLOW_MS:
                status, msg = "warn", f"Açıldı ama yavaş ({ms} ms)"
            else:
                status, msg = "ok", f"Açıldı ({ms} ms)"
        except Exception as exc:
            ms = int((time.monotonic() - started) * 1000)
            status, msg = "fail", f"{type(exc).__name__}: {exc}"
        out.append({"id": f"page-{i + 1}", "group": "Sayfalar", "title": label,
                    "status": status, "message": msg, "ms": ms})
    return out


CHECKS = [
    ("db", "Altyapı", "Veritabanı bağlantısı", _db),
    ("schema", "Altyapı", "Veritabanı yapısı", _schema),
    ("clock", "Altyapı", "Sunucu ve veritabanı saati", _clock),
    ("joblock", "Altyapı", "Pod'lar arası iş kilidi", _job_lock),
    ("secrets", "Altyapı", "Güvenlik anahtarları", _secrets),
    ("ldap", "Bağlantılar", "AD / LDAP", _ldap),
    ("smtp", "Bağlantılar", "Mail sunucusu (mail gönderilmez)", _smtp),
    ("ai", "Bağlantılar", "AI servisi", _ai),
    ("wiki", "Bağlantılar", "Kullanım Kılavuzu (wiki)", _wiki),
    ("vault", "Bağlantılar", "Vault", _vault),
    ("jenkins", "Bağlantılar", "Jenkins", _jenkins),
    ("jobs", "Zamanlanmış işler ve mail", "Zamanlanmış işlerin son çalışması", _jobs),
    ("scheduler", "Zamanlanmış işler ve mail", "Zamanlayıcı", _scheduler),
    ("mail", "Zamanlanmış işler ve mail", "Son 7 günün mailleri", _mail_week),
    ("missing", "Veri tutarlılığı", "Eksik bilgiler", _missing),
    ("chain", "Veri tutarlılığı", "Sertifika zinciri", _chain),
    ("admins", "Yetkiler", "Yönetici hesabı", _admins),
    ("auth", "Yetkiler", "Giriş zorunluluğu", _auth_all),
    ("admin-only", "Yetkiler", "Yalnız yöneticinin yapabildikleri", _admin_only),
]


def check_list() -> list[dict]:
    return [{"id": i, "group": g, "title": t} for i, g, t, _ in CHECKS] + \
           [{"id": f"page-{n + 1}", "group": "Sayfalar", "title": label} for n, (label, _) in enumerate(PAGES)]


def run_checks(db: Session, authorization: str | None) -> list[dict]:
    out = []
    for cid, group, title, fn in CHECKS:
        started = time.monotonic()
        try:
            status, msg = fn(db)
        except Exception as exc:
            db.rollback()
            status, msg = "fail", f"{type(exc).__name__}: {str(exc)[:300]}"
        out.append({"id": cid, "group": group, "title": title, "status": status, "message": msg,
                    "ms": int((time.monotonic() - started) * 1000)})
    return out + _page_checks(authorization)


def counts_of(results: list[dict], key: str = "status") -> dict:
    out: dict[str, int] = {}
    for r in results:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


# ---------------------------------------------------------------- koşular (Audit Log'da)
def _details(row: AuditLog) -> dict:
    try:
        d = json.loads(row.details or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _ts(v: datetime | None) -> str | None:
    return v.isoformat() + "Z" if v else None


def new_run_id() -> str:
    return "R" + datetime.now(ISTANBUL).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def start_run(db: Session, user: User, title: str | None, request: Request | None = None) -> dict:
    run_id = new_run_id()
    version = app_version()
    title = (title or "").strip()[:MAX_TITLE] or f"v{version} regresyon testi"
    log_action(db, user.username, "regression_start", TABLE, run_id,
               {"title": title, "version": version, "scenarios": scenario_count()}, request)
    db.commit()
    return get_run(db, run_id)


def _start_row(db: Session, run_id: str) -> AuditLog | None:
    return (db.query(AuditLog).filter(AuditLog.action == "regression_start", AuditLog.table_name == TABLE,
                                      AuditLog.record_id == run_id).first())


def _marks(db: Session, run_ids: list[str]) -> dict[str, dict[str, dict]]:
    """koşu → senaryo → en son işaret (boş sonuç = işaret kaldırıldı)."""
    out: dict[str, dict[str, dict]] = {r: {} for r in run_ids}
    if not run_ids:
        return out
    rows = (db.query(AuditLog).filter(AuditLog.action == "regression_mark", AuditLog.table_name == TABLE,
                                      AuditLog.record_id.in_(run_ids))
            .order_by(AuditLog.created_at, AuditLog.id).all())
    for row in rows:
        d = _details(row)
        sid = d.get("scenario")
        if not sid:
            continue
        if d.get("result") in RESULTS:
            out[row.record_id][sid] = {"result": d["result"], "note": d.get("note") or "",
                                       "by": row.username, "at": _ts(row.created_at)}
        else:
            out[row.record_id].pop(sid, None)
    return out


def _summary(marks: dict[str, dict], total: int) -> dict:
    c = counts_of(list(marks.values()), "result")
    return {"pass": c.get("pass", 0), "fail": c.get("fail", 0), "skip": c.get("skip", 0),
            "pending": max(0, total - len(marks)), "total": total}


def _run_out(start: AuditLog, marks: dict[str, dict], end: AuditLog | None) -> dict:
    d = _details(start)
    total = int(d.get("scenarios") or scenario_count())
    return {"id": start.record_id, "title": d.get("title") or start.record_id, "version": d.get("version") or "",
            "started_by": start.username, "started_at": _ts(start.created_at),
            "finished_at": _ts(end.created_at) if end else None,
            "finished_by": end.username if end else None,
            "counts": _summary(marks, total)}


def _ends(db: Session, run_ids: list[str]) -> dict[str, AuditLog]:
    if not run_ids:
        return {}
    return {r.record_id: r for r in db.query(AuditLog).filter(
        AuditLog.action == "regression_end", AuditLog.table_name == TABLE, AuditLog.record_id.in_(run_ids)).all()}


def list_runs(db: Session, limit: int = 30) -> list[dict]:
    starts = (db.query(AuditLog).filter(AuditLog.action == "regression_start", AuditLog.table_name == TABLE)
              .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all())
    ids = [s.record_id for s in starts]
    marks, ends = _marks(db, ids), _ends(db, ids)
    return [_run_out(s, marks[s.record_id], ends.get(s.record_id)) for s in starts]


def last_auto(db: Session, run_id: str | None = None) -> dict | None:
    q = db.query(AuditLog).filter(AuditLog.action == "regression_auto", AuditLog.table_name == TABLE)
    if run_id:
        q = q.filter(AuditLog.record_id == run_id)
    row = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).first()
    if row is None:
        return None
    d = _details(row)
    return {"at": _ts(row.created_at), "by": row.username, "run_id": row.record_id or None,
            "version": d.get("version") or "", "results": d.get("results") or []}


def get_run(db: Session, run_id: str) -> dict | None:
    start = _start_row(db, run_id)
    if start is None:
        return None
    marks = _marks(db, [run_id])[run_id]
    run = _run_out(start, marks, _ends(db, [run_id]).get(run_id))
    run["marks"] = marks
    run["auto"] = last_auto(db, run_id)
    return run


def mark(db: Session, user: User, run_id: str, scenario: str, result: str | None, note: str | None,
         request: Request | None = None) -> dict:
    log_action(db, user.username, "regression_mark", TABLE, run_id,
               {"scenario": scenario, "result": result or "", "note": (note or "").strip()[:MAX_NOTE]}, request)
    db.commit()
    return _marks(db, [run_id])[run_id].get(scenario) or {}


def finish_run(db: Session, user: User, run_id: str, request: Request | None = None) -> dict:
    run = get_run(db, run_id)
    log_action(db, user.username, "regression_end", TABLE, run_id, {"counts": run["counts"]}, request)
    db.commit()
    return get_run(db, run_id)


def save_auto(db: Session, user: User, run_id: str | None, results: list[dict],
              request: Request | None = None) -> None:
    log_action(db, user.username, "regression_auto", TABLE, run_id or "",
               {"version": app_version(), "counts": counts_of(results),
                "results": [{k: r[k] for k in ("id", "group", "title", "status", "message")} for r in results]},
               request)
    db.commit()


# ---------------------------------------------------------------- AI için özet
def ai_run_report(db: Session, run_id: str | None = None) -> dict:
    """AI aracı: bir koşunun (verilmezse en sonuncunun) sonucu ve bir önceki koşuyla farkı."""
    runs = list_runs(db, limit=50)
    if not runs:
        return {"hata": "Henüz regresyon testi başlatılmamış"}
    run = next((r for r in runs if r["id"] == run_id), None) if run_id else runs[0]
    if run is None:
        return {"hata": f"Koşu bulunamadı: {run_id}", "kosular": [r["id"] for r in runs[:10]]}
    idx = {r["id"]: i for i, r in enumerate(runs)}[run["id"]]
    prev = runs[idx + 1] if idx + 1 < len(runs) else None
    ids = [run["id"]] + ([prev["id"]] if prev else [])
    marks = _marks(db, ids)
    scen = scenario_index()

    def row(sid: str, m: dict) -> dict:
        sc = scen.get(sid, {})
        return {"senaryo": sid, "bolum": sc.get("section"), "ne_yapilir": sc.get("title"),
                "beklenen": sc.get("expected"), "not": m.get("note") or None, "isaretleyen": m.get("by")}

    cur = marks[run["id"]]
    out = {"kosu": run["id"], "baslik": run["title"], "surum": run["version"],
           "baslatan": run["started_by"], "baslangic": run["started_at"], "bitis": run["finished_at"],
           "sayilar": {"gecti": run["counts"]["pass"], "kaldi": run["counts"]["fail"],
                       "atlandi": run["counts"]["skip"], "bekliyor": run["counts"]["pending"]},
           "bolum_sayilari": {},
           "kalanlar": [row(s, m) for s, m in cur.items() if m["result"] == "fail"],
           "atlananlar": [row(s, m) for s, m in cur.items() if m["result"] == "skip"][:40],
           "link": "/regression"}
    for sid, m in cur.items():
        sec = scen.get(sid, {}).get("section") or "?"
        b = out["bolum_sayilari"].setdefault(sec, {"gecti": 0, "kaldi": 0, "atlandi": 0})
        b[{"pass": "gecti", "fail": "kaldi", "skip": "atlandi"}[m["result"]]] += 1
    auto = last_auto(db, run["id"])
    if auto:
        out["otomatik_kontroller"] = {"zaman": auto["at"], "sorunlar": [
            {"kontrol": r["title"], "durum": r["status"], "mesaj": r["message"]}
            for r in auto["results"] if r.get("status") in ("warn", "fail")]}
    if prev:
        old = marks[prev["id"]]
        out["onceki_kosu"] = {
            "kosu": prev["id"], "baslik": prev["title"], "surum": prev["version"],
            "sayilar": {"gecti": prev["counts"]["pass"], "kaldi": prev["counts"]["fail"]},
            "once_gecip_simdi_kalan": [s for s, m in cur.items()
                                       if m["result"] == "fail" and old.get(s, {}).get("result") == "pass"],
            "once_kalip_simdi_gecen": [s for s, m in cur.items()
                                       if m["result"] == "pass" and old.get(s, {}).get("result") == "fail"]}
    return out


def ai_runs(db: Session) -> dict:
    return {"kosular": [{"kosu": r["id"], "baslik": r["title"], "surum": r["version"],
                         "baslatan": r["started_by"], "baslangic": r["started_at"], "bitti": bool(r["finished_at"]),
                         "gecti": r["counts"]["pass"], "kaldi": r["counts"]["fail"],
                         "atlandi": r["counts"]["skip"], "bekliyor": r["counts"]["pending"]}
                        for r in list_runs(db, limit=20)]}
