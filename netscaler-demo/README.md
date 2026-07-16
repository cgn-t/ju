# NetScaler CPX — Yerel Cert-Swap Demosu

NetScaler'da **sertifika değişimini** yerel Docker'da birebir gösterir. Hedef mimariyi kanıtlar:
**Vault → (Jenkins taklidi script) → NITRO → NetScaler**, JUMBO yalnız tetik+doğrular, **özel anahtar
JUMBO'ya girmez** (custody-free). NetScaler = **CPX** (container'lı ADC, tam NITRO API), `jumbo-net`
üzerinde.

## İki çalıştırma yolu (aynı bootstrap/swap/verify scriptleri)
| Ortam | NetScaler tarafı | Başlat |
|---|---|---|
| **amd64** (Linux/CI/VM) | Gerçek **NetScaler CPX** (`quay.io/netscaler/netscaler-cpx`) | `./run-cpx.sh` |
| **Apple Silicon / arm64** | **NITRO-uyumlu mock ADC** (`mock/`, arm64 native) | `./run-mock.sh` |

> **Neden mock?** CPX yalnız **linux/amd64**; paket motoru (`nsrpc_shm_proc`) Apple Silicon'da
> emülasyonla başlamıyor (`--privileged`/`--shm-size` fark etmez). Mock ADC aynı NITRO uçlarını
> karşılar **ve** 443'te yüklü cert ile TLS sunar → swap sonrası sunulan cert değişir. **Gerçek
> NetScaler değildir**; birebir CPX için `run-cpx.sh`'i bir amd64 host'ta kullanın.

## Bileşenler
| Konteyner | Ne |
|---|---|
| `jumbo-cpx` | NetScaler tarafı — gerçek CPX **veya** mock ADC (aynı ad, host NITRO **19080**, veri 443→host **8443**) |
| `jumbo-vault-demo` | dev-mode Vault — YENİ cert+key'in kaynağı (custody) |
| `jumbo` | mevcut app — SSL vserver'ın backend'i (nginx :8080), vserver'ı UP tutar |

> **CPX imajı** quay.io'da **public** (login gerekmez), yalnız `EULA=yes` env zorunlu. NITRO host portu
> **19080** (9080 `jumbo` konteynerinde dolu olduğundan).

## Akış — sırayla çalıştır
```bash
cd netscaler-demo
./gen-demo-certs.sh     # ESKİ + YENİ self-signed çiftler (farklı O= → fingerprint görünür değişir)
./run-mock.sh           # Apple Silicon: mock ADC  ·  amd64'te birebir CPX için: ./run-cpx.sh
./bootstrap-nitro.sh    # ESKİ cert + SSL vserver + backend + bind  → "önce" durumu
./verify.sh             # >>> fingerprint A (OLD-CERT-2025) sunuluyor

./seed-vault.sh         # YENİ cert+key → Vault'a (custody kaynağı)
./swap-cert.sh          # Jenkins taklidi: Vault'tan oku → NITRO update sslcertkey (YERİNDE) → save
./verify.sh             # >>> fingerprint B (NEW-CERT-2026) — cert değişti, aynı vserver/aynı certkey
```

**Beklenen sonuç:** iki `verify.sh` çıktısı farklı subject (`O=OLD…` → `O=NEW…`) ve farklı SHA-256
fingerprint gösterir. Cert-key adı (`demo_ck`) ve vserver (`demo_vs`) **aynı kalır** — değişim yerinde.

## Neyi kanıtlıyor
- **Yerinde `update sslcertkey`**: ad sabit → o çifte bağlı tüm vserver'lar anında yeni cert'i sunar.
- **Custody-free**: özel anahtar `Vault → swap script → CPX` yolunu izler; JUMBO süreci anahtara dokunmaz.
- **Doğrulama**: `verify.sh` = JUMBO `live_check`'inin mantığı (VIP'e TLS, sunulan cert fingerprint'i).

## Sorun giderme
| Belirti | Çözüm |
|---|---|
| `run-cpx.sh` NITRO beklerken takılır | `docker logs jumbo-cpx \| tail -40`; kimlik farklıysa `NS_PASS=... ./run-cpx.sh` |
| `verify.sh` bağlanamıyor | vserver UP değil → bootstrap yapıldı mı, `jumbo` (:8080) ayakta mı; alternatif hedef `jumbo-cpx:443` (jumbo-net içinden) |
| `systemfile` "already exists" | swap her seferinde `new_<saat>.*` adı kullanır; bootstrap tek sefer |
| İsim çakışması | `docker rm -f jumbo-cpx jumbo-vault-demo` ile temizleyip tekrar |

## Temizlik
```bash
docker rm -f jumbo-cpx jumbo-vault-demo
```

## Sonraki (JUMBO Faz 1)
Bu ortam, JUMBO'nun `netscaler` ayarı + `POST /api/netscaler/deploy` (tetik) + cert detayı "Dağıt"
butonu + `live_check` doğrulaması için **canlı hedef**tir. Swap script'i gerçek bir yerel Jenkins job'una
(buildWithParameters + withVault) taşınabilir.
