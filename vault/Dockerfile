# JUMBO Vault — config + policy'leri GÖMÜLÜ taşıyan Vault imajı.
#
# Neden ayrı imaj? Kapalı/hava-boşluklu prod'da host'ta repo bulunmayabilir. Bu imaj
# config.hcl ve policies/'i içine alır → çalıştırırken -v config/-v policies MOUNT'una GEREK YOK,
# yalnız kalıcı veri volume'ü (/vault/file) bağlanır. İç registry'ye push'layıp öyle dağıtın.
#
# Derle:   docker build -t jumbo-vault:1.18 vault/         (repo kökünden)
#          # ya da:  cd vault && docker build -t jumbo-vault:1.18 .
# Çalıştır: README.md §1-B (config/policy mount'suz, sade run)
#
# NOT: TLS sertifika/anahtarı ve unseal key'leri ASLA imaja gömmeyin — bunlar runtime'da
# volume/-e ile gelir (README §7). Bu imaj yalnız statik config + read-only policy içerir.

FROM hashicorp/vault:1.18

# Sunucu yapılandırması. İmaj entrypoint'i 'server' argümanında otomatik '-config=/vault/config'
# ekler; config.hcl'i tam o dizine koyuyoruz (ekstra -config VERİLMEZ → çift-yükleme/port çakışması yok).
COPY config.hcl /vault/config/config.hcl

# JUMBO read-only policy — kurulumda 'vault policy write jumbo-ro /vault/policies/jumbo-ro.hcl' ile yüklenir.
COPY policies/ /vault/policies/

EXPOSE 8200

# Konteyner canlılığı: Vault süreci ayakta + API cevap veriyor mu? sealed/standby/uninit durumları da
# SAĞLIKLI sayılır (restart sonrası unseal edilene kadar 'sealed' NORMAL steady-state'tir).
# TLS açarsanız (tls_disable=0) http -> https yapın ve '--no-check-certificate' ekleyin.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:8200/v1/sys/health?standbycode=200&sealedcode=200&uninitcode=200" >/dev/null 2>&1 || exit 1

# Yalnız 'server' — config zaten /vault/config'den otomatik yüklenir.
CMD ["server"]
