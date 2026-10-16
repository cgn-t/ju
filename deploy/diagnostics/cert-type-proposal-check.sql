-- =====================================================================================
-- Teşhis: farklı tipteki sertifikalar arasında (root/intermediate → leaf) devir önerileri
-- Yalnız SELECT — veriye dokunmaz. MSSQL (prod şema adları).
--
-- transfer_proposals.via değerleri (önerinin üretildiği yol):
--   live-check   = Canlı doğrulama        import       = İçe aktarma
--   vault-sync   = Vault senkron          import-chain = Canlı zincir
--   attach       = Elle eşleme            manual       = Elle devral
--   backfill     = Geçiş (uygulama her açılışta yarım kalan devirleri tamamlar)
-- =====================================================================================


-- Q0) CertType dağılımı — boş / beklenmeyen değer var mı?
SELECT CertType, COUNT(*) AS adet
FROM SSLCertificates
GROUP BY CertType;


-- Q1) Tipler arası devir önerileri — via kolonu önerinin hangi yoldan geldiğini gösterir
SELECT p.id, p.status, p.via, p.created_by, p.created_at,
       o.ID AS old_id, o.NAME AS old_name, o.CertType AS old_type,
       n.ID AS new_id, n.NAME AS new_name, n.CertType AS new_type,
       d.domain
FROM transfer_proposals p
JOIN SSLCertificates o ON o.ID = p.old_cert_id
JOIN SSLCertificates n ON n.ID = p.new_cert_id
LEFT JOIN domain_certificates d ON d.id = p.domain_id
WHERE LOWER(LTRIM(RTRIM(o.CertType))) <> LOWER(LTRIM(RTRIM(n.CertType)))
ORDER BY p.created_at DESC;


-- Q2) Kendinden imzalı (root olması gereken) ama CertType'ı 'root' olmayan sertifikalar
SELECT ID, NAME, CertType, Subject, Issuer
FROM SSLCertificates
WHERE Subject = Issuer
  AND LOWER(LTRIM(RTRIM(CertType))) <> 'root';


-- Q3) "Yerine geçti" (superseded_by_id) bağı farklı tipe işaret edenler — "Geçiş" önerilerinin kaynağı
SELECT o.ID, o.NAME, o.CertType, o.IsActive,
       n.ID AS new_id, n.NAME AS new_name, n.CertType AS new_type
FROM SSLCertificates o
JOIN SSLCertificates n ON n.ID = o.superseded_by_id
WHERE LOWER(LTRIM(RTRIM(o.CertType))) <> LOWER(LTRIM(RTRIM(n.CertType)));


-- Q4) CertType değerinde gizli karakter var mı? (SQL LTRIM/RTRIM yalnız boşluğu siler; satır sonu/tab
--     kalırsa SQL filtresi kaydı 'leaf' sayar, Python tarafı ise doğru okur → tipler arası öneri)
--     Beklenen uzunluk: Root=4, Leaf=4, Intermediate=12. Daha uzunsa ve hex şu değerlerle bitiyorsa gizli karakter var:
--     0D00 = satır başı (CR)   0A00 = satır sonu (LF)   0900 = tab   A000 = bölünmez boşluk (NBSP)
SELECT CertType, LEN(CertType) AS uzunluk,
       CAST(CertType AS VARBINARY(64)) AS hex, COUNT(*) AS adet
FROM SSLCertificates
GROUP BY CertType, LEN(CertType), CAST(CertType AS VARBINARY(64));


-- Q5) İlgili sertifikalar: kim, ne zaman, hangi kaynakla ekledi
--     (JUMBO CertType'ı küçük harfle yazar; büyük harfli "Leaf"/"Root" dış kaynaktan eklenmiş olabilir)
SELECT ID, NAME, CertType, source, CertificateCreator, CreatedDate, ModifiedDate,
       fingerprint_sha256, superseded_by_id, IsActive
FROM SSLCertificates
WHERE ID IN (7, 8, 13, 36, 110, 113, 117);


-- Q6) Onaylanmış/uygulanmış öneriler + attach önerilerinin eşleme tipi (server/client)
SELECT id, status, via, mapping_type, kind, old_cert_id, new_cert_id, domain_id,
       created_by, created_at, decided_by, decided_at, applied_at, note
FROM transfer_proposals
WHERE id IN (160, 161, 177) OR status IN ('approved', 'applied')
ORDER BY created_at;


-- Q7) Audit Log: bu sertifikalarla ilgili öneri / onay / devir kayıtları (en eski önce)
SELECT ID, Username, Action, TableName, RecordID, CreatedAt,
       CAST(Details AS NVARCHAR(MAX)) AS Details
FROM AuditLog
WHERE Action IN ('propose', 'approve', 'supersede_apply', 'live_check_run', 'import', 'update')
  AND (RecordID IN ('7', '8', '13', '36', '110', '113', '117')
       OR CAST(Details AS NVARCHAR(MAX)) LIKE '%akbank%'
       OR CAST(Details AS NVARCHAR(MAX)) LIKE '%akportfoy%')
ORDER BY CreatedAt;
