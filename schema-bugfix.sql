-- -----------------------------------------------------------------------------
-- schema-bugfix.sql — prod'da tekrarlayan "Invalid column name '...'" hatasının
-- kalıcı düzeltmesi.
--
-- NEDEN: schema-OLD.sql script'i baştan sona tam çalıştırılmadığında (parça
-- parça / atlanarak çalıştırıldığında), daha sonraki bölümler henüz eklenmemiş
-- kolonlara referans verip "Invalid column name" hatası veriyor. İlk seferde
-- fingerprint_sha256/is_internal, ikinci seferde source/created_at bu şekilde
-- çıktı — script'in atladığı her kolon sırayla aynı hatayı verecek.
--
-- ÇÖZÜM: schema-OLD.sql'de MEVCUT PROD tablolarına (SSLCertificates,
-- domain_certificates, applications, users, AuditLog) eklenen TÜM additive
-- kolonları, bu betik ile TEK SEFERDE ve en başta ekleyin. İdempotenttir
-- (IF COL_LENGTH ... IS NULL ile sarılı) — tekrar tekrar çalıştırmak güvenlidir,
-- var olan kolonlara dokunmaz.
--
-- ÇALIŞTIRMA SIRASI:
--   1) Bu betiği (schema-bugfix.sql) baştan sona, TAM olarak çalıştırın.
--   2) Ardından schema-OLD.sql'i baştan sona tekrar çalıştırın (artık bu
--      kolonlar zaten var olduğu için o satırlar no-op geçecek; script'in geri
--      kalanı — index/backfill/NOT NULL sıkılaştırma — sorunsuz ilerleyecek).
-- -----------------------------------------------------------------------------

/* ---- SSLCertificates ---- */
IF COL_LENGTH('dbo.SSLCertificates','san')                   IS NULL ALTER TABLE dbo.SSLCertificates ADD san NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','fingerprint_sha256')    IS NULL ALTER TABLE dbo.SSLCertificates ADD fingerprint_sha256 NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','parent_id')              IS NULL ALTER TABLE dbo.SSLCertificates ADD parent_id INT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','superseded_by_id')       IS NULL ALTER TABLE dbo.SSLCertificates ADD superseded_by_id INT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','is_internal')             IS NULL ALTER TABLE dbo.SSLCertificates ADD is_internal BIT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','source')                  IS NULL ALTER TABLE dbo.SSLCertificates ADD source NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','vault_path')              IS NULL ALTER TABLE dbo.SSLCertificates ADD vault_path NVARCHAR(255) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','auto_renew')              IS NULL ALTER TABLE dbo.SSLCertificates ADD auto_renew BIT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','key_size')                IS NULL ALTER TABLE dbo.SSLCertificates ADD key_size INT NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','public_key_type')         IS NULL ALTER TABLE dbo.SSLCertificates ADD public_key_type NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','key_curve')                IS NULL ALTER TABLE dbo.SSLCertificates ADD key_curve NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','signature_hash')            IS NULL ALTER TABLE dbo.SSLCertificates ADD signature_hash NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','revocation_status')          IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_status NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','revocation_checked_at')       IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_checked_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','revocation_detail')            IS NULL ALTER TABLE dbo.SSLCertificates ADD revocation_detail NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','environment')                   IS NULL ALTER TABLE dbo.SSLCertificates ADD environment NVARCHAR(20) NULL;
GO

/* ---- domain_certificates ---- */
IF COL_LENGTH('dbo.domain_certificates','sy_team_id')        IS NULL ALTER TABLE dbo.domain_certificates ADD sy_team_id INT NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','ug_team_id')         IS NULL ALTER TABLE dbo.domain_certificates ADD ug_team_id INT NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','ug_team_name')        IS NULL ALTER TABLE dbo.domain_certificates ADD ug_team_name NVARCHAR(255) NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','servers_to_update')    IS NULL ALTER TABLE dbo.domain_certificates ADD servers_to_update NVARCHAR(500) NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','live_check_status')     IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_status NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','live_check_detail')      IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_detail NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','live_check_at')           IS NULL ALTER TABLE dbo.domain_certificates ADD live_check_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','created_at')               IS NULL ALTER TABLE dbo.domain_certificates ADD created_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','updated_at')                IS NULL ALTER TABLE dbo.domain_certificates ADD updated_at DATETIME2 NULL;
GO
IF COL_LENGTH('dbo.domain_certificates','notify_days')                IS NULL ALTER TABLE dbo.domain_certificates ADD notify_days INT NULL;
GO

/* ---- applications ---- */
IF COL_LENGTH('dbo.applications','domain_id')  IS NULL ALTER TABLE dbo.applications ADD domain_id INT NULL;
GO
IF COL_LENGTH('dbo.applications','sy_team_id') IS NULL ALTER TABLE dbo.applications ADD sy_team_id INT NULL;
GO
IF COL_LENGTH('dbo.applications','ug_team_id') IS NULL ALTER TABLE dbo.applications ADD ug_team_id INT NULL;
GO

/* ---- users ---- */
IF COL_LENGTH('dbo.users','full_name')   IS NULL ALTER TABLE dbo.users ADD full_name NVARCHAR(255) NULL;
GO
IF COL_LENGTH('dbo.users','role')         IS NULL ALTER TABLE dbo.users ADD role NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.users','auth_source')   IS NULL ALTER TABLE dbo.users ADD auth_source NVARCHAR(10) NULL;
GO
IF COL_LENGTH('dbo.users','is_active')      IS NULL ALTER TABLE dbo.users ADD is_active BIT NULL;
GO
IF COL_LENGTH('dbo.users','last_login')      IS NULL ALTER TABLE dbo.users ADD last_login DATETIME2 NULL;
GO

/* ---- AuditLog ---- */
IF COL_LENGTH('dbo.AuditLog','ip_address') IS NULL ALTER TABLE dbo.AuditLog ADD ip_address NVARCHAR(50) NULL;
GO
