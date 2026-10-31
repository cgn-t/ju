Regresyon Test Kılavuzu, Bölüm 2, madde 10. Önce *Hazırlık* sayfası yapılmış olmalıdır. Tablodaki her adımı yapın ve ekranda "Ne görmelisiniz" sütunundakini görüp görmediğinize bakın. Jumbo'daki **Regresyon Testi** sayfasında bu adımlar "Uygulamalar, trust store, sertifika yönetimi, uyum ve iptal" bölümünde **B2-10.1**, **B2-10.2** … kimlikleriyle listelenir.

Uyum sayfası (Analiz > Uyum), envanterdeki sertifikaları Ayarlar > Uyum'daki kurallara göre denetler ve kurala uymayanları listeler. Hiçbir sertifikayı değiştirmez. Sayfa varsayılan olarak yalnız yöneticiye açıktır; bu bölümün tamamı Yönetici hesabıyla yapılır. Varsayılan kurallar: RSA en az 2048 bit, EC en az 256 bit, yasak imza sha1 ve md5, en fazla 398 gün ömür, CA izin listesi kapalı.

Toplam sayılar ortamınızdaki diğer sertifikalara göre değişir. Bu yüzden tablo yalnız bu bölümde yüklediğiniz sertifikaları sorar.

| Adım | Ne yapın | Ne görmelisiniz |
|---|---|---|
| 10.1 | Şu dosyaları yükleyin (Oluşturan Ekip = Ödeme Sistemleri SY, Ortam = Test): `17-zayif-rsa-1024.pem`, `18-zayif-ec-p192.pem`, `19-sha224-imzali.pem`, `20-omur-399-gun.pem`, `21-omur-398-gun.pem`, `22-baska-yayinci.pem`, `23-istanbul-yayinci.pem` | Hepsi eklenir. 22 ve 23 ikişer sertifika ekler: kendi yayıncıları ("Bilinmeyen Test SM", "İSTANBUL Test SM") ve asıl sertifika |
| 10.2 | Analiz > Uyum | Listede üçü vardır: `zayif-rsa` (Zayıf Anahtar, RSA 1024, Önem Yüksek), `zayif-ec` (Zayıf Anahtar, EC 192, Önem Orta), `omur-399` (Aşırı Ömür, Önem Orta). `omur-398`, `sha224-imza`, `baska-yayinci`, `istanbul-yayinci` listede yoktur |
| 10.3 | Üstteki "Kurallar" satırında "Zayıf Anahtar" etiketine tıklayın | Liste yalnız zayıf anahtarlı sertifikalara iner. Tekrar tıklayınca filtre kalkar |
| 10.4 | Ayarlar > Uyum > Yasak İmza Özet Algoritmaları kutusuna `sha224` ekleyin (listeden seçin ya da yazıp Enter). Kaydet. Uyum sayfasını yenileyin | `sha224-imza` listeye gelir: Zayıf İmza, İmza sütununda sha224, Önem Yüksek |
| 10.5 | Ayarlar > Uyum: "CA allowlist zorunlu" açın. CA Allowlist kutusuna `Jumbo Test` yazıp Enter, sonra `istanbul` yazıp Enter (küçük harfle, Latin i ile). Kaydet. Uyum sayfasını yenileyin | `baska-yayinci` gelir: İzin Listesi Dışı CA, Önem Yüksek. `istanbul-yayinci` gelmez; yayıncısı "İSTANBUL Test SM" büyük İ ile yazılmış olsa da izin listesindeki `istanbul` ile eşleşir. Bölüm 1'in `localhost` sertifikaları (yayıncı Jumbo Test Ara SM) gelmez |
| 10.6 | Bölüm 1, madde 7'de gerçek sitelerden domain eklediyseniz bu sitelerin sertifikalarına bakın | Onlar da İzin Listesi Dışı CA olarak gelir, çünkü yayıncıları izin listesinde yoktur. Bu beklenen sonuçtur |
| 10.7 | Ayarlar > Uyum: Asgari RSA (bit) = `1024`. Kaydet. Uyum sayfasını yenileyin | `zayif-rsa` listeden çıkar; `zayif-ec` kalır |
| 10.8 | Ayarlar > Uyum: "Uyum değerlendirmesi etkin" kapatın, Kaydet. Uyum sayfasını açın | Sarı uyarı: "Uyum değerlendirmesi kapalı (Ayarlar → Uyum). Aşağıdaki bulgular yine de mevcut envantere göre hesaplanır..." Liste görünmeye devam eder |
| 10.9 | Ayarları geri alın: Uyum değerlendirmesi etkin açık, Asgari RSA `2048`, `sha224` silinir, CA allowlist zorunlu kapalı, izin listesi boş. Kaydet | 10.2'deki üç sertifika yeniden listededir; `sha224-imza` ve `baska-yayinci` listeden çıkar |
