"""AI asistanının veritabanı okuma araçları: veri_tablolari ve veri_sorgula (salt-okur).

AI SQL yazmaz. Tabloyu, filtreleri, sıralamayı ve gruplamayı araç parametresi olarak verir;
sorgu burada SQLAlchemy ile kurulur, yalnız SELECT çalışır. Yalnız TABLES'taki tablolar ve
kolonlar görünür:
  - Kişisel bilgi yok: kullanıcının e-postası, şifresi, son giriş zamanı; işlem geçmişinde IP
    adresi. Yönetici olmayanlar giriş kayıtlarını, kullanıcı/ayar değişikliklerini görmez. AI'a
    sorulan sorular (ai_ask) kimseye gösterilmez.
  - Sır yok: app_settings tablosu hiç yok; Jenkins adım parametreleri yok.
  - Büyük alanlar yok ya da kısaltılır: PEM, mail gövdesi, akış tanımı.
Kimlik kolonlarının (sy_team_id, certificate_id …) yanına okunur ad eklenir (sy_team_adi …).
"""

from datetime import datetime, timezone

from sqlalchemy import and_, func, inspect, not_, or_
from sqlalchemy.orm import Session

from app.core.textmatch import ci_equals, ci_like
from app.core.timeutil import ISTANBUL, ist_to_utc
from app.db.models import (AppDependency, Application, ApplicationTag, ApplicationTrustedCert,
                           AuditLog, Certificate, CertificateDomainMap, DeploymentFlow,
                           DeploymentRun, DeploymentRunStep, DiscoveredCertificate, Domain,
                           MailQueue, Notification, ScanRun, ScanTarget, Tag, Team,
                           TransferProposal, User, UserTeam)

DEFAULT_ROWS = 30
MAX_ROWS = 100
MAX_TEXT = 500
LONG_TEXT = {"live_check_detail": 1500, "definition": 1500, "details": 1000}

# Takvim tarihi olan kolonlar olduğu gibi gösterilir (ekrandaki ValidTo ile aynı gün kalsın);
# diğer zaman kolonları (oluşturma, gönderim …) UTC'den Türkiye saatine çevrilir.
CALENDAR_DATES = {"valid_from", "valid_to", "expire_date"}

PERSONAL_ACTIONS = ("ai_ask", "login", "login_failed")
PERSONAL_TABLES = ("users", "app_settings")


def _audit_filter(user: User) -> list:
    if user.role == "admin":
        return [AuditLog.action != "ai_ask"]
    return [AuditLog.action.notin_(PERSONAL_ACTIONS), AuditLog.table_name.notin_(PERSONAL_TABLES)]


# tablo adı → (model, açıklama, {kolon: açıklama}, varsayılan sıralama (kolon, azalan), link, satır filtresi)
TABLES: dict[str, tuple] = {
    "sertifikalar": (Certificate, "SSL sertifikaları (envanter)", {
        "id": "", "name": "Sertifika adı (CN)", "cert_type": "leaf | intermediate | root",
        "issuer": "Issuer", "subject": "Subject", "serial_number": "Serial Number", "san": "SAN listesi",
        "valid_from": "ValidFrom", "valid_to": "ValidTo (bitiş)", "is_active": "aktif mi (pasif = false)",
        "is_internal": "kurum içi CA mı", "environment": "Prod | Test", "creator": "Oluşturan Ekip (SY ekip adı)",
        "purchased_by": "Satın Alım Yapan", "notes": "Notlar", "source": "manual | vault | live",
        "fingerprint_sha256": "SHA-256 Fingerprint", "subject_key_identifier": "SKI",
        "authority_key_identifier": "AKI", "public_key_type": "RSA | EC …", "key_size": "anahtar bit",
        "key_curve": "EC eğrisi", "signature_hash": "imza özeti (sha256, sha1 …)",
        "extended_key_usage": "EKU", "revocation_status": "good | revoked | unknown | unreachable | not_checkable",
        "revocation_checked_at": "son iptal kontrolü", "parent_id": "üst (Issuer) sertifika id",
        "superseded_by_id": "yerine geçen yeni sertifika id", "auto_renew": "",
        "created_at": "kayıt zamanı", "updated_at": "son değişiklik",
    }, ("valid_to", False), lambda r: f"/certificates?cert={r['id']}", None),
    "domainler": (Domain, "Domainler", {
        "id": "", "domain": "domain adı", "sy_team_id": "sahibi SY ekibi", "ug_team_id": "UG ekibi",
        "ug_team_name": "UG ekip etiketi", "external_address": "Dış Adres", "external_company": "Dış Firma",
        "cert_owner": "sertifika sahibi", "mail_addresses": "ek bildirim adresleri",
        "notify_days": "Bildirim Gün Sayısı (boş = varsayılan)", "servers_to_update": "Güncellenecek Sunucular",
        "keystore": "Keystore", "ssl_pinning": "SSL Pinning", "lb_update": "LB güncelleme",
        "env_update": "Ortam güncelleme", "waf_update": "WAF güncelleme", "action_required": "Aksiyon",
        "expire_date": "Manuel Bitiş Tarihi", "info": "Detay",
        "live_check_status": "son Canlı Doğrulama: match | mismatch | chain_incomplete | unreachable | no_mapping | not_checkable",
        "live_check_at": "son Canlı Doğrulama zamanı", "live_check_detail": "son Canlı Doğrulama detayı (JSON)",
        "created_at": "", "updated_at": "",
    }, ("domain", False), lambda r: f"/domains?domain={r['id']}", None),
    "sertifika_domain_baglantilari": (CertificateDomainMap, "Hangi sertifika hangi domaine bağlı", {
        "id": "", "certificate_id": "sertifika", "domain_id": "domain",
        "mapping_type": "server (sunucunun sunduğu) | client (Trusted: domainin güvendiği)",
    }, ("id", True), None, None),
    "uygulamalar": (Application, "Uygulamalar", {
        "id": "", "app_name": "Uygulama Adı", "server_name": "Sunucu Adı", "ip_address": "IP Adresi",
        "dns": "DNS", "domain_id": "Bağlı Domain", "sy_team_id": "sahibi SY ekibi", "ug_team_id": "UG ekibi",
        "status": "aktif mi", "app_user": "Uygulama Kullanıcısı", "conf_path": "Config Path",
        "log_path": "Log Path", "control_method": "Kontrol Yöntemi", "start_stop_method": "Start/Stop Yöntemi",
        "required_commands": "Gerekli Komutlar", "service_provider_contact": "Servis Sağlayıcı İletişim",
        "info": "Bilgi", "notes": "Notlar",
    }, ("app_name", False), None, None),
    "uygulama_bagimliliklari": (AppDependency, "Uygulamanın bağlandığı hedef domainler (Trusted bağlantı / mTLS)", {
        "id": "", "app_id": "uygulama", "target_domain_id": "hedef domain",
        "client_cert_id": "uygulamanın kullandığı client sertifika", "note": "", "created_at": "",
    }, ("id", True), None, None),
    "uygulama_trust_store": (ApplicationTrustedCert, "Uygulamaların trust store'undaki sertifikalar", {
        "id": "", "app_id": "uygulama", "cert_id": "sertifika", "note": "", "created_at": "",
    }, ("id", True), None, None),
    "etiketler": (Tag, "Uygulama etiketi kataloğu", {
        "id": "", "category": "kategori", "name": "etiket", "color": "",
    }, ("category", False), None, None),
    "uygulama_etiketleri": (ApplicationTag, "Uygulama ↔ etiket", {
        "id": "", "application_id": "uygulama", "tag_id": "etiket",
    }, ("id", True), None, None),
    "ekipler": (Team, "SY ve UG ekipleri", {
        "id": "", "name": "ekip adı", "type": "SY | UG | ADMIN | VIEWER", "email": "ekibin bildirim adresi",
    }, ("name", False), None, None),
    "ekip_uyelikleri": (UserTeam, "Kim hangi ekipte", {
        "id": "", "user_id": "kullanıcı", "team_id": "ekip", "created_at": "",
    }, ("id", True), None, None),
    "kullanicilar": (User, "Jumbo kullanıcıları (kişisel bilgiler hariç)", {
        "id": "", "username": "kullanıcı adı", "full_name": "Ad Soyad",
        "role": "admin (Yönetici) | editor (Ekip Editörü) | viewer (Ekip İzleyici) | allviewer (Genel İzleyici) | none",
        "auth_source": "ldap | local", "is_active": "",
    }, ("username", False), None, None),
    "degisiklik_talepleri": (TransferProposal, "Değişiklik talepleri", {
        "id": "", "kind": "transfer (Sertifika değişimi) | server_add (Sunucuya eklenen) | server_remove (Sunucudan kalkan) | date_fix (Tarih güncelleme) | trusted_add (Trusted bağlantı)",
        "status": "pending | approved | applied | rejected | cancelled", "old_cert_id": "eski sertifika",
        "new_cert_id": "yeni sertifika", "domain_id": "domain", "app_id": "uygulama",
        "mapping_type": "server | client", "sy_team_id": "onaylayacak SY ekibi",
        "via": "nereden açıldı (import, live-check …)", "signal": "ski | subject", "live_seen": "Canlıda görüldü",
        "live_seen_at": "", "created_by": "açan", "created_at": "", "decided_by": "karar veren",
        "decided_at": "", "applied_at": "", "note": "",
    }, ("created_at", True), lambda r: f"/proposals?domain={r['domain_id']}" if r.get("domain_id") else "/proposals", None),
    "bildirimler": (Notification, "Gönderilen uyarı bildirimleri (mail ve diğer kanallar)", {
        "id": "", "certificate_id": "sertifika", "domain_id": "domain", "channel": "email | slack | teams …",
        "recipient": "alıcı(lar)", "subject": "konu", "days_left": "gönderildiğinde kalan gün", "sent_at": "",
    }, ("sent_at", True), None, None),
    "mail_gecmisi": (MailQueue, "Mail gönderim kaydı (kuyruk ve teslim edilemeyenler)", {
        "id": "", "to_addresses": "alıcılar", "subject": "konu", "stakeholder": "alıcı paydaş",
        "certificate_id": "sertifika", "domain_id": "domain", "days_left": "",
        "status": "pending | sent | failed", "attempts": "", "last_error": "son hata",
        "created_at": "", "sent_at": "",
    }, ("created_at", True), None, None),
    "kesif_hedefleri": (ScanTarget, "Keşif (ağ taraması) hedefleri", {
        "id": "", "name": "", "kind": "cidr | host | inventory", "value": "adres", "ports": "",
        "enabled": "", "sy_team_id": "ekip",
    }, ("name", False), None, None),
    "kesif_bulgulari": (DiscoveredCertificate, "Keşifte bulunan sertifikalar", {
        "id": "", "host": "", "port": "", "name": "sunulan sertifika CN", "issuer": "", "subject": "",
        "san": "", "serial_number": "", "valid_from": "", "valid_to": "",
        "status": "new (yeni bulgu) | adopted (Envantere Alındı) | ignored (Yok sayıldı)",
        "origin": "network (Ağ Taraması) | ct (CT izleme)", "fingerprint_sha256": "", "sy_team_id": "ekip",
        "first_seen_at": "", "last_seen_at": "", "note": "",
    }, ("last_seen_at", True), None, None),
    "kesif_taramalari": (ScanRun, "Keşif taramalarının çalışmaları", {
        "id": "", "kind": "network | ct", "status": "running | done | error", "trigger": "manual | schedule",
        "started_at": "", "finished_at": "", "targets_scanned": "", "hosts_reachable": "",
        "new_findings": "", "error": "", "created_by": "",
    }, ("started_at", True), None, None),
    "dagitim_akislari": (DeploymentFlow, "Dağıtım (Jenkins) akışları", {
        "id": "", "app_id": "uygulama", "name": "", "description": "", "definition": "akış tanımı (JSON)",
        "created_by": "", "updated_by": "", "created_at": "", "updated_at": "",
    }, ("updated_at", True), None, None),
    "dagitim_calistirmalari": (DeploymentRun, "Dağıtım akışı çalıştırmaları", {
        "id": "", "flow_id": "akış", "app_id": "uygulama", "flow_name_snapshot": "akış adı",
        "status": "", "triggered_by": "", "trigger_type": "", "started_at": "", "finished_at": "",
        "created_at": "",
    }, ("created_at", True), lambda r: f"/deployments/runs/{r['id']}", None),
    "dagitim_adimlari": (DeploymentRunStep, "Dağıtım çalıştırmasının adımları (Jenkins job'ları)", {
        "id": "", "run_id": "çalıştırma id", "node_label": "adım adı", "jenkins_job": "",
        "status": "", "jenkins_build_number": "", "started_at": "", "finished_at": "", "error_message": "",
    }, ("id", True), None, None),
    "islem_gecmisi": (AuditLog, "Audit Log: kim, ne zaman, neyi değiştirdi (details: eski → yeni)", {
        "id": "", "created_at": "zaman", "username": "yapan kullanıcı (system = otomatik iş)",
        "action": "create | update | delete | import | approve | propose | live_check_run …",
        "table_name": "certificates | domains | certificate_domain_map | applications | app_dependencies | "
                      "app_trusted_certs | transfer_proposals | teams | user_teams | tags | wiki_pages …",
        "record_id": "kayıt id", "details": "değişiklik detayı (JSON)",
    }, ("created_at", True), None, _audit_filter),
}

# Kimlik kolonu → okunur ad kaynağı
_REF_KIND = {
    "sy_team_id": "team", "ug_team_id": "team", "team_id": "team",
    "certificate_id": "cert", "cert_id": "cert", "client_cert_id": "cert", "old_cert_id": "cert",
    "new_cert_id": "cert", "parent_id": "cert", "superseded_by_id": "cert",
    "domain_id": "domain", "target_domain_id": "domain", "app_id": "app", "application_id": "app",
    "user_id": "user", "tag_id": "tag", "flow_id": "flow",
}
_REF_SOURCE = {
    "team": (Team.id, Team.name), "cert": (Certificate.id, Certificate.name),
    "domain": (Domain.id, Domain.domain), "app": (Application.id, Application.app_name),
    "user": (User.id, func.coalesce(User.full_name, User.username)), "tag": (Tag.id, Tag.name),
    "flow": (DeploymentFlow.id, DeploymentFlow.name),
}

OPERATORS = ("=", "!=", ">", ">=", "<", "<=", "icerir", "icermez", "baslar", "bos", "dolu", "liste")


class QueryError(Exception):
    pass


def _columns(model) -> dict:
    return {a.key: a.columns[0] for a in inspect(model).column_attrs}


def _python_type(col):
    try:
        return col.type.python_type
    except NotImplementedError:
        return str


def _is_long_text(col) -> bool:
    return _python_type(col) is str and getattr(col.type, "length", None) is None


def _coerce(name: str, col, value):
    t = _python_type(col)
    if value is None:
        return None
    try:
        if t is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "evet", "aktif", "yes")
            return bool(value)
        if t is int:
            return int(value)
        if t is datetime:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", ""))
            return dt if name in CALENDAR_DATES else ist_to_utc(dt)
    except (TypeError, ValueError):
        raise QueryError(f"'{name}' için değer anlaşılmadı: {value!r}")
    return str(value)


def _condition(name: str, col, op: str, value):
    op = (op or "=").strip().lower()
    is_text = _python_type(col) is str
    if op == "bos":
        return or_(col.is_(None), col == "") if is_text else col.is_(None)
    if op == "dolu":
        return and_(col.isnot(None), col != "") if is_text else col.isnot(None)
    if op in ("icerir", "icermez", "baslar"):
        pattern = f"%{value}%" if op != "baslar" else f"{value}%"
        cond = ci_like(col, pattern)
        return not_(cond) if op == "icermez" else cond
    if op == "liste":
        items = value if isinstance(value, list) else str(value).split(",")
        items = [i.strip() if isinstance(i, str) else i for i in items if i not in (None, "")]
        if not items:
            raise QueryError(f"'{name}' için liste boş")
        if is_text:
            return or_(*[ci_equals(col, str(i)) for i in items])
        return col.in_([_coerce(name, col, i) for i in items])
    v = _coerce(name, col, value)
    if op == "=":
        return ci_equals(col, v) if is_text else col == v
    if op == "!=":
        return not_(ci_equals(col, v)) if is_text else col != v
    if op in (">", ">=", "<", "<="):
        return {">": col > v, ">=": col >= v, "<": col < v, "<=": col <= v}[op]
    raise QueryError(f"Bilinmeyen işlem: {op}. Geçerli işlemler: {', '.join(OPERATORS)}")


def _fmt(name: str, value):
    if isinstance(value, datetime):
        if name in CALENDAR_DATES:
            return value.strftime("%Y-%m-%d")
        local = value.replace(tzinfo=timezone.utc).astimezone(ISTANBUL)
        return local.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str):
        limit = LONG_TEXT.get(name, MAX_TEXT)
        return value if len(value) <= limit else value[:limit] + "…"
    return value


def _add_names(db: Session, rows: list[dict]) -> None:
    wanted: dict[str, set] = {}
    for r in rows:
        for k, v in r.items():
            if k in _REF_KIND and isinstance(v, int):
                wanted.setdefault(_REF_KIND[k], set()).add(v)
    names: dict[str, dict] = {}
    for kind, ids in wanted.items():
        id_col, name_col = _REF_SOURCE[kind]
        names[kind] = dict(db.query(id_col, name_col).filter(id_col.in_(list(ids)[:500])).all())
    for r in rows:
        for k in [k for k in r if k in _REF_KIND and isinstance(r[k], int)]:
            r[f"{k[:-3]}_adi"] = names.get(_REF_KIND[k], {}).get(r[k])


def describe(tablo: str | None = None) -> dict:
    """veri_tablolari aracı: tablo listesi ya da bir tablonun alanları."""
    if tablo:
        spec = TABLES.get(tablo)
        if spec is None:
            return {"hata": f"Bilinmeyen tablo: {tablo}", "tablolar": list(TABLES)}
        model, desc, cols = spec[0], spec[1], spec[2]
        types = _columns(model)
        fields = {}
        for name, note in cols.items():
            t = _python_type(types[name])
            kind = {bool: "evet/hayır", int: "sayı", datetime: "tarih"}.get(t, "metin")
            fields[name] = f"{kind}" + (f" — {note}" if note else "") + (
                f" (ad: {name[:-3]}_adi)" if name in _REF_KIND else "")
        return {"tablo": tablo, "aciklama": desc, "alanlar": fields}
    return {"tablolar": {name: spec[1] for name, spec in TABLES.items()},
            "not": "Bir tablonun alanlarını görmek için tablo adıyla tekrar çağır."}


def query(db: Session, user: User, tablo: str, filtreler: list | None = None,
          alanlar: list | None = None, sirala: str | None = None, azalan: bool | None = None,
          grupla: list | None = None, adet: int | None = None) -> dict:
    spec = TABLES.get(tablo or "")
    if spec is None:
        raise QueryError(f"Bilinmeyen tablo: {tablo}. Tablolar: {', '.join(TABLES)}")
    model, _, allowed, (default_sort, default_desc), link, row_filter = spec
    cols = _columns(model)

    def column(name: str):
        if name not in allowed:
            raise QueryError(f"'{tablo}' tablosunda '{name}' alanı yok ya da gösterilmiyor. "
                             f"Alanlar: {', '.join(allowed)}")
        return cols[name]

    conditions = list(row_filter(user)) if row_filter else []
    for f in filtreler or []:
        if not isinstance(f, dict):
            raise QueryError("Her filtre {alan, islem, deger} biçiminde olmalı")
        name = str(f.get("alan") or "")
        conditions.append(_condition(name, column(name), str(f.get("islem") or "="), f.get("deger")))
    limit = max(1, min(int(adet or DEFAULT_ROWS), MAX_ROWS))

    if grupla:
        group_names = [str(g) for g in grupla][:3]
        group_cols = [column(g) for g in group_names]
        if any(_is_long_text(c) for c in group_cols):
            raise QueryError("Uzun metin alanlarına göre gruplanamaz")
        count = func.count().label("adet")
        q = db.query(*group_cols, count).filter(*conditions).group_by(*group_cols)
        groups = [dict(zip(group_names + ["adet"], [_fmt(n, v) for n, v in zip(group_names, r[:-1])] + [r[-1]]))
                  for r in q.order_by(count.desc()).limit(limit).all()]
        _add_names(db, groups)
        total = db.query(func.count()).select_from(model).filter(*conditions).scalar() or 0
        return {"tablo": tablo, "toplam_kayit": total, "grup_sayisi": len(groups), "gruplar": groups}

    names = [str(a) for a in (alanlar or [])] or list(allowed)
    if "id" in allowed and "id" not in names:
        names = ["id"] + names
    sel = [column(n) for n in names]
    sort_name = sirala or default_sort
    sort_col = column(sort_name)
    if _is_long_text(sort_col):
        raise QueryError("Uzun metin alanına göre sıralanamaz")
    desc = default_desc if azalan is None and not sirala else bool(azalan)
    order = [sort_col.desc() if desc else sort_col.asc()]
    if sort_name != "id" and "id" in allowed:
        order.append(cols["id"].desc() if desc else cols["id"].asc())
    total = db.query(func.count()).select_from(model).filter(*conditions).scalar() or 0
    rows = [{n: _fmt(n, v) for n, v in zip(names, r)}
            for r in db.query(*sel).filter(*conditions).order_by(*order).limit(limit).all()]
    _add_names(db, rows)
    if link:
        for r in rows:
            if r.get("id") is not None:
                r["link"] = link(r)
    return {"tablo": tablo, "toplam": total, "gosterilen": len(rows), "satirlar": rows}
