"""Çoklu pod / çoklu cluster: aynı iş aynı anda TEK yerde çalışsın.

Kilit ortak veritabanındadır: MSSQL `sp_getapplock` (oturuma bağlı, yeni tablo GEREKMEZ).
Kilidi tutan pod iş sırasında çökerse DB bağlantısı kopar ve MSSQL kilidi kendisi bırakır —
elle temizlik gerekmez. SQLite (geliştirme/test) tek süreçtir; orada süreç içi kilit yeterli.
sp_getapplock kullanılamazsa (yetki/sürüm) bir kez hata loglanır ve süreç içi kilide düşülür:
uygulama çalışmaya devam eder, yalnız pod'lar arası koruma olmaz.

İşin son durumu (kim başlattı, ne zaman, hangi pod, sonuç) app_settings'te `jobstate.<iş>`
satırında tutulur — hangi pod'a bağlanılırsa bağlanılsın aynı durum görünür. Bu kategori
DEFAULTS'ta olmadığından Ayarlar API'sinden okunamaz/yazılamaz."""

import json
import logging
import os
import socket
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.timeutil import utcnow
from app.db.models import AppSetting
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

STATE_CATEGORY = "jobstate"
POD = os.environ.get("HOSTNAME") or socket.gethostname()
# Zamanlanmış günlük işlerde: başka pod bu süre içinde aynı işi başlattıysa tekrar çalışma
# (pod saatleri birkaç saniye kayık olabilir; ilk pod bitirip kilidi bıraktıktan sonra
# ikincisi tetiklenirse kilit tek başına yetmez).
DAILY_GAP_SECONDS = 30 * 60
# Testler aynı zamanlanmış işi art arda çağırır; orada bu fren kapatılır (conftest).
GAPS_ENABLED = True

_local_locks: dict[str, threading.Lock] = {}
_local_guard = threading.Lock()
_mssql_disabled = False  # sp_getapplock bir kez başarısız olduysa süreç içi kilide düşülür

_LOCK_SQL = text(
    "SET NOCOUNT ON; DECLARE @r int; "
    "EXEC @r = sp_getapplock @Resource = :res, @LockMode = 'Exclusive', "
    "@LockOwner = 'Session', @LockTimeout = :ms; SELECT @r AS r")
_UNLOCK_SQL = text(
    "SET NOCOUNT ON; DECLARE @r int; "
    "EXEC @r = sp_releaseapplock @Resource = :res, @LockOwner = 'Session'; SELECT @r AS r")
# NOCOUNT oturuma yapışır: açık kalırsa bağlantı havuza dönünce UPDATE'ler satır sayısı -1 verir
# ve SQLAlchemy StaleDataError atar (girişte last_login → 500). Her kilit sorgusundan sonra kapatılır.
_NOCOUNT_OFF = "SET NOCOUNT OFF"


def _local(name: str) -> threading.Lock:
    with _local_guard:
        return _local_locks.setdefault(name, threading.Lock())


def _use_db_lock() -> bool:
    return engine.dialect.name == "mssql" and not _mssql_disabled


class JobLock:
    """Tek bir işin kilidi. acquire() → True ise iş bu pod'da çalışabilir; bitince release().
    Kilit iş parçacığına devredilebilir (istekte alınır, arka plan thread'i bırakır)."""

    def __init__(self, name: str):
        self.name = name
        self.held = False
        self._conn = None
        self._local: threading.Lock | None = None

    @property
    def resource(self) -> str:
        return f"jumbo:{self.name}"

    def acquire(self, wait_seconds: float = 0) -> bool:
        global _mssql_disabled
        if self.held:
            return True
        if _use_db_lock():
            try:
                return self._acquire_db(wait_seconds)
            except Exception:
                _mssql_disabled = True
                logger.exception("Veritabanı iş kilidi (sp_getapplock) kullanılamadı — pod içi "
                                 "kilide geçildi; birden fazla pod varsa işler çakışabilir")
        lock = _local(self.name)
        ok = lock.acquire(timeout=wait_seconds) if wait_seconds > 0 else lock.acquire(blocking=False)
        if ok:
            self._local, self.held = lock, True
        return ok

    def _acquire_db(self, wait_seconds: float) -> bool:
        conn = engine.connect()
        try:
            code = conn.execute(_LOCK_SQL, {"res": self.resource,
                                            "ms": int(max(0, wait_seconds) * 1000)}).scalar()
            conn.exec_driver_sql(_NOCOUNT_OFF)
            conn.commit()
        except Exception:
            conn.invalidate()
            conn.close()
            raise
        if code is not None and code >= 0:  # 0: hemen verildi, 1: bekledikten sonra verildi
            self._conn, self.held = conn, True
            return True
        conn.close()
        if code in (-1, -2, -3):  # zaman aşımı (başkası tutuyor) / iptal / deadlock kurbanı
            return False
        raise RuntimeError(f"sp_getapplock beklenmeyen sonuç: {code}")

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        if self._conn is not None:
            conn, self._conn = self._conn, None
            try:
                conn.execute(_UNLOCK_SQL, {"res": self.resource}).scalar()
                conn.exec_driver_sql(_NOCOUNT_OFF)
                conn.commit()
                conn.close()
            except Exception:
                # Bırakılamadıysa bağlantıyı havuza geri VERME: fiziksel bağlantı kapanınca
                # MSSQL kilidi kendisi bırakır.
                logger.exception("İş kilidi bırakılamadı (%s) — bağlantı kapatıldı", self.name)
                conn.invalidate()
                conn.close()
        elif self._local is not None:
            lock, self._local = self._local, None
            lock.release()


# ---- Ortak iş durumu (app_settings: jobstate.<iş>) ----

def _now_iso() -> str:
    """UTC, saat dilimi işaretli ISO — tarayıcı yerel saat sanıp 3 saat kaydırmasın."""
    return utcnow().replace(tzinfo=timezone.utc).isoformat()


def _parse_iso(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def read_state(name: str) -> dict:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, f"{STATE_CATEGORY}.{name}")
        return json.loads(row.value) if row is not None and row.value else {}
    except Exception:
        logger.exception("İş durumu okunamadı (%s)", name)
        return {}
    finally:
        db.close()


def write_state(name: str, **fields) -> None:
    """Durumu birleştirerek yazar. Yalnız kilidi tutan çağırır → aynı satıra eşzamanlı yazım yok."""
    db = SessionLocal()
    try:
        key = f"{STATE_CATEGORY}.{name}"
        row = db.get(AppSetting, key)
        state = json.loads(row.value) if row is not None and row.value else {}
        state.update(fields)
        if row is None:
            row = AppSetting(key=key, category=STATE_CATEGORY)
            db.add(row)
        row.value = json.dumps(state, ensure_ascii=False, default=str)
        row.is_encrypted = False
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("İş durumu yazılamadı (%s)", name)
    finally:
        db.close()


def job_status(name: str) -> dict:
    """Son çalıştırmanın durumu: running, triggered_by, started_at, finished_at, pod, result.
    Durum 'çalışıyor' diyor ama kilit boşsa iş yarıda kalmıştır (pod çöktü/yeniden başladı):
    'running' False döner ve 'interrupted' True işaretlenir."""
    state = read_state(name)
    out = {"running": bool(state.get("running")), "triggered_by": state.get("triggered_by"),
           "started_at": state.get("started_at"), "finished_at": state.get("finished_at"),
           "pod": state.get("pod"), "result": state.get("result")}
    if out["running"]:
        probe = JobLock(name)
        if probe.acquire():
            probe.release()
            out["running"] = False
            out["interrupted"] = True
    return out


def run_job(name: str, fn, *, triggered_by: str = "schedule", lock: JobLock | None = None,
            min_gap_seconds: int = 0, record: bool = True):
    """İşi kilit altında çalıştırır. `lock` verilmişse (istekte alınmış) onu kullanır ve bitince
    bırakır; verilmemişse kendisi almaya çalışır, alamazsa {"status": "skipped"} döner.
    min_gap_seconds: zamanlanmış çalıştırmada başka bir pod bu süre içinde aynı zamanlanmış
    işi başlattıysa tekrar çalışmaz. record=False: durum yazılmaz (12 sn'lik poll gibi)."""
    if lock is None:
        lock = JobLock(name)
        if not lock.acquire():
            logger.info("'%s' işi başka bir yerde çalışıyor — atlandı", name)
            return {"status": "skipped", "reason": "busy"}
    try:
        now = _now_iso()
        if not GAPS_ENABLED:
            min_gap_seconds = 0
        if min_gap_seconds:
            last = _parse_iso(read_state(name).get("last_scheduled_at"))
            if last and utcnow() - last < timedelta(seconds=min_gap_seconds):
                logger.info("'%s' işi az önce başka bir pod'da çalıştı — atlandı", name)
                return {"status": "skipped", "reason": "recent"}
        if record:
            write_state(name, running=True, triggered_by=triggered_by, started_at=now,
                        finished_at=None, result=None, pod=POD,
                        **({"last_scheduled_at": now} if min_gap_seconds else {}))
        elif min_gap_seconds:
            write_state(name, last_scheduled_at=now)
        result = None
        try:
            result = fn()
            return result
        except Exception as exc:
            result = {"status": "error", "error": str(exc)[:300]}
            raise
        finally:
            if record:
                write_state(name, running=False, finished_at=_now_iso(),
                            result=result if isinstance(result, dict) else None)
    finally:
        lock.release()


def start_in_background(name: str, fn, *, triggered_by: str, thread_name: str | None = None) -> bool:
    """Kilidi BU istekte alır ve işi arka plan thread'inde çalıştırır (HTTP isteği beklemez —
    ön kapı zaman aşımına düşmesin). Kilit doluysa False (çağıran 409 döner)."""
    lock = JobLock(name)
    if not lock.acquire():
        return False
    # Durum hemen 'çalışıyor' olsun: yanıt döner dönmez sorgulayan eski sonucu görmesin.
    write_state(name, running=True, triggered_by=triggered_by, started_at=_now_iso(),
                finished_at=None, result=None, pod=POD)

    def _target():
        try:
            run_job(name, fn, triggered_by=triggered_by, lock=lock)
        except Exception:
            logger.exception("'%s' arka plan işi hata verdi", name)
    try:
        threading.Thread(target=_target, daemon=True, name=thread_name or f"job-{name}").start()
    except Exception:
        lock.release()
        raise
    return True
