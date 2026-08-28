"""FAZ 3 — Şablon birleştirme (Faz 2) SONRASI tutarlılık testleri.

Kapsam: 4 mail türünün (süre-uyarı, süresi-geçmiş, devir-hatırlatma, pasife-alma) artık
ortak footer/genişlik/subject-prefix paylaştığını ve devir-hatırlatmasının HTML sürümünün
artık doküman linklerini de içerdiğini (Faz 2'de eklenen düzeltme — önceden yalnız düz-metin
sürümünde vardı) kilitler."""

from datetime import datetime, timedelta

from app.db.models import Certificate, CertificateDomainMap, Domain, Team, TransferProposal
from app.db.session import SessionLocal
from app.services import notifier
from tests import certgen


def _team(client, h, name, email):
    r = client.post("/api/teams", headers=h, json={"name": name, "type": "SY", "email": email})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_leaf(client, h, cn, *, days=30, nb_days_ago=25):
    ca, ca_key = certgen.make_ca(f"CA {cn}")
    nb = datetime.utcnow() - timedelta(days=nb_days_ago)
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=nb, days=days, san=[cn])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


def _set_smtp(client, h, **over):
    cfg = {"enabled": True, "host": "smtp.test", "from_address": "jumbo@test",
           "expiry_warning_days": 30, "resend_interval_hours": 3, "auto_expiry_enabled": True,
           "queue_enabled": False, "fallback_address": ""}
    cfg.update(over)
    assert client.put("/api/settings/smtp", headers=h, json=cfg).status_code == 200


def _capture(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(notifier, "_send_mail",
                        lambda cfg, to, subject, body, html=None: sent.append(
                            {"to": list(to), "subject": subject, "html": html}))
    return sent


def _seed(fn):
    db = SessionLocal()
    try:
        r = fn(db)
        db.commit()
        return r
    finally:
        db.close()


def _run(fn=None, **kw):
    db = SessionLocal()
    try:
        return (fn or notifier.send_expiry_notifications)(db, **kw)
    finally:
        db.close()


def _setup_cert_domain_proposal(client, h, tag):
    """Bir SY ekibi + domain + sertifika + o sertifikayı devreden bir TransferProposal kurar.
    (cert_id, team_id, domain, proposal_id) döner."""
    tid = _team(client, h, f"TC {tag} SY", f"tc-{tag}@test")
    cid = _import_leaf(client, h, f"tc-{tag}-cert.test")

    def seed(db):
        cert = db.get(Certificate, cid)
        cert.creator = None
        dom = Domain(domain=f"tc-{tag}-dom.test", sy_team_id=tid)
        db.add(dom)
        db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=dom.id, mapping_type="server"))
        new_cert = Certificate(name=f"tc-{tag}-new.test", cert_type="leaf",
                               valid_from=datetime.utcnow(),
                               valid_to=datetime.utcnow() + timedelta(days=365), is_active=False)
        db.add(new_cert)
        db.flush()
        proposal = TransferProposal(old_cert_id=cid, new_cert_id=new_cert.id, domain_id=dom.id,
                                    mapping_type="server", sy_team_id=tid, status="pending",
                                    kind="transfer", via="manual")
        db.add(proposal)
        db.flush()
        return dom.domain, proposal.id
    domain_name, proposal_id = _seed(seed)
    return cid, tid, domain_name, proposal_id


def test_all_render_functions_share_footer_and_width(client, auth_headers):
    """4 render fonksiyonunun da (süre-uyarı/süresi-geçmiş/devir-hatırlatma/pasife-alma)
    aynı ortak footer'ı ve aynı max-width'i ürettiğini doğrular — Faz 2 öncesi bu üçü
    (özellikle devir-hatırlatma ve pasife-alma) birbirinden farklıydı."""
    h = auth_headers
    cid, tid, domain_name, proposal_id = _setup_cert_domain_proposal(client, h, "footer")

    db = SessionLocal()
    try:
        cert = db.get(Certificate, cid)
        team = db.get(Team, tid)
        proposal = db.get(TransferProposal, proposal_id)

        party = {"label": team.name, "emails": [team.email], "reasons": ["test nedeni"],
                "effective_days": 30}
        html_expiry = notifier._render_cert_mail_html(cert, 5, party, expired=False)
        html_expired = notifier._render_cert_mail_html(cert, -3, party, expired=True)
        html_proposal = notifier._render_proposal_reminder_html(team, [proposal], {"doc_links": ""})
        html_deact = notifier._render_deactivation_html(cert, "admin", [domain_name], [team.name])

        for name, html in (("expiry", html_expiry), ("expired", html_expired),
                           ("proposal", html_proposal), ("deactivation", html_deact)):
            assert notifier._MAIL_FOOTER in html, f"{name}: ortak footer eksik"
            assert notifier._MAIL_MAX_WIDTH in html, f"{name}: ortak genişlik eksik"
    finally:
        db.close()


def test_proposal_reminder_html_includes_doc_links(client, auth_headers):
    """Faz 2 öncesi _render_proposal_reminder_html doc_links'i HİÇ eklemiyordu (yalnız düz-metin
    sürümünde vardı) — bu asimetri artık kapandı."""
    h = auth_headers
    cid, tid, domain_name, proposal_id = _setup_cert_domain_proposal(client, h, "doclinks")
    db = SessionLocal()
    try:
        team = db.get(Team, tid)
        proposal = db.get(TransferProposal, proposal_id)
        cfg = {"doc_links": "https://wiki.test/devir-onay-rehberi"}
        html = notifier._render_proposal_reminder_html(team, [proposal], cfg)
        assert "https://wiki.test/devir-onay-rehberi" in html
    finally:
        db.close()


def test_all_scenario_subjects_have_jumbo_prefix(client, auth_headers, monkeypatch):
    """4 senaryonun da gerçek gönderiminde subject'in [JUMBO] ile başladığını doğrular
    (uçtan uca, gerçek send_* / notify_certificate_deactivated çağrılarıyla)."""
    h = auth_headers

    # 1: süre-uyarı
    _team(client, h, "TC Subj SY", "tc-subj@test")
    cid = _import_leaf(client, h, "tc-subj-cert.test")
    _seed(lambda db: setattr(db.get(Certificate, cid), "creator", "TC Subj SY"))
    _set_smtp(client, h)
    sent = _capture(monkeypatch)
    _run(force=True)
    assert sent and all(m["subject"].startswith("[JUMBO]") for m in sent)

    # 2: süresi geçmiş
    cid_exp = _import_leaf(client, h, "tc-subj-expired.test", days=10, nb_days_ago=40)
    _seed(lambda db: setattr(db.get(Certificate, cid_exp), "creator", "TC Subj SY"))
    sent.clear()
    _run(notifier.send_expired_notifications, force=True)
    assert sent and all(m["subject"].startswith("[JUMBO]") for m in sent)

    # 3: devir hatırlatma
    _setup_cert_domain_proposal(client, h, "subjprop")
    sent.clear()
    db = SessionLocal()
    try:
        notifier.send_pending_proposal_notifications(db, force=True)
    finally:
        db.close()
    assert sent and all(m["subject"].startswith("[JUMBO]") for m in sent)

    # 4: pasife alma — bu sertifikaya bağlı domaini olan bir ekip kur
    tid_deact = _team(client, h, "TC Subj Deact SY", "tc-subj-deact@test")
    cid_deact = _import_leaf(client, h, "tc-subj-deact-cert.test")
    dom_id = client.post("/api/domains", headers=h, json={"domain": "tc-subj-deact-dom.test"}).json()["id"]
    client.put(f"/api/domains/{dom_id}", headers=h, json={"sy_team_id": tid_deact})
    r = client.post(f"/api/domains/{dom_id}/certificates", headers=h,
                    json={"certificate_id": cid_deact, "mapping_type": "client"})
    assert r.status_code == 200, r.text
    sent.clear()
    db = SessionLocal()
    try:
        cert = db.get(Certificate, cid_deact)
        notifier.notify_certificate_deactivated(db, cert, "admin")
    finally:
        db.close()
    assert sent and all(m["subject"].startswith("[JUMBO]") for m in sent)
