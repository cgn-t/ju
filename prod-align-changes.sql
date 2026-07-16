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
