#!/bin/sh
# Pod içinde çalıştırın: sunucunun TLS'te sunduğu sertifikayı gösterir (yalnız okur).
# Kullanım: sh pod-cert-check.sh            -> stablex.net:443
#           sh pod-cert-check.sh host [port]

HOST="${1:-stablex.net}"
PORT="${2:-443}"

openssl s_client -connect "$HOST:$PORT" -servername "$HOST" </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -serial -fingerprint -sha256
