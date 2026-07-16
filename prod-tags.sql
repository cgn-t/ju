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
