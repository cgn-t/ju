**Uygulamalar** ekranı uygulama envanterini, sunucularını ve domain ilişkilerini tutar. Uygulama eklemek için Yönetici ya da Ekip Editörü olmanız gerekir.

## Uygulama ekleme
1. **Yeni Uygulama**'ya basın.
2. **Uygulama Adı**, **Sunucu Adı** ve **SY Takımı** zorunludur.
3. **Bağlı Domain**: uygulamanın kendi domaini. Bu domainin server sertifikası uygulamanın sertifikası sayılır.
4. İsterseniz IP Adresi, DNS, Config Path, Log Path, Start/Stop Yöntemi, Kontrol Yöntemi, Gerekli Komutlar, Servis Sağlayıcı İletişim, Etiketler ve notları doldurun.

## Bağımlılık (Trusted bağlantı)
Uygulama başka bir domaine bağlanıyorsa uygulama penceresinden bağımlılık ekleyin: **Hedef Domain** ve gerekiyorsa uygulamanın kullandığı client **Sertifika**. Hedef domainin sertifikası yenilendiğinde bu uygulama da etkilenenler listesinde görünür.

## Trust store
Uygulamanın güvendiği sertifikaları (trust store) uygulama penceresinden ekleyin. Pasif bir sertifika trust store'a eklenemez. Ekip Editörü yalnız kendi ekibinin uygulamalarının trust store'unu düzenler.

## Uyarı mailleri
Uygulamanın SY ekibi şu sertifikalar için de uyarı maili alır: Bağlı Domain'in server sertifikası, bağımlılıktaki client sertifika ve trust store'daki sertifikalar (trust store'dakiler için yalnız süre dolana kadar). Uygulama pasif olsa da uyarı gider. Ayrıntı: *Uyarı mailleri*.
