"""Devir önerisi kapsamı ve tip koruması (2026-10-16 canlı vakası).

  • Canlı doğrulama YALNIZ kontrol ettiği domain için öneri üretir — eski sertifikanın diğer
    domainlerine yayılmaz (SSLVA ve abc.com/fff.com.tr vakaları).
  • Her seviye (leaf/intermediate/root) için EKLEME / DEĞİŞİKLİK / KALDIRMA önerisi; eşleme
    kendiliğinden değişmez. Root sunulmadığında envanterdeki üst sertifikadan türetilir.
  • Farklı seviyeler (root/intermediate ↔ leaf) arasında hiçbir yoldan devir önerisi oluşmaz.
  • cert_type_filter LOWER() kullanmaz (Türkçe collation'da 'Intermediate' → 'ıntermediate').
"""

from datetime import datetime

import pytest

from app.core.certtype import cert_type_filter
from app.db import models as m
from app.db.session import SessionLocal
from app.services import cert_parser, live_check, renewal
from tests import certgen


@pytest.fixture()
def db(client):
    s = SessionLocal()
    yield s
    s.close()


def _add(db, cert, cert_type=None, *, parent=None):
    """Envantere ekler. cert_type verilirse prod'daki gibi ham yazım ("Intermediate") kullanılır."""
    p = cert_parser.parse_x509(cert)
    row = m.Certificate(**p.__dict__)
    if cert_type:
        row.cert_type = cert_type
    if parent is not None:
        row.parent_id = parent.id
    db.add(row)
    db.flush()
    return row


def _domain(db, name, *server_certs):
    dom = m.Domain(domain=name)
    db.add(dom)
    db.flush()
    for c in server_certs:
        db.add(m.CertificateDomainMap(certificate_id=c.id, domain_id=dom.id, mapping_type="server"))
    db.flush()
    return dom


def _live(db, dom, monkeypatch, *served):
    monkeypatch.setattr(live_check, "fetch_served_chain", lambda host, port: list(served))
    live_check.check_domain(db, dom)
    db.flush()


def _props(db, *domains):
    """Paylaşılan test DB'sinde yalnız verilen domainlerin bekleyen önerileri."""
    return (db.query(m.TransferProposal)
            .filter(m.TransferProposal.status == "pending",
                    m.TransferProposal.domain_id.in_([d.id for d in domains]))
            .order_by(m.TransferProposal.id).all())


def _chain(tag, *, leaf_cn=None, root=None):
    """root → intermediate → leaf (gerçek imzalı zincir)."""
    if root is None:
        root = certgen.make_ca(f"{tag} Root", not_before=datetime(2020, 1, 1))
    r, rk = root
    i, ik = certgen.make_intermediate(r, rk, f"{tag} CA", not_before=datetime(2021, 1, 1))
    leaf, _ = certgen.make_leaf(i, ik, leaf_cn or f"{tag}.test", not_before=datetime(2026, 1, 1))
    return (r, rk), (i, ik), leaf


def test_live_check_proposes_only_for_checked_domain_sslva(db, monkeypatch):
    """SSLVA vakası: X sertifikası web ve sslva'ya bağlı. web.aa.com yeni sertifika sunar →
    öneri YALNIZ web.aa.com için; sslva (X'e bağlı olsa da) etkilenmez."""
    (r, rk), (i, ik), x = _chain("sslva")
    y, _ = certgen.make_leaf(i, ik, "*.aa.test", not_before=datetime(2026, 6, 1))
    R = _add(db, r, "Root")
    I = _add(db, i, "Intermediate", parent=R)
    X = _add(db, x, "Leaf", parent=I)
    Y = _add(db, y, "Leaf", parent=I)
    web = _domain(db, "web.aa.test", R, I, X)
    sslva = _domain(db, "sslva.aa.test", R, I, X)

    _live(db, web, monkeypatch, y, i)

    props = _props(db, web, sslva)
    assert [(p.kind, p.old_cert_id, p.new_cert_id, p.domain_id) for p in props] == \
        [("transfer", X.id, Y.id, web.id)]
    assert props[0].via == "live-check" and props[0].live_seen is True
    assert _props(db, sslva) == []
    db.rollback()


def test_shared_root_intermediate_do_not_leak_to_other_domain(db, monkeypatch):
    """abc.com (A,B,C) ve fff.com.tr (A,B,D). D yenilenince yalnız fff için D→D' çıkar;
    abc.com'a ve A/B'ye (root/intermediate → leaf) öneri ÇIKMAZ."""
    (a, ak), (b, bk), c = _chain("shared", leaf_cn="abc.test")
    d, _ = certgen.make_leaf(b, bk, "fff.test", not_before=datetime(2026, 1, 1))
    d2, _ = certgen.make_leaf(b, bk, "fff.test", not_before=datetime(2026, 7, 1))
    A = _add(db, a, "Root")
    B = _add(db, b, "Intermediate", parent=A)
    C = _add(db, c, "Leaf", parent=B)
    D = _add(db, d, "Leaf", parent=B)
    D2 = _add(db, d2, "Leaf", parent=B)
    abc = _domain(db, "abc.test", A, B, C)
    fff = _domain(db, "fff.test", A, B, D)

    _live(db, fff, monkeypatch, d2, b)

    props = _props(db, abc, fff)
    assert [(p.kind, p.old_cert_id, p.new_cert_id, p.domain_id) for p in props] == \
        [("transfer", D.id, D2.id, fff.id)]
    assert _props(db, abc) == []
    assert not any(p.old_cert_id in (A.id, B.id) for p in props)
    db.rollback()


def test_unmapped_levels_become_add_proposals_including_derived_root(db, monkeypatch):
    """Boş domain: sunulan leaf + intermediate ve envanterden türetilen root için 3 EKLEME
    önerisi; hiçbir eşleme kendiliğinden eklenmez. Onay → eşleme eklenir."""
    (r, rk), (i, ik), leaf = _chain("addall")
    R = _add(db, r, "Root")
    I = _add(db, i, "Intermediate", parent=R)
    L = _add(db, leaf, "Leaf", parent=I)
    dom = _domain(db, "addall.test")

    _live(db, dom, monkeypatch, leaf, i)

    props = _props(db, dom)
    assert sorted((p.kind, p.new_cert_id) for p in props) == \
        sorted([("server_add", R.id), ("server_add", I.id), ("server_add", L.id)])
    assert all(p.old_cert_id == p.new_cert_id and p.live_seen for p in props)
    assert db.query(m.CertificateDomainMap).filter_by(domain_id=dom.id).count() == 0

    leaf_prop = next(p for p in props if p.new_cert_id == L.id)
    leaf_prop.status = "approved"
    renewal.apply_proposal(db, leaf_prop, "tester", None)
    assert leaf_prop.status == "applied"
    assert db.query(m.CertificateDomainMap).filter_by(
        domain_id=dom.id, certificate_id=L.id, mapping_type="server").count() == 1
    db.rollback()


def test_extra_bound_cert_not_served_becomes_remove_proposal(db, monkeypatch):
    """Domaine erişildi, zincir alındı: bağlı ama sunulmayan leaf → KALDIRMA önerisi.
    Root sunulmadığından (yalnız türetildi) root için kaldırma önerisi ÜRETİLMEZ."""
    (r, rk), (i, ik), leaf = _chain("remove")
    stray, _ = certgen.make_leaf(i, ik, "stray.remove.test", not_before=datetime(2025, 1, 1))
    other_root, _ = certgen.make_ca("remove Other Root", not_before=datetime(2020, 1, 1))
    R = _add(db, r, "Root")
    R2 = _add(db, other_root, "Root")
    I = _add(db, i, "Intermediate", parent=R)
    L = _add(db, leaf, "Leaf", parent=I)
    S = _add(db, stray, "Leaf", parent=I)
    dom = _domain(db, "remove.test", R, R2, I, L, S)

    _live(db, dom, monkeypatch, leaf, i)

    props = _props(db, dom)
    assert [(p.kind, p.new_cert_id) for p in props] == [("server_remove", S.id)]

    props[0].status = "approved"
    renewal.apply_proposal(db, props[0], "tester", None)
    assert db.query(m.CertificateDomainMap).filter_by(domain_id=dom.id, certificate_id=S.id).count() == 0
    assert db.get(m.Certificate, S.id).is_active is True  # kaldırma pasife ALMAZ
    db.rollback()


def test_intermediate_rotation_is_same_level_transfer(db, monkeypatch):
    """Intermediate değişti (B → B'): değişiklik önerisi aynı seviyede (intermediate → intermediate)."""
    r, rk = certgen.make_ca("introt Root", not_before=datetime(2020, 1, 1))
    b, bk = certgen.make_intermediate(r, rk, "introt CA", not_before=datetime(2021, 1, 1))
    b2, b2k = certgen.make_intermediate(r, rk, "introt CA", not_before=datetime(2026, 1, 1))
    leaf, _ = certgen.make_leaf(b2, b2k, "introt.test", not_before=datetime(2026, 2, 1))
    R = _add(db, r, "Root")
    B = _add(db, b, "Intermediate", parent=R)
    B2 = _add(db, b2, "Intermediate", parent=R)
    L = _add(db, leaf, "Leaf", parent=B2)
    dom = _domain(db, "introt.test", R, B, L)

    _live(db, dom, monkeypatch, leaf, b2)

    props = _props(db, dom)
    assert [(p.kind, p.old_cert_id, p.new_cert_id) for p in props] == [("transfer", B.id, B2.id)]
    db.rollback()


def test_cross_type_never_proposed_or_applied(db):
    """Hiçbir yol root/intermediate → leaf önerisi üretmez; eski sürümden kalan böyle bir
    öneri onaylansa bile UYGULANMAZ (iptal edilir)."""
    (r, rk), (i, ik), leaf = _chain("xtype")
    R = _add(db, r, "Root")
    I = _add(db, i, "Intermediate", parent=R)
    L = _add(db, leaf, "Leaf", parent=I)
    dom = _domain(db, "xtype.test", R, I)

    assert renewal.propose(db, L, R, username="t", request=None, via="manual") == []
    assert renewal.propose(db, L, I, username="t", request=None, via="live-check",
                           domain_id=dom.id) == []
    assert renewal.propose_attach_transfer(db, L, I, dom, "server", username="t", request=None) is None

    stale = m.TransferProposal(old_cert_id=R.id, new_cert_id=L.id, domain_id=dom.id,
                               mapping_type="server", kind="transfer", status="approved", via="attach")
    db.add(stale)
    db.flush()
    renewal.apply_proposal(db, stale, "tester", None)
    assert stale.status == "cancelled"
    assert db.get(m.Certificate, R.id).superseded_by_id is None
    assert db.query(m.CertificateDomainMap).filter_by(domain_id=dom.id, certificate_id=R.id).count() == 1
    db.rollback()


def test_manual_supersede_rejects_cross_type(client, auth_headers):
    ca, ca_key = certgen.make_ca("Manual Xtype CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "manual-xtype.test")
    r = client.post("/api/certificates/import", headers=auth_headers,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    ids = {c["cert_type"]: c["id"] for c in r.json()}
    resp = client.post(f"/api/certificates/{ids['leaf']}/supersede/{ids['root']}", headers=auth_headers)
    assert resp.status_code == 400 and "aynı seviyedeki" in resp.json()["detail"]


def test_vault_and_file_import_do_not_propose(client, auth_headers):
    ca, ca_key = certgen.make_ca("NoPropose CA")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "nopropose.test", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "nopropose.test", key=key, not_before=datetime(2026, 6, 1))

    def imp(pem, **data):
        return client.post("/api/certificates/import", headers=auth_headers,
                           files={"file": ("c.pem", pem.encode(), "application/x-pem-file")}, data=data)

    v1_id = next(c["id"] for c in imp(certgen.pem(v1) + certgen.pem(ca)).json() if c["cert_type"] == "leaf")
    dom = client.post("/api/domains", headers=auth_headers, json={"domain": "nopropose.test"}).json()["id"]
    client.post(f"/api/domains/{dom}/certificates", headers=auth_headers,
                json={"certificate_id": v1_id, "mapping_type": "server"})
    v2_id = imp(certgen.pem(v2), supersede="true").json()[0]["id"]
    pend = client.get("/api/proposals", headers=auth_headers, params={"status": "pending"}).json()
    assert not any(p["new_cert_id"] == v2_id for p in pend)


def test_client_attach_of_different_level_is_not_a_transfer(client, auth_headers):
    """Client (trusted) eşlemede root bağlıyken leaf eklemek devir DEĞİL — doğrudan eklenir."""
    ca, ca_key = certgen.make_ca("Client Level CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "client-level.test")
    r = client.post("/api/certificates/import", headers=auth_headers,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    ids = {c["cert_type"]: c["id"] for c in r.json()}
    dom = client.post("/api/domains", headers=auth_headers, json={"domain": "client-level.test"}).json()["id"]
    for cid in (ids["root"], ids["leaf"]):
        resp = client.post(f"/api/domains/{dom}/certificates", headers=auth_headers,
                           json={"certificate_id": cid, "mapping_type": "client"})
        assert resp.status_code == 200, resp.text
    pend = client.get("/api/proposals", headers=auth_headers, params={"status": "pending"}).json()
    assert not any(p["domain_id"] == dom for p in pend)


def test_cert_type_filter_is_collation_independent(db):
    """LOWER() kullanılmaz: ham 'Intermediate' / 'INTERMEDIATE' intermediate sayılır, leaf sayılmaz."""
    rows = []
    for raw in ("Intermediate", "INTERMEDIATE", "intermediate", "Leaf", None):
        c = m.Certificate(name=f"ctf-{raw}", cert_type=raw)
        db.add(c)
        rows.append(c)
    db.flush()
    ids = [c.id for c in rows]
    inter = {c.id for c in db.query(m.Certificate).filter(
        m.Certificate.id.in_(ids), cert_type_filter(m.Certificate.cert_type, "intermediate"))}
    leaf = {c.id for c in db.query(m.Certificate).filter(
        m.Certificate.id.in_(ids), cert_type_filter(m.Certificate.cert_type, "leaf"))}
    assert inter == set(ids[:3])
    assert leaf == set(ids[3:])
    db.rollback()
