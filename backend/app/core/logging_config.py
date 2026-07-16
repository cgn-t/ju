"""Merkezi log yapılandırması — TEK biçim, tek kaynak.

Önceki durum: container loglarında 5 farklı biçim karışıyordu (Python varsayılan
"INFO:logger:mesaj", uvicorn "INFO:  ...", apscheduler iç detayları, nginx access ×2,
supervisord). Bu modül Python tarafını tek hizalı biçime alır:

    2026-07-09 19:41:08 INFO     [app.main] JUMBO başlatıldı

Kurallar:
  • uvicorn / uvicorn.error → aynı biçim (startup/shutdown mesajları korunur).
  • uvicorn.access → WARNING: istek satırlarını nginx ön kapı zaten loglar; uvicorn'un
    aynı isteği ikinci kez yazması çift satır üretiyordu.
  • apscheduler → WARNING: "Adding job tentatively..." gibi iç detaylar gürültü.
  • Seviye LOG_LEVEL ortam değişkeniyle değiştirilebilir (varsayılan INFO).
      - Docker'dan yönetim:  docker run ... -e LOG_LEVEL=DEBUG   (veya INFO / ERROR)
      - DEBUG  → LDAP sorgusu dahil ayrıntılı iz (aşağıya bkz.)
      - INFO   → durum satırları (başlangıç, giriş denemesi/başarısı)
      - ERROR  → yalnız hatalar
  • DEBUG, uygulamanın KENDİ okunur LDAP izini verir (app.services.ldap_auth): hedef sunucu,
    TLS politikası, bind DN, base DN, arama filtresi, bulunan DN, istenen nitelikler ve bind
    sonucu — hepsi şifresiz. "Sorgu nasıl gidiyor" sorusunu bu iz cevaplar.
  • ldap3 kütüphanesinin HAM protokol logu (çok ayrıntılı: tek girişte on KB'larca satır) AYRI
    bir anahtarla açılır ve VARSAYILAN KAPALIDIR (okunur iz çoğu teşhis için yeter):
        docker run ... -e LOG_LEVEL=DEBUG -e LDAP_LOG_DETAIL=EXTENDED
    LDAP_LOG_DETAIL ∈ OFF (varsayılan) | BASIC | PROTOCOL | NETWORK | EXTENDED (en ayrıntılı).
    Şifreler her seviyede MASKELENİR.

uvicorn CLI kendi log config'ini app import'undan ÖNCE uygular; setup_logging()
main.py import'unda dictConfig ile adlandırılmış logger'ları yeniden yapılandırdığı
için son söz bu modülündür.
"""

import logging
import os
from logging.config import dictConfig

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = "INFO"
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {"level": level, "handlers": ["console"]},
        "loggers": {
            # uvicorn kendi handler'larını kurar — bizimkiyle DEĞİŞTİR (çift satırı önle)
            "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
            # İstek satırlarını nginx ön kapı loglar; uvicorn access aynı isteği tekrarlıyordu
            "uvicorn.access": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            # Zamanlayıcının iç işleyiş mesajları operasyonel değer taşımıyor
            "apscheduler": {"level": "WARNING"},
            # ldap3 ham protokol logu: seviye DEBUG ise DEBUG kayıtları geçer, aksi halde susar.
            # Ayrıntı düzeyi ayrıca _configure_ldap3_logging ile açılır (yalnız DEBUG'da EXTENDED).
            "ldap3": {"level": level, "handlers": ["console"], "propagate": False},
        },
    })
    _configure_ldap3_logging()
    logging.captureWarnings(True)  # warnings.warn → log biçiminde (dağınık stderr yerine)


def _configure_ldap3_logging() -> None:
    """ldap3 kütüphanesinin HAM protokol logunu LDAP_LOG_DETAIL anahtarına göre ayarlar.

    Bu log ÇOK ayrıntılıdır (tek girişte on KB'larca satır: her PDU'nun ASN.1 dökümü) ve
    uygulamanın kendi okunur LDAP izi (app.services.ldap_auth) çoğu teşhis için yettiğinden
    VARSAYILAN OLARAK KAPALIDIR. İhtiyaç olursa Docker'dan açılır:
        -e LOG_LEVEL=DEBUG -e LDAP_LOG_DETAIL=EXTENDED   (BASIC|PROTOCOL|NETWORK|EXTENDED)
    Şifreler her seviyede maskelenir (hide_sensitive_data=True). ldap3 yoksa/API sürümü
    farklıysa sessizce geçilir — loglama yapılandırması uygulamayı ASLA düşürmemeli."""
    detail_name = os.getenv("LDAP_LOG_DETAIL", "OFF").upper()
    try:
        from ldap3.utils.log import (BASIC, EXTENDED, NETWORK, OFF, PROTOCOL,
                                      set_library_log_detail_level,
                                      set_library_log_hide_sensitive_data)
        detail = {"OFF": OFF, "BASIC": BASIC, "PROTOCOL": PROTOCOL,
                  "NETWORK": NETWORK, "EXTENDED": EXTENDED}.get(detail_name, OFF)
        set_library_log_hide_sensitive_data(True)  # bind şifreleri logda gizlenir
        set_library_log_detail_level(detail)
        if detail != OFF:
            # Ham log DEBUG seviyesinde üretilir; LOG_LEVEL DEBUG değilse bile görünsün diye
            # ldap3 logger'ını açıkça DEBUG'a çek (kullanıcı bilinçli olarak istedi).
            logging.getLogger("ldap3").setLevel(logging.DEBUG)
    except Exception:  # noqa: BLE001 — loglama yapılandırması uygulamayı ASLA düşürmemeli
        pass
