"""v3.9.38 Veritabanı Değişiklikleri sayfası: yalnız admin, yalnız DB_CONSOLE=1; SQL tek işlemde
çalışır, "Dene" geri alır, riskli ifade UYGULA onayı ister, her çalıştırma Audit Log'a yazılır."""

import pytest
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.session import engine
from app.services import db_console


@pytest.fixture()
def console_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "db_console", True)


def _tables():
    return set(inspect(engine).get_table_names())


def _run(client, h, sql, dry=False, title="test", confirm=None):
    body = {"sql": sql, "title": title, "dry_run": dry}
    if confirm is not None:
        body["confirm"] = confirm
    return client.post("/api/db-console/run", headers=h, json=body)


def test_disabled_by_default_hidden(client, auth_headers):
    assert client.get("/api/db-console", headers=auth_headers).status_code == 404
    assert _run(client, auth_headers, "SELECT 1").status_code == 404
    assert client.get("/api/auth/me", headers=auth_headers).json()["features"]["db_console"] is False


def test_admin_only(client, auth_headers, console_on):
    r = client.post("/api/users", headers=auth_headers, json={"username": "dbc_editor", "password": "Parola!123", "role": "editor"})
    assert r.status_code == 200
    tok = client.post("/api/auth/login-json", json={"username": "dbc_editor", "password": "Parola!123"}).json()["access_token"]
    eh = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/db-console", headers=eh).status_code == 403
    assert _run(client, eh, "SELECT 1").status_code == 403
    assert client.get("/api/auth/me", headers=eh).json()["features"]["db_console"] is False
    assert client.get("/api/auth/me", headers=auth_headers).json()["features"]["db_console"] is True


def test_try_rolls_back_and_run_commits(client, auth_headers, console_on):
    sql = "-- deneme\nCREATE TABLE dbc_deneme (id INTEGER, ad VARCHAR(20));\nINSERT INTO dbc_deneme VALUES (1, 'a;b');"
    r = _run(client, auth_headers, sql, dry=True, title="v0 deneme")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] and r.json()["dry_run"]
    assert "dbc_deneme" not in _tables()                      # geri alındı
    r = _run(client, auth_headers, sql, title="v0 kalıcı")
    assert r.status_code == 200 and r.json()["ok"]
    assert "dbc_deneme" in _tables()
    # SELECT sonucu tablo olarak döner
    r = _run(client, auth_headers, "SELECT id, ad FROM dbc_deneme", dry=True, title="kontrol")
    assert r.json()["results"][0] == {"columns": ["id", "ad"], "rows": [[1, "a;b"]], "truncated": False}
    hist = client.get("/api/db-console", headers=auth_headers).json()["history"]
    assert [h["title"] for h in hist[:3]] == ["kontrol", "v0 kalıcı", "v0 deneme"]
    assert hist[1]["dry_run"] is False and hist[2]["dry_run"] is True and hist[1]["by"] == "admin"
    assert "CREATE TABLE dbc_deneme" in hist[1]["sql"]


def test_error_changes_nothing(client, auth_headers, console_on):
    r = _run(client, auth_headers, "CREATE TABLE dbc_hata (id INTEGER);\nINSERT INTO yok_boyle_tablo VALUES (1);",
             title="hatalı")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "yok_boyle_tablo" in body["error"]
    assert "dbc_hata" not in _tables()                        # ilk ifade de geri alındı
    hist = client.get("/api/db-console", headers=auth_headers).json()["history"]
    assert hist[0]["title"] == "hatalı" and hist[0]["ok"] is False


def test_risky_sql_needs_confirm_word(client, auth_headers, console_on):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE dbc_sil (id INTEGER)"))
    r = _run(client, auth_headers, "DROP TABLE dbc_sil", title="sil")
    assert r.status_code == 400 and "UYGULA" in r.json()["detail"]
    assert "dbc_sil" in _tables()
    # deneme onaysız çalışır (geri alınır)
    assert _run(client, auth_headers, "DROP TABLE dbc_sil", dry=True, title="sil").json()["ok"]
    assert "dbc_sil" in _tables()
    r = _run(client, auth_headers, "DROP TABLE dbc_sil", title="sil", confirm="UYGULA")
    assert r.status_code == 200 and r.json()["ok"]
    assert "dbc_sil" not in _tables()


def test_validation(client, auth_headers, console_on):
    assert _run(client, auth_headers, "   ").status_code == 400
    assert _run(client, auth_headers, "SELECT 1", title="").status_code == 400
    a = client.post("/api/db-console/analyze", headers=auth_headers, json={"sql": "UPDATE x SET a=1"}).json()
    assert a["warnings"] and a["confirm_word"] == "UYGULA"


def test_status_lists_pending_changes(client, auth_headers, console_on):
    d = client.get("/api/db-console", headers=auth_headers).json()
    assert d["enabled"] is True and d["dialect"] == "sqlite" and d["can_alter"] is True
    p = next(x for x in d["pending"] if x["key"] == "standard_name")
    assert p["column"] == "StandartAd" and p["script"].endswith("v3.9.39-standart-ad.sql")


# ---------- SQL çözümleme ----------
def test_warnings_ignore_comments_and_strings():
    w = db_console.warnings_for
    assert w("-- DROP TABLE x\nSELECT 'DROP TABLE y'") == []
    assert w("ALTER TABLE t ADD c INT") == []
    assert any("DROP" in x for x in w("ALTER TABLE t DROP COLUMN c"))
    assert any("TRUNCATE" in x for x in w("truncate table t"))
    assert any("DELETE" in x for x in w("DELETE FROM t"))
    assert w("DELETE FROM t WHERE id = 1") == []
    assert any("UPDATE" in x for x in w("UPDATE t SET a = 1"))
    assert w("UPDATE t SET a = 1 WHERE id = 2") == []


def test_split_batches_and_statements():
    assert db_console.split_batches("A\nGO\nB\n go \nC") == ["A", "B", "C"]
    assert db_console.split_statements("INSERT INTO t VALUES ('a;b'); -- x;y\nSELECT 1;") == [
        "INSERT INTO t VALUES ('a;b')", "-- x;y\nSELECT 1"]
