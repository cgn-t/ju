"""Kök / ara / uç sertifika algılaması (v3.8.10): yükleme ve otomatik çekme.

Tek başına bakıldığında kökle ayırt edilemeyen kendinden imzalı sertifikalar (uzantısız v1 kök,
KU'suz ve CN'i alan adı gibi kök, SAN taşıyan kök) önce 'uç' sayılır; başka bir sertifikayı
imzaladığı görülünce (aynı dosyada ya da envanterde, hangi sırayla eklenirse) köke yükseltilir."""
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

from app.services.cert_parser import parse_upload
from tests.certgen import key_pem, make_ca, make_intermediate, make_key, make_leaf, pem
from tests.test_live_check import _tls_server

def _n(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def build(subject, issuer, pub, sign_key, *, bc=None, ku=None, san=None, ski=True, aki_key=None,
          aki_keyid=None, nb=datetime(2026, 1, 1), days=365, version3=True):
    b = (x509.CertificateBuilder().subject_name(_n(subject)).issuer_name(_n(issuer))
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(nb).not_valid_after(nb + timedelta(days=days)))
    if bc is not None:
        b = b.add_extension(x509.BasicConstraints(ca=bc, path_length=None), critical=True)
    if ku is not None:
        b = b.add_extension(ku, critical=True)
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in san]), critical=False)
    if ski:
        b = b.add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
    if aki_key is not None:
        b = b.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(aki_key), critical=False)
    if aki_keyid is not None:
        b = b.add_extension(x509.AuthorityKeyIdentifier(aki_keyid, None, None), critical=False)
    return b.sign(sign_key, hashes.SHA256())


def KU(sign=False, ds=True):
    return x509.KeyUsage(digital_signature=ds, content_commitment=False, key_encipherment=not sign,
                         data_encipherment=False, key_agreement=False, key_cert_sign=sign,
                         crl_sign=sign, encipher_only=False, decipher_only=False)


def kind(cert):
    return parse_upload(pem(cert).encode())[0].cert_type


def test_classification_matrix():
    rows = []
    def rec(label, cert, expected):
        got = kind(cert)
        rows.append((label, expected, got, "OK" if got == expected else "HATA"))

    root, rk = make_ca("M Kok CA")
    inter, ik = make_intermediate(root, rk, "M Ara CA")
    leaf, _ = make_leaf(inter, ik, "m.test", san=["m.test"])
    rec("standart kök", root, "root")
    rec("standart ara", inter, "intermediate")
    rec("standart uç", leaf, "leaf")

    i2, i2k = make_intermediate(inter, ik, "M Ara CA 2")
    rec("2. katman ara", i2, "intermediate")

    # Çapraz imzalı kök: R2 kendi kök + R1 imzalı kopyası
    r1, r1k = make_ca("Eski Kok")
    r2k = make_key()
    cross = build("Yeni Kok", "Eski Kok", r2k.public_key(), r1k, bc=True, ku=KU(True),
                  aki_key=r1k.public_key())
    r2 = build("Yeni Kok", "Yeni Kok", r2k.public_key(), r2k, bc=True, ku=KU(True),
               aki_key=r2k.public_key())
    rec("çapraz imzalı kök kopyası", cross, "intermediate")
    rec("yeni kök (kendinden imzalı, AKI=SKI)", r2, "root")

    k = make_key()
    rec("v1 kök (hiç uzantı yok)", build("V1 Kok", "V1 Kok", k.public_key(), k, ski=False), "leaf")  # tek başına ayırt edilemez
    rec("kök: BC yok, KU certSign", build("KU Kok", "KU Kok", k.public_key(), k, ku=KU(True)), "root")
    rec("kök: KU yok, CN düz ad (openssl req -x509)",
        build("Jumbo Ic CA", "Jumbo Ic CA", k.public_key(), k, bc=True, aki_key=k.public_key()), "root")
    rec("kök: KU yok, CN alan adı gibi (openssl req -x509, CN=ca.jumbo.local)",
        build("ca.jumbo.local", "ca.jumbo.local", k.public_key(), k, bc=True, aki_key=k.public_key()), "leaf")
    rec("kök: KU certSign + SAN'da DNS",
        build("Jumbo Kok CA", "Jumbo Kok CA", k.public_key(), k, bc=True, ku=KU(True),
              san=["pki.jumbo.local"]), "leaf")
    rec("kendinden imzalı sunucu (CA:TRUE + SAN)",
        build("cihaz.jumbo.local", "cihaz.jumbo.local", k.public_key(), k, bc=True, san=["cihaz.jumbo.local"]), "leaf")
    rec("kendinden imzalı sunucu (CA:TRUE, KU certSign yok)",
        build("Firewall", "Firewall", k.public_key(), k, bc=True, ku=KU(False)), "leaf")
    rec("kendinden imzalı uç (CA:FALSE)",
        build("self.test", "self.test", k.public_key(), k, bc=False, san=["self.test"], aki_key=k.public_key()), "leaf")
    k2 = make_key()
    rec("anahtar geçişi ara CA (issuer=subject, AKI≠SKI)",
        build("M Kok CA", "M Kok CA", k2.public_key(), rk, bc=True, ku=KU(True), aki_key=rk.public_key()),
        "intermediate")
    rec("CA'nın imzaladığı, CA:TRUE işaretli sunucu sertifikası (KU certSign yok, SAN var)",
        build("app.jumbo.local", "M Ara CA", k2.public_key(), ik, bc=True, ku=KU(False),
              san=["app.jumbo.local"], aki_key=ik.public_key()), "leaf")
    rec("ara CA: BC yok, KU certSign",
        build("Eski Ara", "M Kok CA", k2.public_key(), rk, ku=KU(True), aki_key=rk.public_key()), "intermediate")
    rec("uç: hiç uzantı yok (v1, CA imzalı)", build("v1.test", "M Ara CA", k2.public_key(), ik, ski=False), "leaf")
    assert [r for r in rows if r[3] != "OK"] == []


def _imp(client, h, text):
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return {c["name"]: c for c in r.json()}


def _get(client, h, cid):
    return client.get(f"/api/certificates/{cid}", headers=h).json()


def _parent_name(client, h, cid):
    c = _get(client, h, cid)
    pid = c.get("parent_id")
    return _get(client, h, pid)["name"] if pid else None


def _server(client, h, domain_id):
    return sorted((c["name"], c["cert_type"]) for c in
                  client.get(f"/api/domains/{domain_id}", headers=h).json()["certificates"]
                  if c["mapping_type"] == "server")


def _pending(client, h, domain_id):
    return [p for p in client.get("/api/proposals", headers=h, params={"status": "pending"}).json()
            if p["domain_id"] == domain_id]


def test_upload_two_tier_chain_in_mixed_order(client, auth_headers):
    h = auth_headers
    root, rk = make_ca("U Kok")
    ia, iak = make_intermediate(root, rk, "U Ara A")
    ib, ibk = make_intermediate(ia, iak, "U Ara B")
    leaf, _ = make_leaf(ib, ibk, "u.test", san=["u.test"])
    rows = _imp(client, h, pem(ia) + pem(leaf) + pem(root) + pem(ib))
    out = {n: (c["cert_type"], _parent_name(client, h, c["id"])) for n, c in rows.items()}
    assert out == {"u.test": ("leaf", "U Ara B"), "U Ara B": ("intermediate", "U Ara A"),
                   "U Ara A": ("intermediate", "U Kok"), "U Kok": ("root", None)}


def test_upload_leaf_first_then_cas_relinks(client, auth_headers):
    h = auth_headers
    root, rk = make_ca("R Kok")
    ia, iak = make_intermediate(root, rk, "R Ara")
    leaf, _ = make_leaf(ia, iak, "r.test", san=["r.test"])
    lid = _imp(client, h, pem(leaf))["r.test"]["id"]
    assert _parent_name(client, h, lid) is None
    _imp(client, h, pem(ia))
    _imp(client, h, pem(root))
    assert _parent_name(client, h, lid) == "R Ara"
    assert _parent_name(client, h, _get(client, h, lid)["parent_id"]) == "R Kok"


def test_self_signed_same_key_renewal_not_linked_to_each_other(client, auth_headers):
    """Bug: aynı anahtarla yenilenen kendinden imzalı sunucu sertifikaları (cihazlar sık yapar)
    aynı SKI'yi taşır; eskiden ikisi birbirinin 'üst sertifikası' olarak bağlanıyordu (döngü)."""
    h = auth_headers
    k = make_key()
    old = build("ss.jumbo.local", "ss.jumbo.local", k.public_key(), k, bc=True, san=["ss.jumbo.local"],
                aki_key=k.public_key(), nb=datetime(2025, 1, 1))
    new = build("ss.jumbo.local", "ss.jumbo.local", k.public_key(), k, bc=True, san=["ss.jumbo.local"],
                aki_key=k.public_key(), nb=datetime(2026, 1, 1))
    oid = _imp(client, h, pem(old))["ss.jumbo.local"]["id"]
    nid = _imp(client, h, pem(new))["ss.jumbo.local"]["id"]
    o, n = _get(client, h, oid), _get(client, h, nid)
    assert (o["cert_type"], n["cert_type"]) == ("leaf", "leaf")
    assert o.get("parent_id") is None and n.get("parent_id") is None


def test_fetch_cross_signed_root_chain(client, auth_headers):
    """Sunucu çapraz imzalı kök kopyası gönderiyor: kopya ara CA sayılır, gerçek kök envanterden
    türetilip bağlanır; ardından canlı doğrulama uyumlu, hiçbir talep açılmaz."""
    h = auth_headers
    r1, r1k = make_ca("X Eski Kok")
    r2k = make_key()
    r2 = build("X Yeni Kok", "X Yeni Kok", r2k.public_key(), r2k, bc=True, ku=KU(True),
               aki_key=r2k.public_key(), days=3650)
    cross = build("X Yeni Kok", "X Eski Kok", r2k.public_key(), r1k, bc=True, ku=KU(True),
                  aki_key=r1k.public_key(), days=3650)
    ia, iak = make_intermediate(r2, r2k, "X Ara")
    leaf, lk = make_leaf(ia, iak, "127.0.0.1", san=["127.0.0.1"])
    _imp(client, h, pem(r1) + pem(r2))
    with _tls_server(pem(leaf) + pem(ia) + pem(cross), key_pem(lk)) as port:
        d = client.post("/api/domains", headers=h, json={"domain": f"127.0.0.1:{port}"}).json()["id"]
        assert client.post(f"/api/domains/{d}/import-chain", headers=h).status_code == 200
        assert _server(client, h, d) == [("127.0.0.1", "leaf"), ("X Ara", "intermediate"),
                                         ("X Yeni Kok", "intermediate"), ("X Yeni Kok", "root")]
        lc = client.post(f"/api/domains/{d}/live-check", headers=h).json()
        assert lc["live_check_status"] == "match"
        assert _pending(client, h, d) == []


def test_fetch_without_root_binds_root_and_live_check_opens_no_request(client, auth_headers):
    """Bug: sunucular kökü göndermez. Otomatik çekme kökü bağlamıyor, ilk canlı doğrulama da her
    domain için gereksiz bir 'kökü ekle' değişiklik talebi açıyordu (elle bağlama kökü bağlar)."""
    h = auth_headers
    root, rk = make_ca("N Kok")
    ia, iak = make_intermediate(root, rk, "N Ara")
    leaf, lk = make_leaf(ia, iak, "127.0.0.1", san=["127.0.0.1"])
    _imp(client, h, pem(root))
    with _tls_server(pem(leaf) + pem(ia), key_pem(lk)) as port:
        d = client.post("/api/domains", headers=h, json={"domain": f"127.0.0.1:{port}"}).json()["id"]
        assert client.post(f"/api/domains/{d}/import-chain", headers=h).status_code == 200
        assert _server(client, h, d) == [("127.0.0.1", "leaf"), ("N Ara", "intermediate"),
                                         ("N Kok", "root")]
        lc = client.post(f"/api/domains/{d}/live-check", headers=h).json()
        assert lc["live_check_status"] == "match"
        assert _pending(client, h, d) == []


def test_fetch_ca_flagged_server_cert_signed_by_internal_ca_is_leaf(client, auth_headers):
    """Bug: CA:TRUE işaretli ama sertifika imzalama yetkisi olmayan sunucu sertifikası (iç CA
    imzalı) 'ara CA' sayılıyordu: domaine uç sertifika bağlanmıyordu."""
    h = auth_headers
    root, rk = make_ca("C Kok")
    ia, iak = make_intermediate(root, rk, "C Ara")
    k = make_key()
    srv = build("127.0.0.1", "C Ara", k.public_key(), iak, bc=True, ku=KU(False), san=["127.0.0.1"],
                aki_key=iak.public_key())
    _imp(client, h, pem(root) + pem(ia))
    with _tls_server(pem(srv) + pem(ia), key_pem(k)) as port:
        target = f"127.0.0.1:{port}"
        d = client.post("/api/domains", headers=h, json={"domain": target}).json()["id"]
        probe = client.post("/api/domains/probe-chain", headers=h, json={"domain": target}).json()
        assert [(c["name"], c["cert_type"]) for c in probe["certificates"]] == [
            ("127.0.0.1", "leaf"), ("C Ara", "intermediate")]
        r = client.post(f"/api/domains/{d}/import-chain", headers=h)
        assert r.status_code == 200 and r.json()["mapped_server"] == "127.0.0.1"
        assert _server(client, h, d) == [("127.0.0.1", "leaf"), ("C Ara", "intermediate"),
                                         ("C Kok", "root")]


def _ambiguous_root_and_leaf(tag, variant):
    k = make_key()
    if variant == "v1":  # hiç uzantısı olmayan eski v1 kök
        root = build(f"{tag} V1 Kok", f"{tag} V1 Kok", k.public_key(), k, ski=False)
    elif variant == "host":  # openssl req -x509 ile üretilmiş, CN'i alan adı gibi kök
        root = build(f"ca.{tag}.local", f"ca.{tag}.local", k.public_key(), k, bc=True,
                     aki_key=k.public_key())
    else:  # SAN'ında DNS adı taşıyan kök
        root = build(f"{tag} SAN Kok", f"{tag} SAN Kok", k.public_key(), k, bc=True, ku=KU(True),
                     san=[f"pki.{tag}.local"])
    lk = make_key()
    issuer_cn = root.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    leaf = build(f"srv.{tag}.test", issuer_cn, lk.public_key(), k, bc=False, san=[f"srv.{tag}.test"],
                 ski=variant != "v1", aki_key=None if variant == "v1" else k.public_key())
    return root, leaf


def test_ambiguous_self_signed_root_promoted_when_it_signed_another_cert(client, auth_headers):
    """Bug: bu kökler 'uç' sayılıyor, imzaladıkları sertifika da üstsüz kalıyordu (v1 kökte hiç
    bağlanmıyordu). Artık imzaladığı bir sertifika görülünce köke yükseltilir — aynı dosyada,
    önce kök ya da önce uç yüklense de."""
    h = auth_headers
    results = []
    for variant in ("v1", "host", "san"):
        for order in ("same-file", "root-first", "leaf-first"):
            tag = f"p{variant}{order.replace('-', '')}"
            root, leaf = _ambiguous_root_and_leaf(tag, variant)
            if order == "same-file":
                preview = client.post("/api/certificates/import/preview", headers=h,
                                      files={"file": ("c.pem", (pem(leaf) + pem(root)).encode())}).json()
                assert sorted(p["cert_type"] for p in preview) == ["leaf", "root"]
                _imp(client, h, pem(leaf) + pem(root))
            elif order == "root-first":
                _imp(client, h, pem(root))
                _imp(client, h, pem(leaf))
            else:
                _imp(client, h, pem(leaf))
                _imp(client, h, pem(root))
            rows = client.get("/api/certificates", headers=h, params={"search": tag}).json()
            r = next(c for c in rows if c["issuer"] == c["subject"])
            lf = next(c for c in rows if c["issuer"] != c["subject"])
            results.append((variant, order, r["cert_type"], lf["cert_type"],
                            _parent_name(client, h, lf["id"]) == r["name"]))
    assert [x for x in results if x[2:] != ("root", "leaf", True)] == []
