"""Profilim: giriş yapan kişinin LDAP/AD bilgileri (v3.9.3).

Sayfa açıldığında servis hesabıyla canlı okunur; DB'ye bir şey yazılmaz. Sahte dizin ldap3 MOCK_SYNC
ile kurulur (gerçek AD bulut ortamından erişilemez)."""

from cryptography.fernet import Fernet
from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import AppSetting, User
from app.db.session import SessionLocal
from app.services import ldap_auth
from app.services.settings_service import save_category

BASE = "OU=Users,DC=firma,DC=local"
ISMAIL = f"CN=İsmail Çelik,OU=Sertifika,OU=Bilgi Guvenligi,{BASE}"
AYSE = f"CN=Ayşe Yılmaz,OU=Sertifika,OU=Bilgi Guvenligi,{BASE}"
MEHMET = f"CN=Mehmet Öz,OU=Bilgi Guvenligi,{BASE}"
EDITORS = "CN=JUMBO_Editors,OU=Groups,DC=firma,DC=local"
SCRUM = "CN=SY-BBB,OU=ScrumGroup,OU=BTPersonel,DC=firma,DC=local"

CFG = {"enabled": True, "server": "127.0.0.1", "port": 1, "use_ssl": False, "base_dn": BASE,
       "bind_dn": "CN=svc,DC=firma,DC=local", "bind_password": "x", "user_attr": "sAMAccountName",
       "group_role_map": {EDITORS: "editor"}}


def _fake_directory(monkeypatch):
    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    server = Server("fake", get_info=OFFLINE_AD_2012_R2)
    conn = Connection(server, user="CN=svc,DC=firma,DC=local", password="x", client_strategy=MOCK_SYNC)
    conn.strategy.add_entry("CN=svc,DC=firma,DC=local", {"userPassword": "x", "objectClass": "person"})
    conn.strategy.add_entry(MEHMET, {"objectClass": "user", "sAMAccountName": "mehmet.oz", "displayName": "Mehmet Öz",
                                     "title": "Bölüm Başkanı", "department": "Bilgi Güvenliği Bölümü"})
    conn.strategy.add_entry(AYSE, {"objectClass": "user", "sAMAccountName": "ayse.yilmaz", "displayName": "Ayşe Yılmaz",
                                   "title": "Müdür", "department": "Sertifika Müdürlüğü", "manager": MEHMET,
                                   "mail": "ayse@firma.com.tr"})
    conn.strategy.add_entry(ISMAIL, {"objectClass": "user", "sAMAccountName": "ismail.celik",
                                     "displayName": "İsmail Çelik", "title": "Kıdemli Uzman",
                                     "department": "Sertifika Müdürlüğü", "mail": "ismail@firma.com.tr",
                                     "manager": AYSE, "memberOf": [EDITORS, "CN=VPN,OU=Groups,DC=firma,DC=local", SCRUM],
                                     "userAccountControl": "514", "userPassword": "Gizli.123",
                                     "division": "Teknoloji Grubu"})
    conn.bind()
    monkeypatch.setattr(ldap_auth, "_server", lambda cfg: server)
    monkeypatch.setattr(ldap_auth, "_connect", lambda server, cfg, user, password: conn)
    monkeypatch.setattr(conn, "unbind", lambda: True)  # aynı sahte bağlantı birden çok kez kullanılır


def _save(db, cfg):
    db.query(AppSetting).filter(AppSetting.category == "ldap").delete()
    db.commit()
    save_category(db, "ldap", cfg)


def test_profile_reads_summary_managers_groups_and_hides_password(client, monkeypatch):
    db = SessionLocal()
    try:
        _fake_directory(monkeypatch)
        _save(db, CFG)
        p = ldap_auth.directory_profile(db, "ismail.celik")
        assert p["status"] == "ok", p
        summary = {s["key"]: s["value"] for s in p["summary"]}
        assert summary["title"] == "Kıdemli Uzman" and summary["department"] == "Sertifika Müdürlüğü"
        assert [m["name"] for m in p["managers"]] == ["Ayşe Yılmaz", "Mehmet Öz"]
        assert p["managers"][0]["title"] == "Müdür"
        assert p["ou_path"] == ["Users", "Bilgi Guvenligi", "Sertifika"]
        groups = {g["name"]: g["mapped_role"] for g in p["groups"]}
        assert groups == {"JUMBO_Editors": "editor", "VPN": None, "SY-BBB": None}
        # Ekip grubu (varsayılan OU=ScrumGroup): sol menüde adın altında görünür
        assert p["team_groups"] == ["SY-BBB"] and summary["team"] == "SY-BBB"
        assert "Hesap devre dışı" in p["account_flags"]
        names = {a["name"].lower() for a in p["attributes"]}
        assert "division" in names and "userpassword" not in names
    finally:
        _save(db, {"enabled": False})
        db.close()


def test_profile_not_found_and_disabled(client, monkeypatch):
    db = SessionLocal()
    try:
        _save(db, {"enabled": False})
        assert ldap_auth.directory_profile(db, "ismail.celik")["status"] == "disabled"
        _fake_directory(monkeypatch)
        _save(db, CFG)
        assert ldap_auth.directory_profile(db, "yok.boyle")["status"] == "not_found"
    finally:
        _save(db, {"enabled": False})
        db.close()


def test_endpoints_local_account_and_admin_only(client, auth_headers):
    r = client.get("/api/auth/me/directory", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "local"
    assert client.get("/api/users/999999/directory", headers=auth_headers).status_code == 404

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "profil.viewer").first():
            db.add(User(username="profil.viewer", email="pv@x", role="allviewer", auth_source="local",
                        password_hash=hash_password("Pw.12345"), is_active=True))
            db.commit()
        admin_id = db.query(User).filter(User.username == "admin").first().id
    finally:
        db.close()
    tok = client.post("/api/auth/login-json", json={"username": "profil.viewer", "password": "Pw.12345"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get(f"/api/users/{admin_id}/directory", headers=h).status_code == 403
    assert client.get("/api/auth/me/directory", headers=h).json()["status"] == "local"
    assert client.get(f"/api/users/{admin_id}/directory", headers=auth_headers).json()["status"] == "local"
