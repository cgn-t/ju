# Jumbo Kullanım Kılavuzu (kurum wiki'sine aktarmak için)

Jumbo AI kılavuzu buradan değil, Ayarlar > AI Asistanı > Kullanım Kılavuzu'na girilen kurum wiki'sinden (Azure DevOps / TFS ya da Confluence) okur. Bu klasör wiki'ye aktarılacak metindir.

- `Jumbo-Kullanım-Kılavuzu.md` ana sayfa; `Jumbo-Kullanım-Kılavuzu/` altında bölümler (ör. `Domainler.md`) ve her bölümün klasöründe alt sayfalar. Dosya adlarında boşluk yerine `-` var (Azure DevOps wiki'sinin kendi düzeni); `.order` dosyaları sayfa sırasıdır.
- Wiki'ye elle aktarırken: her `.md` dosyasının içeriğini aynı adlı (tireler yerine boşluk) wiki sayfasına yapıştırın.
- Bu klasör olduğu gibi bir git deposuna konup Azure DevOps'ta "Publish code as wiki" ile de yayımlanabilir.
- `tek-sayfa.md`: kılavuzun tamamı tek dosyada.
- `Jumbo-Kullanım-Kılavuzu/Regresyon-Testi/`: yöneticiler için regresyon test kılavuzu (Hazırlık, madde 1–11, hata sayılmayacak davranışlar, Regresyon Testi sayfasının kullanımı). Wiki'de ana sayfanın altında olduğu için Jumbo AI, Regresyon Testi sayfasındaki "Adımı anlat" sorularını buradan cevaplar. `tek-sayfa.md`'de yoktur.

Wiki'de sayfa eklenip çıkarıldıktan sonra Ayarlar'da "Wiki'yi Şimdi Oku"ya basın.
