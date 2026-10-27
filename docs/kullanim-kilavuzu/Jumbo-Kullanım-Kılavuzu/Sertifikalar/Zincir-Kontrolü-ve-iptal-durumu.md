## Zincir nasıl kurulur?
Jumbo her sertifikanın üst sertifikasını (Issuer) PEM'deki SKI/AKI bilgisinden bulur ve Root → Intermediate → Leaf zincirini kendisi kurar. Kendi kendini imzalamış (self-signed) sertifikanın üstü olmaz.

## Zincir Kontrolü (yönetici)
Eski kayıtlarda tür ya da üst sertifika yanlış olabilir. **SSL Sertifikaları** ekranındaki **Zincir Kontrolü** düğmesi tüm kayıtları PEM'den yeniden hesaplar ve farkları listeler. Listeyi inceleyip **Düzelt** ile uygulayabilirsiniz. Yapılan her düzeltme Audit Log'a yazılır. PEM'i olmayan kayıtlar kontrol edilemez.

## İptal durumu (OCSP/CRL)
Sertifika penceresindeki **İptal Durumu** sekmesi, CA'nın sertifikayı iptal edip etmediğini gösterir:
- **İptal edilmemiş (good)**
- **Sertifika İPTAL EDİLMİŞ (revoked)**: CA sertifikayı iptal etmiştir, hemen yenilenmelidir.
- **Ulaşılamadı**: OCSP/CRL adresine erişilemedi.
- **Bilinmiyor (unknown)**: CA bu sertifikayı tanımıyor.
- **Kontrol edilemez**: sertifikada iptal bilgisi yok ya da üst sertifika envanterde yok.

**Şimdi Kontrol Et** tek sertifikayı hemen denetler. Gece toplu denetim varsayılan olarak kapalıdır; yönetici Ayarlar > İptal (OCSP/CRL)'den açar. Açıkken iptal edilen sertifika için ilgili ekiplere bir kez mail gider.
