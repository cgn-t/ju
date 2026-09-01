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

-- -----------------------------------------------------------------------------
-- 2026-08-28 · Dağıtım akışı (Jenkins pipeline editörü)
--   [ models.py: DeploymentFlow / DeploymentRun / DeploymentRunStep ]
-- Eski tek-job manuel Dağıtım formunun yerine geçer. Flow = uygulamaya bağlı DAG tanımı
-- (nodes+edges+params JSON). Run/RunStep = değişmez çalıştırma geçmişi (flow sonradan
-- değişse/silinse de run ETKİLENMEZ — definition_snapshot donar).
-- DeploymentRun.app_id KASITLI FK'SİZ (mail_queue.certificate_id deseni) — Application
-- (CASCADE)→Flow(SET NULL)→Run çoklu cascade yolunu MSSQL'de önlemek için.
-- Taze DB'de gerekmez (create_all kurar); bu blok mevcut prod DB içindir.
-- -----------------------------------------------------------------------------
IF OBJECT_ID('dbo.deployment_flows', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.deployment_flows (
        id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_deployment_flows PRIMARY KEY,
        app_id       INT            NOT NULL,
        name         NVARCHAR(255)  NOT NULL,
        description  NVARCHAR(MAX)  NULL,
        definition   NVARCHAR(MAX)  NOT NULL,
        created_by   NVARCHAR(100)  NULL,
        updated_by   NVARCHAR(100)  NULL,
        created_at   DATETIME       NOT NULL CONSTRAINT DF_deployment_flows_created DEFAULT (GETUTCDATE()),
        updated_at   DATETIME       NOT NULL CONSTRAINT DF_deployment_flows_updated DEFAULT (GETUTCDATE()),
        CONSTRAINT uq_deployment_flow_app_name UNIQUE (app_id, name),
        CONSTRAINT FK_deployment_flows_app FOREIGN KEY (app_id) REFERENCES dbo.applications(id) ON DELETE CASCADE
    );
    CREATE INDEX IX_deployment_flows_created ON dbo.deployment_flows(created_at);
END
GO

IF OBJECT_ID('dbo.deployment_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.deployment_runs (
        id                   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_deployment_runs PRIMARY KEY,
        flow_id              INT            NULL,
        app_id               INT            NULL,   -- FK'siz (bkz. üstteki not)
        flow_name_snapshot   NVARCHAR(255)  NOT NULL,
        definition_snapshot  NVARCHAR(MAX)  NOT NULL,
        status               NVARCHAR(20)   NOT NULL CONSTRAINT DF_deployment_runs_status DEFAULT ('pending'),
        triggered_by         NVARCHAR(100)  NULL,
        trigger_type         NVARCHAR(20)   NOT NULL CONSTRAINT DF_deployment_runs_trigger_type DEFAULT ('manual'),
        -- manual (Dağıt) | retry (tek adım yeniden dene) | rerun (geçmiş run'ı aynı parametrelerle
        -- yeniden tetikle — rollback)
        source_run_id        INT            NULL,   -- rerun'ın kaynağı olan run
        started_at           DATETIME       NULL,
        finished_at          DATETIME       NULL,
        created_at           DATETIME       NOT NULL CONSTRAINT DF_deployment_runs_created DEFAULT (GETUTCDATE()),
        CONSTRAINT FK_deployment_runs_flow FOREIGN KEY (flow_id) REFERENCES dbo.deployment_flows(id) ON DELETE SET NULL,
        CONSTRAINT FK_deployment_runs_source FOREIGN KEY (source_run_id) REFERENCES dbo.deployment_runs(id) ON DELETE SET NULL
    );
    CREATE INDEX IX_deployment_runs_status  ON dbo.deployment_runs(status);
    CREATE INDEX IX_deployment_runs_app     ON dbo.deployment_runs(app_id);
    CREATE INDEX IX_deployment_runs_created ON dbo.deployment_runs(created_at);
END
GO

IF OBJECT_ID('dbo.deployment_run_steps', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.deployment_run_steps (
        id                   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_deployment_run_steps PRIMARY KEY,
        run_id               INT            NOT NULL,
        node_id              NVARCHAR(100)  NOT NULL,
        node_label           NVARCHAR(255)  NOT NULL,
        jenkins_job          NVARCHAR(255)  NOT NULL,
        params_snapshot      NVARCHAR(MAX)  NOT NULL,
        depends_on           NVARCHAR(MAX)  NULL,
        status               NVARCHAR(20)   NOT NULL CONSTRAINT DF_deployment_run_steps_status DEFAULT ('pending'),
        jenkins_queue_url    NVARCHAR(500)  NULL,
        jenkins_build_number INT            NULL,
        started_at           DATETIME       NULL,
        finished_at          DATETIME       NULL,
        last_poll_at         DATETIME       NULL,
        error_message        NVARCHAR(1000) NULL,
        created_at           DATETIME       NOT NULL CONSTRAINT DF_deployment_run_steps_created DEFAULT (GETUTCDATE()),
        CONSTRAINT uq_run_step_node UNIQUE (run_id, node_id),
        CONSTRAINT FK_deployment_run_steps_run FOREIGN KEY (run_id) REFERENCES dbo.deployment_runs(id) ON DELETE CASCADE
    );
    CREATE INDEX IX_deployment_run_steps_status ON dbo.deployment_run_steps(status);
END
GO

-- -----------------------------------------------------------------------------
-- 2026-09-01 · Otomatik CA sertifika alımı (issuance)
--   [ models.py: IssuanceProfile / IssuanceRequest, Domain additive kolonları ]
-- Faz A: Vault PKI sign_csr + onay-kapılı (opsiyonel zero-touch, domain bazlı).
-- ŞEMADA private_key KOLONU YOK — özel anahtar velayeti JUMBO dışında kalır; csr_pem
-- yalnız PEM metin (public key + kimlik), sır İÇERMEZ. previous_request_id self-FK
-- ondelete YOK (SSLCertificates.parent_id ile aynı MSSQL self-ref kısıtı).
-- Taze DB'de gerekmez (create_all kurar); bu blok mevcut prod DB içindir.
--
-- DDL GEREKTİRMEYEN ayarlar (app_settings satırı, Ayarlar → CA Profilleri/Erişim):
--   • issuance.enabled (bool, false)              — global kill-switch
--   • issuance.default_profile_id (int, null)     — domain'de seçili değilse düşülecek profil
--   • issuance.default_renew_before_days (int, 30)
--   • issuance.schedule_hour (int, 6)              — scan-expiring-for-issuance cron saati
--   • access.issuance_all_roles (bool, false)      — Sertifika Talepleri sayfa görünürlüğü
-- -----------------------------------------------------------------------------
IF OBJECT_ID('dbo.issuance_profiles', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.issuance_profiles (
        id                  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_issuance_profiles PRIMARY KEY,
        name                NVARCHAR(255)  NOT NULL,
        ca_type             NVARCHAR(20)   NOT NULL,   -- vault_pki | acme (adcs ileride, ayrı plan)
        enabled             BIT            NOT NULL CONSTRAINT DF_issuance_profiles_enabled DEFAULT (0),
        vault_mount         NVARCHAR(100)  NULL,
        vault_role          NVARCHAR(100)  NULL,
        acme_directory_url  NVARCHAR(500)  NULL,
        acme_account_key    NVARCHAR(MAX)  NULL,   -- Fernet şifreli (JWK)
        eab_kid             NVARCHAR(255)  NULL,
        eab_hmac_key        NVARCHAR(MAX)  NULL,   -- Fernet şifreli
        proxy_url           NVARCHAR(255)  NULL,
        timeout_seconds     INT            NOT NULL CONSTRAINT DF_issuance_profiles_timeout DEFAULT (15),
        allow_key_return    BIT            NOT NULL CONSTRAINT DF_issuance_profiles_keyret  DEFAULT (0),
        created_by          NVARCHAR(100)  NULL,
        created_at          DATETIME       NOT NULL CONSTRAINT DF_issuance_profiles_created DEFAULT (GETUTCDATE()),
        updated_at          DATETIME       NOT NULL CONSTRAINT DF_issuance_profiles_updated DEFAULT (GETUTCDATE()),
        CONSTRAINT uq_issuance_profiles_name UNIQUE (name)
    );
END
GO

IF OBJECT_ID('dbo.issuance_requests', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.issuance_requests (
        id                   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_issuance_requests PRIMARY KEY,
        domain_id            INT            NOT NULL,
        profile_id           INT            NOT NULL,
        sy_team_id           INT            NULL,
        status               NVARCHAR(20)   NOT NULL CONSTRAINT DF_issuance_requests_status  DEFAULT ('pending_approval'),
        -- pending_approval | approved | submitted | polling | issued | failed | rejected | cancelled | expired
        method               NVARCHAR(20)   NOT NULL,   -- csr_sign | issue | acme
        common_name          NVARCHAR(255)  NOT NULL,
        sans                 NVARCHAR(MAX)  NULL,        -- JSON liste
        csr_pem              NVARCHAR(MAX)  NULL,        -- PEM metin; private key İÇERMEZ
        requested_ttl_hours  INT            NULL,
        previous_request_id  INT            NULL,        -- self-FK, ondelete YOK (bkz. üstteki not)
        challenge_type       NVARCHAR(10)   NULL,        -- http-01 | dns-01 (yalnız ACME)
        external_order_url   NVARCHAR(500)  NULL,
        attempt_count        INT            NOT NULL CONSTRAINT DF_issuance_requests_attempts DEFAULT (0),
        last_error           NVARCHAR(MAX)  NULL,
        last_polled_at       DATETIME       NULL,
        result_cert_id       INT            NULL,
        [trigger]            NVARCHAR(20)   NOT NULL CONSTRAINT DF_issuance_requests_trigger DEFAULT ('manual'),
        -- scheduled_renewal | manual | zero_touch
        zero_touch           BIT            NOT NULL CONSTRAINT DF_issuance_requests_zt DEFAULT (0),
        created_by           NVARCHAR(100)  NULL,
        created_at           DATETIME       NOT NULL CONSTRAINT DF_issuance_requests_created DEFAULT (GETUTCDATE()),
        decided_by           NVARCHAR(100)  NULL,
        decided_at           DATETIME       NULL,
        submitted_at         DATETIME       NULL,
        finished_at          DATETIME       NULL,
        note                 NVARCHAR(MAX)  NULL,
        CONSTRAINT FK_issuance_requests_domain   FOREIGN KEY (domain_id)           REFERENCES dbo.domain_certificates(id),
        CONSTRAINT FK_issuance_requests_profile  FOREIGN KEY (profile_id)          REFERENCES dbo.issuance_profiles(id),
        CONSTRAINT FK_issuance_requests_team     FOREIGN KEY (sy_team_id)          REFERENCES dbo.teams(id),
        CONSTRAINT FK_issuance_requests_prev     FOREIGN KEY (previous_request_id) REFERENCES dbo.issuance_requests(id),
        CONSTRAINT FK_issuance_requests_cert     FOREIGN KEY (result_cert_id)      REFERENCES dbo.[SSLCertificates]([ID]) ON DELETE SET NULL
    );
    CREATE INDEX IX_issuance_requests_domain   ON dbo.issuance_requests(domain_id);
    CREATE INDEX IX_issuance_requests_profile  ON dbo.issuance_requests(profile_id);
    CREATE INDEX IX_issuance_requests_team     ON dbo.issuance_requests(sy_team_id);
    CREATE INDEX IX_issuance_requests_status   ON dbo.issuance_requests(status);
    CREATE INDEX IX_issuance_requests_prev     ON dbo.issuance_requests(previous_request_id);
    CREATE INDEX IX_issuance_requests_cert     ON dbo.issuance_requests(result_cert_id);
    CREATE INDEX IX_issuance_requests_created  ON dbo.issuance_requests(created_at);
END
GO

IF COL_LENGTH('dbo.domain_certificates', 'issuance_profile_id') IS NULL
    ALTER TABLE dbo.domain_certificates ADD issuance_profile_id INT NULL
        CONSTRAINT FK_domain_issuance_profile FOREIGN KEY REFERENCES dbo.issuance_profiles(id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_domain_issuance_profile'
               AND object_id = OBJECT_ID('dbo.domain_certificates'))
    CREATE INDEX IX_domain_issuance_profile ON dbo.domain_certificates(issuance_profile_id);
GO
IF COL_LENGTH('dbo.domain_certificates', 'auto_issuance_enabled') IS NULL
    ALTER TABLE dbo.domain_certificates ADD auto_issuance_enabled BIT NOT NULL
        CONSTRAINT DF_domain_auto_issuance DEFAULT (0);
GO
IF COL_LENGTH('dbo.domain_certificates', 'issuance_zero_touch') IS NULL
    ALTER TABLE dbo.domain_certificates ADD issuance_zero_touch BIT NOT NULL
        CONSTRAINT DF_domain_issuance_zt DEFAULT (0);
GO
IF COL_LENGTH('dbo.domain_certificates', 'issuance_renew_before_days') IS NULL
    ALTER TABLE dbo.domain_certificates ADD issuance_renew_before_days INT NULL;
GO
