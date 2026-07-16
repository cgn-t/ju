# JUMBO read-only Vault policy — YALNIZ OKUMA.
# JUMBO Vault'tan yalnız PKI CA zincirini ve KV kasa içeriğini OKUR; hiçbir şey yazmaz/üretmez.
# (Sertifika issue/renew ve özel anahtar velayeti Vault + dış otomasyonda kalır.)

# --- PKI CA zinciri (envantere alma: {pki}/ca/pem, {pki}/cert/ca_chain) ---
path "pki/cert/*" {
  capabilities = ["read"]
}
path "pki/ca/pem" {
  capabilities = ["read"]
}

# --- KV v2 kasa (JUMBO yalnız okur: {kv}/data/*, {kv}/metadata/*) ---
path "secret/data/*" {
  capabilities = ["read"]
}
path "secret/metadata/*" {
  capabilities = ["read", "list"]
}

# --- Sağlık kontrolü ("Bağlantıyı Test Et") ---
path "sys/health" {
  capabilities = ["read"]
}
