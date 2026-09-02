"""Uçtan uca MAIL SENARYOLARI — her senaryo için DB'ye kayıt atılır, sonra gerçek notifier
kodu SMTP taklit edilerek (monkeypatch _send_mail) çalıştırılıp alıcılar doğrulanır.

Kapsanan senaryolar:
  1. Oluşturan Ekip (sahip) — domaine bağlı olmasa bile mail alır.
  2. Bağlı domainin SY ekibi (server eşleme).
  3. Client bağımlılığı (AppDependency) olan uygulamanın SY ekibi.
  4. Trust store'a ekleyen uygulamanın SY ekibi.
  5. Aynı ekip iki kaynaktan → TEK mail (birleşme).
  6. Tekrar-önleme = 3 SAAT (resend_interval_hours): 2. çağrı atlanır, force gönderir.
  7. Yedek adres (fallback) — birincil SMTP hatasında ikinci deneme.
  8. Süresi GEÇMİŞ akışı (send_expired_notifications).
  9. Günlük tarama KAPALI (auto_expiry_enabled=false): cron atlar AMA dış API yine gönderir.
 10. Domain başına notify_days penceresi: 60g açık → mail; 15g → aynı gün-kalanda mail YOK.
 11. Tekrar-önleme KAPALI: art arda iki tarama da gönderir.
 12. Bir domain'e Server + Trusted (client) FARKLI iki sertifika bağlıyken İKİSİ de bildirilir.
 13. Bir domain'e AYNI tipten (server) iki farklı sertifika bağlıyken (rotasyon) İKİSİ de bildirilir.
 14. Bir uygulamaya client bağımlılığı + trust store FARKLI iki sertifikayla bağlıyken İKİSİ de bildirilir.
 15. notify_days penceresi aynı domain'in birden fazla sertifikasına TUTARLI (sertifika bazında) uygulanır.
"""

from datetime import datetime, timedelta

from app.db.models import (AppDependency, Application, ApplicationTrustedCert, Certificate,
                           CertificateDomainMap, Domain)
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_leaf(client, h, cn, *, days=30, nb_days_ago=25):
    """valid_to ≈ now + (days - nb_days_ago). Varsayılan: ~now+5 gün (uyarı penceresi içinde)."""
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=nb_days_ago)
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=nb, days=days, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "resend_interval_hours": 3, "auto_expiry_enabled": True,
           "queue_enabled": False, "fallback_address": ""}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch, *, fail_substr=None):
    """notifier._send_mail'i taklit et: alıcıları topla. fail_substr verilirse o adresi içeren
    gönderimde hata FIRLAT (yedek-adres yolunu tetiklemek için)."""
    sent: list[dict] = []

    def fake(cfg, to, subject, body, html=None):
        if fail_substr and any(fail_substr in a for a in to):
            raise RuntimeError("primary down (test)")
        sent.append({"to": list(to), "subject": subject})
    monkeypatch.setattr(notifier, "_send_mail", fake)
    return sent


def _seed(fn):
    db = SessionLocal()
    try:
        r = fn(db)
        db.commit()
        return r
    finally:
        db.close()


def _run(fn=None, **kw):
    db = SessionLocal()
    try:
        return (fn or notifier.send_expiry_notifications)(db, **kw)
    finally:
        db.close()


def _got(sent, addr):
    return any(addr in m["to"] for m in sent)


# 1 — Oluşturan Ekip (domaine bağlı olmasa bile)
def test_scn_creator_team(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN Creator SY", "scn-creator@test")
    cid = _import_leaf(client, h, "scn-creator.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN Creator SY"))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "scn-creator@test")


# 2 — Bağlı domainin SY ekibi
def test_scn_domain_bound(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN Domain SY", "scn-domain@test")
    cid = _import_leaf(client, h, "scn-domain-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        d = Domain(domain="scn-dom.test", sy_team_id=tid)
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=d.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "scn-domain@test")


# 3 — Client bağımlılığı olan uygulamanın SY ekibi
def test_scn_client_dependency(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN Dep SY", "scn-dep@test")
    cid = _import_leaf(client, h, "scn-dep-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        d = Domain(domain="scn-dep-target.test")
        db.add(d); db.flush()
        app = Application(app_name="SCN Dep App", server_name="srv", sy_team_id=tid, status=True)
        db.add(app); db.flush()
        db.add(AppDependency(app_id=app.id, target_domain_id=d.id, client_cert_id=cid))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "scn-dep@test")


# 4 — Trust store'a ekleyen uygulamanın SY ekibi
def test_scn_trust_store(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN Trust SY", "scn-trust@test")
    cid = _import_leaf(client, h, "scn-trust-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        app = Application(app_name="SCN Trust App", server_name="srv", sy_team_id=tid, status=True)
        db.add(app); db.flush()
        db.add(ApplicationTrustedCert(app_id=app.id, cert_id=cid))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "scn-trust@test")


# 5 — Aynı ekip iki kaynaktan (oluşturan + domain) → TEK mail
def test_scn_same_team_single_mail(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN Merge SY", "scn-merge@test")
    cid = _import_leaf(client, h, "scn-merge-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = "SCN Merge SY"
        d = Domain(domain="scn-merge-dom.test", sy_team_id=tid)
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=d.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "scn-merge@test" in m["to"]]
    assert len(hits) == 1, f"aynı ekip TEK mail almalı, {len(hits)} geldi"


# 6 — Tekrar-önleme = 3 saat
def test_scn_dedup_3h(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN Dedup SY", "scn-dedup@test")
    cid = _import_leaf(client, h, "scn-dedup-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN Dedup SY"))
    _set_smtp(client, h)  # resend_interval_hours=3
    sent = _capture(monkeypatch)

    _run(force=False)                       # ilk gönderim → dedup kaydı yazılır
    assert _got(sent, "scn-dedup@test")
    sent.clear()
    _run(force=False)                       # 3 saat içinde tekrar → ATLANIR
    assert not _got(sent, "scn-dedup@test"), "3 saat içinde tekrar mail GİTMEMELİ"
    sent.clear()
    _run(force=True)                        # force → yine gönderir
    assert _got(sent, "scn-dedup@test")


# 7 — Yedek adres (fallback)
def test_scn_fallback(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN FB SY", "scn-primary@test")
    cid = _import_leaf(client, h, "scn-fb-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN FB SY"))
    _set_smtp(client, h, fallback_address="scn-fallback@test")
    sent = _capture(monkeypatch, fail_substr="scn-primary@test")
    _run(force=True)
    assert _got(sent, "scn-fallback@test"), "birincil hata → yedek adrese gitmeli"
    assert not _got(sent, "scn-primary@test")


# 8 — Süresi GEÇMİŞ akışı
def test_scn_expired(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN Expired SY", "scn-expired@test")
    cid = _import_leaf(client, h, "scn-expired-cert.test", days=10, nb_days_ago=40)  # valid_to ~ now-30
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN Expired SY"))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(notifier.send_expired_notifications, force=True)
    assert _got(sent, "scn-expired@test")


# 9 — Günlük tarama KAPALI: cron atlar, dış API yine gönderir
def test_scn_auto_expiry_toggle(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN Toggle SY", "scn-toggle@test")
    cid = _import_leaf(client, h, "scn-toggle-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN Toggle SY"))
    _set_smtp(client, h, auto_expiry_enabled=False)
    sent = _capture(monkeypatch)

    notifier.check_expiring_certificates()   # ZAMANLANMIŞ cron yolu → kapalı → hiç mail yok
    assert sent == [], "günlük tarama kapalıyken cron mail ATMAMALI"

    _run(force=True)                         # DIŞ API yolu (doğrudan çağrı) → yine gönderir
    assert _got(sent, "scn-toggle@test"), "API tetiği kapalı bayraktan etkilenmemeli"


# 11 — Tekrar-önleme KAPALI: art arda iki tarama da gönderir (dedup atlanır)
def test_scn_dedup_disabled(client, auth_headers, monkeypatch):
    h = auth_headers
    _team(client, h, "SCN NoDedup SY", "scn-nodedup@test")
    cid = _import_leaf(client, h, "scn-nodedup-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "SCN NoDedup SY"))
    _set_smtp(client, h, resend_dedup_enabled=False)
    sent = _capture(monkeypatch)

    _run(force=False)                       # ilk gönderim
    assert _got(sent, "scn-nodedup@test")
    sent.clear()
    _run(force=False)                       # dedup kapalı → yine gönderir (3 saat geçmeden)
    assert _got(sent, "scn-nodedup@test"), "dedup kapalıyken ikinci tarama da mail göndermeli"


# 10 — Domain başına notify_days penceresi
def test_scn_notify_days_window(client, auth_headers, monkeypatch):
    h = auth_headers
    ta = _team(client, h, "SCN WinA SY", "scn-wina@test")
    tb = _team(client, h, "SCN WinB SY", "scn-winb@test")
    cida = _import_leaf(client, h, "scn-wina.test", days=75, nb_days_ago=25)  # valid_to ~ now+50
    cidb = _import_leaf(client, h, "scn-winb.test", days=75, nb_days_ago=25)

    def seed(db):
        db.get(Certificate, cida).creator = None
        db.get(Certificate, cidb).creator = None
        da = Domain(domain="scn-wina-dom.test", sy_team_id=ta, notify_days=60)
        dbb = Domain(domain="scn-winb-dom.test", sy_team_id=tb, notify_days=15)
        db.add_all([da, dbb]); db.flush()
        db.add(CertificateDomainMap(certificate_id=cida, domain_id=da.id, mapping_type="server"))
        db.add(CertificateDomainMap(certificate_id=cidb, domain_id=dbb.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "scn-wina@test"), "50g kalan, 60g penceresi → mail gitmeli"
    assert not _got(sent, "scn-winb@test"), "50g kalan, 15g penceresi → mail GİTMEMELİ (geçit)"


# 12 — Bir domain'e BİRDEN FAZLA farklı sertifika (Server + Trusted/client) bağlıyken HER İKİSİ
# için de ayrı bildirim gitmeli (dispatch sertifika bazında döner, domain bazında değil).
def test_scn_domain_multiple_certs_server_and_trusted_both_notify(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN MultiType SY", "scn-multitype@test")
    cid_server = _import_leaf(client, h, "scn-multitype-server.test")
    cid_client = _import_leaf(client, h, "scn-multitype-client.test")

    def seed(db):
        db.get(Certificate, cid_server).creator = None
        db.get(Certificate, cid_client).creator = None
        d = Domain(domain="scn-multitype-dom.test", sy_team_id=tid)
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid_server, domain_id=d.id, mapping_type="server"))
        db.add(CertificateDomainMap(certificate_id=cid_client, domain_id=d.id, mapping_type="client"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "scn-multitype@test" in m["to"]]
    subjects = {m["subject"] for m in hits}
    assert any("scn-multitype-server.test" in s for s in subjects), \
        f"Server sertifikası için mail gitmedi: {subjects}"
    assert any("scn-multitype-client.test" in s for s in subjects), \
        f"Trusted (client) sertifikası için mail gitmedi: {subjects}"
    assert len(hits) == 2, f"2 farklı sertifika → 2 AYRI mail beklenirdi, {len(hits)} geldi"


# 13 — Bir domain'e AYNI mapping_type'tan (server) BİRDEN FAZLA farklı sertifika bağlıyken
# (ör. rotasyon sırasında eski+yeni birlikte) HER İKİSİ de bildirilmeli.
def test_scn_domain_multiple_certs_same_type_both_notify(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN MultiSame SY", "scn-multisame@test")
    cid_old = _import_leaf(client, h, "scn-multisame-old.test")
    cid_new = _import_leaf(client, h, "scn-multisame-new.test")

    def seed(db):
        db.get(Certificate, cid_old).creator = None
        db.get(Certificate, cid_new).creator = None
        d = Domain(domain="scn-multisame-dom.test", sy_team_id=tid)
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid_old, domain_id=d.id, mapping_type="server"))
        db.add(CertificateDomainMap(certificate_id=cid_new, domain_id=d.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "scn-multisame@test" in m["to"]]
    subjects = {m["subject"] for m in hits}
    assert any("scn-multisame-old.test" in s for s in subjects)
    assert any("scn-multisame-new.test" in s for s in subjects)
    assert len(hits) == 2, f"aynı tipten 2 farklı sertifika → 2 AYRI mail beklenirdi, {len(hits)} geldi"


# 14 — Bir uygulamaya HEM client bağımlılığı (AppDependency.client_cert) HEM trust store
# (ApplicationTrustedCert) ile FARKLI iki sertifika bağlıyken ikisi de bildirilmeli.
def test_scn_app_multiple_cert_bindings_both_notify(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN AppMulti SY", "scn-appmulti@test")
    cid_dep = _import_leaf(client, h, "scn-appmulti-dep.test")
    cid_trust = _import_leaf(client, h, "scn-appmulti-trust.test")

    def seed(db):
        db.get(Certificate, cid_dep).creator = None
        db.get(Certificate, cid_trust).creator = None
        d = Domain(domain="scn-appmulti-target.test")
        db.add(d); db.flush()
        app = Application(app_name="SCN AppMulti App", server_name="srv", sy_team_id=tid, status=True)
        db.add(app); db.flush()
        db.add(AppDependency(app_id=app.id, target_domain_id=d.id, client_cert_id=cid_dep))
        db.add(ApplicationTrustedCert(app_id=app.id, cert_id=cid_trust))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "scn-appmulti@test" in m["to"]]
    subjects = {m["subject"] for m in hits}
    assert any("scn-appmulti-dep.test" in s for s in subjects), \
        f"AppDependency (client_cert) sertifikası için mail gitmedi: {subjects}"
    assert any("scn-appmulti-trust.test" in s for s in subjects), \
        f"Trust store sertifikası için mail gitmedi: {subjects}"
    assert len(hits) == 2, f"2 farklı bağlantı türü → 2 AYRI mail beklenirdi, {len(hits)} geldi"


# 15 — notify_days penceresi, AYNI domain'in BİRDEN FAZLA sertifikasına TUTARLI uygulanır:
# pencereye giren sertifika bildirilir, girmeyen (aynı domain/ekip olsa dahi) bildirilmez.
def test_scn_notify_days_applies_per_cert_on_same_domain(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "SCN PerCertWin SY", "scn-percertwin@test")
    # 60 günlük pencere: ~10 gün kalan sertifika GİRER, ~50 gün kalan GİRMEZ (global 30 da girmez)
    cid_soon = _import_leaf(client, h, "scn-percertwin-soon.test", days=40, nb_days_ago=30)  # ~10g kaldı
    cid_far = _import_leaf(client, h, "scn-percertwin-far.test", days=75, nb_days_ago=25)    # ~50g kaldı

    def seed(db):
        db.get(Certificate, cid_soon).creator = None
        db.get(Certificate, cid_far).creator = None
        d = Domain(domain="scn-percertwin-dom.test", sy_team_id=tid, notify_days=15)
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid_soon, domain_id=d.id, mapping_type="server"))
        db.add(CertificateDomainMap(certificate_id=cid_far, domain_id=d.id, mapping_type="client"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "scn-percertwin@test" in m["to"]]
    subjects = {m["subject"] for m in hits}
    assert any("scn-percertwin-soon.test" in s for s in subjects), \
        f"15g penceresi içindeki sertifika bildirilmedi: {subjects}"
    assert not any("scn-percertwin-far.test" in s for s in subjects), \
        f"15g penceresi DIŞINDAKİ sertifika yanlışlıkla bildirildi: {subjects}"
