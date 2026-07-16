#!/usr/bin/env bash
# "ÖNCE" durumu: ESKİ cert'i yükle → sslcertkey + SSL vserver + backend service + bind.
# Backend olarak jumbo konteynerini (nginx :8080) kullanır → vserver UP olur, TLS handshake'te cert sunulur.
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh

[ -f "$CERTS_DIR/old.cer" ] || { echo "Önce ./gen-demo-certs.sh çalıştırın."; exit 1; }

CPX_IP=$(net_ip "$CPX_NAME");  [ -n "$CPX_IP" ]  || { echo "CPX çalışmıyor mu? ./run-cpx.sh"; exit 1; }
JUMBO_IP=$(net_ip jumbo);      [ -n "$JUMBO_IP" ] || { echo "jumbo konteyneri jumbo-net'te değil."; exit 1; }
echo "CPX_IP=$CPX_IP  JUMBO_IP=$JUMBO_IP (backend)"

echo "1) LB + SSL özelliklerini aç"
nitro_post "nsfeature?action=enable" '{"nsfeature":{"feature":["LB","SSL"]}}' >/dev/null || true

echo "2) ESKİ cert dosyalarını yükle (/nsconfig/ssl)"
nitro_upload "$CERTS_DIR/old.cer" old.cer >/dev/null
nitro_upload "$CERTS_DIR/old.key" old.key >/dev/null

echo "3) sslcertkey '$CERTKEY' (ESKİ) oluştur"
nitro_post sslcertkey "{\"sslcertkey\":{\"certkey\":\"$CERTKEY\",\"cert\":\"old.cer\",\"key\":\"old.key\"}}"

echo "4) SSL vserver '$VSERVER' ($CPX_IP:443) + backend service '$SERVICE' ($JUMBO_IP:8080)"
nitro_post lbvserver "{\"lbvserver\":{\"name\":\"$VSERVER\",\"servicetype\":\"SSL\",\"ipv46\":\"$CPX_IP\",\"port\":443}}"
nitro_post service   "{\"service\":{\"name\":\"$SERVICE\",\"ip\":\"$JUMBO_IP\",\"servicetype\":\"HTTP\",\"port\":8080}}"
nitro_post lbvserver_service_binding "{\"lbvserver_service_binding\":{\"name\":\"$VSERVER\",\"servicename\":\"$SERVICE\"}}"

echo "5) cert'i vserver'a bağla"
nitro_post sslvserver_sslcertkey_binding "{\"sslvserver_sslcertkey_binding\":{\"vservername\":\"$VSERVER\",\"certkeyname\":\"$CERTKEY\"}}"

echo "6) kaydet"
nitro_post "nsconfig?action=save" '{"nsconfig":{}}' >/dev/null

echo "Bitti. Doğrula:  ./verify.sh   (ESKİ / OLD-CERT fingerprint'i görmelisiniz)"
