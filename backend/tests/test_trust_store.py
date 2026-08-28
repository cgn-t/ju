"""R4a/R4b — Uygulama trust store + halef 'trusted ekle' onayı.

- Trust store CRUD (ekle / listele / mükerrer 409).
- Trust store'daki sertifikanın süresi yaklaşınca uygulamanın SY ekibine mail (notifier 4. paydaş).
- Halef sertifika import edilince DEVİR değil 'trusted_add' önerisi üretilir; onaylanınca yeni
  sertifika trust store'a eklenir, ESKİ trusted KALIR (ikisi de) ve eski AKTİF kalır.
"""

from datetime import datetime, timedelta

from app.db.models import Certificate
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _sy_team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _app(client, h, name, sy_team_id):
    r = client.post("/api/applications", headers=h,
                    json={"app_name": name, "server_name": name, "sy_team_id": sy_team_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import(client, h, pem_text, *, supersede=False):
    return client.post("/api/certificates/import", headers=h,
                       files={"file": ("c.pem", pem_text.encode(), "application/x-pem-file")},
                       data={"supersede": "true"} if supersede else {})


def _set_smtp(client, h, **over):
    # queue_enabled=False AÇIKÇA: önceki testler kuyruğu açık bırakmış olabilir (session-scoped
    # ayarlar) → doğrudan gönderim için sıfırla, yoksa mailler mail_queue'ya düşer.
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "queue_enabled": False}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def test_trusted_store_crud_and_notify(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Trust-A", "trust-a@test")
    app_id = _app(client, h, "TrustApp-A", tid)
    ca, ca_key = certgen.make_ca("Trust CA A")
    nb = datetime.utcnow() - timedelta(days=20)                # valid_to ~ now + 10 gün
    leaf, _ = certgen.make_leaf(ca, ca_key, "trusta.test", not_before=nb, days=30, san=["trusta.test"])
    r = _import(client, h, certgen.pem(leaf) + certgen.pem(ca))
    assert r.status_code == 200, r.text
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    # trust store'a ekle → listele → mükerrer 409
    r = client.post(f"/api/applications/{app_id}/trusted", headers=h,
                    json={"certificate_id": leaf_id, "note": "kök CA güveni"})
    assert r.status_code == 200, r.text
    lst = client.get(f"/api/applications/{app_id}/trusted", headers=h).json()
    assert any(t["cert_id"] == leaf_id for t in lst)
    r = client.post(f"/api/applications/{app_id}/trusted", headers=h, json={"certificate_id": leaf_id})
    assert r.status_code == 409, r.text

    # süre-uyarı maili uygulamanın SY ekibine gider (domaine bağlı olmasa bile)
    _set_smtp(client, h)
    sent = []
    monkeypatch.setattr(notifier, "_send_mail",
                        lambda cfg, to, subject, body, html=None: sent.append(list(to)))
    db = SessionLocal()
    try:
        notifier.send_expiry_notifications(db, force=True)
    finally:
        db.close()
    assert any("trust-a@test" in to for to in sent), f"trust store ekibi mail almalıydı: {sent}"


def test_trusted_add_proposal_keeps_old(client, auth_headers):
    h = auth_headers
    tid = _sy_team(client, h, "SY-Trust-B", "trust-b@test")
    app_id = _app(client, h, "TrustApp-B", tid)
    ca, ca_key = certgen.make_ca("Trust CA B")
    key = certgen.make_key()                                   # aynı anahtar → aynı SKI → halef sinyali
    v1, _ = certgen.make_leaf(ca, ca_key, "trustb.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "trustb.test", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    # v1'i trust store'a ekle
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": v1_id}).status_code == 200

    # halef v2'yi supersede=true ile import → DEVİR değil trusted_add önerisi
    r2 = _import(client, h, certgen.pem(v2), supersede=True)
    assert r2.status_code == 200, r2.text
    v2_id = r2.json()[0]["id"]
    props = client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
    ta = [p for p in props if p.get("kind") == "trusted_add"
          and p["new_cert_id"] == v2_id and p["app_id"] == app_id]
    assert ta, f"trusted_add önerisi yok: {[(p.get('kind'), p['new_cert_id'], p.get('app_id')) for p in props]}"

    # onayla → v2 trust store'a eklendi, v1 HÂLÂ trusted (ikisi de), v1 AKTİF kaldı
    assert client.post(f"/api/proposals/{ta[0]['id']}/approve", headers=h).status_code == 200
    ids = {t["cert_id"] for t in client.get(f"/api/applications/{app_id}/trusted", headers=h).json()}
    assert v1_id in ids and v2_id in ids, f"eski+yeni birlikte trusted olmalı: {ids}"
    db = SessionLocal()
    try:
        assert db.get(Certificate, v1_id).is_active is True, "eski trusted pasife alınmamalı"
    finally:
        db.close()


def test_backfill_no_phantom_trusted_add(client, auth_headers):
    """Bug #4 regresyonu: v1 hem domaine SERVER eşli HEM trust store'da. Halef onaylanınca eski
    trusted olduğu için AKTİF kalır → startup backfill onu seçer. Backfill, ZATEN UYGULANMIŞ
    trusted_add grain'ini yeniden ÖNERMEMELİ (onay kuyruğunda phantom oluşturmamalı)."""
    from app.main import backfill_transfer_proposals
    h = auth_headers
    tid = _sy_team(client, h, "SY-Backfill", "bf@test")
    app_id = _app(client, h, "BackfillApp", tid)
    ca, ca_key = certgen.make_ca("Backfill CA")
    key = certgen.make_key()                                   # ortak anahtar → halef sinyali
    v1, _ = certgen.make_leaf(ca, ca_key, "bf.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "bf.test", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    dom = client.post("/api/domains", headers=h, json={"domain": "bf.test"}).json()["id"]
    client.post(f"/api/domains/{dom}/certificates", headers=h,
                json={"certificate_id": v1_id, "mapping_type": "server"})   # server eşle
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": v1_id}).status_code == 200   # + trust store

    v2_id = _import(client, h, certgen.pem(v2), supersede=True).json()[0]["id"]
    for p in client.get("/api/proposals", headers=h, params={"status": "pending"}).json():
        if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id:         # transfer + trusted_add
            assert client.post(f"/api/proposals/{p['id']}/approve", headers=h).status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Certificate, v1_id).is_active is True, "trusted → eski aktif kalır (backfill seçer)"
    finally:
        db.close()

    backfill_transfer_proposals()   # startup simülasyonu
    pend = client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
    phantom = [p for p in pend if p["new_cert_id"] == v2_id and p["old_cert_id"] == v1_id]
    assert phantom == [], f"backfill uygulanmış trusted_add'i yeniden önermemeli (phantom): {phantom}"


def test_trusted_add_proposal_rehomed_on_team_change(client, auth_headers):
    """Bug #5 regresyonu: uygulamanın SY ekibi değişince trusted_add önerisi de YENİ ekibe taşınır
    (re-home yalnız mTLS dep önerilerini değil). Aksi halde öneri eski ekipte kalır: yeni sahip
    onaylayamaz (403), eski sahip artık sahibi olmadığı uygulamaya cert ekleyebilirdi."""
    h = auth_headers
    t1 = _sy_team(client, h, "SY-Rehome-1", "rh1@test")
    t2 = _sy_team(client, h, "SY-Rehome-2", "rh2@test")
    app_id = _app(client, h, "RehomeApp", t1)
    ca, ca_key = certgen.make_ca("Rehome CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "rehome.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "rehome.test", key=key, not_before=datetime(2026, 6, 1))
    v1_id = next(c["id"] for c in _import(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    assert client.post(f"/api/applications/{app_id}/trusted", headers=h,
                       json={"certificate_id": v1_id}).status_code == 200
    v2_id = _import(client, h, certgen.pem(v2), supersede=True).json()[0]["id"]

    def _ta():
        return next(p for p in client.get("/api/proposals", headers=h,
                                          params={"status": "pending"}).json()
                    if p.get("kind") == "trusted_add" and p["new_cert_id"] == v2_id
                    and p["app_id"] == app_id)
    assert _ta()["sy_team_id"] == t1, "öneri başlangıçta T1'de"

    # uygulamayı T2'ye devret → trusted_add önerisi de T2'ye taşınmalı
    assert client.put(f"/api/applications/{app_id}", headers=h,
                      json={"sy_team_id": t2}).status_code == 200
    assert _ta()["sy_team_id"] == t2, "trusted_add önerisi yeni sahibe (T2) taşınmalı"
