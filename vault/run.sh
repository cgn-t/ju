#!/usr/bin/env bash
# JUMBO Vault'u KENDİ Dockerfile'ından (config.hcl + policies GÖMÜLÜ) DERLEYİP başlatır.
# Kullanım:  cd vault && ./run.sh
# Config/policy imaja gömülü olduğundan MOUNT gerekmez; yalnız kalıcı veri volume'ü bağlanır.
# Sonraki adımlar (init/unseal/PKI/KV/token) için README.md'ye bakın.
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="jumbo-vault:1.18"
NAME="jumbo-vault"

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "HATA: '$NAME' adlı bir konteyner zaten var."
  echo "      Eskisini silmek için:  docker rm -f $NAME   (dev/leftover ise veri kaybı olmaz)"
  exit 1
fi

echo "Vault imajı derleniyor ($IMAGE — config+policy gömülü)..."
docker build -t "$IMAGE" .

docker run -d --name "$NAME" --restart unless-stopped \
  -p 8200:8200 --cap-add IPC_LOCK \
  -e VAULT_ADDR=http://127.0.0.1:8200 \
  -v jumbo-vault-data:/vault/file \
  "$IMAGE" server

echo
echo "✅ Vault başlatıldı (mühürlü/başlatılmamış)."
echo "   Durum:   docker exec $NAME vault status"
echo "   Sonraki: docker exec $NAME vault operator init -key-shares=5 -key-threshold=3   (README §2)"
