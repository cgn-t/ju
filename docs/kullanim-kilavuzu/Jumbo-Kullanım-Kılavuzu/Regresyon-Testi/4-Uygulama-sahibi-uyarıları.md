Regresyon Test Kılavuzu, Bölüm 1, madde 4. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın.

Yönetici hesabıyla. Bir uygulamanın sahibi (uygulamanın SY ekibi), uygulamanın Bağlı Domain'indeki sertifika ve trust store'undaki (Trusted) sertifikalar dolarken uyarılır. Şirkette mTLS kullanılmadığı için mTLS adımları bu kılavuzda yok.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 4.1 | Uygulamalar > yeni uygulama: Uygulama Adı = `Mobil Şube`, Sunucu Adı = `mobilsrv01`, SY Takımı = Mobil Uygulamalar SY, Bağlı Domain = `localhost:9445` | Uygulama eklenir, adındaki Ş doğru görünür |
| 4.2 | Uygulamanın "Trusted Sertifikalar (trust store)" bölümüne `trusted-20-gun-kala.jumbo-test.local` ve `trusted-suresi-gecmis.jumbo-test.local` ekleyin | İkisi de listede, bitiş tarihleriyle |
| 4.3 | Ayarlar > E-posta (SMTP) > **Süre Uyarılarını Şimdi Gönder** | 3.6'daki maillere ek olarak C'ye iki mail: `localhost (19 gün kaldı)`, nedeninde "Uygulama sahibi (bağlı domain localhost:9445): Mobil Şube". `trusted-20-gun-kala.jumbo-test.local`, nedeninde "Uygulama trust store'unda (trusted): Mobil Şube". A aynı sertifikalar için yine kendi mailini alır |
| 4.4 | C'ye gelen iki maili açın | Düzen 3.7'deki maillerle aynı. Metinde "Trusted" kelimesi geçer |
| 4.5 | **Süresi Geçenleri Şimdi Gönder** | `trusted-suresi-gecmis` için yalnız A'ya mail gider. C'ye bu sertifika için **mail gitmez** (Trusted sertifikanın sahibine yalnız süresi dolana kadar mail gider; bilinçli karar) |
| 4.6 | Mobil Şube'nin Durum'unu Pasif yapıp kaydedin, Süre Uyarılarını Şimdi Gönder. Sonra tekrar Aktif yapın | Pasif uygulamanın sahibine (C) uyarılar gitmeye devam eder |
| 4.7 | SSL Sertifikaları'nda `localhost:9445`'e bağlı `localhost` sertifikasını (bitişi ~19 gün) **Pasife Al** | Pasife alınmaz: "Bu sertifika şu domain(ler)e SERVER olarak bağlı: localhost:9445. Pasife almadan önce server bağlantısını Değişiklik Talebi ile yeni sertifikaya taşıyın." |
| 4.8 | `trusted-20-gun-kala.jumbo-test.local` sertifikasını **Pasife Al** | Pasife alınır (yalnız Trusted olarak bağlı sertifikaya izin verilir). Bu işlem için mail gitmez. Sonraki Şimdi Gönder'de bu sertifika için uyarı gitmez |
