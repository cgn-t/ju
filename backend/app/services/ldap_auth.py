"""LDAP/Active Directory kimlik doğrulama ve AD grubu → uygulama rolü eşleme."""

import base64
import logging
import re
import ssl
from datetime import datetime

from ldap3 import ALL, ALL_ATTRIBUTES, BASE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.orm import Session

from app.services.settings_service import get_category, secret_state

logger = logging.getLogger(__name__)


class LdapResult:
    def __init__(self, success: bool, role: str = "viewer", email: str = "",
                 full_name: str = "", error: str = ""):
        self.success = success
        self.role = role
        self.email = email
        self.full_name = full_name
        self.error = error


def _subst(template: str, **values: str) -> str:
    """Şablondaki {ad} VE {{ad}} yer tutucularını değiştirir. str.format() yerine replace kullanılır:
    (1) hem {username} hem resimdeki {{username}} biçimini destekler, (2) DN'lerdeki süslü parantezler
    str.format()'u KeyError ile bozardı — replace bundan etkilenmez."""
    for key, value in values.items():
        template = template.replace("{{%s}}" % key, value).replace("{%s}" % key, value)
    return template


def _tls(cfg: dict) -> Tls:
    """TLS doğrulama politikası:
      • skip_cert_verify → doğrulama YOK (kendinden imzalı/dev sertifikaları; PROD'da kullanmayın).
      • ca_cert (PEM) → yalnız o dahili CA'ya karşı doğrula.
      • aksi halde → sistem kök sertifikalarıyla doğrula."""
    if cfg.get("skip_cert_verify"):
        return Tls(validate=ssl.CERT_NONE)
    ca = (cfg.get("ca_cert") or "").strip()
    if ca:
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=ca)
    return Tls(validate=ssl.CERT_REQUIRED)


def _tls_desc(cfg: dict) -> str:
    """DEBUG logu için TLS politikasını insan-okur biçime çevirir (sır içermez)."""
    if not (bool(cfg.get("use_ssl", True)) or bool(cfg.get("start_tls", False))):
        return "yok (düz bağlantı)"
    if cfg.get("skip_cert_verify"):
        return "doğrulama ATLANIYOR (CERT_NONE, yalnız dev)"
    if (cfg.get("ca_cert") or "").strip():
        return "dahili CA (PEM) ile doğrulama"
    return "sistem kök sertifikalarıyla doğrulama"


def _server(cfg: dict) -> Server:
    use_ssl = bool(cfg.get("use_ssl", True))
    start_tls = bool(cfg.get("start_tls", False))
    # TLS politikası yalnız TLS kullanılan modlarda (LDAPS veya StartTLS) uygulanır.
    tls = _tls(cfg) if (use_ssl or start_tls) else None
    return Server(cfg["server"], port=int(cfg.get("port") or 636),
                  use_ssl=use_ssl, tls=tls, get_info=ALL)


def _connect(server: Server, cfg: dict, user: str | None, password: str | None) -> Connection:
    """Bağlantı kurar ve bind eder. LDAPS DEĞİL ama StartTLS seçiliyse, bind'den ÖNCE düz
    bağlantıyı TLS'e yükseltir. Bind reddedilirse sunucunun TAM tanı mesajını içeren
    LDAPBindError fırlatır — auto_bind'in genel 'invalidCredentials' metni nedeni gizliyordu;
    AD'nin mesajındaki data kodu asıl sebebi söyler (52e=yanlış şifre, 533=hesap devre dışı,
    775=kilitli, 532=şifre süresi dolmuş, 773=ilk girişte şifre değiştirmeli)."""
    start_tls = bool(cfg.get("start_tls", False)) and not bool(cfg.get("use_ssl", True))
    logger.debug("LDAP bind başlıyor → hedef_dn=%s | start_tls=%s | anonim=%s",
                 user or "(yok)", start_tls, not bool(user))
    conn = Connection(server, user=user or None, password=password or None)
    conn.open()
    if start_tls:
        logger.debug("LDAP StartTLS uygulanıyor (düz bağlantı TLS'e yükseltiliyor)")
        conn.start_tls()
    if not conn.bind():
        result = conn.result or {}
        logger.debug("LDAP bind REDDEDİLDİ → hedef_dn=%s | sonuç=%s", user or "(yok)", result)
        conn.unbind()
        raise LDAPBindError("bind reddedildi: %s — %s" % (
            result.get("description", "?"),
            (result.get("message") or "").strip() or "(sunucu ek mesaj vermedi)"))
    logger.debug("LDAP bind BAŞARILI → hedef_dn=%s", user or "(anonim)")
    return conn


_BIND_PASSWORD_PROBLEMS = {
    "missing": "Bind şifresi kayıtlı değil. Ayarlar > LDAP'ta Bind Şifresi'ni girip Kaydet'e basın.",
    "no_key": "Bind şifresi okunamadı: uygulamada FERNET_KEY tanımlı değil. Kurulumda eski "
              "FERNET_KEY değerini verin ya da Bind Şifresi'ni yeniden girip Kaydet'e basın.",
    "undecryptable": "Bind şifresi okunamadı: kayıtlı şifre farklı bir FERNET_KEY ile şifrelenmiş "
                     "(kurulumdaki FERNET_KEY eskisiyle aynı değil). Kurulumda eski FERNET_KEY "
                     "değerini verin ya da Bind Şifresi'ni yeniden girip Kaydet'e basın.",
}


def _bind_password_problem(db: Session, cfg: dict) -> str | None:
    """Bind DN tanımlı ama şifresi boş geldiyse nedenini söyler. Aksi halde ldap3 yalnız
    'password is mandatory in simple bind' der ve asıl sebep (kayıtsız şifre ya da değişen
    FERNET_KEY yüzünden çözülemeyen şifre) görünmez."""
    if not cfg.get("bind_dn") or cfg.get("bind_password"):
        return None
    state = secret_state(db, "ldap.bind_password")
    return _BIND_PASSWORD_PROBLEMS.get(state, _BIND_PASSWORD_PROBLEMS["missing"])


def test_connection(db: Session) -> tuple[bool, str]:
    """Settings sayfasındaki 'bağlantıyı test et' için: bind hesabıyla bağlanmayı dener."""
    cfg = get_category(db, "ldap", mask_secrets=False)
    if not cfg.get("server"):
        return False, "LDAP sunucu adresi tanımlı değil"
    logger.info("LDAP bağlantı testi: sunucu=%s:%s | bind_dn=%s",
                cfg.get("server"), cfg.get("port") or 636, cfg.get("bind_dn"))
    logger.debug("LDAP test TLS=%s", _tls_desc(cfg))
    problem = _bind_password_problem(db, cfg)
    if problem:
        logger.error("LDAP bağlantı testi yapılamadı: %s", problem)
        return False, f"Bağlantı hatası: {problem}"
    try:
        conn = _connect(_server(cfg), cfg, cfg.get("bind_dn"), cfg.get("bind_password"))
        conn.unbind()
        logger.info("LDAP bağlantı testi BAŞARILI (servis hesabı bind edildi)")
        return True, "Bağlantı başarılı"
    except LDAPException as exc:
        logger.error("LDAP bağlantı testi HATASI (sunucu=%s): %s", cfg.get("server"), exc)
        return False, f"Bağlantı hatası: {exc}"


def _entry_value(entry, attr: str) -> str:
    """LDAP girdisinden tek attribute değerini güvenle okur (yoksa/boşsa ""). Attribute erişimi ldap3'te
    büyük/küçük harf duyarsızdır; yapılandırılabilir attribute adları için sözlük erişimi kullanılır."""
    if not attr or attr not in entry:
        return ""
    val = entry[attr]
    return str(val) if val else ""


def authenticate(db: Session, username: str, password: str) -> LdapResult:
    cfg = get_category(db, "ldap", mask_secrets=False)
    if not cfg.get("enabled") or not cfg.get("server"):
        return LdapResult(False, error="LDAP etkin değil")
    # BOŞ ŞİFRE ile bind, RFC 4513 §5.1.2'de 'unauthenticated' (anonim) bind'e dönüşür ve izin veren
    # sunucularda başarı döner → kimlik doğrulama atlanır. Bind'e GİTMEDEN reddet.
    if not password:
        return LdapResult(False, error="Kullanıcı adı veya şifre hatalı")
    logger.info("LDAP giriş denemesi: kullanıcı=%s", username)
    problem = _bind_password_problem(db, cfg)
    if problem:
        logger.error("LDAP doğrulama yapılamadı (kullanıcı=%s): %s", username, problem)
        return LdapResult(False, error="Kullanıcı adı veya şifre hatalı")
    try:
        server = _server(cfg)
        user_attr = cfg.get("user_attr") or "sAMAccountName"
        email_attr = cfg.get("email_attr") or "mail"
        display_attr = cfg.get("display_attr") or "displayName"
        # DEBUG: sorgunun TÜM parametreleri (şifreler HARİÇ) — "sorgu nasıl gidiyor" bunu gösterir.
        logger.debug("LDAP hedef: sunucu=%s:%s | LDAPS(use_ssl)=%s | StartTLS=%s | TLS=%s",
                     cfg.get("server"), cfg.get("port") or 636, bool(cfg.get("use_ssl", True)),
                     bool(cfg.get("start_tls", False)), _tls_desc(cfg))

        # 1) Servis hesabıyla kullanıcının DN'ini ve niteliklerini bul
        logger.debug("LDAP 1) servis hesabıyla arama bind'i → bind_dn=%s", cfg.get("bind_dn"))
        search_conn = _connect(server, cfg, cfg.get("bind_dn"), cfg.get("bind_password"))
        # RFC 4515 §3: filtre değerindeki *()\\NUL kaçışlanmalı — kullanıcı adı enjeksiyonunu önle.
        safe_username = escape_filter_chars(username)
        # Filtre tanımlıysa onu kullan; değilse user_attr'dan türet ((sAMAccountName={username})).
        used_default_filter = not bool(cfg.get("user_filter"))
        user_filter = _subst(cfg.get("user_filter") or f"({user_attr}={{username}})",
                             username=safe_username)
        attrs = ["memberOf", email_attr, display_attr, user_attr]  # user_attr: çok-eşleşmede tam-eşleşme için
        logger.debug("LDAP 2) kullanıcı aranıyor → base=%s | filtre=%s%s | istenen_nitelikler=%s",
                     cfg.get("base_dn"), user_filter,
                     " (user_attr'dan türetildi — user_filter boş)" if used_default_filter
                     else " (user_filter kullanıldı; user_attr YOKSAYILDI)", attrs)
        search_conn.search(cfg["base_dn"], user_filter, attributes=attrs)
        logger.debug("LDAP arama sonucu: %d kayıt döndü", len(search_conn.entries))
        if not search_conn.entries:
            logger.warning("LDAP kullanıcı BULUNAMADI: kullanıcı=%s (base=%s, filtre=%s) — "
                           "Base DN veya filtre yanlış olabilir", username, cfg.get("base_dn"),
                           user_filter)
            search_conn.unbind()
            return LdapResult(False, error="Kullanıcı LDAP'ta bulunamadı")
        entries = search_conn.entries
        if len(entries) > 1:
            # Filtre BİRDEN FAZLA kayıt eşleştirdi (tipik sebep: filtre çok geniş VEYA Base DN tüm
            # forest/domain'i kapsıyor; AD MaxPageSize=1000 → sonuç 1000'de KESİLİR ve aranan hesap
            # o sayfada olmayabilir). GÜVENLİK: rastgele İLK sonuca ASLA bind etme — yanlış hesaba
            # giriş olur (bkz. prod: N6666 aranırken newadmusr bulunuyordu). ÇÖZÜM: sayfa limitini
            # BÜYÜTMEK DEĞİL (limit AD politikası, 10k da yetmeyebilirdi) — SUNUCU TARAFINDA daralt:
            # mevcut filtreyi ({user_attr}={username}) ile AND'leyip TEK kaydı iste. Hesap ilk
            # 1000'de olmasa bile bu sorgu bulur. Yine tek kayıt dönmezse BELİRSİZ kabul et, reddet.
            wide_filter = user_filter if user_filter.startswith("(") else f"({user_filter})"
            narrowed = "(&%s(%s=%s))" % (wide_filter, user_attr, safe_username)
            logger.warning("LDAP filtre %d kayıt eşleştirdi (filtre çok geniş / Base DN tüm dizini "
                           "kapsıyor olabilir) → sunucu tarafında daraltılıyor: %s",
                           len(entries), narrowed)
            search_conn.search(cfg["base_dn"], narrowed, attributes=attrs)
            entries = search_conn.entries
            logger.debug("LDAP daraltılmış arama sonucu: %d kayıt", len(entries))
            if len(entries) != 1:
                sample = [str(e.entry_dn) for e in entries[:5]]
                logger.warning("LDAP daraltılmış arama TEK kayıt dönmedi (dönen=%d, %s=%s) → GİRİŞ "
                               "REDDEDİLDİ (belirsiz). 'Kullanıcı attribute' gerçek login attribute'u "
                               "olmalı (AD'de sAMAccountName) ve/veya filtreyi ((%s={username}) gibi) "
                               "ve Base DN'i daraltın. DN'ler: %s",
                               len(entries), user_attr, username, user_attr, sample)
                search_conn.unbind()
                return LdapResult(False, error="LDAP filtresi kullanıcıyı tekil eşleştiremedi — "
                                  "yönetici arama filtresini veya Base DN'i daraltmalı")
            logger.warning("LDAP daraltılmış aramayla tek hesaba indirgendi — kalıcı çözüm için "
                           "filtreyi/Base DN'i daraltın.")
        entry = entries[0]
        # entry_dn: kaydın GERÇEK DN'i (ldap3 her sunucuda doldurur). distinguishedName
        # ATTRIBUTE'u YALNIZ AD'de var — OpenLDAP'ta boş döner ve bind invalidDNSyntax verirdi.
        user_dn = str(entry.entry_dn)
        email = _entry_value(entry, email_attr)
        full_name = _entry_value(entry, display_attr)
        groups = [str(g) for g in (entry.memberOf.values if "memberOf" in entry else [])]
        logger.info("LDAP kullanıcı bulundu: kullanıcı=%s → dn=%s", username, user_dn)
        logger.debug("LDAP nitelikler → %s=%s | %s=%s | memberOf(%d grup)=%s",
                     email_attr, email or "(boş)", display_attr, full_name or "(boş)",
                     len(groups), groups)

        # memberOf boşsa VE ayrı grup araması yapılandırılmışsa: grup tabanında kullanıcıyı üye
        # gösteren grupları ara (bazı dizinler memberOf'u kullanıcı girdisinde doldurmaz).
        if not groups and cfg.get("group_base") and cfg.get("group_filter"):
            group_filter = _subst(cfg["group_filter"],
                                  user_dn=escape_filter_chars(user_dn), username=safe_username)
            logger.debug("LDAP 3) grup araması (memberOf boş) → base=%s | filtre=%s",
                         cfg.get("group_base"), group_filter)
            search_conn.search(cfg["group_base"], group_filter, attributes=["cn"])
            # entry_dn kullan: distinguishedName attribute'u yalnız AD'de var (bkz. yukarısı)
            groups = [str(g.entry_dn) for g in search_conn.entries]
            logger.debug("LDAP grup araması sonucu: %d grup → %s", len(groups), groups)
        search_conn.unbind()

        # 2) Kullanıcının kendi şifresiyle bind ederek doğrula. Reddi AYRI logla: hangi
        # kullanıcı/DN ve sunucunun TAM mesajı (AD data kodu) — teşhis için kritik.
        logger.debug("LDAP 4) kullanıcının KENDİ şifresiyle doğrulama bind'i → dn=%s", user_dn)
        try:
            user_conn = _connect(server, cfg, user_dn, password)
            user_conn.unbind()
        except LDAPBindError as exc:
            logger.warning("LDAP KULLANICI bind reddi (kullanıcı=%s, dn=%s): %s",
                           username, user_dn, exc)
            return LdapResult(False, error="Kullanıcı adı veya şifre hatalı")

        # 3) Grup → rol eşleme (en yüksek yetkili eşleşme kazanır)
        role_map: dict = cfg.get("group_role_map") or {}
        levels = {"viewer": 0, "editor": 1, "admin": 2}
        role = cfg.get("default_role", "viewer")
        for group_dn, mapped_role in role_map.items():
            if any(group_dn.lower() == g.lower() for g in groups):
                if levels.get(mapped_role, 0) > levels.get(role, 0):
                    role = mapped_role
        logger.info("LDAP giriş BAŞARILI: kullanıcı=%s | dn=%s | eşlenen_rol=%s",
                    username, user_dn, role)
        return LdapResult(True, role=role, email=email, full_name=full_name)
    except LDAPException as exc:
        # Bağlantı/TLS/servis-bind hatası gibi GERÇEK hatalar (yanlış şifre değil — o yukarıda
        # WARNING). ERROR seviyesinde: LOG_LEVEL=ERROR'da bile görünür.
        logger.error("LDAP doğrulama HATASI (kullanıcı=%s, sunucu=%s): %s",
                     username, cfg.get("server"), exc)
        return LdapResult(False, error="Kullanıcı adı veya şifre hatalı")


# ── Profil sayfası: kullanıcının dizindeki TÜM bilgileri ─────────────────────────────────────
# Girişten bağımsızdır: sayfa açıldığında servis hesabıyla canlı okunur, DB'ye yazılmaz.

# Hiçbir koşulda gösterilmeyen nitelikler (şifre/şifre geçmişi/LAPS). Ad içinde "password" geçenler de.
_HIDDEN_ATTRS = {"unicodepwd", "dbcspwd", "lmpwdhistory", "ntpwdhistory", "supplementalcredentials",
                 "ms-mcs-admpwd", "ms-mcs-admpwdexpirationtime", "msds-managedpassword"}
_PHOTO_ATTRS = {"thumbnailphoto", "jpegphoto"}

# Özet kutuları: (anahtar, ekranda başlık, aranacak nitelikler — ilk dolu olan kullanılır)
_SUMMARY_FIELDS = [
    ("full_name", "Ad Soyad", ["displayName", "cn"]),
    ("title", "Unvan", ["title"]),
    ("department", "Departman", ["department", "departmentNumber"]),
    ("division", "Bölüm", ["division"]),
    ("company", "Şirket", ["company", "o"]),
    ("office", "Ofis", ["physicalDeliveryOfficeName", "roomNumber"]),
    ("location", "Şehir", ["l"]),
    ("employee_id", "Sicil No", ["employeeID", "employeeNumber"]),
    ("employee_type", "Çalışan Tipi", ["employeeType"]),
    ("mail", "E-posta", ["mail"]),
    ("upn", "UPN", ["userPrincipalName"]),
    ("account", "Hesap Adı", ["sAMAccountName", "uid"]),
    ("phone", "Telefon", ["telephoneNumber"]),
    ("mobile", "Cep Telefonu", ["mobile"]),
    ("description", "Açıklama", ["description"]),
    ("created", "Hesap Açılış", ["whenCreated", "createTimestamp"]),
    ("last_logon", "Son Oturum (AD)", ["lastLogonTimestamp"]),
    ("pwd_last_set", "Şifre Değişimi", ["pwdLastSet"]),
    ("account_expires", "Hesap Bitişi", ["accountExpires"]),
]
_MAX_MANAGER_DEPTH = 8


def _hidden(attr: str) -> bool:
    low = attr.lower()
    return low in _HIDDEN_ATTRS or "password" in low


def _fmt_value(value) -> str:
    """Tek nitelik değerini ekranda okunur metne çevirir. Tarihler ISO; ikili veri boyutuyla."""
    if isinstance(value, datetime):
        # AD 'hiçbir zaman' değerleri (0 → 1601, 0x7FFF.. → 9999) gerçek tarih değildir
        if value.year <= 1601 or value.year >= 9999:
            return "Hiçbir zaman"
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8")
            if text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        return f"(ikili veri, {len(value)} bayt)"
    return str(value)


def _rdn_value(dn: str) -> str:
    """'CN=Ali Veli,OU=IT,...' → 'Ali Veli'. Kaçışlı virgüller (\\,) korunur."""
    first = re.split(r"(?<!\\),", dn, maxsplit=1)[0]
    return first.split("=", 1)[1].replace("\\,", ",") if "=" in first else dn


def _ou_path(dn: str) -> list[str]:
    """DN'deki OU'lar en üstten alta: 'CN=x,OU=Ekip,OU=Müdürlük,DC=..' → ['Müdürlük', 'Ekip']."""
    parts = re.split(r"(?<!\\),", dn)
    return [p.split("=", 1)[1].replace("\\,", ",") for p in reversed(parts)
            if p.strip().lower().startswith("ou=")]


def _attr_values(entry, name: str) -> list:
    if name not in entry:
        return []
    vals = entry[name].values
    return [v for v in vals if v not in (None, "", b"")]


def _first(entry, names: list[str]) -> str:
    for name in names:
        vals = _attr_values(entry, name)
        if vals:
            return _fmt_value(vals[0])
    return ""


def _find_one(conn: Connection, cfg: dict, username: str, attrs) -> object | None:
    """authenticate() ile AYNI arama: filtre + birden çok sonuçta user_attr ile daraltma.
    Tek kayıt bulunamazsa None (rastgele ilk sonuç ASLA kullanılmaz)."""
    safe = escape_filter_chars(username)
    user_attr = cfg.get("user_attr") or "sAMAccountName"
    user_filter = _subst(cfg.get("user_filter") or f"({user_attr}={{username}})", username=safe)
    conn.search(cfg["base_dn"], user_filter, attributes=attrs)
    entries = conn.entries
    if len(entries) > 1:
        wide = user_filter if user_filter.startswith("(") else f"({user_filter})"
        conn.search(cfg["base_dn"], "(&%s(%s=%s))" % (wide, user_attr, safe), attributes=attrs)
        entries = conn.entries
    return entries[0] if len(entries) == 1 else None


def _person(conn: Connection, dn: str) -> dict:
    """Yönetici gibi bir DN'in kısa kartı. Okunamazsa yalnız DN'den türetilen ad döner."""
    card = {"dn": dn, "name": _rdn_value(dn), "title": "", "department": "", "mail": "", "manager_dn": ""}
    try:
        conn.search(dn, "(objectClass=*)", search_scope=BASE,
                    attributes=["displayName", "cn", "title", "department", "departmentNumber",
                                "mail", "manager"])
    except LDAPException as exc:
        logger.debug("LDAP kişi kartı okunamadı (dn=%s): %s", dn, exc)
        return card
    if conn.entries:
        e = conn.entries[0]
        card.update(name=_first(e, ["displayName", "cn"]) or card["name"], title=_first(e, ["title"]),
                    department=_first(e, ["department", "departmentNumber"]), mail=_first(e, ["mail"]),
                    manager_dn=_first(e, ["manager"]))
    return card


def _uac_flags(value: str) -> list[str]:
    try:
        uac = int(value)
    except (TypeError, ValueError):
        return []
    flags = []
    if uac & 0x2:
        flags.append("Hesap devre dışı")
    if uac & 0x10:
        flags.append("Hesap kilitli")
    if uac & 0x10000:
        flags.append("Şifre süresi dolmaz")
    if uac & 0x800000:
        flags.append("Şifrenin süresi dolmuş")
    return flags or ["Etkin"]


def directory_profile(db: Session, username: str) -> dict:
    """Kullanıcının dizin kaydını okur: özet alanlar, yönetici zinciri, gruplar, tüm nitelikler.
    Dönüş: {"status": ok|disabled|not_found|error, "message": str, ...}. Hata fırlatmaz."""
    cfg = get_category(db, "ldap", mask_secrets=False)
    if not cfg.get("enabled") or not cfg.get("server"):
        return {"status": "disabled", "message": "LDAP Ayarlar'da etkin değil."}
    problem = _bind_password_problem(db, cfg)
    if problem:
        return {"status": "error", "message": problem}
    try:
        conn = _connect(_server(cfg), cfg, cfg.get("bind_dn"), cfg.get("bind_password"))
    except LDAPException as exc:
        logger.error("LDAP profil okuma: bağlantı hatası (kullanıcı=%s): %s", username, exc)
        return {"status": "error", "message": f"LDAP sunucusuna bağlanılamadı: {exc}"}
    try:
        entry = _find_one(conn, cfg, username, [ALL_ATTRIBUTES])
        if entry is None:
            return {"status": "not_found",
                    "message": "Kullanıcı LDAP'ta bulunamadı (ya da filtre birden çok kayıt eşleştirdi)."}
        dn = str(entry.entry_dn)

        attributes, photo = [], None
        for name in sorted(entry.entry_attributes, key=str.lower):
            if _hidden(name):
                continue
            vals = _attr_values(entry, name)
            if not vals:
                continue
            if name.lower() in _PHOTO_ATTRS and isinstance(vals[0], (bytes, bytearray)):
                photo = photo or "data:image/jpeg;base64," + base64.b64encode(vals[0]).decode()
            attributes.append({"name": name, "values": [_fmt_value(v) for v in vals]})

        summary = []
        for key, label, names in _SUMMARY_FIELDS:
            value = _first(entry, names)
            if value:
                summary.append({"key": key, "label": label, "value": value})
        uac = _first(entry, ["userAccountControl"])
        account_flags = _uac_flags(uac) if uac else []

        groups = [str(g) for g in _attr_values(entry, "memberOf")]
        group_source = "memberOf"
        if not groups and cfg.get("group_base") and cfg.get("group_filter"):
            group_filter = _subst(cfg["group_filter"], user_dn=escape_filter_chars(dn),
                                  username=escape_filter_chars(username))
            conn.search(cfg["group_base"], group_filter, attributes=["cn"])
            groups = [str(g.entry_dn) for g in conn.entries]
            group_source = "group_search"
        role_map = {k.lower(): v for k, v in (cfg.get("group_role_map") or {}).items()}
        group_out = sorted(({"dn": g, "name": _rdn_value(g), "mapped_role": role_map.get(g.lower())}
                            for g in groups), key=lambda g: g["name"].lower())

        # Yönetici zinciri: manager → onun manager'ı ... (döngü ve derinlik korumalı)
        chain, seen = [], {dn.lower()}
        next_dn = _first(entry, ["manager"])
        while next_dn and next_dn.lower() not in seen and len(chain) < _MAX_MANAGER_DEPTH:
            seen.add(next_dn.lower())
            card = _person(conn, next_dn)
            chain.append(card)
            next_dn = card.pop("manager_dn")
        for card in chain:
            card.pop("manager_dn", None)

        reports = sorted((_rdn_value(str(r)) for r in _attr_values(entry, "directReports")), key=str.lower)
        return {"status": "ok", "message": "", "dn": dn, "ou_path": _ou_path(dn), "photo": photo,
                "summary": summary, "account_flags": account_flags, "managers": chain,
                "direct_reports": reports, "groups": group_out, "group_source": group_source,
                "attributes": attributes}
    except LDAPException as exc:
        logger.error("LDAP profil okuma hatası (kullanıcı=%s): %s", username, exc)
        return {"status": "error", "message": f"LDAP okuma hatası: {exc}"}
    finally:
        conn.unbind()
