"""Süresi yaklaşan sertifikalar için günlük SMTP uyarı job'ı (APScheduler)."""

import html as html_mod
import logging
import smtplib
from datetime import datetime, timedelta
from app.core.timeutil import utcnow
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db.models import (AppDependency, ApplicationTrustedCert, Certificate,
                            CertificateDomainMap, Domain, MailQueue, Notification, Team,
                            TransferProposal, User)
from app.db.session import SessionLocal
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def _send_mail(cfg: dict, to_addresses: list[str], subject: str, body: str,
               html_body: str | None = None) -> None:
    """html_body verilirse multipart/alternative gönderilir: istemci HTML'i (tablolu görünüm)
    gösterir, düz metin eski biçimiyle YEDEK kalır (metin-tabanlı istemciler için)."""
    if html_body:
        msg: MIMEText | MIMEMultipart = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = ", ".join(to_addresses)
    with smtplib.SMTP(cfg["host"], int(cfg.get("port") or 25), timeout=15) as smtp:
        if cfg.get("use_tls"):
            smtp.starttls()
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg.get("password") or "")
        smtp.sendmail(cfg["from_address"], to_addresses, msg.as_string())


def _team_emails(team) -> list[str]:
    """SY ekibinin bildirim adres(ler)i — TEK KAYNAK. Team.email virgülle birden çok
    adres taşıyabilir. Domain kendi e-postasını tutmaz; sahibi ekipten türetir."""
    if team is None or not team.email:
        return []
    return [a.strip() for a in team.email.split(",") if a.strip()]


# ---------------------------------------------------------------------------
# HTML mail şablonu — eski sistemin tablolu bilgilendirme düzeni birebir örnek
# alınmıştır: selamlama + kırmızı süre banner'ı + "Domain Detay Bilgileri"
# tablosu (Bağlantı Tipi şeridiyle) + "SSL Sertifika Detayı" tablosu (+ çok
# domainli sertifikada "İlişkili Domainler" özeti). Tüm stiller INLINE çünkü
# mail istemcileri <style> bloklarını güvenilir işlemez.
# ---------------------------------------------------------------------------
_esc = html_mod.escape
_TD = "padding:6px 10px;border:1px solid #d9d9d9;vertical-align:top;font-size:14px"
_TH = _TD + ";background:#f2f2f2;font-weight:bold;width:220px"


def _fmt(value) -> str:
    """Tablo hücre değeri: boş → '-', bool → Evet/Hayır, tarih → 'YYYY-MM-DD HH:MM:SS UTC'."""
    if value is None or value == "":
        return "-"
    if value is True:
        return "Evet"
    if value is False:
        return "Hayır"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
    return str(value)


def _kv_table(rows: list[tuple]) -> str:
    trs = "".join(
        f'<tr><td style="{_TH}">{_esc(k)}</td><td style="{_TD}">{_esc(_fmt(v))}</td></tr>'
        for k, v in rows)
    return f'<table cellspacing="0" style="border-collapse:collapse;width:100%">{trs}</table>'


def _section(title: str) -> str:
    return f'<h3 style="margin:20px 0 8px;font-size:15px;color:#222">{_esc(title)}</h3>'


def _banner(text: str) -> str:
    return ('<div style="border:2px solid #c62828;background:#fdecea;color:#c62828;'
            'padding:14px;text-align:center;font-size:18px;font-weight:bold;margin:16px 0">'
            f'&#9888; {_esc(text)}</div>')


def _warn_line(text: str) -> str:
    return f'<div style="color:#c62828;font-weight:bold;margin:6px 0">&#9888; {_esc(text)}</div>'


def _mapping_label(mapping_type: str | None) -> str:
    """mapping_type ('server'/'client') → düz metin etiket. DB değeri 'client' kalır, UX'te 'Trusted' gösterilir."""
    return {"server": "Server", "client": "Trusted"}.get((mapping_type or "").lower(), mapping_type or "-")


def _type_strip(mapping_type: str) -> str:
    return ('<div style="border-left:4px solid #1565c0;background:#e8f0fe;color:#222;'
            'padding:8px 12px;margin:20px 0 8px;font-size:14px">'
            f'Bağlantı Tipi: <b>{_esc(_mapping_label(mapping_type))}</b></div>')


def _domain_rows(dom) -> list[tuple]:
    """'Domain Detay Bilgileri' tablosu — eski sistemdeki alan sırasıyla."""
    return [
        ("Domain", dom.domain),
        ("External Address", dom.external_address),
        ("UG", dom.ug_team.name if dom.ug_team else dom.ug_team_name),
        ("SY", dom.sy_team.name if dom.sy_team else None),
        ("Sertifika Sahibi", dom.cert_owner),
        ("LB Update", dom.lb_update),
        ("Env Update", dom.env_update),
        ("WAF Update", dom.waf_update),
        ("Dış Firma", dom.external_company),
        ("Bitiş Tarihi", dom.expire_date),
        ("Detay", dom.info),
        ("Aksiyon Alma", dom.action_required),
        ("SSL Pinning", dom.ssl_pinning),
        ("Keystore", dom.keystore),
    ]


def _cert_rows(cert: Certificate) -> list[tuple]:
    """'SSL Sertifika Detayı' tablosu — eski sistemdeki alan sırasıyla."""
    return [
        ("NAME", cert.name),
        ("SerialNumber", cert.serial_number),
        ("Issuer", cert.issuer),
        ("Oluşturan Ekip", cert.creator),
        ("Subject", cert.subject),
        ("SubjectKeyIdentifier", cert.subject_key_identifier),
        ("ValidFrom", cert.valid_from),
        ("ValidTo", cert.valid_to),
        ("Notes", cert.notes),
        ("Satın Alım Yapan Ekip/Kişi", cert.purchased_by),
        ("Internal", cert.is_internal),
    ]


def _related_domains_table(mappings) -> str:
    """Çok domainli sertifikada özet: Domain | Bağlantı Tipi | UG | SY | Sertifika Sahibi."""
    head = "".join(f'<td style="{_TH};width:auto">{_esc(h)}</td>'
                   for h in ("Domain", "Bağlantı Tipi", "UG", "SY", "Sertifika Sahibi"))
    body = ""
    for m in mappings:
        dom = m.domain
        cells = (dom.domain,
                 _mapping_label(m.mapping_type),
                 dom.ug_team.name if dom.ug_team else dom.ug_team_name,
                 dom.sy_team.name if dom.sy_team else None,
                 dom.cert_owner)
        body += "<tr>" + "".join(f'<td style="{_TD}">{_esc(_fmt(c))}</td>' for c in cells) + "</tr>"
    return (f'<table cellspacing="0" style="border-collapse:collapse;width:100%">'
            f"<tr>{head}</tr>{body}</table>")


# ---------------------------------------------------------------------------
# Ortak mail iskeleti — TÜM mail türleri (süre-uyarı/süresi-geçmiş/devir-hatırlatma/
# pasife-alma) aynı font/renk/genişlik/selamlama/footer'ı paylaşır. Yalnız gövde içeriği
# (tablo/liste/paragraf) senaryoya özgü kalır.
# ---------------------------------------------------------------------------
_MAIL_FONT = "Arial,Helvetica,sans-serif"
_MAIL_COLOR = "#222"
_MAIL_MAX_WIDTH = "860px"
_MAIL_FOOTER = ('<p style="color:#888;font-size:12px;margin-top:20px">İyi çalışmalar,<br>'
                "JUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir.</p>")
_MAIL_FOOTER_TEXT = "\nİyi çalışmalar,\nJUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."


def _mail_html_wrap(greeting: str, body_html: str, *, doc_links: str = "") -> str:
    """4 mail türünün ORTAK dış iskeleti: font/renk/genişlik + selamlama + [gövde] +
    [doc_links varsa] + footer. Gövde HTML'i senaryoya özgü (tablo/liste/paragraf) kalır."""
    parts = [f'<div style="font-family:{_MAIL_FONT};color:{_MAIL_COLOR};max-width:{_MAIL_MAX_WIDTH}">',
             f"<p>{_esc(greeting)}</p>", body_html]
    if doc_links:
        parts.append(_doc_links_html(doc_links))
    parts.append(_MAIL_FOOTER + "</div>")
    return "".join(parts)


def _mail_text_wrap(greeting: str, body_text: str, *, doc_links: str = "") -> str:
    """Düz-metin karşılığı — aynı iskelet mantığı (selamlama + gövde + doc_links + footer)."""
    parts = [greeting, "", body_text]
    dl = _doc_links_text(doc_links) if doc_links else ""
    if dl:
        parts.append(dl)
    parts.append(_MAIL_FOOTER_TEXT)
    return "\n".join(p for p in parts if p is not None)


def _render_cert_mail_html(cert: Certificate, days_left: int, p: dict, *, expired: bool,
                           doc_links: str = "") -> str:
    """Tek paydaşa giden tablolu HTML gövde. Düzen, bağlı domain sayısına göre eski
    sistemdeki iki mail tipini karşılar: tek domain → 'Domain Detay Bilgileri' +
    Bağlantı Tipi şeridi + 'SSL Sertifika Detayı'; çok domain → 'SSL Sertifika
    Detayı' + 'İlişkili Domainler' özeti; domain'siz → yalnız sertifika detayı."""
    mappings = [m for m in cert.domain_mappings if m.domain is not None]
    parts: list[str] = []
    if expired:
        parts.append("<p>Aşağıdaki sertifikanın süresi DOLMUŞ ancak JUMBO envanterinde hâlâ "
                     "AKTİF görünüyor. Lütfen envanteri güncelleyin.</p>")
    else:
        parts.append("<p>Aşağıdaki sertifikanın bitiş tarihi yaklaşmaktadır. Sertifika expire "
                     "date öncesinde alınması gereken aksiyonlar varsa şimdiden başlamanızı "
                     "rica ederiz.</p>")

    # Sahibi/e-postası tanımsız domain uyarıları (eski sistemdeki 'mail_addresses bulunamadı'
    # satırının karşılığı): o domain'in ekibi bu bildirimi ALAMIYOR — görünür olsun.
    for m in mappings:
        if m.domain.sy_team is None or not _team_emails(m.domain.sy_team):
            parts.append(_warn_line(f"{m.domain.domain} için sahibi SY ekibi/e-postası tanımlı "
                                    "değil — bu domain'in ekibi bilgilendirilemiyor."))

    if expired:
        parts.append(_banner(f"Bu sertifikanın süresi {-days_left} gün önce doldu — "
                             "JUMBO'da hâlâ AKTİF görünüyor!"))
    else:
        parts.append(_banner(f"Bu sertifikanın süresi {days_left} gün içinde dolmaktadır!"))

    if len(mappings) == 1:
        parts.append(_section("Domain Detay Bilgileri"))
        parts.append(_kv_table(_domain_rows(mappings[0].domain)))
        parts.append(_type_strip(mappings[0].mapping_type))

    parts.append(_section("SSL Sertifika Detayı"))
    parts.append(_kv_table(_cert_rows(cert)))

    if len(mappings) > 1:
        parts.append(_section("İlişkili Domainler"))
        parts.append(_related_domains_table(mappings))

    parts.append(_section(f"Bu bildirimi alma nedeniniz ({p['label']})"))
    parts.append("<ul style='margin:4px 0;font-size:14px'>"
                 + "".join(f"<li>{_esc(r)}</li>" for r in p["reasons"]) + "</ul>")

    if expired:
        parts.append('<p style="font-size:14px">Lütfen JUMBO envanterini güncelleyin:</p>'
                     '<ol style="font-size:14px;margin:4px 0">'
                     "<li>Yenilenen sertifikayı JUMBO'ya ekleyin (SSL Sertifikalar → Yeni Ekle).</li>"
                     "<li>'Devir Önerileri' üzerinden yeni sertifikaya geçişi onaylayın.</li>"
                     "<li>Sertifika artık kullanılmıyorsa kaydı pasife alın; yetkiniz yoksa "
                     "ilgili ekiplerle iletişime geçerek pasife alınmasını sağlayın.</li></ol>")
    else:
        parts.append('<p style="font-size:14px">Yenileme sürecini başlatmanız ve yeni sertifikayı '
                     "JUMBO'ya eklemeniz önerilir. Yerine geçecek sertifika 'Devir Önerileri' "
                     "üzerinden onayınızla devreye girer.</p>")

    return _mail_html_wrap("Merhabalar,", "".join(parts), doc_links=doc_links)


def _deactivation_body_text(cert: Certificate, actor: str, bound: list[str], team_list: list[str]) -> str:
    return (
        f"'{cert.name}' sertifikası {actor} tarafından pasife alındı.\n\n"
        f"Bu sertifika hâlâ şu domain(ler)e bağlı görünüyor:\n"
        + "".join(f"  - {d}\n" for d in bound)
        + "\nİlgili SY ekipleri: " + (", ".join(team_list) if team_list else "—") + "\n\n"
        "Domaininizin yerine geçecek sertifikayı JUMBO'da 'Devir Önerileri' üzerinden\n"
        "onaylamanız gerekir — JUMBO kendiliğinden bir değişiklik yapmaz."
    )


def _render_deactivation_html(cert: Certificate, actor: str, bound: list[str], team_list: list[str]) -> str:
    body = (
        f"<p><b>'{_esc(cert.name)}'</b> sertifikası <b>{_esc(actor)}</b> tarafından pasife alındı.</p>"
        "<p>Bu sertifika hâlâ şu domain(ler)e bağlı görünüyor:</p>"
        "<ul style='font-size:14px'>" + "".join(f"<li>{_esc(d)}</li>" for d in bound) + "</ul>"
        f"<p>İlgili SY ekipleri: {_esc(', '.join(team_list) if team_list else '—')}</p>"
        "<p>Domaininizin yerine geçecek sertifikayı JUMBO'da <b>'Devir Önerileri'</b> üzerinden "
        "onaylamanız gerekir — JUMBO kendiliğinden bir değişiklik yapmaz.</p>"
    )
    return _mail_html_wrap("Merhabalar,", body)


def notify_certificate_deactivated(db: Session, cert: Certificate, actor: str) -> dict:
    """Pasife alınan sertifikaya bağlı domain varsa, o domainlerin SAHİBİ SY ekibine
    bilgilendirme gönderir. Alıcılar TEK KAYNAKTAN gelir: domainin SY ekibinin e-postası
    (Team.email, virgülle çoklu). SMTP açıksa mail atılır (queue-farkında + fallback'li,
    diğer 3 mail türüyle aynı `_deliver` çekirdeği üzerinden — bkz. Faz 2 şablon birleştirme);
    alıcı olsun olmasın in-app Notification kaydı tutulur (iz kalsın). JUMBO devir yapmaz —
    bu yalnız bilgilendirmedir; ekip yerine geçecek sertifikayı kendi onaylar. Dedup YOKTUR
    (event-tetiklemeli, süre-uyarısı gibi tekrarlanan bir tarama değildir).

    Döner: {bound_domains, recipients, teams, mail_sent, message}
    """
    domains: set[str] = set()
    teams: set[str] = set()
    recipients: set[str] = set()
    for mapping in cert.domain_mappings:
        dom = mapping.domain
        if dom is None:
            continue
        domains.add(dom.domain)
        team = dom.sy_team
        if team is not None:
            teams.add(team.name)
            recipients.update(_team_emails(team))

    bound = sorted(domains)
    to_addr = sorted(recipients)
    team_list = sorted(teams)

    if not bound:
        return {"bound_domains": [], "recipients": [], "teams": [],
                "mail_sent": False, "message": "Sertifika pasife alındı."}

    subject = f"[JUMBO] Sertifika pasife alındı: {cert.name} — {len(bound)} domain etkilendi"
    body = _mail_text_wrap("Merhabalar,", _deactivation_body_text(cert, actor, bound, team_list))
    html_body = _render_deactivation_html(cert, actor, bound, team_list)

    mail_sent = False
    mail_queue_id = None
    cfg = get_category(db, "smtp", mask_secrets=False)
    if to_addr and cfg.get("enabled") and cfg.get("host"):
        mail_sent, _note, mail_queue_id = _deliver(db, cfg, to_addr, subject, body, html_body,
                                                    certificate_id=cert.id, stakeholder="deactivation",
                                                    days_left=None)

    db.add(Notification(certificate_id=cert.id,
                        recipient=", ".join(to_addr) if to_addr else "(tanımlı alıcı yok)",
                        subject=subject, days_left=None, mail_queue_id=mail_queue_id))
    db.commit()

    if not to_addr:
        note = "bağlı domainlerde tanımlı alıcı yok — kayıt tutuldu"
    elif mail_sent:
        note = f"{len(to_addr)} alıcı bilgilendirildi (mail gönderildi/kuyruğa alındı)"
    else:
        note = f"{len(to_addr)} alıcı belirlendi (SMTP kapalı veya gönderim başarısız — kayıt tutuldu)"
    message = f"Sertifika pasife alındı — {len(bound)} domain etkilendi; {note}."
    return {"bound_domains": bound, "recipients": to_addr, "teams": team_list,
            "mail_sent": mail_sent, "message": message}


def _expiry_stakeholders(db: Session, cert: Certificate, global_days: int = 30) -> list[dict]:
    """Süre uyarısının PAYDAŞLARINI çözer — her paydaş AYRI mail alır:
      1. Sertifikanın SAHİBİ: cert.creator "Oluşturan Ekip" (SY) ya da geriye dönük kullanıcı.
      2. Bağlı olduğu her DOMAIN'in sahibi SY ekibi (Team.email, virgülle çoklu).
      3. CLIENT olarak bağlı olduğu her UYGULAMANIN (AppDependency.client_cert) sahibi SY ekibi.
    Aynı SY ekibi birden çok kaynaktan geliyorsa TEK mail alır, nedenleri birleşir.

    Her paydaşa `effective_days` eşlenir: paydaş, sertifika bitişine bu kadar gün kala mail
    almaya başlar. DOMAIN paydaşında domainin `notify_days`'i (boşsa `global_days`); oluşturan-
    ekip / kullanıcı / uygulama paydaşında `global_days`. Aynı ekip birden çok domaine sahipse
    effective_days = MAX (en erken pencere isteyen kazanır). Geçit `_dispatch_cert_mails`'te.
    Döner: [{label, emails, reasons, effective_days}] — emails boş paydaşlar elenir."""
    stakeholders: dict[str, dict] = {}

    def add(key: str, label: str, emails: list[str], reason: str, effective_days: int) -> None:
        if not emails:
            return
        s = stakeholders.setdefault(key, {"label": label, "emails": sorted(set(emails)),
                                          "reasons": [], "effective_days": effective_days})
        if reason not in s["reasons"]:
            s["reasons"].append(reason)
        s["effective_days"] = max(s["effective_days"], effective_days)

    # 1) sahip: OLUŞTURAN EKİP (SY). creator alanı SSL Sertifikalar sayfasındaki
    #    "Oluşturan Ekip" seçiminden SY ekip ADI olarak gelir → o ekip HER ZAMAN
    #    paydaştır (domaine/uygulamaya bağlı olmasa bile mail alır). Geriye dönük:
    #    eşleşen SY ekip yoksa creator bir kullanıcı adı olarak denenir
    #    (Vault/oto-import yollarında creator=user.username'e düşebiliyor).
    #    Domaini olmayan paydaş global_days penceresini kullanır.
    if cert.creator:
        owner_team = (db.query(Team)
                      .filter(Team.name == cert.creator, Team.type == "SY").first())
        if owner_team is not None and _team_emails(owner_team):
            add(f"team:{owner_team.id}", owner_team.name, _team_emails(owner_team),
                "Sertifikayı oluşturan (sahibi) SY ekibisiniz", global_days)
        else:
            owner = db.query(User).filter(User.username == cert.creator,
                                          User.is_active == True).first()
            if owner is not None and owner.email:
                add(f"user:{owner.id}", f"sahip ({owner.username})", [owner.email],
                    "Bu sertifikayı siz oluşturdunuz (sahip)", global_days)

    # 2) bağlı domainlerin SY ekipleri — domainin kendi notify_days penceresiyle
    for m in cert.domain_mappings:
        dom = m.domain
        if dom is None or dom.sy_team is None:
            continue
        dom_days = dom.notify_days or global_days
        add(f"team:{dom.sy_team.id}", dom.sy_team.name, _team_emails(dom.sy_team),
            f"Domain sahibi: {dom.domain} ({_mapping_label(m.mapping_type)})", dom_days)

    # 3) client (trusted) olarak bağlı olduğu uygulamaların SY ekipleri
    deps = (db.query(AppDependency)
            .filter(AppDependency.client_cert_id == cert.id).all())
    for dep in deps:
        app_row = dep.app
        if app_row is None or app_row.sy_team is None:
            continue
        add(f"team:{app_row.sy_team.id}", app_row.sy_team.name, _team_emails(app_row.sy_team),
            f"Uygulama sahibi (trusted bağlantı): {app_row.app_name}", global_days)

    # 4) trust store'una eklendiği (trusted) uygulamaların SY ekipleri
    trusted = (db.query(ApplicationTrustedCert)
               .filter(ApplicationTrustedCert.cert_id == cert.id).all())
    for tr in trusted:
        app_row = tr.app
        if app_row is None or app_row.sy_team is None:
            continue
        add(f"team:{app_row.sy_team.id}", app_row.sy_team.name, _team_emails(app_row.sy_team),
            f"Uygulama trust store'unda (trusted): {app_row.app_name}", global_days)

    return list(stakeholders.values())


def _domain_expiry_stakeholder(domain: Domain, global_days: int = 30) -> dict | None:
    """Sertifikasız (server tipi aktif sertifikası olmayan, yalnız manuel Bitiş Tarihi
    girilmiş) domain için TEK paydaş: domainin kendi SY ekibi. sy_team yoksa ya da
    e-postası tanımsızsa None (çağıran atlar — _expiry_stakeholders'ın aksine burada
    birleştirilecek ikinci bir kaynak yok)."""
    if domain.sy_team is None:
        return None
    emails = _team_emails(domain.sy_team)
    if not emails:
        return None
    return {"label": domain.sy_team.name, "emails": emails,
            "reasons": [f"Domain sahibi: {domain.domain} (sertifikasız, manuel bitiş tarihi)"],
            "effective_days": domain.notify_days or global_days}


def _doc_links_html(doc_links: str) -> str:
    """Ayarlardaki doküman bağlantılarını mailin altına HTML bölümü olarak render eder."""
    lines = [ln.strip() for ln in (doc_links or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    items = "".join(
        (f'<li><a href="{_esc(ln)}">{_esc(ln)}</a></li>' if ln.startswith(("http://", "https://"))
         else f"<li>{_esc(ln)}</li>")
        for ln in lines)
    return _section("Sertifika Yönetimi Dokümanları") + f"<ul style='font-size:14px;margin:4px 0'>{items}</ul>"


def _doc_links_text(doc_links: str) -> str:
    """Doküman bağlantılarının düz metin karşılığı."""
    lines = [ln.strip() for ln in (doc_links or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\nSertifika Yönetimi Dokümanları:\n" + "".join(f"  - {ln}\n" for ln in lines)


def _send_with_fallback(cfg: dict, to_addresses: list[str], subject: str, body: str,
                        html_body: str | None) -> tuple[bool, str]:
    """Birincil alıcılara gönderir; SMTP hatası olursa `fallback_address`'e İKİNCİ deneme yapar.
    (ok, açıklama) döner. Kuyruk boşaltma da bu çekirdeği kullanır."""
    try:
        _send_mail(cfg, to_addresses, subject, body, html_body)
        return True, "gönderildi"
    except Exception as exc:
        logger.warning("Birincil mail gönderilemedi (%s): %s", ", ".join(to_addresses), exc)
        fb = [a.strip() for a in (cfg.get("fallback_address") or "").replace(";", ",").split(",") if a.strip()]
        primary_lc = {a.lower() for a in to_addresses}
        if fb and {a.lower() for a in fb} != primary_lc:
            try:
                _send_mail(cfg, fb, f"[YEDEK] {subject}",
                           f"Bu bildirim asıl alıcıya ({', '.join(to_addresses)}) gönderilemedi; "
                           f"yedek adrese iletildi.\n\n{body}", html_body)
                return True, f"birincil başarısız → yedek adrese gönderildi ({', '.join(fb)})"
            except Exception as exc2:
                logger.exception("Yedek mail de gönderilemedi")
                return False, f"birincil ve yedek başarısız: {exc2}"
        return False, f"gönderilemedi: {exc}"


def _deliver(db: Session, cfg: dict, to_addresses: list[str], subject: str, body: str,
             html_body: str | None, *, certificate_id, stakeholder, days_left,
             domain_id=None) -> tuple[bool, str, int | None]:
    """queue_enabled ise mail'i mail_queue'ya YAZAR (drain job gönderir); değilse doğrudan
    (fallback'li) gönderir. (ok, açıklama, mail_queue_id) döner — ok=True 'işlendi' (gönderildi
    veya kuyruğa alındı). mail_queue_id yalnız kuyruğa yazıldığında dolu — çağıran, yazacağı
    Notification satırını buna bağlayıp (Notification.mail_queue_id) GERÇEK teslim durumunu/
    zamanını sonradan mail_queue'dan okuyabilsin diye (bkz. api/notifications.py mail geçmişi).
    certificate_id VEYA domain_id verilir, ikisi birden değil."""
    if cfg.get("queue_enabled"):
        mq = MailQueue(to_addresses=", ".join(to_addresses), subject=subject,
                       body_text=body, body_html=html_body, certificate_id=certificate_id,
                       domain_id=domain_id, stakeholder=stakeholder, days_left=days_left)
        db.add(mq)
        db.flush()  # id'yi ata (henüz commit değil — çağıran kendi Notification'ıyla birlikte commit eder)
        return True, "kuyruğa alındı", mq.id
    ok, note = _send_with_fallback(cfg, to_addresses, subject, body, html_body)
    return ok, note, None


def _record_dispatch_error(db: Session, context: str, exc: Exception, *, certificate_id=None,
                           domain_id=None, label: str | None = None,
                           valid_to: datetime | None = None) -> None:
    """Döngü içinde SMTP DIŞI, beklenmeyen bir hata (bkz. _dispatch_cert_mails/_dispatch_domain_mails/
    send_pending_proposal_notifications'daki per-item except blokları) yalnız loglanırsa admin
    bunu Mail Gönderim Geçmişi'nde HİÇ göremez — mail hiç denenmediği için ne Notification ne
    normal mail_queue kaydı oluşur. Bu fonksiyon, elimizdeki en az bilgiyle bile olsa bir
    'failed' mail_queue satırı yazar ki geçmiş ekranında (kaynak='queue') görünsün ve detay
    panelinde tam hata mesajı okunabilsin. Bu yazma işleminin KENDİSİ başarısız olursa (ör. DB
    o an erişilemez), yalnız loglanır — çağıran döngüyü asla bloke etmez."""
    try:
        days_left = None
        if valid_to is not None:
            try:
                days_left = (valid_to - utcnow()).days
            except Exception:
                days_left = None
        db.add(MailQueue(
            to_addresses="(bilinmiyor — mail hiç denenemedi)",
            subject=f"[JUMBO] {context}{': ' + label if label else ''}",
            body_text=(f"{context}{(' — ' + label) if label else ''} sırasında beklenmeyen bir "
                       f"hata oluştu; bu mail HİÇ GÖNDERİLMEDİ (denenmedi bile):\n\n"
                       f"{type(exc).__name__}: {exc}"),
            certificate_id=certificate_id, domain_id=domain_id, stakeholder=label,
            days_left=days_left, status="failed", last_error=f"{type(exc).__name__}: {exc}"[:1000],
            attempts=1))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Hata kaydı (mail_queue) da yazılamadı: %s (%s)", context, label)


def _dispatch_cert_mails(db: Session, cfg: dict, certs: list, *, force: bool,
                         make_subject, make_body, make_html=None, global_days: int = 30) -> dict:
    """Ortak gönderim çekirdeği: her sertifika için paydaşları çözer ve HER paydaşa
    kendi nedenleriyle AYRI mail atar. force=False + resend_dedup_enabled AÇIK → o paydaşa
    (alıcıya) son `resend_interval_hours` saatte (varsayılan 3) bildirim gönderilmişse O PAYDAŞ
    atlanır (cron tekrar-önleme) — dedup PAYDAŞ BAZINDA yapılır ki bir paydaşın gönderim hatası
    diğer paydaşların (başarılı olup Notification kaydı yazılmış) retry hakkını gasp etmesin
    (bkz. test_scn_partial_failure_retries_only_failed_stakeholder). dedup KAPALIYSA her tarama
    gönderir; force=True → dedup'tan bağımsız mutlaka gönderilir (API). queue_enabled ise
    mailler doğrudan gönderilmez, mail_queue'ya yazılır. make_html verilirse multipart:
    HTML + düz metin yedek."""
    sent = skipped = 0
    details: list[dict] = []
    interval_hours = max(1, int(cfg.get("resend_interval_hours") or 3))
    dedup_enabled = cfg.get("resend_dedup_enabled", True)  # kapalıysa her tarama gönderir
    for cert in certs:
        try:
            parties = _expiry_stakeholders(db, cert, global_days)
            if not parties:
                skipped += 1
                continue

            days_left = (cert.valid_to - utcnow()).days  # geçmişse NEGATİF (gün önce doldu)
            subject = make_subject(cert, days_left)
            mails: list[dict] = []
            for p in parties:  # HER paydaşa AYRI mail — kendi nedenleriyle
                # per-domain geçit: paydaş kendi bildirim penceresine (effective_days) girmeden
                # mail almaz. Süresi-geçmiş akışında days_left negatif → geçit hep geçer.
                if days_left > p.get("effective_days", global_days):
                    continue
                recipient_str = ", ".join(p["emails"])
                if not force and dedup_enabled:
                    recent = (db.query(Notification)
                              .filter(Notification.certificate_id == cert.id,
                                      Notification.channel == "email",  # kanal bildirimleri maili engellemesin
                                      Notification.recipient == recipient_str,  # paydaş bazlı dedup
                                      Notification.sent_at >= utcnow() - timedelta(hours=interval_hours))
                              .first())
                    if recent:
                        skipped += 1
                        continue
                body = make_body(cert, days_left, p)
                html_body = make_html(cert, days_left, p) if make_html else None
                ok, note, mail_queue_id = _deliver(db, cfg, p["emails"], subject, body, html_body,
                                                   certificate_id=cert.id, stakeholder=p["label"],
                                                   days_left=days_left)
                if ok:
                    # işlendi (doğrudan gönderildi ya da kuyruğa alındı) → tekrar-önleme kaydı.
                    # mail_queue_id: kuyruğa alındıysa GERÇEK teslim durumu/zamanı oradan okunur.
                    db.add(Notification(certificate_id=cert.id, recipient=recipient_str,
                                        subject=f"{subject} → {p['label']}", days_left=days_left,
                                        channel="email", mail_queue_id=mail_queue_id))
                    db.commit()
                    sent += 1
                    mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": True, "note": note})
                else:
                    logger.warning("Bildirim işlenemedi: %s → %s (%s)", cert.name, p["label"], note)
                    # queue KAPALIYKEN doğrudan gönderim + fallback başarısız → mail geçmişinde
                    # görünsün diye mail_queue'ya 'failed' yaz. Notifications'a YAZMA (dedup açık
                    # kalsın → sonraki tarama yeniden dener). drain yalnız 'pending' işler; bu satır
                    # yeniden denenmez (zaten doğrudan denendi). queue AÇIKSA zaten _deliver kuyruğa
                    # yazmış olurdu (ok=True) → buraya düşmez; çift kayıt olmaz.
                    if not cfg.get("queue_enabled"):
                        db.add(MailQueue(to_addresses=", ".join(p["emails"]), subject=subject,
                                         body_text=body, body_html=html_body, certificate_id=cert.id,
                                         stakeholder=p["label"], days_left=days_left,
                                         status="failed", last_error=(note or "")[:1000], attempts=1))
                        db.commit()
                    mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": False, "note": note})
            details.append({"certificate": cert.name, "days_left": days_left, "mails": mails})
        except Exception as exc:
            # Beklenmeyen bir hata (ör. bozuk veri, şablon hatası) BU sertifikayı atlar ama
            # taramanın geri kalanını (diğer sertifikalar) durdurmaz — bkz. run_mail_queue_drain
            # ile aynı dayanıklılık ilkesi. SMTP gönderim hataları zaten _send_with_fallback
            # içinde ayrıca yakalanır; bu except yalnız BEKLENMEYEN programlama/veri hatalarınadır.
            # Sessizce loglamak YETMEZ — admin'in Mail Gönderim Geçmişi'nde GÖRMESİ gerekir,
            # bu yüzden en az bilgiyle bile olsa bir 'failed' mail_queue kaydı yazılır.
            db.rollback()
            cert_name = getattr(cert, "name", str(cert))
            logger.exception("Sertifika bildirimi işlenemedi (atlanıyor): %s", cert_name)
            skipped += 1
            _record_dispatch_error(db, "Sertifika bildirimi işlenemedi", exc,
                                   certificate_id=getattr(cert, "id", None), label=cert_name,
                                   valid_to=getattr(cert, "valid_to", None))
            details.append({"certificate": cert_name, "days_left": None,
                            "mails": [], "error": f"beklenmeyen hata — atlandı: {exc}"})

    return {"enabled": True, "checked": len(certs), "sent": sent, "skipped": skipped,
            "details": details,
            "message": f"{len(certs)} sertifika tarandı, {sent} mail gönderildi, {skipped} atlandı."}


def _dispatch_domain_mails(db: Session, cfg: dict, domains: list, *, force: bool,
                           make_subject, make_body, make_html=None, global_days: int = 30) -> dict:
    """_dispatch_cert_mails'in SERTİFİKASIZ DOMAIN karşılığı: her domain için TEK paydaş
    (kendi SY ekibi — bkz. _domain_expiry_stakeholder), bu yüzden çoklu-paydaş birleştirme/
    partial-failure-per-stakeholder karmaşıklığı yok. Aynı dedup/resend/queue/fallback
    çekirdeğini (_deliver/_send_with_fallback) paylaşır; Notification/MailQueue satırları
    certificate_id=NULL, domain_id=domain.id ile yazılır. Dönüş {checked, sent, skipped,
    details} — enabled/message çağıran fonksiyonda (cert sonucuyla) birleştirilir."""
    sent = skipped = 0
    details: list[dict] = []
    interval_hours = max(1, int(cfg.get("resend_interval_hours") or 3))
    dedup_enabled = cfg.get("resend_dedup_enabled", True)
    for dom in domains:
        try:
            p = _domain_expiry_stakeholder(dom, global_days)
            if p is None:
                skipped += 1
                continue

            days_left = (dom.expire_date - utcnow()).days
            if days_left > p["effective_days"]:
                skipped += 1
                continue
            subject = make_subject(dom, days_left)
            recipient_str = ", ".join(p["emails"])
            if not force and dedup_enabled:
                recent = (db.query(Notification)
                          .filter(Notification.domain_id == dom.id,
                                  Notification.channel == "email",
                                  Notification.recipient == recipient_str,
                                  Notification.sent_at >= utcnow() - timedelta(hours=interval_hours))
                          .first())
                if recent:
                    skipped += 1
                    continue
            body = make_body(dom, days_left, p)
            html_body = make_html(dom, days_left, p) if make_html else None
            ok, note, mail_queue_id = _deliver(db, cfg, p["emails"], subject, body, html_body,
                                               certificate_id=None, domain_id=dom.id,
                                               stakeholder=p["label"], days_left=days_left)
            mails: list[dict] = []
            if ok:
                db.add(Notification(domain_id=dom.id, recipient=recipient_str,
                                    subject=f"{subject} → {p['label']}", days_left=days_left,
                                    channel="email", mail_queue_id=mail_queue_id))
                db.commit()
                sent += 1
                mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": True, "note": note})
            else:
                logger.warning("Domain bildirimi işlenemedi: %s → %s (%s)", dom.domain, p["label"], note)
                if not cfg.get("queue_enabled"):
                    db.add(MailQueue(to_addresses=", ".join(p["emails"]), subject=subject,
                                     body_text=body, body_html=html_body, domain_id=dom.id,
                                     stakeholder=p["label"], days_left=days_left,
                                     status="failed", last_error=(note or "")[:1000], attempts=1))
                    db.commit()
                mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": False, "note": note})
            details.append({"domain": dom.domain, "days_left": days_left, "mails": mails})
        except Exception as exc:
            # Bkz. _dispatch_cert_mails'teki aynı korumanın gerekçesi: bu domain'i atla,
            # taramanın geri kalanını durdurma. Yine de Mail Gönderim Geçmişi'nde görünsün.
            db.rollback()
            dom_name = getattr(dom, "domain", str(dom))
            logger.exception("Domain bildirimi işlenemedi (atlanıyor): %s", dom_name)
            skipped += 1
            _record_dispatch_error(db, "Domain bildirimi işlenemedi", exc,
                                   domain_id=getattr(dom, "id", None), label=dom_name,
                                   valid_to=getattr(dom, "expire_date", None))
            details.append({"domain": dom_name, "days_left": None,
                            "mails": [], "error": f"beklenmeyen hata — atlandı: {exc}"})

    return {"checked": len(domains), "sent": sent, "skipped": skipped, "details": details}


_SMTP_OFF = {"enabled": False, "checked": 0, "sent": 0, "skipped": 0, "details": [],
             "message": "SMTP kapalı veya sunucu tanımsız — mail gönderilmedi."}


def _reason_block(p: dict) -> str:
    return ("Bu bildirimi alma nedeniniz (%s):\n" % p["label"]
            + "".join(f"  - {r}\n" for r in p["reasons"]))


def send_expiry_notifications(db: Session, *, force: bool = False) -> dict:
    """SÜRESİ YAKLAŞAN sertifikalar: bitişe `expiry_warning_days`'ten az gün kalanlar.
    Günlük 08:00 cron ve POST /api/notifications/expiry-run bu fonksiyonu kullanır."""
    cfg = get_category(db, "smtp", mask_secrets=False)
    warn_days = int(cfg.get("expiry_warning_days") or 30)
    # Bir domain kendi notify_days'iyle global default'tan ERKEN uyarı isteyebilir → aday
    # penceresini tüm domainlerin en büyük (MAX) isteğine kadar aç; asıl "kaç gün kala"
    # kararı paydaş/domain bazında _dispatch_cert_mails içindeki geçitte verilir.
    row = (db.query(Domain.notify_days).filter(Domain.notify_days.isnot(None))
           .order_by(Domain.notify_days.desc()).first())
    scan_days = max(warn_days, int(row[0]) if row and row[0] else 0)
    threshold = utcnow() + timedelta(days=scan_days)
    expiring = (
        db.query(Certificate)
        .filter(Certificate.is_active == True,
                Certificate.valid_to.isnot(None),
                Certificate.valid_to <= threshold,
                Certificate.valid_to >= utcnow())
        .all()
    )

    # E-posta DIŞI kanallar (Slack/Teams/Webhook): per-domain gün sayısı YALNIZ e-postayı
    # etkiler → bu kanallara global warn_days penceresine süzülmüş listeyi ver.
    global_threshold = utcnow() + timedelta(days=warn_days)
    from app.services.notify.dispatcher import notify_certs
    notify_certs(db, [c for c in expiring if c.valid_to <= global_threshold], kind="expiry", force=force)

    if not cfg.get("enabled") or not cfg.get("host"):
        return dict(_SMTP_OFF)

    def subject(cert, days_left):
        return f"[JUMBO] Sertifika süresi doluyor: {cert.name} ({days_left} gün kaldı)"

    def body(cert, days_left, p):
        return (
            f"Sertifika: {cert.name}\nSeri No: {cert.serial_number}\n"
            f"Bitiş: {cert.valid_to:%Y-%m-%d %H:%M} UTC\nKalan: {days_left} gün\n\n"
            + _reason_block(p)
            + "\nYenileme sürecini başlatmanız ve yeni sertifikayı JUMBO'ya eklemeniz önerilir.\n"
              "Yerine geçecek sertifika 'Devir Önerileri' üzerinden onayınızla devreye girer.\n"
            + _doc_links_text(cfg.get("doc_links") or "")
            + "\nJUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def html(cert, days_left, p):
        return _render_cert_mail_html(cert, days_left, p, expired=False,
                                      doc_links=cfg.get("doc_links") or "")

    cert_result = _dispatch_cert_mails(db, cfg, expiring, force=force,
                                       make_subject=subject, make_body=body, make_html=html,
                                       global_days=warn_days)

    # Server tipi AKTİF sertifikası OLMAYAN, yalnız manuel Bitiş Tarihi girilmiş domainler —
    # bkz. _dispatch_domain_mails. Aktif-server-sertifikalı domainler zaten yukarıdaki cert
    # akışıyla (bkz. _expiry_stakeholders bent 2) kapsanır; burada tekrar sayılmaz.
    expiring_domains = (
        db.query(Domain)
        .filter(Domain.expire_date.isnot(None),
                Domain.expire_date <= threshold,
                Domain.expire_date >= utcnow(),
                ~Domain.certificate_mappings.any(
                    (CertificateDomainMap.mapping_type == "server")
                    & CertificateDomainMap.certificate.has(Certificate.is_active == True)))
        .all()
    )

    def dom_subject(dom, days_left):
        return f"[JUMBO] Domain bitiş tarihi yaklaşıyor: {dom.domain} ({days_left} gün kaldı)"

    def dom_body(dom, days_left, p):
        return (
            f"Domain: {dom.domain}\nBitiş Tarihi (manuel): {dom.expire_date:%Y-%m-%d}\n"
            f"Kalan: {days_left} gün\n\n"
            + _reason_block(p)
            + "\nBu domain'e bağlı AKTİF bir sertifika bulunmuyor; bitiş tarihi manuel "
              "girilmiştir. Lütfen yenileme sürecini başlatın ve yeni sertifikayı JUMBO'ya "
              "ekleyip bu domain'e Server olarak bağlayın.\n"
            + _doc_links_text(cfg.get("doc_links") or "")
            + "\nJUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def dom_html(dom, days_left, p):
        body_html = (
            _banner(f"Bu domain'in bitiş tarihi {days_left} gün içinde dolmaktadır!")
            + _section("Domain Detay Bilgileri") + _kv_table(_domain_rows(dom))
            + _section(f"Bu bildirimi alma nedeniniz ({p['label']})")
            + "<ul style='margin:4px 0;font-size:14px'>"
            + "".join(f"<li>{_esc(r)}</li>" for r in p["reasons"]) + "</ul>"
            + '<p style="font-size:14px">Bu domain\'e bağlı AKTİF bir sertifika bulunmuyor; '
              "bitiş tarihi manuel girilmiştir. Lütfen yenileme sürecini başlatın ve yeni "
              "sertifikayı JUMBO'ya ekleyip bu domain'e Server olarak bağlayın.</p>"
        )
        return _mail_html_wrap("Merhabalar,", body_html, doc_links=cfg.get("doc_links") or "")

    dom_result = _dispatch_domain_mails(db, cfg, expiring_domains, force=force,
                                        make_subject=dom_subject, make_body=dom_body,
                                        make_html=dom_html, global_days=warn_days)

    return {
        "enabled": True,
        "checked": cert_result["checked"] + dom_result["checked"],
        "sent": cert_result["sent"] + dom_result["sent"],
        "skipped": cert_result["skipped"] + dom_result["skipped"],
        "details": cert_result["details"] + dom_result["details"],
        "message": (f"{cert_result['checked']} sertifika + {dom_result['checked']} domain "
                    f"tarandı, {cert_result['sent'] + dom_result['sent']} mail gönderildi, "
                    f"{cert_result['skipped'] + dom_result['skipped']} atlandı."),
    }


def send_expired_notifications(db: Session, *, force: bool = False) -> dict:
    """SÜRESİ GEÇMİŞ ama JUMBO'da HÂLÂ AKTİF (güncellenmemiş) sertifikalar: paydaşlara
    'JUMBO'da güncelleyin' hatırlatması gönderir. POST /api/notifications/expired-run
    bu fonksiyonu kullanır. Pasife alınmış kayıtlar taranmaz (zaten güncellenmiş sayılır)."""
    cfg = get_category(db, "smtp", mask_secrets=False)
    expired = (
        db.query(Certificate)
        .filter(Certificate.is_active == True,
                Certificate.valid_to.isnot(None),
                Certificate.valid_to < utcnow())
        .all()
    )

    # E-posta DIŞI kanallar — SMTP açık olmasa da bağımsız çalışır.
    from app.services.notify.dispatcher import notify_certs
    notify_certs(db, expired, kind="expired", force=force)

    if not cfg.get("enabled") or not cfg.get("host"):
        return dict(_SMTP_OFF)

    def subject(cert, days_left):
        return (f"[JUMBO] SÜRESİ GEÇMİŞ sertifika: {cert.name} "
                f"({-days_left} gün önce doldu) — JUMBO'da güncelleme gerekli")

    def body(cert, days_left, p):
        return (
            f"Sertifika: {cert.name}\nSeri No: {cert.serial_number}\n"
            f"Bitiş: {cert.valid_to:%Y-%m-%d %H:%M} UTC\n"
            f"Durum: SÜRESİ {-days_left} GÜN ÖNCE DOLDU — JUMBO'da hâlâ AKTİF görünüyor.\n\n"
            + _reason_block(p)
            + "\nLütfen JUMBO envanterini güncelleyin:\n"
              "  1) Yenilenen sertifikayı JUMBO'ya ekleyin (SSL Sertifikalar → Yeni Ekle).\n"
              "  2) 'Devir Önerileri' üzerinden yeni sertifikaya geçişi onaylayın.\n"
              "  3) Sertifika artık kullanılmıyorsa kaydı pasife alın; yetkiniz yoksa ilgili\n"
              "     ekiplerle iletişime geçerek pasife alınmasını sağlayın.\n"
            + _doc_links_text(cfg.get("doc_links") or "")
            + "\nJUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def html(cert, days_left, p):
        return _render_cert_mail_html(cert, days_left, p, expired=True,
                                      doc_links=cfg.get("doc_links") or "")

    global_days = int(cfg.get("expiry_warning_days") or 30)
    cert_result = _dispatch_cert_mails(db, cfg, expired, force=force,
                                       make_subject=subject, make_body=body, make_html=html,
                                       global_days=global_days)

    # Server tipi AKTİF sertifikası OLMAYAN, yalnız manuel Bitiş Tarihi girilmiş ve süresi
    # geçmiş domainler — bkz. _dispatch_domain_mails.
    expired_domains = (
        db.query(Domain)
        .filter(Domain.expire_date.isnot(None),
                Domain.expire_date < utcnow(),
                ~Domain.certificate_mappings.any(
                    (CertificateDomainMap.mapping_type == "server")
                    & CertificateDomainMap.certificate.has(Certificate.is_active == True)))
        .all()
    )

    def dom_subject(dom, days_left):
        return (f"[JUMBO] SÜRESİ GEÇMİŞ domain: {dom.domain} "
                f"({-days_left} gün önce doldu) — JUMBO'da güncelleme gerekli")

    def dom_body(dom, days_left, p):
        return (
            f"Domain: {dom.domain}\nBitiş Tarihi (manuel): {dom.expire_date:%Y-%m-%d}\n"
            f"Durum: SÜRESİ {-days_left} GÜN ÖNCE DOLDU.\n\n"
            + _reason_block(p)
            + "\nLütfen JUMBO envanterini güncelleyin:\n"
              "  1) Yenilenen sertifikayı JUMBO'ya import edin ve bu domain'e Server olarak "
              "bağlayın.\n"
              "  2) Bu domain'in Manuel Bitiş Tarihi'ni güncelleyin ya da boşaltın.\n"
            + _doc_links_text(cfg.get("doc_links") or "")
            + "\nJUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def dom_html(dom, days_left, p):
        body_html = (
            _banner(f"Bu domain'in bitiş tarihi {-days_left} gün önce doldu!")
            + _section("Domain Detay Bilgileri") + _kv_table(_domain_rows(dom))
            + _section(f"Bu bildirimi alma nedeniniz ({p['label']})")
            + "<ul style='margin:4px 0;font-size:14px'>"
            + "".join(f"<li>{_esc(r)}</li>" for r in p["reasons"]) + "</ul>"
            + '<p style="font-size:14px">Lütfen JUMBO envanterini güncelleyin: yenilenen '
              "sertifikayı import edip bu domain'e Server olarak bağlayın, ya da Manuel Bitiş "
              "Tarihi'ni güncelleyin/boşaltın.</p>"
        )
        return _mail_html_wrap("Merhabalar,", body_html, doc_links=cfg.get("doc_links") or "")

    dom_result = _dispatch_domain_mails(db, cfg, expired_domains, force=force,
                                        make_subject=dom_subject, make_body=dom_body,
                                        make_html=dom_html, global_days=global_days)

    return {
        "enabled": True,
        "checked": cert_result["checked"] + dom_result["checked"],
        "sent": cert_result["sent"] + dom_result["sent"],
        "skipped": cert_result["skipped"] + dom_result["skipped"],
        "details": cert_result["details"] + dom_result["details"],
        "message": (f"{cert_result['checked']} sertifika + {dom_result['checked']} domain "
                    f"tarandı, {cert_result['sent'] + dom_result['sent']} mail gönderildi, "
                    f"{cert_result['skipped'] + dom_result['skipped']} atlandı."),
    }


def _proposal_location(p: TransferProposal) -> str:
    """Bir devir önerisinin KONUM açıklaması — trust store | domain (bağlantı tipi) | mTLS
    bağımlılığı | '-'. _proposal_rows'un 'Konum' satırında kullanılır."""
    if p.kind == "trusted_add":
        return f"Trust store: {p.app.app_name}" if p.app else "Uygulama trust store"
    if p.domain is not None:
        return f"{p.domain.domain} ({_mapping_label(p.mapping_type)})"
    if p.app_dependency_id is not None:
        return "mTLS bağımlılığı"
    return "-"


def _proposal_label(p: TransferProposal) -> str:
    """Tek bir devir önerisinin insan-okur ÖZETİ (bölüm başlığı) — konum bilgisi artık
    _proposal_rows'un ayrı 'Konum' satırında, burada yalnız eski → yeni."""
    old = p.old_cert.name if p.old_cert else f"#{p.old_cert_id}"
    new = p.new_cert.name if p.new_cert else f"#{p.new_cert_id}"
    return f"{old} → {new}"


_PROPOSAL_KIND_LABELS = {"transfer": "Sertifika Devri", "trusted_add": "Trust Store Ekleme"}
_PROPOSAL_SIGNAL_LABELS = {"ski": "SubjectKeyIdentifier", "subject": "Subject"}


def _proposal_rows(p: TransferProposal) -> list[tuple]:
    """'Devir Önerisi Detayı' tablosu — _cert_rows/_domain_rows ile aynı alan:değer deseni."""
    return [
        ("Eski Sertifika", p.old_cert.name if p.old_cert else f"#{p.old_cert_id}"),
        ("Eski Sertifika Bitiş", p.old_cert.valid_to if p.old_cert else None),
        ("Yeni Sertifika", p.new_cert.name if p.new_cert else f"#{p.new_cert_id}"),
        ("Yeni Sertifika Bitiş", p.new_cert.valid_to if p.new_cert else None),
        ("Konum", _proposal_location(p)),
        ("Öneri Türü", _PROPOSAL_KIND_LABELS.get(p.kind, p.kind)),
        ("Sinyal Eşleşmesi", _PROPOSAL_SIGNAL_LABELS.get(p.signal, p.signal)),
        ("Kaynak", p.via),
        ("Oluşturulma Tarihi", p.created_at),
        ("Not", p.note),
    ]


def _proposal_reminder_greeting(team: Team | None) -> str:
    return f"Sayın {team.name} ekibi," if team else "Sayın Yetkili,"


def _proposal_reminder_text(team: Team | None, props: list, cfg: dict) -> str:
    blocks: list[str] = []
    for i, p in enumerate(props, start=1):
        blocks.append(f"\nDevir Önerisi {i}/{len(props)}: {_proposal_label(p)}\n"
                     + "".join(f"  {k}: {_fmt(v)}\n" for k, v in _proposal_rows(p)))
    body = (
        f"JUMBO'da onayınızı bekleyen {len(props)} devir önerisi var:\n"
        + "".join(blocks)
        + "\nLütfen JUMBO 'Devir Önerileri' ekranından bu önerileri gözden geçirip ONAYLAYIN veya\n"
        "REDDEDİN. Onaylanan öneriler yeni sertifikayı devreye alır; reddedilenler kapanır ve\n"
        "onay kuyruğu temizlenir."
    )
    return _mail_text_wrap(_proposal_reminder_greeting(team), body, doc_links=cfg.get("doc_links") or "")


def _render_proposal_reminder_html(team: Team | None, props: list, cfg: dict) -> str:
    parts: list[str] = [f"<p>JUMBO'da <b>onayınızı bekleyen {len(props)} devir önerisi</b> var:</p>",
                        _banner(f"{len(props)} devir önerisi onayınızı bekliyor — karar "
                               "verilene kadar hatırlatma tekrarlanır.")]
    for i, p in enumerate(props, start=1):
        parts.append(_section(f"Devir Önerisi {i}/{len(props)}: {_proposal_label(p)}"))
        parts.append(_kv_table(_proposal_rows(p)))
    parts.append(
        '<p style="font-size:14px">Lütfen JUMBO <b>\'Devir Önerileri\'</b> ekranından bu '
        "önerileri gözden geçirip <b>onaylayın</b> veya <b>reddedin</b>. Onaylananlar yeni "
        "sertifikayı devreye alır; reddedilenler kapanır ve onay kuyruğu temizlenir.</p>")
    return _mail_html_wrap(_proposal_reminder_greeting(team), "".join(parts),
                           doc_links=cfg.get("doc_links") or "")


def send_pending_proposal_notifications(db: Session, *, force: bool = False) -> dict:
    """Onay kuyruğunda BEKLEYEN (status='pending') devir önerileri için ilgili SY ekiplerine
    hatırlatma gönderir — ekip başına TEK mail, o ekibin tüm bekleyen önerilerini listeler.
    Amaç: onay kuyruğunu temizlemek. Günlük zamanlanmış job (check_pending_proposals) ve
    POST /api/notifications/proposal-run bu fonksiyonu kullanır. `force` imza uyumu içindir;
    dedup YOKTUR — hatırlatma, öneri karara bağlanana dek tekrarlanabilir olmalıdır."""
    cfg = get_category(db, "smtp", mask_secrets=False)
    if not cfg.get("enabled") or not cfg.get("host"):
        return dict(_SMTP_OFF)

    pending = (db.query(TransferProposal)
               .filter(TransferProposal.status == "pending")
               .order_by(TransferProposal.sy_team_id, TransferProposal.created_at).all())
    # Sertifikası silinmiş orphan önerileri atla (savunma; delete zaten temizler)
    pending = [p for p in pending
               if db.get(Certificate, p.old_cert_id) and db.get(Certificate, p.new_cert_id)]

    by_team: dict[int, list] = {}
    ownerless: list = []
    for p in pending:
        if p.sy_team_id is None:
            ownerless.append(p)
        else:
            by_team.setdefault(p.sy_team_id, []).append(p)

    sent = skipped = 0
    for team_id, props in by_team.items():
        try:
            team = db.get(Team, team_id)
            emails = ([a.strip() for a in (team.email or "").replace(";", ",").split(",") if a.strip()]
                      if team else [])
            if not emails:
                skipped += len(props)
                continue
            subject = f"[JUMBO] Onayınızı bekleyen {len(props)} devir önerisi"
            body_text = _proposal_reminder_text(team, props, cfg)
            body_html = _render_proposal_reminder_html(team, props, cfg)
            ok, note, _mqid = _deliver(db, cfg, emails, subject, body_text, body_html,
                                       certificate_id=None, stakeholder=(team.name if team else None),
                                       days_left=None)
            if ok:
                sent += 1
            else:
                skipped += len(props)
                logger.warning("Devir hatırlatması gönderilemedi: %s (%s)",
                               team.name if team else team_id, note)
                # queue KAPALIYKEN doğrudan gönderim başarısız → Mail Gönderim Geçmişi'nde
                # görünsün diye 'failed' yaz (bkz. _dispatch_cert_mails'teki aynı desen).
                if not cfg.get("queue_enabled"):
                    db.add(MailQueue(to_addresses=", ".join(emails), subject=subject,
                                     body_text=body_text, body_html=body_html,
                                     stakeholder=team.name if team else None,
                                     status="failed", last_error=(note or "")[:1000], attempts=1))
                    db.commit()
        except Exception as exc:
            # Bkz. _dispatch_cert_mails'teki aynı korumanın gerekçesi: bu ekibi atla,
            # diğer ekiplerin hatırlatmasını engelleme. Yine de geçmişte görünsün.
            db.rollback()
            team_label = getattr(db.get(Team, team_id), "name", None) or f"team_id={team_id}"
            logger.exception("Devir hatırlatması işlenemedi (atlanıyor): %s", team_label)
            skipped += len(props)
            _record_dispatch_error(db, "Devir hatırlatması işlenemedi", exc, label=team_label)

    # Sahipsiz (sy_team yok → yalnız admin onaylar) öneriler: fallback adrese bilgi (varsa)
    if ownerless:
        try:
            fb = [a.strip() for a in (cfg.get("fallback_address") or "").replace(";", ",").split(",")
                  if a.strip()]
            if fb:
                subject = f"[JUMBO] Sahibi atanmamış {len(ownerless)} devir önerisi (admin onayı)"
                body_text = _proposal_reminder_text(None, ownerless, cfg)
                ok, note, _mqid = _deliver(db, cfg, fb, subject, body_text, None,
                                           certificate_id=None, stakeholder="ownerless", days_left=None)
                if ok:
                    sent += 1
                else:
                    skipped += len(ownerless)
                    logger.warning("Sahipsiz devir hatırlatması gönderilemedi: %s", note)
                    if not cfg.get("queue_enabled"):
                        db.add(MailQueue(to_addresses=", ".join(fb), subject=subject, body_text=body_text,
                                         stakeholder="ownerless", status="failed",
                                         last_error=(note or "")[:1000], attempts=1))
                        db.commit()
            else:
                skipped += len(ownerless)
        except Exception as exc:
            db.rollback()
            logger.exception("Sahipsiz devir hatırlatması işlenemedi (atlanıyor)")
            skipped += len(ownerless)
            _record_dispatch_error(db, "Sahipsiz devir hatırlatması işlenemedi", exc,
                                   label="ownerless")
            skipped += len(ownerless)

    return {"enabled": True, "checked": len(pending), "sent": sent, "skipped": skipped, "details": [],
            "message": f"{len(pending)} bekleyen öneri; {sent} hatırlatma gönderildi, {skipped} atlandı."}


def check_pending_proposals() -> None:
    """Zamanlanmış devir-onayı hatırlatma job'ı. `smtp.auto_proposal_reminder_enabled` KAPALIYSA
    atlar (job zamanlıdır ama mail atmaz). Dış API tetiği (/notifications/proposal-run) bu
    bayraktan ETKİLENMEZ — send_pending_proposal_notifications'ı DOĞRUDAN çağırır."""
    db: Session = SessionLocal()
    try:
        cfg = get_category(db, "smtp", mask_secrets=False)
        if not cfg.get("auto_proposal_reminder_enabled", False):
            logger.info("Devir hatırlatması: otomatik gönderim kapalı — atlandı")
            return
        result = send_pending_proposal_notifications(db, force=False)
        if result["sent"]:
            logger.info("Devir hatırlatması: %s", result["message"])
    except Exception:
        # Öğe-bazlı hatalar send_pending_proposal_notifications içinde zaten yakalanıp
        # atlanıyor; bu yalnız döngüye girmeden ÖNCEKİ (ör. sorgu) beklenmeyen hatalar
        # için son güvenlik ağı — run_mail_queue_drain ile aynı ilke.
        logger.exception("Devir hatırlatması job'ı başarısız")
    finally:
        db.close()


def _proposal_reminder_hour() -> int:
    """Devir-onayı hatırlatmasının saatini smtp ayarından okur (0-23, varsayılan 9)."""
    db = SessionLocal()
    try:
        h = int(get_category(db, "smtp", mask_secrets=False).get("proposal_reminder_hour") or 9)
        return h if 0 <= h <= 23 else 9
    except Exception:
        return 9
    finally:
        db.close()


def check_expiring_certificates() -> None:
    """Günlük 08:00 zamanlanmış job — ortak çekirdeği tekrar-önleme AÇIK çağırır.
    `smtp.auto_expiry_enabled` KAPALIYSA otomatik tarama atlanır (job yine zamanlıdır ama
    mail atmaz). Dış API tetiği (/notifications/expiry-run) bu bayraktan ETKİLENMEZ —
    send_expiry_notifications'ı DOĞRUDAN çağırır, istendiğinde her zaman gönderir."""
    db: Session = SessionLocal()
    try:
        cfg = get_category(db, "smtp", mask_secrets=False)
        if not cfg.get("auto_expiry_enabled", True):
            logger.info("Süre uyarısı: günlük otomatik tarama kapalı (auto_expiry_enabled=false) — atlandı")
            return
        result = send_expiry_notifications(db, force=False)
        if result["sent"]:
            logger.info("Süre uyarısı: %s", result["message"])
    except Exception:
        # Bkz. check_pending_proposals'taki aynı gerekçe: öğe-bazlı hatalar zaten
        # _dispatch_cert_mails/_dispatch_domain_mails içinde yakalanıyor; bu yalnız
        # döngüye girmeden önceki beklenmeyen hatalar için son güvenlik ağı.
        logger.exception("Süre uyarısı job'ı başarısız")
    finally:
        db.close()


def _discovery_hour() -> int:
    """Keşif taramasının gece saatini ayarlardan okur (0-23, varsayılan 3)."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_category
    db = SessionLocal()
    try:
        hour = int(get_category(db, "discovery", mask_secrets=False).get("schedule_hour") or 3)
        return hour if 0 <= hour <= 23 else 3
    except Exception:
        return 3
    finally:
        db.close()


def _schedule_hour(category: str, default: int) -> int:
    """Verilen ayar kategorisinin gece saatini okur (0-23, aralık dışıysa varsayılan)."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_category
    db = SessionLocal()
    try:
        hour = int(get_category(db, category, mask_secrets=False).get("schedule_hour") or default)
        return hour if 0 <= hour <= 23 else default
    except Exception:
        return default
    finally:
        db.close()


def drain_mail_queue(db: Session) -> dict:
    """mail_queue'daki bekleyen mailleri hız-limitine (queue_batch_size) uyarak gönderir.
    'mail-queue-drain' job'ı her queue_interval_minutes'te çağırır. Fallback adres burada da
    geçerli. 5 başarısız denemeden sonra öğe 'failed' işaretlenir."""
    cfg = get_category(db, "smtp", mask_secrets=False)
    if not cfg.get("enabled") or not cfg.get("host"):
        return {"drained": 0, "sent": 0, "failed": 0, "message": "SMTP kapalı — kuyruk boşaltılmadı."}
    batch = max(1, int(cfg.get("queue_batch_size") or 50))
    pending = (db.query(MailQueue)
               .filter(MailQueue.status == "pending")
               .order_by(MailQueue.created_at.asc())
               .limit(batch).all())
    sent = failed = 0
    for item in pending:
        to = [a.strip() for a in (item.to_addresses or "").split(",") if a.strip()]
        ok, note = _send_with_fallback(cfg, to, item.subject or "", item.body_text or "", item.body_html)
        item.attempts = (item.attempts or 0) + 1
        if ok:
            item.status, item.sent_at = "sent", utcnow()
            sent += 1
        else:
            item.last_error = note[:1000]
            if item.attempts >= 5:
                item.status = "failed"
            failed += 1
        db.commit()
    return {"drained": len(pending), "sent": sent, "failed": failed,
            "message": f"{len(pending)} kuyruk öğesi işlendi ({sent} gönderildi, {failed} başarısız)."}


def run_mail_queue_drain() -> None:
    """Zamanlanmış kuyruk boşaltma job'ı (her queue_interval_minutes)."""
    db: Session = SessionLocal()
    try:
        result = drain_mail_queue(db)
        if result.get("sent"):
            logger.info("Mail kuyruğu: %s", result["message"])
    except Exception:
        logger.exception("Mail kuyruğu boşaltma hatası")
    finally:
        db.close()


def _queue_interval() -> int:
    """Kuyruk boşaltma sıklığını (dakika) ayarlardan okur (>=1, varsayılan 5)."""
    db = SessionLocal()
    try:
        m = int(get_category(db, "smtp", mask_secrets=False).get("queue_interval_minutes") or 5)
        return m if m >= 1 else 5
    except Exception:
        return 5
    finally:
        db.close()


def start_scheduler() -> None:
    from app.services.ct_monitor import run_ct_scan_job
    from app.services.deployment_engine import poll_running_runs
    from app.services.discovery import run_scan_job
    from app.services.live_check import check_all_domains
    from app.services.revocation import check_all_certificates

    if not scheduler.running:
        scheduler.add_job(check_expiring_certificates, "cron", hour=8, minute=0,
                          id="expiry-check", replace_existing=True)
        # Devir-onayı hatırlatması — iş içinde 'smtp.auto_proposal_reminder_enabled' kontrol edilir
        scheduler.add_job(check_pending_proposals, "cron", hour=_proposal_reminder_hour(), minute=0,
                          id="proposal-reminder", replace_existing=True)
        scheduler.add_job(check_all_domains, "cron", hour=7, minute=0,
                          id="live-check", replace_existing=True)
        # Ağ keşfi gece taraması — iş içinde 'discovery.enabled' kontrol edilir (kapalıysa atlar)
        scheduler.add_job(run_scan_job, "cron", hour=_discovery_hour(), minute=0,
                          id="discovery-scan", replace_existing=True)
        # CT (crt.sh) gece taraması — iş içinde 'ct.enabled' kontrol edilir (kapalıysa atlar)
        scheduler.add_job(run_ct_scan_job, "cron", hour=_schedule_hour("ct", 4), minute=0,
                          id="ct-scan", replace_existing=True)
        # İptal (OCSP/CRL) gece denetimi — iş içinde 'revocation.enabled' kontrol edilir
        scheduler.add_job(check_all_certificates, "cron", hour=_schedule_hour("revocation", 5), minute=0,
                          id="revocation-check", replace_existing=True)
        # Mail gönderim kuyruğunu periyodik boşalt (SMTP provider gönderim limitine uyum)
        scheduler.add_job(run_mail_queue_drain, "interval", minutes=_queue_interval(),
                          id="mail-queue-drain", replace_existing=True)
        # Dağıtım akışı (Jenkins DAG) orkestrasyonu — RUNNING run'ların adımlarını pollar,
        # bitenleri ilerletir. max_instances=1: bir poll uzun sürerse üst üste binmesin.
        scheduler.add_job(poll_running_runs, "interval", seconds=12,
                          id="deployment-poll", replace_existing=True, max_instances=1, coalesce=True)
        scheduler.start()
