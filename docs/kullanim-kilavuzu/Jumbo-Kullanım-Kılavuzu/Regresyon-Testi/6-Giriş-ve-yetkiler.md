Regresyon Test Kılavuzu, Bölüm 1, madde 6. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Hazırlık'taki hesaplarla. Her hesapla ayrı giriş yapın (başka tarayıcı ya da gizli pencere kolaylık sağlar). Burada "Ödeme editörü" adında i harfi olan AD hesabıdır; örneklerde `ismail.celik` yazıyor, kendi hesabınızın adını kullanın.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 6.1 | Ödeme editörüyle yanlış şifre girin; sonra şifre alanını boş bırakın | İkisinde de giriş olmaz, kırmızı hata mesajı çıkar |
| 6.2 | Ödeme editörüyle küçük harfle (`ismail.celik`) girin, çıkış yapın, BÜYÜK harfle (`ISMAIL.CELIK`) girin | İkisinde de sağ üstte aynı rol (SY Ekip) ve aynı ekranlar. Yönetici hesabıyla Ayarlar > Kullanıcılar'da bu kişi **tek** satırdır, kopya yok |
| 6.3 | Ödeme editörüyle Domainler | Yalnız Ödeme Sistemleri SY domainleri: `excel-bir`, `localhost:9441`, `9442`, `9443`, `9445`, `9447`. `9444`, `9446` ve `excel-iki` görünmez |
| 6.4 | Ödeme editörüyle SSL Sertifikaları'nda `localhost:9444`'e bağlı yeni `localhost` sertifikasını (~395g, İletişim'in) açıp Notlar'ı değiştirmeyi deneyin | Değişmez: "Bu sertifika başka bir ekibe ait; yalnız o ekibin editörü veya admin düzenleyebilir" |
| 6.5 | Aynı hesapla `tek-sertifika.jumbo-test.local` (Ödeme'nin oluşturduğu) Notlar'ını değiştirin | Kaydedilir |
| 6.6 | Aynı hesapla Değişiklik Talepleri | Yalnız Ödeme Sistemleri SY domainlerinin bekleyen talepleri görünür ve onaylanabilir |
| 6.7 | İletişim editörüyle girin, Domainler'de `localhost:9444`'i düzenleyip Detay'a bir not yazın | Yalnız İletişim domainleri (`excel-iki`, `9444`, `9446`) görünür; düzenleme kaydedilir |
| 6.8 | İzleyici hesabıyla girin | Ödeme Sistemleri SY domainleri görünür. Yeni Ekle, düzenle, sil ve Excel Yükle düğmeleri yoktur ya da çalışmaz; deneme "Bu işlem için yetkiniz yok" ile reddedilir |
| 6.9 | Rolsüz hesapla girin | "Henüz bir takıma atanmadınız" ekranı; hiçbir veri görünmez, yalnız Çıkış Yap düğmesi |
| 6.10 | Ödeme editörüyle Analiz > Sertifika Haritası | **Tüm** ekiplerin domainleri görünür. Bu bilinçli bir karardır, hata değildir |
| 6.11 | Yönetici hesabıyla Ayarlar > Audit Log | Bu testte yapılan ekleme, düzenleme, onay, ret ve pasife alma işlemleri kullanıcı adı ve saatle listelenir. CSV olarak indirip Excel'de açınca Türkçe harfler doğru |
