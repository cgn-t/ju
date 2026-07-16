/* ============================================================================
   JUMBO — CANLI (mevcut TMTKS00 şeması) ÜZERİNE ADDITIVE DEĞİŞİKLİKLER
   ----------------------------------------------------------------------------
   Yeni JUMBO uygulamasının mevcut prod veritabanı üzerinde çalışması için gereken
   TÜM EKLEMELER. Yalnızca EKLEME yapılır (yeni kolon / yeni tablo / yeni index):
   mevcut tablo, kolon, kısıt ve VERİ AYNEN KORUNUR — hiçbir şey silinmez/yeniden
   adlandırılmaz. Eski uygulama çalışmaya devam edebilir.

   NOT: Uygulama açılışta bu değişiklikleri (ensure_new_columns + create_all +
   backfill) OTOMATİK de yapar. Bu script, DBA onaylı / manuel uygulama içindir.
   İdempotenttir: her ekleme "yoksa ekle" ile sarılıdır, tekrar çalıştırılabilir.

   Şema adı 'dbo' varsayıldı; farklıysa uyarlayın.
   ============================================================================ */

/* ---------------------------------------------------------------------------
   1) SSLCertificates — app-yeni kolonlar (fingerprint kimliği, zincir, vb.)
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.SSLCertificates','san')                IS NULL ALTER TABLE dbo.SSLCertificates ADD san NVARCHAR(MAX) NULL;
IF COL_LENGTH('dbo.SSLCertificates','fingerprint_sha256') IS NULL ALTER TABLE dbo.SSLCertificates ADD fingerprint_sha256 NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.SSLCertificates','parent_id')          IS NULL ALTER TABLE dbo.SSLCertificates ADD parent_id INT NULL;
IF COL_LENGTH('dbo.SSLCertificates','superseded_by_id')   IS NULL ALTER TABLE dbo.SSLCertificates ADD superseded_by_id INT NULL;
IF COL_LENGTH('dbo.SSLCertificates','is_internal')        IS NULL ALTER TABLE dbo.SSLCertificates ADD is_internal BIT NULL;
IF COL_LENGTH('dbo.SSLCertificates','source')             IS NULL ALTER TABLE dbo.SSLCertificates ADD source NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.SSLCertificates','vault_path')         IS NULL ALTER TABLE dbo.SSLCertificates ADD vault_path NVARCHAR(255) NULL;
IF COL_LENGTH('dbo.SSLCertificates','auto_renew')         IS NULL ALTER TABLE dbo.SSLCertificates ADD auto_renew BIT NULL;
-- Kripto özellikleri (politika/uyum motoru + PQC envanteri) — PEM'den backfill edilir.
IF COL_LENGTH('dbo.SSLCertificates','key_size')           IS NULL ALTER TABLE dbo.SSLCertificates ADD key_size INT NULL;
IF COL_LENGTH('dbo.SSLCertificates','public_key_type')    IS NULL ALTER TABLE dbo.SSLCertificates ADD public_key_type NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.SSLCertificates','key_curve')          IS NULL ALTER TABLE dbo.SSLCertificates ADD key_curve NVARCHAR(50) NULL;
IF COL_LENGTH('dbo.SSLCertificates','signature_hash')     IS NULL ALTER TABLE dbo.SSLCertificates ADD signature_hash NVARCHAR(50) NULL;
-- İptal (revocation) durumu — OCSP/CRL denetimi (null = denetlenmemiş; backfill yok).
IF COL_LENGTH('dbo.SSLCertificates','revocation_status')     IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_status NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.SSLCertificates','revocation_checked_at') IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_checked_at DATETIME2 NULL;
IF COL_LENGTH('dbo.SSLCertificates','revocation_detail')     IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_detail NVARCHAR(MAX) NULL;
GO

/* ---------------------------------------------------------------------------
   2) domain_certificates — sahiplik FK'leri + drift alanları
   (mevcut sy/ug SERBEST METİN kolonları KORUNUR; app yeni FK'leri kullanır)
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.domain_certificates','sy_team_id')        IS NULL ALTER TABLE dbo.domain_certificates ADD sy_team_id INT NULL;
IF COL_LENGTH('dbo.domain_certificates','ug_team_id')        IS NULL ALTER TABLE dbo.domain_certificates ADD ug_team_id INT NULL;
IF COL_LENGTH('dbo.domain_certificates','ug_team_name')      IS NULL ALTER TABLE dbo.domain_certificates ADD ug_team_name NVARCHAR(255) NULL;
IF COL_LENGTH('dbo.domain_certificates','servers_to_update') IS NULL ALTER TABLE dbo.domain_certificates ADD servers_to_update NVARCHAR(500) NULL;
IF COL_LENGTH('dbo.domain_certificates','live_check_status') IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_status NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.domain_certificates','live_check_detail') IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_detail NVARCHAR(MAX) NULL;
IF COL_LENGTH('dbo.domain_certificates','live_check_at')     IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_at DATETIME2 NULL;
IF COL_LENGTH('dbo.domain_certificates','created_at')        IS NULL ALTER TABLE dbo.domain_certificates ADD created_at DATETIME2 NULL;
IF COL_LENGTH('dbo.domain_certificates','updated_at')        IS NULL ALTER TABLE dbo.domain_certificates ADD updated_at DATETIME2 NULL;
GO

/* ---------------------------------------------------------------------------
   3) applications — FK sahiplik/domain (mevcut domain/sy_team/ug_team metni KORUNUR)
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.applications','domain_id')  IS NULL ALTER TABLE dbo.applications ADD domain_id INT NULL;
IF COL_LENGTH('dbo.applications','sy_team_id') IS NULL ALTER TABLE dbo.applications ADD sy_team_id INT NULL;
IF COL_LENGTH('dbo.applications','ug_team_id') IS NULL ALTER TABLE dbo.applications ADD ug_team_id INT NULL;
GO

/* ---------------------------------------------------------------------------
   4) users — rol/auth/aktiflik (mevcut username/password/email KORUNUR)
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.users','full_name')   IS NULL ALTER TABLE dbo.users ADD full_name NVARCHAR(255) NULL;
IF COL_LENGTH('dbo.users','role')        IS NULL ALTER TABLE dbo.users ADD role NVARCHAR(20) NULL;
IF COL_LENGTH('dbo.users','auth_source') IS NULL ALTER TABLE dbo.users ADD auth_source NVARCHAR(10) NULL;
IF COL_LENGTH('dbo.users','is_active')   IS NULL ALTER TABLE dbo.users ADD is_active BIT NULL;
IF COL_LENGTH('dbo.users','last_login')  IS NULL ALTER TABLE dbo.users ADD last_login DATETIME2 NULL;
GO

/* ---------------------------------------------------------------------------
   5) AuditLog — ip_address
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.AuditLog','ip_address') IS NULL ALTER TABLE dbo.AuditLog ADD ip_address NVARCHAR(50) NULL;
GO

/* ---------------------------------------------------------------------------
   6) YENİ TABLOLAR (prod'da yok). FK bağımlılık sırasıyla. [group]/session_cache
   tablolarına DOKUNULMAZ.
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.teams','U') IS NULL
CREATE TABLE dbo.teams (
    id INT NOT NULL IDENTITY(1,1),
    name NVARCHAR(255) NOT NULL,
    -- 'SY' | 'UG' | 'ADMIN' | 'VIEWER' (ADMIN/VIEWER singleton'ları app startup'ta seed edilir; RBAC).
    type NVARCHAR(10) NOT NULL,
    email NVARCHAR(255) NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_team_name_type UNIQUE (name, type)
);
GO
-- Mevcut (eski) teams tablosu NVARCHAR(2) ile kurulduysa ADMIN/VIEWER için genişlet (idempotent).
-- App açılışında ensure_team_type_width() aynısını yapar; DBA elle koşarsa da güvenli.
IF OBJECT_ID('dbo.teams','U') IS NOT NULL
   AND EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.teams')
               AND name='type' AND max_length < 20)  -- NVARCHAR: max_length = 2*karakter
BEGIN
    IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name='uq_team_name_type')
        ALTER TABLE dbo.teams DROP CONSTRAINT uq_team_name_type;
    ALTER TABLE dbo.teams ALTER COLUMN type NVARCHAR(10) NOT NULL;
    ALTER TABLE dbo.teams ADD CONSTRAINT uq_team_name_type UNIQUE (name, type);
END
GO

IF OBJECT_ID('dbo.app_settings','U') IS NULL
CREATE TABLE dbo.app_settings (
    [key] NVARCHAR(100) NOT NULL,
    category NVARCHAR(20) NOT NULL,
    value NVARCHAR(MAX) NULL,
    is_encrypted BIT NOT NULL,
    updated_at DATETIME2 NOT NULL,
    PRIMARY KEY ([key])
);
GO

IF OBJECT_ID('dbo.notifications','U') IS NULL
CREATE TABLE dbo.notifications (
    id INT NOT NULL IDENTITY(1,1),
    certificate_id INT NULL,
    recipient NVARCHAR(500) NULL,
    subject NVARCHAR(500) NULL,
    days_left INT NULL,
    sent_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(certificate_id) REFERENCES dbo.SSLCertificates([ID]) ON DELETE CASCADE
);
GO

IF OBJECT_ID('dbo.app_dependencies','U') IS NULL
CREATE TABLE dbo.app_dependencies (
    id INT NOT NULL IDENTITY(1,1),
    app_id INT NOT NULL,
    target_domain_id INT NOT NULL,
    client_cert_id INT NULL,
    note NVARCHAR(500) NULL,
    created_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_app_target UNIQUE (app_id, target_domain_id),
    FOREIGN KEY(app_id) REFERENCES dbo.applications(id) ON DELETE CASCADE,
    FOREIGN KEY(target_domain_id) REFERENCES dbo.domain_certificates(id) ON DELETE CASCADE,
    FOREIGN KEY(client_cert_id) REFERENCES dbo.SSLCertificates([ID]) ON DELETE SET NULL
);
GO

IF OBJECT_ID('dbo.user_teams','U') IS NULL
CREATE TABLE dbo.user_teams (
    id INT NOT NULL IDENTITY(1,1),
    user_id INT NOT NULL,
    team_id INT NOT NULL,
    created_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_user_team UNIQUE (user_id, team_id),
    FOREIGN KEY(user_id) REFERENCES dbo.users(id) ON DELETE CASCADE,
    FOREIGN KEY(team_id) REFERENCES dbo.teams(id) ON DELETE CASCADE
);
GO

/* transfer_proposals: SSLCertificates'a İKİ FK (old+new) — MSSQL çoklu-cascade-yolunu
   reddettiği için bu FK'lerde CASCADE YOK (temizlik uygulama seviyesinde). */
IF OBJECT_ID('dbo.transfer_proposals','U') IS NULL
CREATE TABLE dbo.transfer_proposals (
    id INT NOT NULL IDENTITY(1,1),
    old_cert_id INT NOT NULL,
    new_cert_id INT NOT NULL,
    domain_id INT NULL,
    mapping_type NVARCHAR(10) NULL,
    app_dependency_id INT NULL,
    sy_team_id INT NULL,
    status NVARCHAR(12) NOT NULL,
    signal NVARCHAR(20) NULL,
    via NVARCHAR(20) NULL,
    live_seen BIT NOT NULL,
    live_seen_at DATETIME2 NULL,
    created_by NVARCHAR(100) NULL,
    created_at DATETIME2 NOT NULL,
    decided_by NVARCHAR(100) NULL,
    decided_at DATETIME2 NULL,
    applied_at DATETIME2 NULL,
    note NVARCHAR(MAX) NULL,
    PRIMARY KEY (id),
    -- NOT: granül benzersizliği tam UNIQUE değil, yalnız AÇIK önerilere filtreli index (böl.7b) ile
    -- uygulanır — reddedilen bir granül yeniden önerilebilsin (aksi halde MSSQL IntegrityError).
    FOREIGN KEY(old_cert_id) REFERENCES dbo.SSLCertificates([ID]),
    FOREIGN KEY(new_cert_id) REFERENCES dbo.SSLCertificates([ID]),
    FOREIGN KEY(domain_id) REFERENCES dbo.domain_certificates(id),
    FOREIGN KEY(app_dependency_id) REFERENCES dbo.app_dependencies(id),
    FOREIGN KEY(sy_team_id) REFERENCES dbo.teams(id)
);
GO

/* 6b) AĞ KEŞFİ (discovery) tabloları — YENİ app tabloları (prod'da yok). discovered_certificates
   envanterdeki SSLCertificates'a FK İLE BAĞLANMAZ (eşleşme fingerprint ile okuma anında çözülür)
   → cascade/çoklu-yol derdi yok. scan_targets.sy_team_id yalnız etiket (cascade YOK). */
IF OBJECT_ID('dbo.scan_targets','U') IS NULL
CREATE TABLE dbo.scan_targets (
    id INT NOT NULL IDENTITY(1,1),
    name NVARCHAR(255) NOT NULL,
    kind NVARCHAR(20) NOT NULL,          -- cidr | host | inventory
    value NVARCHAR(255) NULL,            -- CIDR/host; inventory'de boş
    ports NVARCHAR(100) NULL,            -- virgüllü; boşsa varsayılan portlar
    enabled BIT NOT NULL,
    sy_team_id INT NULL,
    created_at DATETIME2 NOT NULL,
    updated_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(sy_team_id) REFERENCES dbo.teams(id)
);
GO

IF OBJECT_ID('dbo.discovered_certificates','U') IS NULL
CREATE TABLE dbo.discovered_certificates (
    id INT NOT NULL IDENTITY(1,1),
    host NVARCHAR(255) NOT NULL,
    port INT NOT NULL,
    fingerprint_sha256 NVARCHAR(100) NOT NULL,
    name NVARCHAR(255) NULL,
    issuer NVARCHAR(500) NULL,
    subject NVARCHAR(500) NULL,
    san NVARCHAR(MAX) NULL,
    serial_number NVARCHAR(100) NULL,
    valid_from DATETIME2 NULL,
    valid_to DATETIME2 NULL,
    pem_certificate NVARCHAR(MAX) NULL,  -- benimseme (adopt) için saklanır
    status NVARCHAR(20) NOT NULL,        -- new | in_inventory | adopted | ignored
    origin NVARCHAR(20) NOT NULL DEFAULT 'network',  -- network (aktif tarama) | ct (crt.sh)
    crtsh_id NVARCHAR(50) NULL,          -- CT bulgusunda crt.sh giriş kimliği (CT: host=domain, port=0)
    sy_team_id INT NULL,                 -- hedefin SY ekibi; benimsemede sertifikanın "Oluşturan"ı olur (FK YOK)
    first_seen_at DATETIME2 NOT NULL,
    last_seen_at DATETIME2 NOT NULL,
    note NVARCHAR(MAX) NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_discovered_endpoint UNIQUE (host, port, fingerprint_sha256)
);
GO

-- Tablo önceki sürümde sy_team_id'siz kurulduysa additive ekle (idempotent).
IF COL_LENGTH('dbo.discovered_certificates','sy_team_id') IS NULL
    ALTER TABLE dbo.discovered_certificates ADD sy_team_id INT NULL;
GO

-- CT (crt.sh) izleme: origin/crtsh_id additive (idempotent). Mevcut satırlar 'network'.
IF COL_LENGTH('dbo.discovered_certificates','origin') IS NULL
    ALTER TABLE dbo.discovered_certificates ADD origin NVARCHAR(20) NULL;
GO
UPDATE dbo.discovered_certificates SET origin='network' WHERE origin IS NULL;
GO
IF COL_LENGTH('dbo.discovered_certificates','crtsh_id') IS NULL
    ALTER TABLE dbo.discovered_certificates ADD crtsh_id NVARCHAR(50) NULL;
GO

IF OBJECT_ID('dbo.scan_runs','U') IS NULL
CREATE TABLE dbo.scan_runs (
    id INT NOT NULL IDENTITY(1,1),
    started_at DATETIME2 NOT NULL,
    finished_at DATETIME2 NULL,
    status NVARCHAR(12) NOT NULL,        -- running | done | error
    [trigger] NVARCHAR(20) NULL,         -- manual | schedule
    kind NVARCHAR(20) NOT NULL DEFAULT 'network',  -- network (ağ taraması) | ct (crt.sh)
    targets_scanned INT NOT NULL,
    hosts_reachable INT NOT NULL,
    new_findings INT NOT NULL,
    error NVARCHAR(MAX) NULL,
    created_by NVARCHAR(100) NULL,
    PRIMARY KEY (id)
);
GO

-- CT taramaları için tür ayrımı additive (idempotent). Mevcut satırlar 'network'.
IF COL_LENGTH('dbo.scan_runs','kind') IS NULL
    ALTER TABLE dbo.scan_runs ADD kind NVARCHAR(20) NULL;
GO
UPDATE dbo.scan_runs SET kind='network' WHERE kind IS NULL;
GO

/* ---------------------------------------------------------------------------
   7) Fingerprint kısmi UNIQUE index (sertifikanın tekil kimliği; NULL'lar hariç)
   --------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ux_sslcertificates_fingerprint')
    CREATE UNIQUE INDEX ux_sslcertificates_fingerprint
        ON dbo.SSLCertificates (fingerprint_sha256)
        WHERE fingerprint_sha256 IS NOT NULL;
GO

/* ---------------------------------------------------------------------------
   7b) FK DESTEK INDEX'LERİ. MSSQL FK kolonlarını otomatik indexlemez; ON DELETE CASCADE/SET NULL
   ve join'ler destek index'i olmadan tablo taraması + kilit tırmanışı yapar. Yalnız kapsanmayan
   FK kolonları (app_id=uq_app_target, user_id/team_id=uq_user_team zaten kapsıyor). Idempotent.
   --------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_sslcert_parent'         AND object_id=OBJECT_ID('dbo.SSLCertificates'))   CREATE INDEX ix_sslcert_parent         ON dbo.SSLCertificates(parent_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_sslcert_superseded'     AND object_id=OBJECT_ID('dbo.SSLCertificates'))   CREATE INDEX ix_sslcert_superseded     ON dbo.SSLCertificates(superseded_by_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_dc_sy_team'             AND object_id=OBJECT_ID('dbo.domain_certificates')) CREATE INDEX ix_dc_sy_team            ON dbo.domain_certificates(sy_team_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_dc_ug_team'             AND object_id=OBJECT_ID('dbo.domain_certificates')) CREATE INDEX ix_dc_ug_team            ON dbo.domain_certificates(ug_team_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_app_domain'             AND object_id=OBJECT_ID('dbo.applications'))       CREATE INDEX ix_app_domain             ON dbo.applications(domain_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_app_sy_team'            AND object_id=OBJECT_ID('dbo.applications'))       CREATE INDEX ix_app_sy_team            ON dbo.applications(sy_team_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_app_ug_team'            AND object_id=OBJECT_ID('dbo.applications'))       CREATE INDEX ix_app_ug_team            ON dbo.applications(ug_team_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_notif_cert'             AND object_id=OBJECT_ID('dbo.notifications'))      CREATE INDEX ix_notif_cert             ON dbo.notifications(certificate_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_appdep_target'          AND object_id=OBJECT_ID('dbo.app_dependencies'))   CREATE INDEX ix_appdep_target          ON dbo.app_dependencies(target_domain_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_appdep_clientcert'      AND object_id=OBJECT_ID('dbo.app_dependencies'))   CREATE INDEX ix_appdep_clientcert      ON dbo.app_dependencies(client_cert_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_prop_old'               AND object_id=OBJECT_ID('dbo.transfer_proposals')) CREATE INDEX ix_prop_old               ON dbo.transfer_proposals(old_cert_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_prop_new'               AND object_id=OBJECT_ID('dbo.transfer_proposals')) CREATE INDEX ix_prop_new               ON dbo.transfer_proposals(new_cert_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_prop_domain'            AND object_id=OBJECT_ID('dbo.transfer_proposals')) CREATE INDEX ix_prop_domain            ON dbo.transfer_proposals(domain_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_prop_appdep'            AND object_id=OBJECT_ID('dbo.transfer_proposals')) CREATE INDEX ix_prop_appdep            ON dbo.transfer_proposals(app_dependency_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_prop_sy_team'           AND object_id=OBJECT_ID('dbo.transfer_proposals')) CREATE INDEX ix_prop_sy_team           ON dbo.transfer_proposals(sy_team_id);
-- Granül benzersizliği YALNIZ açık öneriler (pending/approved) için — kapalı granül tekrar önerilebilir.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='uq_proposal_grain_open'    AND object_id=OBJECT_ID('dbo.transfer_proposals'))
    CREATE UNIQUE INDEX uq_proposal_grain_open
        ON dbo.transfer_proposals (old_cert_id, new_cert_id, domain_id, mapping_type, app_dependency_id)
        WHERE status IN ('pending','approved');
GO

-- Ağ keşfi (discovery) index'leri: FK destek (scan_targets.sy_team_id) + sorgu/upsert index'leri.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_scan_targets_sy_team'   AND object_id=OBJECT_ID('dbo.scan_targets'))            CREATE INDEX ix_scan_targets_sy_team   ON dbo.scan_targets(sy_team_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_disc_host'              AND object_id=OBJECT_ID('dbo.discovered_certificates')) CREATE INDEX ix_disc_host              ON dbo.discovered_certificates(host);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_disc_fingerprint'       AND object_id=OBJECT_ID('dbo.discovered_certificates')) CREATE INDEX ix_disc_fingerprint       ON dbo.discovered_certificates(fingerprint_sha256);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_scan_runs_started'      AND object_id=OBJECT_ID('dbo.scan_runs'))               CREATE INDEX ix_scan_runs_started      ON dbo.scan_runs(started_at);
GO

/* ---------------------------------------------------------------------------
   8) BACKFILL — mevcut satırları doldur (app açılışta da yapar; burada elle de
   çalıştırılabilir). fingerprint/san (PEM'den), parent_id (AKI/SKI), sy_team_id/
   ug_team_id (sy/ug metninden + teams) UYGULAMA tarafında üretilir (SQL ile değil,
   çünkü PEM ayrıştırma/SKI eşleşmesi gerekir). Aşağıdakiler basit varsayılanlardır:
   --------------------------------------------------------------------------- */
UPDATE dbo.SSLCertificates SET source     = 'manual' WHERE source IS NULL;
UPDATE dbo.SSLCertificates SET auto_renew = 0        WHERE auto_renew IS NULL;
-- is_internal: mevcut 'Internal' (metin) kolonundan türet
UPDATE dbo.SSLCertificates
   SET is_internal = CASE WHEN LOWER(LTRIM(RTRIM([Internal]))) IN ('1','true','evet','yes') THEN 1 ELSE 0 END
 WHERE is_internal IS NULL;
UPDATE dbo.domain_certificates SET created_at = SYSUTCDATETIME() WHERE created_at IS NULL;
UPDATE dbo.domain_certificates SET updated_at = SYSUTCDATETIME() WHERE updated_at IS NULL;
UPDATE dbo.users SET role        = 'viewer' WHERE role IS NULL;
UPDATE dbo.users SET auth_source = 'ldap'   WHERE auth_source IS NULL;
UPDATE dbo.users SET is_active   = 1        WHERE is_active IS NULL;
GO

/* ---------------------------------------------------------------------------
   9) APP-DEĞİŞMEZİ kolonlarını NOT NULL + DEFAULT yap (backfill'DEN SONRA). Neden: bu kolonlar
   app modelinde non-optional (NOT NULL) ama additive'de NULL eklenmişti; eski app / manuel / toplu
   INSERT bunları NULL bırakırsa app okurken None düşer (500 / satır sessizce filtrelenir). DEFAULT
   kısıtı gelecekteki tüm yazımları da korur. is_internal derivasyonu (8) korunur — burada yalnız kısıt.
   Idempotent (kısıt yoksa ekle; ALTER COLUMN NOT NULL zaten NOT NULL ise güvenle tekrarlanır).
   NOT: auth_source varsayılanı mevcut backfill ile tutarlı olsun diye 'ldap'; mevcut prod kullanıcıları
   lokal parolalıysa bu değeri 'local' yapmayı değerlendirin (semantik karar).
   --------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_SSLCert_source')
    ALTER TABLE dbo.SSLCertificates ADD CONSTRAINT DF_SSLCert_source DEFAULT N'manual' FOR source;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_SSLCert_auto_renew')
    ALTER TABLE dbo.SSLCertificates ADD CONSTRAINT DF_SSLCert_auto_renew DEFAULT 0 FOR auto_renew;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_SSLCert_is_internal')
    ALTER TABLE dbo.SSLCertificates ADD CONSTRAINT DF_SSLCert_is_internal DEFAULT 0 FOR is_internal;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_users_role')
    ALTER TABLE dbo.users ADD CONSTRAINT DF_users_role DEFAULT N'viewer' FOR role;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_users_auth_source')
    ALTER TABLE dbo.users ADD CONSTRAINT DF_users_auth_source DEFAULT N'ldap' FOR auth_source;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_users_is_active')
    ALTER TABLE dbo.users ADD CONSTRAINT DF_users_is_active DEFAULT 1 FOR is_active;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_dc_created_at')
    ALTER TABLE dbo.domain_certificates ADD CONSTRAINT DF_dc_created_at DEFAULT SYSUTCDATETIME() FOR created_at;
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name='DF_dc_updated_at')
    ALTER TABLE dbo.domain_certificates ADD CONSTRAINT DF_dc_updated_at DEFAULT SYSUTCDATETIME() FOR updated_at;
GO
-- Backfill tüm NULL'ları doldurdu → şimdi NOT NULL yap (zaten NOT NULL ise tekrar güvenli).
ALTER TABLE dbo.SSLCertificates   ALTER COLUMN source      NVARCHAR(20) NOT NULL;
ALTER TABLE dbo.SSLCertificates   ALTER COLUMN auto_renew  BIT          NOT NULL;
ALTER TABLE dbo.SSLCertificates   ALTER COLUMN is_internal BIT          NOT NULL;
ALTER TABLE dbo.users             ALTER COLUMN role        NVARCHAR(20) NOT NULL;
ALTER TABLE dbo.users             ALTER COLUMN auth_source NVARCHAR(10) NOT NULL;
ALTER TABLE dbo.users             ALTER COLUMN is_active   BIT          NOT NULL;
ALTER TABLE dbo.domain_certificates ALTER COLUMN created_at DATETIME2   NOT NULL;
ALTER TABLE dbo.domain_certificates ALTER COLUMN updated_at DATETIME2   NOT NULL;
GO

/* fingerprint + san (PEM'den), parent_id (SKI zinciri), teams + sy_team_id/ug_team_id
   (domain_certificates.sy/ug ve applications.sy_team/ug_team metinlerinden, e-posta
   [group]'tan) → bunlar UYGULAMA açılışında otomatik doldurulur (backfill_certificate_fields,
   backfill_parent_links, backfill_team_owners). SQL ile yapılmaz. */
