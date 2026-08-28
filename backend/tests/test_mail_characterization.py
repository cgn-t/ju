"""FAZ 1 — Mail sistemi karakterizasyon/regresyon testleri (şablon birleştirme refactor'ünden ÖNCE).

Amaç: mevcut davranışı kilitlemek, sonra Faz 2 refactor'ünün regresyona yol açmadığını kanıtlamak.

Kapsanan konular:
  1. Paydaş açlığı — BİLİNEN BUG: _dispatch_cert_mails dedup kontrolü sertifika bazında yapılıyor,
     paydaş bazında değil. Bu test DOĞRU-BEKLENEN davranışı yazıyor; Faz 2 refactor'üne kadar
     KIRMIZI kalması beklenir (bilinçli — kod tabanında xfail/skip konvansiyonu yok).
  2. Scheduler job envanteri — hangi job'ların zamanlandığını kilitler (expired-check'in
     BİLİNÇLİ OLARAK cron'da olmadığı dahil).
  3. Mail kuyruğu (mail_queue) drain hata senaryosu — art arda başarısızlıkta attempts artışı
     ve 5. denemede kalıcı 'failed' olma.
  4. SMTP için ayrı bir "test maili gönder" ucunun OLMADIĞININ doğrulanması.
  5. STARTTLS-only davranışı — use_tls açık/kapalıyken starttls() çağrılıp çağrılmadığı ve
     implicit-SSL (smtplib.SMTP_SSL) desteğinin hiç kullanılmadığı.
"""

from datetime import datetime, timedelta

from app.db.models import (Certificate, CertificateDomainMap, Domain, MailQueue)
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
    gönderimde hata FIRLAT (yedek-adres / retry yolunu tetiklemek için)."""
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


# ---------------------------------------------------------------------------
# 1. Paydaş açlığı — bilinen bug, Faz 2'ye kadar KIRMIZI
# ---------------------------------------------------------------------------

def test_scn_partial_failure_retries_only_failed_stakeholder(client, auth_headers, monkeypatch):
    """Sertifika X'in 2 paydaşı var (A ekibi, B ekibi). 1. taramada A'ya mail BAŞARILI gider
    (Notification kaydı yazılır), B'ye SMTP hatasıyla BAŞARISIZ olur (Notification YAZILMAZ,
    yalnız mail_queue'ya 'failed' düşer). 2. taramada (aynı 3 saatlik dedup penceresinde,
    force=False): A dedup ile ATLANMALI (zaten mail aldı), B RETRY ALMALI (ilk denemesi hiç
    başarılı olmadı). ŞU AN: _dispatch_cert_mails dedup kontrolü sertifika bazında yapıldığı
    için A'nın Notification kaydı B'yi de bloke ediyor — bu test Faz 2 refactor'üne (paydaş
    bazlı dedup) kadar KIRMIZI kalması beklenen bilinçli bir karakterizasyon testidir."""
    h = auth_headers
    ta = _team(client, h, "SCN Starve A", "starve-a@test")
    tb = _team(client, h, "SCN Starve B", "starve-b@test")
    cid = _import_leaf(client, h, "scn-starve-cert.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        da = Domain(domain="starve-a-dom.test", sy_team_id=ta)
        dbb = Domain(domain="starve-b-dom.test", sy_team_id=tb)
        db.add_all([da, dbb])
        db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=da.id, mapping_type="server"))
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=dbb.id, mapping_type="server"))
    _seed(seed)
    _set_smtp(client, h)  # resend_interval_hours=3, dedup açık (varsayılan)

    # 1. tarama: B başarısız olsun
    sent = _capture(monkeypatch, fail_substr="starve-b@test")
    _run(force=False)
    assert _got(sent, "starve-a@test"), "A ilk taramada mail almalı"
    assert not _got(sent, "starve-b@test"), "B ilk taramada başarısız olmalı (test kurgusu)"

    # 2. tarama (aynı dedup penceresinde, force=False, artık SMTP hatası yok): A atlanmalı, B retry almalı
    sent2 = _capture(monkeypatch)
    _run(force=False)
    assert not _got(sent2, "starve-a@test"), "A zaten mail aldı, dedup penceresinde tekrar gitmemeli"
    assert _got(sent2, "starve-b@test"), (
        "B'nin ilk denemesi başarısızdı, retry alması gerekir "
        "(BİLİNEN BUG — paydaş açlığı, Faz 2'de düzelecek)")


# ---------------------------------------------------------------------------
# 2. Scheduler job envanteri
# ---------------------------------------------------------------------------

def test_scheduler_job_inventory(client):
    """conftest'in session-scope client fixture'ı (`with TestClient(app) as c`) FastAPI
    lifespan'ını (main.py: start_scheduler) tetikliyor → notifier.scheduler GERÇEKTEN running
    ve job'lu. Bu test mevcut job envanterini kilitler — yeni bir job eklenir/silinirse bilinçli
    bir değişiklik olmalı. `expired-check` gibi bir job'ın OLMADIĞI ayrıca doğrulanır: süresi-geçmiş
    bildirimi bilinçli olarak yalnız API'den (/api/notifications/expired-run) tetiklenir."""
    assert notifier.scheduler.running
    job_ids = {j.id for j in notifier.scheduler.get_jobs()}
    expected = {"expiry-check", "proposal-reminder", "live-check",
                "discovery-scan", "ct-scan", "revocation-check", "mail-queue-drain"}
    assert job_ids == expected, f"job envanteri değişti: {job_ids}"
    assert "expired-check" not in job_ids, (
        "süresi-geçmiş bildirimi BİLİNÇLİ OLARAK cron'da YOK — yalnız API ile tetiklenir")

    expiry_job = next(j for j in notifier.scheduler.get_jobs() if j.id == "expiry-check")
    field_map = {f.name: str(f) for f in expiry_job.trigger.fields}
    assert field_map["hour"] == "8" and field_map["minute"] == "0"


# ---------------------------------------------------------------------------
# 3. Mail kuyruğu drain hata senaryosu
# ---------------------------------------------------------------------------

def test_queue_drain_failure_increments_attempts_then_fails_at_five(client, auth_headers, monkeypatch):
    """Bir MailQueue satırı 'pending' olarak seed edilir; gönderim her seferinde hata fırlatır.
    attempts her denemede +1 artmalı, 5. denemede status='failed' olup last_error dolmalı,
    ve 'failed' olduktan sonraki drain çağrıları bu satırı BİR DAHA DENEMEMELİ."""
    h = auth_headers
    _set_smtp(client, h, queue_enabled=True)

    def seed(db):
        mq = MailQueue(to_addresses="drain-fail@test", subject="s", body_text="b")
        db.add(mq)
        db.flush()
        return mq.id
    row_id = _seed(seed)

    def fail_send(cfg, to, subject, body, html=None):
        if any("drain-fail@test" in a for a in to):
            raise RuntimeError("smtp down (test)")
    monkeypatch.setattr(notifier, "_send_mail", fail_send)

    db = SessionLocal()
    try:
        for i in range(1, 5):
            notifier.drain_mail_queue(db)
            row = db.get(MailQueue, row_id)
            assert row.attempts == i, f"deneme {i}: attempts={row.attempts}"
            assert row.status == "pending", f"deneme {i}: henüz 'failed' olmamalı"

        notifier.drain_mail_queue(db)  # 5. deneme
        row = db.get(MailQueue, row_id)
        assert row.attempts == 5
        assert row.status == "failed"
        assert row.last_error and "smtp down" in row.last_error

        attempts_after_five = row.attempts
        notifier.drain_mail_queue(db)  # 6. drain — 'failed' satır bir daha denenmemeli
        row = db.get(MailQueue, row_id)
        assert row.attempts == attempts_after_five, "failed satır tekrar denenmemeli"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. SMTP test-mail endpoint'inin yokluğu
# ---------------------------------------------------------------------------

def test_smtp_has_no_notify_test_endpoint(client, auth_headers):
    """SMTP kanalı app/services/notify/CHANNELS listesinde YOK (yalnız slack/teams/webhook/
    servicenow/jira/zoom/jabber var) → /api/settings/smtp/notify-test 404 döner. Bu, SMTP
    testi için AYRI bir uç (gerçek test-mail gönderimi) OLMADIĞINI belgeleyen negatif testtir;
    ileride eklenirse bu test bilinçli güncellenmeli."""
    r = client.post("/api/settings/smtp/notify-test", headers=auth_headers)
    assert r.status_code == 404, (
        "SMTP notify-test ucu eklenmiş görünüyor — bu testin kaldırılması/güncellenmesi gerekir")


# ---------------------------------------------------------------------------
# 5. STARTTLS-only davranış
# ---------------------------------------------------------------------------

class _FakeSMTP:
    """smtplib.SMTP yerine geçen, context-manager destekli sahte istemci."""
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.starttls_called = False
        self.login_called = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, u, p):
        self.login_called = (u, p)

    def sendmail(self, frm, to, msg):
        self.sent = (frm, to, msg)


def test_send_mail_starttls_only_when_use_tls_true(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(notifier.smtplib, "SMTP", _FakeSMTP)
    cfg = {"host": "h", "port": 25, "from_address": "f@test", "use_tls": True}
    notifier._send_mail(cfg, ["x@test"], "subj", "body")
    assert _FakeSMTP.instances[-1].starttls_called is True


def test_send_mail_no_starttls_when_use_tls_false(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(notifier.smtplib, "SMTP", _FakeSMTP)
    cfg = {"host": "h", "port": 25, "from_address": "f@test", "use_tls": False}
    notifier._send_mail(cfg, ["x@test"], "subj", "body")
    assert _FakeSMTP.instances[-1].starttls_called is False


def test_send_mail_no_implicit_ssl_support_documented(monkeypatch):
    """DOKÜMANTASYON TESTİ: _send_mail her zaman smtplib.SMTP (plaintext/STARTTLS) kullanır;
    implicit-SSL (port 465, smtplib.SMTP_SSL) yolu hiç yok — use_tls=False + port=465 verilse
    bile SMTP_SSL asla çağrılmaz (bilinen sınırlama, gerçek 465 sunucusuna karşı bu PATLAR)."""
    monkeypatch.setattr(notifier.smtplib, "SMTP", _FakeSMTP)
    ssl_calls = []
    monkeypatch.setattr(notifier.smtplib, "SMTP_SSL",
                        lambda *a, **k: (ssl_calls.append((a, k)), _FakeSMTP(*a, **k))[-1])
    notifier._send_mail({"host": "h", "port": 465, "from_address": "f@test"}, ["x@test"], "s", "b")
    assert not ssl_calls, "SMTP_SSL hiç çağrılmamalı — implicit-SSL desteği yok (bilinen sınırlama)"
