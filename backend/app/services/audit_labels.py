"""Audit Log okunurluk katmanı — işlem/nesne/alan Türkçe etiketleri ve tek satırlık özet.

TEK KAYNAK: hem CSV dışa aktarımı hem UI (/api/audit/meta) bu sözlükleri kullanır.
Listede olmayan anahtar ham haliyle gösterilir (yeni bir log_action eklenince ekran bozulmaz).
"""

import json

from app.services.audit import CATEGORIES, MASK

CATEGORY_LABELS = {
    "changes": "Değişiklikler",
    "approval": "Onay & Değişiklik",
    "security": "Güvenlik",
    "system": "Sistem",
}
assert set(CATEGORY_LABELS) == set(CATEGORIES)

ACTION_LABELS = {
    "create": "Oluşturma", "update": "Güncelleme", "delete": "Silme", "import": "İçe aktarma",
    "deactivate": "Pasife alma", "adopt": "Envantere alma", "ignore": "Yok sayma",
    "vault_sync": "Vault senkronizasyonu", "duplicate_detected": "Mükerrer tespit",
    "propose": "Değişiklik talebi", "approve": "Talep onayı", "propose_reject": "Talep reddi",
    "propose_cancel": "Talep iptali", "supersede_apply": "Değişiklik uygulandı",
    "trusted_add_apply": "Trust store'a eklendi",
    "server_add_apply": "Bağlantı eklendi (talep)", "server_remove_apply": "Bağlantı kaldırıldı (talep)",
    "date_fix_apply": "Tarih güncellendi (talep)",
    "login": "Giriş", "login_failed": "Başarısız giriş",
    "add_member": "Ekibe üye ekleme", "remove_member": "Ekipten üye çıkarma",
    "live_check_run": "Canlı doğrulama", "notify": "Bildirim çalıştırma",
    "revocation_run": "İptal denetimi başlatma", "revocation_check": "İptal kontrolü",
    "scan": "Keşif taraması", "test": "Bağlantı testi", "job_summary": "Zamanlanmış iş",
    "trigger": "Tetikleme", "rerun": "Yeniden çalıştırma", "retry": "Adım tekrarı",
    "cancel": "İptal", "ct-scan": "CT izleme", "mail_retry": "Mail yeniden kuyruğa",
    "name_mismatch_ok": "Adres uyumsuzluğu onayı", "chain_repair": "Zincir düzeltme",
    "ai_ask": "AI sorusu",
    "regression_start": "Regresyon testi başladı", "regression_mark": "Regresyon senaryosu",
    "regression_end": "Regresyon testi bitti", "regression_auto": "Regresyon otomatik kontrol",
    "regression_lab": "Regresyon test hazırlığı", "regression_cleanup": "Regresyon test verisi temizlendi",
}

# İşlem rengi (UI çip) — kategori renginden bağımsız, işlemin doğasına göre
ACTION_TONE = {
    "create": "success", "import": "success", "adopt": "success", "approve": "success",
    "supersede_apply": "success", "trusted_add_apply": "success", "add_member": "success",
    "server_add_apply": "success", "server_remove_apply": "warning", "date_fix_apply": "success",
    "update": "info", "propose": "info", "vault_sync": "info", "chain_repair": "info",
    "delete": "error", "login_failed": "error", "propose_reject": "error", "remove_member": "error",
    "deactivate": "warning", "propose_cancel": "warning", "cancel": "warning",
    "duplicate_detected": "warning", "ignore": "warning", "name_mismatch_ok": "warning",
}

TABLE_LABELS = {
    "certificates": "Sertifika", "SSLCertificates": "Sertifika", "domains": "Domain",
    "certificate_domain_map": "Domain bağlantısı", "applications": "Uygulama",
    "app_dependencies": "Trusted bağlantı", "app_trusted_certs": "Trust store",
    "transfer_proposals": "Değişiklik talebi", "users": "Kullanıcı", "teams": "Ekip",
    "user_teams": "Ekip üyeliği", "tags": "Etiket", "app_settings": "Ayarlar",
    "scan_targets": "Keşif hedefi", "scan_runs": "Keşif taraması",
    "discovered_certificates": "Keşfedilen sertifika", "notifications": "Bildirim",
    "deployment_flows": "Dağıtım akışı", "deployment_run": "Dağıtım çalıştırması",
    "deployment_run_step": "Dağıtım adımı", "jenkins_job": "Jenkins işi", "jobs": "Zamanlanmış iş",
    "mail_queue": "Mail kuyruğu", "ai": "AI asistanı", "regression": "Regresyon testi",
}

FIELD_LABELS = {
    # Domain
    "domain": "Domain", "external_address": "Dış adres", "cert_owner": "Sertifika sahibi",
    "lb_update": "LB güncelleme", "env_update": "Ortam güncelleme", "waf_update": "WAF güncelleme",
    "external_company": "Dış firma", "expire_date": "Bitiş tarihi", "info": "Detay",
    "mail_addresses": "Mail adresleri", "action_required": "Aksiyon", "ssl_pinning": "SSL pinning",
    "keystore": "Keystore", "ug_team_id": "UG ekibi", "sy_team_id": "SY ekibi",
    "ug_team_name": "UG ekip adı", "servers_to_update": "Güncellenecek sunucular",
    "notify_days": "Bildirim günü",
    # Sertifika
    "name": "Ad", "serial_number": "Serial Number", "issuer": "Issuer", "subject": "Subject",
    "cert_type": "Tür", "valid_from": "ValidFrom", "valid_to": "ValidTo", "is_active": "Aktif",
    "purchased_by": "Satın alan", "notes": "Notlar", "environment": "Ortam", "source": "Kaynak",
    "fingerprint_sha256": "SHA-256 Fingerprint", "vault_path": "Vault yolu", "parent_id": "Üst sertifika",
    # Uygulama
    "app_name": "Uygulama adı", "app_user": "Uygulama kullanıcısı", "conf_path": "Konfigürasyon yolu",
    "control_method": "Kontrol yöntemi", "dns": "DNS", "ip_address": "IP adresi", "log_path": "Log yolu",
    "required_commands": "Gerekli komutlar", "server_name": "Sunucu adı",
    "service_provider_contact": "Servis sağlayıcı iletişim", "start_stop_method": "Başlat/durdur yöntemi",
    "status": "Durum", "domain_id": "Domain", "tags": "Etiketler", "cert_id": "Sertifika",
    # Kullanıcı / ekip / etiket
    "username": "Kullanıcı adı", "full_name": "Ad soyad", "email": "E-posta", "role": "Rol",
    "auth_source": "Kimlik kaynağı", "password": "Şifre", "type": "Tür", "category": "Kategori",
    "color": "Renk",
    # Keşif / akış
    "value": "Değer", "ports": "Portlar", "enabled": "Etkin", "kind": "Tür", "description": "Açıklama",
    "definition": "Akış tanımı",
    # Bağlam alanları (detay çekmecesi)
    "old_name": "Eski sertifika", "new_name": "Yeni sertifika", "reason": "Sebep", "note": "Not",
    "via": "Kaynak", "mapping_type": "Bağlantı tipi", "domains": "Domainler", "certificates": "Sertifikalar",
    "count": "Adet", "live_seen": "Canlıda görüldü", "served_cn": "Sunulan sertifika",
    "member": "Üye", "team": "Ekip", "job": "İş", "duration_s": "Süre (sn)", "error": "Hata",
    "total": "Toplam", "checked": "Kontrol edilen", "sent": "Gönderilen", "skipped": "Atlanan",
    "revoked": "İptal edilmiş", "mismatched": "Eşleşmeyen", "by_status": "Duruma göre",
    "targets": "Hedef", "reachable": "Erişilebilir", "new_findings": "Yeni bulgu",
    "success": "Başarılı", "message": "Mesaj", "target": "Hedef", "endpoint": "Uç",
    "file": "Dosya", "created": "Oluşturulan", "updated": "Güncellenen", "proposals": "Talepler",
    "serial": "Serial Number", "cert": "Sertifika", "app": "Uygulama", "fields": "Alanlar", "host": "Host",
    "port": "Port", "flow_name": "Akış", "trigger": "Tetikleme", "creator": "Oluşturan", "chain": "Zincir",
    "superseded": "Değiştirilen", "paths": "Yollar", "params": "Parametreler", "ok": "Başarılı",
    "node_id": "Adım", "jenkins_job": "Jenkins işi", "flow_id": "Akış", "user_id": "Kullanıcı",
    "issuance_profile_id": "Sertifika profili", "auto_issuance_enabled": "Otomatik üretim",
    "issuance_zero_touch": "Zero-touch", "issuance_renew_before_days": "Yenileme (gün önce)",
    "old_id": "Eski sertifika #", "new_id": "Yeni sertifika #", "proposal_id": "Talep #",
    "dep_id": "Bağımlılık #", "target_domain_id": "Hedef domain #", "run_id": "Çalıştırma #",
    "source_run_id": "Kaynak çalıştırma #", "recipients": "Alıcılar", "previous_error": "Önceki hata",
}

# Bilinen kod değerlerinin okunur karşılığı (alan → {değer: etiket})
VALUE_LABELS = {
    "trigger": {"manual": "Manuel", "schedule": "Zamanlanmış"},
    "type": {"server": "Server", "client": "Trusted (client)", "SY": "SY", "UG": "UG"},
    "mapping_type": {"server": "Server", "client": "Trusted (client)"},
    "status": {"good": "Geçerli", "revoked": "İptal edilmiş", "unknown": "Bilinmiyor",
               "match": "Eşleşiyor", "mismatch": "EŞLEŞMİYOR",
               "chain_incomplete": "Ara sertifika eksik", "unreachable": "Erişilemedi",
               "no_mapping": "Bağlı sertifika yok", "not_checkable": "Kontrol edilemez",
               "ok": "Tamamlandı", "error": "Hata"},
    "via": {"live-check": "Canlı doğrulama", "import": "İçe aktarma", "manual": "Manuel",
            "vault-sync": "Vault senkronizasyonu", "import-chain": "Canlıdan içe aktarma",
            "attach": "Bağlantı çakışması", "backfill": "Geriye dönük tarama",
            "live-chain": "Canlıdan içe aktarma"},
}

_BOOL = {True: "Evet", False: "Hayır"}


def field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key)


def value_label(key: str, v):
    return VALUE_LABELS.get(key, {}).get(v, v) if isinstance(v, str) else v


def _fmt(v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return _BOOL[v]
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v) or "—"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    s = str(v)
    # ISO tarih → gün (saat gürültüsü özet satırında gereksiz)
    if len(s) >= 19 and s[4] == "-" and s[10] == "T":
        return s[:10]
    return s


def parse_details(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def summarize(action: str, details) -> str:
    """Satırın tek bakışta okunur özeti (tabloda 'Değişiklik' kolonu ve CSV)."""
    if details is None:
        return ""
    if isinstance(details, str):
        return details[:300]
    if isinstance(details, list):  # eski biçim: değişen alan adları listesi
        return "Değişen alanlar: " + ", ".join(field_label(str(x)) for x in details)
    changes = details.get("changes")
    if isinstance(changes, dict):
        if not changes:
            return "Değişiklik yok"
        parts = []
        for k, e in list(changes.items())[:3]:
            if e.get("masked"):
                parts.append(f"{field_label(k)} değişti")
            else:
                old = e.get("old_label", e.get("old"))
                new = e.get("new_label", e.get("new"))
                parts.append(f"{field_label(k)}: {_fmt(old)} → {_fmt(new)}")
        more = len(changes) - 3
        return "; ".join(parts) + (f" (+{more} alan)" if more > 0 else "")
    if action == "login_failed":
        return details.get("reason") or "Başarısız giriş"
    if action == "job_summary":
        st = {"ok": "tamamlandı", "error": "HATA"}.get(details.get("status"), details.get("status") or "")
        bits = [f"{field_label(k)}: {_fmt(details[k])}" for k in
                ("total", "checked", "sent", "revoked", "targets", "new_findings", "errors")
                if details.get(k) not in (None, 0, "")]
        if details.get("by_status"):
            bits.append(_fmt(details["by_status"]))
        return f"{details.get('job', '')} {st}" + (f" — {', '.join(bits)}" if bits else "")
    if action == "ai_ask":
        return details.get("question") or ""
    if action == "test":
        return f"{details.get('target', '')}: {'başarılı' if details.get('success') else 'BAŞARISIZ'}"
    if action == "regression_start":
        return f"{details.get('title') or ''} (v{details.get('version') or '?'})"
    if action == "regression_mark":
        res = {"pass": "Geçti", "fail": "Kaldı", "skip": "Atlandı"}.get(details.get("result"), "işaret kaldırıldı")
        return f"{details.get('scenario') or ''}: {res}" + (f" — {details['note']}" if details.get("note") else "")
    if action == "regression_lab":
        return details.get("step") or ""
    if action == "regression_cleanup":
        c = details.get("counts") or {}
        names = {"certificates": "sertifika", "domains": "domain", "applications": "uygulama",
                 "users": "hesap", "teams": "ekip"}
        return ", ".join(f"{v} {names.get(k, k)}" for k, v in c.items() if v) or "silinecek kayıt yoktu"
    if action in ("regression_end", "regression_auto"):
        c = details.get("counts") or {}
        labels = {"pass": "geçti", "fail": "kaldı", "skip": "atlandı", "pending": "bekliyor",
                  "ok": "yeşil", "warn": "sarı"}
        return ", ".join(f"{v} {labels.get(k, k)}" for k, v in c.items() if v and k != "total")
    if action in ("propose", "approve", "propose_reject", "propose_cancel", "supersede_apply"):
        s = f"{details.get('old_name') or '?'} → {details.get('new_name') or '?'}"
        if details.get("domains"):
            s += f" ({', '.join(details['domains'])})"
        elif details.get("domain"):
            s += f" ({details['domain']})"
        if details.get("note"):
            s += f" — not: {details['note']}"
        return s
    if "snapshot" in details:
        snap = details["snapshot"] or {}
        ident = next((snap[k] for k in ("name", "domain", "app_name", "username", "cert", "app")
                      if snap.get(k)), None)
        return f"Silinen: {ident}" if ident else "Silinen kaydın özeti saklandı"
    skip = {"old_id", "new_id", "domain_id", "cert_id", "app_id", "user_id", "proposal_id",
            "dep_id", "target_domain_id", "run_id"}
    pairs = [f"{field_label(k)}: {_fmt(value_label(k, v))}" for k, v in details.items()
             if k not in skip and v not in (None, "", [], {}) and v != MASK]
    return "; ".join(pairs[:4])


def meta() -> dict:
    return {"categories": CATEGORY_LABELS, "actions": ACTION_LABELS, "action_tone": ACTION_TONE,
            "tables": TABLE_LABELS, "fields": FIELD_LABELS, "values": VALUE_LABELS}
