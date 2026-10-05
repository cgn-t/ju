#!/bin/sh
# nginx'i başlatmadan önce iki şey yapar:
#   1) LOG_LEVEL'e göre erişim-log modunu seçer. Aynı LOG_LEVEL env değişkeni backend'de de
#      kullanılır (bkz. backend/app/core/logging_config.py) — tek kaynaktan iki tarafı da yönetir.
#        LOG_LEVEL=DEBUG        → nginx TÜM istekleri loglar (2xx/3xx dahil).
#        LOG_LEVEL=<diğer/boş>  → nginx yalnız 2xx/3xx DIŞI (hata) istekleri loglanır.
#   2) Backend (uvicorn :5000) portu dinlemeye başlayana kadar BEKLER. supervisord her iki
#      süreci (api/web) PARALEL başlatır ve "başladı" saymak için yalnız startsecs (sürecin
#      çökmeden ayakta kalma süresi) kullanır — bu GERÇEK bir hazır-mı kontrolü değildir.
#      Backend açılışta DB şeması/migration işi yaptığı için portu birkaç saniye geç açar;
#      bu sürede nginx zaten ayaktaysa /api/* istekleri "111: Connection refused" → 502 alır
#      (container tamamen ayağa kalktıktan sonra kendiliğinden düzelir ama geçici hatalıdır).
#      Azami 30sn bekler; bu süre dolarsa (ör. backend gerçekten çökmüşse) nginx yine de
#      başlar — statik önyüz en azından çalışsın, /api/* o zaman gerçek bir 502 verir.
set -e

MODE_FILE=/tmp/nginx-log-mode.conf
if [ "${LOG_LEVEL:-INFO}" = "DEBUG" ]; then
    printf 'map $status $loggable { default 1; }\n' > "$MODE_FILE"
else
    printf 'map $status $loggable { ~^[23] 0; default 1; }\n' > "$MODE_FILE"
fi

python3 - <<'PY' || echo "nginx-entrypoint: backend 30sn içinde hazır olmadı, nginx yine de başlatılıyor" >&2
import socket
import sys
import time

for _ in range(60):
    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(0.5)
sys.exit(1)
PY

exec nginx -g "daemon off;"
