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

## Şema (MSSQL)
- **Taze DB**: uygulama açılışta `create_all` + `ensure_new_columns` + `ensure_indexes` ile şemayı KENDİ kurar.
  Elle kurmak istersen: `schema-mssql.sql` (repo kökü; models'ten üretilmiş tam DDL).
- **Mevcut/eski DB**: `schema-mssql.sql`'i mevcut yapınla karşılaştırıp eksik tablo/kolon/index'i uygula.
  Sürüm yönetimi için Alembic önerilir (istenirse eklenir).
