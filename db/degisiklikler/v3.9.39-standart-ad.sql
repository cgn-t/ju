-- v3.9.39 Sertifikalara Standart Ad kolonu
-- Nerede çalıştırılır: Jumbo > İşlemler > Veritabanı Değişiklikleri (yalnız admin, DB_CONSOLE=1).
-- Ne yapar: SSLCertificates tablosuna boş olabilen tek bir kolon ekler. NAME ve diğer kolonlara,
--           mevcut verilere dokunmaz. Kolon zaten varsa hiçbir şey yapmaz (tekrar çalıştırmak güvenli).
-- Sonra:   Standart Ad özelliği açılır. Mevcut sertifikalara ad vermek için
--           SSL Sertifikaları > "İsimlendirme Kuralını Uygula — Toplu" ekranı kullanılır.
IF COL_LENGTH('dbo.SSLCertificates', 'StandartAd') IS NULL
    ALTER TABLE dbo.SSLCertificates ADD StandartAd NVARCHAR(255) NULL;
