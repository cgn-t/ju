# JUMBO — Teknik Doküman

Bu doküman geliştirici/operasyon içindir: kod nerede, hangi dosya neyi yönetir, bir sorun
olduğunda ilk nereye bakılmalı. Kurulum adımları için [`README.md`](../README.md), son
kullanıcı akışları için [`docs/KULLANICI-KILAVUZU.md`](KULLANICI-KILAVUZU.md).

## 1. Genel Mimari

```
                          ┌────────────────────────────┐
Dış istek ─▶ nginx :8080 ─┤ /api/*  ─▶ uvicorn :5000    │  (tek Docker container,
             (ÖN KAPI)    │ /*      ─▶ nginx :9080 SPA  │   supervisord ile yönetilir)
                          └────────────────────────────┘
                                     │
                                MSSQL (prod, container dışı — pymssql)
                                SQLite (dev/test — DATABASE_URL)
```

- **Backend**: FastAPI + SQLAlchemy, `backend/app/`. Tek process, APScheduler ile arka plan
  işleri aynı process içinde (ayrı worker yok).
- **Frontend**: React 18 + TypeScript + Vite + MUI, `frontend/src/`. TanStack Query ile
  server-state; `axios baseURL:'/api'` (relatif — CORS yok).
- **Dağıtım**: tek Docker imajı, `Dockerfile` (repo kökü) — çok aşamalı build (node build →
  python+nginx runtime). Ayrıntı: [`deploy/README.md`](../deploy/README.md).
- **Şema yönetimi**: migrasyon aracı (Alembic vb.) YOK. `ensure_new_columns()` /
  `ensure_indexes()` (`backend/app/main.py`) her açılışta idempotent `ALTER TABLE` ile eksik
  kolon/indexi tamamlar. Bkz. §8.

## 2. Backend kod haritası

`backend/app/` altında paketler:

| Klasör | İçerik |
|---|---|
| `api/` | REST uç noktaları — her dosya bir kaynak grubu, FastAPI router |
| `core/` | config, JWT/rol güvenliği, sertifika tipi yardımcıları, zaman yardımcıları, logging |
| `db/` | SQLAlchemy modelleri (`models.py`) + session |
| `services/` | iş mantığı — API katmanının çağırdığı gerçek işler |
| `services/providers/` | CA/Vault soyutlaması |
| `services/notify/` | entegrasyon kanalları (Slack/Teams/Webhook/ServiceNow/Jira/Zoom/Jabber) |
| `scripts/` | tek seferlik/manuel betikler (ör. `migrate_from_legacy.py`) |

### 2.1 `api/*.py` — bir sorun raporlandığında hangi uca bakılır

| Dosya | Kapsadığı uçlar / sayfa | Sorun türü örneği |
|---|---|---|
| `auth.py` | login, token yenileme | "Giriş yapamıyorum", 401/403 |
| `certificates.py` | SSL Sertifikaları sayfası — import (PEM/DER/PFX), CRUD, hiyerarşi, supersede | İçe aktarma hatası, yanlış zincir, pasife alma |
| `domains.py` | Domainler sayfası — CRUD, sertifika bağlama, canlı doğrulama tetikleme | Domain kaydedilmiyor, canlı doğrulama yanlış sonuç |
| `dashboard.py` | Anasayfa özet sayıları | Dashboard'daki sayılar tutmuyor |
| `applications.py` | Uygulamalar sayfası — envanter, bağımlılık, trust store, etiketler | Uygulama/bağımlılık CRUD sorunları |
| `proposals.py` | Devir Önerileri — onay/red/iptal (CAS deseni) | Onay butonu çalışmıyor, öneri kaybolmuyor |
| `discovery.py` | Keşif — tarama hedefleri, sonuçlar, adopt/yok say | Tarama sonuç vermiyor, adopt hata veriyor |
| `policy.py` | Uyum politikası kuralları ve değerlendirme sonucu | Bir sertifika yanlış "uyumsuz" görünüyor |
| `deployments.py` | Dağıtım (Jenkins) akış editörü + çalıştırmalar | Job tetiklenmiyor, adım durumu güncellenmiyor |
| `jenkins.py` | Jenkins bağlantı testi/job listeleme | Jenkins'e bağlanamıyor |
| `notifications.py` | Bildirim tetikleme uçları (`/expiry-run`, `/expired-run`) + Mail Gönderim Geçmişi (`/history`, `/history/{source}/{id}`) | Dış tetikleme 401/429 veriyor, mail geçmişi eksik/yanlış görünüyor |
| `settings_api.py` | Ayarlar kategorilerinin oku/yaz uç noktası (LDAP/SMTP/Vault/erişim/…) | Bir ayar kaydolmuyor |
| `users.py` | Kullanıcı, Ekip (Team), Ekip Üyeliği CRUD + RBAC | Rol/yetki hataları, "bu sayfayı göremiyorum" |
| `tags.py` | Uygulama etiket kataloğu | Etiket oluşturulamıyor |
| `schemas.py` | TÜM Pydantic request/response modelleri (kod değil, ama her uç burada tip arar) | 422 validation hatası ayıklarken buraya bak |

### 2.2 `services/*.py` — iş mantığının gerçek yeri

| Dosya | Sorumluluk | "Buraya bak" ne zaman |
|---|---|---|
| `cert_parser.py` | PEM/DER/PFX ayrıştırma, alan çıkarma, SKI/AKI zincir kurma, fingerprint | İçe aktarılan sertifikanın alanları yanlış/eksik |
| `renewal.py` | Yenileme (rotation) algılama — aynı SKI/CN+issuer eşleşmesi, `TransferProposal` üretimi, `apply_proposal`, `find_predecessors` | Devir önerisi hiç oluşmuyor / yanlış eski sertifikayı öneriyor |
| `live_check.py` | Canlı doğrulama (drift detection) — domain:port'a bağlanıp sunulan sertifikayı fingerprint ile karşılaştırma | "Şimdi Doğrula" yanlış sonuç veriyor, mismatch algılanmıyor |
| `discovery.py` | Ağ taraması — hedef port aralığı tarama, `DiscoveredCertificate` üretimi, adopt | Keşif taraması hiç sonuç bulmuyor/timeout |
| `ct_monitor.py` | Certificate Transparency (crt.sh) log izleme | CT'den beklenen sertifika gelmiyor |
| `revocation.py` | OCSP/CRL iptal durumu denetimi (yalnızca OKUMA — CA'ya iptal isteği GÖNDERMEZ) | İptal durumu "bilinmiyor"/yanlış görünüyor |
| `policy.py` | Uyum politikası kural değerlendirmesi | Bir kural beklenmedik şekilde tetiklenmiyor/tetikleniyor |
| `deployment_engine.py` | Jenkins DAG akışının çalıştırılması — adım sırası, retry, çift-tetik koruması | Dağıtım akışı yanlış adımda takılıyor, retry çalışmıyor |
| `jenkins_client.py` | Jenkins REST API istemcisi (job tetikleme, konsol log, durum) | Jenkins'ten dönen veri hatalı/timeout |
| `notifier.py` | **Tüm mail/bildirim motoru** — bkz. §5, en büyük ve en kritik dosya (1150+ satır) | Herhangi bir mail sorunu BURADAN başlar |
| `audit.py` | Audit log yazma yardımcıları | Bir mutasyon audit log'a düşmüyor |
| `ldap_auth.py` | LDAP/AD bind + grup→rol eşleme | LDAP girişi başarısız, rol yanlış atanıyor |
| `settings_service.py` | Ayar kategorilerinin oku/yaz + Fernet şifreleme (`_fernet()`) | Bir ayar kaydedilince şifre/token bozuluyor |
| `providers/vault.py` | Vault PKI okuma (`health()`/`fetch()`), CA zinciri | Vault bağlantı testi başarısız |
| `notify/*.py` | Slack/Teams/Webhook/ServiceNow/Jira/Zoom/Jabber entegrasyon gönderimleri | Bir entegrasyon kanalına mesaj gitmiyor |

### 2.3 `core/*.py`

- `config.py` — ortam değişkenlerinden ayar okuma (`DATABASE_URL`, `effective_database_url`,
  `JWT_SECRET`, `FERNET_KEY`, ...). **SEC-4**: MSSQL'e karşı çalışırken `JWT_SECRET` zorunlu,
  boşsa/varsayılansa uygulama açılmaz.
- `security.py` — JWT üretme/doğrulama, `ROLE_LEVELS` (viewer=0, editor=1, admin=2,
  allviewer=0 ama "her şeyi görür"), `PAGE_SETTING_KEY` (hangi sayfa hangi Ayarlar>Erişim
  switch'ine bağlı), `page_visible()`, `require_page_access()`, `require_team_or_admin()`.
  **RBAC ile ilgili HER ŞEY burada başlar.**
- `certtype.py` — sertifika türü (Root/Intermediate/Leaf) belirleme mantığı.
- `timeutil.py` — zaman dilimi/`utcnow` yardımcıları.
- `logging_config.py` — log formatı/seviyesi.

## 3. Veritabanı modelleri (`backend/app/db/models.py`)

Tam liste (678 satır, tek dosya — yeni bir tablo eklerken önce burada ara):

`Team`, `Certificate`, `Domain`, `CertificateDomainMap`, `Application`, `AppDependency`,
`ApplicationTrustedCert`, `Tag`, `ApplicationTag`, `User`, `AuditLog`, `AppSetting`,
`Notification`, `MailQueue`, `UserTeam`, `TransferProposal`, `ScanTarget`,
`DiscoveredCertificate`, `ScanRun`, `DeploymentFlow`, `DeploymentRun`, `DeploymentRunStep`.

Önemli noktalar:
- **`certificate_id`/`domain_id` FK'siz kolonlar** (`MailQueue`, `Notification`) bilinçli —
  MSSQL "multiple cascade paths" hatasından kaçınmak için. Yeni bir FK eklerken önce
  `backend/DEV-MSSQL.md`'deki "MSSQL uyum notları" bölümüne bak.
- **`Notification.mail_queue_id`** — bir bildirim kaydını, kuyruğa girdiyse gerçek teslim
  kaydına (`MailQueue`) bağlar; admin ekranındaki gerçek durum/zaman çizelgesi buradan gelir.
- **`TransferProposal`** — yenileme (rotation) ve trust-store ekleme önerilerinin ortak
  tablosu; `kind` alanı (`transfer` | `trusted_add`) ayrımı yapar.
- **Self-referencing FK'lerde `ondelete` YOK** (`Certificate.parent_id`,
  `Certificate.superseded_by_id`) — MSSQL cycle/çoklu-yol reddi yüzünden; boşaltma ilgili
  `delete_*` fonksiyonlarında elle yapılır.

## 4. Zamanlanmış işler (APScheduler, `backend/app/services/notifier.py`)

Tüm arka plan cron/interval işleri **tek dosyada** kayıtlıdır (`scheduler.add_job(...)`,
dosya sonu): bir zamanlanmış işin çalışıp çalışmadığını kontrol ederken direkt buraya bak.

| İş | Sıklık | Ne yapar |
|---|---|---|
| `check_expiring_certificates` | Günlük 08:00 | Süresi yaklaşan sertifikalar için mail |
| `check_pending_proposals` | Günlük (ayarlanabilir saat) | Bekleyen devir önerileri için hatırlatma maili |
| `check_all_domains` | Günlük 07:00 | Canlı doğrulama (drift detection) taraması |
| `run_scan_job` | Günlük (ayarlanabilir saat) | Ağ keşif taraması |
| `run_ct_scan_job` | Günlük (ayarlanabilir saat, varsayılan 4) | Certificate Transparency log taraması |
| `check_all_certificates` | Günlük (ayarlanabilir saat, varsayılan 5) | OCSP/CRL iptal durumu denetimi |
| `run_mail_queue_drain` | Dakikada bir (ayarlanabilir) | Kuyruktaki bekleyen mailleri gerçekten gönderir |
| `poll_running_runs` | 12 saniyede bir | Çalışan Jenkins dağıtımlarının durumunu günceller |

Bu işlerden biri "çalışmıyor" gibi görünüyorsa önce ilgili Ayarlar sekmesindeki
enabled/kill-switch'e, sonra uygulama loglarına (`docker logs jumbo`, `[program:api]` kısmı)
bak.

## 5. Mail / Bildirim Sistemi (`notifier.py`) — en sık dokunulan alan

Akış: **karar (kim, neden, ne zaman)** → **gönderim/kuyruğa alma** → **kalıcı kayıt**.

- `_expiry_stakeholders(db, cert, global_days)` — bir sertifikanın paydaşlarını çözer:
  1) oluşturan ekip/kullanıcı, 2) bağlı domainlerin SY ekibi, 3) client olarak bağlı
  uygulamaların SY ekibi. Her paydaş AYRI mail alır.
- `_domain_expiry_stakeholder(domain, global_days)` — sertifikasız, yalnız **manuel Bitiş
  Tarihi** girilmiş domainler için TEK paydaş (domain SY ekibi) çözer. Aktif bir SERVER
  sertifikası bağlıysa bu yol devre dışıdır (o zaman zaten `_expiry_stakeholders` üzerinden
  gider).
- `_dispatch_cert_mails(...)` / `_dispatch_domain_mails(...)` — paylaşılan gönderim/dedup
  motoru: aynı paydaşa kısa sürede tekrar göndermeyi engeller (`resend_interval_*`), SMTP
  kapalıysa/kuyruk açıksa `MailQueue`'ya yazar.
- `_deliver(db, cfg, to_addr, subject, body, html_body, ...)` — gerçek gönderim/kuyruğa
  alma çekirdeği. Dönüş: `(mail_sent: bool, not: str, mail_queue_id: int | None)`. Queue
  açıksa `MailQueue` satırı yazıp `mail_queue_id` döner; `Notification` bu id'yi saklar.
- `drain_mail_queue()` — kuyruktaki `pending` satırları gerçekten gönderen arka plan işi;
  başarısızlıkta `attempts`/`last_error` günceller, `failed` yazar.
- Mail HTML şablonları: `_banner()`, `_section()`, `_kv_table()`, `_mail_html_wrap()` — 4 mail
  türü (süresi yaklaşan/geçen sertifika, domain hatırlatma, devir onayı) bu ortak
  bileşenleri paylaşır. Body'yi değiştirirken bu yardımcıları kullan, HTML'i elle yazma.
- **Semptom → dosya haritası**:
  - "Mail hiç gitmiyor" → önce Ayarlar>SMTP `enabled`+host, sonra `send_expiry_notifications`/
    `send_expired_notifications` giriş noktaları.
  - "Mail kuyrukta bekliyor, gönderilmiyor" → `run_mail_queue_drain` çalışıyor mu (log), Ayarlar>
    SMTP "Gönderim Kuyruğu Etkin" ve "Boşaltma Aralığı".
  - "Admin ekranında 'Gönderildi' görünüyor ama alıcı almadı" → `MailQueue.status`/`last_error`'a
    bak (Ayarlar > Mail Gönderim Geçmişi'nde satıra tıkla → detay paneli gerçek durumu gösterir).
  - "Yanlış/eksik alıcıya gitti" → `_expiry_stakeholders`/`_domain_expiry_stakeholder`.
  - "Devir onayı hatırlatması gelmiyor" → `check_pending_proposals` + `send_pending_proposal_notifications`.

## 6. RBAC / Yetkilendirme Modeli

- Roller: `admin` (2), `editor` (1), `viewer` (0), `allviewer` (0 ama "her şeyi görür,
  düzenleyemez"). Tanım: `core/security.py:ROLE_LEVELS`/`VALID_ROLES`.
- **Takım üyeliği veri kapsamını belirler** — bir kullanıcının hangi domain/sertifikaları
  gördüğü, `UserTeam` üyeliklerinden türer (bkz. memory: RBAC takım modeli).
  `user_team_ids()`/`domain_scope_team_ids()` kapsam sorgularının başlangıç noktasıdır.
- **Sayfa görünürlüğü** (Uyum/Devir Önerisi/Keşif/Dağıtım): `PAGE_SETTING_KEY` → Ayarlar>Erişim
  switch'i. admin+allviewer HER ZAMAN görür; Devir Önerisi'nde ayrıca SY üyeliği olan herkes
  kendi ekibinin tekliflerini görür — bu görünürlük kuralı, ONAY yetkisinden (`require_team_or_admin`)
  BAĞIMSIZDIR.
- "Bu kullanıcı bir sayfayı/butonu göremiyor" şikayetinde bakılacak sıra: 1) rolü, 2) takım
  üyeliği (Ayarlar>Ekip Üyelikleri), 3) ilgiliyse Ayarlar>Erişim switch'i.

## 7. Frontend kod haritası (`frontend/src/`)

| Yer | İçerik |
|---|---|
| `pages/*.tsx` | Bir route = bir sayfa dosyası (bkz. `App.tsx` route tablosu) |
| `components/` | Sayfalar arası paylaşılan bileşenler (detay drawer'ları, dialoglar, tablolar) |
| `api/client.ts` | axios instance, `baseURL:'/api'`, interceptor (401 → login'e yönlendirme) |
| `api/types.ts` | Backend `schemas.py` ile eşleşen TS tipleri — 422/tip uyuşmazlığında ilk bakılacak yer |
| `theme.ts` | Renk/etiket haritaları (`daysLeftColor`, durum renkleri, ortak fontlar) |
| `hooks/` | `usePageAccess`, `usePendingIssuanceCount` benzeri paylaşılan React Query hook'ları |
| `App.tsx` | Route tanımları + `PageAccessRoute` (sayfa görünürlük kapısı) |
| `AppLayout.tsx` | Navigasyon menüsü, üst bar |

Route haritası (`App.tsx`): `/` (Dashboard), `/certificates`, `/domains`, `/proposals`
(erişim kapılı), `/cert-map`, `/applications`, `/policy` (erişim kapılı), `/discovery`
(erişim kapılı), `/deployments` + `/deployments/runs[/:runId]` (erişim kapılı), `/settings`.

`Settings.tsx` (2144 satır, tek dosya) — her biri kendi alt-bileşeni olan sekmeler:
Kullanıcılar, Ekipler, Ekip Üyelikleri, Erişim, LDAP, SMTP, Mail Gönderim Geçmişi, Slack,
MS Teams, Webhook, ServiceNow, Jira, Zoom, Jabber, Keşif, CT, Uyum, İptal (OCSP/CRL),
Etiketler, Vault, Jenkins, Audit Log. Bir ayar ekranı sorununda önce ilgili `<X>Tab()`
fonksiyonuna, sonra `settings_api.py`/`settings_service.py`'ye bak.

Bir UI hatası ayıklarken sıra: 1) ilgili `pages/*.tsx` bileşeni, 2) `api/types.ts` (tip
uyumu), 3) backend `api/*.py` + `schemas.py`.

## 8. Şema/DB değişikliği dosyaları (repo kökü)

| Dosya | Amaç |
|---|---|
| `schema-OLD.sql` | Baseline DDL (bir önceki birleştirme noktası) |
| `schema-NEW.sql` | Baseline'dan SONRAKİ değişikliklerin tarihli, append-only günlüğü |
| `schema-bugfix.sql` | DBA'ya acil, tek seferlik, idempotent düzeltme betiği (tüm additive kolonlar) |
| `schema-<Tarih>.sql` | O günün DB değişikliğini içeren, DBA'ya AYRICA verilecek dar kapsamlı betik (`schema-NEW.sql`'deki ilgili bloğun kopyası) |

Kod tarafında gerçek uygulanan mekanizma `backend/app/main.py:ensure_new_columns()` —
buradaki `additions` sözlüğü prod'da eksik olabilecek kolonları process açılışında ekler.
**Yeni bir kolon eklerken 3 yer birden güncellenir**: `models.py` (SQLAlchemy tanımı),
`main.py:ensure_new_columns()` (idempotent ALTER), `schema-NEW.sql` (dokümantasyon/DBA günlüğü).

## 9. Sık Karşılaşılan Sorunlar — Nereye Bakılır

| Semptom | İlk bakılacak yer |
|---|---|
| Uygulamaya giriş yapılamıyor (genel) | `docker ps` (container ayakta mı) → `docker logs jumbo` → `curl` ile `/api/auth/login-json` |
| Giriş yapılamıyor (AD/LDAP kullanıcısı) | `services/ldap_auth.py`, Ayarlar>LDAP bağlantı testi |
| 403 "yetkisiz" hatası | `core/security.py` rol/sayfa kontrolleri, kullanıcının rolü+takım üyeliği |
| Sertifika içe aktarma hata veriyor | `services/cert_parser.py`, `api/certificates.py` import ucu |
| Devir önerisi oluşmuyor/yanlış | `services/renewal.py` (`find_predecessors`/`propose`) |
| Canlı doğrulama (drift) yanlış sonuç | `services/live_check.py` |
| Mail gitmiyor / yanlış alıcıya gidiyor | §5 — `services/notifier.py` |
| Mail geçmişinde durum yanlış görünüyor | `Notification.mail_queue_id`, `api/notifications.py:list_mail_history` |
| Jenkins dağıtımı takılıyor/tekrar tetikleniyor | `services/deployment_engine.py`, `services/jenkins_client.py` |
| Keşif taraması sonuç bulmuyor | `services/discovery.py`, `api/discovery.py`, Ayarlar>Keşif hedefleri |
| MSSQL "multiple cascade paths" hatası | `backend/DEV-MSSQL.md` "MSSQL uyum notları"; yeni FK eklerken `ondelete` kullanma |
| DB'de kolon eksik hatası (prod) | `main.py:ensure_new_columns()`'a kolon eklenmemiş olabilir — §8 |
| Bir ayar kaydedilmiyor/şifreleniyor bozuk | `services/settings_service.py` (`_fernet()`), `FERNET_KEY` ortam değişkeni |
| Container çöküyor/yeniden başlamıyor | `docker logs jumbo` (`[program:api]`/`[program:web]` etiketli satırlar), `run.sh` |

## 10. Testler

```bash
cd backend && ./.venv/bin/python -m pytest tests/ -q
```

31 test dosyası, 265 test (pytest **SQLite** kullanır, `conftest.py` `DATABASE_URL`'i
override eder — MSSQL gerekmez). Mail sistemiyle ilgili değişiklik yaparken en az şu
dosyaları çalıştır: `test_mail_scenarios.py`, `test_domain_mail_scenarios.py`,
`test_mail_history.py`, `test_mail_template_consistency.py`, `test_mail_characterization.py`,
`test_mail_features.py`.

> Bilinen kırılganlık: `test_mail_characterization.py::test_scn_partial_failure_retries_only_failed_stakeholder`
> ve `test_domain_mail_scenarios.py::test_dom_dedup_resend_window` bazı test-sırası
> kombinasyonlarında flaky olabiliyor (izole çalıştırıldığında her zaman geçer) — bilinen,
> önceden var olan bir durum, regresyon değil.
