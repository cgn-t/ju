-- v3.9.39 GERİ ALMA: Standart Ad kolonunu kaldırır (kolondaki adlar SİLİNİR).
-- Yalnız Standart Ad özelliğinden tamamen vazgeçilirse çalıştırın. Önce DB yedeği alın.
-- Sayfa, DROP içerdiği için onay olarak UYGULA yazmanızı ister.
IF COL_LENGTH('dbo.SSLCertificates', 'StandartAd') IS NOT NULL
    ALTER TABLE dbo.SSLCertificates DROP COLUMN StandartAd;
