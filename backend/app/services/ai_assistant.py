"""AI asistanı — kurum içi AI servisine (OpenAI uyumlu /chat/completions) bağlanır.

Ayarlar > AI Asistanı alanları (api_url, api_key, model, ...) burada okunur.
  - health(): bağlantı + kimlik testi ("Bağlantıyı Test Et")
  - ask(): kullanıcının sorusunu cevaplar. AI, Jumbo verisini yalnız aşağıdaki SALT-OKUR araçlarla
    (tool calling) okur. AI hiçbir kaydı değiştiremez (yazan araç yok).
Kapsam (Ayarlar > AI Asistanı > full_access):
  - Açık (varsayılan, sahibin kararı 27.10.2026): herkes tüm uygulama verisini sorabilir. Araçlar
    soranın yerine "Genel İzleyici" gözüyle okur; kişisel bilgiler, şifreler ve ayarlar araçlarda
    hiç yoktur (bkz. ai_data.py).
  - Kapalı: araçlar mevcut API uçlarını soran kullanıcıyla çağırır; ekranda göremeyeceği bir kaydı
    AI üzerinden de göremez.
"Nasıl yapılır" soruları kurumun wiki'sindeki Kullanım Kılavuzu'ndan cevaplanır (bkz. wiki.py).
Servis tool calling desteklemiyorsa (ya da ayarlarda kapatıldıysa) araçsız sohbet yapılır; bu
durumda kılavuzun metni sistem mesajına eklenir.
"""

import json
import logging
import threading
from datetime import date, datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import page_visible
from app.core.textmatch import fold
from app.core.timeutil import ISTANBUL
from app.db.models import User
from app.services import ai_data, wiki
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8          # bir soruda AI'ın en fazla kaç kez araç çağırabileceği
MAX_LIST_ITEMS = 40          # bir aracın AI'a döndürdüğü en fazla satır
MAX_HISTORY = 20             # AI'a gönderilen en fazla önceki mesaj (soru-cevap)
MAX_QUESTION_CHARS = 4000

ROLE_NAMES = {"admin": "Yönetici", "editor": "Ekip Editörü", "viewer": "Ekip İzleyici",
              "allviewer": "Genel İzleyici"}
WIKI_DIGEST_CHARS = 20_000   # araçsız modda sistem mesajına eklenen kılavuz metni üst sınırı
GUIDE_PROMPT = ("Jumbo'nun nasıl kullanılacağı sorulursa (bir iş nerede, nasıl yapılır, bir düğme ya da durum ne "
                "demek, kim onaylar) önce kilavuz_ara ile kurumun wiki'sindeki Kullanım Kılavuzu'na bak ve "
                "cevabı oradaki bilgiye dayandır.")
NO_GUIDE_PROMPT = ("Jumbo için bir kullanım kılavuzu tanımlı değil. Bir işin Jumbo'da nasıl yapılacağı "
                   "sorulursa ekran adlarını tahmin etme; emin değilsen bilmediğini söyle.")


class AiError(Exception):
    """Kullanıcıya gösterilecek, anlaşılır hata."""


# ---------------------------------------------------------------- günlük soru sınırı (pod başına)
_usage_lock = threading.Lock()
_usage: dict[tuple[str, date], int] = {}


def _take_quota(username: str, limit: int) -> bool:
    if limit <= 0:
        return True
    today = date.today()
    with _usage_lock:
        for k in [k for k in _usage if k[1] != today]:
            del _usage[k]
        n = _usage.get((username, today), 0)
        if n >= limit:
            return False
        _usage[(username, today)] = n + 1
        return True


# ---------------------------------------------------------------- AI servisine istek
def _endpoint(cfg: dict) -> str:
    """Girilen adres tam uç olabilir (…/chat/completions, Azure'daki ?api-version dâhil) ya da
    yalnız taban (…/v1) — tabansa /chat/completions eklenir."""
    url = (cfg.get("api_url") or "").strip()
    base = url.split("?", 1)[0].rstrip("/")
    if cfg.get("url_as_is") or base.endswith("/chat/completions"):
        return url
    query = url.split("?", 1)[1] if "?" in url else ""
    return f"{base}/chat/completions" + (f"?{query}" if query else "")


def _headers(cfg: dict) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "JUMBO-CLM/ai"}
    key = cfg.get("api_key") or ""
    if key:
        if cfg.get("auth_mode") == "api-key":
            headers["api-key"] = key          # Azure OpenAI ve bazı kurum içi ağ geçitleri
        else:
            headers["Authorization"] = f"Bearer {key}"
    # Kurum ağ geçidinin istediği ek başlıklar (ör. "x-cluster: test-v2"), satır başına bir tane
    for line in str(cfg.get("extra_headers") or "").splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip() and name.strip().lower() not in ("content-type", "content-length", "host"):
            headers[name.strip()] = value.strip()
    return headers


def _post(cfg: dict, body: dict) -> dict:
    try:
        with httpx.Client(proxy=(cfg.get("proxy_url") or None),
                          timeout=float(cfg.get("timeout_seconds") or 60),
                          verify=not bool(cfg.get("skip_cert_verify"))) as client:
            r = client.post(_endpoint(cfg), headers=_headers(cfg), json=body)
    except httpx.TimeoutException:
        raise AiError("AI servisi zamanında cevap vermedi (zaman aşımı).")
    except httpx.HTTPError as exc:
        raise AiError(f"AI servisine bağlanılamadı: {exc}")
    if r.status_code in (401, 403):
        raise AiError(f"AI servisi anahtarı kabul etmedi (HTTP {r.status_code}) — API anahtarını kontrol edin.")
    if r.status_code == 404:
        raise AiError("AI servisinde bu adres bulunamadı (HTTP 404) — API adresini kontrol edin.")
    if r.status_code == 429:
        raise AiError("AI servisi şu an çok yoğun ya da kota doldu (HTTP 429). Biraz sonra tekrar deneyin.")
    if r.status_code >= 400:
        raise _HttpError(r.status_code, r.text[:500])
    try:
        return r.json()
    except ValueError:
        raise AiError("AI servisinin cevabı okunamadı (JSON değil).")


class _HttpError(AiError):
    def __init__(self, status: int, text: str):
        super().__init__(f"AI servisi hata döndürdü (HTTP {status}): {text}")
        self.status = status
        self.text = text


def is_available(cfg: dict) -> bool:
    return bool(cfg.get("enabled") and cfg.get("api_url") and cfg.get("model"))


def health(db: Session) -> tuple[bool, str]:
    cfg = get_category(db, "ai", mask_secrets=False)
    if not cfg.get("api_url") or not cfg.get("model"):
        return False, ("AI servisi tanımlı değil: API adresi ve model adı girilmeli (önce kaydedin). "
                       "Wiki bağlantısını denemek için Kullanım Kılavuzu bölümündeki \"Wiki'yi Şimdi Oku\"yu kullanın.")
    try:
        data = _post(cfg, {"model": cfg["model"], "max_tokens": 20,
                           "messages": [{"role": "user", "content": "Sadece 'tamam' yaz."}]})
    except AiError as exc:
        return False, str(exc)
    text = _message(data).get("content") or ""
    return True, f"AI servisi cevap verdi: \"{text.strip()[:60]}\""


def _message(data: dict) -> dict:
    try:
        return data["choices"][0]["message"] or {}
    except (KeyError, IndexError, TypeError):
        raise AiError("AI servisinin cevabı beklenen biçimde değil (OpenAI uyumlu değil mi?).")


# ---------------------------------------------------------------- salt-okur araçlar
def _d(v) -> str | None:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return v


def _ts(v) -> str:
    """Olay zamanı (DB'de naive UTC) → Türkiye saati."""
    if not isinstance(v, datetime):
        return ""
    return v.replace(tzinfo=timezone.utc).astimezone(ISTANBUL).strftime("%Y-%m-%d %H:%M")


def full_access(cfg: dict) -> bool:
    return bool(cfg.get("full_access", True))


def _reader(user: User, cfg: dict) -> User:
    """Araçların kimin gözüyle okuyacağı. Tam erişimde yönetici olmayan herkes Genel İzleyici
    gibi okur (her şeyi görür, kişisel veri araçlarda zaten yok). Oturuma eklenmeyen geçici nesne."""
    if full_access(cfg) and user.role not in ("admin", "allviewer"):
        return User(id=user.id, username=user.username, full_name=user.full_name,
                    role="allviewer", auth_source=user.auth_source, is_active=True)
    return user


def _call(fn, *args, **kwargs):
    """API ucunu doğrudan çağırır; yetki/bulunamadı hatası AI'a düz metin olarak döner."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        return {"hata": exc.detail}


def _cert_row(c) -> dict:
    return {"id": c.id, "ad": c.name, "tur": c.cert_type, "issuer": c.issuer,
            "valid_to": _d(c.valid_to), "kalan_gun": c.days_left, "aktif": c.is_active,
            "ortam": c.environment, "olusturan_ekip": c.creator,
            "domainler": [d.domain for d in (c.domains or [])][:10],
            "domain_sayisi": c.domain_count if c.domain_count is not None else len(c.domains or []),
            "link": f"/certificates?cert={c.id}"}


def tool_search_certificates(db: Session, user: User, metin: str | None = None,
                             kalan_gun_en_fazla: int | None = None, suresi_dolmus: bool | None = None,
                             pasifler_dahil: bool = False, tur: str | None = None) -> dict:
    from app.api.certificates import page_certificates
    page = page_certificates(page=0, size=1, all=True, q=metin or None,
                             is_active=None if pasifler_dahil else True,
                             f_name=None, f_ski=None, f_saniss=None, f_source=None,
                             f_environment=None, f_valid=None, collapsed=None, collapse_all=False,
                             expanded=None, db=db, _=user)
    certs = [r.cert for r in page.items]
    if tur:
        certs = [c for c in certs if (c.cert_type or "").lower() == tur.lower()]
    if suresi_dolmus is True:
        certs = [c for c in certs if c.days_left is not None and c.days_left < 0]
    elif suresi_dolmus is False:
        certs = [c for c in certs if c.days_left is None or c.days_left >= 0]
    if kalan_gun_en_fazla is not None:
        certs = [c for c in certs if c.days_left is not None and 0 <= c.days_left <= kalan_gun_en_fazla]
    certs.sort(key=lambda c: (c.days_left is None, c.days_left if c.days_left is not None else 0))
    return {"toplam": len(certs), "gosterilen": min(len(certs), MAX_LIST_ITEMS),
            "sertifikalar": [_cert_row(c) for c in certs[:MAX_LIST_ITEMS]]}


def tool_get_certificate(db: Session, user: User, id: int) -> dict:
    from app.api.certificates import get_certificate
    from app.api.summary import certificate_impact, certificate_mails
    c = _call(get_certificate, int(id), db=db, user=user)
    if isinstance(c, dict):
        return c
    out = _cert_row(c)
    out.update({
        "subject": c.subject, "serial_number": c.serial_number, "valid_from": _d(c.valid_from),
        "san": c.san, "ski": c.subject_key_identifier, "aki": c.authority_key_identifier,
        "ust_sertifika_id": c.parent_id, "kaynak": c.source, "notlar": c.notes,
        "anahtar": f"{c.public_key_type or ''} {c.key_size or ''} {c.key_curve or ''}".strip(),
        "imza_hash": c.signature_hash, "iptal_durumu": c.revocation_status,
        "yerine_gecen": c.superseded_by_name, "onceki_sertifikalar": [p.name for p in c.supersedes],
        "domainler": [f"{d.domain} ({d.mapping_type})" for d in c.domains],
    })
    impact = _call(certificate_impact, int(id), db=db, _=user)
    if not isinstance(impact, dict):
        out["etkilenenler"] = json.loads(impact.model_dump_json())
    mails = _call(certificate_mails, int(id), db=db, user=user)
    if isinstance(mails, list):
        out["son_mailler"] = [{"zaman": _ts(m.sent_at), "tur": m.mail_type, "alicilar": m.recipients,
                               "durum": m.status} for m in mails[:10]]
    return out


def tool_search_domains(db: Session, user: User, metin: str | None = None,
                        durum: str | None = None, ekip: str | None = None) -> dict:
    from app.api.domains import page_domains
    page = page_domains(page=0, size=1, all=True, q=metin or None, status=durum or None,
                        sy=ekip or None, sort="domain", dir="asc", f_domain=None, f_sy=None,
                        f_ug=None, f_server=None, f_client=None, f_email=None, db=db, user=user)
    rows = [{"id": d.id, "domain": d.domain, "sy_ekip": d.sy_team.name if d.sy_team else None,
             "server_kalan_gun": d.server_days_left, "client_kalan_gun": d.client_days_left,
             "canli_dogrulama": d.live_check_status, "bekleyen_talep": d.pending_proposals,
             "link": f"/domains?domain={d.id}"} for d in page.items]
    return {"toplam": page.total, "durum_sayilari": page.counts,
            "gosterilen": min(len(rows), MAX_LIST_ITEMS), "domainler": rows[:MAX_LIST_ITEMS]}


def tool_get_domain(db: Session, user: User, id: int) -> dict:
    from app.api.domains import get_domain
    d = _call(get_domain, int(id), db=db, user=user)
    if isinstance(d, dict):
        return d
    detail = d.live_check_detail
    try:
        detail = json.loads(detail) if detail else None
    except ValueError:
        pass
    return {
        "id": d.id, "domain": d.domain, "dis_adres": d.external_address,
        "sy_ekip": d.sy_team.name if d.sy_team else None,
        "ug_ekip": d.ug_team_name or (d.ug_team.name if d.ug_team else None),
        "sertifika_sahibi": d.cert_owner, "dis_firma": d.external_company, "bilgi": d.info,
        "mail_adresleri": d.mail_addresses, "bildirim_gun": d.notify_days,
        "ssl_pinning": d.ssl_pinning, "guncellenecek_sunucular": d.servers_to_update,
        "sertifikalar": [{"id": c.certificate_id, "ad": c.name, "baglanti": c.mapping_type,
                          "tur": c.cert_type, "valid_to": _d(c.valid_to), "kalan_gun": c.days_left,
                          "aktif": c.is_active} for c in d.certificates],
        "canli_dogrulama": {"durum": d.live_check_status, "zaman": _ts(d.live_check_at),
                            "detay": detail},
        "bekleyen_talep": d.pending_proposals, "link": f"/domains?domain={d.id}",
    }


def tool_list_change_requests(db: Session, user: User, durum: str = "pending",
                              metin: str | None = None) -> dict:
    if not page_visible(db, user, "proposals"):
        return {"hata": "Değişiklik Talepleri sayfası bu kullanıcıya kapalı"}
    from app.api.proposals import page_proposals
    page = page_proposals(page=0, size=MAX_LIST_ITEMS, status=durum or "pending", kind=None,
                          domain_id=None, sy_team_id=None, via=None, live_seen=None,
                          decidable=False, mine=False, q=metin or None, sort="created_at",
                          dir="desc", db=db, user=user)
    rows = [{"id": p.id, "tur": p.kind, "durum": p.status, "eski": p.old_cert_name,
             "yeni": p.new_cert_name, "domain": p.domain_name, "uygulama": p.app_name,
             "ekip": p.sy_team_name, "acan": p.created_by_name or p.created_by,
             "acilis": _ts(p.created_at), "karar_veren": p.decided_by,
             "karar_zamani": _ts(p.decided_at), "not": p.note,
             "link": f"/proposals?domain={p.domain_id}" if p.domain_id else "/proposals"}
            for p in page.items]
    return {"toplam": page.total, "durum_sayilari": page.counts, "talepler": rows}


def tool_dashboard(db: Session, user: User) -> dict:
    from app.api.dashboard import dashboard
    d = dashboard(db=db, user=user)
    return {"toplam_domain": d.total_domains, "suresi_dolmus_domain": d.expired_domains,
            "gecerli_domain": d.valid_domains, "aktif_sertifika": d.total_certificates,
            "suresi_dolmus_sertifika": d.expired_certificates,
            "ekip_domain_sayilari": [json.loads(t.model_dump_json()) for t in d.sy_domain_counts],
            "yaklasan_bitisler": [{"id": e.certificate_id, "ad": e.name, "valid_to": _d(e.valid_to),
                                   "kalan_gun": e.days_left, "ekipler": e.sy_teams,
                                   "domainler": e.domains} for e in d.expiring_certificates]}


def tool_change_history(db: Session, user: User, metin: str | None = None,
                        kullanici: str | None = None, son_gun: int = 30) -> dict:
    """Kim açabilir: run_tool'daki _available. Yönetici dışındakiler giriş kayıtlarını ve
    kullanıcı/ayar değişikliklerini görmez (kişisel bilgi); AI soruları kimseye gösterilmez."""
    from app.api.users import _audit_query, _to_audit_out
    from app.db.models import AuditLog
    days = max(1, min(int(son_gun or 30), 366))
    rows = (_audit_query(db, q=metin or None, username=kullanici or None, since_hours=days * 24)
            .filter(*ai_data._audit_filter(user))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(MAX_LIST_ITEMS).all())
    return {"son_gun": days, "kayitlar": [
        {"zaman": _ts(a.created_at), "kullanici": a.user_full_name or a.username,
         "islem": a.action, "nesne": a.table_name, "kayit": a.record_label or a.record_id,
         "ozet": a.summary} for a in _to_audit_out(db, rows)]}


def tool_policy(db: Session, user: User, metin: str | None = None, kural: str | None = None) -> dict:
    if not page_visible(db, user, "policy"):
        return {"hata": "Uyum sayfası bu kullanıcıya kapalı"}
    from app.services import policy
    result = policy.evaluate_inventory(db)
    rows = []
    for cert, violations in result["violations"]:
        if metin and fold(metin) not in fold(cert.name):
            continue
        if kural and kural not in [v["rule"] for v in violations]:
            continue
        rows.append({"id": cert.id, "ad": cert.name, "issuer": cert.issuer, "valid_to": _d(cert.valid_to),
                     "onem": policy.max_severity(violations),
                     "ihlaller": [f"{v['rule']}: {v['detail']}" for v in violations],
                     "link": f"/certificates?cert={cert.id}"})
    return {"degerlendirilen": result["total_evaluated"], "uyumlu": result["compliant"],
            "uyumsuz": len(result["violations"]), "kural_sayilari": result["rule_counts"],
            "bulunan": len(rows), "ihlaller": rows[:MAX_LIST_ITEMS]}


def _guide(db: Session) -> list:
    try:
        return wiki.pages(db)
    except wiki.WikiError as exc:
        raise HTTPException(status_code=503, detail=f"Kullanım Kılavuzu şu an okunamıyor: {exc}")


def tool_wiki_search(db: Session, user: User, metin: str | None = None) -> dict:
    guide = _guide(db)
    hits = wiki.search(guide, metin, limit=4)
    if not hits:
        return {"sonuc": "Kılavuzda bu konuda sayfa bulunamadı",
                "sayfalar": [{"baslik": p.title, "link": p.url} for p in guide[:MAX_LIST_ITEMS]]}
    # En iyi eşleşmenin metni doğrudan döner; çoğu soruda ikinci bir çağrı gerekmez.
    best = hits[0][0]
    return {"en_uygun": {"baslik": best.title, "link": best.url, "metin": best.text[:6000]},
            "diger_sayfalar": [{"baslik": p.title, "adres": p.id, "link": p.url, "ozet": ex}
                               for p, ex in hits[1:]]}


def tool_wiki_read(db: Session, user: User, adres: str) -> dict:
    page = wiki.find(_guide(db), adres)
    if page is None:
        return {"hata": "Kılavuz sayfası bulunamadı"}
    return {"baslik": page.title, "link": page.url, "metin": page.text}


def tool_tables(db: Session, user: User, tablo: str | None = None) -> dict:
    return ai_data.describe(tablo)


def tool_query(db: Session, user: User, tablo: str, filtreler: list | None = None,
               alanlar: list | None = None, sirala: str | None = None, azalan: bool | None = None,
               grupla: list | None = None, adet: int | None = None) -> dict:
    try:
        return ai_data.query(db, user, tablo, filtreler=filtreler, alanlar=alanlar, sirala=sirala,
                             azalan=azalan, grupla=grupla, adet=adet)
    except ai_data.QueryError as exc:
        db.rollback()
        return {"hata": str(exc)}


def tool_regression_runs(db: Session, user: User) -> dict:
    from app.services import regression
    return regression.ai_runs(db)


def tool_regression_run(db: Session, user: User, kosu: str | None = None) -> dict:
    from app.services import regression
    return regression.ai_run_report(db, kosu)


TOOLS = {
    "sertifika_ara": (tool_search_certificates, {
        "description": "SSL sertifikalarını arar/süzer. Bitişe kalan güne göre en yakından sıralı döner. "
                       "Varsayılan yalnız aktif sertifikalar.",
        "properties": {
            "metin": {"type": "string", "description": "Ad, Subject, Issuer, Serial Number ya da SKI içinde geçen metin"},
            "kalan_gun_en_fazla": {"type": "integer", "description": "Yalnız bitişine en fazla bu kadar gün kalanlar (süresi dolanlar hariç)"},
            "suresi_dolmus": {"type": "boolean", "description": "true: yalnız süresi dolmuşlar, false: dolmamışlar"},
            "pasifler_dahil": {"type": "boolean", "description": "Pasif sertifikalar da dahil edilsin mi"},
            "tur": {"type": "string", "enum": ["leaf", "intermediate", "root"]},
        }}),
    "sertifika_detay": (tool_get_certificate, {
        "description": "Bir sertifikanın tüm bilgileri: bağlı domainler, etkilenen uygulamalar, son uyarı mailleri.",
        "properties": {"id": {"type": "integer"}}, "required": ["id"]}),
    "domain_ara": (tool_search_domains, {
        "description": "Kullanıcının görebildiği domainleri arar. Durum: valid (geçerli), expiring (yaklaşan), "
                       "expired (süresi dolmuş), nocert (sertifikasız).",
        "properties": {
            "metin": {"type": "string", "description": "Domain adı, sertifika sahibi ya da dış firma"},
            "durum": {"type": "string", "enum": ["valid", "expiring", "expired", "nocert"]},
            "ekip": {"type": "string", "description": "SY ekip adı (tam ad)"},
        }}),
    "domain_detay": (tool_get_domain, {
        "description": "Bir domainin bilgileri, bağlı sertifikaları ve son Canlı Doğrulama sonucu (detayıyla).",
        "properties": {"id": {"type": "integer"}}, "required": ["id"]}),
    "degisiklik_talepleri": (tool_list_change_requests, {
        "description": "Değişiklik talepleri (yenileme, ekleme, kaldırma, tarih düzeltme).",
        "properties": {
            "durum": {"type": "string", "enum": ["pending", "approved", "applied", "rejected", "cancelled", "all"]},
            "metin": {"type": "string", "description": "Domain, sertifika ya da uygulama adı"},
        }}),
    "genel_durum": (tool_dashboard, {
        "description": "Anasayfa özeti: domain/sertifika sayıları, ekip bazında domain sayısı, yaklaşan bitişler.",
        "properties": {}}),
    "kayit_gecmisi": (tool_change_history, {
        "description": "Kim, ne zaman, neyi değiştirdi (Audit Log, eski → yeni).",
        "properties": {
            "metin": {"type": "string", "description": "Kayıt adı (domain, sertifika...) ya da değişiklikte geçen metin"},
            "kullanici": {"type": "string", "description": "Kullanıcı adı ya da Ad Soyad"},
            "son_gun": {"type": "integer", "description": "Son kaç gün (varsayılan 30)"},
        }}),
    "uyum_ihlalleri": (tool_policy, {
        "description": "Uyum (politika) ihlalleri: izin listesi dışı CA, zayıf anahtar, zayıf imza, aşırı ömür.",
        "properties": {
            "metin": {"type": "string", "description": "Sertifika adında geçen metin"},
            "kural": {"type": "string", "enum": ["untrusted_issuer", "weak_key", "weak_signature", "excessive_validity"]},
        }}),
    "kilavuz_ara": (tool_wiki_search, {
        "description": "Kurumun wiki'sindeki Jumbo Kullanım Kılavuzu'nda arar: bir işin nasıl/nerede "
                       "yapılacağı, ekranlar, düğmeler, roller, kurallar. En uygun sayfanın tam metnini ve "
                       "diğer eşleşmeleri döndürür.",
        "properties": {"metin": {"type": "string", "description": "Konu, ör. 'domain ekleme', 'değişiklik talebi onay'"}},
        "required": ["metin"]}),
    "kilavuz_oku": (tool_wiki_read, {
        "description": "Kullanım Kılavuzu'ndan bir sayfanın tam metni.",
        "properties": {"adres": {"type": "string", "description": "Sayfa adresi (kilavuz_ara'nın verdiği 'adres') ya da başlığı"}},
        "required": ["adres"]}),
    "veri_tablolari": (tool_tables, {
        "description": "Jumbo veritabanındaki okunabilir tablolar; tablo adı verilirse o tablonun alanları. "
                       "Diğer araçlar yetmediğinde veri_sorgula'dan önce kullan.",
        "properties": {"tablo": {"type": "string", "enum": list(ai_data.TABLES)}}}),
    "veri_sorgula": (tool_query, {
        "description": "Bir tabloyu süzerek okur ya da sayar (salt-okur). Satırlarda kimlik alanlarının "
                       "yanında okunur adı da gelir (ör. sy_team_id + sy_team_adi). grupla verilirse "
                       "gruplara göre kayıt sayısı döner. Tarih değerleri YYYY-MM-DD.",
        "properties": {
            "tablo": {"type": "string", "enum": list(ai_data.TABLES)},
            "filtreler": {"type": "array", "description": "Hepsi birlikte (VE) uygulanır", "items": {
                "type": "object", "properties": {
                    "alan": {"type": "string"},
                    "islem": {"type": "string", "enum": list(ai_data.OPERATORS),
                              "description": "icerir/baslar harf duyarsız; bos/dolu değer istemez; liste virgüllü ya da dizi"},
                    "deger": {"description": "Karşılaştırılacak değer"},
                }, "required": ["alan", "islem"]}},
            "alanlar": {"type": "array", "items": {"type": "string"}, "description": "Dönecek alanlar (boşsa hepsi)"},
            "sirala": {"type": "string", "description": "Sıralanacak alan"},
            "azalan": {"type": "boolean"},
            "grupla": {"type": "array", "items": {"type": "string"}, "description": "Sayım için gruplanacak alanlar (en fazla 3)"},
            "adet": {"type": "integer", "description": f"En fazla satır (varsayılan {ai_data.DEFAULT_ROWS}, üst sınır {ai_data.MAX_ROWS})"},
        }, "required": ["tablo"]}),
    "regresyon_testleri": (tool_regression_runs, {
        "description": "Yönetici: Regresyon Testi sayfasında başlatılan son testler ve Geçti/Kaldı/Atlandı sayıları.",
        "properties": {}}),
    "regresyon_sonucu": (tool_regression_run, {
        "description": "Yönetici: bir regresyon testinin sonucu (verilmezse en sonuncusu): bölüm bazında sayılar, "
                       "kalan senaryolar ve notları, otomatik kontrollerdeki sorunlar, bir önceki testle fark.",
        "properties": {"kosu": {"type": "string", "description": "Test numarası, ör. R20261030-201500-ab12"}}}),
}

REGRESSION_TOOLS = ("regresyon_testleri", "regresyon_sonucu")
REGRESSION_PROMPT = (
    "Kullanıcı şu an Jumbo'nun Regresyon Testi sayfasında, sürüm öncesi test yapıyor. "
    "Bir senaryonun adımı sorulursa Kullanım Kılavuzu'na da bakarak adım adım, kısa anlat; hangi ekranda "
    "hangi düğmeye basılacağını söyle. Kılavuzun 'Regresyon Testi' bölümünde Hazırlık (test paketi, test "
    "siteleri, hesaplar), madde 1–11 ve 'Hata sayılmayacak davranışlar' sayfaları vardır; B2-8.1 gibi "
    "kimlikler kılavuzdaki madde 8.1'dir. Kılavuzda 'Hata sayılmayacak' denen bir durumu hata sayma. Sonucu doğrulaman istenirse ilgili kayıtları araçlarla bul "
    "(sertifika, domain, değişiklik talebi, Audit Log, mail geçmişi) ve beklenen sonuçla madde madde "
    "karşılaştır; göremediğin şeyi (ekran görünümü, gelen mail kutusu) kullanıcının kontrol etmesini iste. "
    "'Kaldı' denen bir senaryoda kayıtlara bakıp olası nedenleri sırala, hangisinin hata hangisinin "
    "ayar/veri sorunu olabileceğini ayır. Özet istenirse regresyon_sonucu aracını kullan. "
    "Testler gerçek veriyi bozmamalı: veri değiştiren adımlarda yalnız test kayıtlarının kullanılmasını hatırlat.")


def _available(name: str, user: User, cfg: dict) -> bool:
    """Aracı bu kullanıcıya sunalım mı? Tam erişim kapalıyken ekrandaki yetki geçerlidir:
    Audit Log yalnız yönetici; tablo okuma yalnız her şeyi gören roller (ekip kapsamı uygulanamaz).
    Kılavuz araçları yalnız Ayarlar'da kurum wiki'si tanımlıysa sunulur. Regresyon araçları her
    durumda yalnız yöneticiye (Regresyon Testi sayfası gibi)."""
    if name in REGRESSION_TOOLS:
        return user.role == "admin"
    if name in ("kilavuz_ara", "kilavuz_oku"):
        return wiki.is_configured(cfg)
    if full_access(cfg):
        return True
    if name == "kayit_gecmisi":
        return user.role == "admin"
    if name in ("veri_tablolari", "veri_sorgula"):
        return user.role in ("admin", "allviewer")
    return True


def tool_specs(user: User, cfg: dict | None = None) -> list[dict]:
    cfg = cfg if cfg is not None else {}
    specs = []
    for name, (_, spec) in TOOLS.items():
        if not _available(name, user, cfg):
            continue
        params = {"type": "object", "properties": spec["properties"]}
        if spec.get("required"):
            params["required"] = spec["required"]
        specs.append({"type": "function",
                      "function": {"name": name, "description": spec["description"], "parameters": params}})
    return specs


def run_tool(db: Session, user: User, name: str, raw_args: str | dict | None,
             cfg: dict | None = None) -> str:
    cfg = cfg if cfg is not None else get_category(db, "ai", mask_secrets=True)
    entry = TOOLS.get(name)
    if entry is None:
        return json.dumps({"hata": f"Bilinmeyen araç: {name}"}, ensure_ascii=False)
    if not _available(name, user, cfg):
        msg = ("Kayıt geçmişini yalnız yöneticiler görebilir" if name == "kayit_gecmisi"
               else "Regresyon testlerini yalnız yöneticiler görebilir" if name in REGRESSION_TOOLS
               else "Bu araç bu kullanıcıya kapalı")
        return json.dumps({"hata": msg}, ensure_ascii=False)
    try:
        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
    except ValueError:
        args = {}
    allowed = set(entry[1]["properties"])
    args = {k: v for k, v in (args or {}).items() if k in allowed and v not in (None, "")}
    try:
        result = entry[0](db, _reader(user, cfg), **args)
    except HTTPException as exc:
        result = {"hata": exc.detail}
    except Exception as exc:   # araç hatası soruyu düşürmesin; AI'a söylenir
        logger.exception("AI aracı hata verdi: %s", name)
        db.rollback()
        result = {"hata": f"Araç çalışmadı: {type(exc).__name__}"}
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- sohbet
def _wiki_digest(db: Session) -> str:
    """Araçsız mod: kılavuz metni (bütçe kadar) sistem mesajına eklenir."""
    try:
        guide = wiki.pages(db)
    except wiki.WikiError as exc:
        logger.warning("Kılavuz araçsız mod için okunamadı: %s", exc)
        return ""
    parts, used = [], 0
    for p in guide:
        chunk = f"### {p.title} ({p.url})\n{p.text}\n"
        if used + len(chunk) > WIKI_DIGEST_CHARS:
            parts.append(f"### {p.title} ({p.url}) — metin sığmadı, kullanıcıyı bu sayfaya yönlendir\n")
            continue
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def system_prompt(cfg: dict, user: User, page: str | None, with_tools: bool,
                  db: Session | None = None) -> str:
    name = cfg.get("assistant_name") or "Jumbo AI"
    lines = [
        f"Sen {name}'sın: bankanın 'Jumbo Sertifika Takip' uygulamasının yardımcısısın.",
        "Kullanıcıya Türkçe, kısa ve sade cevap ver. Teknik sertifika terimlerini İngilizce yaz "
        "(Leaf, Intermediate, Root, Subject, Issuer, Serial Number, SAN, SKI/AKI, ValidFrom, ValidTo).",
        "Jumbo'da hiçbir şeyi değiştiremezsin; değişiklik gerekiyorsa kullanıcıya hangi ekrandan "
        "yapacağını söyle (SSL Sertifikaları, Domainler, Uygulamalar, Değişiklik Talepleri, Canlı Doğrulama).",
        f"Bugünün tarihi: {date.today().isoformat()}.",
        f"Soran kullanıcı: {user.full_name or user.username}, rolü: {ROLE_NAMES.get(user.role, user.role)}.",
    ]
    if with_tools:
        lines += [
            "Jumbo verisi gereken her soruda araçları kullan; sayı, tarih ya da ad UYDURMA. "
            "Araç bir şey bulamadıysa bunu açıkça söyle.",
            ("Jumbo'daki tüm uygulama verisini okuyabilirsin; kullanıcının rolü ne olursa olsun soruyu cevapla. "
             "Kişisel bilgiler (telefon, şifre, kişisel e-posta, giriş kayıtları) ve sistem ayarları araçlarda "
             "yoktur; sorulursa bunlara erişimin olmadığını söyle."
             if full_access(cfg) else
             "Araçlar yalnız bu kullanıcının görmeye yetkili olduğu kayıtları döndürür."),
            "Araç 'hata' dönerse nedenini kullanıcıya aynen söyle.",
            "Önce hazır araçları dene (sertifika_ara, domain_ara, degisiklik_talepleri …). Yetmezse "
            "veri_tablolari ile tabloları ve alanları öğren, veri_sorgula ile oku ya da say.",
            (GUIDE_PROMPT + " Cevabın sonunda kılavuz sayfasının bağlantısını aracın verdiği 'link' ile ver, "
             "ör. [Domain ekleme](https://wiki.firma.local/display/JUMBO/Domain+ekleme). Kılavuzda yoksa "
             "tahmin yürütme, bulunmadığını söyle."
             if wiki.is_configured(cfg) else NO_GUIDE_PROMPT),
            "Kayıtlardan söz ederken aracın verdiği 'link' ile Markdown bağlantısı ver, ör. "
            "[web.firma.com](/domains?domain=12).",
            "Araçlardaki saatler Türkiye saatidir.",
        ]
    else:
        lines.append("Jumbo kayıtlarına erişimin yok; kayıtlarla ilgili sorularda kullanıcıyı ilgili ekrana yönlendir.")
        digest = _wiki_digest(db) if db is not None and wiki.is_configured(cfg) else ""
        if digest:
            lines.append("Jumbo'nun nasıl kullanılacağı sorulursa yalnız aşağıdaki Kullanım Kılavuzu'na "
                         "dayan ve ilgili sayfanın bağlantısını ver; bağlantı her başlığın yanındaki adrestir.\n"
                         "--- KULLANIM KILAVUZU ---\n" + digest + "--- KILAVUZ SONU ---")
        else:
            lines.append(NO_GUIDE_PROMPT)
    if page:
        lines.append(f"Kullanıcı şu an bu ekranda: {page[:200]}")
        if page.startswith("/regression") and user.role == "admin":
            lines.append(REGRESSION_PROMPT)
    if cfg.get("extra_instructions"):
        lines.append(str(cfg["extra_instructions"])[:4000])
    return "\n".join(lines)


def _clean_history(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages[-MAX_HISTORY:]:
        role = m.get("role")
        content = str(m.get("content") or "")[:MAX_QUESTION_CHARS]
        if role in ("user", "assistant") and content.strip():
            out.append({"role": role, "content": content})
    return out


def ask(db: Session, user: User, messages: list[dict], page: str | None = None) -> dict:
    """→ {"answer": str, "tools_used": [str], "tool_mode": bool}"""
    cfg = get_category(db, "ai", mask_secrets=False)
    if not is_available(cfg):
        raise AiError("AI asistanı kapalı ya da ayarları eksik (Ayarlar > AI Asistanı).")
    history = _clean_history(messages)
    if not history or history[-1]["role"] != "user":
        raise AiError("Soru boş.")
    if not _take_quota(user.username, int(cfg.get("daily_limit") or 0)):
        raise AiError(f"Bugünkü soru sınırına ulaştınız ({cfg.get('daily_limit')}). Yarın tekrar deneyin.")

    with_tools = bool(cfg.get("use_tools", True))
    convo = [{"role": "system", "content": system_prompt(cfg, user, page, with_tools, db)}] + history
    used: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS + 1):
        body = {"model": cfg["model"], "messages": convo, "temperature": 0.2}
        if with_tools:
            body["tools"] = tool_specs(user, cfg)
        try:
            data = _post(cfg, body)
        except _HttpError as exc:
            # Servis tool calling'i desteklemiyorsa bir kez araçsız dene (genel sohbet)
            if with_tools and exc.status in (400, 422) and not used:
                logger.warning("AI servisi araçlı isteği reddetti, araçsız deneniyor: %s", exc.text[:200])
                with_tools = False
                convo[0] = {"role": "system", "content": system_prompt(cfg, user, page, False, db)}
                continue
            raise
        msg = _message(data)
        calls = msg.get("tool_calls") or []
        if not calls or not with_tools:
            return {"answer": (msg.get("content") or "").strip() or "(AI boş cevap döndürdü)",
                    "tools_used": used, "tool_mode": with_tools}
        convo.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = (call.get("function") or {})
            name = fn.get("name") or ""
            used.append(name)
            convo.append({"role": "tool", "tool_call_id": call.get("id") or name,
                          "content": run_tool(db, user, name, fn.get("arguments"), cfg)})
    return {"answer": "Bu soru için çok fazla adım gerekti; soruyu daha dar sormayı deneyin.",
            "tools_used": used, "tool_mode": with_tools}
