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

-- -----------------------------------------------------------------------------
-- 2026-08-04 · Domain başına süre-uyarı gün sayısı  [ models.py: Domain.notify_days ]
-- Bir domain, sertifika bitişine kaç gün kala mail gönderileceğini kendi seçebilir.
-- NULL = Ayarlar'daki global smtp.expiry_warning_days (varsayılan 30) kullanılır.
-- -----------------------------------------------------------------------------
IF COL_LENGTH('dbo.domain_certificates', 'notify_days') IS NULL
    ALTER TABLE dbo.domain_certificates ADD notify_days INT NULL;
GO

-- -----------------------------------------------------------------------------
-- 2026-08-04 · Uygulama TRUST STORE  [ models.py: ApplicationTrustedCert ]
-- Bir uygulamanın güvendiği (trusted) sertifikalar — CA/peer doğrulama çıpası. Çoklu
-- olabilir (uq_app_trusted app_id+cert_id). app_dependencies deseni: app_id CASCADE,
-- cert_id SET NULL (farklı tablolar → MSSQL çoklu-yol cascade sorunu yok).
-- Taze DB'de create_all zaten kurar; bu blok mevcut prod DB içindir.
-- -----------------------------------------------------------------------------
IF OBJECT_ID('dbo.app_trusted_certs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.app_trusted_certs (
        id         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_app_trusted_certs PRIMARY KEY,
        app_id     INT           NOT NULL,
        cert_id    INT           NULL,
        note       NVARCHAR(500) NULL,
        created_at DATETIME      NOT NULL CONSTRAINT DF_app_trusted_created DEFAULT (GETUTCDATE()),
        CONSTRAINT uq_app_trusted UNIQUE (app_id, cert_id),
        CONSTRAINT FK_app_trusted_app  FOREIGN KEY (app_id)  REFERENCES dbo.applications(id)     ON DELETE CASCADE,
        CONSTRAINT FK_app_trusted_cert FOREIGN KEY (cert_id) REFERENCES dbo.[SSLCertificates]([ID]) ON DELETE SET NULL
    );
    CREATE INDEX IX_app_trusted_cert ON dbo.app_trusted_certs(cert_id);
END
GO

-- -----------------------------------------------------------------------------
-- 2026-08-04 · Halef 'trusted ekle' onayı  [ TransferProposal.kind / app_id ]
-- trusted_add = yeni (halef) sertifikayı bir uygulamanın trust store'una EKLEME onayı;
-- devir DEĞİL (eski trusted korunur). app_id = hedef uygulama.
-- -----------------------------------------------------------------------------
IF COL_LENGTH('dbo.transfer_proposals', 'app_id') IS NULL
    ALTER TABLE dbo.transfer_proposals ADD app_id INT NULL;
GO
IF COL_LENGTH('dbo.transfer_proposals', 'kind') IS NULL
    ALTER TABLE dbo.transfer_proposals ADD kind NVARCHAR(20) NOT NULL
        CONSTRAINT DF_transfer_proposals_kind DEFAULT ('transfer');
GO
-- Grain (uq_proposal_grain_open) app_id boyutunu da içermeli: aynı old/new için FARKLI
-- uygulamalara trusted_add önerileri çakışmasın. Mevcut filtreli unique index yeniden kurulur.
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'uq_proposal_grain_open'
           AND object_id = OBJECT_ID('dbo.transfer_proposals'))
    DROP INDEX uq_proposal_grain_open ON dbo.transfer_proposals;
GO
CREATE UNIQUE INDEX uq_proposal_grain_open ON dbo.transfer_proposals
    (old_cert_id, new_cert_id, domain_id, mapping_type, app_dependency_id, app_id)
    WHERE status IN ('pending','approved');
GO

-- -----------------------------------------------------------------------------
-- 2026-08-25 · E-posta ayarları (DDL YOK) + Devir-onayı hatırlatması
-- Aşağıdaki SMTP ayarları app_settings'e SATIR olarak yazılır (Ayarlar → E-posta);
-- şema DEĞİŞMEZ. Kayıt yoksa uygulama DEFAULTS'tan okur (settings_service.py).
--   • resend_dedup_enabled (bool)          — süre-uyarısı tekrar-önlemeyi aç/kapa
--   • resend_interval_hours (int, 3)       — tekrar aralığı SAAT (eski resend_interval_days yerine)
--   • auto_proposal_reminder_enabled (bool)— bekleyen devir önerileri günlük hatırlatması aç/kapa
--   • proposal_reminder_hour (int 0-23, 9) — zamanlanmış hatırlatma saati
-- Devir-onayı hatırlatması yalnız MEVCUT tabloları kullanır (transfer_proposals, teams,
-- notifications, mail_queue) → yeni tablo/kolon YOK. Server-bound pasife-alma kuralı ve
-- 6 devir bug fix'i de yalnız mevcut kolonlarla çalışır (superseded_by_id baseline'da var).
-- -----------------------------------------------------------------------------

-- -----------------------------------------------------------------------------
-- 2026-08-27 · Sertifika ortam etiketi (prod/test)  [ models.py: Certificate.environment ]
-- Nullable, backfill YOK — otomatik yollar (vault-sync/keşif/mevcut prod verisi) bilemez;
-- yalnız manuel ekleme/içe aktarma formunda UI zorunlu kılar, DB seviyesinde zorunlu DEĞİL.
-- -----------------------------------------------------------------------------
IF COL_LENGTH('dbo.SSLCertificates', 'environment') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD environment NVARCHAR(20) NULL;
GO

-- -----------------------------------------------------------------------------
-- 2026-08-27 · Sayfa erişim kontrolü (DDL YOK)  [ settings_service.py: DEFAULTS["access"] ]
-- Uyum/Devir Önerisi/Keşif/Dağıtım sayfa görünürlüğü app_settings'e SATIR olarak yazılır
-- (Ayarlar → Erişim); şema DEĞİŞMEZ. Varsayılan hepsi false (admin+allviewer-only).
--   • policy_all_roles / proposals_all_roles / discovery_all_roles / deployments_all_roles (bool)
-- -----------------------------------------------------------------------------
