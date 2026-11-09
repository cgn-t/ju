-- v3.9.39 Sertifikalara Standart Ad kolonu (kolon adı v3.9.40'ta İngilizce standarda göre StandardName oldu)
-- Nerede çalıştırılır: Jumbo > İşlemler > Veritabanı Değişiklikleri (yalnız admin, DB_CONSOLE=1).
-- Ne yapar: SSLCertificates tablosuna boş olabilen tek bir kolon ekler. NAME ve diğer kolonlara,
--           mevcut verilere dokunmaz. Kolon zaten varsa hiçbir şey yapmaz (tekrar çalıştırmak güvenli).
--           Betiğin eski hâli bir ortamda çalıştırılıp StandartAd kolonu açılmışsa, kolon verisiyle
--           birlikte StandardName adına çevrilir.
-- Sonra:   Standart Ad özelliği açılır. Mevcut sertifikalara ad vermek için
--           SSL Sertifikaları > "İsimlendirme Kuralını Uygula — Toplu" ekranı kullanılır.
IF COL_LENGTH('dbo.SSLCertificates', 'StandartAd') IS NOT NULL
   AND COL_LENGTH('dbo.SSLCertificates', 'StandardName') IS NULL
    EXEC sp_rename 'dbo.SSLCertificates.StandartAd', 'StandardName', 'COLUMN';
IF COL_LENGTH('dbo.SSLCertificates', 'StandardName') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD StandardName NVARCHAR(255) NULL;
