"""SERTİFİKASIZ (server tipi AKTİF sertifikası olmayan) domainler için yalnız manuel
"Bitiş Tarihi" (Domain.expire_date) alanına dayalı hatırlatma maili senaryoları.

Kök neden: notifier.send_expiry_notifications/send_expired_notifications tarihsel olarak
SADECE Certificate.valid_to'yu taradığı için, sertifikası hiç eklenmemiş ama manuel bitiş
tarihi girilmiş domainler hiç bildirim ALMIYORDU. Bu dosya notifier._dispatch_domain_mails
yolunu (bkz. notifier.py) uçtan uca doğrular.

Kapsanan senaryolar:
  1. Server sertifikası olmayan, expire_date yakın domain → süre-uyarı maili gider.
  2. Aynı domain expire_date geçmişte → süresi-geçmiş maili gider.
  3. Domain'e AKTİF server sertifikası de eşliyken: yalnız cert-akışından mail gider,
     domain-only akış ÇİFT göndermez (regresyon guard'ı).
  4. Domain yalnız client/trusted eşlemesine sahip (server sertifikası YOK) → yine
     domain-only akıştan mail gider (server-only exclusion kararının testi).
  5. Dedup/resend penceresi: art arda iki force=False çağrısında ikinci atlanır;
     force=True yine gönderir.
  6. sy_team_id=None olan domain → crash yok, mail gitmez.
  7. notify_days penceresi domain-only akışta da geçerli.
"""

from datetime import datetime, timedelta

from app.db.models import Certificate, CertificateDomainMap, Domain
from app.services import notifier
from tests.test_mail_scenarios import _capture, _got, _import_leaf, _run, _seed, _set_smtp, _team


# 1 — Server sertifikası olmayan, expire_date yakın domain → süre-uyarı maili
def test_dom_expiring_soon_sent(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "DOM Soon SY", "dom-soon@test")
    _seed(lambda db: db.add(Domain(domain="dom-soon.test", sy_team_id=tid,
                                   expire_date=datetime.utcnow() + timedelta(days=5))))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "dom-soon@test")


# 2 — Aynı domain, süresi geçmiş → süresi-geçmiş akışı
def test_dom_already_expired_sent(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "DOM Expired SY", "dom-expired@test")
    _seed(lambda db: db.add(Domain(domain="dom-expired.test", sy_team_id=tid,
                                   expire_date=datetime.utcnow() - timedelta(days=5))))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(notifier.send_expired_notifications, force=True)
    assert _got(sent, "dom-expired@test")


# 3 — Domain'e AKTİF server sertifikası eşliyken domain-only akış ÇİFT göndermemeli
def test_dom_with_active_server_cert_excluded(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "DOM WithCert SY", "dom-withcert@test")
    cid = _import_leaf(client, h, "dom-withcert-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        d = Domain(domain="dom-withcert.test", sy_team_id=tid,
                   expire_date=datetime.utcnow() + timedelta(days=5))
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=d.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    hits = [m for m in sent if "dom-withcert@test" in m["to"]]
    assert len(hits) == 1, f"aktif server sertifikası VARKEN TEK mail (cert-akışından) beklenirdi, {len(hits)} geldi"
    assert any("dom-withcert-cert.test" in m["subject"] for m in hits), \
        "gelen mail cert-akışının konusunu taşımalı (sertifika adı içermeli)"
    assert not any("dom-withcert.test (" in m["subject"] for m in hits), \
        "domain-only akış subject'i de gelmemeli (çift gönderim)"


# 4 — Domain yalnız client/trusted eşlemesine sahip (server sertifikası YOK) → yine
# domain-only akıştan mail gitmeli (server-only exclusion kararı)
def test_dom_client_only_mapping_still_notifies(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "DOM ClientOnly SY", "dom-clientonly@test")
    cid = _import_leaf(client, h, "dom-clientonly-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        d = Domain(domain="dom-clientonly.test", sy_team_id=tid,
                   expire_date=datetime.utcnow() + timedelta(days=5))
        db.add(d); db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=d.id, mapping_type="client"))
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "dom-clientonly@test"), \
        "yalnız client/trusted eşlemesi olan domain (server sertifikası yok) manuel tarihle bildirilmeli"


# 5 — Dedup/resend penceresi domain-only akışta da geçerli
def test_dom_dedup_resend_window(client, auth_headers, monkeypatch):
    h = auth_headers
    tid = _team(client, h, "DOM Dedup SY2", "dom-dedup2@test")
    _seed(lambda db: db.add(Domain(domain="dom-dedup2.test", sy_team_id=tid,
                                   expire_date=datetime.utcnow() + timedelta(days=5))))
    _set_smtp(client, h)  # resend_interval_hours=3
    sent = _capture(monkeypatch)

    _run(force=False)                       # ilk gönderim → dedup kaydı yazılır
    assert _got(sent, "dom-dedup2@test")
    sent.clear()
    _run(force=False)                       # 3 saat içinde tekrar → ATLANIR
    assert not _got(sent, "dom-dedup2@test"), "3 saat içinde tekrar mail GİTMEMELİ"
    sent.clear()
    _run(force=True)                        # force → yine gönderir
    assert _got(sent, "dom-dedup2@test")


# 6 — sy_team_id=None → crash yok, mail gitmez
def test_dom_no_sy_team_skipped(client, auth_headers, monkeypatch):
    h = auth_headers
    _seed(lambda db: db.add(Domain(domain="dom-noteam.test", sy_team_id=None,
                                   expire_date=datetime.utcnow() + timedelta(days=5))))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    result = _run(force=True)
    assert result["enabled"] is True
    assert not any("dom-noteam.test" in (m.get("subject") or "") for m in sent)


# 7 — notify_days penceresi domain-only akışta da geçerli
def test_dom_notify_days_window(client, auth_headers, monkeypatch):
    h = auth_headers
    ta = _team(client, h, "DOM WinA SY", "dom-wina@test")
    tb = _team(client, h, "DOM WinB SY", "dom-winb@test")

    def seed(db):
        da = Domain(domain="dom-wina.test", sy_team_id=ta, notify_days=60,
                    expire_date=datetime.utcnow() + timedelta(days=50))
        dbb = Domain(domain="dom-winb.test", sy_team_id=tb, notify_days=15,
                     expire_date=datetime.utcnow() + timedelta(days=50))
        db.add_all([da, dbb])
    _seed(seed)
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert _got(sent, "dom-wina@test"), "50g kalan, 60g penceresi → mail gitmeli"
    assert not _got(sent, "dom-winb@test"), "50g kalan, 15g penceresi → mail GİTMEMELİ (geçit)"
