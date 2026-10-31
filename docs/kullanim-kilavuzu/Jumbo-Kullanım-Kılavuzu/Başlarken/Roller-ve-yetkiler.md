Jumbo'da herkesin bir rolü vardır. Rolü yönetici Ayarlar > Kullanıcılar ekranında verir. LDAP ile giriş yapanlarda rol, AD grubundan da gelebilir.

## Roller
- **Yönetici**: her şeyi görür ve düzenler. Sertifikayı pasife alma, silme, Zincir Kontrolü, Sistem Sağlığı, Regresyon Testi ve Ayarlar yalnız yöneticidedir.
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
AI asistanı, Jumbo'daki uygulama verisinin tamamını rolünüzden bağımsız okuyabilir (yönetici bunu Ayarlar > AI Asistanı'ndan kapatabilir). Kişisel bilgiler (e-posta, telefon, fotoğraf, şifre, giriş kayıtları) ve sistem ayarları AI'a hiç verilmez.
