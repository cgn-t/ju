"""Kullanım Kılavuzu'nun Jumbo'yla gelen sayfaları (Markdown).

Açılışta wiki.ensure_wiki_seed() eksik olanları ekler; hiç elle düzenlenmemiş sayfaları buradaki
güncel metinle yeniler. Yönetici bir sayfayı düzenlediyse ya da sildiyse ona dokunulmaz.
Ekranda görünen adlar (düğme, sekme, menü) ekrandakiyle birebir aynı yazılmalı: AI asistanı
"nasıl yapılır" sorularını bu metinlerden cevaplar.

Desteklenen biçim: ## başlık, ### alt başlık, - madde, 1. adım, **kalın**, `kod`,
[bağlantı](/domains) ve "> " ile başlayan not kutusu.
"""

BUILTIN_PAGES: list[dict] = [
    # ------------------------------------------------------------------ Başlarken
    {
        "slug": "jumbo-nedir", "category": "Başlarken", "sort_order": 100,
        "title": "Jumbo nedir?",
        "body": """Jumbo, bankadaki SSL sertifikalarının ve bu sertifikaları kullanan domainlerin ve uygulamaların takip edildiği uygulamadır. Amaç, hiçbir sertifikanın habersiz süresinin dolmamasıdır.

## Jumbo ne yapar?
- Sertifikaları (Leaf, Intermediate, Root) ve aralarındaki zinciri tutar.
- Her sertifikanın hangi domainde ve hangi uygulamada kullanıldığını gösterir.
- Süresi yaklaşan sertifikalar için ilgili SY ekiplerine mail atar.
- Domainlere her gün bağlanıp sunucunun gerçekten hangi sertifikayı sunduğunu kontrol eder (Canlı Doğrulama).
- Bir kaydın değişmesi gerektiğinde kaydı kendisi değiştirmez: değişiklik talebi açar, domainin SY ekibi onaylayınca uygular.

## Sol menü
- **Anasayfa**: genel sayılar ve yaklaşan bitişler.
- **Genel Durum** (Yönetici ve Genel İzleyici) ya da **Ekibim** (Ekip Editörü ve Ekip İzleyici).
- **SSL Sertifikaları**, **Domainler**, **Uygulamalar**: envanter ekranları.
- **Analiz**: Sertifika Haritası, Uyum, Keşif.
- **İşlemler**: Değişiklik Talepleri, Dağıtım, Tüm Çalıştırmalar, Sistem Sağlığı.
- **Yardım**: bu Kullanım Kılavuzu.

Sol alttaki adınıza tıklayınca Profilim, Ayarlar (yöneticide) ya da Etiketler, koyu tema ve Çıkış Yap seçenekleri açılır.

Bazı menüler rolünüze ya da yöneticinin Ayarlar > Erişim'deki seçimine göre görünmeyebilir. Ayrıntı için [Roller ve yetkiler](/wiki/roller-ve-yetkiler) sayfasına bakın.

> Sağ alttaki AI simgesine tıklayıp Jumbo'daki kayıtları ya da bir işin nasıl yapılacağını sorabilirsiniz. Bkz. [AI asistanını kullanma](/wiki/ai-asistani).""",
    },
    {
        "slug": "roller-ve-yetkiler", "category": "Başlarken", "sort_order": 110,
        "title": "Roller ve yetkiler",
        "body": """Jumbo'da herkesin bir rolü vardır. Rolü yönetici Ayarlar > Kullanıcılar ekranında verir. LDAP ile giriş yapanlarda rol, AD grubundan da gelebilir.

## Roller
- **Yönetici**: her şeyi görür ve düzenler. Sertifikayı pasife alma, silme, Zincir Kontrolü ve Ayarlar yalnız yöneticidedir.
- **Ekip Editörü**: üyesi olduğu SY ekiplerinin domainlerini, sertifikalarını ve uygulamalarını görür ve düzenler. Ekibinin değişiklik taleplerini onaylayabilir.
- **Ekip İzleyici**: üyesi olduğu SY ekiplerinin kayıtlarını görür, değiştiremez.
- **Genel İzleyici**: her şeyi görür, hiçbir şeyi değiştiremez.
- **Yetkisiz**: rol atanmamıştır, hiçbir şey göremez.

## Ekip üyeliği neden önemli?
Ekip Editörü ve Ekip İzleyici yalnız üyesi oldukları SY ekiplerinin kayıtlarını görür. Üyelik yoksa ekranlar boş görünür. Üyeliği yönetici Ayarlar > Ekip Üyelikleri'nden verir.

Başka bir ekibin sertifikasını düzenlemeye çalışırsanız "Bu sertifika başka bir ekibe ait" uyarısı çıkar. Kendi ekibinizin ve hiçbir ekibe ait olmayan sertifikaları düzenleyebilirsiniz.

## Sayfa görünürlüğü
Uyum, Değişiklik Talepleri, Keşif ve Dağıtım sayfalarını yönetici, Ekip Editörü ve Ekip İzleyici için Ayarlar > Erişim'den açıp kapatabilir. Değişiklik Talepleri menüde kapalı olsa bile SY ekibi üyeleri kendi ekiplerinin taleplerine domain penceresindeki **Onaya git** bağlantısıyla ulaşır.

## AI asistanı
AI asistanı, Jumbo'daki uygulama verisinin tamamını rolünüzden bağımsız okuyabilir (yönetici bunu Ayarlar > AI Asistanı'ndan kapatabilir). Kişisel bilgiler (e-posta, telefon, fotoğraf, şifre, giriş kayıtları) ve sistem ayarları AI'a hiç verilmez.""",
    },
    {
        "slug": "ai-asistani", "category": "Başlarken", "sort_order": 120,
        "title": "AI asistanını kullanma",
        "body": """Her sayfanın sağ altındaki AI simgesine tıklayınca sağdan bir sohbet paneli açılır. Panel açıkken sayfayı kullanmaya devam edebilirsiniz.

## Neler sorabilirsiniz?
- **Kayıtlar**: "Önümüzdeki 30 günde süresi dolacak sertifikalar hangileri?", "web.ornek.com hangi uygulamalarda kullanılıyor?", "BBB ekibinin bekleyen değişiklik talepleri neler?"
- **Geçmiş**: "Geçen hafta web.ornek.com'da ne değişti, kim değiştirdi?"
- **Kullanım**: "Yeni domain nasıl eklenir?", "Değişiklik talebini kim onaylar?" AI bu soruları bu kılavuzdan cevaplar ve ilgili sayfanın bağlantısını verir.
- **Genel bilgi**: "CSR nedir?", "Intermediate sertifika ne işe yarar?"

## Nasıl çalışır?
- AI hiçbir kaydı değiştirmez, yalnız okur. Değişiklik gerekiyorsa hangi ekrandan yapacağınızı söyler.
- Cevaptaki bağlantılar ilgili kaydı ya da kılavuz sayfasını açar.
- Cevabın altındaki **Baktığı yerler** satırı, AI'ın hangi verilere baktığını gösterir.
- Kişisel bilgiler (e-posta, telefon, fotoğraf, şifre, giriş kayıtları) ve sistem ayarları AI'a verilmez.
- Her soru Audit Log'a "AI sorusu" olarak yazılır. Kişi başı günlük soru sınırını yönetici belirler.

## Panel düğmeleri
- **Yeni sohbet**: konuşmayı temizler.
- **Genişlet / Daralt**: paneli büyütür ya da küçültür.
- **Hazır sorular**: boş sohbette kart olarak görünür; sohbet sürerken yazma alanındaki ampul simgesinden açılır.
- **Kapat** ya da Esc: paneli kapatır. Sohbet aynı tarayıcı sekmesinde saklanır.
- Enter soruyu gönderir, Shift+Enter yeni satır açar.

> AI yanılabilir. Önemli bir karardan önce kaydı açıp kontrol edin.""",
    },

    # ------------------------------------------------------------------ Sertifikalar
    {
        "slug": "sertifika-ekleme", "category": "Sertifikalar", "sort_order": 200,
        "title": "Sertifika ekleme",
        "body": """Sertifika eklemek için Yönetici ya da Ekip Editörü olmanız gerekir.

## Dosyadan içe aktarma (önerilen)
1. [SSL Sertifikaları](/certificates) ekranında **Yeni Ekle**'ye basın.
2. **Dosyadan İçe Aktar (PEM / DER / PFX)** sekmesinde dosyayı sürükleyin ya da tıklayıp seçin. PEM metnini de yapıştırabilirsiniz. PFX dosyasında **PFX Parolası** istenir.
3. Jumbo dosyadaki her sertifikayı okur ve önizlemede gösterir: **Yeni** ya da **Zaten kayıtlı**. Leaf, Intermediate ve Root türü, Issuer, ValidFrom/ValidTo ve zincir bağlantısı sertifikadan otomatik okunur.
4. **Oluşturan Ekip** (sertifikayı oluşturan SY ekibi) ve **Ortam** (Prod ya da Test) zorunludur.
5. **Onaylıyorum, İçe Aktar** ile kaydedin.

## Yenileme algılanırsa
Yeni sertifika eski bir sertifikanın yenisiyse önizlemede bilgi kutusu çıkar:
- **Yenileme — aynı anahtar (SKI aynı)**
- **Yeniden anahtarlama — yeni anahtar (CN + issuer aynı)**

Eski sertifika bir domaine ya da uygulamaya bağlıysa **değişiklik talebi oluştur** kutusu işaretli gelir. Talep bağlantıları hemen taşımaz: her bağlantı için ayrı talep açılır ve SY ekibinin onayını bekler. Birden çok eski sertifika aday olursa hiçbiri seçili gelmez; doğru olanı siz seçersiniz. Ayrıntı: [Süresi dolan sertifikayı yenileme](/wiki/sertifika-yenileme).

## Elle ekleme
**Manuel Ekle** sekmesi, PEM dosyası olmayan eski kayıtlar içindir. Sertifika Adı, ValidTo, Oluşturan Ekip ve Ortam'ı elle girersiniz. PEM olmadığı için zincir, Canlı Doğrulama karşılaştırması ve Zincir Kontrolü bu kayıtta çalışmaz; mümkünse dosyadan içe aktarın.

> Sertifikayı domaine bağlamak ayrı bir adımdır: [Domaine sertifika bağlama](/wiki/sertifika-baglama).""",
    },
    {
        "slug": "sertifika-listesi", "category": "Sertifikalar", "sort_order": 210,
        "title": "SSL Sertifikaları ekranı",
        "body": """[SSL Sertifikaları](/certificates) ekranı tüm sertifika envanterini gösterir. Ekip Editörü ve Ekip İzleyici yalnız kendi SY ekiplerinin sertifikalarını görür.

## Liste
- Üstteki sekmeler sayılarıyla süzer: Geçerli, **Yaklaşan (≤30g)**, **Süresi Dolmuş**.
- Arama kutusu ad, Subject, Issuer, Serial Number ve SKI içinde arar. Kolon başlıklarındaki filtreler ayrıca süzer.
- Intermediate ve Root sertifikaların altındaki Leaf'ler **Zinciri aç / Zinciri kapat** ile gösterilir ya da gizlenir.
- **Pasifleri göster** kapalıyken yalnız aktif sertifikalar listelenir.
- Tablo ve kart görünümü arasında geçiş yapılabilir. **Excel İndir** filtrelenmiş listeyi indirir.

## Sertifika penceresi
Bir satıra tıklayınca sağdan sertifika penceresi açılır. Sekmeler:
- **Özet**: kalan gün, ömür çizelgesi, temel bilgiler.
- **Zincir**: Root → Intermediate → Leaf zinciri.
- **Bağlantılar**: bağlı domainler (Server / Trusted) ve uygulamalar.
- **Teknik Detay**: Subject, Issuer, Serial Number, SAN, SKI/AKI, anahtar ve imza bilgisi, SHA-256 Fingerprint, PEM.
- **İptal Durumu**: OCSP/CRL sonucu ve **Şimdi Kontrol Et**.
- **Kurumsal**: Oluşturan Ekip, Ortam, Satın Alım Yapan, Notlar.
- **Mailler**: bu sertifika için gönderilen uyarı mailleri.
- **Etkilenenler**: sertifikanın süresi dolarsa etkilenecek domainler, uygulamalar ve ekipler.

## Düzenleme
Ekip Editörü Ortam, Satın Alım Yapan, Oluşturan Ekip ve Notlar alanlarını düzenleyebilir. Sertifikadan okunan alanları (Ad, Type, üst sertifika, Internal) yalnız yönetici düzeltebilir.

## Pasife alma ve silme
Satırdaki **⋯** menüsünde **Pasife Al**, **Aktifleştir** ve **Sil (kalıcı)** bulunur; bunlar yalnız yöneticidedir. Bir domaine server sertifikası olarak bağlı sertifika pasife alınamaz.""",
    },
    {
        "slug": "sertifika-yenileme", "category": "Sertifikalar", "sort_order": 220,
        "title": "Süresi dolan sertifikayı yenileme",
        "body": """Sertifika yenilemesi Jumbo dışında yapılır (CA'dan yeni sertifika alınır, sunucuya kurulur). Jumbo'da yapılacaklar şunlardır:

1. Yeni sertifikayı [SSL Sertifikaları](/certificates) > **Yeni Ekle** ile içe aktarın. Bkz. [Sertifika ekleme](/wiki/sertifika-ekleme).
2. Jumbo eski sertifikayı tanır (aynı anahtar ya da aynı CN ve CA). **değişiklik talebi oluştur** işaretli kalsın.
3. Eski sertifikanın bağlı olduğu her domain ve uygulama için ayrı bir **Sertifika değişimi** talebi açılır.
4. Domainin SY ekibi [Değişiklik Talepleri](/proposals) ekranında talebi inceler ve onaylar. Onaylanınca bağlantı yeni sertifikaya taşınır.

## Canlıda görüldü
Yeni sertifika sunucuya kurulduysa gece çalışan Canlı Doğrulama bunu görür ve talebe **Canlıda görüldü** işaretini koyar. Bu işaret, onaylamanın güvenli olduğunu gösterir. Talep açılmamışsa Canlı Doğrulama, yeni sertifikayı sunan domain için kendisi talep açar.

## Eski sertifika ne olur?
Eski sertifika hâlâ bir yerde kullanılıyorsa ya da bekleyen talebi varsa aktif kalır. Hiçbir yerde kullanılmadığında yönetici pasife alabilir. Yenilenen sertifikanın penceresinde yenisine giden bağlantı görünür.

> Talebi sonradan açmak isterseniz sertifika penceresindeki **Değişiklik Talebi Oluştur** düğmesini kullanın.""",
    },
    {
        "slug": "zincir-ve-iptal", "category": "Sertifikalar", "sort_order": 230,
        "title": "Zincir Kontrolü ve iptal durumu",
        "body": """## Zincir nasıl kurulur?
Jumbo her sertifikanın üst sertifikasını (Issuer) PEM'deki SKI/AKI bilgisinden bulur ve Root → Intermediate → Leaf zincirini kendisi kurar. Kendi kendini imzalamış (self-signed) sertifikanın üstü olmaz.

## Zincir Kontrolü (yönetici)
Eski kayıtlarda tür ya da üst sertifika yanlış olabilir. [SSL Sertifikaları](/certificates) ekranındaki **Zincir Kontrolü** düğmesi tüm kayıtları PEM'den yeniden hesaplar ve farkları listeler. Listeyi inceleyip **Düzelt** ile uygulayabilirsiniz. Yapılan her düzeltme Audit Log'a yazılır. PEM'i olmayan kayıtlar kontrol edilemez.

## İptal durumu (OCSP/CRL)
Sertifika penceresindeki **İptal Durumu** sekmesi, CA'nın sertifikayı iptal edip etmediğini gösterir:
- **İptal edilmemiş (good)**
- **Sertifika İPTAL EDİLMİŞ (revoked)**: CA sertifikayı iptal etmiştir, hemen yenilenmelidir.
- **Ulaşılamadı**: OCSP/CRL adresine erişilemedi.
- **Bilinmiyor (unknown)**: CA bu sertifikayı tanımıyor.
- **Kontrol edilemez**: sertifikada iptal bilgisi yok ya da üst sertifika envanterde yok.

**Şimdi Kontrol Et** tek sertifikayı hemen denetler. Gece toplu denetim varsayılan olarak kapalıdır; yönetici Ayarlar > İptal (OCSP/CRL)'den açar. Açıkken iptal edilen sertifika için ilgili ekiplere bir kez mail gider.""",
    },

    # ------------------------------------------------------------------ Domainler
    {
        "slug": "domain-ekleme", "category": "Domainler", "sort_order": 300,
        "title": "Domain ekleme ve Excel ile toplu yükleme",
        "body": """Domain eklemek için Yönetici ya da Ekip Editörü olmanız gerekir.

## Tek domain
1. [Domainler](/domains) ekranında **Yeni Domain**'e basın.
2. **Domain** adını ve **SY Takımı**'nı girin (ikisi de zorunlu). UG Takımı, Dış Adres, Dış Firma, Güncellenecek Sunucular, Keystore ve Detay isteğe bağlıdır.
3. **Bildirim Gün Sayısı** boş kalırsa uyarı maili varsayılan sürede (30 gün) başlar. Bu domain için daha erken uyarı istiyorsanız gün sayısı girin.
4. Kaydedin. Aynı domain ikinci kez eklenemez.

## Excel ile toplu yükleme
1. **Excel** menüsünden **Boş şablon indir**'e basın. İlk satır örnektir; silip kendi verinizi girin.
2. Doldurduğunuz dosyayı **Excel** > **Excel'den yükle** ile yükleyin.
3. Jumbo'da tanımlı olmayan bir SY ekibi adı yazılan satır atlanır ve ekranda uyarı kalır; ekip Jumbo'da kendiliğinden açılmaz. Ekip adında büyük/küçük harf farkı sorun değildir.

Aynı menüdeki **Listeyi indir**, filtrelenmiş domain listesini indirir.

## Sonraki adım
Domain eklendikten sonra sertifikasını bağlayın: [Domaine sertifika bağlama](/wiki/sertifika-baglama). Ardından **Şimdi Doğrula** ile sunucunun gerçekten bu sertifikayı sunduğunu kontrol edin: [Canlı Doğrulama](/wiki/canli-dogrulama).""",
    },
    {
        "slug": "sertifika-baglama", "category": "Domainler", "sort_order": 310,
        "title": "Domaine sertifika bağlama (Server / Trusted)",
        "body": """Bir domainin hangi sertifikayı kullandığını Jumbo'ya bağlantı ile söylersiniz. Uyarı mailleri, Canlı Doğrulama ve Etkilenenler listesi bu bağlantılardan çalışır.

## Bağlantı tipleri
- **Server**: domainin sunucusunun sunduğu sertifika. Süresi dolarsa site çalışmaz.
- **Trusted**: domainin güvendiği (trust store'a eklenmiş) sertifika, örneğin karşı tarafın sertifikası ya da kurum içi Root.

## Nasıl bağlanır?
1. [Domainler](/domains) ekranında domaine tıklayın, **Sertifikalar** sekmesini açın.
2. **Sertifika seç** kutusunda ad, SKI ya da Serial Number ile arayın.
3. **Bağlantı Tipi**'ni (Server ya da Trusted) seçip ekleyin.

Sertifika domain adını kapsamıyorsa kırmızı **Alan adını kapsamıyor** uyarısı çıkar. Wildcard sertifikalar (*.ornek.com) alt alan adlarını kapsar.

## Canlıdaki sertifikayı içe aktarma
Sertifika Jumbo'da yoksa domain penceresinin **Canlı Doğrulama** sekmesinde **Canlıdaki Sertifikayı İçe Aktar** düğmesi sunucunun sunduğu sertifikayı ve zincirini Jumbo'ya ekler ve domaine bağlar.

## Bağlantıyı kaldırma
Sertifikalar sekmesinde bağlantının yanındaki **Bağlantıyı kaldır** yalnız bağlantıyı siler; sertifika envanterde kalır.

> Bağlantıları bir sertifikadan yenisine taşımak için bağlantıyı elle değiştirmek yerine yeni sertifikayı içe aktarıp değişiklik talebi açın: [Süresi dolan sertifikayı yenileme](/wiki/sertifika-yenileme).""",
    },
    {
        "slug": "canli-dogrulama", "category": "Domainler", "sort_order": 320,
        "title": "Canlı Doğrulama",
        "body": """Canlı Doğrulama, domainin sunucusuna bağlanıp sunulan sertifikayı Jumbo'daki bağlı sertifikayla karşılaştırır. Her gece (varsayılan 07:00) tüm domainler için kendiliğinden çalışır. Domain penceresindeki **Canlı Doğrulama** sekmesinde **Şimdi Doğrula** ile hemen çalıştırabilirsiniz.

## Sonuçlar
- **Eşleşiyor**: sunulan sertifika envanterle aynı.
- **EŞLEŞMİYOR**: sunucu bağlı sertifikadan farklı bir sertifika sunuyor ya da sertifika domain adını kapsamıyor. Domain birden çok IP'ye çıkıyorsa ve IP'lerden biri farklı sertifika sunuyorsa da bu sonuç çıkar.
- **SÜRESİ DOLMUŞ**: sunucu süresi dolmuş sertifikayı sunuyor.
- **Ara sertifika sunucuda eksik**: sunucu zincirdeki Intermediate'i göndermiyor; bazı istemciler bağlanamaz.
- **Erişilemedi**: sunucuya bağlanılamadı.
- **Server sertifikası bağlanmamış**: karşılaştırılacak bağlı sertifika yok.
- **Kontrol edilemez (wildcard)**: *.ornek.com gibi adreslere bağlanılamaz.

Sonuçta **Tarih farkı** notu varsa, sunulan sertifika aynıdır ama Jumbo'daki ValidTo eskidir.

## Canlı Doğrulama neyi değiştirir?
Hiçbir kaydı kendisi değiştirmez. Bulduğu her farkı değişiklik talebine çevirir:
- Yeni sertifika canlıda görüldü: **Sertifika değişimi** (Canlıda görüldü).
- Sunucu fazladan bir sertifika sunuyor: **Sunucuya eklenen**.
- Bağlı sertifika artık sunulmuyor: **Sunucudan kalkan** (yalnız bağlantı kaldırılır).
- Tarih farkı: **Tarih güncelleme**.

Reddedilen talep aynı fark için bir daha açılmaz.

## Ek kontroller
Sonuç ekranında DNS kaydı, Çoklu IP, CAA ve OCSP Stapling bilgileri de görünür. Bunlar bilgi amaçlıdır; yalnız Çoklu IP'de farklı sertifika sunan IP sonucu kırmızıya çevirir.""",
    },

    # ------------------------------------------------------------------ Uygulamalar
    {
        "slug": "uygulama-ekleme", "category": "Uygulamalar", "sort_order": 400,
        "title": "Uygulama ekleme, bağımlılık ve trust store",
        "body": """[Uygulamalar](/applications) ekranı uygulama envanterini, sunucularını ve domain ilişkilerini tutar. Uygulama eklemek için Yönetici ya da Ekip Editörü olmanız gerekir.

## Uygulama ekleme
1. **Yeni Uygulama**'ya basın.
2. **Uygulama Adı**, **Sunucu Adı** ve **SY Takımı** zorunludur.
3. **Bağlı Domain**: uygulamanın kendi domaini. Bu domainin server sertifikası uygulamanın sertifikası sayılır.
4. İsterseniz IP Adresi, DNS, Config Path, Log Path, Start/Stop Yöntemi, Kontrol Yöntemi, Gerekli Komutlar, Servis Sağlayıcı İletişim, Etiketler ve notları doldurun.

## Bağımlılık (Trusted bağlantı)
Uygulama başka bir domaine bağlanıyorsa uygulama penceresinden bağımlılık ekleyin: **Hedef Domain** ve gerekiyorsa uygulamanın kullandığı client **Sertifika**. Hedef domainin sertifikası yenilendiğinde bu uygulama da etkilenenler listesinde görünür.

## Trust store
Uygulamanın güvendiği sertifikaları (trust store) uygulama penceresinden ekleyin. Pasif bir sertifika trust store'a eklenemez. Ekip Editörü yalnız kendi ekibinin uygulamalarının trust store'unu düzenler.

## Uyarı mailleri
Uygulamanın SY ekibi şu sertifikalar için de uyarı maili alır: Bağlı Domain'in server sertifikası, bağımlılıktaki client sertifika ve trust store'daki sertifikalar (trust store'dakiler için yalnız süre dolana kadar). Uygulama pasif olsa da uyarı gider. Ayrıntı: [Uyarı mailleri](/wiki/uyari-mailleri).""",
    },

    # ------------------------------------------------------------------ Onay ve bildirim
    {
        "slug": "degisiklik-talepleri", "category": "Onay ve Bildirimler", "sort_order": 500,
        "title": "Değişiklik talepleri: inceleme ve onay",
        "body": """Jumbo bağlantıları kendisi değiştirmez; değişikliği önerir. Talep domainin SY ekibi (ya da yönetici) onaylayınca uygulanır, reddedilirse hiçbir şey değişmez.

## Talep türleri
- **Sertifika değişimi**: bağlantı eski sertifikadan yenisine taşınır (yenileme).
- **Sunucuya eklenen**: sunucuda görülen sertifika domaine bağlanacak.
- **Sunucudan kalkan**: sunucu artık sunmuyor, bağlantı kaldırılacak.
- **Tarih güncelleme**: kayıttaki tarihler sertifikanın kendisinden yeniden okunur.
- **Trusted bağlantı**: uygulamanın trust store'u ya da bağımlılığı yeni sertifikaya taşınır.

## Kim onaylar?
Domainin SY ekibindeki Ekip Editörleri ve yöneticiler. Ekip İzleyici ve Genel İzleyici onaylayamaz. SY ekibi olmayan (sahipsiz) domainin talebini yalnız yönetici onaylar.

## İnceleme
1. [Değişiklik Talepleri](/proposals) ekranında **Bekleyen** sekmesini açın. **Yalnız karar verebileceklerim** ile kendi onaylayabileceklerinizi süzün.
2. Talebe tıklayınca inceleme penceresi açılır: eski ve yeni sertifika yan yana, kimlik alanlarının eşleşmesi (Subject, SAN, SKI, Issuer), Fingerprint ve canlı kanıt.
3. **Canlıda görüldü** işareti yeni sertifikanın sunucuda görüldüğünü gösterir; bu durumda onaylamak güvenlidir. İşaret yoksa onaydan önce Canlı Doğrulama önerilir.
4. Onaylayın ya da reddedin. Her karar Audit Log'a yazılır.

Domain penceresindeki **Onaya git** bağlantısı, o domainin taleplerini süzülmüş olarak açar. Bekleyen talep sayısı menüde rozet olarak görünür.

> Yönetici açarsa bekleyen talebi olan SY ekiplerine her sabah hatırlatma maili gider (Ayarlar > E-posta).""",
    },
    {
        "slug": "uyari-mailleri", "category": "Onay ve Bildirimler", "sort_order": 510,
        "title": "Uyarı mailleri: kime, ne zaman gider?",
        "body": """## Süresi yaklaşan sertifika
Her sabah 08:00'de, bitişine uyarı süresinden az kalan aktif sertifikalar için mail gider. Varsayılan uyarı süresi 30 gündür (Ayarlar > E-posta). Domainin **Bildirim Gün Sayısı** doluysa o domainin ilgilileri o süreye göre uyarılır.

## Kimler alır?
Her ilgili ayrı mail alır, nedeni mailde yazar:
- Sertifikanın **Oluşturan Ekip**'i.
- Sertifikanın bağlı olduğu her domainin SY ekibi.
- Sertifikayı Bağlı Domain, client sertifika ya da trust store üzerinden kullanan uygulamaların SY ekibi.

Aynı ekip birden çok nedenle ilgiliyse tek mail alır. Ekibin mail adresi Ayarlar > Ekipler'de tanımlıdır. Hiç alıcısı bulunamayan sertifikanın maili yedek adrese gider.

## Diğer mailler
- **Süresi dolmuş ama hâlâ aktif** sertifikalar için her sabah 08:05'te.
- **İptal edilen** (revoked) sertifika için bir kez (iptal denetimi açıksa).
- Yönetici bir sertifikayı **pasife aldığında**, bağlı domainlerin SY ekiplerine bilgi.
- Bekleyen değişiklik talepleri için sabah hatırlatması (yönetici açarsa).

## Gönderilen mailleri görme
- Sertifika penceresinin **Mailler** sekmesi o sertifikanın maillerini gösterir.
- Yöneticiler tüm geçmişi Ayarlar > Mail Gönderim Geçmişi'nde görür; teslim edilemeyenler de burada.

Mail ayrıca Slack, Microsoft Teams, Webhook, ServiceNow, Jira gibi kanallara da gönderilebilir; bunları yönetici Ayarlar > Bildirimler altından açar.""",
    },

    # ------------------------------------------------------------------ Analiz
    {
        "slug": "sertifika-haritasi", "category": "Analiz", "sort_order": 600,
        "title": "Sertifika Haritası",
        "body": """[Sertifika Haritası](/cert-map) sertifikaların zincirini ve bağlı domainlerini görsel olarak gösterir.

## Görünümler
- **Sertifikalar**: Root → Intermediate → Leaf zinciri ve Leaf'lere bağlı domainler.
- **İlişkiler**: sertifikalardan türetilen Trusted → Server ilişkileri, yani hangi domainin hangi domaine güvendiği, ayrıca uygulama domainleri ve dış bağımlılıklar.

## Kullanım
- Bir kartın üzerine gelince kısa bilgi (tür, ad, ValidTo, kalan gün) çıkar.
- Karta tıklayınca kart sabitlenir, soy ağacı (üst ve alt sertifikalar) vurgulanır ve bilgi kartı açılır.
- Çift tıklama kaydın detay penceresini açar.
- **Yalnız bunu göster** seçilen kartın soy ağacı dışındakileri gizler; **Seçimi kaldır** geri getirir.
- Üstteki **Ara** kutusu ve süzgeçlerle takım, sertifika türü, bağlantı tipi (Server, Trusted) ya da kalan güne (Doldu, ≤ 30 gün) göre daraltabilirsiniz.
- **PNG olarak indir** haritanın resmini kaydeder.

Haritada tüm ekiplerin domainleri görünür.""",
    },
    {
        "slug": "uyum-ve-kesif", "category": "Analiz", "sort_order": 610,
        "title": "Uyum ve Keşif ekranları",
        "body": """## Uyum
[Uyum](/policy) ekranı aktif sertifikaları kurum politikasına göre denetler:
- **İzin Listesi Dışı CA**: Issuer, izin verilen CA listesinde değil.
- **Zayıf Anahtar**: anahtar boyu politikadaki alt sınırın altında.
- **Zayıf İmza**: SHA-1 ya da MD5 gibi zayıf imza.
- **Aşırı Ömür**: geçerlilik süresi sınırı aşıyor (varsayılan 398 gün).

Her ihlalin önemi (Yüksek, Orta, Düşük) görünür. Kurallar yönetici tarafından Ayarlar > Uyum'da belirlenir. İhlal sayısı menüde rozet olarak görünür.

## Keşif
[Keşif](/discovery) ekranı Jumbo'da kayıtlı olmayan (shadow) sertifikaları bulur:
- **Ağ Taraması**: tanımlı ağ aralıklarına ve sunuculara bağlanıp sunulan sertifikaları toplar.
- **CT izleme**: herkese açık Certificate Transparency (crt.sh) kayıtlarında kurum adına çıkarılmış sertifikaları arar.

Her bulgu için **Envantere Al** sertifikayı Jumbo'ya ekler, **Yok say** listeden çıkarır. Tarama hedefleri ve gece çalışma saatleri Ayarlar > Keşif ve Ayarlar > CT (crt.sh)'den belirlenir; ikisi de varsayılan olarak kapalıdır.""",
    },
    {
        "slug": "anasayfa-ekibim-genel-durum", "category": "Analiz", "sort_order": 620,
        "title": "Anasayfa, Ekibim ve Genel Durum",
        "body": """## Anasayfa
[Anasayfa](/) genel sayıları gösterir: Toplam Domain, Süresi Dolmuş Domain, Geçerli Domain, Toplam Sertifika (yalnız aktifler) ve Süresi Dolmuş Sertifika. Altında ekip bazında domain sayıları ve yaklaşan bitişler listelenir.

## Ekibim (Ekip Editörü ve Ekip İzleyici)
[Ekibim](/my-team) ekibinizin yapması gerekenleri toplar: süresi dolmuş ya da yaklaşan sertifikalar, Canlı Doğrulama'da EŞLEŞMİYOR çıkan domainler ve bekleyen değişiklik talepleri.

## Genel Durum (Yönetici ve Genel İzleyici)
[Genel Durum](/overview) tüm ekiplerin sertifika durumunu tek tabloda gösterir. **Acil** durumdaki ekipler öne çıkar. Ekip adına tıklayınca o ekibin özeti açılır. Tablo Excel olarak indirilebilir.

## Sistem Sağlığı (Yönetici)
[Sistem Sağlığı](/system-health) otomatik işlerin (mail, Canlı Doğrulama, iptal denetimi, keşif) son çalışmasını, mail gönderimini ve bağlantıları tek bakışta gösterir.""",
    },

    # ------------------------------------------------------------------ Dağıtım
    {
        "slug": "dagitim", "category": "Dağıtım", "sort_order": 700,
        "title": "Dağıtım akışları (Jenkins)",
        "body": """[Dağıtım](/deployments) ekranı, sertifika kurulumu gibi işleri Jenkins job'larından oluşan akışlarla çalıştırır.

## Akış hazırlama
1. Solda uygulamayı ve akışı seçin ya da yeni akış oluşturun.
2. **Başlat**'ın yanındaki + ile ilk düğümü ekleyin. Her düğüm bir Jenkins job'udur ve parametreleri vardır.
3. Her düğümün yanındaki + ile ardışık ya da paralel devam adımları ekleyin.
4. Kaydedin.

## Çalıştırma
Akışı çalıştırınca adımlar sırayla (paralel olanlar birlikte) Jenkins'te tetiklenir ve durumları canlı izlenir. Geçmiş çalıştırmalar [Tüm Çalıştırmalar](/deployments/runs) ekranında akış adı, tetikleyen, Jenkins job'u ya da parametre değeriyle aranabilir.

Jenkins bağlantısı yönetici tarafından Ayarlar > Jenkins'te tanımlanır. Sayfanın görünürlüğü Ayarlar > Erişim'e bağlıdır.""",
    },

    # ------------------------------------------------------------------ Yönetim
    {
        "slug": "ayarlar", "category": "Yönetim", "sort_order": 800,
        "title": "Ayarlar (yöneticiler için)",
        "body": """Ayarlar'a sol alttaki adınıza tıklayıp **Ayarlar** ile ulaşılır. Yönetici olmayanlar burada yalnız **Etiketler**'i görür.

## Kullanıcılar ve ekipler
- **Kullanıcılar**: hesaplar ve roller. Bkz. [Roller ve yetkiler](/wiki/roller-ve-yetkiler).
- **Ekipler**: SY ve UG ekipleri ve ekip mail adresleri. Ekip adı değişince sertifikaların Oluşturan Ekip alanı da güncellenir.
- **Ekip Üyelikleri**: kullanıcının hangi SY ekiplerini göreceği.
- **Erişim**: Uyum, Değişiklik Talepleri, Keşif ve Dağıtım sayfalarının görünürlüğü.
- **LDAP / Active Directory** ve **LDAP Sorguları**: kurumsal girişin ayarları ve dizinden canlı sorgular.

## Bildirimler
- **E-posta (SMTP)**: sunucu, uyarı süresi, yedek adres, **Test Maili Gönder**.
- **Mail Gönderim Geçmişi**: gönderilen ve teslim edilemeyen mailler.
- Slack, Microsoft Teams, Webhook, ServiceNow, Jira, Zoom, Jabber kanalları.

## Denetim ve tarama
- **Keşif**, **CT (crt.sh)**, **Uyum**, **İptal (OCSP/CRL)**, **Canlı Doğrulama**: kurallar ve gece çalışma saatleri.

## Sistem
- **Etiketler**: uygulama etiketi kataloğu.
- **Jenkins**: Dağıtım ekranının Jenkins bağlantısı.
- **AI Asistanı**: kurum içi AI servisinin adresi, modeli, anahtarı, hazır sorular, günlük soru sınırı ve AI'ın tüm veriyi görüp görmeyeceği.
- **Audit Log**: kim, neyi, ne zaman değiştirdi (eski → yeni). Her kolon filtrelenir, CSV olarak indirilebilir.

Ayar değişiklikleri yeniden başlatma gerektirmeden uygulanır ve Audit Log'a yazılır. Şifre ve anahtarlar şifreli saklanır.""",
    },
    {
        "slug": "kilavuzu-duzenleme", "category": "Yönetim", "sort_order": 810,
        "title": "Bu kılavuzu düzenleme",
        "body": """Kullanım Kılavuzu'nu herkes okuyabilir; sayfa ekleme, düzenleme ve silme yöneticidedir.

## Sayfa ekleme ve düzenleme
1. [Kullanım Kılavuzu](/wiki) ekranında **Yeni Sayfa**'ya ya da açık sayfadaki **Düzenle**'ye basın.
2. **Başlık**, **Kategori** ve **Sıra** girin. Aynı kategorideki sayfalar menüde birlikte, Sıra'ya göre dizilir.
3. **İçerik** alanına metni yazın. Yanındaki önizleme sayfanın nasıl görüneceğini gösterir.
4. Kaydedin. Her değişiklik Audit Log'a yazılır.

## Yazım kuralları
- `## Başlık` ve `### Alt başlık`
- `- madde` ve `1. adım`
- `**kalın**` yazıyı kalın yapar; iki ters tırnak işareti arasındaki yazı kod gibi görünür.
- `[bağlantı metni](/domains)` Jumbo içindeki bir ekranı açar; `[metin](/wiki/sayfa-adresi)` başka bir kılavuz sayfasını açar.
- `> ` ile başlayan satır not kutusu olur.

## AI asistanı ile ilişkisi
AI asistanı "nasıl yapılır" sorularını bu sayfalardan cevaplar. Kurumun kendi prosedürlerini (örneğin sertifika talep süreci, iletişim adresleri) buraya eklerseniz AI da bunları anlatır.

Jumbo'yla gelen sayfalar yeni sürümlerde güncellenir. Bir sayfayı düzenlerseniz o sayfa artık sizin metninizle kalır. Sildiğiniz sayfa geri gelmez.""",
    },
]
