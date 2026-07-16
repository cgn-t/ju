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
