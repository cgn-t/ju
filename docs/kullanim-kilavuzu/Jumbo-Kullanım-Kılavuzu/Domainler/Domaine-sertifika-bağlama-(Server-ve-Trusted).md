Bir domainin hangi sertifikayı kullandığını Jumbo'ya bağlantı ile söylersiniz. Uyarı mailleri, Canlı Doğrulama ve Etkilenenler listesi bu bağlantılardan çalışır.

## Bağlantı tipleri
- **Server**: domainin sunucusunun sunduğu sertifika. Süresi dolarsa site çalışmaz.
- **Trusted**: domainin güvendiği (trust store'a eklenmiş) sertifika, örneğin karşı tarafın sertifikası ya da kurum içi Root.

## Nasıl bağlanır?
1. **Domainler** ekranında domaine tıklayın, **Sertifikalar** sekmesini açın.
2. **Sertifika seç** kutusunda ad, SKI ya da Serial Number ile arayın.
3. **Bağlantı Tipi**'ni (Server ya da Trusted) seçip ekleyin.

Sertifika domain adını kapsamıyorsa kırmızı **Alan adını kapsamıyor** uyarısı çıkar. Wildcard sertifikalar (*.ornek.com) alt alan adlarını kapsar.

## Canlıdaki sertifikayı içe aktarma
Sertifika Jumbo'da yoksa domain penceresinin **Canlı Doğrulama** sekmesinde **Canlıdaki Sertifikayı İçe Aktar** düğmesi sunucunun sunduğu sertifikayı ve zincirini Jumbo'ya ekler ve domaine bağlar.

## Bağlantıyı kaldırma
Sertifikalar sekmesinde bağlantının yanındaki **Bağlantıyı kaldır** yalnız bağlantıyı siler; sertifika envanterde kalır.

> Bağlantıları bir sertifikadan yenisine taşımak için bağlantıyı elle değiştirmek yerine yeni sertifikayı içe aktarıp değişiklik talebi açın: *Süresi dolan sertifikayı yenileme*.
