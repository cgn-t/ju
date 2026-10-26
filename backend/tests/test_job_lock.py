"""Çoklu pod / çoklu cluster: işlerin ortak DB kilidiyle tek yerde çalışması (v3.9.12).

Gerçek MSSQL burada yok: sp_getapplock yolu sahte bir bağlantıyla, pod'lar arası çakışma
süreç içi kilitle (iki thread = iki pod) sınanır. Dış tetikler: mail (202 + arka plan +
tekrar-önleme açık), iptal denetimi, ağ keşfi ve CT için X-API-Key.
"""

import threading
import time

import pytest

from app.api import notifications as notifications_api
from app.api import trigger_auth
from app.db.models import ScanTarget
from app.db.session import SessionLocal
from app.services import discovery, job_lock, live_check, notifier, revocation
from app.services.settings_service import get_category, save_category


@pytest.fixture(autouse=True)
def _reset_guards(client):  # client: test DB'si ve şema hazır olsun (durum app_settings'e yazılır)
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()
    yield
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()


def _wait(client, url, headers, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get(url, headers=headers).json()
        if not st["running"] and st.get("finished_at"):
            return st
        time.sleep(0.05)
    raise AssertionError(f"iş bitmedi: {url}")


# ---- Kilit ve ortak durum ----

def test_second_pod_cannot_take_busy_lock():
    pod_a, pod_b = job_lock.JobLock("t-busy"), job_lock.JobLock("t-busy")
    assert pod_a.acquire()
    got = []
    t = threading.Thread(target=lambda: got.append(pod_b.acquire()))
    t.start()
    t.join()
    assert got == [False], "kilit doluyken ikinci pod işi alamamalı"
    pod_a.release()
    assert pod_b.acquire(), "kilit bırakılınca diğer pod alabilmeli"
    pod_b.release()


def test_run_job_skips_when_busy_and_records_state():
    calls = []
    holder = job_lock.JobLock("t-run")
    assert holder.acquire()
    try:
        out = []
        t = threading.Thread(target=lambda: out.append(job_lock.run_job("t-run", lambda: calls.append(1))))
        t.start()
        t.join()
        assert out == [{"status": "skipped", "reason": "busy"}] and calls == []
    finally:
        holder.release()
    assert job_lock.run_job("t-run", lambda: {"status": "ok", "n": 3}, triggered_by="tester") == \
        {"status": "ok", "n": 3}
    st = job_lock.job_status("t-run")
    assert st["running"] is False and st["triggered_by"] == "tester"
    assert st["result"] == {"status": "ok", "n": 3} and st["started_at"] and st["finished_at"]
    assert st["pod"] == job_lock.POD


def test_scheduled_run_skips_if_another_pod_just_ran(monkeypatch):
    """Pod saatleri birkaç saniye kayık: ilk pod bitirip kilidi bıraktıktan sonra ikincisi
    tetiklenirse kilit tek başına yetmez — 'az önce çalıştı' kaydı ikinci çalışmayı durdurur."""
    monkeypatch.setattr(job_lock, "GAPS_ENABLED", True)
    calls = []
    first = job_lock.run_job("t-gap", lambda: calls.append(1) or {"status": "ok"}, min_gap_seconds=1800)
    second = job_lock.run_job("t-gap", lambda: calls.append(2) or {"status": "ok"}, min_gap_seconds=1800)
    assert first == {"status": "ok"} and second == {"status": "skipped", "reason": "recent"}
    assert calls == [1]
    # elle/dış tetik bu frenden etkilenmez
    assert job_lock.run_job("t-gap", lambda: {"status": "ok"}, triggered_by="admin") == {"status": "ok"}


def test_status_reports_interrupted_run_when_lock_is_free():
    """Pod iş sırasında çöktüyse durum 'çalışıyor' kalır ama kilit boştur → yarıda kaldı."""
    job_lock.write_state("t-crash", running=True, triggered_by="schedule", started_at="2026-10-25T03:00:00+00:00")
    st = job_lock.job_status("t-crash")
    assert st["running"] is False and st["interrupted"] is True


def test_jobstate_is_not_exposed_through_settings_api(client, auth_headers):
    job_lock.write_state("t-hidden", running=False)
    assert client.get("/api/settings/jobstate", headers=auth_headers).json() == {}
    client.put("/api/settings/jobstate", headers=auth_headers, json={"t-hidden": {"running": True}})
    assert job_lock.read_state("t-hidden") == {"running": False}, "Ayarlar API'si iş durumunu yazamamalı"


# ---- MSSQL sp_getapplock yolu (sahte bağlantı) ----

class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeConn:
    def __init__(self, codes, log):
        self.codes, self.log = codes, log

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.log.append(("release" if "sp_releaseapplock" in sql else "get", dict(params or {})))
        if "sp_releaseapplock" in sql:
            return _FakeResult(0)
        code = self.codes.pop(0)
        if isinstance(code, Exception):
            raise code
        return _FakeResult(code)

    def exec_driver_sql(self, sql):
        self.log.append(("sql", sql))

    def commit(self):
        self.log.append(("commit", {}))

    def close(self):
        self.log.append(("close", {}))

    def invalidate(self):
        self.log.append(("invalidate", {}))


class _FakeEngine:
    class dialect:
        name = "mssql"

    def __init__(self, codes):
        self.codes, self.log = codes, []

    def connect(self):
        return _FakeConn(self.codes, self.log)


def test_mssql_lock_uses_sp_getapplock_and_releases(monkeypatch):
    eng = _FakeEngine([0, -1])
    monkeypatch.setattr(job_lock, "engine", eng)
    monkeypatch.setattr(job_lock, "_mssql_disabled", False)
    a = job_lock.JobLock("live-check")
    assert a.acquire()
    assert eng.log[0] == ("get", {"res": "jumbo:live-check", "ms": 0})
    b = job_lock.JobLock("live-check")
    assert not b.acquire(), "-1 (zaman aşımı) = başka pod tutuyor"
    a.release()
    assert ("release", {"res": "jumbo:live-check"}) in eng.log
    assert not job_lock._mssql_disabled
    # NOCOUNT açık bağlantı havuza dönerse UPDATE'ler -1 satır der → girişte StaleDataError (UAT)
    assert eng.log.count(("sql", "SET NOCOUNT OFF")) == 3, "her kilit/bırakma sonrası kapatılmalı"


def test_mssql_wait_passes_timeout_in_ms(monkeypatch):
    eng = _FakeEngine([1])
    monkeypatch.setattr(job_lock, "engine", eng)
    monkeypatch.setattr(job_lock, "_mssql_disabled", False)
    lock = job_lock.JobLock("startup-schema")
    assert lock.acquire(wait_seconds=600)
    assert eng.log[0] == ("get", {"res": "jumbo:startup-schema", "ms": 600000})
    lock.release()


def test_mssql_lock_failure_falls_back_to_local_lock(monkeypatch):
    """sp_getapplock kullanılamazsa (yetki/sürüm) uygulama durmaz: pod içi kilide düşer."""
    eng = _FakeEngine([RuntimeError("Could not find stored procedure 'sp_getapplock'")])
    monkeypatch.setattr(job_lock, "engine", eng)
    monkeypatch.setattr(job_lock, "_mssql_disabled", False)
    lock = job_lock.JobLock("t-fallback")
    assert lock.acquire()
    assert job_lock._mssql_disabled is True
    assert ("invalidate", {}) in eng.log
    lock.release()


# ---- Mail tetikleri ----

def _smtp(client, h, **over):
    cfg = get_category(SessionLocal(), "smtp", mask_secrets=False)
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def test_external_mail_trigger_runs_in_background_with_dedup(client, auth_headers, monkeypatch):
    seen = []

    def fake_scan(db, *, force=False):
        seen.append(force)
        return {"enabled": True, "checked": 4, "sent": 2, "skipped": 2, "message": "ok", "details": []}
    monkeypatch.setitem(notifications_api._JOBS, "expiry-run", (notifier.JOB_EXPIRY_MAIL, fake_scan))
    _smtp(client, auth_headers, trigger_api_key="mail-key")
    key = {"X-API-Key": "mail-key"}
    r = client.post("/api/notifications/expiry-run", headers=key)
    assert r.status_code == 202, r.text
    assert r.json()["status_url"] == "/api/notifications/expiry-run/status"
    st = _wait(client, "/api/notifications/expiry-run/status", key)
    assert st["triggered_by"] == "external-api" and st["result"]["sent"] == 2
    assert seen == [False], "dış tetikte tekrar-önleme açık olmalı (force=False)"
    # ekrandaki "Şimdi Gönder" bugünkü gibi hemen gönderir ve sonucu döner
    r = client.post("/api/notifications/expiry-run", headers=auth_headers)
    assert r.status_code == 200 and r.json()["sent"] == 2
    assert seen == [False, True]


def test_mail_trigger_busy_returns_409(client, auth_headers):
    other_pod = job_lock.JobLock(notifier.JOB_EXPIRED_MAIL)
    assert other_pod.acquire()
    try:
        out = []
        t = threading.Thread(target=lambda: out.append(
            client.post("/api/notifications/expired-run", headers=auth_headers).status_code))
        t.start()
        t.join()
        assert out == [409]
        assert notifier.check_expired_certificates()["status"] == "skipped", "gece işi de atlamalı"
    finally:
        other_pod.release()


# ---- İptal denetimi ----

def _revocation(client, h, **over):
    cfg = {"enabled": True, "auto_enabled": True, "trigger_api_key": ""}
    cfg.update(over)
    assert client.put("/api/settings/revocation", headers=h, json=cfg).status_code == 200


def test_revocation_auto_off_skips_nightly_but_external_key_runs(client, auth_headers, monkeypatch):
    runs = []
    monkeypatch.setattr(revocation, "run_all_checks",
                        lambda: runs.append(1) or {"status": "ok", "checked": 0, "revoked": 0})
    _revocation(client, auth_headers, auto_enabled=False, trigger_api_key="rev-key")
    try:
        assert revocation.check_all_certificates() == {"status": "skipped"}
        assert runs == [], "gece otomatik kapalıyken çalışmamalı"
        key = {"X-API-Key": "rev-key"}
        assert client.post("/api/certificates/revocation-run", headers={"X-API-Key": "yanlis"}).status_code == 401
        r = client.post("/api/certificates/revocation-run", headers=key)
        assert r.status_code == 200, r.text
        st = _wait(client, "/api/certificates/revocation-run/status", key)
        assert runs == [1] and st["triggered_by"] == "external-api"
        assert client.post("/api/certificates/revocation-run", headers=key).status_code == 429
    finally:
        _revocation(client, auth_headers, enabled=False)


def test_revocation_external_still_refused_when_feature_off(client, auth_headers):
    _revocation(client, auth_headers, enabled=False, trigger_api_key="rev-key2")
    r = client.post("/api/certificates/revocation-run", headers={"X-API-Key": "rev-key2"})
    assert r.status_code == 409 and "kapalı" in r.json()["detail"]


# ---- Ağ keşfi / CT ----

def test_discovery_scan_with_external_key_and_busy(client, auth_headers, monkeypatch):
    done = []
    monkeypatch.setattr(discovery, "run_scan_by_id", lambda run_id: done.append(run_id))
    db = SessionLocal()
    try:
        db.add(ScanTarget(name="jl-hedef", kind="host", value="127.0.0.1", enabled=True))
        db.commit()
    finally:
        db.close()
    cfg = get_category(SessionLocal(), "discovery", mask_secrets=False)
    cfg["trigger_api_key"] = "disc-key"
    assert client.put("/api/settings/discovery", headers=auth_headers, json=cfg).status_code == 200
    key = {"X-API-Key": "disc-key"}
    r = client.post("/api/discovery/scan", headers=key)
    assert r.status_code == 200, r.text
    st = _wait(client, "/api/discovery/scan/status", key)
    assert done == [r.json()["run_id"]] and st["triggered_by"] == "external-api"
    # smtp anahtarı keşfi açamaz
    assert client.post("/api/discovery/scan", headers={"X-API-Key": "mail-key"}).status_code == 401

    other_pod = job_lock.JobLock(discovery.JOB_NAME)
    assert other_pod.acquire()
    try:
        out = []
        t = threading.Thread(target=lambda: out.append(
            client.post("/api/discovery/scan", headers=auth_headers).status_code))
        t.start()
        t.join()
        assert out == [409]
    finally:
        other_pod.release()


def test_ct_scan_requires_ct_key(client):
    assert client.post("/api/discovery/ct-scan", headers={"X-API-Key": "disc-key"}).status_code == 401
    assert client.get("/api/discovery/ct-scan/status").status_code == 401


# ---- Canlı doğrulama durumu ortak ----

def test_live_check_status_comes_from_shared_state():
    job_lock.write_state(live_check.JOB_NAME, running=False, triggered_by="external-api",
                         started_at="2026-10-25T04:00:00+00:00", finished_at="2026-10-25T04:05:00+00:00",
                         result={"status": "ok", "total": 9}, pod="baska-pod-1")
    st = live_check.bulk_run_status()
    assert st["pod"] == "baska-pod-1" and st["result"]["total"] == 9


# ---- Saat ayarı başka pod'da kaydedilince ----

def test_schedule_change_saved_elsewhere_is_applied_here():
    assert notifier.scheduler.running
    db = SessionLocal()
    try:
        before = get_category(db, "live_check", mask_secrets=False).get("schedule_hour")
        save_category(db, "live_check", {"schedule_hour": 2})  # başka pod'da kaydedilmiş gibi (API yok)
    finally:
        db.close()
    try:
        assert "live-check" in notifier.sync_schedules_from_settings()
        job = notifier.scheduler.get_job("live-check")
        assert {f.name: str(f) for f in job.trigger.fields}["hour"] == "2"
        assert notifier.sync_schedules_from_settings() == [], "değişmeyen işe dokunulmamalı"
    finally:
        db = SessionLocal()
        try:
            save_category(db, "live_check", {"schedule_hour": before if before is not None else 7})
        finally:
            db.close()
        notifier.sync_schedules_from_settings()
