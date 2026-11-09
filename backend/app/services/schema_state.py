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

from sqlalchemy import inspect

from app.db.session import engine

CACHE_SECONDS = 60

# Her bekleyen değişiklik: hangi sürüm, hangi tablo/kolon, hangi özelliği açar, betik dosyası.
EXPECTATIONS: list[dict] = [
    {
        "key": "standard_name",
        "version": "3.9.39",
        "title": "Sertifikalara Standart Ad kolonu",
        "table": "SSLCertificates",
        "column": "StandartAd",
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


def _columns(table: str) -> set[str]:
    try:
        return {c["name"].lower() for c in inspect(engine).get_columns(table)}
    except Exception:  # tablo yok / yetki yok → özellik kapalı say
        return set()


def _load() -> dict[str, bool]:
    by_table: dict[str, set[str]] = {}
    out = {}
    for e in EXPECTATIONS:
        cols = by_table.setdefault(e["table"], _columns(e["table"]))
        out[e["key"]] = e["column"].lower() in cols
    return out


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
