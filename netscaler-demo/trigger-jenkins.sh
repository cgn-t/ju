#!/usr/bin/env bash
# Jenkins 'netscaler-deploy' job'unu curl ile tetikler (JUMBO'nun yapacağının aynısı).
# Kullanım:  ./trigger-jenkins.sh [CERTKEY]   (varsayılan demo_ck)
set -euo pipefail
cd "$(dirname "$0")"
JBASE=${JENKINS_URL:-http://localhost:18080}
JUSER=${JENKINS_USER:-jumbo}; JPASS=${JENKINS_PASS:-jumbo123}
CERTKEY=${1:-demo_ck}
VAULT_PATH=${VAULT_PATH:-secret/data/certs/demo}

# CSRF crumb + POST AYNI oturumu paylaşmalı → cookie jar (JSESSIONID) ortak kullan.
JAR=$(mktemp); trap 'rm -f "$JAR"' EXIT
CRUMB=$(curl -sf -u "$JUSER:$JPASS" -c "$JAR" "$JBASE/crumbIssuer/api/json" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['crumbRequestField']+':'+d['crumb'])" 2>/dev/null || true)
[ -n "$CRUMB" ] && echo "crumb alındı (${CRUMB%%:*})" || echo "UYARI: crumb alınamadı"

echo "Job tetikleniyor: netscaler-deploy (CERTKEY=$CERTKEY, VAULT_PATH=$VAULT_PATH)"
curl -sf -u "$JUSER:$JPASS" -b "$JAR" ${CRUMB:+-H "$CRUMB"} -X POST \
  "$JBASE/job/netscaler-deploy/buildWithParameters" \
  --data-urlencode "CERTKEY=$CERTKEY" \
  --data-urlencode "VAULT_PATH=$VAULT_PATH" -o /dev/null -w "HTTP %{http_code} (201/302 = kuyruğa alındı)\n"
echo "Build logu:  $JBASE/job/netscaler-deploy/lastBuild/console"
echo "Sonuç doğrulama:  ./verify.sh"
