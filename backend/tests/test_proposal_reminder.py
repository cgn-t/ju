"""Devir-onayı hatırlatması: onay kuyruğunda BEKLEYEN öneri olan SY ekiplerine (ekip başına
tek mail) hatırlatma. Zamanlanmış job auto_proposal_reminder_enabled ile; dış API tetiği bayraktan
bağımsız gönderir. Amaç: onay kuyruğunu temizlemek."""

from datetime import datetime

from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import(client, h, pem_text, *, supersede=False):
    return client.post("/api/certificates/import", headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")},
                       data={"supersede": "true"} if supersede else {})


def _pending_for_team(client, h, *, team_email, domain, cn):
    """team(SY,email) + domain(sy=team) + v1 server eşle + v2 supersede → (v1→v2, domain) pending
    öneri (sy_team_id=team). Dönüş: team_id."""
    tid = _team(client, h, f"SY-{domain}", team_email)
    dom = client.post("/api/domains", headers=h,
                      json={"domain": domain, "sy_team_id": tid}).json()["id"]
    ca, ck = certgen.make_ca(f"CA {cn}")
    key = certgen.make_key()                                   # ortak anahtar → halef sinyali
    v1, _ = certgen.make_leaf(ca, ck, cn, key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ck, cn, key=key, not_before=datetime(2026, 6, 1))
    v1id = next(c["id"] for c in _import(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                if c["cert_type"] == "leaf")
    client.post(f"/api/domains/{dom}/certificates", headers=h,
                json={"certificate_id": v1id, "mapping_type": "server"})
    _import(client, h, certgen.pem(v2), supersede=True)
    return tid


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "queue_enabled": False, "auto_proposal_reminder_enabled": True}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch):
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        sent.append({"to": list(to), "subject": subject, "body": body})
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


def _run(fn=None, **kw):
    db = SessionLocal()
    try:
        return (fn or notifier.send_pending_proposal_notifications)(db, **kw)
    finally:
        db.close()


def _got(sent, addr):
    return any(addr in m["to"] for m in sent)


def test_reminder_one_mail_per_team_lists_proposals(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email="pa@test", domain="pr-a.test", cn="pr-a.test")
    _pending_for_team(client, h, team_email="pb@test", domain="pr-b.test", cn="pr-b.test")
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    res = _run(force=True)

    assert _got(sent, "pa@test") and _got(sent, "pb@test"), "her iki ekip de mail almalı"
    assert len([m for m in sent if "pa@test" in m["to"]]) == 1, "ekip başına TEK mail"
    body_a = next(m["body"] for m in sent if "pa@test" in m["to"])
    assert "pr-a.test" in body_a and "→" in body_a, "gövde bekleyen öneriyi listelemeli"
    assert res["sent"] >= 2


def test_reminder_team_without_email_skipped(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email=None, domain="pr-noemail.test", cn="pr-noemail.test")
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert not any("pr-noemail.test" in m["body"] for m in sent), "e-postasız ekibe mail gitmemeli"


def test_reminder_auto_toggle_cron_vs_api(client, auth_headers, monkeypatch):
    """auto_proposal_reminder_enabled=False → zamanlanmış cron atlar; ama doğrudan çağrı (API) gönderir."""
    h = auth_headers
    _pending_for_team(client, h, team_email="ptoggle@test", domain="pr-toggle.test", cn="pr-toggle.test")
    _set_smtp(client, h, auto_proposal_reminder_enabled=False)
    sent = _capture(monkeypatch)

    notifier.check_pending_proposals()          # cron yolu → kapalı → mail YOK
    assert not _got(sent, "ptoggle@test"), "otomatik kapalıyken cron mail ATMAMALI"

    _run(force=True)                            # doğrudan çekirdek (API yolu) → gönderir
    assert _got(sent, "ptoggle@test"), "API/force kapalı bayraktan ETKİLENMEMELİ"


def test_proposal_run_api_endpoint(client, auth_headers, monkeypatch):
    h = auth_headers
    _pending_for_team(client, h, team_email="papi@test", domain="pr-api.test", cn="pr-api.test")
    _set_smtp(client, h, auto_proposal_reminder_enabled=False)  # kapalı olsa bile API gönderir
    sent = _capture(monkeypatch)
    r = client.post("/api/notifications/proposal-run", headers=h)
    assert r.status_code == 200, r.text
    assert _got(sent, "papi@test"), "API tetiği ilgili ekibe mail göndermeli"
    assert r.json()["sent"] >= 1
