"""Bildirim kanalları (Slack/Teams/Webhook) + dispatcher testleri.

Egress YAPILMAZ: her kanalın http_client'ı sahte istemciyle değiştirilir. Kapsam: kanal payload'ları,
'Test' sonucu (ok/ağ-hatası graceful), dispatcher'ın etkin kanallara göndermesi + kanal-bazlı 7-gün
dedup + bir kanal patlarsa diğerlerinin sürmesi + e-posta dedup'ının kanaldan bağımsızlığı; endpoint yetki.
"""

from datetime import timedelta

import httpx

from app.core.timeutil import utcnow
from app.db.models import Certificate, Notification
from app.db.session import SessionLocal
from app.services.notify import dispatcher, jabber, jira, servicenow, slack, teams, webhook, zoom
from app.services.notify.base import NotifyEvent


class _Resp:
    def __init__(self, status: int = 200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("http error", request=httpx.Request("POST", "http://x"),
                                        response=httpx.Response(self.status_code))


class _Client:
    """httpx.Client yerine: post'u kaydeder ya da verilen istisnayı fırlatır. Ağ I/O yok."""
    def __init__(self, sink: list, status: int = 200, exc: Exception | None = None):
        self._sink, self._status, self._exc = sink, status, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None, auth=None):
        if self._exc:
            raise self._exc
        self._sink.append({"method": "post", "url": url, "json": json,
                           "headers": headers or {}, "auth": auth})
        return _Resp(self._status)

    def get(self, url, params=None, auth=None, headers=None):
        if self._exc:
            raise self._exc
        self._sink.append({"method": "get", "url": url, "params": params,
                           "auth": auth, "headers": headers or {}})
        return _Resp(self._status)


def _patch_http(monkeypatch, sink, status=200, exc=None):
    for mod in (slack, teams, webhook, servicenow, zoom, jira):
        monkeypatch.setattr(mod, "http_client", lambda cfg: _Client(sink, status, exc))


EVENT = NotifyEvent(kind="expiry", cert_id=1, cert_name="a.example", days_left=5,
                    title="Süre doluyor", text="Kalan 5 gün", fields={"serial_number": "01"})


# ---- kanal birim testleri ----
def test_slack_send_payload(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    assert slack.SlackChannel().send({"webhook_url": "http://slack"}, EVENT) is True
    assert sink[0]["url"] == "http://slack" and "Süre doluyor" in sink[0]["json"]["text"]


def test_slack_no_url_false(monkeypatch):
    _patch_http(monkeypatch, [])
    assert slack.SlackChannel().send({}, EVENT) is False


def test_teams_messagecard(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    assert teams.TeamsChannel().send({"webhook_url": "http://teams"}, EVENT) is True
    assert sink[0]["json"]["@type"] == "MessageCard"


def test_webhook_payload_and_auth_header(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok = webhook.WebhookChannel().send({"url": "http://wh", "auth_header": "Authorization: Bearer x"}, EVENT)
    assert ok is True
    assert sink[0]["url"] == "http://wh"
    assert sink[0]["headers"] == {"Authorization": "Bearer x"}
    assert sink[0]["json"]["certificate"] == "a.example"


def test_channel_test_ok_missing_and_error(monkeypatch):
    _patch_http(monkeypatch, [])
    assert slack.SlackChannel().test({"webhook_url": "http://x"})[0] is True
    assert slack.SlackChannel().test({})[0] is False          # url yok
    _patch_http(monkeypatch, [], exc=httpx.ConnectError("blocked"))
    assert slack.SlackChannel().test({"webhook_url": "http://x"})[0] is False  # ağ hatası → graceful


# ---- Faz 2 kanalları: ServiceNow + Zoom ----
def test_servicenow_creates_incident_with_basic_auth(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok = servicenow.ServiceNowChannel().send(
        {"instance_url": "https://x.service-now.com/", "username": "u", "password": "p"}, EVENT)
    assert ok is True
    assert sink[0]["url"] == "https://x.service-now.com/api/now/table/incident"   # trailing / kırpıldı
    assert sink[0]["auth"] == ("u", "p")
    assert sink[0]["json"]["short_description"] and sink[0]["json"]["urgency"] == "2"  # expiry → Orta


def test_servicenow_expired_is_high_urgency(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    expired = NotifyEvent(kind="expired", cert_id=2, cert_name="b.example", days_left=-3,
                          title="SÜRESİ GEÇMİŞ", text="doldu")
    servicenow.ServiceNowChannel().send(
        {"instance_url": "https://x.service-now.com", "username": "u", "password": "p"}, expired)
    assert sink[0]["json"]["urgency"] == "1"   # expired → Yüksek


def test_servicenow_missing_config_false(monkeypatch):
    _patch_http(monkeypatch, [])
    assert servicenow.ServiceNowChannel().send({"username": "u"}, EVENT) is False   # instance yok


def test_servicenow_test_validates_without_incident(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok, _ = servicenow.ServiceNowChannel().test(
        {"instance_url": "https://x.service-now.com", "username": "u", "password": "p"})
    assert ok is True
    assert sink[0]["method"] == "get"   # incident AÇMADAN GET ile doğrular
    assert servicenow.ServiceNowChannel().test({"instance_url": "https://x"})[0] is False  # kullanıcı yok


# ---- Jira (talep/issue) — Basic + Bearer kimlik ----
def test_jira_creates_issue_basic_auth(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok = jira.JiraChannel().send(
        {"base_url": "https://firma.atlassian.net/", "username": "u@x", "api_token": "t",
         "project_key": "OPS", "issue_type": "Task"}, EVENT)
    assert ok is True
    assert sink[0]["url"] == "https://firma.atlassian.net/rest/api/2/issue"   # trailing / kırpıldı
    assert sink[0]["auth"] == ("u@x", "t") and sink[0]["headers"] == {}       # Basic → auth tuple
    f = sink[0]["json"]["fields"]
    assert f["project"]["key"] == "OPS" and f["issuetype"]["name"] == "Task" and f["summary"]


def test_jira_bearer_uses_authorization_header(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    jira.JiraChannel().send(
        {"base_url": "https://jira.firma.local", "auth_mode": "bearer", "api_token": "PAT123",
         "project_key": "NOC"}, EVENT)
    assert sink[0]["auth"] is None                                            # Bearer → auth yok
    assert sink[0]["headers"] == {"Authorization": "Bearer PAT123"}


def test_jira_missing_config_false(monkeypatch):
    _patch_http(monkeypatch, [])
    assert jira.JiraChannel().send({"base_url": "https://x"}, EVENT) is False   # project_key yok


def test_jira_test_validates_without_issue(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok, _ = jira.JiraChannel().test(
        {"base_url": "https://jira.firma.local", "auth_mode": "bearer", "api_token": "P",
         "project_key": "OPS"})
    assert ok is True
    assert sink[0]["method"] == "get" and sink[0]["url"].endswith("/rest/api/2/myself")  # issue AÇMAZ
    assert jira.JiraChannel().test({"base_url": "https://x"})[0] is False   # project yok


def test_zoom_send_payload_and_token_header(monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    ok = zoom.ZoomChannel().send({"webhook_url": "http://zoom", "token": "tok"}, EVENT)
    assert ok is True
    assert sink[0]["url"] == "http://zoom"
    assert sink[0]["headers"] == {"Authorization": "tok"}
    assert sink[0]["json"]["content"]["head"]["text"] == EVENT.title
    assert zoom.ZoomChannel().send({"token": "tok"}, EVENT) is False   # url yok → False


# ---- Faz 3 kanalı: Jabber/XMPP (slixmpp gerçek gönderimi _send_xmpp'de → monkeypatch) ----
def test_jabber_send_calls_xmpp_with_body(monkeypatch):
    calls: list = []
    monkeypatch.setattr(jabber, "_send_xmpp", lambda cfg, body: calls.append((cfg, body)))
    ok = jabber.JabberChannel().send({"jid": "jumbo@x", "target": "noc@conf.x"}, EVENT)
    assert ok is True
    assert calls and EVENT.title in calls[0][1] and EVENT.text in calls[0][1]


def test_jabber_missing_config_false(monkeypatch):
    monkeypatch.setattr(jabber, "_send_xmpp", lambda cfg, body: None)
    assert jabber.JabberChannel().send({"jid": "jumbo@x"}, EVENT) is False   # target yok


def test_jabber_test_ok_and_graceful_on_error(monkeypatch):
    monkeypatch.setattr(jabber, "_send_xmpp", lambda cfg, body: None)
    assert jabber.JabberChannel().test({"jid": "jumbo@x", "target": "noc@conf.x"})[0] is True
    assert jabber.JabberChannel().test({"jid": "jumbo@x"})[0] is False       # hedef yok

    def _boom(cfg, body):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(jabber, "_send_xmpp", _boom)
    ok, msg = jabber.JabberChannel().test({"jid": "jumbo@x", "target": "noc@conf.x"})
    assert ok is False and "Gönderilemedi" in msg   # ağ hatası → graceful


# ---- dispatcher ----
def _cfg_map(monkeypatch, mapping):
    monkeypatch.setattr(dispatcher, "get_category",
                        lambda db, cat, mask_secrets=False: mapping.get(cat, {}))


def _mk_cert(name: str, days: int) -> int:
    db = SessionLocal()
    try:
        c = Certificate(name=name, cert_type="leaf", serial_number="01",
                        valid_to=utcnow() + timedelta(days=days), is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
        return c.id
    finally:
        db.close()


def test_dispatcher_sends_enabled_and_dedup(client, monkeypatch):
    sink: list = []
    _patch_http(monkeypatch, sink)
    _cfg_map(monkeypatch, {"slack": {"enabled": True, "webhook_url": "http://s"},
                           "teams": {"enabled": False},
                           "webhook": {"enabled": True, "url": "http://w"}})
    cid = _mk_cert("disp.example", 10)
    db = SessionLocal()
    cert = db.get(Certificate, cid)
    r1 = dispatcher.notify_certs(db, [cert], kind="expiry")
    assert r1["sent"] == 2 and set(r1["channels"]) == {"slack", "webhook"}
    rows = db.query(Notification).filter(Notification.certificate_id == cid).all()
    assert {x.channel for x in rows} == {"slack", "webhook"}
    # tekrar → 7-gün dedup → hiç gönderim yok
    r2 = dispatcher.notify_certs(db, [cert], kind="expiry")
    assert r2["sent"] == 0 and r2["skipped"] == 2
    db.close()


def test_dispatcher_graceful_on_error(client, monkeypatch):
    _patch_http(monkeypatch, [], exc=httpx.ConnectError("blocked"))
    _cfg_map(monkeypatch, {"slack": {"enabled": True, "webhook_url": "http://s"},
                           "teams": {}, "webhook": {}})
    cid = _mk_cert("err.example", 8)
    db = SessionLocal()
    cert = db.get(Certificate, cid)
    r = dispatcher.notify_certs(db, [cert], kind="expiry")   # patlamamalı
    assert r["sent"] == 0
    assert db.query(Notification).filter(Notification.certificate_id == cid).count() == 0
    db.close()


def test_email_dedup_independent_of_channel(client):
    cid = _mk_cert("mix.example", 9)
    db = SessionLocal()
    db.add(Notification(certificate_id=cid, channel="slack", subject="x", days_left=9))
    db.commit()
    # yalnız slack kaydı var → e-posta (channel='email') dedup'ı bağımsız → son 7 günde e-posta YOK
    recent_email = (db.query(Notification)
                    .filter(Notification.certificate_id == cid, Notification.channel == "email",
                            Notification.sent_at >= utcnow() - timedelta(days=7)).first())
    assert recent_email is None
    db.close()


# ---- endpoint ----
def test_notify_test_endpoint_auth_and_unknown(client, auth_headers):
    assert client.post("/api/settings/slack/notify-test").status_code == 401           # kimliksiz
    assert client.post("/api/settings/nope/notify-test", headers=auth_headers).status_code == 404
    r = client.post("/api/settings/slack/notify-test", headers=auth_headers)           # url yok → success False
    assert r.status_code == 200 and "message" in r.json()
