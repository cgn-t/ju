"""Audit Log: eski→yeni değer kaydı, sır maskeleme, silme anlık görüntüsü, eksik işlemlerin
kaydı (onay, canlı doğrulama, başarısız giriş, test, zamanlanmış iş özeti), kategori ve kolon
filtreleri, 1000 sınırı ve CSV dışa aktarma."""

import csv
import io
import json
from datetime import date, datetime, timedelta

from app.core.timeutil import ISTANBUL
from app.db.models import AuditLog
from app.db.session import SessionLocal
from app.services.audit import MASK, audited_job, category_of, diff_fields, diff_dicts
from tests import certgen


def _audit(client, h, **params):
    r = client.get("/api/audit", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _latest(client, h, **params):
    items = _audit(client, h, **params)["items"]
    assert items, f"kayıt yok: {params}"
    return items[0]


# ---- Saf yardımcılar ----

class _Obj:
    name = "eski"
    notify_days = 30
    info = None
    bind_password = "gizli"


def test_diff_fields_only_changed_and_masks_secrets():
    d = diff_fields(_Obj(), {"name": "eski", "notify_days": 15, "info": "", "bind_password": "yeni"})
    assert "name" not in d                       # değişmeyen alan yazılmaz
    assert "info" not in d                       # None ile "" aynı sayılır (form boş alanı)
    assert d["notify_days"] == {"old": 30, "new": 15}
    assert d["bind_password"] == {"old": MASK, "new": MASK, "masked": True}
    assert "gizli" not in json.dumps(d) and "yeni" not in json.dumps(d)


def test_diff_dicts_masks_explicit_secret_keys():
    d = diff_dicts({"webhook_url": "https://a", "host": "x"},
                   {"webhook_url": "https://b", "host": "y"}, secret_keys={"webhook_url"})
    assert d["webhook_url"]["masked"] is True and "https://" not in json.dumps(d)
    assert d["host"] == {"old": "x", "new": "y"}


def test_category_of_rules():
    assert category_of("update", "domains", "ahmet") == "changes"
    assert category_of("approve", "transfer_proposals", "ahmet") == "approval"
    assert category_of("login_failed", "users", "x") == "security"
    assert category_of("update", "app_settings", "admin") == "security"
    assert category_of("job_summary", "jobs", "system") == "system"
    assert category_of("propose", "transfer_proposals", "system") == "system"   # otomatik öneri
    assert category_of("create", "certificates", "system") == "system"


# ---- Güncelleme / silme ----

def test_domain_update_records_old_and_new_with_label(client, auth_headers):
    h = auth_headers
    r = client.post("/api/domains", headers=h, json={"domain": "audit-upd.test", "notify_days": 30})
    did = r.json()["id"]
    assert client.put(f"/api/domains/{did}", headers=h,
                      json={"notify_days": 15, "cert_owner": "Ayşe"}).status_code == 200
    e = _latest(client, h, action="update", table_name="domains", record_id=str(did))
    details = json.loads(e["details"])
    assert details["changes"]["notify_days"] == {"old": 30, "new": 15}
    assert details["changes"]["cert_owner"] == {"old": None, "new": "Ayşe"}
    assert "Bildirim günü: 30 → 15" in e["summary"]
    assert e["record_label"] == "audit-upd.test"
    assert e["category"] == "changes"


def test_domain_delete_keeps_snapshot(client, auth_headers):
    h = auth_headers
    did = client.post("/api/domains", headers=h,
                      json={"domain": "audit-del.test", "cert_owner": "Mehmet"}).json()["id"]
    assert client.delete(f"/api/domains/{did}", headers=h).status_code == 200
    e = _latest(client, h, action="delete", table_name="domains", record_id=str(did))
    details = json.loads(e["details"])
    assert details["snapshot"]["domain"] == "audit-del.test"
    assert details["snapshot"]["cert_owner"] == "Mehmet"
    assert e["summary"] == "Silinen: audit-del.test"
    assert e["record_label"] == "audit-del.test"     # kayıt silinse de ad görünür


def test_settings_update_diff_masks_secret(client, auth_headers):
    h = auth_headers
    r = client.put("/api/settings/smtp", headers=h,
                   json={"host": "mail-audit.local", "password": "CokGizli123"})
    assert r.status_code == 200
    e = _latest(client, h, action="update", table_name="app_settings", record_id="smtp")
    assert "CokGizli123" not in e["details"]
    ch = json.loads(e["details"])["changes"]
    assert ch["host"]["new"] == "mail-audit.local"
    assert e["category"] == "security"
    # Maskeli yer tutucu geri gönderilirse değişiklik sayılmaz
    client.put("/api/settings/smtp", headers=h, json={"password": "********"})
    e2 = _latest(client, h, action="update", table_name="app_settings", record_id="smtp")
    assert "password" not in json.loads(e2["details"])["changes"]


def test_user_update_diff_and_password_masked(client, auth_headers):
    h = auth_headers
    uid = client.post("/api/users", headers=h, json={
        "username": "audit-u1", "password": "Ilk12345!", "email": "a@t", "role": "viewer"}).json()["id"]
    assert client.put(f"/api/users/{uid}", headers=h,
                      json={"full_name": "Audit Kişi", "password": "Yeni12345!"}).status_code == 200
    e = _latest(client, h, action="update", table_name="users", record_id=str(uid))
    ch = json.loads(e["details"])["changes"]
    assert ch["full_name"] == {"old": None, "new": "Audit Kişi"}
    assert ch["password"]["masked"] is True
    assert "Yeni12345!" not in e["details"]


# ---- Daha önce kaydedilmeyen işlemler ----

def test_failed_login_is_recorded_without_password(client, auth_headers):
    r = client.post("/api/auth/login-json", json={"username": "admin", "password": "YanlisSifre!"})
    assert r.status_code == 401
    r = client.post("/api/auth/login-json", json={"username": "kimse-yok-xyz", "password": "p"})
    assert r.status_code == 401
    items = _audit(client, auth_headers, action="login_failed")["items"]
    by_user = {e["username"]: e for e in items}
    assert json.loads(by_user["admin"]["details"])["reason"] == "Hatalı şifre"
    assert json.loads(by_user["kimse-yok-xyz"]["details"])["reason"] == "Bilinmeyen kullanıcı"
    assert all("YanlisSifre" not in (e["details"] or "") for e in items)
    assert by_user["admin"]["category"] == "security"


def test_approve_is_recorded_with_context(client, auth_headers):
    h = auth_headers
    ca, ca_key = certgen.make_ca("Audit Approve CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "audit-approve.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "audit-approve.test", key=key, not_before=datetime(2026, 6, 1))

    def imp(pem, supersede=False):
        r = client.post("/api/certificates/import", headers=h,
                        files={"file": ("c.pem", pem.encode(), "application/x-pem-file")},
                        data={"supersede": "true"} if supersede else {})
        return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    v1_id = imp(certgen.pem(v1) + certgen.pem(ca))
    did = client.post("/api/domains", headers=h, json={"domain": "audit-approve-dom.test"}).json()["id"]
    client.post(f"/api/domains/{did}/certificates", headers=h,
                json={"certificate_id": v1_id, "mapping_type": "server"})
    v2_id = imp(certgen.pem(v2))
    # İçe aktarma artık öneri üretmez — devir bilinçli elle başlatılır
    assert client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=h).status_code == 200
    prop = next(p for p in client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
                if p["new_cert_id"] == v2_id and p["domain_id"] == did)
    r = client.post(f"/api/proposals/{prop['id']}/approve", headers=h, json={"note": "planlı yenileme"})
    assert r.status_code == 200, r.text
    e = _latest(client, h, action="approve", record_id=str(prop["id"]))
    d = json.loads(e["details"])
    assert d["domain"] == "audit-approve-dom.test" and d["note"] == "planlı yenileme"
    assert e["category"] == "approval"
    assert "audit-approve.test → audit-approve.test" in e["summary"]
    # Öneri oluşturma kaydı hangi domain(ler) için açıldığını gösterir
    p = _latest(client, h, action="propose", record_id=str(v2_id))
    assert "audit-approve-dom.test" in json.loads(p["details"])["domains"]


def test_manual_live_check_is_recorded(client, auth_headers):
    h = auth_headers
    did = client.post("/api/domains", headers=h, json={"domain": "127.0.0.1:1"}).json()["id"]
    assert client.post(f"/api/domains/{did}/live-check", headers=h).status_code == 200
    e = _latest(client, h, action="live_check_run", record_id=str(did))
    assert json.loads(e["details"])["status"] == "unreachable"


def test_connection_test_is_recorded(client, auth_headers):
    r = client.post("/api/settings/ldap/test", headers=auth_headers)
    assert r.status_code == 200
    e = _latest(client, auth_headers, action="test")
    d = json.loads(e["details"])
    assert d["target"] == "ldap" and d["success"] == r.json()["success"]
    assert e["category"] == "system"


def test_audited_job_writes_one_summary_and_skips_disabled(client):
    @audited_job("Deneme işi")
    def job_ok():
        return {"status": "ok", "total": 7}

    @audited_job("Kapalı iş")
    def job_skipped():
        return {"status": "skipped"}

    job_ok()
    job_skipped()
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.action == "job_summary").all()
        jobs = [json.loads(r.details)["job"] for r in rows]
        assert jobs.count("Deneme işi") == 1
        assert "Kapalı iş" not in jobs
        ok = next(r for r in rows if json.loads(r.details)["job"] == "Deneme işi")
        assert ok.username == "system" and json.loads(ok.details)["total"] == 7
        assert "duration_s" in json.loads(ok.details)
    finally:
        db.close()


# ---- Sorgu: filtreler, sınır, facets, export ----

def test_category_filter(client, auth_headers):
    sec = _audit(client, auth_headers, category="security")["items"]
    assert sec and all(e["category"] == "security" for e in sec)
    ch = _audit(client, auth_headers, category="changes")["items"]
    assert ch and all(e["category"] == "changes" for e in ch)
    sysi = _audit(client, auth_headers, category="system")["items"]
    assert all(e["category"] == "system" for e in sysi)


def test_limit_applies_after_filter_and_reports_capped(client, auth_headers):
    r = _audit(client, auth_headers, limit=1)
    assert len(r["items"]) == 1 and r["capped"] is True
    # Sınır filtreden SONRA: en yeni kayıt başka bir işlem olsa da filtre doğru kaydı bulur
    r = _audit(client, auth_headers, action="login_failed", limit=1)
    assert r["items"][0]["action"] == "login_failed"
    # Çoklu değer (virgül)
    acts = {e["action"] for e in _audit(client, auth_headers, action="login,login_failed")["items"]}
    assert acts <= {"login", "login_failed"} and acts
    assert client.get("/api/audit", headers=auth_headers, params={"limit": 1001}).status_code == 422


def test_text_and_ip_filters(client, auth_headers):
    items = _audit(client, auth_headers, q="audit-upd.test")["items"]
    assert items and all("audit-upd.test" in (e["details"] or "") + (e["record_id"] or "") + e["username"]
                         for e in items)
    assert _audit(client, auth_headers, ip="testclient")["items"]          # TestClient IP'si
    assert _audit(client, auth_headers, ip="10.99.99.99")["items"] == []
    # Kayıt kolonu: ada göre (detayda geçen) — Değişiklik kolonu: yalnız detay
    rec = _audit(client, auth_headers, record="audit-upd.test", table_name="domains")["items"]
    assert rec and {e["record_label"] for e in rec} == {"audit-upd.test"}
    assert _audit(client, auth_headers, details="Ayşe", action="update")["items"]


def test_facets(client, auth_headers):
    f = client.get("/api/audit/facets", headers=auth_headers).json()
    assert {"changes", "approval", "security", "system"} == set(f["categories"])
    assert f["total"] == sum(f["categories"].values())
    assert any(a["value"] == "login_failed" for a in f["actions"])
    assert any(u["value"] == "admin" for u in f["users"])


def test_meta_labels(client, auth_headers):
    m = client.get("/api/audit/meta", headers=auth_headers).json()
    assert m["actions"]["login_failed"] == "Başarısız giriş"
    assert m["categories"]["approval"] == "Onay & Değişiklik"
    assert m["fields"]["notify_days"] == "Bildirim günü"


def test_export_uses_same_filters_and_readable_columns(client, auth_headers):
    # Filtre günü İstanbul takvimine göre yorumlar (bkz. timeutil.ist_day_start_utc); UTC
    # date.today() İstanbul'da 00:00-03:00 arası "dün"e düşer ve kayıtlar boş gelirdi.
    today = datetime.now(ISTANBUL).date().isoformat()
    r = client.get("/api/audit/export", headers=auth_headers,
                   params={"action": "login_failed", "date_from": today, "date_to": today})
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0][0] == "Tarih (İstanbul)" and "Değişiklik" in rows[0]
    body = rows[1:]
    assert body and all(row[4] == "Başarısız giriş" for row in body)
    assert all(row[3] == "Güvenlik" for row in body)


def test_since_hours_rolling_window(client, auth_headers):
    db = SessionLocal()
    try:
        db.add(AuditLog(username="eski-kayit", action="update", table_name="domains", record_id="",
                        created_at=datetime.utcnow() - timedelta(hours=30)))
        db.commit()
    finally:
        db.close()
    recent = _audit(client, auth_headers, since_hours=24)["items"]
    assert recent and all(e["username"] != "eski-kayit" for e in recent)
    assert any(e["username"] == "eski-kayit" for e in _audit(client, auth_headers, since_hours=48)["items"])
    f = client.get("/api/audit/facets", headers=auth_headers, params={"since_hours": 24}).json()
    assert all(u["value"] != "eski-kayit" for u in f["users"])
    assert client.get("/api/audit", headers=auth_headers, params={"since_hours": 0}).status_code == 422


def test_get_single_entry(client, auth_headers):
    e = _latest(client, auth_headers)
    r = client.get(f"/api/audit/{e['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["id"] == e["id"] and r.json()["category"]
    assert client.get("/api/audit/999999999", headers=auth_headers).status_code == 404
    assert client.get("/api/audit/meta", headers=auth_headers).status_code == 200   # rota çakışmaz


def test_absolute_datetime_range_is_istanbul_local(client, auth_headers):
    db = SessionLocal()
    try:   # DB naive-UTC 09:30 → İstanbul 12:30
        db.add(AuditLog(username="aralik-testi", action="update", table_name="domains", record_id="",
                        created_at=datetime(2026, 3, 10, 9, 30)))
        db.commit()
    finally:
        db.close()

    def count(start, end):
        return len(_audit(client, auth_headers, start=start, end=end, username="aralik-testi")["items"])
    assert count("2026-03-10T12:00", "2026-03-10T13:00") == 1   # İstanbul 12:30 aralıkta
    assert count("2026-03-10T09:00", "2026-03-10T10:00") == 0   # UTC saatiyle aranmaz
    assert count("2026-03-10T12:31", "2026-03-10T13:00") == 0
    f = client.get("/api/audit/facets", headers=auth_headers,
                   params={"start": "2026-03-10T12:00", "end": "2026-03-10T13:00"}).json()
    assert any(u["value"] == "aralik-testi" for u in f["users"])


def test_audit_endpoints_require_admin(client):
    for path in ("/api/audit", "/api/audit/facets", "/api/audit/meta", "/api/audit/export", "/api/audit/1"):
        assert client.get(path).status_code == 401


def test_audit_action_names_fit_prod_column():
    """Prod MSSQL AuditLog.Action NVARCHAR(20): daha uzun eylem adı INSERT'te hata verir ve işlemi
    500'e düşürür (SQLite uzunluğu zorlamadığından testlerde görünmez). Koddaki tüm sabit eylem
    adları kolona sığmalı."""
    import ast
    from pathlib import Path

    limit = AuditLog.__table__.c.Action.type.length
    app_dir = Path(__file__).resolve().parents[1] / "app"
    too_long = []
    for path in app_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            idx = {"log_action": 2, "log_standalone": 1}.get(name)
            if idx is None or len(node.args) <= idx:
                continue
            arg = node.args[idx]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and len(arg.value) > limit:
                too_long.append(f"{path.name}:{node.lineno} {arg.value!r}")
    assert not too_long, f"AuditLog.Action ({limit}) sınırını aşan eylem adları: {too_long}"
