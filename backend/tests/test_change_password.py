"""Yerel hesabın (ör. admin) kendi şifresini arayüzden değiştirmesi (v3.9.34)."""
import uuid

from app.db.models import AuditLog, User
from app.db.session import SessionLocal


def _local_user(client, auth_headers, role="admin", password="eski-sifre-1"):
    name = f"yerel_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", headers=auth_headers, json={
        "username": name, "password": password, "auth_source": "local", "role": role})
    assert r.status_code in (200, 201), r.text
    return name


def _login(client, name, password):
    return client.post("/api/auth/login-json", json={"username": name, "password": password})


def _hdr(client, name, password):
    r = _login(client, name, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_local_account_changes_own_password(client, auth_headers):
    name = _local_user(client, auth_headers)
    h = _hdr(client, name, "eski-sifre-1")
    assert client.get("/api/auth/me", headers=h).json()["local_account"] is True
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "eski-sifre-1", "new_password": "yeni-sifre-2"})
    assert r.status_code == 200, r.text
    assert _login(client, name, "eski-sifre-1").status_code == 401
    assert _login(client, name, "yeni-sifre-2").status_code == 200
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username=name).one().id
        row = (db.query(AuditLog).filter_by(action="password_change", record_id=str(uid)).one())
        assert "yeni-sifre-2" not in (row.details or "") and "eski-sifre-1" not in (row.details or "")


def test_wrong_current_password_rejected_and_logged(client, auth_headers):
    name = _local_user(client, auth_headers, role="viewer")
    h = _hdr(client, name, "eski-sifre-1")
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "yanlis", "new_password": "yeni-sifre-2"})
    assert r.status_code == 400 and "Mevcut şifre hatalı" in r.json()["detail"]
    assert _login(client, name, "eski-sifre-1").status_code == 200
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username=name).one().id
        assert db.query(AuditLog).filter_by(action="pwd_change_failed", record_id=str(uid)).count() == 1


def test_new_password_rules(client, auth_headers):
    name = _local_user(client, auth_headers)
    h = _hdr(client, name, "eski-sifre-1")
    for new, msg in (("kisa", "en az 8"), ("eski-sifre-1", "aynı olamaz"), (" bosluklu-sifre", "boşluk")):
        r = client.post("/api/auth/change-password", headers=h,
                        json={"current_password": "eski-sifre-1", "new_password": new})
        assert r.status_code == 400 and msg in r.json()["detail"], (new, r.text)
    assert _login(client, name, "eski-sifre-1").status_code == 200


def test_ldap_account_cannot_change_password(client, auth_headers):
    from app.core.security import create_access_token
    name = f"ad_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.add(User(username=name, auth_source="ldap", is_active=True, role="viewer",
                    email=f"{name}@x.local", password_hash=""))
        db.commit()
    h = {"Authorization": f"Bearer {create_access_token(name, 'viewer')}"}
    assert client.get("/api/auth/me", headers=h).json()["local_account"] is False
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "x", "new_password": "yeni-sifre-2"})
    assert r.status_code == 400 and "Active Directory" in r.json()["detail"]


def test_requires_login(client):
    r = client.post("/api/auth/change-password",
                    json={"current_password": "admin", "new_password": "yeni-sifre-2"})
    assert r.status_code == 401
