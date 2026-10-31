Regresyon Test Kılavuzu, Bölüm 1, madde 2. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Yönetici hesabıyla, test siteleri açıkken. Domainler > **Yeni Ekle**. Domain alanına adresi yazıp Tab'a basın; "Canlı Sertifika Zinciri" kutusu kendiliğinden dolar. Kaydetmek için zorunlu alanlar: SY Takımı, LoadBalancer Güncelleme, WAF Güncelleme (herhangi bir değer seçin). Kutuda L = sertifika, I = ara sertifika, R = kök demektir.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 2.1 | `localhost:9441` yazın, SY Takımı = Ödeme Sistemleri SY. "Zinciri Sertifikalar'a aktar ve uç sertifikayı bu domain'e server olarak bağla" kutusunu işaretleyin, Ortam = Test, **Ekle** | Kutuda L `localhost` "Yeni" ve I Jumbo Test Ara SM "DB'de kayıtlı". Kaydedince "Zincir aktarıldı" ile başlayan yeşil mesaj. Listede Server Sertifika sütununda yeşil "~300g kaldı" |
| 2.2 | Yeni Ekle'de sırayla `https://localhost:9441/giris`, `LOCALHOST:9441`, `localhost:9441` (başında ve sonunda boşlukla) yazıp Tab'a basın | Üçünde de aynı zincir gelir |
| 2.3 | `LOCALHOST:9441` ile kaydetmeyi deneyin | "Bu domain zaten kayıtlı: LOCALHOST:9441". İkinci kayıt oluşmaz. Sonra Vazgeç |
| 2.4 | `localhost:9442` yazıp Tab | Kırmızı uyarı: "Sunucunun verdiği sertifika 'localhost' adresini kapsamıyor (sertifikadaki adlar: baska-site.jumbo-test.local)… Bu sertifika domaine yalnız aşağıdaki kutu işaretlenirse bağlanır." Aktarma kutusu **işaretsiz** gelir |
| 2.5 | Kutuyu işaretlemeden SY = Ödeme Sistemleri SY ile **Ekle** | Domain eklenir ama hiçbir sertifika bağlanmaz (Server Sertifika sütununda "—"). SSL Sertifikaları'nda `baska-site.jumbo-test.local` yoktur |
| 2.6 | `localhost:9442` detayını açın (göz simgesi) > **Şimdi Doğrula** | Kırmızı EŞLEŞMİYOR ve notta adresi kapsamadığını söyleyen uyarı. Değişiklik Talepleri'nde bu domain için değişiklik talebi açılmaz |
| 2.7 | Aynı detayda Ortam = Test seçip **Canlıdaki Sertifikayı İçe Aktar** | Aktarmaz; adres uyarısı ve yanında **Yine de aktar** düğmesi çıkar |
| 2.8 | **Yine de aktar** | Sertifika bağlanır, hata çıkmaz. Ayarlar > Audit Log'da bu işlem kayıtlıdır. Tekrar Şimdi Doğrula: durum yeşil Eşleşiyor olur (sertifikayı bilerek kabul ettiniz), ama "Uyarı" satırında adres uyarısı kalır |
| 2.9 | `localhost:9443`, SY = Ödeme Sistemleri SY, aktarma kutusu işaretli, Ortam = Test, Ekle | Kutuda yalnız L görünür (I gelmez, bu site ara sertifikayı göndermiyor). Domain eklenir, sertifika bağlanır |
| 2.10 | Aynı şekilde üç domain daha: `localhost:9444` (SY = İletişim Kanalları SY), `localhost:9445` (Ödeme Sistemleri SY), `localhost:9446` (İletişim Kanalları SY) | Listede 9444 turuncu ~25g, 9445 turuncu ~19g, 9446 kırmızı "Süresi Doldu (6g)" ya da (5g). Üst kutularda "SÜRESİ DOLMUŞ" ve "YAKLAŞAN (≤30G)" sayıları artar |
| 2.11 | Yeni Ekle'de `localhost:9999` yazıp Tab (orada site yok) | "Zincir çekilemedi: … — domain yine de kaydedilebilir." Vazgeç |

"Zinciri Getir" ve "Yeniden Sorgula" düğmeleri aynı sorguyu elle tekrarlar.
