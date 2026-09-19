# JUMBO — Kullanıcı Kılavuzu

JUMBO; SSL sertifikalarınızı, domainlerinizi, uygulamalarınızı ve bunlar arasındaki
bağımlılıkları tek yerden takip etmenizi sağlayan bir platformdur. Bu kılavuz, uygulamayı
günlük kullanımda nasıl kullanacağınızı sayfa sayfa anlatır.

## 1. Giriş Yapma

Giriş ekranında kullanıcı adı ve şifrenizle oturum açarsınız.

- **Kurumsal (AD/LDAP) hesabınız varsa**: aynı kullanıcı adı/şifrenizle giriş yapın — JUMBO
  şirket dizininizde sizi arar ve grubunuza göre otomatik rol atar.
- **Lokal hesabınız varsa**: yöneticinizin size verdiği kullanıcı adı/şifre ile giriş yapın.
- Giriş yapamıyorsanız: kullanıcı adı/şifrenizi kontrol edin; yine olmuyorsa BT/JUMBO
  yöneticinize başvurun (hesabınız kilitli/pasif olabilir ya da uygulama geçici olarak
  erişilemez durumda olabilir).

### Roller ne anlama gelir?

| Rol | Ne yapabilir |
|---|---|
| **Görüntüleyici (viewer)** | Yalnızca kendi ekibinin verilerini görüntüler, değişiklik yapamaz |
| **Editör (editor)** | Kendi ekibinin kapsamındaki verileri ekleyip düzenleyebilir |
| **Tüm-Görüntüleyici (allviewer)** | Sistemdeki HER ŞEYİ görür, ama hiçbir şeyi değiştiremez |
| **Yönetici (admin)** | Her şeyi görür ve düzenler; Ayarlar sayfasına erişir |

Hangi domain/sertifikaları görüp göremeyeceğiniz, **hangi ekibin üyesi olduğunuza** bağlıdır
— bunu yönetici Ayarlar > Ekip Üyelikleri'nden ayarlar.

## 2. Anasayfa (Dashboard)

Genel duruma hızlı bakış: SY takımlarına göre domain sayıları ve bitiş tarihine göre
sıralanmış sertifika listesi. Bitmesine **30 gün veya daha az** kalan sertifikalar rozetle
vurgulanır.

## 3. SSL Sertifikaları

Sertifika envanterinizin ana ekranı. İki görünüm arasında geçiş yapabilirsiniz: **kart** veya
**tablo**. Ağaç yapısı sertifikaların hiyerarşisini gösterir (Root ▸ Intermediate ▸ Leaf).

**Yeni sertifika ekleme** ("Yeni Sertifika Ekle" butonu, sağ üst):
- **Dosyadan İçe Aktar** sekmesi: PEM, fullchain PEM, DER veya PFX dosyası yükleyin — alanlar
  (CN, SAN, geçerlilik tarihleri, seri no vb.) otomatik çıkarılır, zincir mevcut sertifikalara
  otomatik bağlanır. Kaydetmeden önce bir **önizleme** gösterilir; "Onaylıyorum, İçe Aktar"
  ile kesinleştirirsiniz.
- **Manuel Ekle** sekmesi: dosyanız yoksa alanları elle girebilirsiniz.
- Aynı sertifika (fingerprint eşleşmesi) zaten sistemdeyse mükerrer eklenmez, uyarılırsınız.

**Yenilenen bir sertifikayı içe aktarırken**: JUMBO bunun eskisinin yenisi olduğunu otomatik
anlar (aynı anahtar ya da aynı CN+CA) ve size onay için bir "devir" önerir — onaylarsanız tüm
bağlı domain/uygulama eşlemeleri otomatik yeni sertifikaya taşınır, eski sertifika pasife
alınır. (Bkz. §7 Devir Önerileri.)

**Diğer işlemler**: PEM kopyalama/indirme, pasif sertifikaları gösterme/gizleme, kalıcı
silme (dikkat: geri alınamaz), arama/filtre.

## 4. Domainler

Domain envanteri — kart veya tablo görünümü, durum filtresi ve kolon filtreleriyle.

**Bir domaine sertifika bağlama**: domain detayından "Server" (sunulan sertifika) veya
"Client/Trusted" (güvenilen sertifika) olarak bir sertifika eşleyebilirsiniz.

**Sertifikasız domainler için "Manuel Bitiş Tarihi"**: eğer bir domainin sertifikası JUMBO
envanterinde yoksa (ör. üçüncü taraf yönetiyor), domain formundaki **"Manuel Bitiş Tarihi"**
alanına bitiş tarihini elle girebilirsiniz — bu tarihe göre de süre yaklaşınca/geçince ilgili
SY ekibine bilgilendirme maili gider (aynı sertifika bazlı uyarılar gibi).

**"Bildirim Eşiği (gün)"**: bu domain için varsayılan 30 gün yerine kaç gün kala
uyarılmak istediğinizi özelleştirebilirsiniz (`notify_days`).

**"Şimdi Doğrula" (Canlı Doğrulama)**: domain detayındaki bu buton, domain:port'a gerçekten
bağlanıp sunucunun O ANDA hangi sertifikayı sunduğunu kontrol eder ve JUMBO'daki kayıtla
karşılaştırır. Olası sonuçlar:
- **Eşleşiyor** — kayıt güncel.
- **Uyuşmuyor** — ya "yenilendi ama deploy edilmedi" ya da süresi dolmuş bir sertifika
  sunuluyor demektir; tek tıkla "Canlıdaki Sertifikayı İçe Aktar ve Eşle" ile düzeltebilirsiniz.
- **Envanter dışı** — sunucudaki sertifika JUMBO'da hiç kayıtlı değil.
- **Erişilemedi** / **Kontrol edilemez** (ör. wildcard) — teknik nedenle kontrol yapılamadı.
- Bu kontrol her sabah 07:00'de tüm domainler için otomatik de çalışır.

## 5. Sertifika Haritası

Sertifika, domain ve uygulamalar arasındaki bağlantıları görsel bir diyagram (React Flow)
üzerinde gösterir. Tür ve bağlantı filtreleri, mini harita ve bir node'a tıklayınca detay
paneli mevcuttur. Karmaşık bağımlılıkları görselleştirmek için kullanışlıdır.

## 6. Uygulamalar

Sunucu/uygulama envanteri: her uygulamanın bağlı olduğu domainler, diğer uygulamalara olan
bağımlılıkları (mTLS vb.), güvendiği (trust store) sertifikalar ve etiketleri buradan
yönetilir.

- **Bağımlılık ekleme/silme**: bir uygulamanın başka bir uygulamaya/sertifikaya olan
  bağımlılığını tanımlarsınız.
- **Trust Store**: uygulamanın güvendiği (istemci olarak kabul ettiği) sertifikaları
  buradan ekler/kaldırırsınız — bu sertifikalardan biri değişince de devir önerisi/bildirim
  akışı devreye girer.
- **Etiketler**: uygulamaları serbest metin etiketlerle sınıflandırabilirsiniz.

## 7. Devir Önerileri (Proposals)

Bir sertifika yenilendiğinde veya bir trust store kaydı için yeni bir aday bulunduğunda,
JUMBO bunu otomatik algılayıp **ilgili SY ekibinin onayına** sunar (sayfa Ayarlar>Erişim'de
kapalıysa görünmeyebilir — yöneticinize danışın).

Her öneri satırında eski ve yeni sertifika karşılaştırması gösterilir:
- **Onayla** — eşleme(ler) yeni sertifikaya taşınır, eski sertifika pasife alınır.
- **Reddet** — öneri reddedilir, hiçbir şey değişmez.
- Karar verilene kadar, ilgili ekibe **günlük hatırlatma maili** gönderilir (Ayarlar > SMTP'de
  saati ayarlanabilir).

## 8. Uyum (Policy)

Tanımlı uyum politikası kurallarına göre her sertifikanın **uyumlu**/**uyumsuz** olup
olmadığını değerlendirir (ör. minimum anahtar uzunluğu, izin verilen imza algoritması gibi
kurallar — kurallar yönetici tarafından Ayarlar > Uyum'da tanımlanır).

## 9. Keşif (Discovery)

Ağınızda tanımlı hedef adres/port aralıklarını tarayarak JUMBO envanterinde **kayıtlı
olmayan ("bilinmeyen"/"shadow")** sertifikaları bulur. Her bulunan sertifika için:
- **Envantere al** — sertifikayı JUMBO'ya normal bir kayıt olarak eklersiniz.
- **Yok say** — bilinçli olarak envanter dışı bırakmak istediğiniz sertifikalar için.

Tarama hedefleri ve zamanlaması Ayarlar > Keşif'ten yönetilir; günlük otomatik tarama da
çalışır.

## 10. Dağıtım (Deployments)

Jenkins tetiklemeli dağıtım akışlarını (ör. bir sertifikayı sunucuya deploy eden Jenkins
job zinciri) görsel bir akış editöründe (DAG) tasarlayıp çalıştırabileceğiniz sayfa.

- Bir akış birden çok **adımdan** oluşur, her adım bir Jenkins job'ına (klasör/ns-job
  desteğiyle) karşılık gelir.
- **Başlat** ile akışı çalıştırırsınız; her adımın durumu (bekliyor/çalışıyor/başarılı/
  başarısız) canlı güncellenir.
- Bir adım başarısız olursa **tüm akışı değil, yalnız o adımı** yeniden tetikleyebilirsiniz.
- "Çalıştırmalar" sekmesinden geçmiş tüm dağıtımları, konsol loglarını (Jenkins'te yeni
  sekmede açılır) görüntüleyebilirsiniz.
- Bir akışı "Başka bir uygulamaya kopyala" ile başka bir uygulama için yeniden
  kullanabilirsiniz.

## 11. Bildirim E-postaları

JUMBO, süresi yaklaşan/geçen sertifikalar ve devir onayı bekleyen öneriler için otomatik
e-posta gönderir. Mail kimlere gider:

1. Sertifikayı **oluşturan ekip**,
2. Sertifikanın bağlı olduğu **domainlerin sahibi SY ekipleri**,
3. Sertifikanın **client (trust store)** olarak bağlı olduğu uygulamaların SY ekipleri,
4. Sertifikasız, yalnız **Manuel Bitiş Tarihi** girilmiş domainler için ilgili domain SY ekibi.

Aynı ekip birden fazla nedenle alıcıysa TEK mail alır, gövdede tüm nedenler listelenir. Aynı
konu için kısa sürede tekrar mail gönderilmez (tekrar-önleme penceresi Ayarlar>SMTP'de
ayarlanır).

### Mail Gönderim Geçmişi (Ayarlar, yalnız yönetici)

Gönderilen/gönderilemeyen tüm bildirim maillerinin kaydı burada tutulur — durum (Gönderildi/
Kuyrukta/Başarısız), kanal, alıcı, konu.

**Bir satıra tıklayınca** açılan detay panelinde şunları görürsünüz:
- Konunun tam metni ve güncel durumu,
- **Kuyruğa Alınma** ve **Gerçek Gönderim** zamanları ayrı ayrı (bir mail önce kuyruğa
  girip sonra gerçekten gönderilmiş/başarısız olmuşsa bu ikisi farklı olabilir — geçmiş artık
  gerçek teslim durumunu yansıtır, yalnızca "kuyruğa alındı" anını değil),
  - Ayrıca kalan gün, alıcı, ilgili sertifika/domain, hata mesajı (varsa) ve deneme sayısı,
- Mail hâlâ kuyrukta/başarısızsa gövdesinin **HTML önizlemesi** veya **düz metin** hâli
  (başarıyla gönderilmiş eski mailler için gövde saklanmaz, yalnız özet bilgiler tutulur).

## 12. Ayarlar (yalnız yönetici)

Sol menüdeki sekmeler:

| Sekme | Ne için |
|---|---|
| Kullanıcılar | Hesap oluşturma/düzenleme, rol atama |
| Ekipler | SY/UG ekiplerini oluşturma ve yönetme |
| Ekip Üyelikleri | Kullanıcı ↔ ekip ilişkisi — **veri görme kapsamını belirler** |
| Erişim | Uyum / Devir Önerileri / Keşif / Dağıtım sayfalarının kimlere görüneceği |
| LDAP / Active Directory | Kurumsal dizinle kimlik doğrulama ayarları |
| E-posta (SMTP) | Bildirim maillerinin sunucu ayarları, uyarı eşiği, tekrar-önleme, kuyruk |
| Mail Gönderim Geçmişi | §11'de anlatılan geçmiş ve detay ekranı |
| Slack / Microsoft Teams / Webhook / ServiceNow / Jira / Zoom / Jabber | Süre uyarılarının ek kanallara (sohbet, olay kaydı, genel webhook) yönlendirilmesi |
| Keşif | Ağ tarama hedefleri ve zamanlaması |
| CT (crt.sh) | Certificate Transparency log izleme ayarları |
| Uyum | Uyum politikası kurallarının tanımı |
| İptal (OCSP/CRL) | İptal durumu denetim ayarları |
| Etiketler | Uygulama etiket kataloğu |
| Vault (Hazırlık) | HashiCorp Vault PKI entegrasyonu (salt-okunur, hazırlık aşaması) |
| Jenkins | Dağıtım sayfası için Jenkins bağlantı bilgileri |
| Audit Log | Tüm değişikliklerin denetim kaydı — filtreleme ve CSV dışa aktarma |

## 13. Sık Karşılaşılan Sorunlar

- **Giriş yapamıyorum**: kullanıcı adı/şifreyi kontrol edin; kurumsal hesapsa AD/LDAP
  ayarlarında bir sorun olabilir; yine de olmuyorsa yöneticinize başvurun (uygulama geçici
  olarak erişilemez durumda olabilir).
- **Beklediğim domain/sertifikayı göremiyorum**: muhtemelen o verinin ait olduğu ekibin üyesi
  değilsinizdir — yöneticinizden Ekip Üyeliği eklemesini isteyin.
- **Devir Önerileri / Uyum / Keşif / Dağıtım sayfasını göremiyorum**: bu sayfalar Ayarlar>
  Erişim'den açılana kadar yalnız yönetici/tüm-görüntüleyiciye görünür.
- **Bildirim maili gelmiyor**: önce mailin gerçekten gitmiş mi diye Ayarlar > Mail Gönderim
  Geçmişi'nden ilgili kaydı arayın; "Başarısız" ise hata mesajını yöneticinize iletin.
- **"Şimdi Doğrula" hep "Erişilemedi" diyor**: JUMBO'nun o domain:port'a ağ erişimi yoktur
  (güvenlik duvarı/DNS) — bu JUMBO'daki bir hata değil, ağ erişilebilirliği sorunudur.
