**SSL Sertifikaları** ekranı tüm sertifika envanterini gösterir. Ekip Editörü ve Ekip İzleyici yalnız kendi SY ekiplerinin sertifikalarını görür.

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
Satırdaki **⋯** menüsünde **Pasife Al**, **Aktifleştir** ve **Sil (kalıcı)** bulunur; bunlar yalnız yöneticidedir. Bir domaine server sertifikası olarak bağlı sertifika pasife alınamaz.
