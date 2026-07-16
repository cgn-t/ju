#!/bin/sh
# Jenkins 'netscaler-deploy' job'unun gövdesi — custody-free yerinde cert değişimi.
# Parametreler env'den gelir (Jenkins build parametreleri): CERTKEY NS_MGMT VAULT_ADDR VAULT_PATH
# Gizli: VAULT_TOKEN (withCredentials ile). Anahtar Vault→Jenkins→NITRO; JUMBO görmez.
set -e
: "${CERTKEY:?CERTKEY gerekli}"; : "${NS_MGMT:?}"; : "${VAULT_ADDR:?}"; : "${VAULT_PATH:?}"; : "${VAULT_TOKEN:?}"

echo "[jenkins] Vault'tan cert+key okunuyor: $VAULT_ADDR/v1/$VAULT_PATH"
DATA=$(curl -sf -H "X-Vault-Token: $VAULT_TOKEN" "$VAULT_ADDR/v1/$VAULT_PATH")
echo "$DATA" | jq -r '.data.data.cert_b64' | base64 -d > /tmp/new.cer
echo "$DATA" | jq -r '.data.data.key_b64'  | base64 -d > /tmp/new.key
echo "[jenkins] yeni cert: $(openssl x509 -in /tmp/new.cer -noout -subject 2>/dev/null | sed 's/^subject=//' || echo '(openssl yok)')"

STAMP=$(date +%s)
CB=$(base64 -w0 /tmp/new.cer); KB=$(base64 -w0 /tmp/new.key)
NS="http://$NS_MGMT/nitro/v1/config"
AUTH='-H X-NITRO-USER:nsroot -H X-NITRO-PASS:nsroot -H Content-Type:application/json'

echo "[jenkins] NITRO systemfile upload (jk_${CERTKEY}_${STAMP}.*)"
curl -sf $AUTH -X POST "$NS/systemfile" \
  -d "{\"systemfile\":{\"filename\":\"jk_${CERTKEY}_${STAMP}.cer\",\"filelocation\":\"/nsconfig/ssl\",\"filecontent\":\"$CB\",\"fileencoding\":\"BASE64\"}}" >/dev/null
curl -sf $AUTH -X POST "$NS/systemfile" \
  -d "{\"systemfile\":{\"filename\":\"jk_${CERTKEY}_${STAMP}.key\",\"filelocation\":\"/nsconfig/ssl\",\"filecontent\":\"$KB\",\"fileencoding\":\"BASE64\"}}" >/dev/null

echo "[jenkins] NITRO update sslcertkey '$CERTKEY' (YERİNDE, nodomaincheck)"
curl -sf $AUTH -X POST "$NS/sslcertkey?action=update" \
  -d "{\"sslcertkey\":{\"certkey\":\"$CERTKEY\",\"cert\":\"jk_${CERTKEY}_${STAMP}.cer\",\"key\":\"jk_${CERTKEY}_${STAMP}.key\",\"nodomaincheck\":true}}"
curl -sf $AUTH -X POST "$NS/nsconfig?action=save" -d '{"nsconfig":{}}' >/dev/null

echo "[jenkins] Bitti — '$CERTKEY' güncellendi (anahtar Vault→Jenkins→NITRO)."
