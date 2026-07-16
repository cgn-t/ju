# JUMBO demo Jenkins

Yerel, tek-container Jenkins — **JUMBO'nun tetiklediği** `netscaler-deploy` job'unu barındırır.
Setup sihirbazı kapalı; her şey **JCasC** (`jenkins.yaml`) ile hazır gelir. Amaç: NetScaler cert-swap
akışında **Vault → Jenkins → NITRO** orkestrasyonu — özel anahtar JUMBO'ya girmez (custody-free).

## Kaldır
```bash
cd netscaler-demo
./run-jenkins.sh          # imajı derler (eklenti indirir) + jumbo-net'te çalıştırır, JCasC job'unu bekler
```
- UI: <http://localhost:18080>  ·  giriş: `admin/admin123` veya `jumbo/jumbo123`
- Konteyner: `jumbo-jenkins` · ağ: `jumbo-net` · host portu `18080 → 8080`
- Hazır olunca `netscaler-deploy` job'u görünür.

## İçerik (`Dockerfile`)
`jenkins/jenkins:lts` + `jq`/`curl`/`openssl` + `ns-deploy.sh` (job gövdesi) + `plugins.txt`
eklentileri (configuration-as-code, job-dsl, workflow-aggregator, credentials-binding,
plain-credentials) + gömülü `jenkins.yaml` (JCasC). `runSetupWizard=false`.

## JCasC ile gelenler (`jenkins.yaml`)
| Öğe | Değer |
|---|---|
| Kullanıcılar | `admin/admin123`, `jumbo/jumbo123` (JUMBO bu kimlikle tetikler) |
| Kimlik bilgisi | `vault-token` (dev Vault kök token) |
| Job | `netscaler-deploy` — parametreli: `CERTKEY`, `NS_MGMT`, `VAULT_ADDR`, `VAULT_PATH` |

> ⚠️ Bu kimlikler **yalnız yerel demo** içindir; gerçek ortamda kullanılmaz.

## JUMBO bağlantısı
Ayarlar → **Jenkins** sekmesi: `Jenkins Adresi = http://jumbo-jenkins:8080` (aynı `jumbo-net`),
`Kullanıcı = jumbo`, `API Token/Parola = jumbo123`. Job **tetikleme** üst menüdeki **Dağıtım**
sayfasındadır (canlı build geçmişiyle).

## Elle tetikleme (JUMBO olmadan)
```bash
./trigger-jenkins.sh [CERTKEY]      # buildWithParameters — CSRF crumb otomatik (JUMBO'nun aynısı)
```
Build logu: <http://localhost:18080/job/netscaler-deploy/lastBuild/console>

## Temizlik
```bash
docker rm -f jumbo-jenkins
```
