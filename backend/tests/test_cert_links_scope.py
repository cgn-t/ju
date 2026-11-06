"""Sertifika → Bağlantılar: başka SY ekibinin domaini için ekip adı + can_view=False döner
(ekran gri pencere yerine "görüntüleme yetkiniz yok" uyarısı gösterir). Admin hepsini açabilir."""
from app.db import models as m
from app.db.session import SessionLocal
from tests.test_scope_idor import _setup


def test_cert_domains_carry_team_and_can_view(client, auth_headers):
    own, other, hdr, ids = _setup(client, auth_headers, "lnk1")
    db = SessionLocal()
    try:
        cert = m.Certificate(name="links-scope.local", cert_type="leaf", is_active=True)
        db.add(cert); db.flush()
        db.add(m.CertificateDomainMap(certificate_id=cert.id, domain_id=ids["dom_own"], mapping_type="server"))
        db.add(m.CertificateDomainMap(certificate_id=cert.id, domain_id=ids["dom_other"], mapping_type="client"))
        db.commit()
        cid = cert.id
    finally:
        db.close()

    r = client.get(f"/api/certificates/{cid}", headers=hdr)
    assert r.status_code == 200, r.text
    by = {d["domain_id"]: d for d in r.json()["domains"]}
    assert by[ids["dom_own"]]["can_view"] is True
    assert by[ids["dom_own"]]["team"] == "KapsamOwnlnk1"
    assert by[ids["dom_other"]]["can_view"] is False
    assert by[ids["dom_other"]]["team"] == "KapsamOtherlnk1"
    # Kapsam dışı domainin canlı durumu sızmaz; detay GET'i hâlâ 404
    assert by[ids["dom_other"]]["live_check_status"] is None
    assert client.get(f"/api/domains/{ids['dom_other']}", headers=hdr).status_code == 404

    imp = client.get(f"/api/certificates/{cid}/impact", headers=hdr).json()
    assert {d["domain_id"]: d["can_view"] for d in imp["domains"]} == {ids["dom_own"]: True, ids["dom_other"]: False}

    # Admin kapsamsız: hepsi açılabilir
    r = client.get(f"/api/certificates/{cid}", headers=auth_headers)
    assert all(d["can_view"] for d in r.json()["domains"])
