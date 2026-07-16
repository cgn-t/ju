#!/usr/bin/env bash
# İki self-signed demo çifti üretir: ESKİ ve YENİ. Farklı O= ve seri → fingerprint gözle görülür değişir.
# Çıktı: certs/old.cer certs/old.key certs/new.cer certs/new.key
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh
mkdir -p "$CERTS_DIR"

gen() { # $1=etiket(O=) $2=gün $3=dosya-önek
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CERTS_DIR/$3.key" -out "$CERTS_DIR/$3.cer" \
    -days "$2" -subj "/CN=demo.jumbo.local/O=$1" \
    -addext "subjectAltName=DNS:demo.jumbo.local" 2>/dev/null
  echo "  $3 → $(openssl x509 -in "$CERTS_DIR/$3.cer" -noout -subject -fingerprint -sha256 | tr '\n' ' ')"
}

echo "Demo sertifikaları üretiliyor ($CERTS_DIR):"
gen "OLD-CERT-2025" 365 old
gen "NEW-CERT-2026" 730 new
echo "Bitti. 'old' bootstrap'ta yüklenir; 'new' Vault'a konup swap'ta kullanılır."
