"""Mail Gönderim Geçmişi — uygulamanın gönderdiği HER mail türü geçmişte görünmeli (v3.9.36).

Eksikti:
- Değişiklik talebi hatırlatması: başarılı gönderim hiç kayıt bırakmıyordu (kuyruk açıksa yalnız
  'Kuyrukta' görünüp gönderilince kayboluyordu).
- SMTP test maili: hiç kayıt bırakmıyordu.
- Pasife alma: mail GİTMESE de (SMTP kapalı / alıcı yok / gönderim hatası) 'Gönderildi' görünüyordu.
"""

from app.db.models import MailQueue
from app.db.session import SessionLocal
from app.services import notifier
from tests.test_certificates_deactivate import _attach, _domain, _import_leaf, _sy_team
from tests.test_proposal_reminder import _capture, _pending_for_team, _run, _set_smtp


def _hist(client, h, **params):
    r = client.get("/api/notifications/history", headers=h, params={"channel": "email", **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _off(client, h):
    _set_smtp(client, h, enabled=False, queue_enabled=False, auto_proposal_reminder_enabled=False)


def test_proposal_reminder_direct_send_visible_in_history(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email="mh-prop@test", domain="mh-prop.test", cn="mh-prop.test")
    _set_smtp(client, h)
    _capture(monkeypatch)
    try:
        assert _run(force=True)["sent"] >= 1
        rows = [r for r in _hist(client, h, recipient="mh-prop@test")]
        assert len(rows) == 1
        r = rows[0]
        assert r["status"] == "sent" and r["mail_type"] == "proposal"
        assert r["stakeholder"] == "SY-mh-prop.test"
        f = client.get("/api/notifications/history/facets", headers=h,
                       params={"channel": "email", "recipient": "mh-prop@test"}).json()
        assert f["types"]["proposal"] == 1
    finally:
        _off(client, h)


def test_proposal_reminder_queued_then_sent_stays_in_history(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email="mh-propq@test", domain="mh-propq.test", cn="mh-propq.test")
    _set_smtp(client, h, queue_enabled=True)
    _capture(monkeypatch)
    try:
        _run(force=True)
        rows = _hist(client, h, recipient="mh-propq@test")
        assert [r["status"] for r in rows] == ["pending"], "kuyruktayken tek satır (mükerrer yok)"
        db = SessionLocal()
        try:
            notifier.drain_mail_queue(db)
        finally:
            db.close()
        rows = _hist(client, h, recipient="mh-propq@test")
        assert [r["status"] for r in rows] == ["sent"], "gönderildikten sonra geçmişten kaybolmamalı"
        assert rows[0]["mail_type"] == "proposal" and rows[0]["source"] == "notification"
        det = client.get(f"/api/notifications/history/notification/{rows[0]['id']}", headers=h).json()
        assert det["body_html"], "kuyruktan gönderilen hatırlatmanın içeriği detayda okunur"
    finally:
        _off(client, h)


def test_smtp_test_mail_visible_in_history(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h)
    _capture(monkeypatch)
    try:
        r = client.post("/api/settings/smtp/test", headers=h, json={"to": "mh-smtptest@test"})
        assert r.json()["success"] is True
        rows = _hist(client, h, recipient="mh-smtptest@test")
        assert len(rows) == 1 and rows[0]["status"] == "sent" and rows[0]["mail_type"] == "test"

        def boom(*a, **k):
            raise OSError("bağlantı reddedildi")
        monkeypatch.setattr(notifier, "_send_mail", boom)
        r = client.post("/api/settings/smtp/test", headers=h, json={"to": "mh-smtpfail@test"})
        assert r.json()["success"] is False
        rows = _hist(client, h, recipient="mh-smtpfail@test")
        assert len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["mail_type"] == "test"
        assert "bağlantı reddedildi" in rows[0]["error"]
    finally:
        _off(client, h)


def test_deactivation_mail_status_is_truthful(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "MH-Pasif", email="mh-pasif@test")

    def bound_leaf(cn):
        dom = _domain(client, h, cn, sy_team_id=tid)
        leaf = _import_leaf(client, h, cn)
        _attach(client, h, dom, leaf, "client")
        return leaf

    # 1) SMTP kapalı → kayıt var ama 'Başarısız' ve nedeni yazıyor
    _off(client, h)
    leaf = bound_leaf("mh-pasif-off.test")
    assert client.post(f"/api/certificates/{leaf}/deactivate", headers=h).json()["mail_sent"] is False
    rows = [r for r in _hist(client, h, record="mh-pasif-off.test") if r["mail_type"] == "deactivated"]
    assert len(rows) == 1 and rows[0]["status"] == "failed"
    assert "kapalı" in rows[0]["error"]

    # 2) SMTP açık, gönderim başarılı → 'Gönderildi'
    _set_smtp(client, h)
    _capture(monkeypatch)
    try:
        leaf = bound_leaf("mh-pasif-ok.test")
        assert client.post(f"/api/certificates/{leaf}/deactivate", headers=h).json()["mail_sent"] is True
        rows = [r for r in _hist(client, h, record="mh-pasif-ok.test") if r["mail_type"] == "deactivated"]
        assert len(rows) == 1 and rows[0]["status"] == "sent"

        # 3) SMTP açık, gönderim hatası → 'Başarısız' + yeniden denenebilir
        def boom(*a, **k):
            raise OSError("sunucu yok")
        monkeypatch.setattr(notifier, "_send_mail", boom)
        leaf = bound_leaf("mh-pasif-err.test")
        assert client.post(f"/api/certificates/{leaf}/deactivate", headers=h).json()["mail_sent"] is False
        rows = [r for r in _hist(client, h, record="mh-pasif-err.test") if r["mail_type"] == "deactivated"]
        assert len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["retryable"] is True
        assert "sunucu yok" in rows[0]["error"]
        db = SessionLocal()
        try:
            assert db.query(MailQueue).filter(MailQueue.certificate_id == leaf,
                                              MailQueue.status == "pending").count() == 0, \
                "başarısız satır kendiliğinden yeniden gönderilmemeli"
        finally:
            db.close()
    finally:
        _off(client, h)
