"""Regresyon Testi > Test Hazırlığı (v3.9.28): sertifika üretimi, localhost'ta test siteleri,
test ekipleri/hesapları ve temizlik. Yalnız admin; yalnız REGRESSION_TOOLS=1 iken."""

import io
import socket
import ssl
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

from app.core.config import get_settings
from app.db.models import Team, User
from app.db.session import SessionLocal
from app.services import regression_lab


@pytest.fixture
def lab_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "regression_tools", True)
    yield
    db = SessionLocal()
    regression_lab.stop_sites(db)
    db.close()


def _served_cert(port: int) -> x509.Certificate:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("localhost", port), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname="localhost") as t:
            return x509.load_der_x509_certificate(t.getpeercert(binary_form=True))


def test_closed_by_default(client, auth_headers):
    assert client.get("/api/regression/lab", headers=auth_headers).json() == {"enabled": False}
    for path in ("/api/regression/lab/certs", "/api/regression/lab/sites/start", "/api/regression/lab/data",
                 "/api/regression/lab/all", "/api/regression/lab/cleanup"):
        assert client.post(path, headers=auth_headers).status_code == 404, path


def test_only_admin(client, auth_headers, lab_on):
    client.post("/api/users", headers=auth_headers, json={
        "username": "lab_editor", "password": "x", "role": "editor", "auth_source": "local"})
    tok = client.post("/api/auth/login-json", json={"username": "lab_editor", "password": "x"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for method, path in [("get", "/api/regression/lab"), ("post", "/api/regression/lab/certs"),
                         ("get", "/api/regression/lab/zip"), ("post", "/api/regression/lab/cleanup")]:
        assert getattr(client, method)(path, headers=h).status_code == 403, path


def test_generate_files_today(client, auth_headers, lab_on):
    r = client.post("/api/regression/lab/certs", headers=auth_headers)
    assert r.status_code == 200, r.text
    names = [f["name"] for f in r.json()["certs"]["files"]]
    assert len(names) == 26 and names[0].startswith("00-") and names[-1].startswith("25-")
    assert all(f["what"] for f in r.json()["certs"]["files"])

    z = zipfile.ZipFile(io.BytesIO(client.get("/api/regression/lab/zip", headers=auth_headers).content))
    assert len([n for n in z.namelist() if n.startswith("dosyalar/")]) == 26

    def get(n):
        r = client.get(f"/api/regression/lab/files/{n}", headers=auth_headers)
        assert r.status_code == 200
        return r.content

    now = datetime.now(timezone.utc)
    c10 = x509.load_pem_x509_certificate(get("10-trusted-20-gun-kala.pem"))
    assert 19 <= (c10.not_valid_after_utc - now).days <= 20          # üretim anına göre
    key, cert, extra = pkcs12.load_key_and_certificates(get("05-parolali-pfx.pfx"), b"Jumbo2026!")
    assert cert is not None and len(extra) == 1
    c14 = x509.load_pem_x509_certificate(get("14-iptal-edilmis.pem"))
    dp = c14.extensions.get_extension_for_class(x509.CRLDistributionPoints).value
    assert dp[0].full_name[0].value == "http://localhost:9440/iptal.crl"
    assert get("06-notepad-unicode-kayit.pem")[:2] in (b"\xff\xfe", b"\xfe\xff")
    assert client.get("/api/regression/lab/files/yok.pem", headers=auth_headers).status_code == 404


def test_sites_serve_and_live_check_matches(client, auth_headers, lab_on):
    assert client.post("/api/regression/lab/sites/start", headers=auth_headers).status_code in (200, 409)
    client.post("/api/regression/lab/certs", headers=auth_headers)
    r = client.post("/api/regression/lab/sites/start", headers=auth_headers)
    assert r.status_code == 200, r.text
    st = r.json()["sites"]
    assert st["running"] and all(row["up"] for row in st["rows"]), st["rows"]

    assert "baska-site.jumbo-test.local" in _served_cert(9442).subject.rfc4514_string()
    assert (_served_cert(9446).not_valid_after_utc < datetime.now(timezone.utc))
    # CRL 9440'tan iner
    import urllib.request
    crl = urllib.request.urlopen("http://localhost:9440/iptal.crl", timeout=5).read()
    assert len(x509.load_der_x509_crl(crl)) == 1

    # Jumbo kendi test sitesine bağlanır: zinciri al, bağla, doğrula → Eşleşiyor
    d = client.post("/api/domains", headers=auth_headers, json={"domain": "localhost:9441"}).json()
    assert client.post(f"/api/domains/{d['id']}/import-chain", headers=auth_headers).status_code == 200
    r = client.post(f"/api/domains/{d['id']}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "match", r.text

    # 9444 yenileme düğmesi: aynı ad, başka sertifika
    old = _served_cert(9444)
    client.post("/api/regression/lab/sites/renewed", headers=auth_headers, json={"renewed": True})
    new = _served_cert(9444)
    assert old.serial_number != new.serial_number
    assert (new.not_valid_after_utc - old.not_valid_after_utc).days > 300

    client.post("/api/regression/lab/sites/stop", headers=auth_headers)
    assert not regression_lab.probe(9441)


def test_sites_close_after_time(client, auth_headers, lab_on):
    client.post("/api/regression/lab/certs", headers=auth_headers)
    client.post("/api/regression/lab/sites/start", headers=auth_headers)
    assert regression_lab.probe(9445)
    db = SessionLocal()
    st = regression_lab.load_state(db)
    st["sites"]["until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    regression_lab.save_state(db, st)
    regression_lab.sync_now(regression_lab.load_state(db))   # izleyici her 10 sn'de bunu yapar
    db.close()
    assert not regression_lab.probe(9445)
    assert client.get("/api/regression/lab", headers=auth_headers).json()["sites"]["running"] is False


def test_prepare_data_and_cleanup(client, auth_headers, lab_on):
    # Önceden var olan gerçek bir ekip: hazırlık onu yeniden açmaz, temizlik silmez
    client.post("/api/teams", headers=auth_headers, json={"name": "Mobil Uygulamalar SY", "type": "SY"})
    r = client.post("/api/regression/lab/all", headers=auth_headers,
                    json={"emails": {"a": "a@test.local", "b": "b@test.local", "c": "c@test.local"}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [t["name"] for t in data["teams"] if t["created_here"]] == [
        "Ödeme Sistemleri SY", "İletişim Kanalları SY", "Mailsiz Test SY"]
    pw = data["password"]
    assert pw and all(u["exists"] for u in data["users"])

    tok = client.post("/api/auth/login-json", json={"username": "ismail.test", "password": pw}).json()
    assert tok["role"] == "editor"
    rolsuz = client.post("/api/auth/login-json", json={"username": "rolsuz.test", "password": pw})
    assert rolsuz.status_code == 200 and rolsuz.json()["role"] not in ("admin", "editor", "viewer", "allviewer")

    # İkinci kez: kopya açılmaz
    client.post("/api/regression/lab/data", headers=auth_headers, json={})
    db = SessionLocal()
    assert db.query(Team).filter(Team.name == "Ödeme Sistemleri SY").count() == 1
    assert db.query(User).filter(User.username == "ismail.test").count() == 1
    odeme = db.query(Team).filter(Team.name == "Ödeme Sistemleri SY").first()
    assert odeme.email == "a@test.local"
    odeme_id = odeme.id
    db.close()

    # Testte eklenen kayıtlar: test sertifikası, test domaini, test ekibinin uygulaması
    files = client.get("/api/regression/lab/zip", headers=auth_headers).content
    pem = zipfile.ZipFile(io.BytesIO(files)).read("dosyalar/02-tam-zincir-ters-sira-anahtarli.pem")
    assert client.post("/api/certificates/import", headers=auth_headers,
                       files={"file": ("f.pem", pem, "application/x-pem-file")}).status_code == 200
    dom = client.post("/api/domains", headers=auth_headers,
                      json={"domain": "excel-bir.jumbo-test.local", "sy_team_id": odeme_id}).json()
    gercek = client.post("/api/domains", headers=auth_headers, json={"domain": "gercek.ornek.com"}).json()
    app = client.post("/api/applications", headers=auth_headers, json={
        "app_name": "Ödeme API", "server_name": "odemesrv01", "sy_team_id": odeme_id, "domain_id": dom["id"]})
    assert app.status_code in (200, 201), app.text

    prev = client.get("/api/regression/lab/cleanup", headers=auth_headers).json()
    assert prev["certificates"] >= 3 and prev["domains"] >= 1 and prev["applications"] >= 1
    assert prev["users"] == 4 and prev["teams"] == 3
    r = client.post("/api/regression/lab/cleanup", headers=auth_headers)
    assert r.status_code == 200, r.text

    after = client.get("/api/regression/lab/cleanup", headers=auth_headers).json()
    assert after == {"certificates": 0, "domains": 0, "applications": 0, "users": 0, "teams": 0}
    db = SessionLocal()
    assert db.query(Team).filter(Team.name == "Mobil Uygulamalar SY").count() == 1   # önceden vardı
    assert db.query(User).filter(User.username.like("%.test")).count() == 0
    db.close()
    assert client.get(f"/api/domains/{gercek['id']}", headers=auth_headers).status_code == 200
    assert not regression_lab.probe(9441)
    st = client.get("/api/regression/lab", headers=auth_headers).json()
    assert st["data"]["password"] is None or not any(u["exists"] for u in st["data"]["users"])
