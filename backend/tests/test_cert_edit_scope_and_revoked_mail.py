"""v3.8.4 sahip kararları:
- Editör yalnız KENDİ ekibine ait (ya da hiçbir ekibe ait olmayan) sertifikayı düzenler.
- İptal edilen (revoked) sertifika için paydaşlara, süre uyarısıyla aynı düzende mail gider;
  yalnız durum 'revoked'a İLK geçtiğinde (tekrar denetim yeni mail üretmez)."""

from datetime import datetime, timedelta

from app.db.models import (Application, ApplicationTrustedCert, Certificate, CertificateDomainMap,
                           Domain)
from app.db.session import SessionLocal
from app.services import notifier, revocation
from app.services.mail_history import classify
from tests import certgen


def _mk_user(client, admin, username, role="editor", pw="Parola!123"):
    r = client.post("/api/users", headers=admin, json={"username": username, "password": pw,
                                                         "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login(client, username, pw="Parola!123"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _team(client, admin, name, email=None):
    body = {"name": name, "type": "SY"}
    if email:
        body["email"] = email
    r = client.post("/api/teams", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _add_member(client, admin, team_id, uid):
    assert client.post(f"/api/teams/{team_id}/members", headers=admin,
                       json={"user_id": uid}).status_code == 200


def _import_leaf(client, h, cn, *, days=200):
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=datetime.utcnow() - timedelta(days=1),
                                days=days, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _seed(fn):
    db = SessionLocal()
    try:
        r = fn(db)
        db.commit()
        return r
    finally:
        db.close()


def _bind_domain(cid, name, team_id, mapping_type="server"):
    def seed(db):
        cert = db.get(Certificate, cid)
        cert.creator = None
        dom = Domain(domain=name, sy_team_id=team_id)
        db.add(dom)
        db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=dom.id, mapping_type=mapping_type))
    _seed(seed)


# ---- Sertifika düzenleme kapsamı ----
def test_editor_cannot_edit_other_teams_certificate(client, auth_headers):
    h = auth_headers
    t_a, t_b = _team(client, h, "CE Alpha SY"), _team(client, h, "CE Beta SY")
    uid = _mk_user(client, h, "ce_editor_alpha")
    _add_member(client, h, t_a, uid)
    eh = _login(client, "ce_editor_alpha")

    own = _import_leaf(client, h, "ce-own.test")
    other = _import_leaf(client, h, "ce-other.test")
    _bind_domain(own, "ce-own-dom.test", t_a)
    _bind_domain(other, "ce-other-dom.test", t_b)

    r = client.put(f"/api/certificates/{other}", headers=eh,
                   json={"cert_type": "intermediate", "notes": "x"})
    assert r.status_code == 403, r.text
    assert "başka bir ekibe ait" in r.json()["detail"]
    db = SessionLocal()
    try:
        assert db.get(Certificate, other).cert_type == "leaf"  # değişmedi
    finally:
        db.close()

    assert client.put(f"/api/certificates/{own}", headers=eh, json={"notes": "bizim"}).status_code == 200
    # admin her sertifikayı düzenler
    assert client.put(f"/api/certificates/{other}", headers=h, json={"notes": "admin"}).status_code == 200


def test_editor_scope_counts_creator_trusted_and_shared(client, auth_headers):
    h = auth_headers
    t_a, t_b = _team(client, h, "CE2 Alpha SY"), _team(client, h, "CE2 Beta SY")
    uid = _mk_user(client, h, "ce2_editor_alpha")
    _add_member(client, h, t_a, uid)
    eh = _login(client, "ce2_editor_alpha")

    # Oluşturan Ekip = kendi ekibi → düzenler
    by_creator = _import_leaf(client, h, "ce2-creator.test")
    _seed(lambda db: setattr(db.get(Certificate, by_creator), "creator", "CE2 Alpha SY"))
    assert client.put(f"/api/certificates/{by_creator}", headers=eh, json={"notes": "a"}).status_code == 200

    # Başka ekip oluşturmuş ama kendi uygulamasının trust store'unda → ortak sahip, düzenler
    trusted = _import_leaf(client, h, "ce2-trusted.test")

    def seed(db):
        db.get(Certificate, trusted).creator = "CE2 Beta SY"
        app = Application(app_name="ce2-app", sy_team_id=t_a)
        db.add(app)
        db.flush()
        db.add(ApplicationTrustedCert(app_id=app.id, cert_id=trusted))
    _seed(seed)
    assert client.put(f"/api/certificates/{trusted}", headers=eh, json={"notes": "a"}).status_code == 200

    # Yalnız başka ekibin oluşturduğu → düzenleyemez
    beta_only = _import_leaf(client, h, "ce2-beta.test")
    _seed(lambda db: setattr(db.get(Certificate, beta_only), "creator", "CE2 Beta SY"))
    assert client.put(f"/api/certificates/{beta_only}", headers=eh, json={"notes": "a"}).status_code == 403

    # Hiçbir ekibe ait olmayan (ör. kök/ara) → ortak, düzenler
    shared = _import_leaf(client, h, "ce2-shared.test")
    _seed(lambda db: setattr(db.get(Certificate, shared), "creator", None))
    assert client.put(f"/api/certificates/{shared}", headers=eh, json={"notes": "a"}).status_code == 200


# ---- İptal maili ----
def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "resend_interval_hours": 3, "queue_enabled": False,
           "fallback_address": ""}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(notifier, "_send_mail",
                        lambda cfg, to, subject, body, html=None: sent.append(
                            {"to": list(to), "subject": subject, "body": body, "html": html}))
    return sent


def test_revoked_cert_mails_stakeholders_once(client, auth_headers, monkeypatch):
    h = auth_headers
    t = _team(client, h, "RV Owner SY", "rv-owner@test")
    t_app = _team(client, h, "RV App SY", "rv-app@test")
    cid = _import_leaf(client, h, "rv-cert.test", days=200)  # süre penceresi DIŞINDA
    _bind_domain(cid, "rv-dom.test", t)

    def seed(db):
        app = Application(app_name="rv-app", sy_team_id=t_app)
        db.add(app)
        db.flush()
        db.add(ApplicationTrustedCert(app_id=app.id, cert_id=cid))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    monkeypatch.setattr(revocation, "check_certificate",
                        lambda db, cert, cl, config: ("revoked", {"method": "ocsp"}))

    r = client.post(f"/api/certificates/{cid}/revocation-check", headers=h)
    assert r.status_code == 200 and r.json()["revocation_status"] == "revoked"
    to = {a for m in sent for a in m["to"]}
    assert {"rv-owner@test", "rv-app@test"} <= to, sent
    m = sent[0]
    assert m["subject"].startswith("[JUMBO] İPTAL EDİLMİŞ sertifika: rv-cert.test")
    assert classify(m["subject"]) == "revoked"
    # süre uyarısıyla aynı iskelet: banner + Domain Detay + SSL Sertifika Detayı + neden + footer
    for part in ("İPTAL EDİLMİŞ (revoked)", "Domain Detay Bilgileri", "SSL Sertifika Detayı",
                 "Bu bildirimi alma nedeniniz", notifier._MAIL_FOOTER):
        assert part in m["html"], part

    # ikinci denetim: durum zaten revoked → yeni mail YOK
    sent.clear()
    assert client.post(f"/api/certificates/{cid}/revocation-check", headers=h).status_code == 200
    assert sent == []


def test_revoked_mail_from_nightly_job_and_fallback(client, auth_headers, monkeypatch):
    h = auth_headers
    cid = _import_leaf(client, h, "rv-noowner.test", days=200)
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", None))
    _set_smtp(client, h, fallback_address="yedek@test")
    sent = _capture(monkeypatch)
    monkeypatch.setattr(revocation, "get_config",
                        lambda db: {"enabled": True, "check_active_only": True,
                                    "method": "ocsp_then_crl", "timeout_seconds": 1})

    def fake_check(db, cert, cl, config):
        return ("revoked", {}) if cert.id == cid else ("good", {})
    monkeypatch.setattr(revocation, "check_certificate", fake_check)

    result = revocation.check_all_certificates()
    assert result["status"] == "ok" and result["revoked"] >= 1
    mine = [m for m in sent if "rv-noowner.test" in m["subject"]]
    assert len(mine) == 1 and mine[0]["to"] == ["yedek@test"]

    sent.clear()
    revocation.check_all_certificates()
    assert not [m for m in sent if "rv-noowner.test" in m["subject"]]
    _set_smtp(client, h)  # sonraki testler için yedek adresi temizle


def test_only_admin_changes_certificate_derived_fields(client, auth_headers):
    """Ad, Type, üst sertifika ve Internal sertifikadan gelir — elle düzeltmeyi yalnız admin yapar;
    editör kendi sertifikasında yalnız kurumsal alanları değiştirir."""
    h = auth_headers
    t_a = _team(client, h, "CE3 Alpha SY")
    uid = _mk_user(client, h, "ce3_editor_alpha")
    _add_member(client, h, t_a, uid)
    eh = _login(client, "ce3_editor_alpha")
    own = _import_leaf(client, h, "ce3-own.test")
    _bind_domain(own, "ce3-own-dom.test", t_a)
    cur = client.get(f"/api/certificates/{own}", headers=h).json()
    root = next(c for c in client.get("/api/certificates", headers=h).json() if c["cert_type"] == "root")

    for change in ({"name": "yeni-ad"}, {"cert_type": "intermediate"},
                   {"is_internal": not cur["is_internal"]}, {"parent_id": root["id"]}):
        r = client.put(f"/api/certificates/{own}", headers=eh, json=change)
        assert r.status_code == 403, (change, r.text)
        assert "yalnız admin" in r.json()["detail"]
    after = client.get(f"/api/certificates/{own}", headers=h).json()
    assert (after["name"], after["cert_type"], after["is_internal"]) == (cur["name"], "leaf", cur["is_internal"])

    # Form tüm alanları geri gönderse de (değişmemişse) kurumsal alan güncellemesi geçer
    r = client.put(f"/api/certificates/{own}", headers=eh,
                   json={"name": cur["name"], "is_internal": cur["is_internal"], "environment": "prod",
                         "purchased_by": "Satın Alma", "notes": "editör notu"})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "editör notu"

    # admin hepsini değiştirir
    r = client.put(f"/api/certificates/{own}", headers=h, json={"name": "admin-adı", "is_internal": True})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "admin-adı"
