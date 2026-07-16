#!/usr/bin/env bash
# CPX SSL vserver'ına TLS bağlanıp SUNULAN cert'i gösterir (JUMBO live_check'inin yaptığının aynısı).
# Kullanım:  ./verify.sh [host:port]   (varsayılan: localhost:8443 → container 443)
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh
TARGET=${1:-localhost:8443}

echo "== TLS: $TARGET =="
LEAF=$(openssl s_client -connect "$TARGET" -servername demo.jumbo.local </dev/null 2>/dev/null \
        | openssl x509 2>/dev/null)
if [ -z "$LEAF" ]; then
  echo "Bağlanılamadı/handshake yok. vserver UP mu? (bootstrap yapıldı mı, backend jumbo:8080 ayakta mı)"
  echo "Alternatif hedef (jumbo-net içinden):  ./verify.sh $(net_ip "$CPX_NAME"):443   veya  jumbo-cpx:443"
  exit 1
fi
echo "$LEAF" | openssl x509 -noout -subject -issuer -serial -enddate -fingerprint -sha256 \
  | sed 's/^/  /'
