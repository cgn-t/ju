"""Zincir Kontrolü (v3.8.11) ve zincir bağlama kenar durumları: çapraz imzalı kökte kök tercihi,
üst sertifika silinince yeniden bağlama, elle üst sertifika verirken döngü engeli."""
from datetime import datetime

from app.db import models as m
from app.db.session import SessionLocal
from tests.certgen import key_pem, make_ca, make_intermediate, make_key, make_leaf, pem
from tests.test_cert_edit_scope_and_revoked_mail import _login, _mk_user
from tests.test_cert_type_detection import KU, _get, _imp, _parent_name, _server, build
from tests.test_live_check import _tls_server


def test_cross_copy_in_inventory_prefers_self_signed_root(client, auth_headers):
    """Bug: çapraz imzalı kopya envanterde önceden varken ara CA ona bağlanıyor, domaine yeni kök
    yerine erken bitecek ESKİ kök bağlanıyordu."""
    h = auth_headers
    r1, r1k = make_ca("Y Eski Kok", days=1000)
    r2k = make_key()
    r2 = build("Y Yeni Kok", "Y Yeni Kok", r2k.public_key(), r2k, bc=True, ku=KU(True),
               aki_key=r2k.public_key(), days=3650)
    cross = build("Y Yeni Kok", "Y Eski Kok", r2k.public_key(), r1k, bc=True, ku=KU(True),
                  aki_key=r1k.public_key(), days=3700)
    ia, iak = make_intermediate(r2, r2k, "Y Ara")
    leaf, lk = make_leaf(ia, iak, "127.0.0.1", san=["127.0.0.1"])
    _imp(client, h, pem(r1) + pem(r2) + pem(cross))
    with _tls_server(pem(leaf) + pem(ia), key_pem(lk)) as port:
        d = client.post("/api/domains", headers=h, json={"domain": f"127.0.0.1:{port}"}).json()["id"]
        assert client.post(f"/api/domains/{d}/import-chain", headers=h).status_code == 200
        assert ("Y Yeni Kok", "root") in _server(client, h, d)
        assert ("Y Eski Kok", "root") not in _server(client, h, d)
        ara = client.get("/api/certificates", headers=h, params={"search": "Y Ara"}).json()[0]
        parent = _get(client, h, ara["parent_id"])
        assert (parent["name"], parent["cert_type"]) == ("Y Yeni Kok", "root")


def test_deleting_ca_relinks_children_to_same_key_sibling(client, auth_headers):
    """Bug: aynı anahtarla yenilenmiş ara CA varken eski ara CA silinince alt sertifikalar üstsüz kalıyordu."""
    h = auth_headers
    root, rk = make_ca("D Kok")
    ik = make_key()
    i_old, _ = make_intermediate(root, rk, "D Ara", key=ik, not_before=datetime(2025, 1, 1))
    i_new, _ = make_intermediate(root, rk, "D Ara", key=ik, not_before=datetime(2026, 1, 1))
    leaf, _ = make_leaf(i_old, ik, "d.test", san=["d.test"])
    _imp(client, h, pem(root) + pem(i_old) + pem(i_new))
    lid = _imp(client, h, pem(leaf))["d.test"]["id"]
    pid = _get(client, h, lid)["parent_id"]
    assert client.delete(f"/api/certificates/{pid}", headers=h).status_code == 200
    new_pid = _get(client, h, lid)["parent_id"]
    assert new_pid is not None and new_pid != pid
    assert _parent_name(client, h, lid) == "D Ara"


def test_manual_parent_cannot_create_loop(client, auth_headers):
    h = auth_headers
    root, rk = make_ca("L Kok")
    ia, _ = make_intermediate(root, rk, "L Ara")
    rows = _imp(client, h, pem(root) + pem(ia))
    kok, ara = rows["L Kok"]["id"], rows["L Ara"]["id"]
    r = client.put(f"/api/certificates/{kok}", headers=h, json={"parent_id": ara})
    assert r.status_code == 400 and "altına bağlanamaz" in r.json()["detail"]
    r = client.put(f"/api/certificates/{ara}", headers=h, json={"parent_id": ara})
    assert r.status_code == 400
    assert client.put(f"/api/certificates/{ara}", headers=h, json={"parent_id": 99999999}).status_code == 400
    assert client.put(f"/api/certificates/{ara}", headers=h, json={"parent_id": kok}).status_code == 200


def _ids(rows):
    return {name: c["id"] for name, c in rows.items()}


def test_chain_check_finds_and_fixes_old_records(client, auth_headers):
    """Eski sürümlerin yazdığı hatalı kayıtlar (prod'daki gibi) Zincir Kontrolü ile bulunur ve düzeltilir."""
    h = auth_headers
    # 1) iç CA imzalı, CA işaretli sunucu sertifikası 'Ara CA' kaydedilmiş
    root, rk = make_ca("ZK Kok")
    ia, iak = make_intermediate(root, rk, "ZK Ara")
    k = make_key()
    caflag = build("zk-cihaz.test", "ZK Ara", k.public_key(), iak, bc=True, ku=KU(False),
                   san=["zk-cihaz.test"], aki_key=iak.public_key())
    # 2) aynı anahtarla yenilenmiş kendinden imzalı sertifikalar birbirine bağlanmış (döngü)
    sk = make_key()
    ss_old = build("zk-ss.test", "zk-ss.test", sk.public_key(), sk, bc=True, san=["zk-ss.test"],
                   aki_key=sk.public_key(), nb=datetime(2025, 1, 1))
    ss_new = build("zk-ss.test", "zk-ss.test", sk.public_key(), sk, bc=True, san=["zk-ss.test"],
                   aki_key=sk.public_key(), nb=datetime(2026, 1, 1))
    # 3) uzantısız v1 kök 'Uç' kayıtlı, imzaladığı sertifika üstsüz
    vk = make_key()
    v1 = build("ZK V1 Kok", "ZK V1 Kok", vk.public_key(), vk, ski=False)
    v1_child = build("zk-v1.test", "ZK V1 Kok", make_key().public_key(), vk, bc=False, ski=False)
    ids = _ids(_imp(client, h, pem(root) + pem(ia) + pem(caflag) + pem(v1) + pem(v1_child)))
    ids["ss_old"] = _imp(client, h, pem(ss_old))["zk-ss.test"]["id"]
    ids["ss_new"] = _imp(client, h, pem(ss_new))["zk-ss.test"]["id"]

    db = SessionLocal()
    try:
        row = lambda key: db.get(m.Certificate, ids[key])
        row("zk-cihaz.test").cert_type = "Intermediate"           # eski yanlış tür (ham yazım)
        row("ss_old").parent_id, row("ss_new").parent_id = ids["ss_new"], ids["ss_old"]
        row("ZK V1 Kok").cert_type = "leaf"
        row("zk-v1.test").parent_id = None
        row("ZK Ara").subject_key_identifier = row("ZK Ara").subject_key_identifier.replace(":", "").lower()
        db.commit()
    finally:
        db.close()

    _mk_user(client, h, "zk-editor", role="editor")
    viewer_h = _login(client, "zk-editor")
    assert client.get("/api/certificates/chain-check", headers=viewer_h).status_code == 403
    assert client.post("/api/certificates/chain-check/apply", headers=viewer_h).status_code == 403

    mine = set(ids.values())
    found = {(f["certificate_id"], f["kind"]): f
             for f in client.get("/api/certificates/chain-check", headers=h).json()
             if f["certificate_id"] in mine}
    assert found[(ids["zk-cihaz.test"], "type")]["expected"] == "Uç Sertifika"
    assert found[(ids["ss_old"], "parent")]["expected"] == "— (üstü yok)"
    assert found[(ids["ss_new"], "parent")]["expected"] == "— (üstü yok)"
    assert found[(ids["ZK V1 Kok"], "type")]["expected"] == "Kök CA"
    assert found[(ids["zk-v1.test"], "parent")]["expected"] == "ZK V1 Kok"
    assert (ids["ZK Ara"], "subject_key_identifier") in found
    assert len(found) == 6, found

    # Kontrol değiştirmez
    assert _get(client, h, ids["zk-cihaz.test"])["cert_type"] == "intermediate"

    applied = client.post("/api/certificates/chain-check/apply", headers=h).json()
    assert {(f["certificate_id"], f["kind"]) for f in applied if f["certificate_id"] in mine} == set(found)
    assert [f for f in client.get("/api/certificates/chain-check", headers=h).json()
            if f["certificate_id"] in mine] == []
    assert _get(client, h, ids["zk-cihaz.test"])["cert_type"] == "leaf"
    assert _get(client, h, ids["ZK V1 Kok"])["cert_type"] == "root"
    assert _parent_name(client, h, ids["zk-v1.test"]) == "ZK V1 Kok"
    assert _get(client, h, ids["ss_old"])["parent_id"] is None
    items = client.get("/api/audit", headers=h, params={"action": "chain_repair"}).json()["items"]
    logged = {(int(a["record_id"]), a["summary"]) for a in items if int(a["record_id"]) in mine}
    assert len(logged) >= 6, items
