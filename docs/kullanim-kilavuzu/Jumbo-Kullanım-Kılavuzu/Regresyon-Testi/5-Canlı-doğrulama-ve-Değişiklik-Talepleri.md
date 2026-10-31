Regresyon Test Kılavuzu, Bölüm 1, madde 5. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Yönetici hesabıyla. Canlı doğrulama, sunucunun gerçekte sunduğu sertifikayı Jumbo'daki kayıtla karşılaştırır. **Kendi başına hiçbir bağı değiştirmez**; her fark İşlemler > Değişiklik Talepleri sayfasına onay bekleyen bir değişiklik talebi olarak düşer. Domain detayında "Canlı Doğrulama (Drift Detection)" bölümü en alttadır.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 5.1 | `localhost:9441` detayı > **Şimdi Doğrula** | Yeşil "Eşleşiyor — sunulan sertifika envanterle aynı" ve "Son kontrol" saati |
| 5.2 | `localhost:9443` detayı > Şimdi Doğrula | Turuncu "Ara sertifika sunucuda eksik". Notta "Sunucu ara sertifikayı göndermiyor (Jumbo Test Ara SM). Tarayıcılar çoğu zaman açar ama Java, mobil ve API istemcileri bağlantı kuramayabilir…". Bunun için talep açılmaz |
| 5.3 | `localhost:9446` detayı > Şimdi Doğrula | Kırmızı "SÜRESİ DOLMUŞ — sunucu süresi dolmuş sertifikayı sunuyor". Not satırında "Sunucu envanterdeki sertifikanın aynısını sunuyor ama süresi dolmuş: localhost — yeni sertifika sunucuya kurulmalı" yazar. "Canlıdaki Sertifikayı İçe Aktar" kutusu görünmez. (v3.8.6'dan önceki sürümde aynı durum "UYUMSUZ — sunulan sertifika eşlenen sertifikadan farklı" diye görünür |
| 5.4 | İşlemler > **Değişiklik Talepleri** | Doğruladığınız domainler için "EKLE Jumbo Test Kök SM" talepleri, Kaynak "Canlı doğrulama", Kanıt "canlıda". Bunlar normaldir: sunucular kök sertifikayı göndermez, Jumbo kökü envanterden bulup domaine eklemeyi önerir |
| 5.5 | 9441'in EKLE talebini **Onayla**; 9443'ün EKLE talebini **Reddet**. Sonra 9443 detayında tekrar Şimdi Doğrula | Onaylanan: 9441 detayında Bağlı Sertifikalar'a kök eklenir. Reddedilen: aynı talep geri gelmez |
| 5.6 | Docker'da: 9440 sayfasında "9444'te sertifikayı yenile" düğmesine basın. Python'da: test sunucusu penceresinde Ctrl+C, sonra `python3 test-sunucusu.py --yenilenmis` | "9444 şu an YENİLENMİŞ sertifikayı sunuyor" yazar |
| 5.7 | `localhost:9444` detayı > Şimdi Doğrula | Kırmızı EŞLEŞMİYOR. Bağlı Sertifikalar'da hâlâ eski sertifika (~25g) durur; onaydan önce bağ değişmez. Detayda "Bu domain için 2 değişiklik talebi SY onayı bekliyor" (biri yeni sertifika, biri kök için EKLE) |
| 5.8 | Değişiklik Talepleri | `localhost → localhost` değişiklik talebi, Domain `localhost:9444`, SY Ekip İletişim Kanalları SY, Kaynak "Canlı doğrulama", Kanıt "canlıda". **İncele** eski ve yeni sertifikayı yan yana gösterir |
| 5.9 | Talebi **Onayla**. Sonra 9444 detayında Şimdi Doğrula | Bağ yeni sertifikaya geçer (~394g kaldı). SSL Sertifikaları'nda eski sertifika pasif görünür. Canlı durum yeşil Eşleşiyor |
| 5.10 | Ayarlar > Canlı Doğrulama | "Gece canlı doğrulaması etkin (her gün)" varsayılan olarak açık, saat 7. Bu ayarlara dokunmayın |

Eski sertifika, başka bir domainde ya da bir uygulamanın trust store'unda kullanılıyorsa onaydan sonra da aktif kalır. O kullanım da devredilince pasife geçer.
