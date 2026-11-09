# Veritabanı değişiklikleri

v3.9.38'den itibaren Jumbo yeni kolon ya da tabloyu pod açılışında kendisi **eklemez**.
Her sürümün DB değişikliği bu klasörde bir `.sql` dosyası olarak gelir.

Nasıl uygulanır:

1. Jumbo'da **İşlemler > Veritabanı Değişiklikleri** sayfasını açın (yalnız admin; ortamda
   `DB_CONSOLE=1` tanımlı olmalı).
2. İlgili dosyanın içeriğini kopyalayıp sayfaya yapıştırın, "Değişiklik adı"na dosya adını yazın.
3. Önce **Dene (geri al)** ile çalıştırın: sonuç gösterilir, hiçbir şey kalıcı olmaz.
4. Sonuç doğruysa **Çalıştır…** deyin. SQL tek işlem olarak çalışır; hata olursa hiçbir şey değişmez.
5. Sağdaki "Bekleyen uygulama değişiklikleri" kutusunda satır "Uygulandı" olur, bağlı özellik açılır.

Dosyalar tekrar çalıştırılsa da zarar vermeyecek şekilde yazılır (`IF COL_LENGTH(...) IS NULL`).
`-geri-al.sql` ile biten dosyalar değişikliği geri alır; yalnız gerçekten gerekiyorsa ve yedekten
sonra kullanın.

| Sürüm | Dosya | Ne yapar |
|---|---|---|
| v3.9.39 | `v3.9.39-standart-ad.sql` | `SSLCertificates.StandardName NVARCHAR(255) NULL` kolonu (Standart Ad) |
