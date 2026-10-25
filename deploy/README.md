# JUMBO — Dağıtım

## Birincil: TEK CONTAINER (nginx + uvicorn, OpenShift uyumlu)

Tek imaj; içinde React SPA + nginx + FastAPI/uvicorn. `supervisord` iki süreci yönetir.

```
  Dış istek ──▶ nginx :8080 ──┬─▶ /api/*  ──▶ uvicorn 127.0.0.1:5000 ──▶ MSSQL (container dışı)
   (ÖNYÜZ)                     └─▶ /*      ──▶ nginx :9080 ──▶ React SPA (statik dosyalar)
```
- **Port düzeni**: ÖNYÜZ (ön kapı) `:8080` (nginx). `/api` → `127.0.0.1:5000` (uvicorn), `/*` → frontend
  `:9080` (React SPA statik). Backend (5000) dışarı KAPALI. 8080 birincil; 9080 frontend'e doğrudan erişim.
- Frontend zaten **relatif `/api`** çağırır (`axios baseURL:'/api'`) → tek origin, CORS yok, kod değişmez.
- MSSQL container'ın DIŞINDADIR. Sürücü **pymssql** (ODBC sürücüsü GEREKMEZ). Bağlantı **parça-parça
  ENV**'den kurulur (`config.effective_database_url` → `mssql+pymssql://USER:PASS@HOST:PORT/DB`):
  `MSSQL_HOST`, `MSSQL_PORT` (vars. 1433), `MSSQL_USER`, `MSSQL_PASSWORD`, `MSSQL_DB`.
  Hesap **DDL yetkili** olmalı (ilk açılışta `create_all` + `ALTER` + `CREATE INDEX` çalışır).
- Alternatif: `MSSQL_HOST` boşsa `DATABASE_URL` kullanılır (SQLite dev/test veya tam pymssql URL'i).

### Derleme
Build context = repo kökü:
```bash
docker build -t jumbo:latest .
```

### Yerel çalıştırma (tek container)
> **GÜVENLİK (SEC-4):** MSSQL'e karşı çalışırken **`JWT_SECRET` ZORUNLU** — imajda kullanılabilir bir
> varsayılan YOK (bilinçli; kaynaktaki bilinen anahtarla token sahteciliğini önler). Boş/`change-me-in-production`
> ise uygulama açılmaz. Ayrıca LDAP/SMTP/Vault sırlarını saklamak için **`FERNET_KEY`** gerekir (yoksa
> hassas ayar düz-metin YAZILMAZ, atlanır).
```bash
# Yerel dev MSSQL (jumbo-mssql) — JWT_SECRET (+FERNET_KEY) ver:
docker run -d --name jumbo --network jumbo-net -p 8080:8080 -p 9080:9080 \
  -e MSSQL_DB=JUMBOBP \
  -e JWT_SECRET="$(openssl rand -base64 48)" \
  -e FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  jumbo:latest

# Başka MSSQL'e bağlanmak için:
docker run -d --name jumbo --network jumbo-net -p 8080:8080 -p 9080:9080 \
  -e MSSQL_HOST=baska-host -e MSSQL_USER=jumbo -e MSSQL_PASSWORD='...' -e MSSQL_DB=JUMBO2 \
  -e JWT_SECRET="$(openssl rand -base64 48)" jumbo:latest

# MSSQL'siz hızlı smoke (SQLite → SEC-4 muaf, JWT_SECRET gerekmez; arbitrary-UID uyumunu da doğrular):
docker run -d --name jumbo --user 1000670000:0 -p 8080:8080 -p 9080:9080 \
  -e MSSQL_HOST='' -e DATABASE_URL='sqlite:////tmp/jumbo.db' jumbo:latest

# Aç:  http://localhost:8080   (önyüz; admin / admin)
```
> Not: İmajdaki varsayılan MSSQL_* değerleri **yerel dev içindir** (dev şifresi dahil). Prod'da
> `jumbo-k8s.yaml` env + Secret bunların HEPSİNİ ezer.
Loglar: `docker logs jumbo` — hem `[program:api]` (uvicorn) hem `[program:web]` (nginx) tek stdout'ta.
`LOG_LEVEL` (varsayılan `INFO`) nginx'in erişim-log hacmini de belirler: `DEBUG` → TÜM istekler
loglanır; diğer her değer → yalnız 2xx/3xx DIŞI (hata) istekler loglanır (bkz.
`deploy/nginx-entrypoint.sh`). Örn: `docker run ... -e LOG_LEVEL=DEBUG jumbo:latest`.

`supervisord` `api` (uvicorn) ve `web` (nginx) süreçlerini PARALEL başlatır; backend DB şeması/
migration işi nedeniyle portu (`:5000`) birkaç saniye geç açar. `nginx-entrypoint.sh` nginx'i
başlatmadan ÖNCE bu portun açılmasını bekler (azami 30sn) — böylece container ayağa kalkarken
`/api/*` isteklerine geçici `502 Bad Gateway` dönme riski ortadan kalkar (nginx backend hazır
olana kadar hiç bağlantı kabul etmez).

### OpenShift / Kubernetes
```bash
# Secret içindeki database-url / jwt-secret / fernet-key değerlerini doldur:
kubectl apply -f deploy/jumbo-k8s.yaml         # tek container Deployment + Service
oc expose svc/jumbo                            # OpenShift: dış erişim için Route (TLS Route'ta sonlanır)
```
- İmaj **arbitrary-UID uyumludur** (pid/temp `/tmp`, yazılabilir dizinler GID 0'a açık, port >1024) →
  OpenShift SCC için özel `securityContext`/UID gerekmez.
- **Sürücü**: MSSQL bağlantısı **pymssql** ile (FreeTDS pip wheel'inde gömülü) → imajda ayrı ODBC
  sürücüsü / Microsoft deposu / imza kurulumu YOK. Prod'da ek sürücü işi gerekmez.

### GitHub'dan imaj (ghcr.io)
`.github/workflows/image.yml` main'e her birleştirmede (ve Actions sekmesinden **Run workflow** ile elle)
imajı derleyip GitHub Container Registry'ye gönderir:
```
ghcr.io/cgn-t/jumbo:<backend/VERSION>   # örn. ghcr.io/cgn-t/jumbo:3.8.12
ghcr.io/cgn-t/jumbo:latest
ghcr.io/cgn-t/jumbo:<commit kısa SHA>
```
Paket ilk gönderimde **private** olur. OpenShift'in çekebilmesi için iki yol var:
- **Pull secret (önerilen):** GitHub'da `read:packages` izinli bir token (classic PAT) oluşturun, sonra
  ```bash
  oc create secret docker-registry ghcr-pull --docker-server=ghcr.io \
     --docker-username=<github-kullanici> --docker-password=<token>
  oc secrets link default ghcr-pull --for=pull
  ```
- **Ya da** GitHub'da paketi *Package settings → Change visibility → Public* yapın (secret gerekmez).

Sonra Deployment'taki imajı sürüm etiketiyle verin (`latest` yerine sabit sürüm önerilir):
```bash
oc set image deployment/jumbo jumbo=ghcr.io/cgn-t/jumbo:3.8.12
# ya da ImageStream ile:  oc import-image jumbo:3.8.12 --from=ghcr.io/cgn-t/jumbo:3.8.12 --confirm
```
OpenShift ghcr.io'ya doğrudan erişemiyorsa (kapalı ağ): imajı `skopeo copy` / `oc image mirror` ile
şirket içi registry'ye aktarın.

## Birden fazla pod / cluster (aktif-aktif, v3.9.12+)

Uygulama aynı MSSQL'e bağlı birden fazla pod'da (farklı cluster'lar dahil) çalışabilir.

- **JWT_SECRET ve FERNET_KEY her yerde birebir aynı olmalı.** Aksi halde kullanıcı başka pod'a
  düşünce oturumdan atılır, LDAP/SMTP şifreleri okunamaz.
- **Zamanlanmış işler** (08:00/08:05 mailleri, talep hatırlatması, canlı doğrulama, iptal
  denetimi, keşif, CT, mail kuyruğu, Jenkins poll) her pod'da zamanlanır ama başlamadan önce
  veritabanından işe ait kilidi alır (`sp_getapplock`, yeni tablo yok). Kilidi alamayan ya da
  aynı işin son 30 dakikada başka pod'da başladığını gören pod atlar. Pod iş sırasında çökerse
  bağlantısı kopar ve MSSQL kilidi kendisi bırakır.
- **İşleri dışarıdan tetiklemek** isterseniz Ayarlar'da otomatik çalışmayı kapatın ve tek bir
  dış araçtan (cron/Jenkins — yalnız BİR yerde kurun) çağırın. Hepsi `X-API-Key` ister;
  anahtarlar Ayarlar'da ilgili sekmede:

  | İş | Tetik | Durum | Anahtar |
  |---|---|---|---|
  | Süre uyarısı | `POST /api/notifications/expiry-run` | `GET …/expiry-run/status` | SMTP |
  | Süresi geçmiş | `POST /api/notifications/expired-run` | `GET …/expired-run/status` | SMTP |
  | Talep hatırlatması | `POST /api/notifications/proposal-run` | `GET …/proposal-run/status` | SMTP |
  | Canlı doğrulama | `POST /api/domains/live-check-run` | `GET …/live-check-run/status` | Canlı Doğrulama |
  | İptal denetimi | `POST /api/certificates/revocation-run` | `GET …/revocation-run/status` | İptal Durumu |
  | Ağ keşfi | `POST /api/discovery/scan` | `GET /api/discovery/scan/status` | Ağ Keşfi |
  | CT izleme | `POST /api/discovery/ct-scan` | `GET /api/discovery/ct-scan/status` | CT |

  Dış tetik hemen döner, iş arka planda yürür. Mail tetiklerinde tekrar-önleme açıktır: araç
  zaman aşımına düşüp tekrar denerse aynı kişiye ikinci mail gitmez. Aynı iş başka yerde
  sürüyorsa `409`, 60 saniye içinde ikinci dış tetik `429` döner.
- **Yeni sürüm** açılırken şema güncellemesini tek pod yapar, diğerleri bekler.
- Ayarlar'da değiştirilen saatler tüm pod'larda en geç 1 dakikada geçerli olur.
- Kilidi denemek için uygulamanın DB kullanıcısıyla:
  `DECLARE @r int; BEGIN TRAN; EXEC @r = sp_getapplock @Resource='jumbo-test', @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=0; SELECT @r; ROLLBACK;`
  → `0` beklenir. Kilit kullanılamazsa uygulama durmaz, logda "Veritabanı iş kilidi
  (sp_getapplock) kullanılamadı" yazar ve pod içi kilide düşer (pod'lar arası koruma olmaz).

## Şema (MSSQL)
- **Taze DB**: uygulama açılışta `create_all` + `ensure_new_columns` + `ensure_indexes` ile şemayı KENDİ kurar.
  Elle kurmak istersen: `schema-mssql.sql` (repo kökü; models'ten üretilmiş tam DDL).
- **Mevcut/eski DB**: `schema-mssql.sql`'i mevcut yapınla karşılaştırıp eksik tablo/kolon/index'i uygula.
  Sürüm yönetimi için Alembic önerilir (istenirse eklenir).
