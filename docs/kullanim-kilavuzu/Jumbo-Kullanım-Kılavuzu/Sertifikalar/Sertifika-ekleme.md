Sertifika eklemek için Yönetici ya da Ekip Editörü olmanız gerekir.

## Dosyadan içe aktarma (önerilen)
1. **SSL Sertifikaları** ekranında **Yeni Ekle**'ye basın.
2. **Dosyadan İçe Aktar (PEM / DER / PFX)** sekmesinde dosyayı sürükleyin ya da tıklayıp seçin. PEM metnini de yapıştırabilirsiniz. PFX dosyasında **PFX Parolası** istenir.
3. Jumbo dosyadaki her sertifikayı okur ve önizlemede gösterir: **Yeni** ya da **Zaten kayıtlı**. Leaf, Intermediate ve Root türü, Issuer, ValidFrom/ValidTo ve zincir bağlantısı sertifikadan otomatik okunur.
4. **Oluşturan Ekip** (sertifikayı oluşturan SY ekibi) ve **Ortam** (Prod ya da Test) zorunludur.
5. **Onaylıyorum, İçe Aktar** ile kaydedin.

## Yenileme algılanırsa
Yeni sertifika eski bir sertifikanın yenisiyse önizlemede bilgi kutusu çıkar:
- **Yenileme — aynı anahtar (SKI aynı)**
- **Yeniden anahtarlama — yeni anahtar (CN + issuer aynı)**

Eski sertifika bir domaine ya da uygulamaya bağlıysa **değişiklik talebi oluştur** kutusu işaretli gelir. Talep bağlantıları hemen taşımaz: her bağlantı için ayrı talep açılır ve SY ekibinin onayını bekler. Birden çok eski sertifika aday olursa hiçbiri seçili gelmez; doğru olanı siz seçersiniz. Ayrıntı: *Süresi dolan sertifikayı yenileme*.

## Elle ekleme
**Manuel Ekle** sekmesi, PEM dosyası olmayan eski kayıtlar içindir. Sertifika Adı, ValidTo, Oluşturan Ekip ve Ortam'ı elle girersiniz. PEM olmadığı için zincir, Canlı Doğrulama karşılaştırması ve Zincir Kontrolü bu kayıtta çalışmaz; mümkünse dosyadan içe aktarın.

> Sertifikayı domaine bağlamak ayrı bir adımdır: *Domaine sertifika bağlama*.
