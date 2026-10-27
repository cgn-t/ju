Sertifika yenilemesi Jumbo dışında yapılır (CA'dan yeni sertifika alınır, sunucuya kurulur). Jumbo'da yapılacaklar şunlardır:

1. Yeni sertifikayı **SSL Sertifikaları** > **Yeni Ekle** ile içe aktarın. Bkz. *Sertifika ekleme*.
2. Jumbo eski sertifikayı tanır (aynı anahtar ya da aynı CN ve CA). **değişiklik talebi oluştur** işaretli kalsın.
3. Eski sertifikanın bağlı olduğu her domain ve uygulama için ayrı bir **Sertifika değişimi** talebi açılır.
4. Domainin SY ekibi **Değişiklik Talepleri** ekranında talebi inceler ve onaylar. Onaylanınca bağlantı yeni sertifikaya taşınır.

## Canlıda görüldü
Yeni sertifika sunucuya kurulduysa gece çalışan Canlı Doğrulama bunu görür ve talebe **Canlıda görüldü** işaretini koyar. Bu işaret, onaylamanın güvenli olduğunu gösterir. Talep açılmamışsa Canlı Doğrulama, yeni sertifikayı sunan domain için kendisi talep açar.

## Eski sertifika ne olur?
Eski sertifika hâlâ bir yerde kullanılıyorsa ya da bekleyen talebi varsa aktif kalır. Hiçbir yerde kullanılmadığında yönetici pasife alabilir. Yenilenen sertifikanın penceresinde yenisine giden bağlantı görünür.

> Talebi sonradan açmak isterseniz sertifika penceresindeki **Değişiklik Talebi Oluştur** düğmesini kullanın.
