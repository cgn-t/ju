Aşağıdakiler bilinçli kararlar ya da bilinen davranışlardır. Testte görürseniz **Kaldı** işaretlemeyin.

## Bölüm 1–7

| Ne görürsünüz | Neden doğru |
|---|---|
| Sertifika Haritası'nda ekip editörü tüm ekiplerin domainlerini görür | Harita bütün resmi göstermek içindir; değişiklik yetkisi yine ekiple sınırlı |
| Aynı sabah aynı sertifika için iki mail gelebilir (uygulama iki kopya çalışıyorsa ya da tam 08:00'de yeniden başlatıldıysa) | Kabul edildi, düzeltilmeyecek |
| Süresi dolmuş bir Trusted sertifika için uygulama sahibine mail gitmez | Trusted sertifikanın sahibine yalnız süre dolana kadar uyarı gider |
| Maillerde "Trusted" kelimesi geçer | Şirket mTLS kullanmadığı için bu kelime bırakıldı |
| Domainin UG ekibine mail gitmez | Şimdilik istenmedi |
| Pasif bir uygulamanın sahibine uyarı gitmeye devam eder | İstenen davranış |
| Bir sertifika elle pasife alınınca mail gitmez | İstenen davranış |
| Domaine server olarak bağlı sertifika elle pasife alınamaz; yalnız Trusted (ya da mTLS) olarak bağlı olan alınabilir | İstenen davranış |
| Değişiklik Talepleri'nde kök sertifika için EKLE talepleri | Sunucular kökü göndermez; Jumbo kökü envanterden tamamlar |
| Bir sunucuya üst üste iki yeni sertifika kurulursa iki rakip talep açık kalabilir | Düzeltilmesi istenmedi |
| İptal edilmiş sertifika maili gelmez | İptal kontrolü Ayarlar'da varsayılan olarak **kapalı**. Bu mail yalnız kontrol açıkken gider; Bölüm 1–7 boyunca kapalı kalır, 11. bölümde (İptal) test edilir |
| Bir sertifikada elle "İptal durumunu denetle" yapılınca, gece iptal kontrolü kapalı olsa bile mail gidebilir | Böyle kalması kararlaştırıldı |

## Varsayılan ayarlar (ilk kurulum)

| Ayar | Varsayılan |
|---|---|
| E-posta bildirimleri | Kapalı (SMTP girilip açılmalı) |
| Uyarı Eşiği | 30 gün |
| Sabah süre uyarısı (08:00) | Açık |
| Sabah süresi geçmiş hatırlatması (08:05) | Açık |
| Tekrar-önleme | Açık, 3 saat |
| Yedek/Varsayılan Adres | Boş |
| Değişiklik talebi hatırlatması | Kapalı |
| Gece canlı doğrulama | Açık, saat 7 |
| Gece iptal denetimi | Kapalı, saat 5 |
| Keşif ve CT taraması | Kapalı |

## Bölüm 8–11

| Ne görürsünüz | Neden |
|---|---|
| Değişiklik talebi oluştuğunda ekibe mail gitmez | Talepler Değişiklik Talepleri ekranında görünür; ayarlanmışsa ayrıca hatırlatma maili gider |
| Trust store'dan çıkarılan sertifika pasife alınmaz | Sertifika başka bir yerde kullanılıyor olabilir; pasife alma elle yapılır |
| Bir sertifikayı oluşturan ekip dışında, onu kullanan ekip de düzenleyebilir (ör. 8.10'dan sonra Ödeme editörü 9446'nın yeni sertifikasının Notlar'ını değiştirebilir) | Sertifikayı domaininde, dış bağımlılığında ya da trust store'unda kullanan her ekip onun sahibi sayılır |
| Uyum kapalıyken de Uyum sayfası bulguları gösterir | Sayfa sarı uyarıyla durumu belirtir |
| CA izin listesi açıkken listede olmayan yayıncının kendisi (ör. "Bilinmeyen Test SM") uyumsuz görünmez, yalnız onun verdiği sertifika görünür | Kural, yayıncı tarafından verilen sertifikalara bakar |
| Bir editör, başka ekibin sertifikasında da Şimdi Kontrol Et'i çalıştırabilir | Kontrol sertifikayı değiştirmez, yalnız durumunu yazar |
| Toplu iptal denetimi için ekranda düğme yoktur | Toplu denetim gece çalışır (11.9) |
