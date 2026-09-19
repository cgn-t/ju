-- -----------------------------------------------------------------------------
-- 2026-09-19 · Mail Gönderim Geçmişi: gerçek kuyruk/teslim zaman çizelgesi
--   [ models.py: Notification.mail_queue_id ]
--
-- NEDEN: queue_enabled açıkken JUMBO bir maili kuyruğa koyduğu ANDA notifications
-- tablosuna "gönderildi" diye sabit bir kayıt yazıyordu — drain job sonradan bu maili
-- göndermeyi 5 kez deneyip GERÇEKTEN başarısız olsa bile admin ekranında hep "Gönderildi"
-- görünüyordu (yanlış). mail_queue_id, hangi notifications satırının hangi mail_queue
-- satırına karşılık geldiğini bağlar; admin ekranı artık GERÇEK durumu (sent/pending/
-- failed) ve GERÇEK zaman çizelgesini (kuyruğa alınma vs. gerçek teslim) gösterebiliyor.
--
-- FK YOK — mail_queue.certificate_id/domain_id ile aynı desen (MSSQL çoklu-yol
-- cascade'inden kaçınma). İdempotenttir — tekrar çalıştırmak güvenlidir.
--
-- Bu blok ayrıca schema-NEW.sql'in sonuna eklenmiştir (bir sonraki schema-OLD.sql
-- baseline birleştirmesinde oraya taşınacaktır); bu dosya yalnız DBA'ya AYRI, hızlı bir
-- betik olarak vermek içindir (schema-bugfix.sql ile aynı amaç).
-- -----------------------------------------------------------------------------

IF OBJECT_ID('dbo.notifications', 'U') IS NOT NULL
   AND COL_LENGTH('dbo.notifications', 'mail_queue_id') IS NULL
    ALTER TABLE dbo.notifications ADD mail_queue_id INT NULL;
GO
IF OBJECT_ID('dbo.notifications', 'U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_notifications_mail_queue_id'
                   AND object_id = OBJECT_ID('dbo.notifications'))
    CREATE INDEX ix_notifications_mail_queue_id ON dbo.notifications(mail_queue_id);
GO
