## Süresi yaklaşan sertifika
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

Mail ayrıca Slack, Microsoft Teams, Webhook, ServiceNow, Jira gibi kanallara da gönderilebilir; bunları yönetici Ayarlar > Bildirimler altından açar.
