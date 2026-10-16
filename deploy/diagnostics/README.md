# Teşhis araçları (yalnız okuma)

Bu klasördeki hiçbir araç veri değiştirmez.

| Araç | Ne için |
|---|---|
| `cert-type-proposal-check.sql` | Tipler arası (root/intermediate → leaf) devir önerisi teşhis sorguları (Q0–Q9) |
| `live-cert-check.sh` | Bir host'un sunduğu sertifika zincirini dizüstü/sunucudan kontrol (openssl + curl) |
| `backend/scripts/live_cert_check.py` | Aynı kontrol **pod içinden**, canlı doğrulamayla birebir aynı bağlantı + envanter karşılaştırması |

## Pod içinden canlı sertifika kontrolü

Canlı doğrulama HTTP yönlendirmesini (301/302) **takip etmez**; host'un TLS el sıkışmasındaki kendi
sertifikasına bakar. Tarayıcı ise yönlendirme sonrası adresin sertifikasını gösterir (ör. `stablex.net`
→ `stablex.com`: kilit simgesi stablex.com'u gösterir, JUMBO stablex.net'in sertifikasını görür).

`deploy/jumbo` pod adını bilmeden çalışan pod'a bağlanır (belirli bir pod için: `oc get pods -l app=jumbo`
ile adı bulup `deploy/jumbo` yerine onu yazın). Namespace farklıysa `-n <namespace>` ekleyin.

### 1) JUMBO aracıyla (v3.6.1 ve sonrası imajda)

```bash
oc exec -it deploy/jumbo -- python -m scripts.live_cert_check stablex.net
oc exec -it deploy/jumbo -- python -m scripts.live_cert_check "xxx.aaakkk.com:8228"
oc exec -it deploy/jumbo -- python -m scripts.live_cert_check stablex.net --no-db   # yalnız TLS, DB'ye bakmadan
```

Çıktı: zincirdeki her sertifika (tip, CN, yayıncı, geçerlilik — İstanbul saati, seri, SHA-256), envanterde
karşılığı ve domaine server olarak bağlı olup olmadığı; sonda domainin açık devir önerileri ve her önerinin
**YENİ** sertifikasının şu an sunulan zincirde olup olmadığı (✔ / ✘).

### 2) Yeni imaj henüz yoksa — openssl tek satır

```bash
oc exec -it deploy/jumbo -- sh -c 'openssl s_client -connect stablex.net:443 -servername stablex.net </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -serial -fingerprint -sha256'
```

`sha256 Fingerprint` değerini Devir Önerileri → İncele ekranındaki **YENİ** sertifikanın parmak iziyle
karşılaştırın: aynıysa öneri doğrudur. (Tarihler GMT'dir; İstanbul = GMT+3.)
