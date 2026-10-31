Regresyon Test Kılavuzu, Bölüm 2, madde 11. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın. Jumbo'daki **Regresyon Testi** sayfasında bu adımlar "Uygulamalar, trust store, sertifika yönetimi, uyum ve iptal" bölümünde **B2-11.1**, **B2-11.2** … kimlikleriyle listelenir.

Bir sertifika, süresi dolmadan yayıncısı tarafından iptal edilebilir. Jumbo bunu sertifikanın içinde yazan adresten (OCSP ya da CRL) sorar. Test paketindeki üç sertifika, test sitelerinin 9440 portundaki iptal listesini (`http://<ad>:9440/iptal.crl`) kullanır. Bu yüzden **Jumbo sunucusu test sitelerinin makinesine 9440 portundan ulaşabilmelidir**; tarayıcınızdan `http://<ad>:9440` sayfasını açabilmeniz bunun için yeterli değildir, Jumbo sunucusu da ulaşabilmelidir. Sertifikalar test sitelerinin adıyla (Docker'daki `AD`) üretildiği için bu dosyaları 9440 sayfasından indirin.

Sonuç Jumbo'da şu şekillerde görünür: **İptal edilmemiş** (yeşil), **İPTAL EDİLMİŞ** (kırmızı), **Ulaşılamadı** (sarı, sorulacak adrese erişilemedi), **Bilinmiyor** (sarı, kurum bu sertifikayı tanımıyor), **Kontrol edilemez** (gri, sertifikada sorulacak adres yok ya da üst sertifika envanterde yok), **Denetlenmedi** (henüz sorulmadı). v3.8.8'den önceki sürümde Ulaşılamadı, Bilinmiyor ve Kontrol edilemez tek bir "Belirsiz" etiketiyle görünür. Jumbo iptal edilmiş sertifikayı pasife almaz, yalnız durumunu yazar ve mail atar.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 11.1 | Yönetici hesabıyla Ayarlar > İptal (OCSP/CRL) sayfasına bakın | "Gece iptal denetimi etkin (her gün)" kapalıdır (varsayılan). Yöntem "OCSP → CRL (önerilen)", Gece Saati 5 |
| 11.2 | `14-iptal-edilmis.pem`, `15-iptal-edilmemis.pem`, `16-iptal-bilgisi-yok.pem` dosyalarını yükleyin (Oluşturan Ekip = Ödeme Sistemleri SY, Ortam = Test) | Üçü de eklenir. Detaylarında "İptal Durumu (OCSP/CRL)" altında **Denetlenmedi** yazar |
| 11.3 | Ödeme editörü ile `iptal-edilmis.jumbo-test.local` detayı > **Şimdi Kontrol Et** | Kırmızı **İPTAL EDİLMİŞ** ve yanında "Son denetim: <şimdiki saat>" |
| 11.4 | A kutusuna bakın | Tek mail: konu "[JUMBO] İPTAL EDİLMİŞ sertifika: iptal-edilmis.jumbo-test.local — acil aksiyon gerekli". İçinde Sertifika, Seri No, Bitiş, "Durum: İPTAL EDİLMİŞ (revoked)" ve üç adımlık "Lütfen şu adımları izleyin" listesi var. Görünümü diğer Jumbo mailleriyle aynıdır |
| 11.5 | Aynı sertifikada tekrar **Şimdi Kontrol Et** | Durum yine İPTAL EDİLMİŞ, Son denetim saati güncellenir. **Yeni mail gelmez** |
| 11.6 | `iptal-edilmemis.jumbo-test.local` > Şimdi Kontrol Et | Yeşil **İptal edilmemiş**. Mail gelmez |
| 11.7 | `iptal-bilgisi-yok.jumbo-test.local` > Şimdi Kontrol Et | Gri **Kontrol edilemez** (bu sertifikada sorulacak adres yoktur). Mail gelmez |
| 11.8 | İzleyici hesabıyla aynı detayı açın | Durum görünür ama Şimdi Kontrol Et düğmesi yoktur |
| 11.9 | Yönetici hesabıyla Ayarlar > İptal: "Gece iptal denetimi etkin" açın, Kaydet. Ertesi sabah (05:00'ten sonra) üç sertifikaya bakın | Durumlar aynıdır (İPTAL EDİLMİŞ / İptal edilmemiş / Kontrol edilemez); Son denetim saati gece 05 civarıdır. İptal edilmiş sertifika için yeni mail gelmez, çünkü durum değişmedi |
| 11.10 | Ayarı tekrar kapatın (varsayılan), Kaydet | Kaydedilir |

Bir sertifika "Ulaşılamadı" geliyorsa önce Jumbo sunucusunun `http://<ad>:9440/iptal.crl` adresine ulaşıp ulaşamadığını sistem yöneticisine kontrol ettirin. Ulaşılamıyorsa 11.6 ve ilk kez denetlenen sertifikalar Ulaşılamadı çıkar; bu bir ağ sorunudur. Daha önce İPTAL EDİLMİŞ çıkmış bir sertifika ise ulaşılamadığında da İPTAL EDİLMİŞ kalır ve yeni mail gitmez.
