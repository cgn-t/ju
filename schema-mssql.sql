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
