"""Takip edilemeyen domain bilgilendirmesi (v3.9.44): aktif Server (leaf) / Trusted sertifikası
ve Manuel Bitiş Tarihi OLMAYAN domainler için SY ekibine (ekip başına tek mail) bilgi."""

from datetime import datetime

from app.db.models import MailQueue, Notification
from app.db.session import SessionLocal
from app.services import mail_history, notifier
from tests import certgen


def _team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _domain(client, h, name, **extra):
    r = client.post("/api/domains", headers=h, json={"domain": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _leaf(client, h, cn):
    ca, ck = certgen.make_ca(f"CA {cn}")
    leaf, _ = certgen.make_leaf(ca, ck, cn, not_before=datetime(2026, 1, 1))
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    certs = r.json()
    return (next(c["id"] for c in certs if c["cert_type"] == "leaf"),
            next(c["id"] for c in certs if c["cert_type"] != "leaf"))


def _map(client, h, dom, cid, mtype):
    r = client.post(f"/api/domains/{dom}/certificates", headers=h,
                    json={"certificate_id": cid, "mapping_type": mtype})
    assert r.status_code == 200, r.text


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test", "queue_enabled": False,
           "fallback_address": "", "auto_untracked_domain_enabled": True}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch):
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        sent.append({"to": list(to), "subject": subject, "body": body, "html": html})
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


def _run(**kw):
    db = SessionLocal()
    try:
        return notifier.send_untracked_domain_notifications(db, **kw)
    finally:
        db.close()


def _mails_to(sent, addr):
    return [m for m in sent if addr in m["to"]]


def test_only_untracked_domains_listed_one_mail_per_team(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-A", "uta@test")
    _domain(client, h, "ut-bos.test", sy_team_id=tid)                        # eksik → listelenir
    _domain(client, h, "ut-bos2.test", sy_team_id=tid)                       # eksik → listelenir
    _domain(client, h, "ut-manuel.test", sy_team_id=tid, expire_date="2027-05-01T00:00:00")
    d_srv = _domain(client, h, "ut-server.test", sy_team_id=tid)
    d_tr = _domain(client, h, "ut-trusted.test", sy_team_id=tid)
    leaf, _ = _leaf(client, h, "ut-server.test")
    _map(client, h, d_srv, leaf, "server")
    leaf2, _ = _leaf(client, h, "ut-trusted.test")
    _map(client, h, d_tr, leaf2, "client")
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    res = _run(force=True)

    mails = _mails_to(sent, "uta@test")
    assert len(mails) == 1, "ekip başına TEK mail"
    m = mails[0]
    for name in ("ut-bos.test", "ut-bos2.test"):
        assert name in m["body"] and name in m["html"]
    for name in ("ut-manuel.test", "ut-server.test", "ut-trusted.test"):
        assert name not in m["body"], f"{name} takip edilebilir, listelenmemeli"
    assert "takip edilemeyen domain" in m["subject"]
    assert mail_history.classify(m["subject"]) == "untracked"
    assert "Manuel Bitiş Tarihi" in m["body"]
    assert res["enabled"] and res["sent"] >= 1


def test_fixing_domain_drops_it_from_list(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-B", "utb@test")
    dom = _domain(client, h, "ut-duzelt.test", sy_team_id=tid)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _mails_to(sent, "utb@test")
    r = client.put(f"/api/domains/{dom}", headers=h,
                   json={"domain": "ut-duzelt.test", "sy_team_id": tid, "expire_date": "2027-01-01T00:00:00"})
    assert r.status_code == 200, r.text
    sent.clear()
    _run(force=True)
    assert not _mails_to(sent, "utb@test"), "eksik giderilince ekip mail almamalı"


def test_team_without_email_and_no_team_go_to_fallback(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-NOMAIL", None)
    _domain(client, h, "ut-nomail.test", sy_team_id=tid)
    _domain(client, h, "ut-sahipsiz.test")
    _set_smtp(client, h, fallback_address="yedek-ut@test")
    sent = _capture(monkeypatch)
    _run(force=True)
    fb = _mails_to(sent, "yedek-ut@test")
    nomail = [m for m in fb if "ut-nomail.test" in m["body"]]
    owner = [m for m in fb if "ut-sahipsiz.test" in m["body"]]
    assert nomail and "SY-UT-NOMAIL" in nomail[0]["body"] and "yedek adrese" in nomail[0]["body"]
    assert owner and "SY ekibi atanmamış" in owner[0]["body"]


def test_no_fallback_records_failed_in_history(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-HICBIR", None)
    _domain(client, h, "ut-hicbir.test", sy_team_id=tid)
    _set_smtp(client, h, fallback_address="")
    _capture(monkeypatch)
    res = _run(force=True)
    assert res["failed"] >= 1
    db = SessionLocal()
    try:
        row = (db.query(MailQueue).filter(MailQueue.stakeholder == "SY-UT-HICBIR",
                                          MailQueue.status == "failed").first())
        assert row is not None and "ut-hicbir.test" in row.body_text
    finally:
        db.close()


def test_sent_mail_visible_in_history(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-GECMIS", "utg@test")
    _domain(client, h, "ut-gecmis.test", sy_team_id=tid)
    _set_smtp(client, h)
    _capture(monkeypatch)
    _run(force=True)
    r = client.get("/api/notifications/history", headers=h, params={"mail_type": "untracked"})
    assert r.status_code == 200, r.text
    assert any("utg@test" in (i.get("recipient") or "") or "SY-UT-GECMIS" in (i.get("subject") or "")
               for i in r.json()["items"])


def test_auto_toggle_cron_vs_api(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-TOGGLE", "uttog@test")
    _domain(client, h, "ut-toggle.test", sy_team_id=tid)
    _set_smtp(client, h, auto_untracked_domain_enabled=False)
    sent = _capture(monkeypatch)
    assert notifier.check_untracked_domains() == {"status": "skipped"}
    assert not _mails_to(sent, "uttog@test"), "otomatik kapalıyken zamanlanmış iş mail atmamalı"
    r = client.post("/api/notifications/untracked-run", headers=h)
    assert r.status_code == 200, r.text
    assert _mails_to(sent, "uttog@test"), "Şimdi Gönder kapalı bayraktan etkilenmemeli"
    _set_smtp(client, h, auto_untracked_domain_enabled=True)
    sent.clear()
    assert notifier.check_untracked_domains()["status"] == "ok"
    assert _mails_to(sent, "uttog@test")


def test_smtp_off_sends_nothing(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h, enabled=False)
    sent = _capture(monkeypatch)
    assert _run(force=True)["enabled"] is False
    assert sent == []


def test_schedule_daily_hour(client, auth_headers):
    h = auth_headers
    _set_smtp(client, h, untracked_domain_hour=14)
    assert notifier._untracked_schedule() == {"trigger": "cron", "hour": 14, "minute": 30}
    _set_smtp(client, h, untracked_domain_hour=99)
    assert notifier._untracked_schedule() == {"trigger": "cron", "hour": 9, "minute": 30}
    _set_smtp(client, h, untracked_domain_hour=9)


def test_external_trigger_with_api_key(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SY-UT-DIS", "utdis@test")
    _domain(client, h, "ut-dis.test", sy_team_id=tid)
    _set_smtp(client, h, trigger_api_key="ut-anahtar-123", auto_untracked_domain_enabled=False)
    sent = _capture(monkeypatch)
    r = client.post("/api/notifications/untracked-run", headers={"X-API-Key": "ut-anahtar-123"})
    assert r.status_code == 202, r.text
    import time
    for _ in range(50):
        st = client.get("/api/notifications/untracked-run/status", headers={"X-API-Key": "ut-anahtar-123"}).json()
        if not st.get("running") and st.get("finished_at"):
            break
        time.sleep(0.1)
    assert _mails_to(sent, "utdis@test"), "dış tetik (X-API-Key) mail göndermeli"
    assert st["result"]["status"] in ("ok", "error")  # önceki testlerin yedeksiz domaini "error" yapar
    assert client.post("/api/notifications/untracked-run", headers={"X-API-Key": "yanlis"}).status_code in (401, 403)
    _set_smtp(client, h, trigger_api_key="")
