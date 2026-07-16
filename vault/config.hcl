## HashiCorp Vault — üretim sunucu yapılandırması (JUMBO PKI CA + KV kasa için).
## Integrated Storage (raft) tek düğüm. HA için birden çok düğüm + retry_join ekleyin.

ui = true

# Integrated storage (raft) ile disable_mlock=true ÖNERİLİR (Vault verisini zaten diske yazar).
disable_mlock = true

storage "raft" {
  path    = "/vault/file"          # imajda 'vault' kullanıcısına ait, yazılabilir dizin (kalıcı volume)
  node_id = "jumbo-vault-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1                  # ⚠️ PROD: TLS AÇIN — aşağıyı doldurup tls_disable = 0 yapın
  # tls_cert_file = "/vault/tls/vault.crt"
  # tls_key_file  = "/vault/tls/vault.key"
}

# Tek düğümde 127.0.0.1 yeterli; HA/çok düğümde bu adresleri diğer düğümlerin eriştiği host:port yapın.
api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"
