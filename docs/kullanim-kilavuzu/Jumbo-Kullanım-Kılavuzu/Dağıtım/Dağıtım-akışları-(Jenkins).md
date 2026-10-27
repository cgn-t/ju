**Dağıtım** ekranı, sertifika kurulumu gibi işleri Jenkins job'larından oluşan akışlarla çalıştırır.

## Akış hazırlama
1. Solda uygulamayı ve akışı seçin ya da yeni akış oluşturun.
2. **Başlat**'ın yanındaki + ile ilk düğümü ekleyin. Her düğüm bir Jenkins job'udur ve parametreleri vardır.
3. Her düğümün yanındaki + ile ardışık ya da paralel devam adımları ekleyin.
4. Kaydedin.

## Çalıştırma
Akışı çalıştırınca adımlar sırayla (paralel olanlar birlikte) Jenkins'te tetiklenir ve durumları canlı izlenir. Geçmiş çalıştırmalar **Tüm Çalıştırmalar** ekranında akış adı, tetikleyen, Jenkins job'u ya da parametre değeriyle aranabilir.

Jenkins bağlantısı yönetici tarafından Ayarlar > Jenkins'te tanımlanır. Sayfanın görünürlüğü Ayarlar > Erişim'e bağlıdır.
