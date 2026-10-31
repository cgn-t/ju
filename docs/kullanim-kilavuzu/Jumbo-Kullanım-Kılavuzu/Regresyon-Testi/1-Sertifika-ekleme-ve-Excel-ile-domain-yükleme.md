Regresyon Test Kılavuzu, Bölüm 1, madde 1. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Yönetici hesabıyla. Dosyalar `sertifikalar/dosyalar/` klasöründe. Her dosya için: SSL Sertifikaları > **Yeni Ekle** > "Dosyadan İçe Aktar" sekmesi, dosyayı seçin, **Oluşturan Ekip** = Ödeme Sistemleri SY (aksi yazılmadıkça), **Ortam** = Test. Önizlemede her sertifikanın yanında "Yeni" ya da "Zaten kayıtlı" yazar.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 1.1 | `00-kok-ve-ara-sertifika.pem` yükleyin | Önizlemede 2 sertifika: Jumbo Test Kök SM ve Jumbo Test Ara SM, ikisi de "Yeni". Ara sertifikanın "Üst Sertifika" sütununda "Jumbo Test Kök SM (bu dosyada)" yazar. Kaydedince "2 sertifika eklendi". Listede ara sertifika kökün altında görünür |
| 1.2 | `01-tek-sertifika.pem` (Windows satır sonlu) | `tek-sertifika.jumbo-test.local` eklenir, listede ara sertifikanın altında durur |
| 1.3 | Aynı `01` dosyasını tekrar yükleyin | Önizlemede "Zaten kayıtlı". Kaydetmeye çalışırsanız "Dosyadaki tüm sertifikalar zaten kayıtlı". Listede kopya oluşmaz |
| 1.4 | `02-tam-zincir-ters-sira-anahtarli.pem` (kök, ara, sertifika ve özel anahtar ters sırada) | Önizlemede 3 sertifika; kök ve ara "Zaten kayıtlı", `tam-zincir.jumbo-test.local` "Yeni". Özel anahtar için hata çıkmaz, anahtar kaydedilmez |
| 1.5 | `03-der-bicimi.cer` | `der-bicimi.jumbo-test.local` eklenir |
| 1.6 | `04-p7b-paketi.p7b` (dosya seçicide .p7b dosyası görünmeli) | Ara sertifika "Zaten kayıtlı", `p7b-paketi.jumbo-test.local` "Yeni" |
| 1.7 | `05-parolali-pfx.pfx`: önce parolasız, sonra "PFX Parolası" alanına `yanlis`, sonra `Jumbo2026!` | Sırayla: "Bu PFX dosyası parola korumalı. PFX parolasını girin." / "PFX parolası hatalı. Parolayı kontrol edip yeniden deneyin." / önizleme gelir ve `parolali-pfx.jumbo-test.local` eklenir |
| 1.8 | `06-notepad-unicode-kayit.pem` (Notepad'de "Unicode" kaydedilmiş) | `notepad-unicode.jumbo-test.local` eklenir |
| 1.9 | `07-yalniz-ozel-anahtar.key` ve `08-ilgisiz-dosya.txt` | İkisinde de kırmızı mesaj: "Dosya formatı tanınamadı. PEM, DER, P7B veya PFX/P12 yükleyin (PFX için parola gerekebilir)." Hiçbir şey eklenmez |
| 1.10 | `09-cn-siz-ec-sertifika.pem` (adı yalnız alternatif adlarda) | Ad boş kalmaz: `cn-siz-ec.jumbo-test.local` görünür. Detayda anahtar EC türü |
| 1.11 | `10-trusted-20-gun-kala.pem`, `11-trusted-suresi-gecmis.pem` yükleyin. Sonra `12-sahipsiz-20-gun-kala.pem` dosyasını **Oluşturan Ekip = Mailsiz Test SY** ile yükleyin | Üçü de eklenir. Listede `10` ve `12` yaklaşık 19–20 gün kaldı (turuncu), `11` süresi dolmuş (kırmızı) görünür. Bunlar 3. ve 4. bölümde kullanılır |
| 1.12 | `tek-sertifika.jumbo-test.local` detayını açın, Notlar'a `Ödeme ğüşıöçİ notu` yazıp kaydedin, sayfayı yenileyip tekrar açın | Türkçe harfler bozulmadan durur |
| 1.13 | Domainler > **Şablon İndir** | Başlıkları ve örnek satırı olan bir Excel iner |
| 1.14 | Domainler > **Excel Yükle** > `13-domain-yukleme.xlsx` | **v3.8.4:** "3 domain eklendi, 1 atlandı, 1 hatalı satır". `excel-bir` Ödeme Sistemleri SY'ye, `excel-iki` İletişim Kanalları SY'ye bağlı; detayda "Türkçe not: ğüşıöçİ" bozulmamış. Ayrıca `excel-uc` eklenir ve Ayarlar > Ekipler'de e-postasız yeni bir "ODEME SISTEMLERI SY" ekibi oluşur (bu sürümde bilinen davranış). **v3.8.5:** "2 domain eklendi"; ekranda kapatılana kadar kalan bir uyarı "Satır 6 (excel-uc.jumbo-test.local): 'ODEME SISTEMLERI SY' adlı SY ekibi bulunamadı. Domain eklenmedi; ekibi Ayarlar > Ekipler'de oluşturun ya da adını düzeltin." Yeni ekip oluşmaz |
| 1.15 | Aynı Excel'i tekrar yükleyin | Yeni domain eklenmez; büyük harfli `EXCEL-BIR` satırı dahil var olanlar "atlandı" sayılır. Domainler listesinde kopya yoktur |
| 1.16 | Domainler arama kutusuna sırayla `ILETISIM`, `iletisim`, `İletişim` yazın (canlıdaki gibi MSSQL'li test ortamında) | Üçünde de `excel-iki.jumbo-test.local` bulunur (Dış Firma alanındaki "İletişim Hizmetleri A.Ş." ile eşleşir) |
