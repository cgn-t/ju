Canlı Doğrulama, domainin sunucusuna bağlanıp sunulan sertifikayı Jumbo'daki bağlı sertifikayla karşılaştırır. Her gece (varsayılan 07:00) tüm domainler için kendiliğinden çalışır. Domain penceresindeki **Canlı Doğrulama** sekmesinde **Şimdi Doğrula** ile hemen çalıştırabilirsiniz.

## Sonuçlar
- **Eşleşiyor**: sunulan sertifika envanterle aynı.
- **EŞLEŞMİYOR**: sunucu bağlı sertifikadan farklı bir sertifika sunuyor ya da sertifika domain adını kapsamıyor. Domain birden çok IP'ye çıkıyorsa ve IP'lerden biri farklı sertifika sunuyorsa da bu sonuç çıkar.
- **SÜRESİ DOLMUŞ**: sunucu süresi dolmuş sertifikayı sunuyor.
- **Ara sertifika sunucuda eksik**: sunucu zincirdeki Intermediate'i göndermiyor; bazı istemciler bağlanamaz.
- **Erişilemedi**: sunucuya bağlanılamadı.
- **Server sertifikası bağlanmamış**: karşılaştırılacak bağlı sertifika yok.
- **Kontrol edilemez (wildcard)**: *.ornek.com gibi adreslere bağlanılamaz.

Sonuçta **Tarih farkı** notu varsa, sunulan sertifika aynıdır ama Jumbo'daki ValidTo eskidir.

## Canlı Doğrulama neyi değiştirir?
Hiçbir kaydı kendisi değiştirmez. Bulduğu her farkı değişiklik talebine çevirir:
- Yeni sertifika canlıda görüldü: **Sertifika değişimi** (Canlıda görüldü).
- Sunucu fazladan bir sertifika sunuyor: **Sunucuya eklenen**.
- Bağlı sertifika artık sunulmuyor: **Sunucudan kalkan** (yalnız bağlantı kaldırılır).
- Tarih farkı: **Tarih güncelleme**.

Reddedilen talep aynı fark için bir daha açılmaz.

## Ek kontroller
Sonuç ekranında DNS kaydı, Çoklu IP, CAA ve OCSP Stapling bilgileri de görünür. Bunlar bilgi amaçlıdır; yalnız Çoklu IP'de farklı sertifika sunan IP sonucu kırmızıya çevirir.
