# 🔐 JUMBO Vault — HashiCorp Vault Docker Kurulumu

JUMBO'nun bağlanacağı **HashiCorp Vault**'u Docker ile ayağa kaldırma rehberi. Vault burada
**PKI CA zinciri** (kök/ara sertifikalar) ve **KV v2 kasa** kaynağı olarak çalışır.

> **JUMBO ↔ Vault ilişkisi READ-ONLY'dir.** JUMBO Vault'tan yalnız **okur**:
> - PKI CA zincirini envantere alır (`{pki}/ca/pem`, `{pki}/cert/ca_chain`)
> - KV v2 kasadan okur (`{kv}/data/*`, `{kv}/metadata/*`)
>
> Sertifika **üretimi/yenilemesi ve özel anahtar velayeti JUMBO'da DEĞİL**, Vault + dış
> otomasyondadır (Ansible/pipeline). Bu yüzden JUMBO'ya yalnız **read-only bir token** verilir.

Bu dizindeki dosyalar:

| Dosya | Ne |
|---|---|
| `run.sh` | **Betikle başlat** — `Dockerfile`'ı derler (config+policy gömülü) + çalıştırır (§1-B) |
| `config.hcl` | Vault sunucu yapılandırması |
| `policies/jumbo-ro.hcl` | JUMBO için read-only policy |
| `Dockerfile` | **config + policy'yi GÖMEN özel imaj** (mount'suz/registry dağıtımı — §1-B) |
| `compose.yaml` | (opsiyonel) `docker compose` kuruluysa aynı kurulum |

> **İki dağıtım yolu var:** **(A)** resmi `hashicorp/vault` imajı + config/policy'yi `-v` ile
> **mount** et (§1) — repo host'ta olduğunda en hızlısı. **(B)** config/policy'yi `Dockerfile` ile
> **imaja göm** (§1-B) — kapalı/hava-boşluklu prod için: imajı iç registry'ye push'la, host'ta repo
> olmadan mount'suz çalıştır. Sonraki tüm adımlar (init/unseal/PKI/KV/token) **ikisinde de aynı**.

---

## 0. Gereksinimler
- Docker + Docker Compose
- Açılacak port: **8200** (API/UI)
- Prod'da: TLS sertifikası (bkz. §7) ve unseal key'lerini saklayacağınız güvenli bir yer

---

## 1. Çalıştır (düz `docker` — compose GEREKMEZ)

`docker compose` kurulu olmayabilir; **asıl yöntem düz `docker run`'dır.** `vault/` dizininden:

```bash
cd vault
docker run -d --name jumbo-vault --restart unless-stopped \
  -p 8200:8200 --cap-add IPC_LOCK \
  -e VAULT_ADDR=http://127.0.0.1:8200 \
  -v jumbo-vault-data:/vault/file \
  -v "$PWD/config.hcl":/vault/config/config.hcl:ro \
  -v "$PWD/policies":/vault/policies:ro \
  hashicorp/vault:1.18 server
docker logs -f jumbo-vault          # "Vault server started" görene kadar (Ctrl-C ile çık)
```

> **Betikle:** `./run.sh` bu kurulumu **gömülü imaj** ile yapar (config+policy imajda, mount'suz) — bkz. §1-B.

> **Önemli:** komut yalnız **`server`**'dır. İmaj entrypoint'i otomatik `-config=/vault/config`
> ekler ve `config.hcl`'i o dizine bağladık; `-config=...`'ı **tekrar vermeyin** (config iki kez
> yüklenip aynı listener'ı 8200'e iki kez bağlar → "address already in use").
>
> **Ne yapıyor:** `-p 8200:8200` API/UI portu · `--cap-add IPC_LOCK` bellek kilidi ·
> `jumbo-vault-data` volume kalıcı raft verisi · `config.hcl` ve `policies/` salt-okunur bağlanır.

Vault artık **mühürlü (sealed)** ve **başlatılmamış (uninitialized)** durumdadır — bir sonraki adım.

> **Alternatif — `docker compose` kuruluysa:** `cd vault && docker compose up -d` (aynı sonuç;
> `compose.yaml` sağlanmıştır).
>
> **İsim çakışması:** "The container name /jumbo-vault is already in use" hatası alırsanız eski bir
> Vault konteyneri vardır → `docker rm -f jumbo-vault` ile silip tekrar deneyin.

Bundan sonraki `vault` komutları konteyner içinden çalışır (`VAULT_ADDR` orada tanımlı):
```bash
alias v='docker exec jumbo-vault vault'
```

---

## 1-B. Alternatif: config+policy GÖMÜLÜ özel imaj (mount'suz / registry)

Kapalı/hava-boşluklu prod'da host'ta repo bulunmayabilir. `Dockerfile`, `config.hcl` ve
`policies/`'i **imaja gömer** → çalıştırırken `-v config.hcl` / `-v policies` mount'una **gerek kalmaz**
(yalnız kalıcı veri volume'ü bağlanır).

**1) İmajı derle** (repo kökünden — `vault/` klasörünü bağlam olarak verir):
```bash
docker build -t jumbo-vault:1.18 vault/
# ya da:  cd vault && docker build -t jumbo-vault:1.18 .
```

**2) Çalıştır** — config/policy mount'u YOK, yalnız kalıcı veri volume'ü:
```bash
docker run -d --name jumbo-vault --restart unless-stopped \
  -p 8200:8200 --cap-add IPC_LOCK \
  -e VAULT_ADDR=http://127.0.0.1:8200 \
  -v jumbo-vault-data:/vault/file \
  jumbo-vault:1.18
```

**Hazır betik** — yukarıdaki **1)** ve **2)**'yi tek adımda yapar:
```bash
cd vault && ./run.sh
```

**3) Kontrol:**
```bash
docker ps                          # STATUS → "healthy" (gömülü HEALTHCHECK)
alias v='docker exec jumbo-vault vault'
v status                           # Initialized: false, Sealed: true  (normal — henüz kurulmadı)
```

**4) Sonraki adım → [§2 Init + Unseal](#2-init--unseal-tek-seferlik).** Init/unseal/PKI/KV/token
adımları §1'deki mount yöntemiyle **birebir aynıdır** (policy dosyası imajda gömülü olduğundan
§5'teki `v policy write jumbo-ro /vault/policies/jumbo-ro.hcl` yine çalışır).

**(Opsiyonel) İç registry'ye push** — hava-boşluklu prod'da host'ta repo/derleme olmadan dağıtım:
```bash
docker tag  jumbo-vault:1.18 registry.firma.local/jumbo-vault:1.18
docker push registry.firma.local/jumbo-vault:1.18
# prod host'ta:  docker run -d --name jumbo-vault ... registry.firma.local/jumbo-vault:1.18
```

> **İsim çakışırsa** (`name /jumbo-vault is already in use`) eski konteyner vardır →
> `docker rm -f jumbo-vault` ile silip 2. adımı tekrarlayın.
>
> **Gömülü:** `config.hcl` → `/vault/config/config.hcl`, policy → `/vault/policies/jumbo-ro.hcl`.
>
> **Gömülmez (runtime'da gelir):** TLS sertifika/anahtarı (`-v ./tls:/vault/tls:ro`) ve unseal
> key'leri/root token (init çıktısı) — bunlar imaja **KONULMAZ**. TLS için config.hcl'i düzenleyip
> imajı yeniden derleyin ya da §1'deki mount yöntemini kullanın.

---

## 2. Init + Unseal (tek seferlik)

```bash
v operator init -key-shares=5 -key-threshold=3
```

Çıktıda **5 Unseal Key** + **1 Initial Root Token** verilir. **BUNLARI GÜVENLİ SAKLAYIN**
(parola yöneticisi/kasa); kaybederseniz Vault verisi kurtarılamaz. Ardından 3 farklı unseal key ile:

```bash
v operator unseal <UNSEAL_KEY_1>
v operator unseal <UNSEAL_KEY_2>
v operator unseal <UNSEAL_KEY_3>
v status                      # Sealed: false görmelisiniz
```

Root token ile giriş (kurulum adımları için):
```bash
v login <ROOT_TOKEN>
```

---

## 3. PKI Secrets Engine (CA)

```bash
# PKI'yı 'pki' yoluna aç (JUMBO'nun varsayılan PKI Mount'u)
v secrets enable pki
v secrets tune -max-lease-ttl=87600h pki       # 10 yıl

# Kök CA üret (kurum içi CA örneği). Ara CA kullanacaksanız §3b'ye bakın.
v write -field=certificate pki/root/generate/internal \
    common_name="JUMBO Kurumsal Root CA" ttl=87600h > jumbo-root-ca.crt

# CRL / issuing URL'leri (JUMBO'nun eriştiği host:port ile)
v write pki/config/urls \
    issuing_certificates="http://<VAULT_HOST>:8200/v1/pki/ca" \
    crl_distribution_points="http://<VAULT_HOST>:8200/v1/pki/crl"

# Sertifika üretimi için rol (issue dış otomasyonca yapılır; JUMBO yalnız CA'yı okur)
v write pki/roles/jumbo \
    allowed_domains="firma.local" allow_subdomains=true max_ttl=8760h
```

Doğrulama (JUMBO'nun okuyacağı uç):
```bash
curl -s http://<VAULT_HOST>:8200/v1/pki/ca/pem | head -1   # -> -----BEGIN CERTIFICATE-----
```

> **§3b — Ara CA (önerilen kurumsal desen):** kök CA'yı çevrimdışı tutup Vault'a yalnız **ara CA**
> yükleyin: `pki/intermediate/generate/internal` → kökle imzalayın → `pki/intermediate/set-signed`.
> JUMBO açısından uç aynıdır (`pki/ca/pem`, `pki/cert/ca_chain`).

---

## 4. KV v2 Kasa

```bash
v secrets enable -path=secret kv-v2       # JUMBO'nun varsayılan KV Mount'u
# Örnek kayıt (JUMBO okur):
v kv put secret/certs/example note="JUMBO tarafından okunacak kasa girdisi"
```

---

## 5. JUMBO için Read-Only Token

```bash
# Read-only policy'yi yükle (dosya konteynere ./policies olarak bağlı)
v policy write jumbo-ro /vault/policies/jumbo-ro.hcl

# Uzun ömürlü, yenilenebilir bir servis token'ı üret (yalnız jumbo-ro yetkisiyle)
v token create -policy=jumbo-ro -period=768h -field=token   # 32 gün periyot, otomatik yenilenebilir
```

Çıkan token'ı JUMBO'ya gireceksiniz (§6). **Root token'ı günlük kullanmayın**; kurulum bitince
saklayın veya iptal edin (`v token revoke <ROOT_TOKEN>` — yalnız başka bir admin yolu bıraktıysanız).

---

## 6. JUMBO'ya Bağla

JUMBO arayüzü → **Ayarlar → Sistem → Vault (Hazırlık)**:

| Alan | Değer |
|---|---|
| Vault Entegrasyonu | **Açık** |
| Vault Adresi | `http://<VAULT_HOST>:8200` (aynı Docker ağındaysa `http://jumbo-vault:8200`) |
| Kimlik Doğrulama | **Token** |
| Token | §5'te üretilen `jumbo-ro` token |
| PKI Mount Path | `pki` |

**Kaydet** → **Bağlantıyı Test Et**. "Vault erişilebilir, PKI mount 'pki' hazır" görmelisiniz.

> **Ağ:** JUMBO `jumbo-net` Docker ağında çalışıyorsa Vault'u da o ağa katın
> (`compose.yaml` içindeki `networks` satırlarını açın) ve adresi `http://jumbo-vault:8200`
> yapın. Farklı hostsa `http://<VAULT_HOST>:8200` (firewall'da 8200 açık olmalı).
>
> **AppRole:** Ayarlar'da AppRole alanları vardır; mevcut sürümde JUMBO **token** ile doğrular.
> Token yolunu kullanın (yukarıdaki gibi).

---

## 7. Prod Sıkılaştırma (ÖNEMLİ)

- **TLS aç:** `config.hcl`'de `tls_disable = 0` yapıp `tls_cert_file`/`tls_key_file` satırlarını açın,
  sertifika/anahtarı `./tls` dizinine koyup compose'daki `./tls:/vault/tls:ro` satırını açın.
  Ardından adres `https://<VAULT_HOST>:8200` olur.
- **Unseal key custody:** 5 key'i farklı kişilere/kasalara dağıtın (Shamir); üçü olmadan mühür açılmaz.
  Otomatik açılış (yeniden başlatmada) için **auto-unseal** (Transit veya bulut KMS) yapılandırın.
- **Root token:** kurulumdan sonra iptal edin; günlük işleri policy'li token'larla yapın.
- **Yedek (raft snapshot):**
  ```bash
  docker exec jumbo-vault vault operator raft snapshot save /vault/file/backup.snap
  docker cp jumbo-vault:/vault/file/backup.snap ./vault-$(date +%F).snap
  ```
  Düzenli (cron) alın; geri yükleme: `vault operator raft snapshot restore`.
- **Volume:** `vault-data` volume'ünü yedek/monitör kapsamına alın (Vault verisi burada).
- **Yeniden başlatma:** Vault her açılışta **sealed** gelir → auto-unseal yoksa §2'deki unseal
  adımını tekrarlamanız gerekir.

---

## Sorun Giderme

| Belirti | Neden / Çözüm |
|---|---|
| JUMBO "PKI mount bulunamadı" | §3 yapılmadı ya da PKI farklı yola açıldı → mount = `pki` olmalı |
| JUMBO "Vault erişilemedi" | Adres/port yanlış, firewall kapalı ya da Vault **sealed** (§2 unseal) |
| `permission denied` | Token yanlış ya da policy eksik → §5'i tekrar edin (jumbo-ro) |
| Yeniden başlatınca bağlantı düştü | Vault sealed geldi → §2 unseal (veya auto-unseal kurun) |
| Compose'da izin hatası | Storage yolu `/vault/file` olmalı (imajda `vault` kullanıcısına ait) |
