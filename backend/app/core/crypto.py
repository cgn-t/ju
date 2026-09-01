"""Ortak Fernet şifreleme yardımcısı — hassas alanların (SMTP/Vault/webhook şifreleri, ACME EAB
anahtarı vb.) şifrelenmesi için TEK kaynak. `settings_service.py` (kategori bazlı ayarlar) ve
`IssuanceProfile` (CA kimlik bilgileri) aynı anahtarı/deseni kullanır.

FERNET_KEY ortam değişkeni yoksa None döner — çağıran CWE-312 fail-closed davranışını uygulamalı:
şifrelenemeyen hassas değeri düz metin KAYDETMEMELİ, uyarı loglayıp yazmayı reddetmelidir
(bkz. settings_service.save_category)."""

from cryptography.fernet import Fernet

from app.core.config import get_settings


def get_fernet() -> Fernet | None:
    key = get_settings().fernet_key
    return Fernet(key.encode()) if key else None
