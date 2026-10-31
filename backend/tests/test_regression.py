"""Regresyon Testi sayfası (v3.9.27): yalnız admin; otomatik kontroller hiçbir kaydı değiştirmez
ve mail göndermez; koşular ve işaretler Audit Log'a yazılır; AI araçları yalnız yöneticiye açık."""

import json

import pytest

from app.db.models import AuditLog, Certificate, Domain
from app.db.session import SessionLocal
from app.services import ai_assistant, notifier, regression


def _viewer(client, headers, username="regr_viewer"):
    r = client.post("/api/teams", headers=headers, json={"name": f"{username}-ekip", "type": "SY"})
    team_id = r.json()["id"]
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": "editor", "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=headers).json() if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=headers, json={"user_id": uid})
    tok = client.post("/api/auth/login-json", json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_catalog_has_all_sections_and_unique_ids(client, auth_headers):
    r = client.get("/api/regression/catalog", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    keys = [s["key"] for s in body["sections"]]
    assert keys == ["import", "canli", "mail", "kritik", "ekran", "pod", "bolum2"]
    ids = [sc["id"] for s in body["sections"] for sc in s["scenarios"]]
    assert len(ids) == len(set(ids)) == body["total"] > 200
    assert all(sc["title"] and sc["expected"] for s in body["sections"] for sc in s["scenarios"])
    # Geliştirici betikleri (pytest, .py) test eden kişiye gösterilmez
    assert not any(".py" in sc["title"] or "pytest" in sc["title"]
                   for s in body["sections"] for sc in s["scenarios"])


def test_only_admin(client, auth_headers):
    h = _viewer(client, auth_headers)
    for method, path in [("get", "/api/regression/catalog"), ("get", "/api/regression/checks"),
                         ("post", "/api/regression/checks/run"), ("get", "/api/regression/runs"),
                         ("post", "/api/regression/runs")]:
        r = getattr(client, method)(path, headers=h)
        assert r.status_code == 403, (path, r.status_code)


def test_auto_checks_read_only(client, auth_headers, monkeypatch):
    def no_mail(*a, **k):
        raise AssertionError("Otomatik kontrol mail göndermemeli")
    monkeypatch.setattr(notifier, "_send_mail", no_mail)
    real = regression.get_category   # önceki testler SMTP/AD'yi açık bırakmış olabilir
    monkeypatch.setattr(regression, "get_category", lambda db, cat, mask_secrets=True: (
        {**real(db, cat, mask_secrets), "enabled": False} if cat in ("smtp", "ldap") else real(db, cat, mask_secrets)))
    db = SessionLocal()
    before = (db.query(Certificate).count(), db.query(Domain).count(),
              db.query(AuditLog).filter(AuditLog.action != "regression_auto").count())
    db.close()

    r = client.post("/api/regression/checks/run", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    results = {x["id"]: x for x in r.json()["results"]}
    assert set(results) == {c["id"] for c in regression.check_list()}
    # Kodun kendisinden gelen kontroller testte yeşil olmalı
    for cid in ("schema", "auth", "admin-only", "admins"):
        assert results[cid]["status"] == "ok", results[cid]
    assert results["db"]["status"] == "warn" and "sqlite" in results["db"]["message"]
    assert results["secrets"]["status"] == "warn"           # testte FERNET_KEY yok
    assert results["ldap"]["status"] == results["smtp"]["status"] == "skip"
    pages = [x for x in results.values() if x["group"] == "Sayfalar"]
    assert len(pages) == len(regression.PAGES)
    assert all(p["status"] in ("ok", "warn") for p in pages), [p for p in pages if p["status"] == "fail"]

    db = SessionLocal()
    after = (db.query(Certificate).count(), db.query(Domain).count(),
             db.query(AuditLog).filter(AuditLog.action != "regression_auto").count())
    db.close()
    assert after == before   # yalnız sonucun kendisi Audit Log'a yazıldı

    last = client.get("/api/regression/checks", headers=auth_headers).json()["last"]
    assert last["results"] and last["by"] == "admin"


def test_admin_only_check_catches_weakened_route(client, auth_headers, monkeypatch):
    monkeypatch.setattr(regression, "ADMIN_ONLY", regression.ADMIN_ONLY + [("GET", "/api/dashboard")])
    db = SessionLocal()
    try:
        status, msg = regression._admin_only(db)
    finally:
        db.close()
    assert status == "fail" and "/api/dashboard" in msg


def test_smtp_check_connects_without_sending(client, auth_headers, monkeypatch):
    calls = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls.append("starttls")

        def login(self, u, p):
            calls.append(("login", u))

        def noop(self):
            calls.append("noop")

        def sendmail(self, *a):
            raise AssertionError("mail gönderilmemeli")

    monkeypatch.setattr(regression.smtplib, "SMTP", FakeSmtp)
    client.put("/api/settings/smtp", headers=auth_headers, json={
        "enabled": True, "host": "smtp.firma.local", "port": 587, "use_tls": True,
        "username": "jumbo", "password": "p", "from_address": "jumbo@firma.local", "fallback_address": ""})
    try:
        db = SessionLocal()
        status, msg = regression._smtp(db)
        db.close()
    finally:
        client.put("/api/settings/smtp", headers=auth_headers, json={"enabled": False, "host": ""})
    assert calls == [("connect", "smtp.firma.local", 587), "starttls", ("login", "jumbo"), "noop"]
    assert status == "warn" and "yedek adres" in msg


def test_run_marks_finish_and_history(client, auth_headers):
    r = client.post("/api/regression/runs", headers=auth_headers, json={"title": "Preprod deneme"})
    assert r.status_code == 200, r.text
    run = r.json()
    rid = run["id"]
    assert run["title"] == "Preprod deneme" and run["version"] == regression.app_version()
    assert run["counts"]["pending"] == run["counts"]["total"]

    m = lambda sc, res, note="": client.post(f"/api/regression/runs/{rid}/marks", headers=auth_headers,  # noqa: E731
                                            json={"scenario": sc, "result": res, "note": note})
    assert m("MAIL-A1", "pass").status_code == 200
    assert m("MAIL-A2", "fail", "Kırmızı bildirim çıkmadı").json()["note"] == "Kırmızı bildirim çıkmadı"
    assert m("EKR-E1", "skip").status_code == 200
    assert m("EKR-E1", None).status_code == 200            # işaret kaldırıldı
    assert m("YOK-1", "pass").status_code == 400
    assert m("MAIL-A1", "belki").status_code == 400

    # Yeni bir koşu açılsa da işaretler koşuya özel kalır
    other = client.post("/api/regression/runs", headers=auth_headers, json={}).json()
    assert other["title"].endswith("regresyon testi") and other["counts"]["pass"] == 0

    run = client.get(f"/api/regression/runs/{rid}", headers=auth_headers).json()
    assert run["counts"]["pass"] == 1 and run["counts"]["fail"] == 1 and run["counts"]["skip"] == 0
    assert set(run["marks"]) == {"MAIL-A1", "MAIL-A2"}
    assert run["marks"]["MAIL-A2"]["by"] == "admin"

    r = client.post("/api/regression/checks/run", headers=auth_headers, json={"run_id": rid})
    assert r.json()["run_id"] == rid
    assert client.get(f"/api/regression/runs/{rid}", headers=auth_headers).json()["auto"]["run_id"] == rid

    done = client.post(f"/api/regression/runs/{rid}/finish", headers=auth_headers).json()
    assert done["finished_at"] and done["finished_by"] == "admin"
    assert m("MAIL-A3", "pass").status_code == 409
    assert client.get("/api/regression/runs/YOK", headers=auth_headers).status_code == 404

    ids = [x["id"] for x in client.get("/api/regression/runs", headers=auth_headers).json()]
    assert ids.index(other["id"]) < ids.index(rid)   # en yeni önce

    # Audit Log'da okunur özet
    rows = client.get("/api/audit", headers=auth_headers, params={"q": "MAIL-A2"}).json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert any("Kaldı" in (a.get("summary") or "") for a in items)


def test_ai_report_compares_with_previous_run(client, auth_headers):
    def run_with(marks):
        rid = client.post("/api/regression/runs", headers=auth_headers, json={}).json()["id"]
        for sc, res in marks.items():
            client.post(f"/api/regression/runs/{rid}/marks", headers=auth_headers,
                        json={"scenario": sc, "result": res, "note": "not " + sc})
        return rid

    run_with({"IMP-A1": "pass", "IMP-A2": "fail"})
    rid = run_with({"IMP-A1": "fail", "IMP-A2": "pass", "MAIL-A1": "skip"})
    db = SessionLocal()
    try:
        rep = regression.ai_run_report(db)
    finally:
        db.close()
    assert rep["kosu"] == rid
    assert rep["sayilar"]["kaldi"] == 1 and rep["sayilar"]["atlandi"] == 1
    assert rep["kalanlar"][0]["senaryo"] == "IMP-A1" and rep["kalanlar"][0]["not"] == "not IMP-A1"
    assert rep["kalanlar"][0]["beklenen"] == "Eklenir"
    assert rep["onceki_kosu"]["once_gecip_simdi_kalan"] == ["IMP-A1"]
    assert rep["onceki_kosu"]["once_kalip_simdi_gecen"] == ["IMP-A2"]


@pytest.fixture()
def ai_on(client, auth_headers):
    client.put("/api/settings/ai", headers=auth_headers, json={
        "enabled": True, "api_url": "https://ai.firma.local/v1", "api_key": "k", "model": "m",
        "daily_limit": 0, "use_tools": True, "full_access": True})
    ai_assistant._usage.clear()
    yield
    client.put("/api/settings/ai", headers=auth_headers, json={"enabled": False, "daily_limit": 100})


def test_ai_regression_tools_admin_only_and_prompt(client, auth_headers, ai_on, monkeypatch):
    bodies = []
    replies = [
        {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "regresyon_sonucu", "arguments": "{}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Özet hazır"}}]},
    ]

    def fake(cfg, body):
        bodies.append(json.loads(json.dumps(body)))
        return replies.pop(0)
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "Son testi özetle"}], "page": "/regression"})
    assert r.status_code == 200, r.text
    assert r.json()["tools_used"] == ["regresyon_sonucu"]
    assert "Regresyon Testi sayfasında" in bodies[0]["messages"][0]["content"]
    tool_msg = json.loads(bodies[1]["messages"][-1]["content"])
    assert "kosu" in tool_msg and "sayilar" in tool_msg

    # Yönetici olmayana araç sunulmaz, sayfa notu da eklenmez (tam erişim açık olsa bile)
    h = _viewer(client, auth_headers, "regr_ai_editor")
    bodies.clear()
    replies.append({"choices": [{"message": {"role": "assistant", "content": "tamam"}}]})
    client.post("/api/ai/chat", headers=h, json={
        "messages": [{"role": "user", "content": "merhaba"}], "page": "/regression"})
    names = {t["function"]["name"] for t in bodies[0]["tools"]}
    assert not names & set(ai_assistant.REGRESSION_TOOLS)
    assert "Regresyon Testi sayfasında" not in bodies[0]["messages"][0]["content"]
