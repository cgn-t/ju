-- -----------------------------------------------------------------------------
-- schema-bugfix.sql — prod'da "Invalid column name 'fingerprint_sha256'" /
-- "Invalid column name 'is_internal'" hatasının acil düzeltmesi.
-- schema-OLD.sql'in bu iki kolonu ekleyen satırlarının (idempotent) tekrarıdır;
-- prod'da script kısmi çalıştığı için bu iki kolon eksik kalmış olabilir.
-- Çalıştırdıktan sonra schema-OLD.sql'i BAŞTAN SONA tekrar çalıştırın.
-- -----------------------------------------------------------------------------
IF COL_LENGTH('dbo.SSLCertificates','fingerprint_sha256') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD fingerprint_sha256 NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.SSLCertificates','is_internal') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD is_internal BIT NULL;
GO
