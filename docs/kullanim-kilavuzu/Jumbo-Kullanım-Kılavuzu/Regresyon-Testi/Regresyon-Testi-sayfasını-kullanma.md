**İşlemler > Regresyon Testi** sayfası yalnız Yönetici rolündekilere görünür. Diğer rollerde menüde yoktur, adres elle yazılsa da açılmaz. Sayfada **Elle test** ve **Otomatik kontroller** sekmeleri vardır. Test ortamında (REGRESSION_TOOLS=1) üçüncü bir sekme, **Test Hazırlığı** da görünür; canlıda bu sekme yoktur.

## Otomatik kontroller
**Kontrolleri Çalıştır**'a basın. Jumbo kendi kendine şunlara bakar: veritabanı bağlantısı ve harf düzeni (collation), tablolar, sunucu saati, gizli anahtarlar, AD, mail sunucusu, AI, Kullanım Kılavuzu (wiki), Vault, Jenkins, zamanlanmış işler, eksik bilgiler, zincir, yönetici sayısı, yetki kontrolleri ve bütün sayfaların açılması.

- Kontroller **hiçbir kaydı değiştirmez ve mail göndermez**. Mail sunucusuna yalnız bağlanıp giriş yapılır, mail atılmaz. Sonuç Audit Log'a yazılır.
- Her satırda Tamam (yeşil), Uyarı (sarı), Hata (kırmızı) ya da Kapalı (gri, o özellik ayarlarda kapalı) yazar. Uyarı ve hata satırlarındaki ✦ düğmesi soruyu AI asistanına sorar.
- Sonuç Excel'e aktarılabilir.

## Test Hazırlığı
Testten önce gereken sertifikaları, test sitelerini, ekipleri ve test hesaplarını Jumbo'nun içinden hazırlar. Ayrı sunucu, Docker ya da betik gerekmez.

1. İsterseniz A, B ve C adreslerini yazın (test ekiplerinin bildirim adresleri), sonra **Hepsini Hazırla (1–3)**'e basın. Üç adımı tek tek de yapabilirsiniz.
2. **Test sertifikaları**: 00–25 numaralı 26 dosya o anki tarihe göre üretilir. Dosyaları tek tek ya da **Tümünü İndir (zip)** ile indirin. PFX parolası ekranda yazar. **Yeniden Üret** her şeyi yeni tarihlerle baştan üretir; açık test siteleri de yeni sertifikalara geçer.
3. **Test siteleri**: `localhost:9441`–`9447` ve iptal listesi `localhost:9440` Jumbo'nun içinde açılır. Jumbo bu sitelere kendi üstünden bağlanır. Her satırda sitenin cevap verip vermediği yazar. Madde 5.6'daki yenileme için **9444: yenilenmiş sertifikayı sun** anahtarını açın. Siteler **4 saat** sonra kendiliğinden kapanır; **Durdur** ile hemen kapatılır, **Başlat** ile yeniden açılır.
4. **Test ekipleri ve hesapları**: 4 SY ekibi (Ödeme Sistemleri SY, İletişim Kanalları SY, Mobil Uygulamalar SY, Mailsiz Test SY) ve 4 yerel test hesabı açılır: `ismail.test` (Ekip Editörü, Ödeme), `iletisim.test` (Ekip Editörü, İletişim), `izleyici.test` (Ekip İzleyici, Ödeme), `rolsuz.test` (Yetkisiz). Parola ekranda yazar. Aynı adlı ekip zaten varsa o kullanılır; aynı adlı hesap varsa ona dokunulmaz. AD girişini sınayan adımlar için gerçek AD hesabı yine gerekir.
5. Test bitince **Test Verisini Temizle**'ye basın. Pencere önce neyin silineceğini sayılarla gösterir: test sertifikaları (Subject ya da Issuer'ında "O=Jumbo Regresyon Testi" olanlar), test domainleri (`localhost…`, `*.jumbo-test.local` ve test ekiplerinin domainleri) ve talepleri, test ekiplerinin uygulamaları, bu sekmenin açtığı ekipler ve hesaplar. Test sonuçları, Audit Log ve ayarlar değişmez.

Mail ayarları (SMTP, Uyarı Eşiği, Yedek adres Y) bu sekmeyle değişmez; *Hazırlık* sayfasındaki gibi elle kontrol edilir. Her adım Audit Log'a "Regresyon test hazırlığı" olarak yazılır.

Çoklu pod kurulumunda test siteleri her pod'da açılır, bu yüzden kontrol hangi pod'a düşerse düşsün siteye ulaşır.

## Elle test
1. **Yeni Test** (ilk seferde **Yeni Test Başlat**) ile bir test açın ve adını yazın (ör. "v3.9.27 preprod"). Sürüm kendiliğinden kaydedilir.
2. Senaryolar bölüm bölüm listelenir. Her senaryoda ne yapılacağı ve beklenen sonuç yazar. Adımı yapın ve **Geçti**, **Kaldı** ya da **Atlandı** seçin. Kaldı seçilince not alanı açılır: ekranda ne gördüğünüzü bir cümleyle yazın. Seçimi kaldırmak için aynı düğmeye tekrar basın.
3. Üstteki sekmelerle yalnız bekleyenleri ya da kalanları görebilir, arama kutusuyla senaryo arayabilirsiniz.
4. Bitince **Testi Bitir**'e basın. Bitmiş teste işaret eklenemez; yeni sürüm için yeni test açın. Sonuçlar Excel'e aktarılabilir.

Bölüm 8–11 (Uygulamalar, trust store, sertifika yönetimi, uyum ve iptal) sayfada **B2-8.1**, **B2-9.4** gibi kimliklerle listelenir; numaralar bu kılavuzdaki madde numaralarıyla aynıdır. Diğer bölümler (sertifika yükleme, canlı doğrulama, mail, kritik alanlar, ekranlar, çoklu pod) geliştirme ekibinin regresyon listelerinden gelir.

Test ve işaretler veritabanına yeni tablo eklemeden Audit Log'a yazılır; kim, ne zaman, hangi sonucu verdi görünür. Testi birden fazla yönetici birlikte yürütebilir.

## AI ile yardım
Her senaryodaki ✦ düğmesi şunları sunar:

- **Adımı anlat**: AI adımı bu kılavuzdan bulup sade dille anlatır.
- **Sonucu kayıtlardan doğrula**: AI Jumbo'daki kayıtlara (sertifika, domain, talep, mail geçmişi) bakıp beklenen sonucun oluşup oluşmadığını söyler.
- **Neden kaldı?**: Kaldı işaretli senaryoda olası nedeni ve neye bakılacağını söyler.

**AI ile Özetle** testin özetini çıkarır: kaç senaryo geçti, kaldı, atlandı; kalanlar ve notları; bir önceki testte geçip bu testte kalanlar. AI yalnız okur; hiçbir kaydı değiştirmez, işaret koymaz.

## Sonuçları bildirme
Testi bitirdikten sonra Excel çıktısını ilgili ekibe gönderin. Her **Kaldı** için şunlar yazılmış olmalı: senaryo kimliği, ne yaptığınız (kılavuzdan farklı bir şey yaptıysanız o da), ekranda gördüğünüz mesaj aynen, ekran görüntüsü ve saat. Mail içeren adımlarda mailin konusunu ve kime geldiğini de yazın. Test bitince Test Hazırlığı sekmesinden test verisini temizleyin (Docker ya da Python ile açtıysanız test sitelerini *Hazırlık* sayfasındaki gibi kapatın).

Testten önce *Hata sayılmayacak davranışlar* sayfasına bakın; oradaki durumları Kaldı işaretlemeyin.
