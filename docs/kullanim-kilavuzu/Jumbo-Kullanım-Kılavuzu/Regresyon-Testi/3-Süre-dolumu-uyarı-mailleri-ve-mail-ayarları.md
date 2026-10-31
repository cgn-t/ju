Regresyon Test Kılavuzu, Bölüm 1, madde 3. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Yönetici hesabıyla, Ayarlar > E-posta (SMTP). Mail konusu her zaman `[JUMBO]` ile başlar. Her mailde "Bu bildirimi alma nedeniniz" başlığı altında alıcının neden mail aldığı yazar. Gönderilen her mail Ayarlar > Mail Gönderim Geçmişi'nde görünür.

**Şimdi Gönder** düğmeleri tekrar-önlemeye takılmaz, her basışta yeniden gönderir. Otomatik sabah taraması ise aynı sertifikaya 3 saat içinde ikinci kez göndermez.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 3.1 | "Test Maili Alıcısı" = A, **Test Maili Gönder** | Yeşil bildirim "Test maili gönderildi: A". A'ya "[JUMBO] SMTP test maili" gelir; içinde sunucu, port ve bağlantı güvenliği yazar |
| 3.2 | Test mailini var olmayan bir adrese gönderin (test mail sunucusu reddediyorsa) | Kırmızı bildirimde sunucunun hata mesajı |
| 3.3 | Ayarlar > Ekipler > Mobil Uygulamalar SY'nin e-postasını `C; A` yapıp kaydedin, sonra tekrar yalnız `C` yapın | Kayıt "C, A" olarak görünür. Sonra C'ye döner |
| 3.4 | Aynı alana `C A` (boşlukla) ya da `abc` yazıp kaydedin | Kaydedilmez: "Geçersiz e-posta adresi … (birden çok adresi virgül ya da noktalı virgülle ayırın)" |
| 3.5 | Domainler > Yeni Ekle: `localhost:9447`, SY = Ödeme Sistemleri SY, aktarma kutusu işaretli, Ortam = Test | Domain eklenir; listede yeşil ~45g |
| 3.6 | **Süre Uyarılarını Şimdi Gönder** | Tam olarak şu 4 mail: A'ya `localhost (19 gün kaldı)`, nedeninde "Domain sahibi: localhost:9445 (Server)". A'ya `trusted-20-gun-kala.jumbo-test.local`, nedeninde "Sertifikayı oluşturan (sahibi) SY ekibisiniz". B'ye `localhost (24 gün kaldı)` (localhost:9444). Y'ye `sahipsiz-20-gun-kala.jumbo-test.local`, nedeninde "e-posta adresi tanımlı bir alıcı bulunamadı … yedek adrese gönderildi". 9447 (45 gün) için mail **gitmez** |
| 3.7 | Mailleri açın | Konu "[JUMBO] Sertifika süresi doluyor: <ad> (N gün kaldı)". Seri no, bitiş tarihi ve kalan gün doğru. Türkçe harfler bozuk değil. Dört mailin düzeni aynı |
| 3.8 | **Süresi Geçenleri Şimdi Gönder** | B'ye "[JUMBO] SÜRESİ GEÇMİŞ sertifika: localhost (N gün önce doldu) — JUMBO'da güncelleme gerekli" (localhost:9446). A'ya aynı konulu `trusted-suresi-gecmis.jumbo-test.local` maili. Mail içinde "JUMBO'da hâlâ AKTİF görünüyor" ve yapılacaklar listesi |
| 3.9 | Domainler > `localhost:9447` düzenle, **Bildirim Gün Sayısı** = 60, kaydet. Sonra Süre Uyarılarını Şimdi Gönder | Bu kez A'ya 9447'nin `localhost (44 gün kaldı)` (ya da 45) maili de gider; nedeninde "Domain sahibi: localhost:9447 (Server)" |
| 3.10 | Ayarlar > Mail Gönderim Geçmişi | Yukarıdaki maillerin hepsi alıcı, konu ve "gönderildi" durumuyla listelenir. Dışa Aktar (Excel) dosyasında Türkçe harfler doğru |
| 3.11 | (İsteğe bağlı, test ortamı gece açık kalıyorsa) ertesi sabah Mail Gönderim Geçmişi | 08:00 süre uyarıları ve 08:05 süresi geçmiş hatırlatmaları kendiliğinden gitmiştir; içerik düğmeyle gönderilenle aynıdır |

Uyarı penceresi Uyarı Eşiği (gün) ayarından gelir (varsayılan 30). Bir domainde Bildirim Gün Sayısı doluysa o domain için o sayı geçerlidir.
