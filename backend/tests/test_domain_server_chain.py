"""Domain 'server' eşlemesinin zincir-bilinçli davranışı (attach_certificate).

Kök neden fix: 'server' eşlemesi artık yalnız leaf değil, çözülebilen TÜM zinciri
(intermediate/root) birlikte taşır — her cert_type kendi havuzuyla (leaf↔leaf,
intermediate↔intermediate, root↔root) karşılaştırılır, birbirine karıştırılmaz."""

from datetime import datetime

from tests import certgen


def _import_pem(client, h, pem_text):
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("chain.pem", pem_text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return r.json()


def _domain(client, h, name):
    r = client.post("/api/domains", headers=h, json={"domain": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(client, h, domain_id, cert_id, mapping_type="server"):
    return client.post(f"/api/domains/{domain_id}/certificates", headers=h,
                       json={"certificate_id": cert_id, "mapping_type": mapping_type})


def _by_type(certs, cert_type):
    return next(c for c in certs if c["cert_type"] == cert_type)


def _server_mappings(client, h, domain_id):
    dom = client.get(f"/api/domains/{domain_id}", headers=h).json()
    return [c for c in dom["certificates"] if c["mapping_type"] == "server"]


def _full_chain(cn, not_before=None):
    root, root_key = certgen.make_ca(f"Root {cn}")
    inter, inter_key = certgen.make_intermediate(root, root_key, f"Inter {cn}",
                                                 not_before=not_before)
    leaf, leaf_key = certgen.make_leaf(inter, inter_key, cn, san=[cn], not_before=not_before)
    return root, inter, leaf


def test_attach_server_binds_full_chain(client, auth_headers):
    """leaf server olarak bağlanınca intermediate+root AYNI işlemde otomatik bağlanır."""
    h = auth_headers
    root, inter, leaf = _full_chain("fullchain-attach.test")
    certs = _import_pem(client, h, certgen.pem(leaf) + certgen.pem(inter) + certgen.pem(root))
    leaf_id = _by_type(certs, "leaf")["id"]

    dom = _domain(client, h, "fullchain-attach.test")
    r = _attach(client, h, dom, leaf_id)
    assert r.status_code == 200, r.text
    assert "warning" not in r.json()

    server = _server_mappings(client, h, dom)
    assert {c["cert_type"] for c in server} == {"root", "intermediate", "leaf"}
    assert len(server) == 3


def test_attach_server_incomplete_chain_warns_but_still_binds_leaf(client, auth_headers):
    """CA envanterde yoksa REDDEDİLMEZ — bulunabilen (yalnız leaf) bağlanır, uyarı döner."""
    h = auth_headers
    ca, ca_key = certgen.make_ca("Lonewolf CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "lonewolf-leaf.test", san=["lonewolf-leaf.test"])
    leaf_id = _import_pem(client, h, certgen.pem(leaf))[0]["id"]  # CA içe aktarılmadı — bilinçli

    dom = _domain(client, h, "lonewolf-leaf.test")
    r = _attach(client, h, dom, leaf_id)
    assert r.status_code == 200, r.text
    assert "eksik" in r.json()["warning"].lower()

    server = _server_mappings(client, h, dom)
    assert [c["cert_type"] for c in server] == ["leaf"]


def test_attach_server_rejects_non_leaf_certificate(client, auth_headers):
    """'Server' olarak yalnız leaf (uç) sertifika doğrudan SEÇİLEBİLİR; intermediate/root
    seçilmeye çalışılırsa 400 — zincir otomatik eklenir, elle seçilmez."""
    h = auth_headers
    root, inter, leaf = _full_chain("rejectnonleaf.test")
    certs = _import_pem(client, h, certgen.pem(leaf) + certgen.pem(inter) + certgen.pem(root))
    inter_id = _by_type(certs, "intermediate")["id"]
    root_id = _by_type(certs, "root")["id"]
    dom = _domain(client, h, "rejectnonleaf.test")
    assert _attach(client, h, dom, inter_id).status_code == 400
    assert _attach(client, h, dom, root_id).status_code == 400


def test_attach_server_second_leaf_same_chain_proposes_only_leaf_level(client, auth_headers):
    """Aynı intermediate+root'u paylaşan İKİNCİ bir leaf eklenince yalnız LEAF seviyesi
    çakışır (değişiklik talebi) — intermediate/root zaten eşli olduğundan dokunulmaz."""
    h = auth_headers
    root, root_key = certgen.make_ca("Shared Root")
    inter, inter_key = certgen.make_intermediate(root, root_key, "Shared Inter")
    leaf_a, _ = certgen.make_leaf(inter, inter_key, "shared-a.test", san=["shared-a.test"],
                                  not_before=datetime(2026, 1, 1))
    leaf_b, _ = certgen.make_leaf(inter, inter_key, "shared-a.test", san=["shared-a.test"],
                                  not_before=datetime(2026, 2, 1))
    certs_a = _import_pem(client, h, certgen.pem(leaf_a) + certgen.pem(inter) + certgen.pem(root))
    leaf_a_id = _by_type(certs_a, "leaf")["id"]
    leaf_b_id = _import_pem(client, h, certgen.pem(leaf_b))[0]["id"]  # aynı CA zaten envanterde

    dom = _domain(client, h, "shared-a.test")
    assert _attach(client, h, dom, leaf_a_id).status_code == 200

    r = _attach(client, h, dom, leaf_b_id)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "proposal_created"

    # domain hâlâ leaf_a + intermediate + root'a eşli; yalnız leaf seviyesinde öneri bekliyor
    server = _server_mappings(client, h, dom)
    assert {c["cert_type"] for c in server} == {"root", "intermediate", "leaf"}
    leaf_mapped = next(c for c in server if c["cert_type"] == "leaf")
    assert leaf_mapped["certificate_id"] == leaf_a_id

    props = [p for p in client.get("/api/proposals", headers=h,
                                   params={"status": "pending"}).json() if p["domain_id"] == dom]
    assert len(props) == 1 and props[0]["mapping_type"] == "server"


def test_attach_server_two_intermediates_bind_without_spurious_proposal(client, auth_headers):
    """Bug fix: zincirde İKİ 'intermediate' tipli sertifika varsa (gerçek 2 katmanlı ara-CA
    hiyerarşisi VEYA eski istemcilerle uyum için eklenen çapraz-imzalı bir kopya — google.com'da
    görüldüğü gibi), bunlar birbirinin çakışma adayı SAYILMAMALI. Önceki haliyle ikinci
    intermediate, az önce bağlanan birinciyi 'rakip' sanıp gereksiz bir değişiklik talebi (202)
    üretiyordu — ilk kurulumda bile."""
    h = auth_headers
    root, root_key = certgen.make_ca("TwoInter Root")
    inter_a, inter_a_key = certgen.make_intermediate(root, root_key, "TwoInter Inter A")
    inter_b, inter_b_key = certgen.make_intermediate(inter_a, inter_a_key, "TwoInter Inter B")
    leaf, _ = certgen.make_leaf(inter_b, inter_b_key, "two-inter.test", san=["two-inter.test"])

    certs = _import_pem(client, h, certgen.pem(leaf) + certgen.pem(inter_b)
                        + certgen.pem(inter_a) + certgen.pem(root))
    leaf_id = _by_type(certs, "leaf")["id"]

    dom = _domain(client, h, "two-inter.test")
    r = _attach(client, h, dom, leaf_id)
    assert r.status_code == 200, r.text
    assert "warning" not in r.json()

    server = _server_mappings(client, h, dom)
    assert len(server) == 4, "leaf + 2 intermediate + root birlikte bağlanmalı"
    cert_types = [c["cert_type"] for c in server]
    assert cert_types.count("intermediate") == 2
    assert cert_types.count("leaf") == 1
    assert cert_types.count("root") == 1

    # Hiçbir değişiklik talebi oluşmamalı — ilk kurulum, rakip yok
    props = [p for p in client.get("/api/proposals", headers=h,
                                   params={"status": "pending"}).json() if p["domain_id"] == dom]
    assert props == []
