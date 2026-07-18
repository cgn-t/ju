-- =============================================================================
-- JUMBO — schema-NEW.sql   (schema-OLD.sql SONRASI değişiklikler)
-- Baseline: schema-OLD.sql. Bundan sonra oluşturulan tablo/kolonları, prod'a
-- uygulandıkça buraya ekleyin (idempotent bloklar hâlinde). Taze DB'de gerekmez:
-- uygulama açılışta Base.metadata.create_all ile yeni tabloları zaten kurar.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 2026-07-18 · SMTP gönderim kuyruğu (outbox)  [ models.py: MailQueue ]
-- smtp.queue_enabled iken mailler doğrudan gönderilmez; buraya yazılır ve
-- 'mail-queue-drain' job'ı queue_batch_size/queue_interval_minutes'e uyarak gönderir.
-- (certificate_id FK'siz — discovered_certificates deseni; MSSQL çoklu-yol cascade'inden kaçınma.)
-- -----------------------------------------------------------------------------
IF OBJECT_ID('dbo.mail_queue', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.mail_queue (
        id             INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_mail_queue PRIMARY KEY,
        to_addresses   NVARCHAR(1000) NOT NULL,
        subject        NVARCHAR(500)  NOT NULL,
        body_text      NVARCHAR(MAX)  NOT NULL,
        body_html      NVARCHAR(MAX)  NULL,
        certificate_id INT            NULL,
        stakeholder    NVARCHAR(255)  NULL,
        days_left      INT            NULL,
        status         NVARCHAR(20)   NOT NULL CONSTRAINT DF_mail_queue_status   DEFAULT ('pending'),  -- pending|sent|failed
        attempts       INT            NOT NULL CONSTRAINT DF_mail_queue_attempts DEFAULT (0),
        last_error     NVARCHAR(1000) NULL,
        created_at     DATETIME       NOT NULL CONSTRAINT DF_mail_queue_created  DEFAULT (GETUTCDATE()),
        sent_at        DATETIME       NULL
    );
    CREATE INDEX IX_mail_queue_status  ON dbo.mail_queue(status);
    CREATE INDEX IX_mail_queue_created ON dbo.mail_queue(created_at);
    CREATE INDEX IX_mail_queue_cert    ON dbo.mail_queue(certificate_id);
END
GO

-- Not: Yeni SMTP AYARLARI (resend_interval_days, fallback_address, doc_links,
-- queue_enabled, queue_batch_size, queue_interval_minutes) DDL gerektirmez —
-- app_settings tablosuna satır olarak, Ayarlar → E-posta kaydedildiğinde yazılır;
-- kayıt yoksa uygulama DEFAULTS'tan okur.
