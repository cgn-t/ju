#!/usr/bin/env bash
# jumbo (uygulama) imajını kök Dockerfile'dan DERLER ve jumbo-net üzerinde başlatır.
# Kullanım:  ./run.sh
#
# Gizli anahtarlar .env'den okunur (git dışı). RECREATE'te JWT_SECRET/FERNET_KEY AYNI kalır:
#   - .env yoksa ve çalışan bir 'jumbo' varsa → secret'lar ondan alınır (KORUNUR).
#   - .env yoksa ve container da yoksa → JWT/FERNET taze üretilir, MSSQL_PASSWORD size bırakılır.
# NEDEN önemli: FERNET_KEY değişirse DB'deki şifreli alanlar OKUNAMAZ; JWT_SECRET değişirse
#              tüm oturumlar düşer. Bu yüzden .env sabit tutulur, ASLA commit edilmez.
set -euo pipefail
cd "$(dirname "$0")"

NAME=${JUMBO_NAME:-jumbo}
NET=${NET:-jumbo-net}
IMAGE=${IMAGE:-jumbo:latest}
ENV_FILE=.env
KEYS='MSSQL_HOST|MSSQL_PORT|MSSQL_USER|MSSQL_DB|MSSQL_PASSWORD|JWT_SECRET|FERNET_KEY'

# --- 1) Gizli anahtarlar: .env yoksa güvenli şekilde hazırla ---
if [ ! -f "$ENV_FILE" ]; then
  if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "ℹ️  .env yok → mevcut '$NAME' container'ından secret'lar alınıyor (KORU)..."
    docker inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | grep -E "^($KEYS)=" > "$ENV_FILE"
    echo "   → $ENV_FILE yazıldı (git dışı; JWT_SECRET/FERNET_KEY korundu)."
  else
    echo "ℹ️  .env yok ve çalışan '$NAME' yok → TAZE secret üretiliyor..."
    {
      echo "MSSQL_HOST=jumbo-mssql"
      echo "MSSQL_PORT=1433"
      echo "MSSQL_USER=sa"
      echo "MSSQL_DB=JUMBOBP"
      echo "MSSQL_PASSWORD=CHANGE_ME"
      echo "JWT_SECRET=$(openssl rand -hex 32)"
      echo "FERNET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
    } > "$ENV_FILE"
    echo "   ⚠️  $ENV_FILE oluşturuldu — MSSQL_PASSWORD'ü düzenleyip ./run.sh'i tekrar çalıştırın."
    exit 1
  fi
fi

# --- 2) İmajı derle ---
echo "jumbo imajı derleniyor ($IMAGE)..."
docker build -t "$IMAGE" .

# --- 3) Çalışan container'a DOKUNMA (yıkıcı değil) ---
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "HATA: '$NAME' zaten var. Yeniden oluşturmak için:"
  echo "      docker rm -f $NAME && ./run.sh      (.env korunur → JWT/FERNET aynı kalır)"
  exit 1
fi

# --- 4) Başlat ---
docker run -d --name "$NAME" --network "$NET" \
  -p 8080:8080 -p 9080:9080 \
  --env-file "$ENV_FILE" --restart unless-stopped "$IMAGE" >/dev/null

echo "✅ jumbo başlatıldı → http://localhost:8080   (ağ: $NET)"
echo "   Loglar: docker logs -f $NAME"
