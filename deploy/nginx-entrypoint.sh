#!/bin/sh
# nginx'i başlatmadan önce LOG_LEVEL'e göre erişim-log modunu seçer. Aynı LOG_LEVEL env
# değişkeni backend'de de kullanılır (bkz. backend/app/core/logging_config.py) — tek
# kaynaktan iki tarafı da yönetir.
#   LOG_LEVEL=DEBUG        → nginx TÜM istekleri loglar (2xx/3xx dahil).
#   LOG_LEVEL=<diğer/boş>  → nginx yalnız 2xx/3xx DIŞI (hata) istekleri loglar.
set -e

MODE_FILE=/tmp/nginx-log-mode.conf
if [ "${LOG_LEVEL:-INFO}" = "DEBUG" ]; then
    printf 'map $status $loggable { default 1; }\n' > "$MODE_FILE"
else
    printf 'map $status $loggable { ~^[23] 0; default 1; }\n' > "$MODE_FILE"
fi

exec nginx -g "daemon off;"
