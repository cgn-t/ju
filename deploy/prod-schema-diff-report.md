# JUMBO — Prod Şema Tutarlılık Raporu (READ-ONLY)

- Hedef : `mssql+pyodbc://sa:***@localhost:1433/TMTKS_REPLICA?TrustServerCertificate=yes&driver=ODBC+Driver+18+for+SQL+Server`
- Dialect: `mssql`
- ⚠️ Bu araç HİÇBİR ŞEY YAZMAZ; yalnız şema kataloğunu okur.
- ℹ️ Bu rapor YALNIZ yukarıdaki hedef içindir. Otorite = canlıya karşı koşmak (`MSSQL_DB=TMTKS00 …`).

## Özet
- Beklenen prod tablosu: **6/6** mevcut
- App-yeni tablo: **0/6** mevcut (eksikler `create_all` ile kurulur)
- ➕ Additive kolon (app açılışta ekler): **25**
- Uyuşmazlık toplam **74**:
    - 🔴 Kritik (eksik prod kolonu/tablosu, tip ailesi): **0** — ad uyuşmazlığı, MUTLAKA düzelt
    - 🟡 Davranışsal (nullability/UNIQUE): **15** — app prod kısıtına UYMALI (SerialNumber, email…)
    - 🟢 Sadakat/bilgi (unicode·uzunluk): **59** — prod'da kolon ZATEN öyle; app yazarken sorun olmaz, yalnız greenfield/tip-sadakati için
- Sonuç: 🔴 kritik YOK ✅; tip/kısıt deltaları Pragmatik/Tam kararına bırakıldı

## AuditLog  _(beklenen prod tablosu)_
  ✅ `ID`  (INTEGER, NOT NULL)
  🟢 `Username`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `Action`  ORM `VARCHAR(20)` ↔ DB `NVARCHAR(20)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `TableName`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `RecordID`  ORM `VARCHAR(50)` ↔ DB `NVARCHAR(50)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NULL↔DB=NOT NULL
  🟢 `Details`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  ✅ `CreatedAt`  (DATETIME, NOT NULL)
  ➕ `ip_address` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).

## SSLCertificates  _(beklenen prod tablosu)_
  ✅ `ID`  (INTEGER, NOT NULL)
  🟢 `NAME`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `SerialNumber`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NULL↔DB=NOT NULL
  🟡 `Issuer`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(500)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NULL↔DB=NOT NULL
  🟡 `Subject`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(500)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NULL↔DB=NOT NULL
  🟢 `SubjectKeyIdentifier`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `AuthorityKeyIdentifier`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `CertType`  ORM `VARCHAR(50)` ↔ DB `NVARCHAR(50)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NOT NULL↔DB=NULL
  🟡 `ValidFrom`  ORM `DATETIME` ↔ DB `DATETIME2`  → null ORM=NULL↔DB=NOT NULL
  🟡 `ValidTo`  ORM `DATETIME` ↔ DB `DATETIME2`  → null ORM=NULL↔DB=NOT NULL
  🟢 `PEMCertificate`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `ExtendedKeyUsage`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  ✅ `IsActive`  (BIT, NOT NULL)
  🟢 `SatinAlimYapan`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `aaakkkCertificateCreator`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `Notes`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `CreatedDate`  ORM `DATETIME` ↔ DB `DATETIME2`  → null ORM=NOT NULL↔DB=NULL
  🟡 `ModifiedDate`  ORM `DATETIME` ↔ DB `DATETIME2`  → null ORM=NOT NULL↔DB=NULL
  ➕ `san` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `fingerprint_sha256` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `parent_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `superseded_by_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `is_internal` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `source` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `vault_path` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `auto_renew` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ℹ️ prod-only (app yok sayar): `DBID`, `ParentKey`, `GrandParentKey`, `Internal`
  🔎 `%CertificateCreator%` kolon(lar)ı: `aaakkkCertificateCreator`
  🔎 `SerialNumber`: NOT NULL=True, UNIQUE=True
  🔎 `Issuer`: NOT NULL=True
  🔎 `Subject`: NOT NULL=True

## app_settings  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## teams  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## users  _(beklenen prod tablosu)_
  ✅ `id`  (INTEGER, NOT NULL)
  🟢 `username`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(50)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 100≠50
  🟡 `password`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NULL↔DB=NOT NULL
  🟡 `email`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100, null ORM=NULL↔DB=NOT NULL
  🟡 `created_at`  ORM `DATETIME` ↔ DB `DATETIME`  → null ORM=NOT NULL↔DB=NULL
  ➕ `full_name` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `role` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `auth_source` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `is_active` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `last_login` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  🔎 `email`: NOT NULL=True, UNIQUE(username)=False

## domain_certificates  _(beklenen prod tablosu)_
  ✅ `id`  (INTEGER, NOT NULL)
  🟡 `domain`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR), null ORM=NOT NULL↔DB=NULL
  🟢 `external_address`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `cert_owner`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `lb_update`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `env_update`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `waf_update`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(10)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠10
  🟢 `external_company`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  ✅ `expire_date`  (DATETIME, NULL)
  🟢 `info`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `mail_addresses`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `Aksiyon_Alma`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(10)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠10
  🟢 `SSLPinning`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(10)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠10
  🟢 `Keystore`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(500)`  → unicode (VARCHAR↔NVARCHAR)
  ➕ `ug_team_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `sy_team_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `servers_to_update` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `live_check_status` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `live_check_detail` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `live_check_at` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `created_at` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `updated_at` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ℹ️ prod-only (app yok sayar): `ug`, `sy`

## notifications  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## user_teams  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## SSLCertificateDomainMapping  _(beklenen prod tablosu)_
  ✅ `ID`  (INTEGER, NOT NULL)
  ✅ `CertID`  (INTEGER, NOT NULL)
  ✅ `DomainID`  (INTEGER, NOT NULL)
  ✅ `MappingType`  (VARCHAR(10), NOT NULL)

## applications  _(beklenen prod tablosu)_
  ✅ `id`  (INTEGER, NOT NULL)
  🟢 `app_name`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100
  🟢 `app_user`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100
  🟢 `conf_path`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 500≠255
  🟢 `control_method`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100
  🟢 `dns`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100
  🟢 `info`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `ip_address`  ORM `VARCHAR(100)` ↔ DB `NVARCHAR(50)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 100≠50, null ORM=NULL↔DB=NOT NULL
  🟢 `log_path`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 500≠255
  🟢 `notes`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `required_commands`  ORM `VARCHAR(max)` ↔ DB `NVARCHAR`  → unicode (VARCHAR↔NVARCHAR)
  🟡 `server_name`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 255≠100, null ORM=NULL↔DB=NOT NULL
  🟢 `service_provider_contact`  ORM `VARCHAR(255)` ↔ DB `NVARCHAR(255)`  → unicode (VARCHAR↔NVARCHAR)
  🟢 `start_stop_method`  ORM `VARCHAR(500)` ↔ DB `NVARCHAR(100)`  → unicode (VARCHAR↔NVARCHAR), uzunluk 500≠100
  ✅ `status`  (BIT, NOT NULL)
  ➕ `domain_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `sy_team_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ➕ `ug_team_id` — app-yeni; prod'da yok, açılışta eklenecek (NORMAL).
  ℹ️ prod-only (app yok sayar): `domain`, `sy_team`, `ug_team`

## app_dependencies  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## transfer_proposals  _(app-yeni tablo)_
- ➕ DB'de yok → `create_all` kuracak (NORMAL, app-yeni tablo).

## ℹ️ DB'de olup ORM'de olmayan tablolar
- `group`, `session_cache`  (app yok sayar; prod'da kalır — ör. `[group]`, `session_cache`).

