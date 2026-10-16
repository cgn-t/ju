"""Toplu canlı doğrulamanın DIŞARIDAN tetiklenmesi (POST /api/domains/live-check-run).

Yetki: X-API-Key (live_check.trigger_api_key) VEYA admin JWT. Anahtar boşsa dış tetik kapalı;
bildirim (smtp) anahtarı bu ucu AÇAMAZ. Tarama arka planda çalışır (202); aynı anda ikinci
tarama başlatılamaz (409); dış tetik art arda çağrılamaz (429). Gece ayarı bu ucu etkilemez.
"""

import json
import time

import pytest

from app.api import trigger_auth
from app.services import live_check

URL = "/api/domains/live-check-run"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    calls = []

    def fake_scan():
        calls.append(time.monotonic())
        return {"status": "ok", "total": 3, "by_status": {"match": 2, "mismatch": 1},
                "errors": 0, "mismatched": ["gizli.example.test"]}
    monkeypatch.setattr(live_check, "_scan_all_domains", fake_scan)
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()
    yield calls
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()


def _settings(client, h, **over):
    cfg = {"enabled": True, "schedule_hour": 7, "trigger_api_key": ""}
    cfg.update(over)
    assert client.put("/api/settings/live_check", headers=h, json=cfg).status_code == 200


def _wait_done(client, headers, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get(f"{URL}/status", headers=headers).json()
        if not st["running"] and st.get("finished_at"):
            return st
        time.sleep(0.05)
    raise AssertionError("toplu tarama bitmedi")


def test_requires_auth_and_key_disabled_when_empty(client, auth_headers):
    _settings(client, auth_headers, trigger_api_key="")
    assert client.post(URL).status_code == 401
    assert client.post(URL, headers={"X-API-Key": ""}).status_code == 401
    assert client.post(URL, headers={"X-API-Key": "herhangi"}).status_code == 401


def test_external_key_starts_background_run_and_status_hides_names(client, auth_headers, _isolate):
    _settings(client, auth_headers, trigger_api_key="lc-anahtar-123")
    key = {"X-API-Key": "lc-anahtar-123"}
    r = client.post(URL, headers=key)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "started" and r.json()["triggered_by"] == "external-api"
    st = _wait_done(client, key)
    assert st["triggered_by"] == "external-api"
    assert st["started_at"].endswith("+00:00") and st["finished_at"].endswith("+00:00"), \
        "saat dilimi işaretli olmalı (tarayıcı UTC'yi yerel saat sanmasın)"
    assert st["result"]["total"] == 3 and st["result"]["by_status"] == {"match": 2, "mismatch": 1}
    assert "mismatched" not in st["result"], "dış anahtara domain adları dönmemeli"
    assert len(_isolate) == 1
    admin_view = client.get(f"{URL}/status", headers=auth_headers).json()
    assert admin_view["result"]["mismatched"] == ["gizli.example.test"]

    items = client.get("/api/audit", headers=auth_headers, params={"limit": 50}).json()["items"]
    trig = next(e for e in items if e["action"] == "live_check_run" and e["username"] == "external-api")
    assert json.loads(trig["details"])["scope"] == "all"
    summary = next(e for e in items if e["action"] == "job_summary"
                   and json.loads(e["details"]).get("job") == "Canlı doğrulama (tetiklenen)")
    assert json.loads(summary["details"])["triggered_by"] == "external-api"


def test_notification_key_cannot_trigger_live_check(client, auth_headers):
    _settings(client, auth_headers, trigger_api_key="lc-ayri")
    smtp = client.get("/api/settings/smtp", headers=auth_headers).json()
    smtp["trigger_api_key"] = "mail-anahtari"
    assert client.put("/api/settings/smtp", headers=auth_headers, json=smtp).status_code == 200
    assert client.post(URL, headers={"X-API-Key": "mail-anahtari"}).status_code == 401


def test_admin_jwt_allowed_editor_forbidden(client, auth_headers):
    _settings(client, auth_headers)
    assert client.post(URL, headers=auth_headers).status_code == 202
    _wait_done(client, auth_headers)
    client.post("/api/users", headers=auth_headers, json={
        "username": "lc_trigger_editor", "password": "pw12345", "role": "editor", "auth_source": "local"})
    tok = client.post("/api/auth/login-json", json={"username": "lc_trigger_editor",
                                                    "password": "pw12345"}).json()["access_token"]
    assert client.post(URL, headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_concurrent_run_is_rejected_and_nightly_skips(client, auth_headers):
    _settings(client, auth_headers)
    assert live_check._bulk_lock.acquire(blocking=False)
    try:
        assert client.post(URL, headers=auth_headers).status_code == 409
        assert live_check.check_all_domains() == {"status": "skipped"}, "gece işi çakışmada atlamalı"
    finally:
        live_check._bulk_lock.release()


def test_external_cooldown(client, auth_headers):
    _settings(client, auth_headers, trigger_api_key="lc-cool")
    key = {"X-API-Key": "lc-cool"}
    assert client.post(URL, headers=key).status_code == 202
    _wait_done(client, key)
    assert client.post(URL, headers=key).status_code == 429


def test_trigger_works_even_when_nightly_disabled(client, auth_headers, _isolate):
    _settings(client, auth_headers, enabled=False)
    assert live_check.check_all_domains() == {"status": "skipped"}
    assert _isolate == [], "gece işi kapalıyken tarama yapılmamalı"
    assert client.post(URL, headers=auth_headers).status_code == 202
    _wait_done(client, auth_headers)
    assert len(_isolate) == 1, "dış/elle tetik gece ayarından bağımsız çalışmalı"
    _settings(client, auth_headers, enabled=True)


def test_wrong_keys_are_rate_limited(client, auth_headers):
    _settings(client, auth_headers, trigger_api_key="lc-dogru")
    codes = [client.post(URL, headers={"X-API-Key": f"yanlis-{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[-1] == 429
