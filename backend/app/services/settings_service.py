"""Kategori bazlı ayarların okunması/yazılması. Hassas alanlar Fernet ile şifrelenir."""

import json
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppSetting

logger = logging.getLogger(__name__)

# Kategori bazında şifrelenecek alan adları
SENSITIVE_KEYS = {
    "ldap.bind_password",
    "smtp.password",
    "vault.token",
    "vault.secret_id",
    # Bildirim kanalları: Incoming Webhook URL'leri taşıyıcı-sır niteliğindedir (bilen POST atabilir).
    "slack.webhook_url",
    "teams.webhook_url",
    "webhook.auth_header",
    "servicenow.password",   # ServiceNow entegrasyon kullanıcısının şifresi
    "zoom.token",            # Zoom Incoming Webhook doğrulama token'ı (bearer-sır)
    "jabber.password",       # XMPP gönderen JID'inin şifresi
    "jira.api_token",        # Jira API token / PAT / şifre (Basic ya da Bearer)
    "jenkins.api_token",     # Jenkins API token ya da şifre (Basic auth)
}

DEFAULTS: dict[str, dict] = {
    "ldap": {
        "enabled": False,
        "server": "",
        "port": 636,
        "use_ssl": True,             # LDAPS (doğrudan TLS, 636)
        "start_tls": False,          # StartTLS ile düz bağlantıyı (389) TLS'e yükselt (legacy)
        "skip_cert_verify": False,   # sunucu sertifikasını doğrulama (YALNIZ dev)
        "ca_cert": "",               # dahili CA PEM demeti (boşsa sistem kökleri)
        "base_dn": "",
        "bind_dn": "",
        "bind_password": "",
        "user_filter": "(sAMAccountName={username})",
        "user_attr": "sAMAccountName",   # giriş adını tutan attribute
        "email_attr": "mail",            # e-posta attribute'u
        "display_attr": "displayName",   # görünen ad attribute'u
        "group_base": "",                # memberOf yoksa grupların aranacağı taban
        "group_filter": "",              # ör. (member={user_dn})
        "group_role_map": {},  # {"CN=JUMBO-Admins,...": "admin"}
        "default_role": "viewer",
    },
    "smtp": {
        "enabled": False,
        "host": "",
        "port": 25,
        "use_tls": False,
        "username": "",
        "password": "",
        "from_address": "jumbo@localhost",
        "expiry_warning_days": 30,
        # Dış otomasyonun (cron/zamanlayıcı) süre-uyarısı taramasını tetikleme anahtarı:
        # POST /api/notifications/expiry-run + "X-API-Key: <bu değer>". BOŞSA dış tetikleme
        # KAPALI (yalnız admin JWT çalışır). Düşük yetkili: yalnız bildirim gönderimini başlatır,
        # veri okuyamaz/değiştiremez.
        "trigger_api_key": "",
    },
    "vault": {
        "enabled": False,
        "address": "",
        "auth_method": "token",  # token|approle
        "token": "",
        "role_id": "",
        "secret_id": "",
        "pki_mount": "pki",
        "kv_mount": "secret",   # KV v2 secret store (dev Vault'ta secret/ hazır gelir)
        "kv_prefix": "certs",   # sertifikaların tutulduğu KV yol öneki
    },
    "general": {
        "expiring_soon_days": 30,
        "dashboard_cert_count": 20,
    },
    "discovery": {
        "enabled": False,             # gece cron taramasını aç/kapa (varsayılan KAPALI)
        "default_ports": "443,8443,9443",  # hedefte port belirtilmezse taranacak portlar
        "concurrency": 32,            # eşzamanlı TLS handshake sayısı
        "timeout_seconds": 6,         # her endpoint için bağlantı zaman aşımı
        "max_hosts": 4096,            # bir taramada üretilecek azami (host×port) hedef sayısı
        "schedule_hour": 3,           # gece cron saati (0-23)
    },
    "ct": {
        # Certificate Transparency (crt.sh) izleme. DIŞ İNTERNET erişimi gerekir → varsayılan KAPALI;
        # kapalı ağda opsiyonel forward proxy ile erişilir, erişilemezse tarama hatayı kaydedip geçer.
        "enabled": False,             # gece cron CT taramasını aç/kapa (varsayılan KAPALI)
        "proxy_url": "",              # crt.sh'e ulaşmak için opsiyonel forward proxy (http://host:port)
        "timeout_seconds": 15,        # crt.sh isteği zaman aşımı (sn)
        "concurrency": 4,             # domain başına eşzamanlı sertifika indirmesi (crt.sh nazik)
        "schedule_hour": 4,           # gece cron saati (0-23)
        "max_domains": 0,             # taranacak azami envanter domaini (0 = hepsi)
        "max_entries_per_domain": 100,  # domain başına işlenecek azami CT girişi
        "match_wildcards": True,      # '*.x.com' envanter domaini için 'x.com' tabanını sorgula
    },
    "policy": {
        # Sertifika uyum politikası. TAMAMEN YEREL (dış erişim yok) → varsayılan AÇIK; ihlaller
        # envanter üstünde okuma-anında hesaplanır. CA allowlist kullanıcı doldurana dek zorlanmaz.
        "enabled": True,              # uyum değerlendirmesi açık mı
        "enforce_ca_allowlist": False,  # issuer allowlist dışıysa ihlal say (liste boşken kapalı tut)
        "ca_allowlist": [],           # izinli issuer parçaları (CN/issuer alt-dizesi, büyük/küçük duyarsız)
        "min_rsa_bits": 2048,         # bundan küçük RSA anahtarı zayıf sayılır
        "min_ec_bits": 256,           # bundan küçük EC eğrisi zayıf sayılır
        "banned_sig_hashes": ["sha1", "md5"],  # yasak imza özet algoritmaları
        "max_validity_days": 398,     # bundan uzun ömür ihlal (0 = kapalı)
        "check_discovered": False,    # keşif bulgularını da değerlendir (şimdilik yalnız envanter)
    },
    "revocation": {
        # İptal (OCSP/CRL) denetimi. DIŞ ERİŞİM gerekir → varsayılan KAPALI; iç/özel CA'lar çoğu
        # zaman public OCSP sunmaz → çok sayıda 'unknown' normaldir. Sertifikayı asla pasife almaz.
        "enabled": False,             # gece cron iptal denetimini aç/kapa (varsayılan KAPALI)
        "proxy_url": "",              # OCSP/CRL uçlarına ulaşmak için opsiyonel forward proxy
        "timeout_seconds": 10,        # OCSP/CRL isteği zaman aşımı (sn)
        "method": "ocsp_then_crl",    # ocsp | crl | ocsp_then_crl
        "schedule_hour": 5,           # gece cron saati (0-23)
        "check_active_only": True,    # yalnız aktif sertifikaları denetle
    },
    # --- Bildirim kanalları (e-posta DIŞI). Süre uyarıları e-postaya EK olarak bu kanallara da
    #     yayınlanır. Dış SaaS (Slack/Teams) kapalı ağda erişilemeyebilir → opsiyonel proxy + graceful.
    "slack": {
        "enabled": False,
        "webhook_url": "",            # Slack Incoming Webhook URL (gizli — Fernet ile şifrelenir)
        "proxy_url": "",              # kapalı ağda Slack'e ulaşmak için opsiyonel forward proxy
        "timeout_seconds": 10,
    },
    "teams": {
        "enabled": False,
        "webhook_url": "",            # Microsoft Teams Incoming Webhook URL (gizli)
        "proxy_url": "",
        "timeout_seconds": 10,
    },
    "webhook": {
        "enabled": False,
        "url": "",                    # generic hedef URL (ServiceNow-dışı entegrasyonlar)
        "auth_header": "",            # "Başlık: değer" (gizli) — ör. "Authorization: Bearer xxx"
        "proxy_url": "",
        "timeout_seconds": 10,
    },
    "servicenow": {
        "enabled": False,
        "instance_url": "",           # ör. https://firma.service-now.com
        "username": "",               # entegrasyon kullanıcısı
        "password": "",               # şifre (gizli — Fernet ile şifrelenir)
        "proxy_url": "",              # bulut örneğe kapalı ağdan ulaşmak için opsiyonel proxy
        "timeout_seconds": 10,
    },
    "jira": {
        # Jira'da issue (talep/görev) açar. Telekomda genelde on-prem (Data Center) + PAT/Bearer.
        "enabled": False,
        "base_url": "",               # Cloud: https://firma.atlassian.net · DC: https://jira.firma.local
        "auth_mode": "basic",         # basic (kullanıcı+token) | bearer (Data Center PAT)
        "username": "",               # Cloud: hesap e-postası · DC-basic: kullanıcı · bearer'da boş
        "api_token": "",              # Cloud API token · DC PAT · veya şifre (gizli)
        "project_key": "",            # ör. OPS — issue'nun açılacağı proje
        "issue_type": "Task",         # ör. Task | Incident | Service Request
        "proxy_url": "",
        "timeout_seconds": 10,
    },
    "zoom": {
        "enabled": False,
        "webhook_url": "",            # Zoom 'Incoming Webhook' uygulamasının Endpoint URL'i
        "token": "",                  # doğrulama token'ı (gizli — Authorization başlığı)
        "proxy_url": "",
        "timeout_seconds": 10,
    },
    "jabber": {
        # Jabber/XMPP (on-prem: ejabberd / Openfire / Cisco Jabber). İÇ AĞ → proxy yok.
        "enabled": False,
        "host": "",                   # XMPP sunucu host (boşsa JID alanından DNS SRV çözülür)
        "port": 5222,
        "jid": "",                    # gönderen JID (ör. jumbo@firma.local)
        "password": "",               # JID şifresi (gizli — Fernet ile şifrelenir)
        "target": "",                 # hedef JID ya da MUC oda JID'i (ör. noc@conference.firma.local)
        "is_muc": False,              # hedef bir MUC (grup) odası mı
        "skip_cert_verify": False,    # sunucu TLS sertifikasını doğrulama (YALNIZ dev)
        "timeout_seconds": 10,
    },
    "jenkins": {
        # JUMBO Jenkins JOB'larını tetikler (genel — herhangi bir job + parametre). NetScaler cert
        # deploy bunun bir kullanımıdır: 'netscaler_job' CERTKEY (domain başına) + VAULT_PATH ile
        # tetiklenir. Custody yok — anahtar Vault→Jenkins→NITRO; JUMBO görmez.
        "enabled": False,
        "base_url": "",               # ör. http://jumbo-jenkins:8080
        "username": "",               # Jenkins kullanıcısı
        "api_token": "",              # API token ya da şifre (gizli — Basic auth)
        "skip_cert_verify": False,    # https ise sunucu TLS sertifikasını doğrulama (YALNIZ dev)
        "netscaler_job": "netscaler-deploy",   # sertifika 'Dağıt' butonunun tetiklediği job
        "proxy_url": "",
        "timeout_seconds": 15,
    },
}


def _fernet() -> Fernet | None:
    key = get_settings().fernet_key
    return Fernet(key.encode()) if key else None


def get_category(db: Session, category: str, mask_secrets: bool = True) -> dict:
    result = dict(DEFAULTS.get(category, {}))
    rows = db.query(AppSetting).filter(AppSetting.category == category).all()
    f = _fernet()
    for row in rows:
        field = row.key.split(".", 1)[1]
        raw = row.value
        sensitive = row.key in SENSITIVE_KEYS
        if sensitive and mask_secrets and raw:
            result[field] = "********"
            continue
        if row.is_encrypted and raw:
            if f:
                try:
                    raw = f.decrypt(raw.encode()).decode()
                except InvalidToken:
                    raw = ""
            else:
                raw = ""
        result[field] = json.loads(raw) if raw else raw
    return result


def save_category(db: Session, category: str, values: dict) -> None:
    f = _fernet()
    for field, value in values.items():
        key = f"{category}.{field}"
        sensitive = key in SENSITIVE_KEYS
        if sensitive and value == "********":
            continue  # maskelenmiş değer geri gönderildi, dokunma
        # GÜVENLİK (CWE-312 fail-closed): FERNET_KEY yoksa hassas değeri DÜZ METİN saklama. Aksi halde
        # get_category maskelese de (********) değer prod DB'sinde açık dururdu. Şifrelenemiyorsa hiç yazma.
        if sensitive and value and not f:
            logger.warning("FERNET_KEY tanımlı değil — '%s' hassas ayarı şifrelenemediği için "
                           "KAYDEDİLMEDİ (düz metin saklanmaz).", key)
            continue
        serialized = json.dumps(value)
        if sensitive and f and value:
            serialized = f.encrypt(json.dumps(value).encode()).decode()
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, category=category)
            db.add(row)
        row.value = serialized
        row.is_encrypted = bool(sensitive and f and value)
    db.commit()
