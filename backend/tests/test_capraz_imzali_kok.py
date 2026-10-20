"""Çapraz imzalı kök kopyası (v3.8.14): www.akbank.de örneği.

Sunucu 5 sertifika gönderir: uç → CA EV R36 → R46 (USERTrust imzalı kopya) → USERTrust (AAA
imzalı kopya) → AAA. Tarayıcı R46'yı kendi güven listesinde bulur ve 3 sertifikada durur.
Jumbo sunulanı olduğu gibi gösterir (R46 kopyası teknik olarak ara sertifika), ama kopyayı
"Çapraz imzalı kök", sonrasını "Ek zincir" diye işaretler."""
import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services import trust_anchors
from tests.certgen import key_pem, make_key, pem
from tests.test_cert_type_detection import KU, _imp, _server, build
from tests.test_live_check import _tls_server

CA = dict(bc=True, ku=KU(sign=True, ds=False))


def _akbank_like():
    aaa_k, ut_k, r46_k, r36_k, leaf_k = (make_key() for _ in range(5))
    aaa = build("AAA Certificate Services", "AAA Certificate Services", aaa_k.public_key(), aaa_k, **CA)
    ut_cross = build("USERTrust RSA Certification Authority", "AAA Certificate Services",
                     ut_k.public_key(), aaa_k, aki_key=aaa_k.public_key(), **CA)
    ut_self = build("USERTrust RSA Certification Authority", "USERTrust RSA Certification Authority",
                    ut_k.public_key(), ut_k, **CA)
    r46_cross = build("Sectigo Public Server Authentication Root R46",
                      "USERTrust RSA Certification Authority", r46_k.public_key(), ut_k,
                      aki_key=ut_k.public_key(), **CA)
    r46_self = build("Sectigo Public Server Authentication Root R46",
                     "Sectigo Public Server Authentication Root R46", r46_k.public_key(), r46_k,
                     days=7300, **CA)
    r36 = build("Sectigo Public Server Authentication CA EV R36",
                "Sectigo Public Server Authentication Root R46", r36_k.public_key(), r46_k,
                aki_key=r46_k.public_key(), **CA)
    leaf = build("127.0.0.1", "Sectigo Public Server Authentication CA EV R36", leaf_k.public_key(),
                 r36_k, bc=False, ku=KU(False), san=["127.0.0.1"], aki_key=r36_k.public_key())
    served = [leaf, r36, r46_cross, ut_cross, aaa]
    return served, leaf_k, r46_self, ut_self


@pytest.fixture
def public_roots(monkeypatch):
    """Test kökleri tarayıcı güven listesindeymiş gibi (gerçek Sectigo anahtarı üretilemez)."""
    roots = set()
    monkeypatch.setattr(trust_anchors, "_public_roots", lambda: roots)

    def add(*certs):
        for c in certs:
            roots.add((c.subject.public_bytes(),
                       c.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)))
    return add


def _probe(client, h, target):
    r = client.post("/api/domains/probe-chain", headers=h, json={"domain": target})
    assert r.status_code == 200, r.text
    return [(c["name"], c["cert_type"], c["cross_signed_root"], c["extra_chain"], c["issuer_name"])
            for c in r.json()["certificates"]]


def test_probe_marks_cross_signed_root_and_extra_chain(client, auth_headers, public_roots):
    h = auth_headers
    served, leaf_k, r46_self, ut_self = _akbank_like()
    public_roots(r46_self, ut_self)
    with _tls_server("".join(pem(c) for c in served), key_pem(leaf_k)) as port:
        rows = _probe(client, h, f"127.0.0.1:{port}")
    assert rows == [
        ("127.0.0.1", "leaf", False, False, "Sectigo Public Server Authentication CA EV R36"),
        ("Sectigo Public Server Authentication CA EV R36", "intermediate", False, False,
         "Sectigo Public Server Authentication Root R46"),
        ("Sectigo Public Server Authentication Root R46", "intermediate", True, False,
         "USERTrust RSA Certification Authority"),
        ("USERTrust RSA Certification Authority", "intermediate", True, True, "AAA Certificate Services"),
        ("AAA Certificate Services", "root", False, True, "AAA Certificate Services"),
    ]


def test_probe_without_public_root_marks_nothing(client, auth_headers, public_roots):
    """Şirket içi CA'lar güven listesinde yok: hiçbir sertifika işaretlenmez (eski davranış)."""
    h = auth_headers
    served, leaf_k, _, _ = _akbank_like()
    with _tls_server("".join(pem(c) for c in served), key_pem(leaf_k)) as port:
        rows = _probe(client, h, f"127.0.0.1:{port}")
    assert [(r[2], r[3]) for r in rows] == [(False, False)] * 5


def test_import_binds_what_server_sends(client, auth_headers, public_roots):
    """İçe aktarma işaretlemeden etkilenmez: sunucunun gönderdiği 5 sertifika da domaine bağlanır
    (canlı doğrulama sunulanla karşılaştırır). R36'nın üstü envanterde kendinden imzalı R46 kökü
    varsa ona bağlanır (v3.8.11); sunulan R46 kopyası ara sertifika olarak kalır."""
    h = auth_headers
    served, leaf_k, r46_self, ut_self = _akbank_like()
    public_roots(r46_self, ut_self)
    r46_root_id = _imp(client, h, pem(r46_self))["Sectigo Public Server Authentication Root R46"]["id"]
    with _tls_server("".join(pem(c) for c in served), key_pem(leaf_k)) as port:
        d = client.post("/api/domains", headers=h, json={"domain": f"127.0.0.1:{port}"}).json()["id"]
        assert client.post(f"/api/domains/{d}/import-chain", headers=h).status_code == 200
    assert _server(client, h, d) == sorted([
        ("127.0.0.1", "leaf"), ("Sectigo Public Server Authentication CA EV R36", "intermediate"),
        ("Sectigo Public Server Authentication Root R46", "intermediate"),
        ("USERTrust RSA Certification Authority", "intermediate"), ("AAA Certificate Services", "root")])
    certs = client.get("/api/certificates", headers=h, params={"limit": 100}).json()
    certs = certs["items"] if isinstance(certs, dict) else certs
    r36 = next(c for c in certs if c["name"] == "Sectigo Public Server Authentication CA EV R36")
    assert r36["parent_id"] == r46_root_id
