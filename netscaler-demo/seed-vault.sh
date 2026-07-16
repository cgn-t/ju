#!/usr/bin/env bash
# YENİ cert+key'i Vault'a koyar (custody: anahtarın kaynağı Vault). Demo için dev-mode Vault
# (jumbo-vault-demo) kullanır — otomatik unseal, KV v2 'secret/' hazır, kök token = demo-root.
# Prod'da bu adım gerçek Vault'tur; swap script'i (Jenkins taklidi) buradan okur.
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh

[ -f "$CERTS_DIR/new.cer" ] || { echo "Önce ./gen-demo-certs.sh çalıştırın."; exit 1; }

if ! docker ps --format '{{.Names}}' | grep -qx "$VAULT_NAME"; then
  docker rm -f "$VAULT_NAME" >/dev/null 2>&1 || true
  echo "dev-mode Vault başlatılıyor ($VAULT_NAME)..."
  docker run -d --name "$VAULT_NAME" --network "$NET" --cap-add IPC_LOCK \
    -e VAULT_DEV_ROOT_TOKEN_ID="$VAULT_TOKEN_ID" \
    -e VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200 \
    -p 18200:8200 hashicorp/vault:1.18 >/dev/null
  sleep 3
fi

vex() { docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VAULT_TOKEN_ID" "$VAULT_NAME" "$@"; }

echo -n "Vault hazır bekleniyor"; for i in $(seq 1 15); do vex vault status >/dev/null 2>&1 && break; echo -n .; sleep 1; done; echo " ✓"

CERT_B64=$(base64 < "$CERTS_DIR/new.cer" | tr -d '\n')
KEY_B64=$(base64 < "$CERTS_DIR/new.key" | tr -d '\n')
vex vault kv put "$VAULT_KV" cert_b64="$CERT_B64" key_b64="$KEY_B64" >/dev/null

echo "YENİ cert+key Vault'a yazıldı → $VAULT_KV"
vex vault kv get -format=json "$VAULT_KV" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']['data']; print('  alanlar:', list(d.keys()))"
echo "Sonraki: ./swap-cert.sh   (Vault'tan okuyup CPX'te yerinde değiştirir)"
