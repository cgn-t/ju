"""Domain detayındaki bağlı sertifikalar zincir sırasıyla döner: server → client; her grupta
leaf → intermediate → root — eşlemelerin eklenme sırasından bağımsız (ör. zincir içe aktarmada
root, intermediate'tan önce bağlanabilir)."""

from datetime import datetime

from app.db import models as m
from app.db.session import SessionLocal
from tests import certgen
from tests.test_proposal_flows_regression import _chain, _cid, _domain, _import


def test_mapped_certs_sorted_leaf_intermediate_root(client, auth_headers):
    h = auth_headers
    (r, _), (i, _), leaf = _chain("ordx", leaf_nb=datetime(2020, 6, 1))  # süresi geçmiş leaf
    client_leaf, _ = certgen.make_ca("ordx Client CA", not_before=datetime(2024, 1, 1))
    _import(client, h, leaf, i, r, client_leaf)
    dom = _domain(client, h, "ordx.test")

    # Bilerek ters sıra: client, root, intermediate, leaf (legacy büyük harfli tip ile)
    db = SessionLocal()
    try:
        for cert, mtype in ((client_leaf, "client"), (r, "server"), (i, "server"), (leaf, "server")):
            db.add(m.CertificateDomainMap(certificate_id=_cid(client, h, cert), domain_id=dom, mapping_type=mtype))
        db.get(m.Certificate, _cid(client, h, r)).cert_type = "Root"
        db.commit()
    finally:
        db.close()

    got = client.get(f"/api/domains/{dom}", headers=h).json()["certificates"]
    assert [(c["mapping_type"], c["cert_type"]) for c in got] == [
        ("server", "leaf"), ("server", "intermediate"), ("server", "root"), ("client", "root")]

    listed = next(d for d in client.get("/api/domains", headers=h, params={"search": "ordx.test"}).json()
                  if d["id"] == dom)
    assert [(c["mapping_type"], c["cert_type"]) for c in listed["certificates"]] == \
        [(c["mapping_type"], c["cert_type"]) for c in got], "liste ve detay aynı sırada olmalı"


def test_two_intermediates_follow_chain_not_name(client, auth_headers):
    """İki katmanlı ara-CA: leaf'i imzalayan (alt) intermediate, üsttekinden önce gelir —
    adları alfabetik olarak ters sırada olsa bile."""
    h = auth_headers
    r, rk = certgen.make_ca("ordy Root", not_before=datetime(2020, 1, 1))
    top, tk = certgen.make_intermediate(r, rk, "AAA ordy Upper CA", not_before=datetime(2025, 1, 1))
    low, lk = certgen.make_intermediate(top, tk, "ZZZ ordy Issuing CA", not_before=datetime(2025, 1, 1))
    leaf, _ = certgen.make_leaf(low, lk, "ordy.test", not_before=datetime(2026, 1, 1))
    _import(client, h, leaf, low, top, r)
    dom = _domain(client, h, "ordy.test")
    db = SessionLocal()
    try:
        for cert in (r, top, low, leaf):
            db.add(m.CertificateDomainMap(certificate_id=_cid(client, h, cert), domain_id=dom, mapping_type="server"))
        db.commit()
    finally:
        db.close()
    names = [c["name"] for c in client.get(f"/api/domains/{dom}", headers=h).json()["certificates"]]
    assert names == ["ordy.test", "ZZZ ordy Issuing CA", "AAA ordy Upper CA", "ordy Root"]
