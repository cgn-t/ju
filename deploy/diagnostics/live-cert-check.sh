#!/usr/bin/env bash
# Canlı doğrulamanın gördüğü sertifikayı elle kontrol etme (yalnız okuma — hiçbir şeyi değiştirmez).
#
# JUMBO canlı doğrulaması HTTP yönlendirmesini (301/302) TAKİP ETMEZ: host:port'a bağlanır ve TLS el
# sıkışmasında sunucunun gönderdiği zinciri alır (SNI = host). Tarayıcı ise yönlendirmeden sonraki
# adresin sertifikasını gösterir — örn. stablex.net → stablex.com yönlendirmesinde tarayıcı kilidi
# stablex.com'u gösterir, ama JUMBO'nun kontrol ettiği stablex.net'in kendi sertifikasıdır.
#
# Kullanım (JUMBO'nun çalıştığı ağdan):
#   ./live-cert-check.sh stablex.net            # 443
#   ./live-cert-check.sh xxx.aaakkk.com 8228
#
# Çıktıdaki SHA-256 parmak izini Devir Önerileri → İncele ekranındaki "YENİ" sertifikanın parmak
# iziyle karşılaştırın: aynıysa öneri doğrudur.

set -euo pipefail

host="${1:?Kullanım: $0 <host> [port]}"
port="${2:-443}"

echo "== Sunulan zincir: ${host}:${port} (SNI=${host})"
chain=$(openssl s_client -connect "${host}:${port}" -servername "${host}" -showcerts </dev/null 2>/dev/null) || true
if ! grep -q "BEGIN CERTIFICATE" <<<"$chain"; then
  echo "Bağlanılamadı ya da sertifika alınamadı (ağ erişimi / port / firewall kontrol edin)." >&2
  exit 1
fi

# Zincirdeki her sertifikayı sırayla (leaf → root) yazdır
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
awk -v dir="$tmp" '/BEGIN CERTIFICATE/{n++; f=1} f{print > (dir "/" sprintf("%02d", n) ".pem")} /END CERTIFICATE/{f=0}' <<<"$chain"
i=0
for pem in "$tmp"/*.pem; do
  echo
  echo "-- [$i] $( [ "$i" -eq 0 ] && echo 'leaf (sunucunun kendi sertifikası)' || echo 'zincir' )"
  openssl x509 -in "$pem" -noout -subject -issuer -startdate -enddate -serial -fingerprint -sha256
  openssl x509 -in "$pem" -noout -ext subjectAltName 2>/dev/null | sed 's/^/   /' || true
  i=$((i + 1))
done

echo
echo "== HTTP yanıtı (bilgi amaçlı — JUMBO bunu takip etmez)"
curl -skI -m 10 "https://${host}:${port}/" | grep -iE '^(HTTP|location)' || echo "HTTP yanıtı alınamadı"
