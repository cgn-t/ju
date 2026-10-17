"""Devir önerisi akışları — uçtan uca REGRESYON seti (v3.5.0 öneri modeli).

Gerçek HTTP uçları üzerinden: içe aktarma → domain/eşleme → canlı doğrulama (sunulan zincir
monkeypatch ile) → /api/proposals → onay/red → eşleme ve sertifika durumunun doğrulanması.

  CANLI DOĞRULAMA  L1–L15  yalnız kontrol edilen domain; ekleme / değişiklik / kaldırma
  ELLE DEVİR       M1–M2   tüm bağlantılara yayılır; reddi bilinçli olarak yeniden açar
  ZİNCİR İÇE AKT.  I1      domain ekranından — yalnız o domain kapsamı
  ÖNERİ AÇMAYAN    N1      dosya içe aktarma / Vault / açılış öneri üretmez
  ÖNERİ HATTI      P1–P3   yetki, audit ve mail etiketleri yeni türlerde
"""

import json
from datetime import datetime

import pytest

from app.db import models as m
from app.db.session import SessionLocal
from app.services import live_check, notifier
from tests import certgen


# ---------------------------------------------------------------- yardımcılar
def _chain(tag, *, root=None, leaf_cn=None, leaf_nb=datetime(2026, 1, 1)):
    if root is None:
        root = certgen.make_ca(f"{tag} Root", not_before=datetime(2020, 1, 1))
    r, rk = root
    i, ik = certgen.make_intermediate(r, rk, f"{tag} CA", not_before=datetime(2025, 1, 1))
    leaf, _ = certgen.make_leaf(i, ik, leaf_cn or f"{tag}.test", not_before=leaf_nb)
    return (r, rk), (i, ik), leaf


def _import(client, h, *certs):
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", "".join(certgen.pem(c) for c in certs).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return {c["fingerprint_sha256"]: c["id"] for c in r.json()}


def _id(cert, ids):
    return ids[cert_fp(cert)]


def cert_fp(cert):
    from app.services.cert_parser import parse_x509
    return parse_x509(cert).fingerprint_sha256


def _cid(client, h, cert):
    """Envanterdeki sertifikanın id'si (parmak izinden)."""
    db = SessionLocal()
    try:
        row = db.query(m.Certificate).filter(m.Certificate.fingerprint_sha256 == cert_fp(cert)).first()
        return row.id if row else None
    finally:
        db.close()


def _domain(client, h, name, sy_team_id=None):
    body = {"domain": name}
    if sy_team_id:
        body["sy_team_id"] = sy_team_id
    r = client.post("/api/domains", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(client, h, dom, cid, mapping_type="server"):
    r = client.post(f"/api/domains/{dom}/certificates", headers=h,
                    json={"certificate_id": cid, "mapping_type": mapping_type})
    assert r.status_code == 200, r.text


def _db_map(dom, cid, mapping_type="server"):
    """API'nin çakışma kuralını atlayarak doğrudan eşleme (canlı veriyi taklit)."""
    db = SessionLocal()
    try:
        db.add(m.CertificateDomainMap(certificate_id=cid, domain_id=dom, mapping_type=mapping_type))
        db.commit()
    finally:
        db.close()


def _live(client, h, monkeypatch, dom, *served, error=None):
    def fake(host, port):
        if error:
            raise error
        return list(served)
    monkeypatch.setattr(live_check, "fetch_served_chain", fake)
    r = client.post(f"/api/domains/{dom}/live-check", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _pending(client, h, *doms):
    return sorted((p for p in client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
                   if p["domain_id"] in doms), key=lambda p: p["id"])


def _all_props(*doms):
    db = SessionLocal()
    try:
        return db.query(m.TransferProposal).filter(m.TransferProposal.domain_id.in_(doms)).all()
    finally:
        db.close()


def _server(client, h, dom):
    d = client.get(f"/api/domains/{dom}", headers=h).json()
    return sorted(c["certificate_id"] for c in d["certificates"] if c["mapping_type"] == "server")


def _active(cid):
    db = SessionLocal()
    try:
        return db.get(m.Certificate, cid).is_active
    finally:
        db.close()


def _approve(client, h, pid):
    r = client.post(f"/api/proposals/{pid}/approve", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _reject(client, h, pid):
    assert client.post(f"/api/proposals/{pid}/reject", headers=h).status_code == 200


def _sig(props):
    return sorted((p["kind"], p["old_cert_id"], p["new_cert_id"], p["domain_id"]) for p in props)


@pytest.fixture()
def h(auth_headers):
    return auth_headers


# ======================================================== CANLI DOĞRULAMA
def test_L1_match_produces_no_proposal(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl1")
    _import(client, h, leaf, i, r)
    dom = _domain(client, h, "regl1.test")
    _attach(client, h, dom, _cid(client, h, leaf))
    assert len(_server(client, h, dom)) == 3  # leaf + intermediate + root zincirle bağlandı

    out = _live(client, h, monkeypatch, dom, leaf, i)
    assert out["live_check_status"] == "match"
    assert _pending(client, h, dom) == []


def test_L2_leaf_renewal_proposes_only_for_checked_domain_then_approve(client, h, monkeypatch):
    """SSLVA: X web ve sslva'ya bağlı; web Y sunar → yalnız web için X→Y. Onay → web'de Y;
    X sslva'da bağlı olduğundan AKTİF kalır. Tekrar kontrol → match, yeni öneri yok."""
    (r, rk), (i, ik), x = _chain("regl2", leaf_cn="web.regl2.test")
    y, _ = certgen.make_leaf(i, ik, "*.regl2.test", not_before=datetime(2026, 6, 1))
    _import(client, h, x, i, r)
    _import(client, h, y)
    X, Y = _cid(client, h, x), _cid(client, h, y)
    web, sslva = _domain(client, h, "web.regl2.test"), _domain(client, h, "sslva.regl2.test")
    _attach(client, h, web, X)
    _attach(client, h, sslva, X)

    out = _live(client, h, monkeypatch, web, y, i)
    assert out["live_check_status"] == "mismatch"
    props = _pending(client, h, web, sslva)
    assert _sig(props) == [("transfer", X, Y, web)]
    assert props[0]["via"] == "live-check" and props[0]["live_seen"] is True
    assert props[0]["created_by"] == "system", "otomatik öneri 'Sistem' olarak görünmeli"

    _approve(client, h, props[0]["id"])
    assert Y in _server(client, h, web) and X not in _server(client, h, web)
    assert X in _server(client, h, sslva), "sslva'ya dokunulmamalı"
    assert _active(X) is True, "X hâlâ sslva'ya bağlı → aktif kalır"
    assert _live(client, h, monkeypatch, web, y, i)["live_check_status"] == "match"
    assert _pending(client, h, web, sslva) == []


def test_L3_shared_root_and_intermediate_do_not_leak(client, h, monkeypatch):
    """abc (A,B,C) ve fff (A,B,D). fff'te D→D2: yalnız fff; A/B için öneri yok; abc değişmez.
    Onay → D'nin bağlantısı kalmadığından pasife alınır."""
    (a, ak), (b, bk), c = _chain("regl3", leaf_cn="abc.regl3.test")
    d, _ = certgen.make_leaf(b, bk, "fff.regl3.test", not_before=datetime(2026, 1, 1))
    d2, _ = certgen.make_leaf(b, bk, "fff.regl3.test", not_before=datetime(2026, 7, 1))
    _import(client, h, c, b, a)
    _import(client, h, d)
    _import(client, h, d2)
    A, B, C, D, D2 = (_cid(client, h, x) for x in (a, b, c, d, d2))
    abc, fff = _domain(client, h, "abc.regl3.test"), _domain(client, h, "fff.regl3.test")
    _attach(client, h, abc, C)
    _attach(client, h, fff, D)
    abc_before = _server(client, h, abc)

    _live(client, h, monkeypatch, fff, d2, b)
    props = _pending(client, h, abc, fff)
    assert _sig(props) == [("transfer", D, D2, fff)]
    assert not any(p["old_cert_id"] in (A, B) for p in props)

    _approve(client, h, props[0]["id"])
    assert _server(client, h, abc) == abc_before
    assert sorted(_server(client, h, fff)) == sorted([A, B, D2])
    assert _active(D) is False


def test_L4_unmapped_levels_become_add_proposals_then_match(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl4")
    _import(client, h, leaf, i, r)
    R, I, L = (_cid(client, h, x) for x in (r, i, leaf))
    dom = _domain(client, h, "regl4.test")

    out = _live(client, h, monkeypatch, dom, leaf, i)
    props = _pending(client, h, dom)
    assert _sig(props) == sorted([("server_add", R, R, dom), ("server_add", I, I, dom),
                                  ("server_add", L, L, dom)])
    assert _server(client, h, dom) == [], "eşleme kendiliğinden EKLENMEMELİ"
    assert sorted(json.loads(out["live_check_detail"])["proposed_add"]) == sorted(
        [p["new_cert_name"] for p in props])

    for p in props:
        _approve(client, h, p["id"])
    assert _server(client, h, dom) == sorted([R, I, L])
    assert _live(client, h, monkeypatch, dom, leaf, i)["live_check_status"] == "match"
    assert _pending(client, h, dom) == []


def test_L5_bound_but_not_served_becomes_remove_then_applied(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl5")
    stray, _ = certgen.make_leaf(i, ik, "stray.regl5.test", not_before=datetime(2025, 1, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, stray)
    L, S = _cid(client, h, leaf), _cid(client, h, stray)
    dom = _domain(client, h, "regl5.test")
    _attach(client, h, dom, L)
    _db_map(dom, S)

    _live(client, h, monkeypatch, dom, leaf, i)
    props = _pending(client, h, dom)
    assert _sig(props) == [("server_remove", S, S, dom)]

    _approve(client, h, props[0]["id"])
    assert S not in _server(client, h, dom)
    assert _active(S) is True, "kaldırma sertifikayı pasife ALMAZ"


def test_L6_root_not_served_never_removed_but_derived_root_rotation_is_change(client, h, monkeypatch):
    """Sunucu root göndermez. Bağlı fazladan bir root için kaldırma ÖNERİLMEZ (kanıt yok)."""
    (r, rk), (i, ik), leaf = _chain("regl6")
    other_root, _ = certgen.make_ca("regl6 Other Root", not_before=datetime(2020, 1, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, other_root)
    O = _cid(client, h, other_root)
    dom = _domain(client, h, "regl6.test")
    _attach(client, h, dom, _cid(client, h, leaf))
    _db_map(dom, O)

    _live(client, h, monkeypatch, dom, leaf, i)  # root sunulmadı
    assert _pending(client, h, dom) == []


def test_L7_served_root_rotation_and_extra_served_level(client, h, monkeypatch):
    """Sunucu root'u da gönderiyor: tüm zincir yeni CA'ya geçmiş → her seviye kendi içinde
    değişiklik (leaf→leaf, int→int, root→root); farklı seviyeler arasında öneri yok."""
    (r, rk), (i, ik), leaf = _chain("regl7old")
    (r2, rk2), (i2, ik2), leaf2 = _chain("regl7new", leaf_cn="regl7old.test", leaf_nb=datetime(2026, 8, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, leaf2, i2, r2)
    R, I, L, R2, I2, L2 = (_cid(client, h, x) for x in (r, i, leaf, r2, i2, leaf2))
    dom = _domain(client, h, "regl7old.test")
    _attach(client, h, dom, L)

    _live(client, h, monkeypatch, dom, leaf2, i2, r2)
    props = _pending(client, h, dom)
    assert _sig(props) == sorted([("transfer", R, R2, dom), ("transfer", I, I2, dom),
                                  ("transfer", L, L2, dom)])


def test_L8_L9_unreachable_and_wildcard_produce_nothing(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl8")
    _import(client, h, leaf, i, r)
    L = _cid(client, h, leaf)
    dom = _domain(client, h, "regl8.test")
    _attach(client, h, dom, L)
    out = _live(client, h, monkeypatch, dom, error=OSError("bağlantı reddedildi"))
    assert out["live_check_status"] == "unreachable"
    wild = _domain(client, h, "*.regl8.test")
    _db_map(wild, L)
    assert _live(client, h, monkeypatch, wild, leaf, i)["live_check_status"] == "not_checkable"
    assert _pending(client, h, dom, wild) == []


def test_L10_L11_idempotent_and_rejection_is_permanent(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl10")
    y, _ = certgen.make_leaf(i, ik, "regl10.test", not_before=datetime(2026, 9, 1))
    stray, _ = certgen.make_leaf(i, ik, "stray.regl10.test", not_before=datetime(2025, 1, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, y)
    _import(client, h, stray)
    dom = _domain(client, h, "regl10.test")
    _attach(client, h, dom, _cid(client, h, leaf))
    empty = _domain(client, h, "empty.regl10.test")

    _live(client, h, monkeypatch, dom, y, i)
    _live(client, h, monkeypatch, empty, y, i)
    first = _pending(client, h, dom, empty)
    _live(client, h, monkeypatch, dom, y, i)
    _live(client, h, monkeypatch, empty, y, i)
    assert _sig(_pending(client, h, dom, empty)) == _sig(first), "tekrar çalıştırma mükerrer üretmemeli"

    for p in first:
        _reject(client, h, p["id"])
    _live(client, h, monkeypatch, dom, y, i)
    _live(client, h, monkeypatch, empty, y, i)
    assert _pending(client, h, dom, empty) == [], "reddedilen öneri otomatik yolla geri gelmemeli"


def test_L12_L13_inactive_bound_and_client_mappings_untouched(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl12")
    old, _ = certgen.make_leaf(i, ik, "regl12.test", not_before=datetime(2025, 1, 1))
    trusted, _ = certgen.make_leaf(i, ik, "client.regl12.test", not_before=datetime(2025, 1, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, old)
    _import(client, h, trusted)
    L, OLD, T = _cid(client, h, leaf), _cid(client, h, old), _cid(client, h, trusted)
    dom = _domain(client, h, "regl12.test")
    _db_map(dom, OLD)
    _attach(client, h, dom, T, "client")
    db = SessionLocal()
    try:
        db.get(m.Certificate, OLD).is_active = False
        db.commit()
    finally:
        db.close()

    _live(client, h, monkeypatch, dom, leaf, i)
    props = _pending(client, h, dom)
    assert not any(OLD in (p["old_cert_id"], p["new_cert_id"]) for p in props), "pasif bağlı yok sayılır"
    assert not any(T in (p["old_cert_id"], p["new_cert_id"]) for p in props), "client eşlemeye dokunulmaz"
    assert ("server_add", L, L, dom) in _sig(props)


def test_L14_unknown_served_chain_is_inventoried_then_proposed(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regl14")
    dom = _domain(client, h, "regl14.test")
    _live(client, h, monkeypatch, dom, leaf, i)
    L, I = _cid(client, h, leaf), _cid(client, h, i)
    assert L and I, "sunulan zincir envantere eklenmeli"
    db = SessionLocal()
    try:
        assert db.get(m.Certificate, L).source == "live"
    finally:
        db.close()
    kinds = {(p["kind"], p["new_cert_id"]) for p in _pending(client, h, dom)}
    assert {("server_add", L), ("server_add", I)} <= kinds


def test_L15_capitalized_legacy_types_behave_like_canonical(client, h, monkeypatch):
    """Prod'daki gibi 'Root' / 'Intermediate' / 'Leaf' yazımları: tipler karışmaz."""
    (r, rk), (i, ik), x = _chain("regl15", leaf_cn="abc.regl15.test")
    d2, _ = certgen.make_leaf(i, ik, "fff.regl15.test", not_before=datetime(2026, 7, 1))
    d, _ = certgen.make_leaf(i, ik, "fff.regl15.test", not_before=datetime(2026, 1, 1))
    _import(client, h, x, i, r)
    _import(client, h, d)
    _import(client, h, d2)
    A, B, C, D, D2 = (_cid(client, h, c) for c in (r, i, x, d, d2))
    db = SessionLocal()
    try:
        for cid, raw in ((A, "Root"), (B, "Intermediate"), (C, "Leaf"), (D, "Leaf"), (D2, "Leaf")):
            db.get(m.Certificate, cid).cert_type = raw
        db.commit()
    finally:
        db.close()
    abc, fff = _domain(client, h, "abc.regl15.test"), _domain(client, h, "fff.regl15.test")
    for dom, leaf_id in ((abc, C), (fff, D)):
        for cid in (A, B, leaf_id):
            _db_map(dom, cid)

    _live(client, h, monkeypatch, fff, d2, i)
    assert _sig(_pending(client, h, abc, fff)) == [("transfer", D, D2, fff)]


# ======================================================== ELLE DEVİR
def test_M1_manual_supersede_fans_out_to_all_bindings(client, h):
    (r, rk), (i, ik), x = _chain("regm1")
    key_leaf = x
    y, _ = certgen.make_leaf(i, ik, "regm1.test", not_before=datetime(2026, 9, 1))
    _import(client, h, key_leaf, i, r)
    _import(client, h, y)
    X, Y = _cid(client, h, x), _cid(client, h, y)
    d1, d2 = _domain(client, h, "a.regm1.test"), _domain(client, h, "b.regm1.test")
    _attach(client, h, d1, X)
    _attach(client, h, d2, X)
    r_ = client.post(f"/api/certificates/{Y}/supersede/{X}", headers=h)
    assert r_.status_code == 200 and r_.json()["proposed"] == 2, r_.text
    props = _pending(client, h, d1, d2)
    assert _sig(props) == sorted([("transfer", X, Y, d1), ("transfer", X, Y, d2)])
    assert all(p["via"] == "manual" for p in props)


def test_M2_manual_cross_type_rejected_and_reopens_rejected_same_type(client, h):
    (r, rk), (i, ik), x = _chain("regm2")
    y, _ = certgen.make_leaf(i, ik, "regm2.test", not_before=datetime(2026, 9, 1))
    _import(client, h, x, i, r)
    _import(client, h, y)
    R, I, X, Y = (_cid(client, h, c) for c in (r, i, x, y))
    dom = _domain(client, h, "regm2.test")
    _attach(client, h, dom, X)
    for new, old in ((X, R), (X, I), (I, R)):
        resp = client.post(f"/api/certificates/{new}/supersede/{old}", headers=h)
        assert resp.status_code == 400, resp.text
    assert client.post(f"/api/certificates/{Y}/supersede/{X}", headers=h).json()["proposed"] == 1
    _reject(client, h, _pending(client, h, dom)[0]["id"])
    assert client.post(f"/api/certificates/{Y}/supersede/{X}", headers=h).json()["proposed"] == 1, \
        "elle devir reddi bilinçli olarak yeniden açar"


# ======================================================== ZİNCİR İÇE AKTARMA (domain ekranı)
def test_I1_import_chain_is_domain_scoped(client, h, monkeypatch):
    from app.api import domains as domains_api
    (r, rk), (i, ik), x = _chain("regi1")
    key = certgen.make_key()
    x, _ = certgen.make_leaf(i, ik, "regi1.test", key=key, not_before=datetime(2026, 1, 1))
    y, _ = certgen.make_leaf(i, ik, "regi1.test", key=key, not_before=datetime(2026, 9, 1))
    _import(client, h, x, i, r)
    X = _cid(client, h, x)
    d1, d2 = _domain(client, h, "regi1.test"), _domain(client, h, "regi1.test:8443")
    _attach(client, h, d1, X)
    _attach(client, h, d2, X)
    monkeypatch.setattr(domains_api, "fetch_served_chain", lambda host, port: [y, i])
    resp = client.post(f"/api/domains/{d1}/import-chain", headers=h, params={"supersede": "true"})
    assert resp.status_code == 200, resp.text
    Y = _cid(client, h, y)
    props = _pending(client, h, d1, d2)
    assert _sig(props) == [("transfer", X, Y, d1)]
    assert props[0]["via"] == "import-chain", "zincir içe aktarma 'Elle eşleme' (attach) etiketlenmemeli"
    assert props[0]["created_by"] == "admin" and props[0]["created_at"]


def test_I2_proposer_full_name_is_returned(client, h, monkeypatch):
    """Önerenin Ad Soyad'ı (LDAP ile dolan users.full_name) listede döner; otomatik öneride yok."""
    from app.api import domains as domains_api
    (r, rk), (i, ik), x = _chain("regi2")
    key = certgen.make_key()
    x, _ = certgen.make_leaf(i, ik, "regi2.test", key=key, not_before=datetime(2026, 1, 1))
    y, _ = certgen.make_leaf(i, ik, "regi2.test", key=key, not_before=datetime(2026, 9, 1))
    _import(client, h, x, i, r)
    X = _cid(client, h, x)
    d1, d2 = _domain(client, h, "regi2.test"), _domain(client, h, "regi2.test:8443")
    _attach(client, h, d1, X)
    _attach(client, h, d2, X)
    db = SessionLocal()
    admin = db.query(m.User).filter_by(username="admin").one()
    prev, admin.full_name = admin.full_name, "Deneme Yönetici"
    db.commit()
    try:
        monkeypatch.setattr(domains_api, "fetch_served_chain", lambda host, port: [y, i])
        assert client.post(f"/api/domains/{d1}/import-chain", headers=h).status_code == 200
        manual = _pending(client, h, d1)
        assert manual[0]["created_by_name"] == "Deneme Yönetici"
        _live(client, h, monkeypatch, d2, y, i)
        auto = _pending(client, h, d2)
        assert auto[0]["created_by"] == "system" and auto[0]["created_by_name"] is None
    finally:
        admin.full_name = prev
        db.commit()
        db.close()


# ======================================================== ÖNERİ AÇMAYAN YOLLAR
def test_N1_file_import_and_startup_do_not_propose(client, h):
    from app import main
    (r, rk), (i, ik), x = _chain("regn1")
    key = certgen.make_key()
    x, _ = certgen.make_leaf(i, ik, "regn1.test", key=key, not_before=datetime(2026, 1, 1))
    y, _ = certgen.make_leaf(i, ik, "regn1.test", key=key, not_before=datetime(2026, 9, 1))
    _import(client, h, x, i, r)
    dom = _domain(client, h, "regn1.test")
    _attach(client, h, dom, _cid(client, h, x))
    resp = client.post("/api/certificates/import", headers=h, data={"supersede": "true"},
                       files={"file": ("y.pem", certgen.pem(y).encode(), "application/x-pem-file")})
    assert resp.status_code == 200
    assert _pending(client, h, dom) == []
    assert not hasattr(main, "backfill_transfer_proposals")


# ======================================================== ÖNERİ HATTI
def test_P1_add_remove_approval_requires_domain_team(client, h, monkeypatch):
    team = client.post("/api/teams", headers=h, json={"name": "RegP1-SY", "type": "SY"}).json()["id"]
    (r, rk), (i, ik), leaf = _chain("regp1")
    _import(client, h, leaf, i, r)
    dom = _domain(client, h, "regp1.test", sy_team_id=team)
    _live(client, h, monkeypatch, dom, leaf, i)
    props = _pending(client, h, dom)
    assert props and all(p["kind"] == "server_add" and p["sy_team_name"] == "RegP1-SY" for p in props)

    uid = client.post("/api/users", headers=h, json={"username": "regp1_out", "password": "pw12345",
                                                     "role": "editor", "auth_source": "local"}).json()["id"]
    outsider = {"Authorization": "Bearer " + client.post(
        "/api/auth/login-json", json={"username": "regp1_out", "password": "pw12345"}).json()["access_token"]}
    assert client.post(f"/api/proposals/{props[0]['id']}/approve", headers=outsider).status_code == 403
    client.post(f"/api/teams/{team}/members", headers=h, json={"user_id": uid})
    member = {"Authorization": "Bearer " + client.post(
        "/api/auth/login-json", json={"username": "regp1_out", "password": "pw12345"}).json()["access_token"]}
    assert client.post(f"/api/proposals/{props[0]['id']}/approve", headers=member).status_code == 200


def test_P2_audit_records_proposal_kind_and_apply(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regp2")
    _import(client, h, leaf, i, r)
    L = _cid(client, h, leaf)
    dom = _domain(client, h, "regp2.test")
    _live(client, h, monkeypatch, dom, leaf, i)
    pid = next(p["id"] for p in _pending(client, h, dom) if p["new_cert_id"] == L)
    _approve(client, h, pid)
    items = client.get("/api/audit", headers=h, params={"limit": 200}).json()["items"]
    prop_log = next(e for e in items if e["action"] == "propose" and e["record_id"] == str(L))
    assert json.loads(prop_log["details"])["kind"] == "server_add"
    apply_log = next(e for e in items if e["action"] == "server_add_apply")
    assert apply_log["category"] == "approval" and json.loads(apply_log["details"])["domain"] == "regp2.test"
    meta = client.get("/api/audit/meta", headers=h).json()
    assert "server_add_apply" in meta["actions"] and "server_remove_apply" in meta["actions"]


def test_P3_mail_labels_for_new_kinds(client, h, monkeypatch):
    (r, rk), (i, ik), leaf = _chain("regp3")
    stray, _ = certgen.make_leaf(i, ik, "stray.regp3.test", not_before=datetime(2025, 1, 1))
    _import(client, h, leaf, i, r)
    _import(client, h, stray)
    dom = _domain(client, h, "regp3.test")
    _attach(client, h, dom, _cid(client, h, leaf))
    _db_map(dom, _cid(client, h, stray))
    empty = _domain(client, h, "regp3.test:8443")
    _live(client, h, monkeypatch, dom, leaf, i)
    _live(client, h, monkeypatch, empty, leaf, i)
    db = SessionLocal()
    try:
        props = db.query(m.TransferProposal).filter(m.TransferProposal.domain_id.in_([dom, empty]),
                                                    m.TransferProposal.status == "pending").all()
        labels = {p.kind: notifier._proposal_label(p) for p in props}
        kinds = {p.kind: notifier._PROPOSAL_KIND_LABELS[p.kind] for p in props}
    finally:
        db.close()
    assert labels["server_add"].startswith("Ekleme: ") and labels["server_remove"] == "Kaldırma: stray.regp3.test"
    assert kinds == {"server_add": "Eşleme Ekleme", "server_remove": "Eşleme Kaldırma"}
