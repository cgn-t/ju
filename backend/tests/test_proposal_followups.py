"""Değişiklik talebi anomalileri (v3.6.3) — regresyon.

  Y1  Eski leaf elle kaldırılıp devir onaylanınca yeni leaf bağlanır (yuva kontrolü tip bazlı).
  T1  Domain devri uygulanınca o domaini hedefleyen mTLS bağımlılığına değişiklik talebi açılır.
  T2  Domain devri uygulanınca eski cert'i güvenen uygulamaya trusted_add önerisi açılır.
  Z1  Zincir içe aktarma: iki katmanlı yeni ara CA → eskiye TEK halef + kalan için EKLEME.
  Z2  Zincir içe aktarma: bağlılardan biri hâlâ sunuluyorsa fazladan olan için KALDIRMA.
"""

from datetime import datetime

from app.api import domains as domains_api
from app.db import models as m
from app.db.session import SessionLocal
from tests import certgen
from tests.test_proposal_flows_regression import (
    _active, _attach, _cid, _domain, _import, _live, _pending, _server,
)


def _approve(client, h, pid):
    r = client.post(f"/api/proposals/{pid}/approve", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def _chain(tag):
    r, rk = certgen.make_ca(f"{tag} Root", not_before=datetime(2020, 1, 1))
    i, ik = certgen.make_intermediate(r, rk, f"{tag} CA", not_before=datetime(2025, 1, 1))
    l1, _ = certgen.make_leaf(i, ik, f"{tag.lower()}.test", not_before=datetime(2026, 1, 1))
    l2, _ = certgen.make_leaf(i, ik, f"{tag.lower()}.test", not_before=datetime(2026, 6, 1))
    return r, i, l1, l2


def _names(ids):
    db = SessionLocal()
    try:
        return sorted(db.get(m.Certificate, c).name for c in ids)
    finally:
        db.close()


def _all_pending(client, h):
    return client.get("/api/proposals", headers=h, params={"status": "pending"}).json()


def test_Y1_removed_old_leaf_then_approve_binds_new_leaf(client, auth_headers):
    h = auth_headers
    r, i, l1, l2 = _chain("Y1")
    _import(client, h, r, i, l1, l2)
    dom = _domain(client, h, "y1.test")
    l1id, l2id = _cid(client, h, l1), _cid(client, h, l2)
    _attach(client, h, dom, l1id)  # leaf + intermediate + root
    rr = client.post(f"/api/domains/{dom}/certificates", headers=h,
                     json={"certificate_id": l2id, "mapping_type": "server"})
    assert rr.status_code == 202, rr.text
    pid = rr.json()["proposal_ids"][0]
    d = client.delete(f"/api/domains/{dom}/certificates/{l1id}", headers=h,
                      params={"mapping_type": "server"})
    assert d.status_code == 200, d.text

    assert _approve(client, h, pid)["status"] == "applied"
    assert l2id in _server(client, h, dom), "intermediate/root yuvayı dolu göstermemeli"
    assert not _active(l1id)


def _app_with_dependency(dom, cert_id, name):
    db = SessionLocal()
    try:
        app = m.Application(app_name=name)
        db.add(app)
        db.flush()
        dep = m.AppDependency(app_id=app.id, target_domain_id=dom, client_cert_id=cert_id)
        db.add(dep)
        db.commit()
        return app.id, dep.id
    finally:
        db.close()


def test_T1_live_renewal_proposes_mtls_dependency_after_domain_apply(client, auth_headers,
                                                                    monkeypatch):
    h = auth_headers
    r, i, l1, l2 = _chain("T1")
    _import(client, h, r, i, l1)
    dom = _domain(client, h, "t1.test")
    l1id = _cid(client, h, l1)
    _attach(client, h, dom, l1id)
    _, dep_id = _app_with_dependency(dom, l1id, "T1 App")

    _live(client, h, monkeypatch, dom, l2, i)
    l2id = _cid(client, h, l2)
    (prop,) = _pending(client, h, dom)
    assert not [p for p in _all_pending(client, h) if p["app_dependency_id"] == dep_id]
    _approve(client, h, prop["id"])

    dep_props = [p for p in _all_pending(client, h) if p["app_dependency_id"] == dep_id]
    assert len(dep_props) == 1 and dep_props[0]["new_cert_id"] == l2id
    assert dep_props[0]["via"] == "live-check"
    assert _active(l1id), "bağımlılık devri onaylanana kadar eski aktif kalmalı"

    _approve(client, h, dep_props[0]["id"])
    db = SessionLocal()
    try:
        assert db.get(m.AppDependency, dep_id).client_cert_id == l2id
    finally:
        db.close()
    assert not _active(l1id)


def test_T1b_dependency_on_other_domain_is_not_touched(client, auth_headers, monkeypatch):
    """Yalnız devri uygulanan domaini hedefleyen bağımlılık önerilir."""
    h = auth_headers
    r, i, l1, l2 = _chain("T1B")
    _import(client, h, r, i, l1)
    dom = _domain(client, h, "t1b.test")
    other = _domain(client, h, "t1b-other.test")
    l1id = _cid(client, h, l1)
    _attach(client, h, dom, l1id)
    _, dep_id = _app_with_dependency(other, l1id, "T1B App")

    _live(client, h, monkeypatch, dom, l2, i)
    (prop,) = _pending(client, h, dom)
    _approve(client, h, prop["id"])
    assert not [p for p in _all_pending(client, h) if p["app_dependency_id"] == dep_id]


def test_T2_live_renewal_proposes_trusted_add_after_domain_apply(client, auth_headers, monkeypatch):
    h = auth_headers
    r, i, l1, l2 = _chain("T2")
    _import(client, h, r, i, l1)
    dom = _domain(client, h, "t2.test")
    l1id = _cid(client, h, l1)
    _attach(client, h, dom, l1id)
    db = SessionLocal()
    try:
        app = m.Application(app_name="T2 App")
        db.add(app)
        db.flush()
        db.add(m.ApplicationTrustedCert(app_id=app.id, cert_id=l1id))
        db.commit()
        app_id = app.id
    finally:
        db.close()

    _live(client, h, monkeypatch, dom, l2, i)
    (prop,) = _pending(client, h, dom)
    _approve(client, h, prop["id"])

    l2id = _cid(client, h, l2)
    tr = [p for p in _all_pending(client, h) if p["kind"] == "trusted_add" and p["app_id"] == app_id]
    assert len(tr) == 1 and tr[0]["new_cert_id"] == l2id
    _approve(client, h, tr[0]["id"])
    db = SessionLocal()
    try:
        assert {t.cert_id for t in db.query(m.ApplicationTrustedCert).filter_by(app_id=app_id)} \
            == {l1id, l2id}
    finally:
        db.close()


def test_Z1_import_chain_two_new_intermediates_single_successor_plus_add(client, auth_headers,
                                                                        monkeypatch):
    h = auth_headers
    ro, rok = certgen.make_ca("Z1 OldRoot", not_before=datetime(2020, 1, 1))
    io, iok = certgen.make_intermediate(ro, rok, "Z1 OldCA", not_before=datetime(2024, 1, 1))
    lo, _ = certgen.make_leaf(io, iok, "z1.test", not_before=datetime(2025, 1, 1))
    _import(client, h, ro, io, lo)
    dom = _domain(client, h, "z1.test")
    _attach(client, h, dom, _cid(client, h, lo))

    rn, rnk = certgen.make_ca("Z1 NewRoot", not_before=datetime(2020, 1, 1))
    ia, iak = certgen.make_intermediate(rn, rnk, "Z1 NewCA A", not_before=datetime(2025, 1, 1))
    ib, ibk = certgen.make_intermediate(ia, iak, "Z1 NewCA B", not_before=datetime(2025, 1, 1))
    ln, _ = certgen.make_leaf(ib, ibk, "z1.test", not_before=datetime(2026, 1, 1))
    monkeypatch.setattr(domains_api, "fetch_served_chain", lambda host, port: [ln, ib, ia, rn])
    rr = client.post(f"/api/domains/{dom}/import-chain", headers=h)
    assert rr.status_code == 200, rr.text
    assert rr.json()["added"] == ["Z1 NewCA A"]

    props = _pending(client, h, dom)
    old_ca = _cid(client, h, io)
    assert len([p for p in props if p["old_cert_id"] == old_ca]) == 1, "eski CA'ya tek halef"
    assert [p["kind"] for p in props if p["new_cert_id"] == _cid(client, h, ia)] == ["server_add"]

    for p in props:
        _approve(client, h, p["id"])
    assert _names(_server(client, h, dom)) == ["Z1 NewCA A", "Z1 NewCA B", "Z1 NewRoot", "z1.test"]
    assert _cid(client, h, ln) in _server(client, h, dom)


def test_Z2_import_chain_matched_level_proposes_remove_not_transfer(client, auth_headers,
                                                                   monkeypatch):
    h = auth_headers
    r, rk = certgen.make_ca("Z2 Root", not_before=datetime(2020, 1, 1))
    i, ik = certgen.make_intermediate(r, rk, "Z2 CA", not_before=datetime(2025, 1, 1))
    lf, _ = certgen.make_leaf(i, ik, "z2.test", not_before=datetime(2026, 1, 1))
    xr, xrk = certgen.make_ca("Z2 OtherRoot", not_before=datetime(2020, 1, 1))
    xi, _ = certgen.make_intermediate(xr, xrk, "Z2 StrayCA", not_before=datetime(2025, 1, 1))
    _import(client, h, r, i, lf, xr, xi)
    dom = _domain(client, h, "z2.test")
    _attach(client, h, dom, _cid(client, h, lf))
    db = SessionLocal()
    try:
        db.add(m.CertificateDomainMap(certificate_id=_cid(client, h, xi), domain_id=dom,
                                      mapping_type="server"))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(domains_api, "fetch_served_chain", lambda host, port: [lf, i, r])
    rr = client.post(f"/api/domains/{dom}/import-chain", headers=h)
    assert rr.status_code == 200, rr.text
    props = _pending(client, h, dom)
    assert [(p["kind"], p["old_cert_id"]) for p in props] == [("server_remove", _cid(client, h, xi))]
    _approve(client, h, props[0]["id"])
    assert _names(_server(client, h, dom)) == ["Z2 CA", "Z2 Root", "z2.test"]
