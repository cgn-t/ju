"""Regresyon Testi > Test mail kutusu (v3.9.29): açıkken Jumbo'nun mailleri sunucuya GİTMEZ,
Test Hazırlığı sekmesinde toplanır; kapalıyken ya da REGRESSION_TOOLS yokken gerçek yol çalışır."""

import smtplib
from datetime import datetime, timedelta

import pytest

from app.core.config import get_settings
from app.db.models import Certificate
from app.db.session import SessionLocal
from app.services import notifier, regression
from app.services.settings_service import get_category
from tests import certgen


@pytest.fixture
def lab_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "regression_tools", True)
    yield


@pytest.fixture
def no_smtp(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("Test mail kutusu açıkken SMTP sunucusuna bağlanılmamalı")
    monkeypatch.setattr(smtplib, "SMTP", boom)
    monkeypatch.setattr(smtplib, "SMTP_SSL", boom)
    return calls


def _smtp(client, h, **over):
    cfg = {"enabled": True, "host": "", "from_address": "", "expiry_warning_days": 30,
           "resend_interval_hours": 3, "auto_expiry_enabled": True, "queue_enabled": False,
           "fallback_address": "yedek@test.local", "resend_dedup_enabled": True}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def test_capture_collects_mails_without_server(client, auth_headers, lab_on, no_smtp):
    h = auth_headers
    client.post("/api/regression/lab/data", headers=h, json={"emails": {"a": "odeme@test.local"}})
    _smtp(client, h)   # sunucu adı bile boş
    client.delete("/api/regression/lab/mails", headers=h)
    r = client.post("/api/regression/lab/mail/capture", headers=h, json={"on": True})
    assert r.status_code == 200 and r.json()["mail"]["capture"] is True

    # Ayarlar ekranı yer tutucu sunucu adını görmez (kaydederken gerçek ayar bozulmasın)
    assert client.get("/api/settings/smtp", headers=h).json().get("host") in ("", None)

    # Süresi yaklaşan sertifika, Oluşturan Ekip = Ödeme Sistemleri SY (A)
    ca, ca_key = certgen.make_ca("Kutu CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "kutu.jumbo-test.local", not_before=datetime.utcnow() - timedelta(days=10),
                                days=30, san=["kutu.jumbo-test.local"])
    r = client.post("/api/certificates/import", headers=h, files={"file": (
        "c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(), "application/x-pem-file")})
    cid = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    db = SessionLocal()
    db.get(Certificate, cid).creator = "Ödeme Sistemleri SY"
    db.commit()
    res = notifier.send_expiry_notifications(db, force=True)
    db.close()
    assert res.get("sent", 0) >= 1, res

    # Test Maili Gönder de kutuya düşer
    r = client.post("/api/settings/smtp/test", headers=h, json={"to": "kendim@test.local"})
    assert r.json()["success"] is True, r.text

    mails = client.get("/api/regression/lab/mails", headers=h).json()
    assert not no_smtp
    to = {t["address"]: t["label"] for m in mails for t in m["to"]}
    assert to.get("odeme@test.local") == "A · Ödeme Sistemleri SY"
    assert "kendim@test.local" in to
    one = next(m for m in mails if any(t["address"] == "odeme@test.local" for t in m["to"]))
    assert "kutu.jumbo-test.local" in one["subject"]
    full = client.get(f"/api/regression/lab/mails/{one['id']}", headers=h).json()
    assert full["html"] and "kutu.jumbo-test.local" in full["body"]

    # Otomatik kontrol sunucuya bağlanmaz, kutunun açık olduğunu söyler
    db = SessionLocal()
    st, msg = regression._smtp(db)
    db.close()
    assert st == "warn" and "Test mail kutusu" in msg

    # Boşalt
    assert client.delete("/api/regression/lab/mails", headers=h).json()["deleted"] == len(mails)
    assert client.get("/api/regression/lab/mails", headers=h).json() == []
    client.post("/api/regression/lab/mail/capture", headers=h, json={"on": False})


def test_capture_off_or_tools_off_uses_real_server(client, auth_headers, lab_on, monkeypatch):
    h = auth_headers
    client.post("/api/regression/lab/mail/capture", headers=h, json={"on": True})
    db = SessionLocal()
    assert get_category(db, "smtp", mask_secrets=False).get("_capture") is True
    monkeypatch.setattr(get_settings(), "regression_tools", False)   # canlı: değişken yok
    assert not get_category(db, "smtp", mask_secrets=False).get("_capture")
    monkeypatch.setattr(get_settings(), "regression_tools", True)
    client.post("/api/regression/lab/mail/capture", headers=h, json={"on": False})
    assert not get_category(db, "smtp", mask_secrets=False).get("_capture")
    db.close()


def test_cleanup_empties_box_and_turns_it_off(client, auth_headers, lab_on, no_smtp):
    h = auth_headers
    _smtp(client, h)
    client.post("/api/regression/lab/mail/capture", headers=h, json={"on": True})
    client.post("/api/settings/smtp/test", headers=h, json={"to": "x@test.local"})
    assert client.get("/api/regression/lab/cleanup", headers=h).json()["mails"] >= 1
    client.post("/api/regression/lab/cleanup", headers=h)
    st = client.get("/api/regression/lab", headers=h).json()["mail"]
    assert st == {"capture": False, "count": 0}


def test_mailbox_admin_only_and_hidden_when_off(client, auth_headers):
    assert client.get("/api/regression/lab/mails", headers=auth_headers).status_code == 404
    client.post("/api/users", headers=auth_headers, json={
        "username": "kutu_editor", "password": "x", "role": "editor", "auth_source": "local"})
    tok = client.post("/api/auth/login-json", json={"username": "kutu_editor", "password": "x"}).json()["access_token"]
    assert client.get("/api/regression/lab/mails", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
