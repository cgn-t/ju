**İşlemler > Regresyon Testi** sayfası yalnız Yönetici rolündekilere görünür. Diğer rollerde menüde yoktur, adres elle yazılsa da açılmaz. Sayfada iki sekme vardır: **Elle test** ve **Otomatik kontroller**.

## Otomatik kontroller
**Kontrolleri Çalıştır**'a basın. Jumbo kendi kendine şunlara bakar: veritabanı bağlantısı ve harf düzeni (collation), tablolar, sunucu saati, gizli anahtarlar, AD, mail sunucusu, AI, Kullanım Kılavuzu (wiki), Vault, Jenkins, zamanlanmış işler, eksik bilgiler, zincir, yönetici sayısı, yetki kontrolleri ve bütün sayfaların açılması.

- Kontroller **hiçbir kaydı değiştirmez ve mail göndermez**. Mail sunucusuna yalnız bağlanıp giriş yapılır, mail atılmaz. Sonuç Audit Log'a yazılır.
- Her satırda Tamam (yeşil), Uyarı (sarı), Hata (kırmızı) ya da Kapalı (gri, o özellik ayarlarda kapalı) yazar. Uyarı ve hata satırlarındaki ✦ düğmesi soruyu AI asistanına sorar.
- Sonuç Excel'e aktarılabilir.

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
Testi bitirdikten sonra Excel çıktısını ilgili ekibe gönderin. Her **Kaldı** için şunlar yazılmış olmalı: senaryo kimliği, ne yaptığınız (kılavuzdan farklı bir şey yaptıysanız o da), ekranda gördüğünüz mesaj aynen, ekran görüntüsü ve saat. Mail içeren adımlarda mailin konusunu ve kime geldiğini de yazın. Test bitince test sitelerini kapatın (*Hazırlık* sayfası).

Testten önce *Hata sayılmayacak davranışlar* sayfasına bakın; oradaki durumları Kaldı işaretlemeyin.
