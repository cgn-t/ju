Regresyon Test Kılavuzu, Bölüm 2, madde 9. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın. Jumbo'daki **Regresyon Testi** sayfasında bu adımlar "Uygulamalar, trust store, sertifika yönetimi, uyum ve iptal" bölümünde **B2-9.1**, **B2-9.2** … kimlikleriyle listelenir.

Bu bölüm Bölüm 1'de yüklenen `tek-sertifika.jumbo-test.local` (Oluşturan Ekip Ödeme Sistemleri SY) ile yapılır. Listede yoksa `01-tek-sertifika.pem` dosyasını Oluşturan Ekip = Ödeme Sistemleri SY, Ortam = Test ile yükleyin. Sertifika detayını SSL Sertifikaları listesinde satırın göz simgesiyle açın; düzenleme detayın sağ üstündeki kalem simgesiyle yapılır. Kaydet'e basınca "Kaydetmeden Önce Kontrol Edin" penceresi gelir, **Onaylıyorum** ile kaydedilir.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 9.1 | Yönetici hesabıyla `tek-sertifika` detayı > kalem. Notlar = `Regresyon notu: ğüşıöçİ`, Satın Alım Yapan = `Ayşe`. Kaydet > Onaylıyorum | Detayda iki alan da yazıldığı gibi, Türkçe harfler bozulmadan görünür |
| 9.2 | İletişim editörü ile aynı sertifikanın Notlar'ını değiştirip kaydedin | Kırmızı mesaj "Bu sertifika başka bir ekibe ait; yalnız o ekibin editörü veya admin düzenleyebilir". Not değişmez |
| 9.3 | Ödeme editörü ile aynı değişikliği yapın | Kaydedilir |
| 9.4 | Ödeme editörü ile SSL Sertifikaları listesine bakın | İşlemler sütununda yalnız göz simgesi vardır. Pasife Al ve Sil simgeleri yoktur (bunlar yalnız yöneticidedir) |
| 9.5 | Yönetici hesabıyla, `localhost:9441`'e bağlı `localhost` sertifikasının satırında Pasife Al (turuncu duraklat simgesi) > Pasife Al | Kırmızı mesaj "Bu sertifika şu domain(ler)e SERVER olarak bağlı: localhost:9441. Pasife almadan önce server bağlantısını Değişiklik Talebi ile yeni sertifikaya taşıyın." Sertifika aktif kalır |
| 9.6 | `tek-sertifika` satırında Pasife Al > "Sertifikayı Pasife Al" penceresinde Pasife Al | "Sertifika pasife alındı." Sertifika listeden çıkar. "Pasifleri göster" açılınca yeniden görünür ve satırında yeşil Aktifleştir simgesi vardır. Bu işlem için kimseye mail gitmez (A kutusuna yeni mail gelmez) |
| 9.7 | "Pasifleri göster" açıkken aynı satırda Aktifleştir (yeşil oynat simgesi) | Sertifika yeniden aktif olur; anahtar kapatılınca listede görünür |
| 9.8 | `tek-sertifika` satırında Sil (kırmızı çöp kutusu) > "Sertifikayı Kalıcı Sil" penceresinde Kalıcı Sil | Sertifika "Pasifleri göster" açık olsa da listede yoktur |
| 9.9 | `01-tek-sertifika.pem` dosyasını tekrar yükleyin (Oluşturan Ekip = Ödeme Sistemleri SY, Ortam = Test) | Önizlemede "Yeni" yazar ve sertifika yeniden eklenir. Notlar boştur (silinen kayıt geri gelmez) |
| 9.10 | Uygulamalar > Ödeme API düzenle. Etiketler kutusunda listeden **Yüksek**'i seçin. Sonra Yeni etiket kategorisi = Ürün iken kutuya `Kart Ödemeleri` yazıp Enter. Kaydet | Listede Ödeme API satırında "Yüksek" ve "Kart Ödemeleri" etiketleri görünür |
| 9.11 | Uygulamalar arama kutusuna `kart ödemeleri` yazın | Ödeme API bulunur |
| 9.12 | Ödeme editörü ile Ödeme API düzenle, Yeni etiket kategorisi listesini açın | Yalnız var olan kategoriler (Kritiklik, Ortam, Ürün) seçilebilir. Kategori = Ürün ile `Mobil Ödeme` yazıp Enter, Kaydet: etiket eklenir |
| 9.13 | Yönetici hesabıyla Analiz > Sertifika Haritası (Sertifikalar görünümü) | Soldan sağa Kök (mavi) → Ara (yeşil) → sertifikalar (turuncu) → domainler (mor). `localhost:9441` ve `localhost:9446` domainleri kendi sertifikalarına bağlıdır |
