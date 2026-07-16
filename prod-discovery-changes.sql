/* ============================================================================
   JUMBO — KEŞİF + CT + POLİTİKA + REVOCATION için TEK konsolide ADDITIVE şema.

   Ne zaman çalıştırılır: MEVCUT prod veritabanında, ELLE (DBA). Taze bir DB'de
   uygulama açılışta bu tablo/kolonları zaten kurar (create_all + ensure_new_columns);
   bu script yalnız önceden kurulmuş prod DB'sine son eklemeleri uygulamak içindir.

   İdempotent: tablo/index/kolon yoksa oluşturur, varsa DOKUNMAZ → tekrar
   çalıştırmak güvenlidir. GO batch ayraçları (SSMS/sqlcmd).

   NOT: Son 3 özelliğin (CT log, politika/uyum, revocation) TÜM DB değişiklikleri operatör
   isteğiyle bu TEK dosyada toplanmıştır — prod'da yalnız bunu çalıştırman yeterli.
   (Ayrı prod-policy-changes.sql / prod-revocation-changes.sql dosyaları kaldırıldı;
    aynı DDL ayrıca taze kurulum için schema-mssql.sql'de ve kümülatif prod-additive-changes.sql'de
    de bulunur — hepsi idempotent olduğundan çakışma olmaz.)

   BÖLÜM 1 — YENİ TABLOLAR (ağ keşfi):
     • scan_targets            — tarama hedefleri (CIDR aralığı / tekil host / envanter domainleri).
                                 sy_team_id yalnız etiket/kapsam ipucudur (DB-cascade YOK).
     • discovered_certificates — ağda bir endpoint'te (host:port) SUNULAN sertifika bulgusu.
                                 Envanterdeki SSLCertificates'a FK İLE BAĞLANMAZ — eşleşme
                                 fingerprint ile OKUMA ANINDA çözülür → MSSQL çoklu-cascade
                                 yolu / kilit derdi yoktur. (host,port,fingerprint) benzersiz.
                                 status: new(shadow) | in_inventory | adopted | ignored.
     • scan_runs               — bir tarama çalıştırmasının özeti (görev izleme / "son tarama").
   BÖLÜM 2 — MEVCUT TABLO KOLONLARI (CT):     discovered_certificates.origin/crtsh_id, scan_runs.kind
   BÖLÜM 3 — MEVCUT TABLO KOLONLARI (politika): SSLCertificates.key_size/public_key_type/key_curve/signature_hash
   BÖLÜM 4 — MEVCUT TABLO KOLONLARI (revocation): SSLCertificates.revocation_status/checked_at/detail
   ============================================================================ */

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

IF OBJECT_ID('dbo.scan_targets','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_scan_targets_sy_team' AND object_id=OBJECT_ID('dbo.scan_targets'))
CREATE INDEX ix_scan_targets_sy_team ON dbo.scan_targets (sy_team_id);
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
    crtsh_id NVARCHAR(50) NULL,          -- CT bulgusunda crt.sh giriş kimliği (CT satırlarında host=domain, port=0)
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

-- CT (crt.sh) izleme: origin (network|ct) + crtsh_id kolonları additive (idempotent). Mevcut satırlar 'network'.
IF COL_LENGTH('dbo.discovered_certificates','origin') IS NULL
    ALTER TABLE dbo.discovered_certificates ADD origin NVARCHAR(20) NULL;
GO
UPDATE dbo.discovered_certificates SET origin='network' WHERE origin IS NULL;
GO
IF COL_LENGTH('dbo.discovered_certificates','crtsh_id') IS NULL
    ALTER TABLE dbo.discovered_certificates ADD crtsh_id NVARCHAR(50) NULL;
GO

IF OBJECT_ID('dbo.discovered_certificates','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_disc_host' AND object_id=OBJECT_ID('dbo.discovered_certificates'))
CREATE INDEX ix_disc_host ON dbo.discovered_certificates (host);
GO

IF OBJECT_ID('dbo.discovered_certificates','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_disc_fingerprint' AND object_id=OBJECT_ID('dbo.discovered_certificates'))
CREATE INDEX ix_disc_fingerprint ON dbo.discovered_certificates (fingerprint_sha256);
GO

IF OBJECT_ID('dbo.scan_runs','U') IS NULL
CREATE TABLE dbo.scan_runs (
    id INT NOT NULL IDENTITY(1,1),
    started_at DATETIME2 NOT NULL,
    finished_at DATETIME2 NULL,
    status NVARCHAR(12) NOT NULL,        -- running | done | error
    [trigger] NVARCHAR(20) NULL,         -- manual | schedule (SQL ayrılmış sözcük → köşeli parantez)
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

IF OBJECT_ID('dbo.scan_runs','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_scan_runs_started' AND object_id=OBJECT_ID('dbo.scan_runs'))
CREATE INDEX ix_scan_runs_started ON dbo.scan_runs (started_at);
GO

/* ----------------------------------------------------------------------------
   BÖLÜM 3 — POLİTİKA / UYUM (policy) kolonları  →  SSLCertificates
   Sertifikanın kripto özellikleri; politika/uyum motoru (zayıf anahtar/imza) ve
   gelecekteki PQC/crypto-agility envanteri kullanır. Değerler açılışta PEM'den
   backfill_certificate_crypto ile doldurulur. Hepsi NULL (kısıt sıkılaştırma YOK).
     • key_size         — RSA modülüs bit / EC eğri boyu
     • public_key_type  — RSA | EC | Ed25519 | Ed448 | DSA
     • key_curve        — EC eğri adı (secp256r1…), diğerlerinde NULL
     • signature_hash   — imza özet algoritması (sha256/sha1/md5…), EdDSA'da NULL
   ---------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.SSLCertificates','key_size')        IS NULL
    ALTER TABLE dbo.SSLCertificates ADD key_size INT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','public_key_type') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD public_key_type NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','key_curve')       IS NULL
    ALTER TABLE dbo.SSLCertificates ADD key_curve NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','signature_hash')  IS NULL
    ALTER TABLE dbo.SSLCertificates ADD signature_hash NVARCHAR(50) NULL;
GO

/* ----------------------------------------------------------------------------
   BÖLÜM 4 — İPTAL / REVOCATION (OCSP/CRL) kolonları  →  SSLCertificates
   Sertifikanın OCSP/CRL ile denetlenen iptal durumu. Değer uygulama tarafından
   yazılır (gece cron veya elle "Şimdi Kontrol Et"); NULL = denetlenmemiş.
   BACKFILL YOK. JUMBO iptal görse bile sertifikayı otomatik pasife ALMAZ.
     • revocation_status      — good | revoked | unknown | NULL(denetlenmemiş)
     • revocation_checked_at  — son denetim zamanı (UTC)
     • revocation_detail      — JSON ayrıntı (method/responder/reason)
   ---------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.SSLCertificates','revocation_status')     IS NULL
    ALTER TABLE dbo.SSLCertificates ADD revocation_status NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','revocation_checked_at') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD revocation_checked_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','revocation_detail')     IS NULL
    ALTER TABLE dbo.SSLCertificates ADD revocation_detail NVARCHAR(MAX) NULL;
GO

/* ----------------------------------------------------------------------------
   BÖLÜM 5 — BİLDİRİM KANALI kolonu  →  notifications
   Süre uyarıları e-postaya EK olarak Slack/Teams/Webhook kanallarına yayınlanır;
   tekrar-önleme (dedup) KANAL-bazlıdır → (certificate_id, channel). notifications
   app-yeni tablodur (taze DB'de create_all kurar); önceden kolonsuz kurulmuş DB'de
   additive eklenir (idempotent). channel: email|slack|teams|webhook|… (mevcut satırlar 'email').
   ---------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.notifications','U') IS NOT NULL
   AND COL_LENGTH('dbo.notifications','channel') IS NULL
    ALTER TABLE dbo.notifications ADD channel NVARCHAR(20) NULL;
GO
IF OBJECT_ID('dbo.notifications','U') IS NOT NULL
    UPDATE dbo.notifications SET channel='email' WHERE channel IS NULL;
GO
