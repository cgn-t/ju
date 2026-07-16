from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Uygulama ayarları. .env dosyasından veya ortam değişkenlerinden okunur.

    Bağlantı önceliği (bkz. effective_database_url):
      1) MSSQL_HOST set ise → parça-parça ENV'den pymssql URL kurulur (container/OpenShift yolu):
         MSSQL_HOST, MSSQL_PORT(=1433), MSSQL_USER, MSSQL_PASSWORD, MSSQL_DB
         → mssql+pymssql://USER:PASSWORD@HOST:PORT/DB?charset=utf8
      2) Aksi halde DATABASE_URL kullanılır. Örnekler:
         MSSQL : mssql+pymssql://user:pass@host:1433/JUMBO2?charset=utf8
         SQLite: sqlite:///./jumbo.db  (lokal geliştirme, testler)
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "JUMBO Sertifika Yönetimi"
    database_url: str = "sqlite:///./jumbo.db"
    # MSSQL bağlantısını parça-parça ENV'den kur (pymssql). MSSQL_HOST doluysa DATABASE_URL'i EZER.
    mssql_host: str = ""
    mssql_port: int = 1433
    mssql_user: str = ""
    mssql_password: str = ""
    mssql_db: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    # Settings tablosundaki hassas değerleri (LDAP bind şifresi vb.) şifrelemek için Fernet anahtarı
    fernet_key: str = ""
    cors_origins: str = "http://localhost:5173"
    # İlk açılışta oluşturulan lokal admin
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin"
    # Otomasyon (Ansible/pipeline) için editor rolünde servis kullanıcısı — boşsa oluşturulmaz
    automation_username: str = ""
    automation_password: str = ""

    @property
    def effective_database_url(self) -> str:
        """Gerçek bağlantı URL'i. MSSQL_HOST doluysa pymssql URL'ini parça ENV'lerden kurar,
        aksi halde DATABASE_URL (varsayılan SQLite; testler bunu SQLite'a override eder)."""
        if self.mssql_host:
            user = quote_plus(self.mssql_user)
            pwd = quote_plus(self.mssql_password)
            return (f"mssql+pymssql://{user}:{pwd}"
                    f"@{self.mssql_host}:{self.mssql_port}/{self.mssql_db}?charset=utf8")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
