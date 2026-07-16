#!/usr/bin/env bash
# NetScaler CPX'i jumbo-net üzerinde başlatır ve NITRO hazır olana kadar bekler.
#  9080/9443 = NITRO yönetim (http/https) · host 8443 → container 443 (SSL vserver veri düzlemi)
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh

if docker ps -a --format '{{.Names}}' | grep -qx "$CPX_NAME"; then
  echo "HATA: '$CPX_NAME' zaten var. Silmek için:  docker rm -f $CPX_NAME"
  exit 1
fi

echo "CPX başlatılıyor ($CPX_IMAGE)..."
# Host portları: 19080/19443 (NITRO; 9080 jumbo'da dolu), 8443→443 (veri düzlemi).
# CPX linux/amd64 → Apple Silicon'da emülasyon (--platform).
docker run -dt --name "$CPX_NAME" --network "$NET" --platform linux/amd64 \
  -e EULA=yes --cap-add=NET_ADMIN --ulimit core=-1 \
  -p 19080:9080 -p 19443:9443 -p 8443:443 \
  "$CPX_IMAGE" >/dev/null

echo -n "NITRO hazır bekleniyor (nsversion)"
if wait_nitro 40; then
  echo " ✓"
  echo -n "  Sürüm: "; nitro_get nsversion | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('nsversion',{}).get('version','?'))" 2>/dev/null || true
  echo "  CPX IP (jumbo-net): $(net_ip "$CPX_NAME")"
  echo "Hazır. Sonraki: ./bootstrap-nitro.sh"
else
  echo " ✗"
  echo "NITRO yanıt vermedi. Log: docker logs $CPX_NAME | tail -40"
  echo "Kimlik farklı olabilir → NS_PASS env'i deneyin (varsayılan nsroot/nsroot)."
  exit 1
fi
