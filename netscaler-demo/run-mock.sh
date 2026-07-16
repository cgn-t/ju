#!/usr/bin/env bash
# run-cpx.sh ALTERNATİFİ (Apple Silicon / amd64 CPX emüle edilemeyen ortamlar için).
# NITRO-uyumlu mock ADC'yi 'jumbo-cpx' adıyla başlatır → bootstrap/swap/verify DEĞİŞMEDEN çalışır.
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh

if docker ps -a --format '{{.Names}}' | grep -qx "$CPX_NAME"; then
  echo "HATA: '$CPX_NAME' zaten var → docker rm -f $CPX_NAME"
  exit 1
fi

echo "mock-ADC imajı derleniyor (arm64 native)..."
docker build -t jumbo-adc-mock:latest ./mock >/dev/null

echo "mock-ADC başlatılıyor ($CPX_NAME)  ·  NITRO host:19080  ·  TLS host:8443"
docker run -dt --name "$CPX_NAME" --network "$NET" \
  -p 19080:9080 -p 8443:443 jumbo-adc-mock:latest >/dev/null

echo -n "NITRO hazır bekleniyor"
if wait_nitro 20; then
  echo " ✓"
  echo -n "  Sürüm: "; nitro_get nsversion | python3 -c "import sys,json;print(json.load(sys.stdin)['nsversion']['version'])" 2>/dev/null || true
  echo "  IP (jumbo-net): $(net_ip "$CPX_NAME")"
  echo "Hazır (MOCK — gerçek NetScaler değil). Sonraki: ./bootstrap-nitro.sh"
else
  echo " ✗"; docker logs "$CPX_NAME" 2>&1 | tail -20; exit 1
fi
