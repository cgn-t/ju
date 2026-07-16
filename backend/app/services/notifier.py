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

from app.db.models import AppDependency, Certificate, Notification, User
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


def _type_strip(mapping_type: str) -> str:
    label = {"server": "Server", "client": "Client"}.get((mapping_type or "").lower(),
                                                         mapping_type or "-")
    return ('<div style="border-left:4px solid #1565c0;background:#e8f0fe;color:#222;'
            'padding:8px 12px;margin:20px 0 8px;font-size:14px">'
            f'Bağlantı Tipi: <b>{_esc(label)}</b></div>')


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
        ("Sertifika Oluşturan", cert.creator),
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
                 {"server": "Server", "client": "Client"}.get((m.mapping_type or "").lower(),
                                                              m.mapping_type),
                 dom.ug_team.name if dom.ug_team else dom.ug_team_name,
                 dom.sy_team.name if dom.sy_team else None,
                 dom.cert_owner)
        body += "<tr>" + "".join(f'<td style="{_TD}">{_esc(_fmt(c))}</td>' for c in cells) + "</tr>"
    return (f'<table cellspacing="0" style="border-collapse:collapse;width:100%">'
            f"<tr>{head}</tr>{body}</table>")


def _render_cert_mail_html(cert: Certificate, days_left: int, p: dict, *, expired: bool) -> str:
    """Tek paydaşa giden tablolu HTML gövde. Düzen, bağlı domain sayısına göre eski
    sistemdeki iki mail tipini karşılar: tek domain → 'Domain Detay Bilgileri' +
    Bağlantı Tipi şeridi + 'SSL Sertifika Detayı'; çok domain → 'SSL Sertifika
    Detayı' + 'İlişkili Domainler' özeti; domain'siz → yalnız sertifika detayı."""
    mappings = [m for m in cert.domain_mappings if m.domain is not None]
    parts = ['<div style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:860px">',
             "<p>Merhabalar,</p>"]
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
                     "<li>Sertifika artık kullanılmıyorsa kaydın pasife alınmasını sağlayın (admin).</li></ol>")
    else:
        parts.append('<p style="font-size:14px">Yenileme sürecini başlatmanız ve yeni sertifikayı '
                     "JUMBO'ya eklemeniz önerilir. Yerine geçecek sertifika 'Devir Önerileri' "
                     "üzerinden onayınızla devreye girer.</p>")

    parts.append('<p style="color:#888;font-size:12px;margin-top:20px">İyi çalışmalar,<br>'
                 "JUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir.</p></div>")
    return "".join(parts)


def notify_certificate_deactivated(db: Session, cert: Certificate, actor: str) -> dict:
    """Pasife alınan sertifikaya bağlı domain varsa, o domainlerin SAHİBİ SY ekibine
    bilgilendirme gönderir. Alıcılar TEK KAYNAKTAN gelir: domainin SY ekibinin e-postası
    (Team.email, virgülle çoklu). SMTP açıksa mail atılır (best-effort); alıcı olsun
    olmasın in-app Notification kaydı tutulur (iz kalsın). JUMBO devir yapmaz — bu yalnız
    bilgilendirmedir; ekip yerine geçecek sertifikayı kendi onaylar.

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
    body = (
        f"'{cert.name}' sertifikası {actor} tarafından pasife alındı.\n\n"
        f"Bu sertifika hâlâ şu domain(ler)e bağlı görünüyor:\n"
        + "".join(f"  - {d}\n" for d in bound)
        + "\nİlgili SY ekipleri: " + (", ".join(team_list) if team_list else "—") + "\n\n"
        "Domaininizin yerine geçecek sertifikayı JUMBO'da 'Devir Önerileri' üzerinden\n"
        "onaylamanız gerekir — JUMBO kendiliğinden bir değişiklik yapmaz.\n\n"
        "JUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
    )

    mail_sent = False
    cfg = get_category(db, "smtp", mask_secrets=False)
    if to_addr and cfg.get("enabled") and cfg.get("host"):
        try:
            _send_mail(cfg, to_addr, subject, body)
            mail_sent = True
        except Exception:
            logger.exception("Pasife alma bilgilendirme maili gönderilemedi: %s", cert.name)

    db.add(Notification(certificate_id=cert.id,
                        recipient=", ".join(to_addr) if to_addr else "(tanımlı alıcı yok)",
                        subject=subject, days_left=None))
    db.commit()

    if not to_addr:
        note = "bağlı domainlerde tanımlı alıcı yok — kayıt tutuldu"
    elif mail_sent:
        note = f"{len(to_addr)} alıcı bilgilendirildi (mail gönderildi)"
    else:
        note = f"{len(to_addr)} alıcı belirlendi (SMTP kapalı — kayıt tutuldu)"
    message = f"Sertifika pasife alındı — {len(bound)} domain etkilendi; {note}."
    return {"bound_domains": bound, "recipients": to_addr, "teams": team_list,
            "mail_sent": mail_sent, "message": message}


def _expiry_stakeholders(db: Session, cert: Certificate) -> list[dict]:
    """Süre uyarısının PAYDAŞLARINI çözer — her paydaş AYRI mail alır:
      1. Sertifikanın SAHİBİ: cert.creator kullanıcı adıysa o kullanıcının e-postası.
      2. Bağlı olduğu her DOMAIN'in sahibi SY ekibi (Team.email, virgülle çoklu).
      3. CLIENT olarak bağlı olduğu her UYGULAMANIN (AppDependency.client_cert) sahibi SY ekibi.
    Aynı SY ekibi hem domain hem uygulama sahibiyse TEK mail alır, nedenleri birleşir.
    Döner: [{key, label, emails, reasons}] — emails boş paydaşlar elenir."""
    stakeholders: dict[str, dict] = {}

    def add(key: str, label: str, emails: list[str], reason: str) -> None:
        if not emails:
            return
        s = stakeholders.setdefault(key, {"label": label, "emails": sorted(set(emails)), "reasons": []})
        if reason not in s["reasons"]:
            s["reasons"].append(reason)

    # 1) sahip (oluşturan kullanıcı)
    if cert.creator:
        owner = db.query(User).filter(User.username == cert.creator,
                                      User.is_active == True).first()
        if owner is not None and owner.email:
            add(f"user:{owner.id}", f"sahip ({owner.username})", [owner.email],
                "Bu sertifikayı siz oluşturdunuz (sahip)")

    # 2) bağlı domainlerin SY ekipleri
    for m in cert.domain_mappings:
        dom = m.domain
        if dom is None or dom.sy_team is None:
            continue
        add(f"team:{dom.sy_team.id}", dom.sy_team.name, _team_emails(dom.sy_team),
            f"Domain sahibi: {dom.domain} ({m.mapping_type})")

    # 3) client olarak bağlı olduğu uygulamaların SY ekipleri
    deps = (db.query(AppDependency)
            .filter(AppDependency.client_cert_id == cert.id).all())
    for dep in deps:
        app_row = dep.app
        if app_row is None or app_row.sy_team is None:
            continue
        add(f"team:{app_row.sy_team.id}", app_row.sy_team.name, _team_emails(app_row.sy_team),
            f"Uygulama sahibi (client sertifikası): {app_row.app_name}")

    return list(stakeholders.values())


def _dispatch_cert_mails(db: Session, cfg: dict, certs: list, *, force: bool,
                         make_subject, make_body, make_html=None) -> dict:
    """Ortak gönderim çekirdeği: her sertifika için paydaşları çözer ve HER paydaşa
    kendi nedenleriyle AYRI mail atar. force=False → son 7 günde bildirim gönderilen
    sertifika atlanır (cron spam önleme); force=True → mutlaka gönderilir (API).
    make_html verilirse mail multipart gider: HTML (tablolu görünüm) + düz metin yedek."""
    sent = skipped = 0
    details: list[dict] = []
    for cert in certs:
        if not force:
            recent = (db.query(Notification)
                      .filter(Notification.certificate_id == cert.id,
                              Notification.channel == "email",  # kanal bildirimleri maili engellemesin
                              Notification.sent_at >= utcnow() - timedelta(days=7))
                      .first())
            if recent:
                skipped += 1
                continue

        parties = _expiry_stakeholders(db, cert)
        if not parties:
            skipped += 1
            continue

        days_left = (cert.valid_to - utcnow()).days  # geçmişse NEGATİF (gün önce doldu)
        subject = make_subject(cert, days_left)
        mails: list[dict] = []
        for p in parties:  # HER paydaşa AYRI mail — kendi nedenleriyle
            body = make_body(cert, days_left, p)
            html_body = make_html(cert, days_left, p) if make_html else None
            try:
                _send_mail(cfg, p["emails"], subject, body, html_body)
                db.add(Notification(certificate_id=cert.id, recipient=", ".join(p["emails"]),
                                    subject=f"{subject} → {p['label']}", days_left=days_left,
                                    channel="email"))
                db.commit()
                sent += 1
                mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": True})
            except Exception:
                logger.exception("Bildirim maili gönderilemedi: %s → %s", cert.name, p["label"])
                mails.append({"to": p["emails"], "stakeholder": p["label"], "ok": False})
        details.append({"certificate": cert.name, "days_left": days_left, "mails": mails})

    return {"enabled": True, "checked": len(certs), "sent": sent, "skipped": skipped,
            "details": details,
            "message": f"{len(certs)} sertifika tarandı, {sent} mail gönderildi, {skipped} atlandı."}


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
    threshold = utcnow() + timedelta(days=warn_days)
    expiring = (
        db.query(Certificate)
        .filter(Certificate.is_active == True,
                Certificate.valid_to.isnot(None),
                Certificate.valid_to <= threshold,
                Certificate.valid_to >= utcnow())
        .all()
    )

    # E-posta DIŞI kanallar (Slack/Teams/Webhook) — SMTP açık olmasa da bağımsız çalışır.
    from app.services.notify.dispatcher import notify_certs
    notify_certs(db, expiring, kind="expiry", force=force)

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
              "Yerine geçecek sertifika 'Devir Önerileri' üzerinden onayınızla devreye girer.\n\n"
              "JUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def html(cert, days_left, p):
        return _render_cert_mail_html(cert, days_left, p, expired=False)

    return _dispatch_cert_mails(db, cfg, expiring, force=force,
                                make_subject=subject, make_body=body, make_html=html)


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
              "  3) Sertifika artık kullanılmıyorsa kaydın pasife alınmasını sağlayın (admin).\n\n"
              "JUMBO Sertifika Yönetimi tarafından otomatik gönderilmiştir."
        )

    def html(cert, days_left, p):
        return _render_cert_mail_html(cert, days_left, p, expired=True)

    return _dispatch_cert_mails(db, cfg, expired, force=force,
                                make_subject=subject, make_body=body, make_html=html)


def check_expiring_certificates() -> None:
    """Günlük 08:00 zamanlanmış job — ortak çekirdeği tekrar-önleme AÇIK çağırır."""
    db: Session = SessionLocal()
    try:
        result = send_expiry_notifications(db, force=False)
        if result["sent"]:
            logger.info("Süre uyarısı: %s", result["message"])
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


def start_scheduler() -> None:
    from app.services.ct_monitor import run_ct_scan_job
    from app.services.discovery import run_scan_job
    from app.services.live_check import check_all_domains
    from app.services.revocation import check_all_certificates

    if not scheduler.running:
        scheduler.add_job(check_expiring_certificates, "cron", hour=8, minute=0,
                          id="expiry-check", replace_existing=True)
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
        scheduler.start()
