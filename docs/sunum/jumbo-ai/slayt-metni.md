# Jumbo AI – slayt metni (kopyala-yapıştır)

## Kapsam
Jumbo Sertifika Takip uygulamasına eklenen, kurum içi AI servisini kullanan soru-cevap asistanı. Kullanıcı sertifika, domain, ekip ve uyum durumunu doğal dille sorar; cevap ilgili kayıtlara bağlantılarla gelir. Kullanım kılavuzu sorularını kurumsal TFS wiki'den yanıtlar. Asistan yalnızca okur, hiçbir kaydı değiştirmez.

## Değer Önerisi / Kazanımlar
- Sertifika ve domain bilgisine menü aramadan, tek soruyla erişim
- Süresi dolacak sertifikalar, uyum ihlalleri ve ekip özetleri anında
- Cevapta kayda giden bağlantı: tek tıkla detay ekranı
- Gözden kaçan süre sonu riskleri azalır, kesinti riski düşer
- Kılavuz soruları wiki'den cevaplanır, destek talebi azalır
- Yeni kullanıcılar uygulamayı daha hızlı öğrenir

## Yönetişim
- Kurum içi AI servisi; veri kurum dışına çıkmaz
- Salt okur; kayıt eklemez, değiştirmez
- E-posta, parola, IP gibi kişisel veriler AI'a verilmez
- Her soru denetim kaydına yazılır
- Günlük soru limiti; ayarlar yalnız yöneticide
- API anahtarı ve wiki token şifreli saklanır

## Detay İçerik / Temel Parçaları
- Sohbet paneli: sağ kenardan açılır, sayfayı kapatmaz; Genişlet/Büyüt, açık-koyu tema
- Hazır sorular: yöneticinin Ayarlar'dan düzenlediği en fazla 20 soru
- Kaynak gösterimi: her cevabın altında "Baktığı yerler" ve Kopyala
- Veri araçları: sertifika/domain sorgusu, izinli tablolarda sorgu (serbest SQL yok), uyum ihlalleri, kayıt geçmişi (yalnız yönetici)
- Yetki: tüm veri modu (Genel İzleyici gibi okur) ya da kullanıcının kendi ekip yetkisi; Ayarlar'dan seçilir
- Kılavuz: TFS / Azure DevOps wiki otomatik okunur, 15 dk'da bir yenilenir
- Yönetim: Ayarlar > AI Asistanı (adres, model, anahtar, limit, ek talimat, bağlantı testi)

## Teknoloji Çözüm Önerisi
Akış: Kullanıcı (Jumbo ekranı, AI paneli) ↔ Jumbo Backend (Python API, yetki + salt okur araçlar) ↔ Kurum İçi AI (OpenAI uyumlu API). Backend veriyi Jumbo MSSQL'den, kılavuzu TFS Wiki'den okur.
- Arayüz: React / Vite; Jumbo içinde yan panel, ayrı uygulama yok
- Backend: Python servisi; model, araç çağırma (tool calling) ile veriyi kullanıcı adına okur
- Model: kurum içi AI servisi; adres, model ve anahtar Ayarlar'dan değişir
- Veri ve ortam: mevcut MSSQL ve OpenShift; yeni tablo, sunucu ya da imaj gerekmez

## Entegrasyon Konuları
- Kurum içi AI servisi: adres, model, API anahtarı; canlı ortam testi
- TFS wiki: PAT ile okuma (REST 6.0 / 5.0 / 4.1)
- Gerekirse kurum proxy ayarı
- Mevcut AD girişi ve Jumbo ekip yetkileri

## Riskler
- Model hatalı/eksik cevap verebilir; kayıt bağlantısıyla doğrulanır
- AI servisi kapalıysa asistan çalışmaz, uygulama etkilenmez
- Wiki güncel tutulmazsa kılavuz cevapları eskir
- Tüm veri modunda diğer ekiplerin verisi görülebilir

## Maliyetler ve Yatırım
- Proje Büyüklüğü: Küçük
- Yatırım Maliyeti (TL): …… (doldurulacak)
- İşletim Maliyeti (TL): …… (doldurulacak)

## Veri Kaynağı
- Yapılandırılmış: X (MSSQL kayıtları)
- Yapılandırılmamış: X (TFS wiki sayfaları)
