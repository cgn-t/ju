Jumbo bağlantıları kendisi değiştirmez; değişikliği önerir. Talep domainin SY ekibi (ya da yönetici) onaylayınca uygulanır, reddedilirse hiçbir şey değişmez.

## Talep türleri
- **Sertifika değişimi**: bağlantı eski sertifikadan yenisine taşınır (yenileme).
- **Sunucuya eklenen**: sunucuda görülen sertifika domaine bağlanacak.
- **Sunucudan kalkan**: sunucu artık sunmuyor, bağlantı kaldırılacak.
- **Tarih güncelleme**: kayıttaki tarihler sertifikanın kendisinden yeniden okunur.
- **Trusted bağlantı**: uygulamanın trust store'u ya da bağımlılığı yeni sertifikaya taşınır.

## Kim onaylar?
Domainin SY ekibindeki Ekip Editörleri ve yöneticiler. Ekip İzleyici ve Genel İzleyici onaylayamaz. SY ekibi olmayan (sahipsiz) domainin talebini yalnız yönetici onaylar.

## İnceleme
1. **Değişiklik Talepleri** ekranında **Bekleyen** sekmesini açın. **Yalnız karar verebileceklerim** ile kendi onaylayabileceklerinizi süzün.
2. Talebe tıklayınca inceleme penceresi açılır: eski ve yeni sertifika yan yana, kimlik alanlarının eşleşmesi (Subject, SAN, SKI, Issuer), Fingerprint ve canlı kanıt.
3. **Canlıda görüldü** işareti yeni sertifikanın sunucuda görüldüğünü gösterir; bu durumda onaylamak güvenlidir. İşaret yoksa onaydan önce Canlı Doğrulama önerilir.
4. Onaylayın ya da reddedin. Her karar Audit Log'a yazılır.

Domain penceresindeki **Onaya git** bağlantısı, o domainin taleplerini süzülmüş olarak açar. Bekleyen talep sayısı menüde rozet olarak görünür.

> Yönetici açarsa bekleyen talebi olan SY ekiplerine her sabah hatırlatma maili gider (Ayarlar > E-posta).
