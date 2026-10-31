Regresyon Test Kılavuzu, Bölüm 2, madde 8. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın. Jumbo'daki **Regresyon Testi** sayfasında bu adımlar "Uygulamalar, trust store, sertifika yönetimi, uyum ve iptal" bölümünde **B2-8.1**, **B2-8.2** … kimlikleriyle listelenir.

Bir uygulama iki şekilde başka sertifikalara bağlıdır. Ekranda ikisinin de adı geçer:

- **Dış Bağımlılıklar (trusted):** uygulamanın bağlandığı başka bir domain. Jumbo, o domainin sertifikasını kendiliğinden izler. O sertifika yenilenince uygulamanın ekibine bir değişiklik talebi gider. Değişiklik Talepleri ekranında bu satırın Domain sütununda "Trusted bağlantı" yazar.
- **Trusted Sertifikalar (trust store):** uygulamanın güvendiği sertifikalar. Birden çok olabilir. Yenisi eklenince eskisi kendiliğinden çıkmaz.

**Hazırlık:** Yönetici hesabıyla. Domainler'de `localhost:9441` (Ödeme Sistemleri SY) ve `localhost:9446` (İletişim Kanalları SY) kayıtlı olmalı; Bölüm 1, madde 2'de eklenmişlerdir. Yoksa aynı şekilde ekleyin. Test paketindeki `25-sunucu-yenisi.pem` dosyası, 9446'daki süresi geçmiş sertifikanın yenisidir. Bu bölümde 9440 sayfasındaki 9444 düğmesine dokunmayın.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 8.1 | Uygulamalar > **Yeni Ekle**: Uygulama Adı = `Ödeme API`, Sunucu Adı = `odemesrv01`, SY Takımı = Ödeme Sistemleri SY, Bağlı Domain = `localhost:9441`. **Ekle** | Listede Ödeme API, Domain `localhost:9441`, SY Ödeme Sistemleri SY, Durum Aktif |
| 8.2 | Ödeme API satırında kalem (düzenle) simgesi. "Dış Bağımlılıklar (trusted)" altında Hedef Domain = `localhost:9446`, **Ekle** | Listeye `localhost:9446` gelir. Altında "Trusted: localhost [..]" ile 9446'daki sertifikanın adı ve anahtar kimliğinin başı yazar. Sertifikayı sizin seçmeniz gerekmez |
| 8.3 | Hedef Domain listesini açın | `localhost:9441` listede yoktur, çünkü uygulama kendi domainine bağımlı olamaz |
| 8.4 | Hedef Domain = `localhost:9446` seçip tekrar **Ekle** | "Bu bağımlılık zaten kayıtlı" mesajı; listede ikinci satır oluşmaz |
| 8.5 | İletişim editörü ile girin, Uygulamalar | Ödeme API listede görünmez (başka ekibin uygulaması) |
| 8.6 | Yönetici hesabıyla SSL Sertifikaları > Yeni Ekle > Dosyadan İçe Aktar: `25-sunucu-yenisi.pem`, **Oluşturan Ekip = İletişim Kanalları SY**, Ortam = Test. Önizlemedeki eski sertifika listesine bakın, sonra "değişiklik talebi oluştur" işaretini **kaldırın** (talebi 8.7'de editör açacak) ve İçe Aktar | Önizlemede "Yeniden anahtarlama → localhost" ve "Bu ada ve CA'ya sahip … eski sertifika var. Yeni sertifika hangisinin yerine geçiyor?" yazısıyla tüm eski `localhost` sertifikaları listelenir. Hiçbiri seçili gelmez. Her satırda bitiş ve bağlantılar yazar; süresi geçmiş olanın satırında "localhost:9446 (server), Ödeme API (istemci sertifikası)". Kaydedince yalnız "1 sertifika eklendi" yazar ve yeni bir `localhost` sertifikası eklenir (yaklaşık 299 gün kaldı) |
| 8.7 | Ödeme editörü ile girin. SSL Sertifikaları'nda 9446'daki eski `localhost` sertifikasının (süresi geçmiş) göz simgesini açın. "Değişiklik Talebi Oluştur" bölümünde Yeni sertifika = 8.6'da eklenen yeni sertifika, **Değişiklik Talebi Oluştur** | "2 değişiklik talebi oluşturuldu — ilgili SY ekiplerinin onayı bekleniyor" |
| 8.8 | Aynı hesapla Değişiklik Talepleri | Yalnız bir satır görünür: ESKİ localhost → YENİ localhost, Domain sütununda "Trusted bağlantı", SY Ekip Ödeme Sistemleri SY |
| 8.9 | İletişim editörü ile Değişiklik Talepleri | Yalnız bir satır: Domain `localhost:9446`, SY Ekip İletişim Kanalları SY. Trusted bağlantı satırı bu hesapta görünmez |
| 8.10 | Ödeme editörü ile Trusted bağlantı satırını **Onayla** | Satır listeden çıkar. Uygulamalar > Ödeme API düzenle: Dış Bağımlılıklar'da artık yeni sertifika yazar (anahtar kimliği değişmiştir). Eski sertifika henüz aktif kalır, çünkü 9446 domaini hâlâ ona bağlı |
| 8.11 | İletişim editörü ile 9446 satırını **Onayla** | Domainler > `localhost:9446` detayında yeni sertifika (~299g) görünür. SSL Sertifikaları'nda eski sertifika artık listede yoktur; "Pasifleri göster" açılınca pasif olarak görünür |
| 8.12 | Ödeme editörü ile Ödeme API düzenle. "Trusted Sertifikalar (trust store)" altında Sertifika = `trusted-20-gun-kala.jumbo-test.local` (Bölüm 1'de yüklendi; yüklenmediyse önce `10-trusted-20-gun-kala.pem` dosyasını Ödeme Sistemleri SY ile yükleyin), **Ekle** | Sertifika mor kalkan simgesiyle listeye gelir |
| 8.13 | Aynı sertifikayı tekrar ekleyin | "Bu sertifika zaten trust store'da" mesajı |
| 8.14 | Yönetici hesabıyla `24-trusted-yenisi.pem` dosyasını yükleyin (Oluşturan Ekip = Ödeme Sistemleri SY). Önizlemede "Eskinin bağlı olduğu uygulamalar: Ödeme API (trust store)" ve işaretli "değişiklik talebi oluştur" görünür; bu adımda talebi editör açacağı için işareti kaldırıp İçe Aktar (mesaj: "1 sertifika eklendi"). Sonra Ödeme editörü ile eski `trusted-20-gun-kala` sertifikasının (19 gün kalan) detayında Yeni sertifika = yeni yüklenen (~299 gün), **Değişiklik Talebi Oluştur** | "1 değişiklik talebi oluşturuldu". Değişiklik Talepleri'nde satırda "trust store'a ekle — eski kalır", Domain sütununda "Ödeme API (trust store)", SY Ekip Ödeme Sistemleri SY |
| 8.15 | Ödeme editörü ile bu talebi **Onayla** | Ödeme API'nin trust store'unda iki sertifika görünür: eskisi ve yenisi ("yeni sertifika (değişiklik talebi onayı ile eklendi)"). Eski sertifika aktif kalır |
| 8.16 | Ödeme editörü ile trust store'da eski sertifikanın satırındaki çöp kutusu, sonra **Kaydet** | Yalnız yeni sertifika kalır. Eski sertifika SSL Sertifikaları'nda aktif kalır (silinmez, pasife alınmaz) |
| 8.17 | Analiz > Sertifika Haritası > **İlişkiler** | Ödeme API, `localhost:9441`'e ve `localhost:9446`'ya bağlı görünür; 9446 bağlantısı turuncu kesikli oktur |

Not: 8.14'te İletişim editörü aynı talebi açmaya çalışırsa "Değişiklik talebini yalnız sertifikanın bağlı olduğu domain/uygulamaların SY ekibi üyesi veya admin tetikleyebilir" mesajını alır. Bu doğru davranıştır, çünkü sertifika onun ekibinin trust store'unda değildir.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 8.18 | Yönetici hesabıyla SSL Sertifikaları'nda `iptal-bilgisi-yok.jumbo-test.local` sertifikasını Pasife Al (11. bölümden önce yapıyorsanız önce `16-iptal-bilgisi-yok.pem` dosyasını yükleyin; 11. bölümden önce Aktifleştir ile geri alın). Sonra Ödeme API düzenle > Trusted Sertifikalar > Sertifika listesini açın | Pasif sertifika listede yoktur. Trust store'da zaten olan sertifika da listede yoktur |
| 8.19 | Uygulamalar > **Yeni Ekle**: Uygulama Adı = `Yeni Test Uygulaması`, Sunucu Adı = `yenisrv01`, SY Takımı = Ödeme Sistemleri SY. Aşağıdaki "Trusted Sertifikalar (trust store)" alanında bir trusted sertifika seçip yanındaki **Ekle**, sonra pencerenin altındaki **Ekle** | Uygulama eklenir. Düzenle açılınca seçtiğiniz sertifika trust store'da görünür |
