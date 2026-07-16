#!/usr/bin/env bash
# Yerel Jenkins'i (jumbo-jenkins) jumbo-net üzerinde kurar/başlatır. UI: http://localhost:18080
# JCasC ile hazır gelir: kullanıcılar (admin/jumbo), vault-token, 'netscaler-deploy' job'u.
set -euo pipefail
cd "$(dirname "$0")"
source ./lib.sh
JNAME=${JENKINS_NAME:-jumbo-jenkins}

if docker ps -a --format '{{.Names}}' | grep -qx "$JNAME"; then
  echo "HATA: '$JNAME' zaten var → docker rm -f $JNAME"
  exit 1
fi

echo "Jenkins imajı derleniyor (eklenti indirme birkaç dk sürebilir)..."
docker build -t jumbo-jenkins:latest ./jenkins

echo "Jenkins başlatılıyor ($JNAME)  ·  UI host:18080  ·  jumbo-net"
docker run -d --name "$JNAME" --network "$NET" -p 18080:8080 jumbo-jenkins:latest >/dev/null

echo -n "Jenkins + JCasC job hazır bekleniyor"
ok=
for i in $(seq 1 48); do
  if curl -sf -m 5 -u jumbo:jumbo123 "http://localhost:18080/job/netscaler-deploy/api/json" >/dev/null 2>&1; then
    ok=1; echo " ✓"; break
  fi
  echo -n .; sleep 5
done
if [ -z "$ok" ]; then
  echo " ✗"; echo "Loglar:  docker logs $JNAME | tail -50"; exit 1
fi
echo "  UI:  http://localhost:18080   (admin/admin123 · jumbo/jumbo123)"
echo "  Job: netscaler-deploy (parametreli: CERTKEY, NS_MGMT, VAULT_ADDR, VAULT_PATH)"
echo "Sonraki: ./trigger-jenkins.sh   (curl ile tetikleyip mock ADC'de cert değişimini görün)"
