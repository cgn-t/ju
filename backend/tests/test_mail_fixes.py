"""v3.7.0 mail düzeltmeleri.

  1. Ekip e-postasında ',' ve ';' ikisi de ayırıcı; ekip kaydında adres biçimi doğrulanır.
  2. Kısmi alıcı reddi: reddedilenler yedek adrese bildirilir ve Mail Gönderim Geçmişi'ne
     'failed' satır olarak düşer (doğrudan gönderim ve kuyruk boşaltma).
  3. Zamanlama ayarı kaydedilince ilgili job yeniden başlatma gerekmeden yeniden planlanır.
  4. use_ssl → smtplib.SMTP_SSL (port 465).
  5. POST /api/settings/smtp/test — yalnız verilen adrese test maili.
  6. Günlük süresi-geçmiş hatırlatması (expired-check job'ı, smtp.auto_expired_enabled).
  7. Zamanlanmış devir hatırlatması kuyruğa alındığında commit edilir (kaybolmaz).
"""

from datetime import datetime, timedelta

import pytest

from app.core.emails import normalize_email_list, split_emails
from app.db.models import Certificate, MailQueue
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen
from tests.test_proposal_reminder import _pending_for_team


def _team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()


def _import_leaf(client, h, cn, *, days=30, nb_days_ago=25):
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=nb_days_ago)
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=nb, days=days, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test", "port": 25,
           "use_tls": False, "use_ssl": False, "username": "",
           "expiry_warning_days": 30, "resend_interval_hours": 3, "auto_expiry_enabled": True,
           "auto_expired_enabled": True, "queue_enabled": False, "fallback_address": "",
           "resend_dedup_enabled": True}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _seed(fn):
    db = SessionLocal()
    try:
        r = fn(db)
        db.commit()
        return r
    finally:
        db.close()


def _capture(monkeypatch):
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        sent.append({"to": list(to), "subject": subject, "body": body})
        return {}
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


class _RefusingSMTP:
    """smtplib.SMTP yerine: 'bad' içeren alıcıları gerçek sunucu gibi kısmi reddeder (dönüş
    sözlüğü), hepsi reddedilirse SMTPRecipientsRefused fırlatır."""
    sent: list[tuple] = []
    instances: list["_RefusingSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.starttls_called = host, port, False
        _RefusingSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, u, p):
        pass

    def sendmail(self, frm, to, msg):
        import smtplib
        refused = {a: (550, b"5.1.1 User unknown") for a in to if "bad" in a}
        if len(refused) == len(to):
            raise smtplib.SMTPRecipientsRefused(refused)
        _RefusingSMTP.sent.append((list(to), _decode(msg)))
        return refused


def _decode(raw: str) -> str:
    """Ham MIME → 'konu\n\ndüz metin gövde' (Türkçe başlık/gövde çözülmüş)."""
    import email
    from email.header import decode_header, make_header
    m = email.message_from_string(raw)
    text = next(p for p in m.walk() if p.get_content_type() == "text/plain")
    return f"{make_header(decode_header(m['Subject']))}\n\n{text.get_payload(decode=True).decode()}"


@pytest.fixture
def fake_smtp(monkeypatch):
    _RefusingSMTP.sent.clear()
    _RefusingSMTP.instances.clear()
    monkeypatch.setattr(notifier.smtplib, "SMTP", _RefusingSMTP)
    monkeypatch.setattr(notifier.smtplib, "SMTP_SSL", _RefusingSMTP)
    return _RefusingSMTP


def _delivered_to(addr):
    return [m for to, m in _RefusingSMTP.sent if addr in to]


# ---------------------------------------------------------------------------
# 1. Ayırıcılar ve doğrulama
# ---------------------------------------------------------------------------

def test_split_emails_accepts_comma_and_semicolon():
    assert split_emails("a@x; b@y,c@z ;; A@X") == ["a@x", "b@y", "c@z"]
    assert split_emails(None) == [] and split_emails("  ") == []


def test_normalize_email_list_rejects_space_separated():
    assert normalize_email_list("a@x;b@y") == "a@x, b@y"
    assert normalize_email_list("") is None
    with pytest.raises(ValueError):
        normalize_email_list("a@x b@y")
    with pytest.raises(ValueError):
        normalize_email_list("not-an-email")


def test_team_email_normalized_and_validated(client, auth_headers):
    h = auth_headers
    t = _team(client, h, "FIX Sep Team", "fix-sep-a@test; fix-sep-b@test")
    assert t["email"] == "fix-sep-a@test, fix-sep-b@test"
    r = client.post("/api/teams", headers=h,
                    json={"name": "FIX Bad Team", "type": "SY", "email": "fix-a@test fix-b@test"})
    assert r.status_code == 422
    r = client.put(f"/api/teams/{t['id']}", headers=h, json={"email": "geçersiz"})
    assert r.status_code == 422


def test_semicolon_team_email_reaches_both(client, auth_headers, monkeypatch):
    """Eski veride ';' ile kayıtlı ekip adresi (doğrulama öncesi) de iki ayrı alıcıya gider."""
    h = auth_headers
    t = _team(client, h, "FIX Semi SY", "fix-semi-a@test")
    from app.db.models import Team
    _seed(lambda db: setattr(db.get(Team, t["id"]), "email", "fix-semi-a@test;fix-semi-b@test"))
    cid = _import_leaf(client, h, "fix-semi-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "FIX Semi SY"))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()
    mine = [m for m in sent if "fix-semi-a@test" in m["to"]]
    assert mine and mine[0]["to"] == ["fix-semi-a@test", "fix-semi-b@test"]


# ---------------------------------------------------------------------------
# 2. Kısmi alıcı reddi
# ---------------------------------------------------------------------------

def test_partial_refusal_goes_to_fallback_and_history(client, auth_headers, fake_smtp):
    h = auth_headers
    _team(client, h, "FIX Partial SY", "fix-ok@test, fix-bad@test")
    cid = _import_leaf(client, h, "fix-partial-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "FIX Partial SY"))
    _set_smtp(client, h, fallback_address="fix-fallback@test")
    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()

    assert _delivered_to("fix-ok@test"), "reddedilmeyen alıcıya mail gitmeli"
    fb = _delivered_to("fix-fallback@test")
    assert fb, "reddedilen alıcı yedek adrese bildirilmeli"
    assert "[YEDEK]" in fb[-1] and "fix-bad@test" in fb[-1]

    db = SessionLocal()
    try:
        row = (db.query(MailQueue).filter(MailQueue.to_addresses == "fix-bad@test")
               .order_by(MailQueue.id.desc()).first())
        assert row is not None and row.status == "failed"
        assert row.certificate_id == cid
        assert "kısmen" in row.last_error and "550" in row.last_error
    finally:
        db.close()


def test_partial_refusal_without_fallback_still_recorded(fake_smtp):
    cfg = {"host": "h", "from_address": "f@test", "fallback_address": ""}
    ok, note, refused = notifier._send_with_fallback(cfg, ["fix2-ok@test", "fix2-bad@test"],
                                                     "s", "b", None)
    assert ok is True and list(refused) == ["fix2-bad@test"]
    assert note.startswith("kısmen gönderildi")


def test_full_refusal_still_uses_fallback(fake_smtp):
    cfg = {"host": "h", "from_address": "f@test", "fallback_address": "fix3-fb@test"}
    ok, note, refused = notifier._send_with_fallback(cfg, ["fix3-bad@test"], "s", "b", None)
    assert ok is True and refused == {} and "yedek" in note
    assert _delivered_to("fix3-fb@test")


def test_queue_drain_partial_refusal_recorded(client, auth_headers, fake_smtp):
    _set_smtp(client, auth_headers, queue_enabled=True, fallback_address="fix4-fb@test")
    mqid = _seed(lambda db: (lambda m: (db.add(m), db.flush(), m.id)[-1])(
        MailQueue(to_addresses="fix4-ok@test, fix4-bad@test", subject="FIX4 kuyruk",
                  body_text="b", stakeholder="FIX4")))
    db = SessionLocal()
    try:
        notifier.drain_mail_queue(db)
        db.expire_all()
        row = db.get(MailQueue, mqid)
        assert row.status == "sent"
        assert "kısmen" in (row.last_error or "")
        failed = db.query(MailQueue).filter(MailQueue.to_addresses == "fix4-bad@test").all()
        assert len(failed) == 1 and failed[0].status == "failed"
    finally:
        db.close()
    assert _delivered_to("fix4-ok@test") and _delivered_to("fix4-fb@test")
    _set_smtp(client, auth_headers)


# ---------------------------------------------------------------------------
# 3. Zamanlama ayarı kaydedilince yeniden planlama
# ---------------------------------------------------------------------------

def _hour(job_id):
    job = notifier.scheduler.get_job(job_id)
    return next(str(f) for f in job.trigger.fields if f.name == "hour")


def test_saving_settings_reschedules_jobs(client, auth_headers):
    h = auth_headers
    assert notifier.scheduler.running
    _set_smtp(client, h, proposal_reminder_hour=14, queue_interval_minutes=7)
    try:
        assert _hour("proposal-reminder") == "14"
        drain = notifier.scheduler.get_job("mail-queue-drain")
        assert drain.trigger.interval == timedelta(minutes=7)
    finally:
        _set_smtp(client, h, proposal_reminder_hour=9, queue_interval_minutes=5)
    assert _hour("proposal-reminder") == "9"


# ---------------------------------------------------------------------------
# 4. Port 465 / SMTP_SSL
# ---------------------------------------------------------------------------

def test_use_ssl_uses_smtp_ssl_without_starttls(monkeypatch):
    calls = []

    class SSL(_RefusingSMTP):
        def __init__(self, host, port, timeout=None):
            calls.append(("ssl", port))
            super().__init__(host, port, timeout)

    class Plain(_RefusingSMTP):
        def __init__(self, host, port, timeout=None):
            calls.append(("plain", port))
            super().__init__(host, port, timeout)

    monkeypatch.setattr(notifier.smtplib, "SMTP_SSL", SSL)
    monkeypatch.setattr(notifier.smtplib, "SMTP", Plain)
    notifier._send_mail({"host": "h", "port": None, "from_address": "f@test",
                         "use_ssl": True, "use_tls": True}, ["x@test"], "s", "b")
    assert calls == [("ssl", 465)]
    assert _RefusingSMTP.instances[-1].starttls_called is False


# ---------------------------------------------------------------------------
# 5. Test maili ucu
# ---------------------------------------------------------------------------

def test_smtp_test_endpoint(client, auth_headers, fake_smtp):
    h = auth_headers
    _set_smtp(client, h)
    r = client.post("/api/settings/smtp/test", headers=h, json={"to": "fix5-me@test"})
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    msg = _delivered_to("fix5-me@test")
    assert msg and "SMTP test maili" in msg[0]

    r = client.post("/api/settings/smtp/test", headers=h, json={"to": "fix5-ok@test; fix5-bad@test"})
    assert r.json()["success"] is False and "fix5-bad@test" in r.json()["message"]

    r = client.post("/api/settings/smtp/test", headers=h, json={"to": "fix5-bad@test"})
    assert r.json()["success"] is False and "Gönderilemedi" in r.json()["message"]


def test_smtp_test_endpoint_requires_host_and_admin(client, auth_headers, fake_smtp):
    _set_smtp(client, auth_headers, host="")
    try:
        r = client.post("/api/settings/smtp/test", headers=auth_headers, json={"to": "x@test"})
        assert r.status_code == 400
    finally:
        _set_smtp(client, auth_headers)
    assert client.post("/api/settings/smtp/test", json={"to": "x@test"}).status_code in (401, 403)


# ---------------------------------------------------------------------------
# 6. Günlük süresi-geçmiş hatırlatması
# ---------------------------------------------------------------------------

def test_expired_job_respects_flag_and_dedup(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "FIX Expired SY", "fix-expired@test")
    cid = _import_leaf(client, h, "fix-expired-cert.test", days=10, nb_days_ago=40)
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "FIX Expired SY"))

    _set_smtp(client, h, auto_expired_enabled=False)
    sent = _capture(monkeypatch)
    assert notifier.check_expired_certificates()["status"] == "skipped"
    assert not any("fix-expired@test" in m["to"] for m in sent)

    _set_smtp(client, h, auto_expired_enabled=True)
    notifier.check_expired_certificates()
    mine = [m for m in sent if "fix-expired@test" in m["to"]]
    assert len(mine) == 1
    # Elle tetiklenen "Süresi Geçenleri Şimdi Gönder" ile BİREBİR aynı konu ve gövde
    manual = _capture(monkeypatch)
    db = SessionLocal()
    try:
        notifier.send_expired_notifications(db, force=True)
    finally:
        db.close()
    same = [m for m in manual if "fix-expired@test" in m["to"]]
    assert same and same[0]["subject"] == mine[0]["subject"] and same[0]["body"] == mine[0]["body"]
    assert "SÜRESİ GEÇMİŞ" in mine[0]["subject"]

    # aynı gün ikinci çalıştırma → tekrar-önleme
    again = _capture(monkeypatch)
    notifier.check_expired_certificates()
    assert not any("fix-expired@test" in m["to"] for m in again)


# ---------------------------------------------------------------------------
# 7. Zamanlanmış devir hatırlatması kuyruğa alınınca commit edilir
# ---------------------------------------------------------------------------

def test_scheduled_proposal_reminder_queue_row_is_committed(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email="fix7-team@test", domain="fix7-dom.test",
                      cn="fix7-cert.test")
    _set_smtp(client, h, queue_enabled=True, auto_proposal_reminder_enabled=True)
    _capture(monkeypatch)
    try:
        assert notifier.check_pending_proposals()["status"] == "ok"
        db = SessionLocal()
        try:
            rows = db.query(MailQueue).filter(MailQueue.to_addresses == "fix7-team@test").all()
            assert len(rows) == 1 and rows[0].status == "pending", "kuyruk satırı kaybolmamalı"
            for r in rows:
                db.delete(r)
            db.commit()
        finally:
            db.close()
    finally:
        _set_smtp(client, h, auto_proposal_reminder_enabled=False)
