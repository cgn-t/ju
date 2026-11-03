"""Dış mail tetiklemesinde hata (v3.9.30).

  • "E-posta Bildirimleri Etkin" kapalıysa ya da mail sunucusu tanımsızsa dış tetik (X-API-Key)
    tarama başlatmaz, hemen 503 döner. Ekrandaki "Şimdi Gönder" (admin) bugünkü gibi 200 + mesaj.
  • Tarama bitince en az bir mail hiçbir adrese (yedek dahil) ulaştırılamadıysa durum adresinin
    sonucu "status": "error" + "failed": <adet>; hepsi gittiyse "status": "ok", "failed": 0.
"""

import pytest

from app.api import trigger_auth
from app.db.models import Certificate, CertificateDomainMap, Domain
from tests.test_job_lock import _wait
from tests.test_mail_characterization import (_capture, _import_leaf, _run, _seed, _set_smtp,
                                              _team)

KEY = {"X-API-Key": "err-key"}
ENDPOINTS = ("expiry-run", "expired-run", "proposal-run")


@pytest.fixture(autouse=True)
def _reset_guards(client):
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()
    yield
    trigger_auth._last_external_run.clear()
    trigger_auth._failed_attempts.clear()


@pytest.fixture()
def smtp(client, auth_headers):
    yield lambda **over: _set_smtp(client, auth_headers, trigger_api_key="err-key", **over)
    _set_smtp(client, auth_headers, enabled=False, trigger_api_key="")


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_external_trigger_503_when_mail_disabled(client, auth_headers, smtp, endpoint, monkeypatch):
    sent = _capture(monkeypatch)
    smtp(enabled=False)
    r = client.post(f"/api/notifications/{endpoint}", headers=KEY)
    assert r.status_code == 503, r.text
    assert "E-posta bildirimleri kapalı" in r.json()["detail"]
    assert sent == []
    # admin "Şimdi Gönder" değişmedi: 200 + "SMTP kapalı" mesajı
    r = client.post(f"/api/notifications/{endpoint}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False


def test_external_trigger_503_when_host_empty(client, smtp):
    smtp(enabled=True, host="")
    r = client.post("/api/notifications/expiry-run", headers=KEY)
    assert r.status_code == 503, r.text


def test_external_trigger_503_does_not_start_cooldown(client, smtp, monkeypatch):
    """503'ten sonra e-posta açılınca araç beklemeden tekrar tetikleyebilmeli (429 değil)."""
    _capture(monkeypatch)
    smtp(enabled=False)
    assert client.post("/api/notifications/expiry-run", headers=KEY).status_code == 503
    smtp(enabled=True)
    assert client.post("/api/notifications/expiry-run", headers=KEY).status_code == 202
    _wait(client, "/api/notifications/expiry-run/status", KEY)


def _expiring_cert_with_team(client, h, tag):
    tid = _team(client, h, f"ERR {tag}", f"err-{tag}@test")
    cid = _import_leaf(client, h, f"err-{tag}.test")

    def seed(db):
        db.get(Certificate, cid).creator = None
        d = Domain(domain=f"err-{tag}-dom.test", sy_team_id=tid)
        db.add(d)
        db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=d.id, mapping_type="server"))
    _seed(seed)
    return cid


def _deactivate(cid):
    _seed(lambda db: setattr(db.get(Certificate, cid), "is_active", False))


def test_status_reports_error_when_smtp_refuses(client, auth_headers, smtp, monkeypatch):
    cid = _expiring_cert_with_team(client, auth_headers, "fail")
    try:
        smtp(fallback_address="")
        _capture(monkeypatch, fail_substr="err-fail@test")
        r = client.post("/api/notifications/expiry-run", headers=KEY)
        assert r.status_code == 202, r.text
        res = _wait(client, "/api/notifications/expiry-run/status", KEY)["result"]
        assert res["status"] == "error" and res["failed"] >= 1
        assert "gönderilemedi" in res["error"]
    finally:
        _deactivate(cid)


def test_status_ok_when_fallback_delivers(client, auth_headers, smtp, monkeypatch):
    """Birincil başarısız ama yedek adrese gitti → mail ulaştı, hata sayılmaz."""
    cid = _expiring_cert_with_team(client, auth_headers, "fb")
    try:
        smtp(fallback_address="yedek-fb@test")
        sent = _capture(monkeypatch, fail_substr="err-fb@test")
        assert client.post("/api/notifications/expiry-run", headers=KEY).status_code == 202
        res = _wait(client, "/api/notifications/expiry-run/status", KEY)["result"]
        assert res["status"] == "ok" and res["failed"] == 0
        assert any("yedek-fb@test" in m["to"] for m in sent)
    finally:
        _deactivate(cid)


def test_status_ok_when_all_sent(client, auth_headers, smtp, monkeypatch):
    cid = _expiring_cert_with_team(client, auth_headers, "ok")
    try:
        smtp()
        sent = _capture(monkeypatch)
        assert client.post("/api/notifications/expiry-run", headers=KEY).status_code == 202
        res = _wait(client, "/api/notifications/expiry-run/status", KEY)["result"]
        assert res["status"] == "ok" and res["failed"] == 0 and "error" not in res
        assert any("err-ok@test" in m["to"] for m in sent)
    finally:
        _deactivate(cid)


def test_notifier_results_carry_failed_count(client, auth_headers, smtp, monkeypatch):
    """Ekrandaki "Şimdi Gönder" sonucunda da gönderilemeyen sayısı görünür (failed)."""
    cid = _expiring_cert_with_team(client, auth_headers, "cnt")
    try:
        smtp(fallback_address="")
        _capture(monkeypatch, fail_substr="err-cnt@test")
        res = _run(force=True)
        assert res["failed"] >= 1
        r = client.post("/api/notifications/expiry-run", headers=auth_headers)
        assert r.status_code == 200 and r.json()["failed"] >= 1
    finally:
        _deactivate(cid)
