"""Uygulama sahibi süre uyarıları (v3.8.3) — regresyon.

  A1  Uygulamanın "Bağlı Domain"i sertifikayı server olarak taşıyorsa uygulama sahibi uyarılır
      (süresi yaklaşan ve geçmiş).
  A2  mTLS bağımlılığı, hedef domainde sertifika yokken eklense de sonradan bağlanan server
      leaf'ini izler (elle eşleme ucu ve tarama öncesi senkron).
  A3  Hiç alıcısı olmayan sertifika yedek adrese gider; yedek adres de yoksa sonuçta görünür.
  A4  Domainin "Bildirim Gün Sayısı" bağlı-domain, mTLS ve trusted uygulama sahibine de uygulanır.
  A5  Trusted sahibi yalnız süre dolana kadar uyarılır; süresi geçmiş mailinde trusted nedeni yok.
  A6  Pasif uygulamanın sahibi uyarılır; UG takımı uyarılmaz.
"""

from datetime import datetime, timedelta

from app.db import models as m
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _team(client, h, name, email, typ="SY"):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": typ, "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _leaf(client, h, cn, *, days_left):
    ca, ck = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=200)
    leaf, _ = certgen.make_leaf(ca, ck, cn, not_before=nb, days=200 + days_left, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    cid = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    db = SessionLocal()
    try:
        db.get(m.Certificate, cid).creator = None
        db.commit()
    finally:
        db.close()
    return cid


def _domain(client, h, name, sy, **extra):
    r = client.post("/api/domains", headers=h, json={"domain": name, "sy_team_id": sy, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(client, h, dom, cid):
    r = client.post(f"/api/domains/{dom}/certificates", headers=h,
                    json={"certificate_id": cid, "mapping_type": "server"})
    assert r.status_code == 200, r.text


def _app(client, h, name, sy, *, domain_id=None, ug=None, status=True):
    r = client.post("/api/applications", headers=h,
                    json={"app_name": name, "server_name": f"{name}-srv", "sy_team_id": sy,
                          "ug_team_id": ug, "domain_id": domain_id, "status": status})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _dep(client, h, app_id, dom):
    r = client.post(f"/api/applications/{app_id}/dependencies", headers=h,
                    json={"target_domain_id": dom})
    assert r.status_code == 200, r.text
    return r.json()


def _trust(client, h, app_id, cid):
    r = client.post(f"/api/applications/{app_id}/trusted", headers=h, json={"certificate_id": cid})
    assert r.status_code == 200, r.text


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "resend_interval_hours": 3, "resend_dedup_enabled": True,
           "auto_expiry_enabled": True, "queue_enabled": False, "fallback_address": ""}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch):
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        sent.append({"to": list(to), "subject": subject, "body": body})
        return {}
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


def _run(fn):
    db = SessionLocal()
    try:
        return fn(db, force=True)
    finally:
        db.close()


def _mails(sent, addr):
    return [x for x in sent if addr in x["to"]]


def _expire(cid, days_ago=3):
    db = SessionLocal()
    try:
        db.get(m.Certificate, cid).valid_to = datetime.utcnow() - timedelta(days=days_ago)
        db.commit()
    finally:
        db.close()


def test_A1_bound_domain_app_owner(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h)
    td = _team(client, h, "A1 Domain SY", "a1-dom@test")
    ta = _team(client, h, "A1 App SY", "a1-app@test")
    dom = _domain(client, h, "a1.test", td)
    cid = _leaf(client, h, "a1.test", days_left=10)
    _attach(client, h, dom, cid)
    _app(client, h, "A1 App", ta, domain_id=dom)

    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert _mails(sent, "a1-dom@test")
    (mail,) = _mails(sent, "a1-app@test")
    assert "Uygulama sahibi (bağlı domain a1.test): A1 App" in mail["body"]

    _expire(cid)
    sent = _capture(monkeypatch)
    _run(notifier.send_expired_notifications)
    assert _mails(sent, "a1-app@test") and "SÜRESİ GEÇMİŞ" in _mails(sent, "a1-app@test")[0]["subject"]


def test_A2_dependency_added_before_leaf_is_filled_on_attach(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h)
    td = _team(client, h, "A2 Target SY", "a2-target@test")
    ta = _team(client, h, "A2 App SY", "a2-app@test")
    dom = _domain(client, h, "a2.test", td)
    dep = _dep(client, h, _app(client, h, "A2 App", ta), dom)
    assert dep["client_cert_id"] is None
    cid = _leaf(client, h, "a2.test", days_left=10)
    _attach(client, h, dom, cid)
    db = SessionLocal()
    try:
        assert db.get(m.AppDependency, dep["id"]).client_cert_id == cid
    finally:
        db.close()
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert _mails(sent, "a2-app@test")


def test_A2b_dependency_filled_by_scan_when_mapped_elsewhere(client, auth_headers, monkeypatch):
    """Eşleme elle ucu dışından (içe aktarma, canlı doğrulama, devir) oluşursa da tarama doldurur."""
    h = auth_headers
    _set_smtp(client, h)
    td = _team(client, h, "A2b Target SY", "a2b-target@test")
    ta = _team(client, h, "A2b App SY", "a2b-app@test")
    dom = _domain(client, h, "a2b.test", td)
    dep = _dep(client, h, _app(client, h, "A2b App", ta), dom)
    cid = _leaf(client, h, "a2b.test", days_left=10)
    db = SessionLocal()
    try:
        db.add(m.CertificateDomainMap(certificate_id=cid, domain_id=dom, mapping_type="server"))
        db.commit()
    finally:
        db.close()
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert _mails(sent, "a2b-app@test")
    db = SessionLocal()
    try:
        assert db.get(m.AppDependency, dep["id"]).client_cert_id == cid
    finally:
        db.close()


def test_A3_no_recipient_goes_to_fallback(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h, fallback_address="a3-fb@test")
    ta = _team(client, h, "A3 App SY", None)
    cid = _leaf(client, h, "a3-peer.test", days_left=10)
    _trust(client, h, _app(client, h, "A3 App", ta), cid)
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    mine = [x for x in _mails(sent, "a3-fb@test") if "a3-peer.test" in x["subject"]]
    assert len(mine) == 1 and "tanımlı bir alıcı bulunamadı" in mine[0]["body"]

    _set_smtp(client, h, fallback_address="")
    sent = _capture(monkeypatch)
    r = _run(notifier.send_expiry_notifications)
    (det,) = [d for d in r["details"] if d["certificate"] == "a3-peer.test"]
    assert "tanımlı alıcı yok" in det["error"]
    db = SessionLocal()  # diğer testlerin yedek adresine düşmesin
    try:
        db.get(m.Certificate, cid).is_active = False
        db.commit()
    finally:
        db.close()


def test_A4_domain_notify_days_applies_to_app_owners(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h, expiry_warning_days=30)
    td = _team(client, h, "A4 Dom SY", "a4-dom@test")
    tb = _team(client, h, "A4 Bound SY", "a4-bound@test")
    tm = _team(client, h, "A4 Mtls SY", "a4-mtls@test")
    tt = _team(client, h, "A4 Trust SY", "a4-trust@test")
    dom = _domain(client, h, "a4.test", td, notify_days=60)
    cid = _leaf(client, h, "a4.test", days_left=45)
    _attach(client, h, dom, cid)
    _app(client, h, "A4 BApp", tb, domain_id=dom)
    _dep(client, h, _app(client, h, "A4 MApp", tm), dom)
    _trust(client, h, _app(client, h, "A4 TApp", tt), cid)
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    for addr in ("a4-dom@test", "a4-bound@test", "a4-mtls@test", "a4-trust@test"):
        assert _mails(sent, addr), addr


def test_A4b_default_window_unchanged(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h, expiry_warning_days=30)
    td = _team(client, h, "A4b Dom SY", "a4b-dom@test")
    tm = _team(client, h, "A4b Mtls SY", "a4b-mtls@test")
    dom = _domain(client, h, "a4b.test", td)
    cid = _leaf(client, h, "a4b.test", days_left=32)
    _attach(client, h, dom, cid)
    _dep(client, h, _app(client, h, "A4b MApp", tm), dom)
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert not _mails(sent, "a4b-dom@test") and not _mails(sent, "a4b-mtls@test")


def test_A5_trusted_only_until_expiry(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h, fallback_address="a5-fb@test")
    tt = _team(client, h, "A5 Trust SY", "a5-trust@test")
    td = _team(client, h, "A5 Dom SY", "a5-dom@test")
    cid = _leaf(client, h, "a5-peer.test", days_left=10)
    _trust(client, h, _app(client, h, "A5 App", tt), cid)
    # aynı ekip hem domain sahibi hem trusted sahibi olan ikinci sertifika
    dom = _domain(client, h, "a5.test", td)
    cid2 = _leaf(client, h, "a5.test", days_left=10)
    _attach(client, h, dom, cid2)
    _trust(client, h, _app(client, h, "A5 App2", td), cid2)

    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert _mails(sent, "a5-trust@test")

    _expire(cid)
    _expire(cid2)
    sent = _capture(monkeypatch)
    _run(notifier.send_expired_notifications)
    assert not _mails(sent, "a5-trust@test"), "süresi dolunca trusted sahibine mail kesilmeli"
    assert not [x for x in _mails(sent, "a5-fb@test") if "a5-peer.test" in x["subject"]], \
        "yalnız trusted paydaşı olan sertifika alıcısız sayılıp yedek adrese gitmemeli"
    (mail,) = _mails(sent, "a5-dom@test")
    assert "Domain sahibi: a5.test" in mail["body"] and "trust store" not in mail["body"]


def test_A6_passive_app_and_ug_team(client, auth_headers, monkeypatch):
    h = auth_headers
    _set_smtp(client, h)
    ta = _team(client, h, "A6 App SY", "a6-app@test")
    ug = _team(client, h, "A6 UG", "a6-ug@test", typ="UG")
    cid = _leaf(client, h, "a6-peer.test", days_left=10)
    _trust(client, h, _app(client, h, "A6 App", ta, ug=ug, status=False), cid)
    sent = _capture(monkeypatch)
    _run(notifier.send_expiry_notifications)
    assert _mails(sent, "a6-app@test")
    assert not _mails(sent, "a6-ug@test")
