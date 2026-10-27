import os
import sys
from pathlib import Path

import pytest

# Uygulama import edilmeden önce test DB'sine yönlendir
TEST_DB = Path(__file__).parent / "test_jumbo.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import endpoint_checks, job_lock  # noqa: E402

# Ek canlı kontroller (DNS/CAA/Çoklu IP/OCSP Stapling) testlerde gerçek ağa çıkmasın;
# kendi testleri (test_endpoint_checks.py) bunu yerel sunucu ve sahte DNS ile açar.
endpoint_checks.ENABLED = False
# Zamanlanmış işlerin "başka pod az önce çalıştırdı" freni testlerde kapalı (aynı iş art arda
# çağrılıyor); kendi testi (test_job_lock.py) bunu açar.
job_lock.GAPS_ENABLED = False

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    with TestClient(app) as c:
        yield c
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture(scope="session")
def auth_headers(client):
    r = client.post("/api/auth/login-json", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES


@pytest.fixture()
def confluence(monkeypatch):
    """Sahte kurum wiki'si (Confluence). Kılavuz önbelleği testten önce ve sonra temizlenir."""
    import httpx

    from app.services import wiki
    from tests.fake_confluence import FakeConfluence

    fake = FakeConfluence()
    monkeypatch.setattr(wiki, "_client", lambda cfg: httpx.Client(
        headers=wiki._headers(cfg), transport=httpx.MockTransport(fake)))
    wiki.reset_cache()
    yield fake
    wiki.reset_cache()


@pytest.fixture()
def wiki_on(client, auth_headers, confluence, monkeypatch):
    """Ayarlar > AI Asistanı'nda kılavuz linki ve token'ı girilmiş (token şifreli saklanır)."""
    from cryptography.fernet import Fernet

    from app.core.config import get_settings
    from tests.fake_confluence import ROOT_LINK

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    r = client.put("/api/settings/ai", headers=auth_headers, json={
        "wiki_url": ROOT_LINK, "wiki_auth_mode": "bearer", "wiki_token": "tok", "wiki_refresh_minutes": 15})
    assert r.status_code == 200, r.text
    yield confluence
    client.put("/api/settings/ai", headers=auth_headers, json={"wiki_url": "", "wiki_token": ""})


@pytest.fixture()
def azure_wiki(client, auth_headers, monkeypatch):
    """Ayarlar'da Azure DevOps (TFS) wiki linki ve PAT girilmiş; wiki sahte (tests/fake_azure_wiki.py)."""
    import httpx
    from cryptography.fernet import Fernet

    from app.core.config import get_settings
    from app.services import wiki
    from tests.fake_azure_wiki import ID_LINK, FakeAzureWiki

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    fake = FakeAzureWiki()
    monkeypatch.setattr(wiki, "_client", lambda cfg: httpx.Client(
        headers=wiki._headers(cfg), transport=httpx.MockTransport(fake)))
    wiki.reset_cache()
    r = client.put("/api/settings/ai", headers=auth_headers, json={
        "wiki_url": ID_LINK, "wiki_auth_mode": "bearer", "wiki_username": "", "wiki_token": "pat"})
    assert r.status_code == 200, r.text
    yield fake
    client.put("/api/settings/ai", headers=auth_headers, json={"wiki_url": "", "wiki_token": ""})
    wiki.reset_cache()
