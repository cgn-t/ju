"""LDAP bind şifresi okunamadığında açık hata (v3.8.15).

Saha: kurulumdan sonra 'Bağlantı Hatası: password is mandatory in simple bind'. Kayıtlı bind
şifresi farklı bir FERNET_KEY ile şifrelendiği için boş okunuyor, ldap3 de yalnız bu genel
mesajı veriyordu. Artık neden ve yapılacak iş söylenir; sunucuya hiç gidilmez."""

from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.db.models import AppSetting
from app.db.session import SessionLocal
from app.services import ldap_auth
from app.services.settings_service import get_category, save_category, secret_state

LDAP_CFG = {"enabled": True, "server": "127.0.0.1", "port": 1, "use_ssl": False,
            "base_dn": "dc=firma,dc=local", "bind_dn": "CN=svc,DC=firma,DC=local"}


def _reset(db):
    db.query(AppSetting).filter(AppSetting.category == "ldap").delete()
    db.commit()


def _use_key(monkeypatch, key):
    monkeypatch.setattr(get_settings(), "fernet_key", key)


def test_password_saved_with_other_key_is_reported(client, monkeypatch):
    db = SessionLocal()
    try:
        _reset(db)
        _use_key(monkeypatch, Fernet.generate_key().decode())
        save_category(db, "ldap", {**LDAP_CFG, "bind_password": "Gizli123"})
        assert secret_state(db, "ldap.bind_password") == "ok"
        assert get_category(db, "ldap", mask_secrets=False)["bind_password"] == "Gizli123"

        _use_key(monkeypatch, Fernet.generate_key().decode())  # yeni kurulum, farklı anahtar
        assert secret_state(db, "ldap.bind_password") == "undecryptable"
        ok, message = ldap_auth.test_connection(db)
        assert not ok
        assert "FERNET_KEY" in message and "password is mandatory" not in message

        res = ldap_auth.authenticate(db, "ali", "x")
        assert not res.success and res.error == "Kullanıcı adı veya şifre hatalı"
    finally:
        _reset(db)
        db.close()


def test_password_saved_but_key_missing_is_reported(client, monkeypatch):
    db = SessionLocal()
    try:
        _reset(db)
        _use_key(monkeypatch, Fernet.generate_key().decode())
        save_category(db, "ldap", {**LDAP_CFG, "bind_password": "Gizli123"})
        _use_key(monkeypatch, "")
        assert secret_state(db, "ldap.bind_password") == "no_key"
        ok, message = ldap_auth.test_connection(db)
        assert not ok and "FERNET_KEY tanımlı değil" in message
    finally:
        _reset(db)
        db.close()


def test_password_never_saved_is_reported(client, monkeypatch):
    db = SessionLocal()
    try:
        _reset(db)
        _use_key(monkeypatch, Fernet.generate_key().decode())
        save_category(db, "ldap", LDAP_CFG)
        assert secret_state(db, "ldap.bind_password") == "missing"
        ok, message = ldap_auth.test_connection(db)
        assert not ok and "Bind şifresi kayıtlı değil" in message
    finally:
        _reset(db)
        db.close()


def test_readable_password_goes_to_server(client, monkeypatch):
    """Şifre okunabiliyorsa yeni kontrol devreye girmez; bağlantı denenir (burada port kapalı)."""
    db = SessionLocal()
    try:
        _reset(db)
        _use_key(monkeypatch, Fernet.generate_key().decode())
        save_category(db, "ldap", {**LDAP_CFG, "bind_password": "Gizli123"})
        ok, message = ldap_auth.test_connection(db)
        assert not ok and "Bind şifresi" not in message
    finally:
        _reset(db)
        db.close()


def test_anonymous_bind_without_dn_is_untouched(client, monkeypatch):
    db = SessionLocal()
    try:
        _reset(db)
        save_category(db, "ldap", {**LDAP_CFG, "bind_dn": ""})
        ok, message = ldap_auth.test_connection(db)
        assert "Bind şifresi" not in message
    finally:
        _reset(db)
        db.close()
