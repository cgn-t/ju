"""Mail Gönderim Geçmişi — GET /api/notifications/history (admin-only).

- notifications (gönderilenler) + mail_queue (pending|failed) BİRLEŞİK; queue 'sent' ATLANIR
  (zaten notifications'ta 'gönderildi' var → mükerrer olmasın).
- status / kanal / arama filtreleri; sertifika adı join.
- non-admin → 403.
- Doğrudan-gönderim başarısızlığı (queue kapalı) mail_queue'ya 'failed' yazar → geçmişte görünür.
"""

from datetime import datetime, timedelta

from app.db.models import Certificate, MailQueue, Notification
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _import_leaf(client, h, cn, *, days=30, nb_days_ago=20):
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=nb_days_ago)          # valid_to ~ now + (days - nb_days_ago)
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=nb, days=days, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _editor_token(client, h, username):
    client.post("/api/users", headers=h, json={"username": username, "password": "x",
                                               "role": "editor", "auth_source": "local"})
    return client.post("/api/auth/login-json",
                       json={"username": username, "password": "x"}).json()["access_token"]


def test_mail_history_merges_and_filters(client, auth_headers):
    h = auth_headers
    leaf_id = _import_leaf(client, h, "history-leaf.test")
    db = SessionLocal()
    try:
        db.add(Notification(certificate_id=leaf_id, recipient="sent-a@test",
                            subject="MHIST gönderildi A", days_left=10, channel="email"))
        db.add(MailQueue(to_addresses="failed-b@test", subject="MHIST başarısız B", body_text="x",
                         certificate_id=leaf_id, days_left=5, status="failed",
                         last_error="SMTP 550 reddedildi", attempts=5))
        db.add(MailQueue(to_addresses="pending-c@test", subject="MHIST kuyrukta C", body_text="x",
                         days_left=3, status="pending"))
        db.add(MailQueue(to_addresses="queued-sent-d@test", subject="MHIST queue-sent D",
                         body_text="x", days_left=1, status="sent", sent_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    rows = client.get("/api/notifications/history", headers=h,
                      params={"channel": "email", "search": "MHIST"}).json()
    by = {r["recipient"]: r for r in rows}
    assert "sent-a@test" in by and "failed-b@test" in by and "pending-c@test" in by
    assert "queued-sent-d@test" not in by, "queue 'sent' satırı gösterilmemeli (mükerrer)"

    assert by["sent-a@test"]["status"] == "sent"
    assert by["sent-a@test"]["source"] == "notification"
    assert by["sent-a@test"]["certificate_name"] == "history-leaf.test"
    assert by["failed-b@test"]["status"] == "failed"
    assert by["failed-b@test"]["source"] == "queue"
    assert by["failed-b@test"]["error"] == "SMTP 550 reddedildi"
    assert by["failed-b@test"]["certificate_name"] == "history-leaf.test"
    assert by["pending-c@test"]["status"] == "pending"

    # status filtresi: yalnız başarısız
    failed = client.get("/api/notifications/history", headers=h,
                        params={"status": "failed", "search": "MHIST"}).json()
    assert {r["recipient"] for r in failed} == {"failed-b@test"}


def test_mail_history_admin_only(client, auth_headers):
    tok = _editor_token(client, auth_headers, "mailhist_editor")
    r = client.get("/api/notifications/history", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


def test_direct_send_failure_recorded(client, auth_headers, monkeypatch):
    h = auth_headers
    # E-postalı SY ekip + creator'ı ona bağlı bir cert → tek net paydaş
    client.post("/api/teams", headers=h,
                json={"name": "MailFail SY", "type": "SY", "email": "fail-sy@test"})
    leaf_id = _import_leaf(client, h, "mailfail-leaf.test")       # valid_to ~ now+10 (30g pencere içinde)
    db = SessionLocal()
    try:
        db.get(Certificate, leaf_id).creator = "MailFail SY"
        db.commit()
    finally:
        db.close()

    # SMTP açık, kuyruk KAPALI (doğrudan gönderim), gönderim HATA fırlatır
    assert client.put("/api/settings/smtp", headers=h, json={
        "enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
        "expiry_warning_days": 30, "queue_enabled": False, "fallback_address": ""}).status_code == 200
    monkeypatch.setattr(notifier, "_send_mail",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SMTP bağlanamadı")))

    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()

    # doğrudan gönderim başarısızlığı mail_queue'ya 'failed' yazmalı
    db = SessionLocal()
    try:
        row = (db.query(MailQueue)
               .filter(MailQueue.status == "failed", MailQueue.to_addresses.like("%fail-sy@test%"))
               .first())
        assert row is not None, "doğrudan gönderim başarısızlığı 'failed' olarak kaydedilmeli"
        assert row.last_error
    finally:
        db.close()

    # ve geçmişte görünür
    failed = client.get("/api/notifications/history", headers=h, params={"status": "failed"}).json()
    assert any("fail-sy@test" in (r["recipient"] or "") for r in failed)
