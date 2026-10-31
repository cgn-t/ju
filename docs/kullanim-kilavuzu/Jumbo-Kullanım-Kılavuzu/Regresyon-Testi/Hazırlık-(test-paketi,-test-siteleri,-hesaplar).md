Regresyon testine başlamadan önce bir kez yapılır. Bütün bölümler (1–11) bu hazırlığı kullanır.

> **En kolay yol:** Test Jumbo'sunda REGRESSION_TOOLS=1 açıksa Regresyon Testi sayfasındaki **Test Hazırlığı** sekmesi bu sayfadaki test paketini, test sitelerini, ekipleri ve test hesaplarını tek düğmeyle hazırlar (bkz. *Regresyon Testi sayfasını kullanma*). O zaman bu sayfada yalnız **Mail adresleri** ve **Ekipler ve ayarlar**'daki E-posta (SMTP) ayarlarını yapmanız yeterlidir; aşağıdaki Docker ve Python yolları gerekmez.

Test canlıda değil, canlıya benzeyen bir **test Jumbo'sunda** yapılır (tercihen canlıdaki gibi MSSQL ve AD girişli). Boş ya da test verili bir veritabanı olabilir.

## Test paketi

Paket `regresyon-kilavuzu/test-paketi` klasöründe (zip: `jumbo-test-paketi.zip`). İçinde:

| Ne | Ne işe yarar |
|---|---|
| `sertifikalar/dosyalar/` | Ekrandan yükleyeceğiniz 13 sertifika dosyası ve 1 Excel dosyası (00–13). 14–25 numaralı dosyalar Bölüm 2 içindir |
| `sertifikalar/sunucu/` | Test sitelerinin kullandığı sertifikalar (elle açmanız gerekmez) |
| `test-sunucusu.py` | 9441–9447 portlarında 7 test sitesi açar. Yalnız Python 3 ister |
| `sertifika-uret.py` | Tüm sertifikaları yeniden üretir. Python 3 ve `cryptography` paketi ister |
| `sertifikalar/BILGI.txt` | Üretim tarihi, test sitesi adı ve PFX parolası |
| Dockerfile, docker-compose.yml, baslat.py | Test sitelerini Docker ile bir sunucuda açar; 9440'ta yönetim sayfası verir (Hazırlık, yol A) |
| gercek-site-testi.py | Gerçek internet adresleri için ağ kontrolü (madde 7.0). Yalnız Python 3 ister |

Paketteki hazır sertifikalar 18.10.2026'da `localhost` adıyla üretildi. "20 gün kala" sertifikaları 07.11.2026'da dolar. Test bu tarihten sonra ya da 28.10.2026'dan geç yapılacaksa sertifikaları yeniden üretin.

## Test sitelerini açma

Test siteleri, Jumbo test sunucusunun ulaşabildiği bir makinede çalışmalıdır. Bu makinenin testi yapan kişinin kendi bilgisayarı olması gerekmez. İki yol var; birincisi önerilir.

**A) Docker ile (önerilen).** Docker kurulu bir sunucuda, örneğin bir test sunucusunda, yapılır:

1. `test-paketi` klasörünü o sunucuya kopyalayın.
2. `docker-compose.yml` dosyasındaki `AD:` satırına, Jumbo sunucusunun bu makineye ulaştığı adı yazın (ör. `testsunucu.firma.local`). Bu ad DNS'te tanımlı olmalı ve Jumbo sunucusu bu makinenin 9440–9447 portlarına erişebilmelidir.
3. Klasörde `docker compose up -d --build` çalıştırın. İlk çalıştırmada internetten Python imajı ve iki paket indirilir. Sertifikalar bu adla üretilir ve sunucu yeniden başlasa da korunur.
4. Tarayıcıda `http://<ad>:9440` adresini açın. Bu sayfada sitelerin listesi, ekrandan yükleyeceğiniz dosyaların indirme bağlantıları, 9444'teki sertifikayı yenileyen düğme (madde 5.6) ve sertifikaları yeniden üretme düğmesi vardır. Dosyaları kendi bilgisayarınıza buradan indirin
5. Test bitince `docker compose down` çalıştırın. Sertifikaları da silmek isterseniz `docker compose down -v` kullanın.

**B) Python ile.** Docker yoksa aşağıdaki adımları izleyin:

1. Paketi o makineye kopyalayın.
2. Jumbo test sunucusunun kendisindeyseniz ve Jumbo `localhost` ile ona ulaşıyorsa adım 3'e geçin. Başka bir makinedeyseniz o makinenin adıyla sertifikaları yeniden üretin: `pip install cryptography` ve ardından `python3 sertifika-uret.py --ad <makine-adı>`.
3. `python3 test-sunucusu.py` çalıştırın. Pencere açık kalmalı. Ekranda 7 port ve "Test siteleri hazır" yazar.
4. Bu kılavuzda `localhost` geçen her yerde kullandığınız adı yazın: Docker'da AD satırındaki adı, Python'da 2. adımdaki adı. Ekrandaki mesajlarda da localhost yerine bu ad görünür.

| Port | Test sitesi ne sunar |
|---|---|
| 9441 | Doğru sertifika ve ara sertifika (sorunsuz site) |
| 9442 | Başka bir sitenin sertifikası (`baska-site.jumbo-test.local`) |
| 9443 | Doğru sertifika, ama ara sertifikayı göndermez |
| 9444 | Yenileme testi: önce 25 gün kala eski sertifika, `--yenilenmis` ile açılınca (Docker'da 9440 sayfasındaki düğmeyle) yeni sertifika |
| 9445 | 20 gün kala dolacak sertifika |
| 9446 | Süresi 5 gün önce dolmuş sertifika |
| 9447 | 45 gün kala dolacak sertifika |

## Hesaplar (sistem yöneticisi hazırlar)

| Hesap | Rol | Ekip üyeliği | Not |
|---|---|---|---|
| Yönetici hesabı | Yönetici | — | Hazırlık ve 1–5. bölümler bununla yapılır |
| Ödeme editörü | SY Ekip | Ödeme Sistemleri SY | AD hesabının adında **i** harfi olmalı (ör. ismail.celik) |
| İletişim editörü | SY Ekip | İletişim Kanalları SY |  |
| İzleyici | İzleyici | Ödeme Sistemleri SY |  |
| Rolsüz hesap | Yetkisiz | — |  |

Rol ve üyelik Ayarlar > Kullanıcılar ve Ayarlar > Ekip Üyelikleri'nden verilir. Bir AD hesabı Jumbo'da ancak ilk girişten sonra listede görünür.

## Mail adresleri

Okuyabildiğiniz **4 adres** gerekir (dağıtım listesi ya da takma ad da olur). Bu kılavuzda A, B, C ve Y diye geçerler. Test Jumbo'su test mail sunucusuna bağlı olmalıdır.

## Ekipler ve ayarlar (Yönetici hesabıyla)

Ayarlar > Ekipler'de "Ekip Ekle" ile dört SY ekibi açın. Adları Türkçe harfleriyle aynen yazın, çünkü Excel dosyası bu adları kullanır.

| Ekip adı | Tip | Bildirim e-postası |
|---|---|---|
| Ödeme Sistemleri SY | SY | A |
| İletişim Kanalları SY | SY | B |
| Mobil Uygulamalar SY | SY | C |
| Mailsiz Test SY | SY | boş bırakın |

Ayarlar > E-posta (SMTP) sekmesinde şunları kontrol edin. Sol sütun Jumbo'nun ilk kurulumdaki değeridir; sağ sütun bu test için olması gerekendir.

| Ayar | Varsayılan (ilk kurulum) | Bu testte |
|---|---|---|
| E-posta Bildirimleri Etkin | Kapalı | Açık |
| SMTP Sunucusu, Port, Bağlantı Güvenliği | Boş, 25, Yok | Test mail sunucusunun bilgileri |
| Uyarı Eşiği (gün) | 30 | 30 |
| Yedek/Varsayılan Adres | Boş | Y |
| Günlük Otomatik Tarama (her sabah 08:00) | Açık | Açık |
| Günlük Süresi Geçmiş Hatırlatması (her sabah 08:05) | Açık | Açık |
| Tekrar-Önleme Etkin / Tekrar Aralığı | Açık / 3 saat | Dokunmayın |

Ayarlar > İptal (OCSP/CRL) sekmesindeki "Gece iptal denetimi etkin" varsayılan olarak **kapalıdır**. Bu bölümde kapalı kalsın.

## Bölüm 8–11 için ek kontrol
Test paketinin `sertifikalar/dosyalar/` klasöründe 14–25 numaralı dosyalar olmalıdır. Yoksa paketin eski sürümü kurulmuştur: güncel paketi kurun ve Hazırlık'ı yeniden yapın, çünkü tüm test sertifikaları aynı anda üretilir.
