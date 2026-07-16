# 🐘 JUMBO — Sertifika Yönetim Platformu (v2)

SSL sertifikalarını, domainleri ve bağımlılıklarını yöneten kurumsal platform.
React + FastAPI + MSSQL. LDAP/Active Directory kimlik doğrulama, rol bazlı yetki,
audit log, e-posta expiry uyarıları ve Vault entegrasyonuna hazır mimari.

## Mimari

```
jumbo/
├── backend/            FastAPI (Python 3.12+)
│   ├── app/
│   │   ├── api/        REST uçları (auth, certificates, domains, dashboard, cert-map,
│   │   │               applications, settings, users, audit)
│   │   ├── core/       config, JWT/rol güvenliği
│   │   ├── db/         SQLAlchemy modelleri + session
│   │   └── services/   cert_parser (PEM/DER/PFX), ldap_auth, audit, notifier,
│   │                   settings (Fernet şifreli), providers/ (Vault-hazır soyutlama)
│   ├── scripts/migrate_from_legacy.py   Eski DB'den veri taşıma (--dry-run destekli)
│   └── tests/          pytest (15 test) + openssl test zinciri fixtures/
├── frontend/           React 18 + TypeScript + Vite + MUI (koyu tema)
│   └── src/pages/      Dashboard, Certificates, Domains, CertMap (React Flow),
│                       Applications, Settings (LDAP/SMTP/Vault/Kullanıcılar/Audit)
├── deploy/             nginx + supervisord conf, k8s manifesti
├── vault/              HashiCorp Vault Docker kurulumu (compose + config + read-only policy + README)
├── Dockerfile          Tek imaj (nginx + uvicorn); build context = repo kökü
└── *.sql               Tablo DDL (schema-mssql.sql) + prod değişiklik script'leri
```

## Kurulum

### Backend

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env       # DATABASE_URL, JWT_SECRET, FERNET_KEY doldurun
./.venv/bin/uvicorn app.main:app --reload --port 8000
```

- **MSSQL** için `.env` içinde:
  `DATABASE_URL=mssql+pyodbc://kullanici:sifre@SUNUCU:1433/JUMBO2?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes`
  (macOS/Linux'ta `msodbcsql18` sürücüsü gerekir; tablolar ilk açılışta otomatik oluşturulur.)
- `FERNET_KEY` üretimi: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  — LDAP bind şifresi, SMTP şifresi ve Vault token'ı bu anahtarla at-rest şifrelenir.
- İlk açılışta `admin/admin` lokal yönetici oluşturulur (`.env` ile değiştirilebilir). **İlk girişten sonra şifreyi değiştirin.**
- API dokümantasyonu: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (API çağrıları 8000'e proxy'lenir)
```

Prod build: `npm run build` → `dist/` klasörünü nginx/IIS'ten servis edin,
`/api`'yi backend'e reverse proxy yapın.

### Eski veritabanından veri taşıma

```bash
cd backend
./.venv/bin/python scripts/migrate_from_legacy.py \
  --legacy-url "mssql+pyodbc://user:pass@10.241.156.180:1433/ESKIDB?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes" \
  --dry-run          # önce raporla, sonra --dry-run'ı kaldırıp çalıştır
```

Taşınanlar: SSLCertificates → certificates (hiyerarşi SKI/AKI'den yeniden kurulur),
domain_certificates → domains (+ sy/ug metinlerinden teams), mapping'ler, applications,
users (şifresiz; LDAP'a yönlendirilir). Idempotenttir, tekrar çalıştırılabilir.

## Özellikler

- **Dashboard** — SY takımı bazında domain adetleri, bitişe göre sıralı sertifika listesi (≤30 gün kalan rozetli)
- **SSL Sertifikaları** — hiyerarşik ağaç (Root ▸ Intermediate ▸ Leaf); binary import
  (PEM/fullchain/DER/PFX, alanlar otomatik çıkarılır, zincir SKI/AKI ile otomatik bağlanır,
  önizleme + mükerrer kontrolü) veya manuel ekleme; PEM kopyala/indir
- **Domainler** — kart/tablo görünümü, durum filtresi, CRUD, sertifikaları server/client olarak bağlama
- **Sertifika Haritası** — React Flow; tür ve bağlantı filtreleri, minimap, node tıklayınca detay
- **Uygulamalar** — sunucu/uygulama envanteri, domain ve takım ilişkileri
- **Ayarlar** (yalnız admin) — LDAP/AD (grup→rol eşleme, bağlantı testi), SMTP (günlük expiry
  uyarı maili), Vault (hazırlık), kullanıcı & rol yönetimi, audit log görüntüleme
- **Güvenlik** — JWT, roller (admin/editor/viewer), tüm mutasyonlarda audit kaydı,
  hassas ayarlar Fernet ile şifreli
- **SAN & Fingerprint** — sertifikalarda SubjectAltName listesi ve SHA-256 fingerprint
  saklanır; duplicate kontrolü fingerprint ile yapılır (SerialNumber tek başına yalnız
  aynı CA içinde benzersizdir). Eski kayıtlar startup'ta PEM'den otomatik doldurulur.
- **Canlı Doğrulama (Drift Detection)** — domain detayındaki "Şimdi Doğrula" butonu veya
  günlük 07:00 taraması, domain:port'ta gerçekte sunulan sertifikayı çekip eşlenmiş
  server sertifikalarıyla fingerprint üzerinden karşılaştırır. Durumlar: match /
  mismatch ("yenilendi ama deploy edilmedi" veya süresi dolmuş sertifika sunuluyor) /
  no_mapping (envanter dışı sertifika) / unreachable / not_checkable (wildcard).
  Mismatch'te tek tık düzeltme: "Canlıdaki Sertifikayı İçe Aktar ve Eşle".
- **Yenileme (Rotation) Devri** — kimlik daima SHA-256 fingerprint'tir; SKI anahtarın
  kimliğidir ve tekillik şartı DEĞİLDİR (aynı anahtarla yenilenen sertifika sorunsuz
  eklenir). Import önizlemesi yenilemeyi algılar (aynı SKI veya aynı CN+issuer) ve
  onayla eşlemeleri devredip eskiyi pasife alır (`superseded_by` zinciri). Vault
  senkronu rotasyonu TEMKİNLİ devirle işler: eşlemeler kopyalanır, eski aktif kalır;
  canlı doğrulama yeni sertifikayı sunucuda görünce devir otomatik tamamlanır.
  Elle devir: `POST /api/certificates/{yeni}/supersede/{eski}`.

## Bildirim API'si (dış tetikleme)

Süre-bazlı bilgilendirme mailleri günlük 08:00 cron'una ek olarak **dış bir araçla**
(cron, zamanlayıcı, izleme sistemi) da tetiklenebilir — login gerekmez:

| Uç | Ne yapar |
|---|---|
| `POST /api/notifications/expiry-run` | Bitişine **Uyarı Eşiği (gün)**'nden az kalan sertifikalar için bilgilendirme gönderir |
| `POST /api/notifications/expired-run` | **Süresi geçmiş ama JUMBO'da hâlâ aktif** (güncellenmemiş) sertifikalar için "JUMBO'da güncelleyin" hatırlatması gönderir |

**Kimlik doğrulama** (ikisi de iki yolu kabul eder):
- **Dış araç**: `X-API-Key` başlığı — anahtar *Settings → E-posta (SMTP) → Dış Tetikleme
  API Anahtarı*'nda tanımlanır. Anahtar boşsa dış tetikleme kapalıdır (fail-closed).
- **UI/insan**: admin JWT (`Authorization: Bearer …`) — Settings'teki butonlar bu yolu kullanır.

```bash
# Süresi yaklaşanlar
curl -X POST https://<host>/api/notifications/expiry-run  -H "X-API-Key: <anahtar>"
# Süresi geçmiş ve JUMBO'da güncellenmemişler
curl -X POST https://<host>/api/notifications/expired-run -H "X-API-Key: <anahtar>"
```

**Alıcılar** — her paydaş **ayrı mail** alır, gövdede alma nedeni listelenir:
1. Sertifikanın **sahibi** (oluşturan kullanıcının e-postası),
2. bağlı olduğu **domainlerin sahibi SY ekipleri** (`Team.email`, virgülle çoklu),
3. **client** olarak bağlı olduğu **uygulamaların sahibi SY ekipleri**.
Aynı ekip birden çok nedenle alıcıysa tek mail alır, nedenler birleşir.

**Yanıt**: `{"enabled": true, "checked": 12, "sent": 8, "skipped": 4, "message": "..."}`
(dış anahtar yalnız sayısal özet alır; admin JWT sertifika/alıcı detaylarını da görür).
SMTP kapalıysa `enabled: false` ile 200 döner, mail gitmez.

**Hata kodları**: `401` geçersiz/eksik anahtar · `429` çok fazla başarısız deneme
(60 sn'de >10) veya aynı ucun 60 sn içinde tekrar tetiklenmesi. Tüm tetiklemeler
audit log'a yazılır (dış aktör: `external-api`).

## LDAP / Active Directory

Settings → LDAP sekmesinden yapılandırılır: sunucu (ldaps://…), Base DN, bind hesabı,
kullanıcı filtresi ve **AD grubu → rol** eşlemesi (JSON). Login akışı: lokal hesap değilse
AD'de kullanıcı aranır → kullanıcının kendi şifresiyle bind → memberOf gruplarından rol atanır.
Lokal admin acil erişim için her zaman çalışır.

## Vault (HashiCorp Vault)

JUMBO Vault'a **READ-ONLY** bağlanır: PKI CA zincirini envantere alır (`{pki}/ca/pem`,
`{pki}/cert/ca_chain`) ve KV v2 kasadan okur. Sertifika üretimi/yenilemesi ve özel anahtar
velayeti JUMBO'da **değildir**; Vault + dış otomasyonda (Ansible/pipeline) kalır.

- **Vault'u Docker ile ayağa kaldırma:** [`vault/README.md`](vault/README.md) — compose ile
  çalıştırma, init/unseal, PKI + KV kurulumu, JUMBO için read-only token ve prod sıkılaştırma.
- **JUMBO'ya bağlama:** Ayarlar → Sistem → **Vault** sekmesi (adres + token + PKI mount);
  `app/services/providers/VaultProvider` `health()`/`fetch()` ile okur.

Sonraki faz (yol haritası): `auto_renew=True` sertifikalar için Vault↔otomasyon tetikli
zamanlanmış yenileme; velayet yine JUMBO'ya girmez.

## Testler

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

Test zinciri (`tests/fixtures/`) openssl ile üretilmiş gerçek root→intermediate→leaf
sertifikalarıdır; import, hiyerarşi kurma, rol yaptırımı, ayar maskeleme ve audit test edilir.
