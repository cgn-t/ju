"""Uygulamanın beklediği ama sahibin Veritabanı Değişiklikleri sayfasından (v3.9.38) elle
uyguladığı şema değişiklikleri.

v3.9.38'den itibaren yeni kolonlar pod açılışında KENDİLİĞİNDEN eklenmez (ensure_new_columns
eski kolonlar için olduğu gibi çalışmaya devam eder). Sahip, GitHub'daki
db/degisiklikler/<sürüm>-*.sql betiğini sayfaya yapıştırıp çalıştırır. Kolon yokken ona bağlı
özellik KAPALI kalır, uygulamanın geri kalanı normal çalışır.

Durum veritabanının kendi şema bilgisinden okunur (yazma yok) ve süreç içinde kısa süre
önbelleğe alınır; sayfadan SQL çalıştırılınca önbellek hemen yenilenir. Çoklu pod'da diğer
pod'lar en geç CACHE_SECONDS sonra yeni durumu görür."""

import threading
import time

from sqlalchemy import text

from app.db.session import engine

CACHE_SECONDS = 60

# Her bekleyen değişiklik: hangi sürüm, hangi tablo/kolon, hangi özelliği açar, betik dosyası.
EXPECTATIONS: list[dict] = [
    {
        "key": "standard_name",
        "version": "3.9.39",
        "title": "Sertifikalara Standart Ad kolonu",
        "table": "SSLCertificates",
        "column": "StandardName",
        "feature": "Standart Ad (isimlendirme kuralı)",
        "script": "db/degisiklikler/v3.9.39-standart-ad.sql",
    },
]

_lock = threading.Lock()
_cache: dict[str, bool] = {}
_cache_at = 0.0
# Testler: gerçek şemadan bağımsız durum vermek için (conftest varsayılan olarak "betik henüz
# çalıştırılmadı" durumunu kurar; Standart Ad testleri açar).
override: dict[str, bool] = {}


def _has_column(table: str, column: str) -> bool:
    """Kolonu, uygulamanın kendi sorgularının çözdüğü şekilde (şema adı vermeden) okumayı dener.

    inspect() kullanıcının varsayılan şemasına bakar; AD ile bağlanan kullanıcının varsayılan
    şeması dbo değilse kolon 'yok' görünüyordu (v3.9.41). Doğrudan TOP 0 / LIMIT 0 sorgusu,
    SQL Server'ın normal ad çözümlemesini (önce kullanıcı şeması, sonra dbo) kullanır."""
    # Köşeli parantez: SQLite'ta çift tırnaklı bilinmeyen ad metin sabiti sayılır, [ad] sayılmaz.
    sql = (f"SELECT TOP 0 [{column}] FROM [{table}]" if engine.dialect.name == "mssql"
           else f"SELECT [{column}] FROM [{table}] LIMIT 0")
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.rollback()
        return True
    except Exception:  # kolon/tablo yok ya da yetki yok → özellik kapalı say
        return False


def _load() -> dict[str, bool]:
    return {e["key"]: _has_column(e["table"], e["column"]) for e in EXPECTATIONS}


def refresh() -> dict[str, bool]:
    global _cache, _cache_at
    with _lock:
        _cache = _load()
        _cache_at = time.monotonic()
        return dict(_cache)


def state() -> dict[str, bool]:
    if not _cache or time.monotonic() - _cache_at > CACHE_SECONDS:
        st = refresh()
    else:
        st = dict(_cache)
    st.update(override)
    return st


def is_ready(key: str) -> bool:
    return bool(state().get(key))


def standard_name_ready() -> bool:
    return is_ready("standard_name")


def pending_list() -> list[dict]:
    st = {**refresh(), **override}
    return [{**e, "applied": bool(st.get(e["key"]))} for e in EXPECTATIONS]
