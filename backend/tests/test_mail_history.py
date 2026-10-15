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
                      params={"channel": "email", "search": "MHIST"}).json()["items"]
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
                        params={"status": "failed", "search": "MHIST"}).json()["items"]
    assert {r["recipient"] for r in failed} == {"failed-b@test"}


def test_mail_history_queued_notification_reflects_real_queue_status(client, auth_headers):
    """notifications.mail_queue_id ile bağlı bir satır, kendi sabit 'sent' değeri yerine
    ilişkili mail_queue satırının GERÇEK durumunu/zamanını göstermeli — kuyruğa girip
    SONRADAN gerçekten başarısız olan bir mail artık 'Gönderildi' görünmemeli."""
    h = auth_headers
    db = SessionLocal()
    try:
        mq = MailQueue(to_addresses="linked-failed@test", subject="MHIST linked failed",
                       body_text="gövde", days_left=4, status="failed",
                       last_error="SMTP 550 5.1.1", attempts=5)
        db.add(mq)
        db.commit()
        n = Notification(recipient="linked-failed@test", subject="MHIST linked failed",
                         days_left=4, channel="email", mail_queue_id=mq.id)
        db.add(n)
        db.commit()
    finally:
        db.close()

    rows = client.get("/api/notifications/history", headers=h,
                      params={"search": "MHIST linked failed"}).json()["items"]
    assert len(rows) == 1, "bağlı mail_queue satırı AYRICA (mükerrer) gösterilmemeli"
    row = rows[0]
    assert row["source"] == "notification"
    assert row["status"] == "failed", "sabit 'sent' değil, GERÇEK kuyruk durumu gösterilmeli"
    assert row["error"] == "SMTP 550 5.1.1"
    assert row["attempts"] == 5
    assert row["delivered_at"] is None, "hiç teslim edilmediyse delivered_at boş olmalı"
    assert row["queued_at"] is not None

    # status=failed filtresi artık bu (notification kaynaklı) satırı da bulmalı
    failed = client.get("/api/notifications/history", headers=h,
                        params={"status": "failed", "search": "MHIST linked failed"}).json()["items"]
    assert len(failed) == 1
    # status=sent filtresi ARTIK bu satırı GETİRMEMELİ (gerçek durumu failed)
    sent = client.get("/api/notifications/history", headers=h,
                      params={"status": "sent", "search": "MHIST linked failed"}).json()["items"]
    assert sent == []


def test_mail_history_detail_linked_notification_shows_queue_body(client, auth_headers):
    h = auth_headers
    db = SessionLocal()
    try:
        mq = MailQueue(to_addresses="linked-pending@test", subject="MHIST linked pending",
                       body_text="düz metin", body_html="<p>html</p>", days_left=2, status="pending")
        db.add(mq)
        db.commit()
        n = Notification(recipient="linked-pending@test", subject="MHIST linked pending",
                         days_left=2, channel="email", mail_queue_id=mq.id)
        db.add(n)
        db.commit()
        nid = n.id
    finally:
        db.close()

    r = client.get(f"/api/notifications/history/notification/{nid}", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "pending"
    assert d["body_text"] == "düz metin"
    assert d["body_html"] == "<p>html</p>"
    assert d["delivered_at"] is None
    assert d["queued_at"] is not None


def test_mail_history_queued_notification_delivered(client, auth_headers):
    """Kuyruğa girip GERÇEKTEN teslim edilmiş (drain job status='sent' yazmış) bir mail:
    delivered_at dolu, status='sent', tek satır (mükerrer yok)."""
    h = auth_headers
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        mq = MailQueue(to_addresses="linked-sent@test", subject="MHIST linked sent",
                       body_text="x", days_left=1, status="sent", sent_at=now)
        db.add(mq)
        db.commit()
        n = Notification(recipient="linked-sent@test", subject="MHIST linked sent",
                         days_left=1, channel="email", mail_queue_id=mq.id)
        db.add(n)
        db.commit()
    finally:
        db.close()

    rows = client.get("/api/notifications/history", headers=h,
                      params={"search": "MHIST linked sent"}).json()["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["delivered_at"] is not None


def test_mail_history_detail_queue_has_body(client, auth_headers):
    """queue kaynaklı kayıtta body_text/body_html DOLU döner (kuyrukta saklanır)."""
    h = auth_headers
    db = SessionLocal()
    try:
        q = MailQueue(to_addresses="detail-queue@test", subject="MHIST detay queue",
                      body_text="düz metin gövde", body_html="<p>html gövde</p>",
                      days_left=5, status="failed", last_error="SMTP 550", attempts=2)
        db.add(q)
        db.commit()
        qid = q.id
    finally:
        db.close()

    r = client.get(f"/api/notifications/history/queue/{qid}", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["body_text"] == "düz metin gövde"
    assert d["body_html"] == "<p>html gövde</p>"
    assert d["recipient"] == "detail-queue@test"
    assert d["status"] == "failed"


def test_mail_history_detail_notification_has_no_body(client, auth_headers):
    """notification kaynaklı kayıtta body_text/body_html hep None döner (gövde saklanmaz)."""
    h = auth_headers
    leaf_id = _import_leaf(client, h, "detail-notif-leaf.test")
    db = SessionLocal()
    try:
        n = Notification(certificate_id=leaf_id, recipient="detail-notif@test",
                         subject="MHIST detay notif", days_left=7, channel="email")
        db.add(n)
        db.commit()
        nid = n.id
    finally:
        db.close()

    r = client.get(f"/api/notifications/history/notification/{nid}", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["body_text"] is None and d["body_html"] is None
    assert d["certificate_name"] == "detail-notif-leaf.test"
    assert d["status"] == "sent"


def test_mail_history_detail_not_found_and_invalid_source(client, auth_headers):
    h = auth_headers
    assert client.get("/api/notifications/history/queue/999999", headers=h).status_code == 404
    assert client.get("/api/notifications/history/bogus/1", headers=h).status_code == 400


def test_mail_history_detail_admin_only(client, auth_headers):
    tok = _editor_token(client, auth_headers, "mailhist_detail_editor")
    r = client.get("/api/notifications/history/queue/1",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


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
    failed = client.get("/api/notifications/history", headers=h, params={"status": "failed"}).json()["items"]
    assert any("fail-sy@test" in (r["recipient"] or "") for r in failed)


# ---- Kullanılabilirlik yenilemesi: sınır/durum, tür, sayaçlar, yeniden kuyruğa alma, zaman ----

def _hist(client, h, **params):
    r = client.get("/api/notifications/history", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_status_filter_applies_before_limit(client, auth_headers):
    """Eskiden durum filtresi limitten SONRA Python'da uygulanıyordu → yeni bildirimler sınırı
    doldurunca daha eski bir başarısız mail hiç görünmüyordu."""
    db = SessionLocal()
    try:
        old_q = MailQueue(to_addresses="mhx-old@test", subject="MHX eski başarısız", body_text="x",
                          status="failed", last_error="SMTP 550", attempts=5,
                          created_at=datetime.utcnow() - timedelta(days=3))
        db.add(old_q)
        db.flush()
        db.add(Notification(recipient="mhx-old@test", subject="MHX eski başarısız", channel="email",
                            mail_queue_id=old_q.id, sent_at=datetime.utcnow() - timedelta(days=3)))
        for i in range(3):
            db.add(Notification(recipient=f"mhx-new{i}@test", subject=f"MHX yeni {i}", channel="email"))
        db.commit()
    finally:
        db.close()
    got = _hist(client, auth_headers, status="failed", q="MHX", limit=1)
    assert [r["recipient"] for r in got["items"]] == ["mhx-old@test"]
    assert got["items"][0]["status"] == "failed"
    allr = _hist(client, auth_headers, q="MHX", limit=2)
    assert len(allr["items"]) == 2 and allr["capped"] is True


def test_mail_type_classification_filter_and_facets(client, auth_headers):
    h = auth_headers
    db = SessionLocal()
    try:
        db.add(Notification(recipient="t1@test", channel="email",
                            subject="[JUMBO] Sertifika süresi doluyor: mht.test (10 gün kaldı) → Sertifika sahibi"))
        db.add(Notification(recipient="t2@test", channel="email",
                            subject="[JUMBO] SÜRESİ GEÇMİŞ sertifika: mht.test (-2 gün)"))
        db.add(Notification(recipient="t3@test, t4@test", channel="email",
                            subject="[JUMBO] Onayınızı bekleyen 2 devir önerisi"))
        db.commit()
    finally:
        db.close()
    rows = _hist(client, h, q="t", recipient="@test", subject="[JUMBO]")["items"]
    by = {r["recipient"]: r for r in rows if r["recipient"] in ("t1@test", "t2@test", "t3@test, t4@test")}
    assert by["t1@test"]["mail_type"] == "expiry" and by["t1@test"]["stakeholder"] == "Sertifika sahibi"
    assert by["t2@test"]["mail_type"] == "expired"
    assert by["t3@test, t4@test"]["mail_type"] == "proposal"
    assert by["t3@test, t4@test"]["recipients"] == ["t3@test", "t4@test"]
    expired_only = _hist(client, h, mail_type="expired", subject="mht.test")["items"]
    assert [r["recipient"] for r in expired_only] == ["t2@test"]
    f = client.get("/api/notifications/history/facets", headers=h, params={"subject": "mht.test"}).json()
    assert f["types"]["expiry"] == 1 and f["types"]["expired"] == 1
    assert f["statuses"]["sent"] == 2 and f["total"] == 2


def test_retry_failed_mail(client, auth_headers):
    h = auth_headers
    db = SessionLocal()
    try:
        ok = MailQueue(to_addresses="retry-me@test", subject="MHR tekrar", body_text="x",
                       status="failed", last_error="SMTP 451", attempts=5)
        unknown = MailQueue(to_addresses="(bilinmiyor — mail hiç denenemedi)", subject="MHR hata",
                            body_text="x", status="failed", last_error="KeyError", attempts=1)
        db.add_all([ok, unknown])
        db.commit()
        ok_id, unknown_id = ok.id, unknown.id
    finally:
        db.close()
    rows = {r["id"]: r for r in _hist(client, h, q="MHR")["items"] if r["source"] == "queue"}
    assert rows[ok_id]["retryable"] is True and rows[unknown_id]["retryable"] is False
    r = client.post(f"/api/notifications/history/queue/{ok_id}/retry", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    db = SessionLocal()
    try:
        q = db.get(MailQueue, ok_id)
        assert q.status == "pending" and q.attempts == 0 and q.last_error is None
    finally:
        db.close()
    assert client.post(f"/api/notifications/history/queue/{unknown_id}/retry", headers=h).status_code == 409
    assert client.post(f"/api/notifications/history/queue/{ok_id}/retry", headers=h).status_code == 409  # artık pending
    audit = client.get("/api/audit", headers=h, params={"action": "mail_retry"}).json()["items"]
    assert any(e["record_id"] == str(ok_id) for e in audit)


def test_time_window_filters(client, auth_headers):
    db = SessionLocal()
    try:
        db.add(Notification(recipient="mhw-old@test", subject="MHW", channel="email",
                            sent_at=datetime.utcnow() - timedelta(hours=30)))
        db.add(Notification(recipient="mhw-new@test", subject="MHW", channel="email"))
        db.commit()
    finally:
        db.close()
    recent = {r["recipient"] for r in _hist(client, auth_headers, subject="MHW", since_hours=24)["items"]}
    assert recent == {"mhw-new@test"}
    both = {r["recipient"] for r in _hist(client, auth_headers, subject="MHW", since_hours=48)["items"]}
    assert both == {"mhw-old@test", "mhw-new@test"}

