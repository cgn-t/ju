#!/usr/bin/env bash
# JENKINS JOB TAKLİDİ — custody-free yerinde cert değişimi:
#   1) Vault'tan YENİ cert+key oku (anahtar buradan gelir, JUMBO değil)
#   2) CPX'e NITRO ile yükle
#   3) update sslcertkey (AD SABİT → bağlı tüm vserver'lar otomatik yeni cert'i sunar)
#   4) save
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh

STAMP=$(date +%H%M%S)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "1) Vault'tan YENİ cert+key çekiliyor ($VAULT_KV)"
vex() { docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VAULT_TOKEN_ID" "$VAULT_NAME" "$@"; }
vex vault kv get -field=cert_b64 "$VAULT_KV" | base64 -d > "$TMP/new.cer"
vex vault kv get -field=key_b64  "$VAULT_KV" | base64 -d > "$TMP/new.key"
echo "   yeni cert: $(openssl x509 -in "$TMP/new.cer" -noout -subject | sed 's/^subject=//')"

echo "2) CPX'e yükle (yeni dosya adları: new_$STAMP.*)"
nitro_upload "$TMP/new.cer" "new_$STAMP.cer" >/dev/null
nitro_upload "$TMP/new.key" "new_$STAMP.key" >/dev/null

echo "3) YERİNDE update: sslcertkey '$CERTKEY' → yeni cert (nodomaincheck)"
nitro_post "sslcertkey?action=update" \
  "{\"sslcertkey\":{\"certkey\":\"$CERTKEY\",\"cert\":\"new_$STAMP.cer\",\"key\":\"new_$STAMP.key\",\"nodomaincheck\":true}}"

echo "4) kaydet"
nitro_post "nsconfig?action=save" '{"nsconfig":{}}' >/dev/null

echo "Bitti — cert '$CERTKEY' üzerinde yerinde değişti. Doğrula:  ./verify.sh  (YENİ / NEW-CERT görmelisiniz)"
echo "Not: anahtar Vault→script→CPX yolunu izledi; JUMBO süreci anahtara dokunmadı."
