"""Pasife alma + bağlı domain SY ekiplerine bilgilendirme testleri.

Kural: bir sertifika pasife alınınca, hâlâ bağlı olduğu domainlerin SY ekiplerine
(Team.email) ve domainin mail_addresses adreslerine bilgilendirme gider; SMTP açıksa
mail atılır, her durumda Notification kaydı tutulur. JUMBO devir yapmaz — bilgilendirme.
"""

from datetime import datetime

from app.db.models import Notification
from app.db.session import SessionLocal
from tests import certgen


def _import_leaf(client, headers, cn, *, days=397, not_before=None):
    """CA + leaf üretir, fullchain olarak import eder, leaf cert id'sini döndürür."""
    ca_cert, ca_key = certgen.make_ca(f"CA {cn}")
    leaf, _ = certgen.make_leaf(ca_cert, ca_key, cn, not_before=not_before or datetime(2026, 1, 1),
                                days=days, san=[cn])
    pem = certgen.pem(leaf) + certgen.pem(ca_cert)
    r = client.post("/api/certificates/import", headers=headers,
                    files={"file": ("chain.pem", pem.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    return leaf_id


def _sy_team(client, headers, name, email=None):
    r = client.post("/api/teams", headers=headers,
                    json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _domain(client, headers, name, *, sy_team_id=None, mail=None):
    r = client.post("/api/domains", headers=headers, json={"domain": name})
    assert r.status_code == 200, r.text
    dom_id = r.json()["id"]
    patch = {}
    if sy_team_id is not None:
        patch["sy_team_id"] = sy_team_id
    if mail is not None:
        patch["mail_addresses"] = mail
    if patch:
        r = client.put(f"/api/domains/{dom_id}", headers=headers, json=patch)
        assert r.status_code == 200, r.text
    return dom_id


def _attach(client, headers, dom_id, cert_id, mapping_type="server"):
    r = client.post(f"/api/domains/{dom_id}/certificates", headers=headers,
                    json={"certificate_id": cert_id, "mapping_type": mapping_type})
    assert r.status_code == 200, r.text


def test_deactivate_bound_cert_notifies_domain_sy_teams(client, auth_headers):
    """Bağlı domainli sertifika pasife alınınca alıcılar TEK KAYNAKTAN gelir: domainin
    SAHİBİ SY ekibinin e-postası (virgülle çoklu). domain.mail_addresses ARTIK yok sayılır."""
    team_id = _sy_team(client, auth_headers, "PasifTakim",
                       email="pasiftakim@banka.local, ops@banka.local")
    dom_id = _domain(client, auth_headers, "pasif-demo.local",
                     sy_team_id=team_id, mail="YOKSAYILMALI@banka.local")
    leaf_id = _import_leaf(client, auth_headers, "pasif-demo.local")
    _attach(client, auth_headers, dom_id, leaf_id)

    r = client.post(f"/api/certificates/{leaf_id}/deactivate", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["certificate"]["is_active"] is False
    assert body["bound_domains"] == ["pasif-demo.local"]
    assert body["teams"] == ["PasifTakim"]
    # Tek kaynak: takım e-postası (çoklu); domain.mail_addresses kullanılmaz
    assert set(body["notified_recipients"]) == {"pasiftakim@banka.local", "ops@banka.local"}
    assert "YOKSAYILMALI@banka.local" not in body["notified_recipients"]
    # SMTP kapalı → mail gitmedi ama kayıt tutuldu
    assert body["mail_sent"] is False
    assert "2 alıcı" in body["message"]

    db = SessionLocal()
    try:
        notes = db.query(Notification).filter(Notification.certificate_id == leaf_id).all()
        assert len(notes) == 1
        assert "pasiftakim@banka.local" in notes[0].recipient
        assert notes[0].days_left is None
    finally:
        db.close()


def test_deactivate_unbound_cert_no_notification(client, auth_headers):
    """Domaine bağlı olmayan sertifika pasife alınınca bilgilendirme üretilmez."""
    leaf_id = _import_leaf(client, auth_headers, "yalniz-cert.local")
    r = client.post(f"/api/certificates/{leaf_id}/deactivate", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["certificate"]["is_active"] is False
    assert body["bound_domains"] == []
    assert body["notified_recipients"] == []
    assert body["message"] == "Sertifika pasife alındı."


def test_deactivate_is_idempotent(client, auth_headers):
    """Zaten pasif sertifika yeniden bilgilendirme üretmez."""
    team_id = _sy_team(client, auth_headers, "TekrarTakim", email="tekrar@banka.local")
    dom_id = _domain(client, auth_headers, "tekrar-demo.local", sy_team_id=team_id)
    leaf_id = _import_leaf(client, auth_headers, "tekrar-demo.local")
    _attach(client, auth_headers, dom_id, leaf_id)

    r1 = client.post(f"/api/certificates/{leaf_id}/deactivate", headers=auth_headers)
    assert r1.status_code == 200 and r1.json()["bound_domains"] == ["tekrar-demo.local"]
    r2 = client.post(f"/api/certificates/{leaf_id}/deactivate", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["message"] == "Sertifika zaten pasif."
    assert r2.json()["bound_domains"] == []

    db = SessionLocal()
    try:
        notes = db.query(Notification).filter(Notification.certificate_id == leaf_id).all()
        assert len(notes) == 1  # ikinci çağrı yeni kayıt yaratmadı
    finally:
        db.close()


def test_deactivate_sends_mail_when_smtp_enabled(client, auth_headers, monkeypatch):
    """SMTP açıkken pasife alma gerçekten mail gönderir (mail_sent=True)."""
    from app.services import notifier

    sent = {}

    def fake_send(cfg, to_addresses, subject, body):
        sent["to"] = list(to_addresses)
        sent["subject"] = subject

    monkeypatch.setattr(notifier, "_send_mail", fake_send)
    monkeypatch.setattr(notifier, "get_category",
                        lambda db, category, mask_secrets=False: {
                            "enabled": True, "host": "smtp.test", "from_address": "jumbo@test"})

    team_id = _sy_team(client, auth_headers, "MailTakim", email="mailtakim@banka.local")
    dom_id = _domain(client, auth_headers, "mail-demo.local", sy_team_id=team_id)
    leaf_id = _import_leaf(client, auth_headers, "mail-demo.local")
    _attach(client, auth_headers, dom_id, leaf_id)

    r = client.post(f"/api/certificates/{leaf_id}/deactivate", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["mail_sent"] is True
    assert sent["to"] == ["mailtakim@banka.local"]
    assert "mail-demo.local" in sent["subject"] or "pasife alındı" in sent["subject"]


def test_team_email_update_admin_only(client, auth_headers):
    """Ekip e-postası PUT /teams/{id} ile güncellenir — yalnız admin."""
    team_id = _sy_team(client, auth_headers, "EpostaTakim")
    r = client.put(f"/api/teams/{team_id}", headers=auth_headers,
                   json={"email": "eposta@banka.local"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "eposta@banka.local"

    # editör kullanıcı ile 403
    client.post("/api/users", headers=auth_headers, json={
        "username": "editor_eposta", "password": "x", "role": "editor", "auth_source": "local"})
    tok = client.post("/api/auth/login-json",
                      json={"username": "editor_eposta", "password": "x"}).json()["access_token"]
    r = client.put(f"/api/teams/{team_id}", headers={"Authorization": f"Bearer {tok}"},
                   json={"email": "hack@x"})
    assert r.status_code == 403
