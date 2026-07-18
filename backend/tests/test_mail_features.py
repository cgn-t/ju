"""Mail yeni özellikleri: gönderim kuyruğu (outbox), yedek/fallback adres ve
süre-uyarı mailine doküman linki eklenmesi.

Kurulum: e-postalı bir SY ekibi + o ekibe ait domain + ~10 gün sonra dolacak leaf
sertifika (server eşlemesi). Böylece paydaş (domain SY ekibi) mail alır.
`notifier._send_mail` monkeypatch ile yakalanır (gerçek SMTP yok)."""

from datetime import datetime, timedelta

from app.db.models import MailQueue
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _sy_team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _expiring_leaf(client, h, cn, sy_team_id):
    ca_cert, ca_key = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=20)          # valid_to ~ now + 10 gün (uyarı penceresinde)
    leaf, _ = certgen.make_leaf(ca_cert, ca_key, cn, not_before=nb, days=30, san=[cn])
    pem = certgen.pem(leaf) + certgen.pem(ca_cert)
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", pem.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    dom_id = client.post("/api/domains", headers=h, json={"domain": cn}).json()["id"]
    client.put(f"/api/domains/{dom_id}", headers=h, json={"sy_team_id": sy_team_id})
    r = client.post(f"/api/domains/{dom_id}/certificates", headers=h,
                    json={"certificate_id": leaf_id, "mapping_type": "server"})
    assert r.status_code == 200, r.text
    return leaf_id


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "queue_enabled": False, "fallback_address": "", "doc_links": ""}
    cfg.update(over)
    r = client.put("/api/settings/smtp", headers=h, json=cfg)
    assert r.status_code == 200, r.text


def test_mail_doc_links_appended(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Mail-A", "team-a@test")
    _expiring_leaf(client, h, "maila.test", tid)
    _set_smtp(client, h, doc_links="https://docs.firma/cert-rehber\nhttps://wiki/ssl")
    sent = []
    monkeypatch.setattr(notifier, "_send_mail",
                        lambda cfg, to, subject, body, html=None: sent.append((to, body, html)))
    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()
    assert sent, "mail gönderilmedi"
    blob = "".join((b or "") + (hh or "") for _, b, hh in sent)
    assert "https://docs.firma/cert-rehber" in blob
    assert "https://wiki/ssl" in blob


def test_mail_fallback_on_failure(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Mail-B", "team-b@test")
    _expiring_leaf(client, h, "mailb.test", tid)
    _set_smtp(client, h, fallback_address="yedek@test")
    calls = []

    def fake(cfg, to, subject, body, html=None):
        calls.append(list(to))
        if "yedek@test" not in to:      # birincil gönderim patlar
            raise RuntimeError("primary smtp down")

    monkeypatch.setattr(notifier, "_send_mail", fake)
    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()
    assert any("team-b@test" in to for to in calls), "birincil denenmedi"
    assert any("yedek@test" in to for to in calls), "yedek adrese ikinci deneme yapılmadı"


def test_mail_queue_enqueue_then_drain(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Mail-C", "team-c@test")
    _expiring_leaf(client, h, "mailc.test", tid)
    _set_smtp(client, h, queue_enabled=True)
    sent = []
    monkeypatch.setattr(notifier, "_send_mail", lambda *a, **k: sent.append(a))
    db = SessionLocal()
    try:
        before = db.query(MailQueue).filter(MailQueue.status == "pending").count()
        notifier.send_expiry_notifications(db, force=True)
        after = db.query(MailQueue).filter(MailQueue.status == "pending").count()
        assert after > before, "kuyruğa yazılmadı"
        assert not sent, "kuyruk açıkken doğrudan gönderim yapıldı"
        res = notifier.drain_mail_queue(db)
        assert res["sent"] >= 1, res
        assert sent, "drain gönderim yapmadı"
        assert db.query(MailQueue).filter(MailQueue.status == "pending").count() == 0
    finally:
        db.close()
