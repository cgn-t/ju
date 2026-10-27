## Uyum
**Uyum** ekranı aktif sertifikaları kurum politikasına göre denetler:
- **İzin Listesi Dışı CA**: Issuer, izin verilen CA listesinde değil.
- **Zayıf Anahtar**: anahtar boyu politikadaki alt sınırın altında.
- **Zayıf İmza**: SHA-1 ya da MD5 gibi zayıf imza.
- **Aşırı Ömür**: geçerlilik süresi sınırı aşıyor (varsayılan 398 gün).

Her ihlalin önemi (Yüksek, Orta, Düşük) görünür. Kurallar yönetici tarafından Ayarlar > Uyum'da belirlenir. İhlal sayısı menüde rozet olarak görünür.

## Keşif
**Keşif** ekranı Jumbo'da kayıtlı olmayan (shadow) sertifikaları bulur:
- **Ağ Taraması**: tanımlı ağ aralıklarına ve sunuculara bağlanıp sunulan sertifikaları toplar.
- **CT izleme**: herkese açık Certificate Transparency (crt.sh) kayıtlarında kurum adına çıkarılmış sertifikaları arar.

Her bulgu için **Envantere Al** sertifikayı Jumbo'ya ekler, **Yok say** listeden çıkarır. Tarama hedefleri ve gece çalışma saatleri Ayarlar > Keşif ve Ayarlar > CT (crt.sh)'den belirlenir; ikisi de varsayılan olarak kapalıdır.
