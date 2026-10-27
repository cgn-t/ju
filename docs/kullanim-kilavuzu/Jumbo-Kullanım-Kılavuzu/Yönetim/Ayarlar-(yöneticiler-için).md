Ayarlar'a sol alttaki adınıza tıklayıp **Ayarlar** ile ulaşılır. Yönetici olmayanlar burada yalnız **Etiketler**'i görür.

## Kullanıcılar ve ekipler
- **Kullanıcılar**: hesaplar ve roller. Bkz. *Roller ve yetkiler*.
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
- **AI Asistanı**: kurum içi AI servisinin adresi, modeli, anahtarı, hazır sorular, günlük soru sınırı AI'ın tüm veriyi görüp görmeyeceği ve Kullanım Kılavuzu'nun okunduğu wiki sayfası.
- **Audit Log**: kim, neyi, ne zaman değiştirdi (eski → yeni). Her kolon filtrelenir, CSV olarak indirilebilir.

Ayar değişiklikleri yeniden başlatma gerektirmeden uygulanır ve Audit Log'a yazılır. Şifre ve anahtarlar şifreli saklanır.
