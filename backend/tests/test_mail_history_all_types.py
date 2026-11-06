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


# --- v3.9.36 ek: yedek adres durumları -------------------------------------------------------

def _fallback_only_sender(monkeypatch, fail_addr):
    """fail_addr'a gönderim hata verir, diğerleri (yedek adres) başarılı."""
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        if fail_addr in to:
            raise OSError("550 alıcı yok")
        sent.append({"to": list(to), "subject": subject, "body": body})
        return {}
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


def test_fallback_delivery_is_visible(client, auth_headers, monkeypatch):
    """Asıl alıcıya gidemeyip yedek adrese giden mail 'Gönderildi' + açıklama notuyla görünür."""
    h = auth_headers
    _pending_for_team(client, h, team_email="mh-fbprim@test", domain="mh-fb.test", cn="mh-fb.test")
    _set_smtp(client, h, fallback_address="mh-yedek@test")
    sent = _fallback_only_sender(monkeypatch, "mh-fbprim@test")
    try:
        _run(force=True)
        assert any("mh-yedek@test" in m["to"] for m in sent)
        rows = _hist(client, h, recipient="mh-fbprim@test")
        assert len(rows) == 1 and rows[0]["status"] == "sent"
        assert "yedek adrese gönderildi" in rows[0]["error"] and "mh-yedek@test" in rows[0]["error"]
        det = client.get(f"/api/notifications/history/notification/{rows[0]['id']}", headers=h).json()
        assert det["error"] and det["body_text"]
    finally:
        _off(client, h)
        _set_smtp(client, h, enabled=False, fallback_address="", auto_proposal_reminder_enabled=False)


def test_queue_drain_fallback_note_and_clean_success(client, auth_headers, monkeypatch):
    db = SessionLocal()
    try:
        _set_smtp(client, auth_headers, queue_enabled=True, fallback_address="mh-yedek2@test")
        a = MailQueue(to_addresses="mh-qfb@test", subject="MHQ yedek", body_text="x", status="pending")
        b = MailQueue(to_addresses="mh-qok@test", subject="MHQ temiz", body_text="x", status="pending",
                      attempts=1, last_error="eski hata")
        db.add_all([a, b]); db.commit()
        _fallback_only_sender(monkeypatch, "mh-qfb@test")
        notifier.drain_mail_queue(db)
        db.refresh(a); db.refresh(b)
        assert a.status == "sent" and "yedek adrese gönderildi" in a.last_error
        assert b.status == "sent" and b.last_error is None, "temiz teslimde eski hata kalmamalı"
    finally:
        db.close()
        _off(client, auth_headers)
        _set_smtp(client, auth_headers, enabled=False, fallback_address="", auto_proposal_reminder_enabled=False)


def test_proposal_team_without_email_goes_to_fallback_or_shows_failed(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _pending_for_team(client, h, team_email="gecici@test", domain="mh-noemail.test", cn="mh-noemail.test")
    assert client.put(f"/api/teams/{tid}", headers=h, json={"email": ""}).status_code == 200
    try:
        # yedek adres var → oraya gider, geçmişte görünür
        _set_smtp(client, h, fallback_address="mh-yedek3@test")
        sent = _capture(monkeypatch)
        _run(force=True)
        mine = [m for m in sent if "mh-yedek3@test" in m["to"] and "SY-mh-noemail.test" in m["body"]]
        assert mine and "e-posta adresi tanımlı olmadığı için yedek adrese" in mine[0]["body"]
        rows = [r for r in _hist(client, h, recipient="mh-yedek3@test") if r["mail_type"] == "proposal"
                and "SY-mh-noemail.test" in (r["stakeholder"] or "")]
        assert len(rows) == 1 and rows[0]["status"] == "sent"

        # yedek adres de yok → 'Başarısız' satırı, sonuçta failed
        _set_smtp(client, h, fallback_address="")
        res = _run(force=True)
        assert res["failed"] >= 1
        rows = [r for r in _hist(client, h, status="failed", subject="değişiklik talebi")
                if r["stakeholder"] == "SY-mh-noemail.test"]
        assert rows and "e-posta adresi tanımlı değil" in rows[0]["error"]
        assert rows[0]["retryable"] is False
    finally:
        _off(client, h)
        # bu ekibin bekleyen talebi diğer testleri etkilemesin
        client.put(f"/api/teams/{tid}", headers=h, json={"email": "mh-noemail-sonra@test"})


def test_deactivation_without_recipient_goes_to_fallback(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "MH-Epostasiz")
    dom = _domain(client, h, "mh-pasif-fb.test", sy_team_id=tid)
    leaf = _import_leaf(client, h, "mh-pasif-fb.test")
    _attach(client, h, dom, leaf, "client")
    _set_smtp(client, h, fallback_address="mh-yedek4@test")
    sent = _capture(monkeypatch)
    try:
        body = client.post(f"/api/certificates/{leaf}/deactivate", headers=h).json()
        assert body["mail_sent"] is True and "yedek adrese" in body["message"]
        assert any("mh-yedek4@test" in m["to"] for m in sent)
        rows = [r for r in _hist(client, h, record="mh-pasif-fb.test") if r["mail_type"] == "deactivated"]
        assert len(rows) == 1 and rows[0]["status"] == "sent"
        assert rows[0]["recipients"] == ["mh-yedek4@test"] and rows[0]["stakeholder"] == "yedek adres"
    finally:
        _off(client, h)
        _set_smtp(client, h, enabled=False, fallback_address="", auto_proposal_reminder_enabled=False)
