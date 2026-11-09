"""Veritabanı Değişiklikleri sayfası (v3.9.38, yalnız admin, yalnız DB_CONSOLE=1).

Sahip, GitHub'daki db/degisiklikler/<sürüm>-*.sql betiğini sayfaya yapıştırıp çalıştırır.
  • Her çalıştırma TEK işlem (transaction) içindedir: hata olursa hiçbir şey değişmez.
  • "Dene" aynı SQL'i çalıştırır, sonucu gösterir ve her şeyi GERİ ALIR.
  • DROP / TRUNCATE / WHERE'siz DELETE-UPDATE görülürse kalıcı çalıştırma için "UYGULA"
    yazılması istenir (sunucu tarafında da zorlanır).
  • MSSQL'de aynı anda tek çalıştırma (sp_getapplock, işlem sahipli) ve 60 sn kilit bekleme sınırı.
  • Kim, ne zaman, hangi SQL, sonuç ve süre mevcut AuditLog tablosuna yazılır (yeni tablo yok).
"""

import re
import threading
import time

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuditLog, User
from app.db.session import engine
from app.services import schema_state
from app.services.audit import log_action

TABLE = "db_console"
ACTION_RUN = "db_console_run"
ACTION_TRY = "db_console_try"
CONFIRM_WORD = "UYGULA"
MAX_ROWS = 200
MAX_RESULT_SETS = 10
MAX_SQL_LEN = 100_000
LOCK_TIMEOUT_MS = 60_000
_local_lock = threading.Lock()


class ConsoleBusy(Exception):
    pass


def enabled() -> bool:
    return bool(get_settings().db_console)


# ---------- SQL çözümleme ----------

_GO_RE = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


def strip_comments(sql: str) -> str:
    """-- ve /* */ yorumlarını tırnak içine dokunmadan siler (uyarı taraması için)."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and (j + 1 >= n or sql[j + 1] != "'"):
                    break
                j += 2 if sql[j] == "'" else 1
            out.append(" ")  # metin içeriği uyarıyı tetiklemesin
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_batches(sql: str) -> list[str]:
    """SSMS'teki gibi tek başına satırdaki GO ile ayrılan parçalar."""
    return [b.strip() for b in _GO_RE.split(sql) if b.strip()]


def split_statements(batch: str) -> list[str]:
    """SQLite tek seferde tek ifade çalıştırır: ;'leri tırnak/yorum dışında böler."""
    parts, buf, i, n = [], [], 0, len(batch)
    while i < n:
        ch = batch[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if batch[j] == "'" and (j + 1 >= n or batch[j + 1] != "'"):
                    break
                j += 2 if batch[j] == "'" else 1
            buf.append(batch[i:j + 1])
            i = j + 1
        elif batch.startswith("--", i):
            j = batch.find("\n", i)
            j = n if j < 0 else j
            buf.append(batch[i:j])
            i = j
        elif ch == ";":
            parts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if strip_comments(p).strip()]


_STMT_SPLIT = re.compile(r";|\n\s*\n")


def warnings_for(sql: str) -> list[str]:
    """Kalıcı çalıştırmada ek onay gerektiren ifadeler."""
    clean = strip_comments(sql)
    found: list[str] = []
    if re.search(r"\bDROP\b", clean, re.I):
        found.append("DROP: bir tablo, kolon ya da nesne silinecek")
    if re.search(r"\bTRUNCATE\b", clean, re.I):
        found.append("TRUNCATE: tablodaki tüm satırlar silinecek")
    for stmt in _STMT_SPLIT.split(clean):
        s = stmt.strip()
        if re.match(r"^(DELETE|UPDATE)\b", s, re.I) and not re.search(r"\bWHERE\b", s, re.I):
            found.append(f"WHERE'siz {s.split()[0].upper()}: tablodaki tüm satırları etkiler")
    # sıra korunarak tekilleştir
    return list(dict.fromkeys(found))


# ---------- Bilgi ----------

def info(db: Session) -> dict:
    dialect = engine.dialect.name
    out: dict = {"enabled": enabled(), "dialect": dialect, "database": None, "can_alter": None,
                 "pending": schema_state.pending_list()}
    try:
        if dialect == "mssql":
            out["database"] = db.execute(text("SELECT DB_NAME()")).scalar()
            perm = db.execute(text(
                "SELECT HAS_PERMS_BY_NAME('dbo.SSLCertificates', 'OBJECT', 'ALTER')")).scalar()
            out["can_alter"] = bool(perm) if perm is not None else None
        else:
            out["database"] = (engine.url.database or "").rsplit("/", 1)[-1] or dialect
            out["can_alter"] = True
    except Exception:  # bilgi alınamazsa sayfa yine açılır
        pass
    return out


def history(db: Session, limit: int = 50) -> list[dict]:
    import json
    rows = (db.query(AuditLog).filter(AuditLog.table_name == TABLE)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all())
    out = []
    for r in rows:
        try:
            d = json.loads(r.details or "{}")
        except ValueError:
            d = {}
        out.append({"id": r.id, "at": r.created_at, "by": r.username, "dry_run": r.action == ACTION_TRY,
                    "title": d.get("title") or "", "sql": d.get("sql") or "", "ok": bool(d.get("ok")),
                    "error": d.get("error"), "ms": d.get("ms"), "rowcounts": d.get("rowcounts") or []})
    return out


# ---------- Çalıştırma ----------

def _execute(cur, stmt: str, results: list, rowcounts: list) -> None:
    cur.execute(stmt)
    while True:
        if cur.description is not None:
            cols = [c[0] for c in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
            if len(results) < MAX_RESULT_SETS:
                results.append({"columns": cols,
                                "rows": [[_cell(v) for v in row] for row in rows[:MAX_ROWS]],
                                "truncated": len(rows) > MAX_ROWS})
            cur.fetchall()  # kalan satırları tüket (sonraki sonuç kümesine geçebilmek için)
        elif cur.rowcount is not None and cur.rowcount >= 0:
            rowcounts.append(cur.rowcount)
        nextset = getattr(cur, "nextset", None)
        try:
            if not nextset or not nextset():
                break
        except Exception:
            break


def _cell(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v[:64]).hex() + ("…" if len(v) > 64 else "")
    return str(v)


def _error_text(exc: Exception) -> str:
    orig = getattr(exc, "orig", None) or exc
    args = getattr(orig, "args", None) or ()
    if args and isinstance(args[0], tuple) and len(args[0]) > 1:  # bazı sürümler: ((kod, b'mesaj'),)
        args = args[0]
    if len(args) > 1 and isinstance(args[0], int) and isinstance(args[1], (bytes, str)):  # pymssql: (kod, b'mesaj')
        msg = args[1].decode("utf-8", "replace") if isinstance(args[1], bytes) else args[1]
        return f"{msg.split('DB-Lib error')[0].strip()} (hata {args[0]})"
    return str(orig).strip()


def run(db: Session, user: User, sql: str, title: str, dry_run: bool, request: Request | None) -> dict:
    """SQL'i ayrı bir bağlantıda tek işlem olarak çalıştırır; dry_run ise sonunda geri alır."""
    dialect = engine.dialect.name
    batches = split_batches(sql)
    started = time.monotonic()
    results: list = []
    rowcounts: list = []
    error = None

    if dialect != "mssql" and not _local_lock.acquire(blocking=False):
        raise ConsoleBusy()
    try:
        with engine.connect() as conn:
            dbapi = conn.connection.dbapi_connection
            cur = dbapi.cursor()
            try:
                if dialect == "mssql":
                    # pymssql autocommit kapalı çalışır: işlemi (BEGIN TRAN) sürücü kendisi açar;
                    # ikinci bir BEGIN iç içe işlem yaratır ve commit'i yarım bırakırdı.
                    cur.execute(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}")
                    cur.execute("DECLARE @r int; EXEC @r = sp_getapplock @Resource = 'jumbo.db_console', "
                                "@LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 0; "
                                "SELECT @r")
                    got = cur.fetchone()
                    if got is None or got[0] < 0:
                        dbapi.rollback()
                        raise ConsoleBusy()
                    for b in batches:
                        _execute(cur, b, results, rowcounts)
                else:
                    cur.execute("BEGIN")
                    for b in batches:
                        for stmt in split_statements(b):
                            _execute(cur, stmt, results, rowcounts)
                if dry_run:
                    dbapi.rollback()
                else:
                    dbapi.commit()
            except ConsoleBusy:
                raise
            except Exception as exc:  # SQL hatası: her şey geri alınır
                error = _error_text(exc)
                try:
                    dbapi.rollback()
                except Exception:
                    pass
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                if dialect == "mssql":
                    try:
                        c2 = dbapi.cursor()
                        c2.execute("SET LOCK_TIMEOUT -1")
                        c2.close()
                    except Exception:
                        pass
    finally:
        if dialect != "mssql":
            _local_lock.release()

    ms = int((time.monotonic() - started) * 1000)
    ok = error is None
    if ok and not dry_run:
        schema_state.refresh()
    log_action(db, user.username, ACTION_TRY if dry_run else ACTION_RUN, TABLE, None,
               {"title": title, "sql": sql, "dry_run": dry_run, "ok": ok, "error": error,
                "ms": ms, "rowcounts": rowcounts[:50]}, request)
    db.commit()
    return {"ok": ok, "dry_run": dry_run, "error": error, "ms": ms, "results": results,
            "rowcounts": rowcounts, "pending": schema_state.pending_list()}
