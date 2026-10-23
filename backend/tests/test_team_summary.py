"""v3.9.9: Yönetici Panosu (tüm ekipler), Ekibim (kendi ekibi), ekip detayı, sertifika
Mailler/Etkilenenler sekmeleri ve Sistem Sağlığı. Hepsi mevcut tablolardan hesaplanır."""
import json
from datetime import timedelta

from app.core.timeutil import utcnow
from app.db.models import (
    Application, AuditLog, Certificate, CertificateDomainMap, Domain, MailQueue, Notification, Team,
    TransferProposal,
)
from app.db.session import SessionLocal
from tests.test_scope_idor import _editor_in, _sy_team


def _login_as(client, headers, username, role):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": role, "auth_source": "local"})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _seed(tag, team_a, team_b):
    """A ekibi: 1 süresi dolmuş, 1 yakında biten, 1 PEM'siz uzun ömürlü, 1 sertifikasız domain,
    1 EŞLEŞMİYOR domain, 1 bekleyen talep. B ekibi: tek sağlıklı sertifika."""
    db = SessionLocal()
    try:
        db.get(Team, team_a).email = f"a-{tag}@ornek.local"
        db.get(Team, team_b).email = f"b-{tag}@ornek.local"
        ids = {}

        def dom(name, team, **kw):
            d = Domain(domain=f"{name}-{tag}.ornek.local", sy_team_id=team, **kw)
            db.add(d)
            db.flush()
            return d

        def cert(name, days, pem=True, **kw):
            c = Certificate(name=f"{name}-{tag}", cert_type="leaf", is_active=True,
                            valid_from=utcnow() - timedelta(days=30),
                            valid_to=utcnow() + timedelta(days=days),
                            pem_certificate=("PEM-" + name) if pem else None, **kw)
            db.add(c)
            db.flush()
            return c

        def bind(c, d, mtype="server"):
            db.add(CertificateDomainMap(certificate_id=c.id, domain_id=d.id, mapping_type=mtype))

        d1, d2, d3 = dom("dolmus", team_a), dom("yakin", team_a), dom("uzun", team_a, live_check_status="mismatch")
        dom("bos", team_a)  # sertifikasız, bitiş tarihi yok → takip edilmiyor
        c1, c2, c3 = cert("dolmus", -5), cert("yakin", 10), cert("uzun", 200, pem=False)
        bind(c1, d1)
        bind(c2, d2)
        bind(c3, d3)
        new = cert("yakin-yeni", 365)
        db.add(TransferProposal(old_cert_id=c2.id, new_cert_id=new.id, domain_id=d2.id,
                                mapping_type="server", kind="transfer", sy_team_id=team_a,
                                status="pending", created_at=utcnow() - timedelta(days=4)))
        db4 = dom("saglam", team_b)
        c4 = cert("saglam", 300)
        bind(c4, db4)
        app = Application(app_name=f"Uyg-{tag}", domain_id=d2.id, sy_team_id=team_b, status=True)
        db.add(app)
        orphan = cert("sahipsiz", 50)
        db.commit()
        ids.update(c1=c1.id, c2=c2.id, c3=c3.id, c4=c4.id, orphan=orphan.id, d2=d2.id, app=app.id)
        return ids
    finally:
        db.close()


def _setup(client, auth_headers, tag):
    a = _sy_team(client, auth_headers, f"OzetA{tag}")
    b = _sy_team(client, auth_headers, f"OzetB{tag}")
    ids = _seed(tag, a, b)
    return a, b, ids


def test_manager_overview_all_teams_sorted_by_risk(client, auth_headers):
    a, b, _ = _setup(client, auth_headers, "m1")
    r = client.get("/api/summary/teams", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "all"
    rows = {t["team_id"]: t for t in body["teams"]}
    ra, rb = rows[a], rows[b]
    assert ra["status"] == "critical" and rb["status"] == "ok"
    assert (ra["expired"], ra["expiring_soon"], ra["pending_proposals"], ra["live_problems"]) == (1, 1, 1, 1)
    assert ra["oldest_pending_days"] == 4 and ra["nearest_days"] in (9, 10)
    assert ra["missing_detail"] == {"no_pem": 1, "domains_without_cert": 1, "no_team_email": False,
                                    "domains_without_team": 0}
    assert ra["missing_info"] == 2
    order = [t["team_id"] for t in body["teams"]]
    assert order.index(a) < order.index(b)
    # Genel toplamda ekibi olmayan sertifikalar da sayılır (Anasayfa ile aynı)
    assert body["totals"]["certificates"] >= 6
    assert any(p["label"] == "Sertifika değişimi" for p in body["oldest_proposals"])


def test_allviewer_sees_all_editor_sees_own_team(client, auth_headers):
    a, b, _ = _setup(client, auth_headers, "m2")
    viewer = _login_as(client, auth_headers, "ozet_genel_m2", "allviewer")
    body = client.get("/api/summary/teams", headers=viewer).json()
    assert body["scope"] == "all"
    assert {a, b} <= {t["team_id"] for t in body["teams"]}

    editor = _editor_in(client, auth_headers, "ozet_ed_m2", a)
    body = client.get("/api/summary/teams", headers=editor).json()
    assert body["scope"] == "team"
    assert [t["team_id"] for t in body["teams"]] == [a]
    # Toplamlar yalnız kendi ekibinden
    assert body["totals"]["expired"] == 1 and body["totals"]["expiring_soon"] == 1
    assert client.get(f"/api/summary/teams/{b}", headers=editor).status_code == 403
    assert client.get(f"/api/summary/teams/{a}", headers=editor).status_code == 200


def test_team_detail_lists(client, auth_headers):
    a, _, ids = _setup(client, auth_headers, "m3")
    db = SessionLocal()
    try:
        db.add(Notification(certificate_id=ids["c1"], recipient="x@ornek.local", subject="s", days_left=-5))
        db.commit()
    finally:
        db.close()
    r = client.get(f"/api/summary/teams/{a}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    names = [c["name"] for c in body["certificates_attention"]]
    assert names == ["dolmus-m3", "yakin-m3"]  # bitişe göre sıralı, uzun ömürlü yok
    assert body["certificates_attention"][0]["last_mail_at"] is not None
    assert body["certificates_attention"][1]["open_proposals"] == ["Sertifika değişimi"]
    kinds = {i["kind"] for i in body["attention"]}
    assert {"live", "no_cert", "no_pem"} <= kinds
    assert len(body["pending"]) == 1 and body["pending"][0]["age_days"] == 4
    assert client.get("/api/summary/teams/999999", headers=auth_headers).status_code == 404


def test_certificate_impact_recipients_and_apps(client, auth_headers):
    a, b, ids = _setup(client, auth_headers, "m4")
    r = client.get(f"/api/certificates/{ids['c2']}/impact", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["domain"] for d in body["domains"]] == ["yakin-m4.ornek.local"]
    assert [(x["app_name"], x["relation"]) for x in body["applications"]] == [("Uyg-m4", "Bağlı Domain")]
    emails = sorted(e for p in body["recipients"] for e in p["emails"])
    assert emails == ["a-m4@ornek.local", "b-m4@ornek.local"]  # domain ekibi + uygulama sahibi
    assert all(p["starts_on"] for p in body["recipients"]) and body["fallback"] is False

    # Hiç alıcısı yok → yedek adres (tanımlıysa) gösterilir
    client.put("/api/settings/smtp", headers=auth_headers, json={"fallback_address": "yedek@ornek.local"})
    body = client.get(f"/api/certificates/{ids['orphan']}/impact", headers=auth_headers).json()
    assert body["fallback"] is True and body["recipients"][0]["emails"] == ["yedek@ornek.local"]
    assert client.get("/api/certificates/999999/impact", headers=auth_headers).status_code == 404


def test_certificate_mails_hide_error_for_non_admin(client, auth_headers):
    a, _, ids = _setup(client, auth_headers, "m5")
    db = SessionLocal()
    try:
        db.add(Notification(certificate_id=ids["c2"], recipient="a-m5@ornek.local",
                            subject="Sertifika süresi doluyor → OzetAm5", days_left=10))
        db.add(MailQueue(to_addresses="eski@ornek.local", subject="Sertifika süresi doluyor",
                         body_text="b", certificate_id=ids["c2"], status="failed",
                         last_error="kısmen gönderildi — sunucu reddetti: eski@ornek.local (550)", attempts=1))
        db.add(Notification(certificate_id=ids["c4"], recipient="b@ornek.local", subject="baska"))
        db.commit()
    finally:
        db.close()
    rows = client.get(f"/api/certificates/{ids['c2']}/mails", headers=auth_headers).json()
    assert {(r["status"], r["recipient"]) for r in rows} == {
        ("sent", "a-m5@ornek.local"), ("failed", "eski@ornek.local")}
    assert any(r["error"] for r in rows)
    editor = _editor_in(client, auth_headers, "ozet_ed_m5", a)
    rows = client.get(f"/api/certificates/{ids['c2']}/mails", headers=editor).json()
    assert len(rows) == 2 and not any(r["error"] for r in rows)


def test_system_health_admin_only(client, auth_headers):
    a, _, _ = _setup(client, auth_headers, "m6")
    db = SessionLocal()
    try:
        db.add(AuditLog(username="system", action="job_summary", table_name="jobs",
                        record_id="Canlı doğrulama", details=json.dumps(
                            {"job": "Canlı doğrulama", "status": "ok", "total": 12,
                             "by_status": {"match": 10, "mismatch": 2}, "duration_s": 3.2})))
        db.commit()
    finally:
        db.close()
    r = client.get("/api/system/health", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    live = next(j for j in body["jobs"] if j["id"] == "live-check")
    assert live["status"] == "ok" and live["summary"] == "12 domain, 2 EŞLEŞMİYOR"
    assert live["last_run_at"] is not None
    assert body["missing"]["certs_without_recipient"] >= 1   # sahipsiz sertifika
    assert body["missing"]["certs_without_pem"] >= 1
    assert body["connections"]["version"]
    editor = _editor_in(client, auth_headers, "ozet_ed_m6", a)
    assert client.get("/api/system/health", headers=editor).status_code == 403
    viewer = _login_as(client, auth_headers, "ozet_genel_m6", "allviewer")
    assert client.get("/api/system/health", headers=viewer).status_code == 403
