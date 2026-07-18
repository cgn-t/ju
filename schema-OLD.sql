-- =============================================================================
-- JUMBO — schema-OLD.sql  (BASELINE / UYGULANMIŞ ŞEMA — 2026-07-18)
-- Su ana kadar proda uygulanmis TUM .sql dosyalarinin birlesimidir.
-- Bundan SONRAKI degisiklikler icin: schema-NEW.sql
-- Birlesenler: schema-mssql, prod-additive-changes, prod-align-changes,
--             prod-discovery-changes, prod-tags
-- =============================================================================


-- ======================= BÖLÜM: schema-mssql.sql =======================
-- JUMBO — MSSQL şeması (models.py metadata'sından ÜRETİLDİ; elle düzenlemeyin).
-- Prod ADLARI ve uzunlukları ile: SSLCertificates/domain_certificates/SSLCertificateDomainMapping/
-- AuditLog + yeni tablolar. Taze DB için; MEVCUT prod'a additive uygulama için
-- prod-additive-changes.sql + prod-align-changes.sql kullanın.
-- Not: uygulama açılışta create_all + ensure_new_columns + ensure_indexes ile şemayı kendi de kurar.

CREATE TABLE [AuditLog] (
	[ID] INTEGER NOT NULL IDENTITY, 
	[Username] NVARCHAR(100) NOT NULL, 
	[Action] NVARCHAR(20) NOT NULL, 
	[TableName] NVARCHAR(100) NOT NULL, 
	[RecordID] NVARCHAR(50) NULL, 
	[Details] NTEXT NULL, 
	[CreatedAt] DATETIME NOT NULL, 
	ip_address NVARCHAR(50) NULL, 
	PRIMARY KEY ([ID])
);

CREATE INDEX [ix_AuditLog_CreatedAt] ON [AuditLog] ([CreatedAt]);

CREATE TABLE [SSLCertificates] (
	[ID] INTEGER NOT NULL IDENTITY, 
	[NAME] NVARCHAR(255) NOT NULL, 
	[SerialNumber] NVARCHAR(100) NULL, 
	[Issuer] NVARCHAR(500) NULL, 
	[Subject] NVARCHAR(500) NULL, 
	[SubjectKeyIdentifier] NVARCHAR(100) NULL, 
	[AuthorityKeyIdentifier] NVARCHAR(100) NULL, 
	[CertType] NVARCHAR(50) NOT NULL, 
	[ValidFrom] DATETIME NULL, 
	[ValidTo] DATETIME NULL, 
	[PEMCertificate] NTEXT NULL, 
	[ExtendedKeyUsage] NVARCHAR(255) NULL, 
	[IsActive] BIT NOT NULL, 
	[SatinAlimYapan] NVARCHAR(255) NULL, 
	[CertificateCreator] NVARCHAR(255) NULL, 
	[Notes] NTEXT NULL, 
	[CreatedDate] DATETIME NOT NULL, 
	[ModifiedDate] DATETIME NOT NULL, 
	san NTEXT NULL, 
	fingerprint_sha256 NVARCHAR(100) NULL, 
	parent_id INTEGER NULL, 
	superseded_by_id INTEGER NULL, 
	is_internal BIT NOT NULL DEFAULT 0, 
	source NVARCHAR(20) NOT NULL DEFAULT 'manual',
	vault_path NVARCHAR(255) NULL,
	auto_renew BIT NOT NULL DEFAULT 0,
	key_size INTEGER NULL,
	public_key_type NVARCHAR(20) NULL,
	key_curve NVARCHAR(50) NULL,
	signature_hash NVARCHAR(50) NULL,
	revocation_status NVARCHAR(20) NULL,
	revocation_checked_at DATETIME NULL,
	revocation_detail NTEXT NULL,
	PRIMARY KEY ([ID]),
	FOREIGN KEY(parent_id) REFERENCES [SSLCertificates] ([ID]), 
	FOREIGN KEY(superseded_by_id) REFERENCES [SSLCertificates] ([ID])
);

CREATE INDEX [ix_SSLCertificates_AuthorityKeyIdentifier] ON [SSLCertificates] ([AuthorityKeyIdentifier]);
CREATE INDEX [ix_SSLCertificates_SubjectKeyIdentifier] ON [SSLCertificates] ([SubjectKeyIdentifier]);
CREATE INDEX [ix_SSLCertificates_ValidTo] ON [SSLCertificates] ([ValidTo]);
CREATE INDEX [ix_SSLCertificates_fingerprint_sha256] ON [SSLCertificates] (fingerprint_sha256);
CREATE INDEX [ix_SSLCertificates_parent_id] ON [SSLCertificates] (parent_id);
CREATE INDEX [ix_SSLCertificates_superseded_by_id] ON [SSLCertificates] (superseded_by_id);
CREATE UNIQUE INDEX ux_sslcertificates_fingerprint ON [SSLCertificates] (fingerprint_sha256) WHERE fingerprint_sha256 IS NOT NULL;
CREATE UNIQUE INDEX ux_sslcertificates_issuer_serial ON [SSLCertificates] ([Issuer], [SerialNumber]) WHERE SerialNumber IS NOT NULL;

CREATE TABLE app_settings (
	[key] NVARCHAR(100) NOT NULL, 
	category NVARCHAR(20) NOT NULL, 
	value NTEXT NULL, 
	is_encrypted BIT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY ([key])
);

CREATE INDEX ix_app_settings_category ON app_settings (category);

CREATE TABLE teams (
	id INTEGER NOT NULL IDENTITY, 
	name NVARCHAR(255) NOT NULL, 
	type NVARCHAR(10) NOT NULL, 
	email NVARCHAR(255) NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_team_name_type UNIQUE (name, type)
);

CREATE TABLE users (
	id INTEGER NOT NULL IDENTITY, 
	username NVARCHAR(100) NOT NULL, 
	password NVARCHAR(255) NULL, 
	email NVARCHAR(255) NULL, 
	created_at DATETIME NOT NULL, 
	full_name NVARCHAR(255) NULL, 
	role NVARCHAR(20) NOT NULL DEFAULT 'viewer', 
	auth_source NVARCHAR(10) NOT NULL DEFAULT 'ldap', 
	is_active BIT NOT NULL DEFAULT 1, 
	last_login DATETIME NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_username ON users (username);

CREATE TABLE domain_certificates (
	id INTEGER NOT NULL IDENTITY, 
	domain NVARCHAR(255) NOT NULL, 
	external_address NVARCHAR(255) NULL, 
	cert_owner NVARCHAR(255) NULL, 
	lb_update NVARCHAR(255) NULL, 
	env_update NVARCHAR(255) NULL, 
	waf_update NVARCHAR(255) NULL, 
	external_company NVARCHAR(255) NULL, 
	expire_date DATETIME NULL, 
	info NTEXT NULL, 
	mail_addresses NVARCHAR(255) NULL, 
	[Aksiyon_Alma] NVARCHAR(255) NULL, 
	[SSLPinning] NVARCHAR(255) NULL, 
	[Keystore] NVARCHAR(500) NULL, 
	ug_team_id INTEGER NULL, 
	sy_team_id INTEGER NULL, 
	ug_team_name NVARCHAR(255) NULL, 
	servers_to_update NVARCHAR(500) NULL, 
	live_check_status NVARCHAR(20) NULL, 
	live_check_detail NTEXT NULL, 
	live_check_at DATETIME NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ug_team_id) REFERENCES teams (id), 
	FOREIGN KEY(sy_team_id) REFERENCES teams (id)
);

CREATE INDEX ix_domain_certificates_domain ON domain_certificates (domain);
CREATE INDEX ix_domain_certificates_sy_team_id ON domain_certificates (sy_team_id);
CREATE INDEX ix_domain_certificates_ug_team_id ON domain_certificates (ug_team_id);

CREATE TABLE notifications (
	id INTEGER NOT NULL IDENTITY, 
	certificate_id INTEGER NULL, 
	recipient NVARCHAR(500) NULL, 
	subject NVARCHAR(500) NULL, 
	days_left INTEGER NULL, 
	sent_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(certificate_id) REFERENCES [SSLCertificates] ([ID]) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_certificate_id ON notifications (certificate_id);

CREATE TABLE user_teams (
	id INTEGER NOT NULL IDENTITY, 
	user_id INTEGER NOT NULL, 
	team_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_team UNIQUE (user_id, team_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_teams_team_id ON user_teams (team_id);
CREATE INDEX ix_user_teams_user_id ON user_teams (user_id);

CREATE TABLE [SSLCertificateDomainMapping] (
	[ID] INTEGER NOT NULL IDENTITY, 
	[CertID] INTEGER NOT NULL, 
	[DomainID] INTEGER NOT NULL, 
	[MappingType] VARCHAR(10) NOT NULL, 
	PRIMARY KEY ([ID]), 
	CONSTRAINT uq_cert_domain_type UNIQUE ([CertID], [DomainID], [MappingType]), 
	FOREIGN KEY([CertID]) REFERENCES [SSLCertificates] ([ID]) ON DELETE CASCADE, 
	FOREIGN KEY([DomainID]) REFERENCES domain_certificates (id) ON DELETE CASCADE
);

CREATE TABLE applications (
	id INTEGER NOT NULL IDENTITY, 
	app_name NVARCHAR(255) NOT NULL, 
	app_user NVARCHAR(255) NULL, 
	conf_path NVARCHAR(500) NULL, 
	control_method NVARCHAR(255) NULL, 
	dns NVARCHAR(255) NULL, 
	info NTEXT NULL, 
	ip_address NVARCHAR(100) NULL, 
	log_path NVARCHAR(500) NULL, 
	notes NTEXT NULL, 
	required_commands NTEXT NULL, 
	server_name NVARCHAR(255) NULL, 
	service_provider_contact NVARCHAR(255) NULL, 
	start_stop_method NVARCHAR(500) NULL, 
	status BIT NOT NULL, 
	domain_id INTEGER NULL, 
	sy_team_id INTEGER NULL, 
	ug_team_id INTEGER NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(domain_id) REFERENCES domain_certificates (id) ON DELETE SET NULL, 
	FOREIGN KEY(sy_team_id) REFERENCES teams (id), 
	FOREIGN KEY(ug_team_id) REFERENCES teams (id)
);

CREATE INDEX ix_applications_domain_id ON applications (domain_id);
CREATE INDEX ix_applications_sy_team_id ON applications (sy_team_id);
CREATE INDEX ix_applications_ug_team_id ON applications (ug_team_id);

CREATE TABLE app_dependencies (
	id INTEGER NOT NULL IDENTITY, 
	app_id INTEGER NOT NULL, 
	target_domain_id INTEGER NOT NULL, 
	client_cert_id INTEGER NULL, 
	note NVARCHAR(500) NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_app_target UNIQUE (app_id, target_domain_id), 
	FOREIGN KEY(app_id) REFERENCES applications (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_domain_id) REFERENCES domain_certificates (id) ON DELETE CASCADE, 
	FOREIGN KEY(client_cert_id) REFERENCES [SSLCertificates] ([ID]) ON DELETE SET NULL
);

CREATE INDEX ix_app_dependencies_client_cert_id ON app_dependencies (client_cert_id);
CREATE INDEX ix_app_dependencies_target_domain_id ON app_dependencies (target_domain_id);

CREATE TABLE transfer_proposals (
	id INTEGER NOT NULL IDENTITY, 
	old_cert_id INTEGER NOT NULL, 
	new_cert_id INTEGER NOT NULL, 
	domain_id INTEGER NULL, 
	mapping_type VARCHAR(10) NULL, 
	app_dependency_id INTEGER NULL, 
	sy_team_id INTEGER NULL, 
	status NVARCHAR(12) NOT NULL, 
	signal NVARCHAR(20) NULL, 
	via NVARCHAR(20) NULL, 
	live_seen BIT NOT NULL, 
	live_seen_at DATETIME NULL, 
	created_by NVARCHAR(100) NULL, 
	created_at DATETIME NOT NULL, 
	decided_by NVARCHAR(100) NULL, 
	decided_at DATETIME NULL, 
	applied_at DATETIME NULL, 
	note NTEXT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(old_cert_id) REFERENCES [SSLCertificates] ([ID]), 
	FOREIGN KEY(new_cert_id) REFERENCES [SSLCertificates] ([ID]), 
	FOREIGN KEY(domain_id) REFERENCES domain_certificates (id), 
	FOREIGN KEY(app_dependency_id) REFERENCES app_dependencies (id), 
	FOREIGN KEY(sy_team_id) REFERENCES teams (id)
);

CREATE INDEX ix_transfer_proposals_app_dependency_id ON transfer_proposals (app_dependency_id);
CREATE INDEX ix_transfer_proposals_created_at ON transfer_proposals (created_at);
CREATE INDEX ix_transfer_proposals_domain_id ON transfer_proposals (domain_id);
CREATE INDEX ix_transfer_proposals_new_cert_id ON transfer_proposals (new_cert_id);
CREATE INDEX ix_transfer_proposals_old_cert_id ON transfer_proposals (old_cert_id);
CREATE INDEX ix_transfer_proposals_status ON transfer_proposals (status);
CREATE INDEX ix_transfer_proposals_sy_team_id ON transfer_proposals (sy_team_id);
CREATE UNIQUE INDEX uq_proposal_grain_open ON transfer_proposals (old_cert_id, new_cert_id, domain_id, mapping_type, app_dependency_id) WHERE status IN ('pending','approved');

CREATE TABLE tags (
	id INTEGER NOT NULL IDENTITY,
	name NVARCHAR(100) NOT NULL,
	category NVARCHAR(50) NOT NULL,
	color NVARCHAR(20) NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_tag_category_name UNIQUE (category, name)
);

CREATE INDEX ix_tags_category ON tags (category);

CREATE TABLE application_tags (
	id INTEGER NOT NULL IDENTITY,
	application_id INTEGER NOT NULL,
	tag_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_application_tag UNIQUE (application_id, tag_id),
	FOREIGN KEY(application_id) REFERENCES applications (id) ON DELETE CASCADE,
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

CREATE INDEX ix_application_tags_application_id ON application_tags (application_id);
CREATE INDEX ix_application_tags_tag_id ON application_tags (tag_id);

-- Ağ keşfi (discovery) — YENİ app tabloları (prod'da yok; create_all kurar).
CREATE TABLE scan_targets (
	id INTEGER NOT NULL IDENTITY,
	name NVARCHAR(255) NOT NULL,
	kind NVARCHAR(20) NOT NULL,
	value NVARCHAR(255) NULL,
	ports NVARCHAR(100) NULL,
	enabled BIT NOT NULL DEFAULT 1,
	sy_team_id INTEGER NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(sy_team_id) REFERENCES teams (id)
);
CREATE INDEX ix_scan_targets_sy_team_id ON scan_targets (sy_team_id);

CREATE TABLE discovered_certificates (
	id INTEGER NOT NULL IDENTITY,
	host NVARCHAR(255) NOT NULL,
	port INTEGER NOT NULL,
	fingerprint_sha256 NVARCHAR(100) NOT NULL,
	name NVARCHAR(255) NULL,
	issuer NVARCHAR(500) NULL,
	subject NVARCHAR(500) NULL,
	san NTEXT NULL,
	serial_number NVARCHAR(100) NULL,
	valid_from DATETIME NULL,
	valid_to DATETIME NULL,
	pem_certificate NTEXT NULL,
	status NVARCHAR(20) NOT NULL DEFAULT 'new',
	origin NVARCHAR(20) NOT NULL DEFAULT 'network',
	crtsh_id NVARCHAR(50) NULL,
	sy_team_id INTEGER NULL,
	first_seen_at DATETIME NOT NULL,
	last_seen_at DATETIME NOT NULL,
	note NTEXT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_discovered_endpoint UNIQUE (host, port, fingerprint_sha256)
);
CREATE INDEX ix_discovered_certificates_host ON discovered_certificates (host);
CREATE INDEX ix_discovered_certificates_fingerprint_sha256 ON discovered_certificates (fingerprint_sha256);

CREATE TABLE scan_runs (
	id INTEGER NOT NULL IDENTITY,
	started_at DATETIME NOT NULL,
	finished_at DATETIME NULL,
	status NVARCHAR(12) NOT NULL,
	[trigger] NVARCHAR(20) NULL,
	kind NVARCHAR(20) NOT NULL DEFAULT 'network',
	targets_scanned INTEGER NOT NULL DEFAULT 0,
	hosts_reachable INTEGER NOT NULL DEFAULT 0,
	new_findings INTEGER NOT NULL DEFAULT 0,
	error NTEXT NULL,
	created_by NVARCHAR(100) NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_scan_runs_started_at ON scan_runs (started_at);


-- ======================= BÖLÜM: prod-additive-changes.sql =======================
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


-- ======================= BÖLÜM: prod-align-changes.sql =======================
-- ============================================================================
-- JUMBO — PROD HİZALAMA DEĞİŞİKLİKLERİ (additive'in ÖTESİNDE, kullanıcı onaylı)
-- ----------------------------------------------------------------------------
-- Bu dosya, prod-additive-changes.sql'in (yeni tablo/kolon) ÜZERİNE, app
-- ile prod arasındaki KALAN farkları prod tarafında kapatan 3 değişikliği içerir.
-- Hepsi güvenli/idempotent ve MSSQL içindir. ÖNCE YEDEK alın.
--
--   1) SSLCertificates kolon adı → CertificateCreator  (app ORM bu adı bekler)
--   2) Kolon uzunluklarını app (ORM) boyuna GENİŞLET   (nvarchar genişletme = veri kaybı YOK)
--   3) Kimlik benzersizliği: (Issuer, SerialNumber) filtreli UNIQUE index (X.509/RFC5280-doğru).
--      GLOBAL UNIQUE(SerialNumber) KULLANILMAZ — tekil kimlik = fingerprint (additive'de).
--
-- NOT: TMTKS00'a bağlıyken çalıştırın (USE TMTKS00). Her blok tekrar çalıştırmaya dayanıklıdır.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) CertificateCreator: prod kolon adını app'in beklediği ada çevir.
--    Mevcut ad karartılmıştı; GERÇEK mevcut adı @old_name'e yazın (ör. 'aaakkkCertificateCreator').
--    Hedef ad zaten CertificateCreator ise hiçbir şey yapmaz.
-- ----------------------------------------------------------------------------
DECLARE @old_name sysname = N'aaakkkCertificateCreator';   -- <<< GERÇEK mevcut prod kolon adını yazın
IF COL_LENGTH('dbo.SSLCertificates', 'CertificateCreator') IS NULL
   AND COL_LENGTH('dbo.SSLCertificates', @old_name) IS NOT NULL
BEGIN
    DECLARE @ren nvarchar(400) = N'dbo.SSLCertificates.' + @old_name;  -- sp_rename 3-parçalı ad ister (tırnaksız)
    EXEC sp_rename @objname = @ren, @newname = N'CertificateCreator', @objtype = 'COLUMN';
    PRINT '1) Kolon yeniden adlandırıldı: ' + @old_name + ' -> CertificateCreator';
END
ELSE
    PRINT '1) CertificateCreator zaten mevcut ya da kaynak kolon yok — atlandı.';
GO

-- ----------------------------------------------------------------------------
-- 2) Uzunluk hizalama: prod kolonlarını app (ORM) boyuna GENİŞLET.
--    Nullability PROD'daki mevcut haliyle KORUNUR (sys.columns'tan okunur) — daraltma/gevşetme YOK.
--    Genişletme güvenlidir: mevcut veri sığar, truncation olmaz.
-- ----------------------------------------------------------------------------
DECLARE @cols TABLE (tbl sysname, col sysname, len int);
INSERT INTO @cols (tbl, col, len) VALUES
    ('users','username',100), ('users','email',255),
    ('domain_certificates','waf_update',255), ('domain_certificates','Aksiyon_Alma',255),
    ('domain_certificates','SSLPinning',255),
    ('applications','app_name',255), ('applications','app_user',255),
    ('applications','conf_path',500), ('applications','control_method',255),
    ('applications','dns',255), ('applications','ip_address',100),
    ('applications','log_path',500), ('applications','server_name',255),
    ('applications','start_stop_method',500);

DECLARE @t sysname, @c sysname, @l int, @nullclause nvarchar(10), @curlen int, @sql nvarchar(max);
DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT tbl, col, len FROM @cols;
OPEN cur;
FETCH NEXT FROM cur INTO @t, @c, @l;
WHILE @@FETCH_STATUS = 0
BEGIN
    SELECT @curlen = c.max_length,        -- nvarchar max_length = 2*karakter (max = -1)
           @nullclause = CASE WHEN c.is_nullable = 1 THEN N'NULL' ELSE N'NOT NULL' END
    FROM sys.columns c
    WHERE c.object_id = OBJECT_ID('dbo.' + @t) AND c.name = @c;

    IF @curlen IS NULL
        PRINT '2) ATLANDI (kolon yok): ' + @t + '.' + @c;
    ELSE IF @curlen = -1 OR @curlen >= @l * 2
        PRINT '2) OK (zaten yeterli): ' + @t + '.' + @c;
    ELSE
    BEGIN
        SET @sql = N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' ALTER COLUMN ' + QUOTENAME(@c) +
                   N' nvarchar(' + CAST(@l AS nvarchar(10)) + N') ' + @nullclause + N';';
        PRINT '2) ' + @sql;
        EXEC sys.sp_executesql @sql;
    END
    FETCH NEXT FROM cur INTO @t, @c, @l;
END
CLOSE cur; DEALLOCATE cur;
GO

-- ----------------------------------------------------------------------------
-- 3) Sertifika KİMLİK benzersizliği — BEST PRACTICE.
--    Tekil kimlik = SHA-256 fingerprint (ux_sslcertificates_fingerprint; additive'de kurulur).
--    Seri numarası GLOBAL benzersiz DEĞİLDİR (RFC 5280: seri yalnız onu VEREN CA içinde
--    benzersiz; farklı CA'lar aynı seriyi verebilir) → global UNIQUE(SerialNumber) KULLANILMAZ.
--    Mantıksal anahtar = (Issuer, SerialNumber): NULL-güvenli filtreli UNIQUE index.
-- ----------------------------------------------------------------------------
-- 3a) Bir önceki plandan kalmış olabilecek HATALI global UNIQUE(SerialNumber)'ı kaldır.
IF EXISTS (SELECT 1 FROM sys.key_constraints
           WHERE parent_object_id = OBJECT_ID('dbo.SSLCertificates') AND name = 'UQ_SSLCert_Serial')
BEGIN
    ALTER TABLE dbo.SSLCertificates DROP CONSTRAINT UQ_SSLCert_Serial;
    PRINT '3a) Eski global UNIQUE(SerialNumber) kaldırıldı: UQ_SSLCert_Serial';
END
GO
-- 3b) (Issuer, SerialNumber) filtreli UNIQUE index. ÖNCE mükerrer kontrolü — varsa eklenmez.
IF EXISTS (SELECT 1 FROM dbo.SSLCertificates WHERE SerialNumber IS NOT NULL
           GROUP BY Issuer, SerialNumber HAVING COUNT(*) > 1)
BEGIN
    PRINT '3b) UYARI: mükerrer (Issuer, SerialNumber) VAR — unique index eklenmedi. Önce temizleyin:';
    PRINT '   SELECT Issuer, SerialNumber, COUNT(*) FROM dbo.SSLCertificates WHERE SerialNumber IS NOT NULL GROUP BY Issuer, SerialNumber HAVING COUNT(*)>1;';
END
ELSE IF NOT EXISTS (SELECT 1 FROM sys.indexes
                    WHERE object_id = OBJECT_ID('dbo.SSLCertificates')
                      AND name = 'ux_sslcertificates_issuer_serial')
BEGIN
    CREATE UNIQUE INDEX ux_sslcertificates_issuer_serial
        ON dbo.SSLCertificates (Issuer, SerialNumber)
        WHERE SerialNumber IS NOT NULL;
    PRINT '3b) (Issuer, SerialNumber) filtreli UNIQUE index eklendi: ux_sslcertificates_issuer_serial';
END
ELSE
    PRINT '3b) (Issuer, SerialNumber) unique zaten mevcut — atlandı.';
GO


-- ======================= BÖLÜM: prod-discovery-changes.sql =======================
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


-- ======================= BÖLÜM: prod-tags.sql =======================
/* ============================================================================
   JUMBO — ETİKET (tag) özelliği için ADDITIVE şema (yalnız YENİ tablolar).

   Ne zaman çalıştırılır: MEVCUT prod veritabanında, ELLE (DBA). Taze bir DB'de
   uygulama açılışta Base.metadata.create_all ile bu tabloları zaten kurar; bu
   script yalnız önceden kurulmuş prod DB'sine iki yeni tabloyu eklemek içindir.

   İdempotent: tablolar/indexler yoksa oluşturur, varsa DOKUNMAZ → tekrar
   çalıştırmak güvenlidir. GO batch ayraçları (SSMS/sqlcmd).

   Eklenen tablolar (mevcut tablolara KOLON EKLENMEZ):
     • tags              — kontrollü, kategorili etiket kataloğu
                           (category, name) benzersiz; aynı ad farklı kategoride olabilir.
     • application_tags  — uygulama ↔ etiket (çoktan-çoğa).
                           Uygulama VEYA etiket silinince satır CASCADE ile düşer.
   ============================================================================ */

IF OBJECT_ID('dbo.tags','U') IS NULL
CREATE TABLE dbo.tags (
    id INT NOT NULL IDENTITY(1,1),
    name NVARCHAR(100) NOT NULL,
    category NVARCHAR(50) NOT NULL,
    color NVARCHAR(20) NULL,
    created_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_tag_category_name UNIQUE (category, name)
);
GO

IF OBJECT_ID('dbo.tags','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_tags_category' AND object_id=OBJECT_ID('dbo.tags'))
CREATE INDEX ix_tags_category ON dbo.tags (category);
GO

IF OBJECT_ID('dbo.application_tags','U') IS NULL
CREATE TABLE dbo.application_tags (
    id INT NOT NULL IDENTITY(1,1),
    application_id INT NOT NULL,
    tag_id INT NOT NULL,
    created_at DATETIME2 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_application_tag UNIQUE (application_id, tag_id),
    FOREIGN KEY(application_id) REFERENCES dbo.applications(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES dbo.tags(id) ON DELETE CASCADE
);
GO

IF OBJECT_ID('dbo.application_tags','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_application_tags_application_id' AND object_id=OBJECT_ID('dbo.application_tags'))
CREATE INDEX ix_application_tags_application_id ON dbo.application_tags (application_id);
GO

IF OBJECT_ID('dbo.application_tags','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE name='ix_application_tags_tag_id' AND object_id=OBJECT_ID('dbo.application_tags'))
CREATE INDEX ix_application_tags_tag_id ON dbo.application_tags (tag_id);
GO

