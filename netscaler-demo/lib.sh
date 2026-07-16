# netscaler-demo ortak yardımcılar — diğer scriptler `source lib.sh` ile kullanır.
# NITRO REST çağrıları + konteyner IP keşfi. (Bu dosya tek başına çalıştırılmaz.)

# --- Ayarlar (env ile geçersiz kılınabilir) ---
NET=${NET:-jumbo-net}
CPX_NAME=${CPX_NAME:-jumbo-cpx}
CPX_IMAGE=${CPX_IMAGE:-quay.io/netscaler/netscaler-cpx:14.1-72.104}

NS_HOST=${NS_HOST:-localhost}          # host'tan NITRO yönetimi
NS_MGMT_PORT=${NS_MGMT_PORT:-19080}    # CPX NITRO HTTP (host 19080→9080; 9080 jumbo'da dolu)
NS_USER=${NS_USER:-nsroot}
NS_PASS=${NS_PASS:-nsroot}

VAULT_NAME=${VAULT_NAME:-jumbo-vault-demo}
VAULT_TOKEN_ID=${VAULT_TOKEN_ID:-demo-root}
VAULT_KV=${VAULT_KV:-secret/certs/demo}

CERTKEY=${CERTKEY:-demo_ck}            # NS'de sabit kalan cert-key adı (yerinde değişecek)
VSERVER=${VSERVER:-demo_vs}
SERVICE=${SERVICE:-demo_svc}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="${CERTS_DIR:-$HERE/certs}"

NITRO="http://$NS_HOST:$NS_MGMT_PORT/nitro/v1/config"
_hdr=(-H "X-NITRO-USER: $NS_USER" -H "X-NITRO-PASS: $NS_PASS" -H "Content-Type: application/json")

# nitro_post <kaynak[?action=...]> <json-gövde>
nitro_post() { curl -sS -m 30 "${_hdr[@]}" -X POST "$NITRO/$1" -d "$2"; echo; }
# nitro_get <kaynak>
nitro_get()  { curl -sS -m 30 "${_hdr[@]}" "$NITRO/$1"; echo; }
# nitro_upload <yerel-dosya> <NS'deki-ad>  → /nsconfig/ssl altına BASE64 yükler
nitro_upload() {
  local b64; b64=$(base64 < "$1" | tr -d '\n')
  nitro_post systemfile \
    "{\"systemfile\":{\"filename\":\"$2\",\"filelocation\":\"/nsconfig/ssl\",\"filecontent\":\"$b64\",\"fileencoding\":\"BASE64\"}}"
}

# jumbo-net üzerindeki bir konteynerin IP'si
net_ip() { docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$1" 2>/dev/null; }

# NITRO hazır mı? (nsversion 200 dönene kadar bekle)
wait_nitro() {
  local tries=${1:-40} i
  for i in $(seq 1 "$tries"); do
    if curl -sf -m 5 "${_hdr[@]}" "$NITRO/nsversion" >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  return 1
}
