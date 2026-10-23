"""Yönetici Panosu / Ekibim / Sistem Sağlığı / sertifika 'Etkilenenler' hesapları.

Hepsi MEVCUT tablolardan okuma anında hesaplanır — yeni tablo/kolon YOK. Ekip ↔ sertifika
ilişkisi mail paydaşlarıyla aynı mantıktır: sertifika, bağlı olduğu domainlerin SY ekibine VE
"Oluşturan Ekip" (creator, SY ekip ADI) alanındaki ekibe aittir.

Kapsam (RBAC) çağıranda security.domain_scope_team_ids ile verilir: None = GLOBAL (admin,
Genel İzleyici), aksi halde kullanıcının SY ekipleri.
"""

import json
from pathlib import Path
from datetime import timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session, load_only

from app.core.timeutil import utcnow
from app.db.models import (
    AppDependency, Application, ApplicationTrustedCert, AuditLog, Certificate,
    CertificateDomainMap, Domain, MailQueue, Notification, Team, TransferProposal, User, UserTeam,
)
from app.services.policy import RULE_LABELS, evaluate_certificate, get_config
from app.services.settings_service import get_category

# Ekip durumu: sıralamada önce 'critical'
STATUS_RANK = {"critical": 0, "warning": 1, "ok": 2}
# Canlı doğrulamada "dikkat" sayılan sonuçlar (sunucu envanterle uyuşmuyor)
LIVE_PROBLEM = {"mismatch", "chain_incomplete"}

# Değişiklik Talepleri ekranındaki kısa etiketlerle aynı (Proposals KIND_META)
UPCOMING_LIMIT = 100   # Ekibim yenileme takvimi: en yakın N sertifika

KIND_LABELS = {"transfer": "Sertifika değişimi", "date_fix": "Tarih güncelleme",
               "server_add": "Sunucuya eklenen", "server_remove": "Sunucudan kalkan",
               "trusted_add": "Trust store'a ekleme"}


def _days_left(valid_to) -> int | None:
    return (valid_to - utcnow()).days if valid_to else None


def _soon_days(db: Session) -> int:
    try:
        return int(get_category(db, "general").get("expiring_soon_days") or 30)
    except (TypeError, ValueError):
        return 30


def _proposal_label(p: TransferProposal) -> str:
    return KIND_LABELS.get(p.kind, p.kind)


class _Inventory:
    """Bir istekte bir kez yüklenen hafif envanter görüntüsü (PEM gibi büyük alanlar çekilmez)."""

    def __init__(self, db: Session):
        self.now = utcnow()
        self.soon = _soon_days(db)
        self.teams = {t.id: t for t in db.query(Team).filter(Team.type == "SY").all()}
        team_by_name = {t.name: t.id for t in self.teams.values()}
        self.domains = db.query(Domain).options(load_only(
            Domain.id, Domain.domain, Domain.sy_team_id, Domain.live_check_status,
            Domain.live_check_at, Domain.expire_date)).all()
        self.domain_by_id = {d.id: d for d in self.domains}
        has_pem = case((Certificate.pem_certificate.is_(None), 0), else_=1)
        rows = (db.query(Certificate, has_pem)
                .options(load_only(Certificate.id, Certificate.name, Certificate.cert_type,
                                   Certificate.issuer, Certificate.public_key_type, Certificate.key_size,
                                   Certificate.signature_hash, Certificate.valid_from,
                                   Certificate.valid_to, Certificate.creator))
                .filter(Certificate.is_active == True).all())  # noqa: E712 (MSSQL uyumu)
        self.certs = {c.id: c for c, _ in rows}
        self.cert_has_pem = {c.id: bool(p) for c, p in rows}
        maps = db.query(CertificateDomainMap.certificate_id, CertificateDomainMap.domain_id,
                        CertificateDomainMap.mapping_type).all()
        self.cert_domains: dict[int, list[tuple[int, str]]] = {}
        self.domain_certs: dict[int, set[int]] = {}
        for cid, did, mtype in maps:
            if cid not in self.certs:
                continue
            self.cert_domains.setdefault(cid, []).append((did, mtype))
            self.domain_certs.setdefault(did, set()).add(cid)
        # Sertifika → sahibi ekipler (bağlı domainlerin ekipleri + Oluşturan Ekip)
        self.cert_teams: dict[int, set[int]] = {}
        for cid, cert in self.certs.items():
            owners = {self.domain_by_id[did].sy_team_id for did, _ in self.cert_domains.get(cid, [])
                      if did in self.domain_by_id and self.domain_by_id[did].sy_team_id}
            if cert.creator and cert.creator in team_by_name:
                owners.add(team_by_name[cert.creator])
            self.cert_teams[cid] = owners
        policy_cfg = get_config(db)
        self.violations = {cid: v for cid, c in self.certs.items() if (v := evaluate_certificate(c, policy_cfg))}
        self.pending = (db.query(TransferProposal)
                        .filter(TransferProposal.status == "pending")
                        .order_by(TransferProposal.created_at.asc()).all())

    def days(self, cid: int) -> int | None:
        return _days_left(self.certs[cid].valid_to)

    def is_expired(self, cid: int) -> bool:
        d = self.days(cid)
        return d is not None and d < 0

    def is_soon(self, cid: int) -> bool:
        d = self.days(cid)
        return d is not None and 0 <= d <= self.soon

    def domain_without_cert(self, d: Domain) -> bool:
        return not self.domain_certs.get(d.id) and not d.expire_date

    def team_cert_ids(self, team_ids: set[int] | None) -> set[int]:
        if team_ids is None:
            return set(self.certs)
        return {cid for cid, owners in self.cert_teams.items() if owners & team_ids}

    def team_domains(self, team_ids: set[int] | None) -> list[Domain]:
        if team_ids is None:
            return list(self.domains)
        return [d for d in self.domains if d.sy_team_id in team_ids]

    def team_pending(self, team_ids: set[int] | None) -> list[TransferProposal]:
        if team_ids is None:
            return list(self.pending)
        return [p for p in self.pending if p.sy_team_id in team_ids]


def _age_days(dt, now) -> int | None:
    return (now - dt).days if dt else None


def _row(inv: _Inventory, team: Team, members: int, apps: int) -> dict:
    ids = {team.id}
    certs = inv.team_cert_ids(ids)
    domains = inv.team_domains(ids)
    pending = inv.team_pending(ids)
    expired = [c for c in certs if inv.is_expired(c)]
    soon = [c for c in certs if inv.is_soon(c)]
    future = [d for c in certs if (d := inv.days(c)) is not None and d >= 0]
    live_problem = [d for d in domains if d.live_check_status in LIVE_PROBLEM]
    no_pem = [c for c in certs if not inv.cert_has_pem[c]]
    no_cert = [d for d in domains if inv.domain_without_cert(d)]
    no_email = not (team.email or "").strip()
    policy = [c for c in certs if c in inv.violations]
    status = ("critical" if expired or live_problem
              else "warning" if soon or pending or policy or no_email else "ok")
    return {
        "team_id": team.id, "team": team.name, "email": team.email, "status": status,
        "members": members, "applications": apps,
        "domains": len(domains), "certificates": len(certs),
        "expired": len(expired), "expiring_soon": len(soon),
        "nearest_days": min(future) if future else None,
        "pending_proposals": len(pending),
        "oldest_pending_days": _age_days(pending[0].created_at, inv.now) if pending else None,
        "policy_violations": len(policy), "live_problems": len(live_problem),
        "missing_info": len(no_pem) + len(no_cert) + (1 if no_email else 0),
        "missing_detail": {"no_pem": len(no_pem), "domains_without_cert": len(no_cert),
                           "no_team_email": no_email},
    }


def _counts_by_team(db: Session, model_col, team_col) -> dict[int, int]:
    return {tid: n for tid, n in db.query(team_col, func.count(model_col)).group_by(team_col).all() if tid}


def _proposal_out(p: TransferProposal, inv: _Inventory) -> dict:
    dom = inv.domain_by_id.get(p.domain_id) if p.domain_id else None
    team = inv.teams.get(p.sy_team_id) if p.sy_team_id else None
    return {"id": p.id, "label": _proposal_label(p), "kind": p.kind,
            "domain_id": p.domain_id, "domain": dom.domain if dom else None,
            "app": p.app.app_name if p.kind == "trusted_add" and p.app else None,
            "old_cert": p.old_cert.name if p.old_cert else None,
            "new_cert": p.new_cert.name if p.new_cert else None,
            "team_id": p.sy_team_id, "team": team.name if team else None,
            "created_at": p.created_at, "age_days": _age_days(p.created_at, inv.now)}


def overview(db: Session, scope: set[int] | None) -> dict:
    """Ekip bazlı özet. scope None → tüm ekipler (yönetici görünümü); küme → yalnız o ekipler."""
    inv = _Inventory(db)
    members = _counts_by_team(db, UserTeam.id, UserTeam.team_id)
    apps = _counts_by_team(db, Application.id, Application.sy_team_id)
    teams = [t for t in inv.teams.values() if scope is None or t.id in scope]
    rows = [_row(inv, t, members.get(t.id, 0), apps.get(t.id, 0)) for t in teams]
    if scope is None:
        # Hiç kaydı olmayan (boş) ekipler tabloyu kalabalıklaştırmasın
        rows = [r for r in rows if r["domains"] or r["certificates"] or r["pending_proposals"]]
    rows.sort(key=lambda r: (STATUS_RANK[r["status"]], -r["expired"], -r["live_problems"],
                             -r["expiring_soon"],
                             r["nearest_days"] if r["nearest_days"] is not None else 10**6,
                             r["team"].lower()))

    cert_ids = inv.team_cert_ids(scope)
    domains = inv.team_domains(scope)
    pending = inv.team_pending(scope)
    expired = [c for c in cert_ids if inv.is_expired(c)]
    soon = [c for c in cert_ids if inv.is_soon(c)]
    future = [d for c in cert_ids if (d := inv.days(c)) is not None and d >= 0]

    # Önümüzdeki 90 gün, İstanbul takvim ayına göre
    months: dict[str, int] = {}
    for cid in cert_ids:
        d = inv.days(cid)
        if d is not None and 0 <= d <= 90:
            local = inv.certs[cid].valid_to.replace(tzinfo=None) + timedelta(hours=3)
            key = f"{local.year:04d}-{local.month:02d}"
            months[key] = months.get(key, 0) + 1

    upcoming = sorted((c for c in cert_ids if 0 <= (inv.days(c) if inv.days(c) is not None else -1) <= 90),
                      key=lambda c: inv.certs[c].valid_to)[:UPCOMING_LIMIT]

    missing = {
        "no_pem": sum(1 for c in cert_ids if not inv.cert_has_pem[c]),
        "domains_without_cert": sum(1 for d in domains if inv.domain_without_cert(d)),
        "domains_without_team": (sum(1 for d in inv.domains if not d.sy_team_id) if scope is None else 0),
    }
    return {
        "scope": "all" if scope is None else "team",
        "generated_at": inv.now,
        "expiring_soon_days": inv.soon,
        "totals": {
            "teams": len(rows),
            "domains": len(domains), "certificates": len(cert_ids),
            "expired": len(expired), "expired_teams": sum(1 for r in rows if r["expired"]),
            "expiring_soon": len(soon), "nearest_days": min(future) if future else None,
            "pending_proposals": len(pending),
            "oldest_pending_days": _age_days(pending[0].created_at, inv.now) if pending else None,
            "live_problems": sum(1 for d in domains if d.live_check_status in LIVE_PROBLEM),
            "policy_violations": sum(1 for c in cert_ids if c in inv.violations),
            "missing_info": sum(missing.values()),
            "missing_detail": missing,
            "status_counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_RANK},
        },
        "teams": rows,
        "upcoming_months": [{"month": k, "count": v} for k, v in sorted(months.items())],
        "upcoming_certs": [{"id": cid, "name": inv.certs[cid].name, "valid_to": inv.certs[cid].valid_to,
                            "days_left": inv.days(cid)} for cid in upcoming],
        "oldest_proposals": [_proposal_out(p, inv) for p in pending[:5]],
    }


def team_detail(db: Session, team_id: int) -> dict | None:
    """Tek ekibin özeti + dikkat isteyen kayıtlar. Ekip yoksa None."""
    inv = _Inventory(db)
    team = inv.teams.get(team_id)
    if team is None:
        return None
    members = db.query(func.count(UserTeam.id)).filter(UserTeam.team_id == team_id).scalar() or 0
    apps = db.query(func.count(Application.id)).filter(Application.sy_team_id == team_id).scalar() or 0
    row = _row(inv, team, members, apps)
    ids = {team_id}
    cert_ids = inv.team_cert_ids(ids)
    domains = inv.team_domains(ids)

    urgent = sorted((c for c in cert_ids if inv.is_expired(c) or inv.is_soon(c)),
                    key=lambda c: inv.certs[c].valid_to)
    last_mail = dict(db.query(Notification.certificate_id, func.max(Notification.sent_at))
                     .filter(Notification.certificate_id.in_(urgent or [-1]))
                     .group_by(Notification.certificate_id).all())
    open_by_cert: dict[int, list[str]] = {}
    for p in inv.pending:
        for cid in {p.old_cert_id, p.new_cert_id}:
            open_by_cert.setdefault(cid, [])
            label = _proposal_label(p)
            if label not in open_by_cert[cid]:
                open_by_cert[cid].append(label)
    team_domain_ids = {d.id for d in domains}

    def cert_out(cid: int) -> dict:
        c = inv.certs[cid]
        names = [inv.domain_by_id[did].domain for did, _ in inv.cert_domains.get(cid, [])
                 if did in team_domain_ids]
        return {"id": cid, "name": c.name, "cert_type": c.cert_type, "valid_to": c.valid_to,
                "days_left": inv.days(cid), "domains": names,
                "last_mail_at": last_mail.get(cid), "open_proposals": open_by_cert.get(cid, [])}

    attention: list[dict] = []
    for d in domains:
        if d.live_check_status in LIVE_PROBLEM:
            attention.append({"kind": "live", "domain_id": d.id, "name": d.domain,
                              "detail": "Canlı doğrulamada EŞLEŞMİYOR" if d.live_check_status == "mismatch"
                              else "Ara sertifika sunucuda eksik"})
    for d in domains:
        if inv.domain_without_cert(d):
            attention.append({"kind": "no_cert", "domain_id": d.id, "name": d.domain,
                              "detail": "Bağlı sertifika ve bitiş tarihi yok, takip edilmiyor"})
    for cid in sorted(cert_ids, key=lambda c: inv.certs[c].name.lower()):
        if cid in inv.violations:
            rules = ", ".join(RULE_LABELS.get(v["rule"], v["rule"]) for v in inv.violations[cid])
            attention.append({"kind": "policy", "certificate_id": cid, "name": inv.certs[cid].name,
                              "detail": f"Uyum: {rules}"})
    for cid in sorted(cert_ids, key=lambda c: inv.certs[c].name.lower()):
        if not inv.cert_has_pem[cid]:
            attention.append({"kind": "no_pem", "certificate_id": cid, "name": inv.certs[cid].name,
                              "detail": "PEM yok, zincir kontrol edilemez"})

    return {
        **row,
        "expiring_soon_days": inv.soon,
        "certificates_attention": [cert_out(c) for c in urgent],
        "pending": [_proposal_out(p, inv) for p in inv.team_pending(ids)],
        "attention": attention,
    }


# --- Sertifika: bitince etkilenenler -------------------------------------------------

def certificate_impact(db: Session, cert: Certificate) -> dict:
    """Sertifika biterse etkilenecek domainler, uygulamalar ve uyarı maili alacak paydaşlar.
    Paydaşlar mail motorunun kendi çözümüdür (notifier._expiry_stakeholders) — ekranda görünen
    liste ile gerçekte mail alanlar aynı olsun."""
    from app.services.notifier import _expiry_stakeholders, _no_recipient_party

    smtp = get_category(db, "smtp", mask_secrets=False)
    try:
        global_days = int(smtp.get("expiry_warning_days") or 30)
    except (TypeError, ValueError):
        global_days = 30

    domains = []
    server_domain_ids = []
    for m in cert.domain_mappings:
        d = m.domain
        if d is None:
            continue
        if m.mapping_type == "server":
            server_domain_ids.append(d.id)
        domains.append({"domain_id": d.id, "domain": d.domain, "mapping_type": m.mapping_type,
                        "team": d.sy_team.name if d.sy_team else None})
    domains.sort(key=lambda x: x["domain"].lower())

    apps: dict[tuple[int, str], dict] = {}

    def add_app(app: Application | None, relation: str, via: str | None = None) -> None:
        if app is None:
            return
        apps.setdefault((app.id, relation), {
            "app_id": app.id, "app_name": app.app_name, "relation": relation, "via": via,
            "team": app.sy_team.name if app.sy_team else None, "active": bool(app.status)})

    if server_domain_ids:
        for app in db.query(Application).filter(Application.domain_id.in_(server_domain_ids)).all():
            add_app(app, "Bağlı Domain", app.domain.domain if app.domain else None)
        for dep in db.query(AppDependency).filter(AppDependency.target_domain_id.in_(server_domain_ids)).all():
            add_app(dep.app, "Bu domaine bağlanıyor", dep.target_domain.domain if dep.target_domain else None)
    for dep in db.query(AppDependency).filter(AppDependency.client_cert_id == cert.id).all():
        add_app(dep.app, "Trusted bağlantı", dep.target_domain.domain if dep.target_domain else None)
    for tr in db.query(ApplicationTrustedCert).filter(ApplicationTrustedCert.cert_id == cert.id).all():
        add_app(tr.app, "Trust store")

    expired = cert.valid_to is not None and cert.valid_to < utcnow()
    parties = _expiry_stakeholders(db, cert, global_days, include_trusted=not expired)
    fallback = False
    if not parties:
        fb = _no_recipient_party(smtp, global_days)
        if fb:
            parties, fallback = [fb], True
    recipients = []
    for p in parties:
        starts = cert.valid_to - timedelta(days=p["effective_days"]) if cert.valid_to else None
        recipients.append({"label": p["label"], "emails": p["emails"], "reasons": p["reasons"],
                           "effective_days": p["effective_days"], "starts_on": starts})
    return {
        "certificate_id": cert.id,
        "domains": domains,
        "applications": sorted(apps.values(), key=lambda a: (a["app_name"].lower(), a["relation"])),
        "recipients": recipients,
        "fallback": fallback,
        "mail_enabled": bool(smtp.get("enabled")),
        "expired": expired,
    }


# --- Sistem Sağlığı ------------------------------------------------------------------

# (scheduler id, audit 'job' adı(ları), ekran adı, ayar kategorisi, etkinlik anahtarı, varsayılan)
JOBS = [
    ("expiry-check", ("Süre uyarısı maili",), "Sabah uyarı mailleri", "smtp", "auto_expiry_enabled", True),
    ("expired-check", ("Süresi geçmiş hatırlatması",), "Süresi dolmuş sertifika maili", "smtp",
     "auto_expired_enabled", True),
    ("proposal-reminder", ("Değişiklik talebi hatırlatması",), "Değişiklik talebi hatırlatması", "smtp",
     "auto_proposal_reminder_enabled", False),
    ("live-check", ("Canlı doğrulama", "Canlı doğrulama (tetiklenen)"), "Canlı doğrulama", "live_check",
     "enabled", False),
    ("discovery-scan", ("Ağ keşfi",), "Keşif taraması", "discovery", "enabled", False),
    ("ct-scan", ("CT log izleme",), "CT izleme", "ct", "enabled", False),
    ("revocation-check", ("İptal (OCSP/CRL) denetimi",), "İptal kontrolü", "revocation", "enabled", False),
]


def _job_summary_text(job_id: str, d: dict) -> str:
    if d.get("status") == "error":
        return f"Hata: {d.get('error') or 'bilinmiyor'}"
    if job_id in ("expiry-check", "expired-check", "proposal-reminder"):
        return f"{d.get('checked') or 0} kayıt incelendi, {d.get('sent') or 0} mail gönderildi"
    if job_id == "live-check":
        by = d.get("by_status") or {}
        parts = [f"{d.get('total') or 0} domain"]
        for key, label in (("mismatch", "EŞLEŞMİYOR"), ("chain_incomplete", "ara sertifika eksik"),
                           ("unreachable", "ulaşılamadı")):
            if by.get(key):
                parts.append(f"{by[key]} {label}")
        return ", ".join(parts)
    if job_id in ("discovery-scan", "ct-scan"):
        return f"{d.get('targets') or 0} hedef, {d.get('new_findings') or 0} yeni bulgu"
    if job_id == "revocation-check":
        return f"{d.get('checked') or 0} sertifika, {d.get('revoked') or 0} iptal edilmiş"
    return ""


def _next_run(job_id: str):
    try:
        from app.services.notifier import scheduler
        if not scheduler.running:
            return None
        job = scheduler.get_job(job_id)
        nrt = job.next_run_time if job else None
        return nrt.astimezone(timezone.utc).replace(tzinfo=None) if nrt else None
    except Exception:
        return None


def _app_version() -> str:
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    except OSError:
        return ""


def system_health(db: Session) -> dict:
    from app.services import mail_history

    now = utcnow()
    jobs = []
    for job_id, names, label, cat, key, default in JOBS:
        cfg = get_category(db, cat, mask_secrets=False)
        enabled = bool(cfg.get(key, default))
        if cat == "smtp":
            enabled = enabled and bool(cfg.get("enabled"))
        last = (db.query(AuditLog)
                .filter(AuditLog.action == "job_summary", AuditLog.record_id.in_(names))
                .order_by(AuditLog.created_at.desc()).first())
        details: dict = {}
        if last is not None:
            try:
                details = json.loads(last.details or "{}")
            except ValueError:
                details = {}
        status = details.get("status") if last is not None else None
        jobs.append({
            "id": job_id, "label": label, "enabled": enabled,
            "last_run_at": last.created_at if last is not None else None,
            "manual": bool(last is not None and last.record_id != names[0]),
            "status": status, "summary": _job_summary_text(job_id, details) if last is not None else None,
            "duration_s": details.get("duration_s"),
            "next_run_at": _next_run(job_id) if enabled else None,
        })

    week = now - timedelta(days=7)
    fac = mail_history.facets(db, mail_history._Filters(channel="email", lo=week))
    refused = (db.query(func.count(MailQueue.id))
               .filter(MailQueue.status == "failed", MailQueue.created_at >= week,
                       MailQueue.last_error.like("kısmen gönderildi%")).scalar() or 0)
    fallback = (db.query(func.count(Notification.id))
                .filter(Notification.sent_at >= week, Notification.subject.like("%→ yedek adres%"))
                .scalar() or 0)

    inv = _Inventory(db)
    app_cert_ids = {r[0] for r in db.query(AppDependency.client_cert_id)
                    .filter(AppDependency.client_cert_id.isnot(None)).all()}
    app_cert_ids |= {r[0] for r in db.query(ApplicationTrustedCert.cert_id)
                     .filter(ApplicationTrustedCert.cert_id.isnot(None)).all()}
    users_with_email = {u for (u,) in db.query(User.username)
                        .filter(User.is_active == True, User.email.isnot(None)).all()}  # noqa: E712
    teams_with_email = {t.name for t in inv.teams.values() if (t.email or "").strip()}

    def has_recipient(cid: int) -> bool:
        c = inv.certs[cid]
        if c.creator and (c.creator in teams_with_email or c.creator in users_with_email):
            return True
        if cid in app_cert_ids:
            return True
        for did, _ in inv.cert_domains.get(cid, []):
            d = inv.domain_by_id.get(did)
            if d is not None and d.sy_team_id in inv.teams and (inv.teams[d.sy_team_id].email or "").strip():
                return True
        return False

    smtp = get_category(db, "smtp", mask_secrets=False)
    ldap = get_category(db, "ldap", mask_secrets=False)
    return {
        "generated_at": now,
        "jobs": jobs,
        "mail_week": {
            "sent": fac["statuses"].get("sent", 0), "failed": fac["statuses"].get("failed", 0),
            "pending": fac["statuses"].get("pending", 0), "refused": refused, "fallback": fallback,
        },
        "missing": {
            "domains_without_team": sum(1 for d in inv.domains if not d.sy_team_id),
            "certs_without_recipient": sum(1 for c in inv.certs if not has_recipient(c)),
            "certs_without_pem": sum(1 for c in inv.certs if not inv.cert_has_pem[c]),
            "apps_without_team": db.query(func.count(Application.id))
            .filter(Application.sy_team_id.is_(None)).scalar() or 0,
            "teams_without_email": sum(1 for t in inv.teams.values() if not (t.email or "").strip()),
        },
        "connections": {
            "smtp": {"enabled": bool(smtp.get("enabled")), "host": smtp.get("host") or None,
                     "fallback_address": smtp.get("fallback_address") or None,
                     "queue_enabled": bool(smtp.get("queue_enabled"))},
            "ldap": {"enabled": bool(ldap.get("enabled")), "server": ldap.get("server") or None},
            "database": True,
            "version": _app_version(),
        },
    }
