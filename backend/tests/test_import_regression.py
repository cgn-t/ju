"""Sertifika içe aktarma ve domainden çekme — regresyon testleri (v3.8.0 düzeltmeleri).

Her test bir bulguyu sabitler; domain testleri gerçek TLS sunucusu (yerel port) kullanır:
  1  pasif sertifika domaine bağlanmaz (içe aktarma, elle bağlama, canlı doğrulama, onay)
  2  yalnız TLS 1.0 konuşan sunucudan zincir çekilir
  3  istemci sertifikası zorunlu TLS 1.2 sunucudan zincir çekilir
  4  kendinden imzalı sunucu sertifikası 'leaf' sayılır, server olarak bağlanır
  5  Manuel Ekle'ye yapıştırılan zincirin tamamı kaydedilir
  6  zincir içe aktarmada oluşan devir önerisi yanıtta döner
  7  PFX parolası boş/yanlış ise parola mesajı verilir
  8  domain alanı https://adres/yol ve IPv6 biçiminde yazılabilir
  9  CN'siz sertifika SAN adıyla görünür
  10 AKI'siz sertifika yayıncısına bağlanır
  11 UTF-16 PEM, TRUSTED CERTIFICATE PEM ve başlıksız base64 okunur
  12 domainden çekilen sertifikada 'Oluşturan' domainin SY ekibidir
"""

import base64
import json
import socket
import ssl
import threading
from datetime import datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.services.cert_parser import parse_upload
from app.services.live_check import parse_target
from tests.certgen import key_pem, make_ca, make_intermediate, make_key, make_leaf, pem


# ---- yardımcılar -------------------------------------------------------------------------

class TlsServer:
    """Yerel portta sertifika sunan küçük TLS sunucusu (her bağlantıda el sıkışıp kapatır)."""

    def __init__(self, tmp_path, cert_pem: str, key: str, *, tls10: bool = False,
                 require_client_cert: bool = False, tls13: bool = False):
        (tmp_path / "srv.pem").write_text(cert_pem)
        (tmp_path / "srv.key").write_text(key)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tmp_path / "srv.pem", tmp_path / "srv.key")
        if tls10:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1
        elif tls13:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        else:
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        if require_client_cert:
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(tmp_path / "srv.pem")
        self.ctx = ctx
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                self.ctx.wrap_socket(conn, server_side=True).close()
            except Exception:
                conn.close()

    def close(self):
        self.sock.close()


def _hier(tag: str):
    root, rk = make_ca(f"{tag} Kok CA")
    inter, ik = make_intermediate(root, rk, f"{tag} Ara CA")
    return root, rk, inter, ik


def _upload(client, auth_headers, data: bytes, name="c.pem", password=None):
    form = {"creator": "admin", "environment": "prod"}
    if password is not None:
        form["password"] = password
    return client.post("/api/certificates/import", headers=auth_headers,
                       files={"file": (name, data)}, data=form)


def _preview(client, auth_headers, data: bytes, name="c.pem", password=None):
    form = {"password": password} if password is not None else {}
    return client.post("/api/certificates/import/preview", headers=auth_headers,
                       files={"file": (name, data)}, data=form)


def _cert_by_name(client, auth_headers, name: str) -> dict:
    rows = client.get("/api/certificates", headers=auth_headers, params={"search": name}).json()
    return next(c for c in rows if c["name"] == name)


def _domain(client, auth_headers, value: str, **extra) -> int:
    r = client.post("/api/domains", headers=auth_headers, json={"domain": value, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _server_names(client, auth_headers, domain_id: int) -> set[str]:
    d = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    return {c["name"] for c in d["certificates"] if c["mapping_type"] == "server"}


# ---- 1) Pasif sertifika -------------------------------------------------------------------

def test_passive_cert_is_not_bound_by_import_chain_attach_or_live_check(client, auth_headers, tmp_path):
    root, rk, inter, ik = _hier("Rg Pasif")
    leaf, key = make_leaf(inter, ik, "rg-eski-portal.ornek.local", san=["rg-eski-portal.ornek.local"])
    assert _upload(client, auth_headers, (pem(leaf) + pem(inter) + pem(root)).encode()).status_code == 200
    cert = _cert_by_name(client, auth_headers, "rg-eski-portal.ornek.local")
    assert client.post(f"/api/certificates/{cert['id']}/deactivate",
                       headers=auth_headers).status_code == 200

    srv = TlsServer(tmp_path, pem(leaf) + pem(inter), key_pem(key))
    try:
        domain_id = _domain(client, auth_headers, f"127.0.0.1:{srv.port}(rg-pasif)")
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers,
                        params={"supersede": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mapped_server"] is None
        assert body["inactive"] == ["rg-eski-portal.ornek.local"]
        assert "rg-eski-portal.ornek.local" not in _server_names(client, auth_headers, domain_id)

        # Canlı doğrulama pasif sertifika için ekleme önerisi üretmez
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.status_code == 200, r.text
        # Sunucuda pasif sertifika durduğu sürece durum yeşil görünmez
        assert r.json()["live_check_status"] == "mismatch"
        assert json.loads(r.json()["live_check_detail"])["inactive_served"] == [
            "rg-eski-portal.ornek.local"]
        from app.db.models import TransferProposal
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            assert db.query(TransferProposal).filter(
                TransferProposal.new_cert_id == cert["id"]).count() == 0
        finally:
            db.close()
    finally:
        srv.close()

    # Elle bağlama: server ve trusted olarak reddedilir
    other = _domain(client, auth_headers, "rg-yeni-portal.ornek.local")
    for mapping_type in ("server", "client"):
        r = client.post(f"/api/domains/{other}/certificates", headers=auth_headers,
                        json={"certificate_id": cert["id"], "mapping_type": mapping_type})
        assert r.status_code == 400, r.text
        assert "pasif" in r.json()["detail"]


def test_pending_add_proposal_is_cancelled_if_cert_became_passive(client, auth_headers):
    from app.db.models import Certificate, Domain
    from app.db.session import SessionLocal
    from app.services import renewal

    root, rk, inter, ik = _hier("Rg Oneri")
    leaf, _ = make_leaf(inter, ik, "rg-oneri.ornek.local")
    assert _upload(client, auth_headers, (pem(leaf) + pem(inter) + pem(root)).encode()).status_code == 200
    cert_id = _cert_by_name(client, auth_headers, "rg-oneri.ornek.local")["id"]
    domain_id = _domain(client, auth_headers, "rg-oneri.ornek.local")
    db = SessionLocal()
    try:
        cert, domain = db.get(Certificate, cert_id), db.get(Domain, domain_id)
        prop = renewal.propose_server_mapping(db, "server_add", cert, domain, username="t",
                                              request=None, via="test")
        assert prop is not None
        cert.is_active = False
        renewal.apply_proposal(db, prop, "t", None)
        assert prop.status == "cancelled"
        assert not cert.domain_mappings
        # Pasif sertifika için yeni ekleme önerisi de doğmaz
        assert renewal.propose_server_mapping(db, "server_add", cert, domain, username="t",
                                              request=None, via="test") is None
        db.rollback()
    finally:
        db.close()


# ---- 2) / 3) Eski TLS ve istemci sertifikası isteyen sunucu --------------------------------

@pytest.mark.parametrize("kind", ["tls10", "mtls12", "mtls13", "tls12"])
def test_probe_reads_chain_from_legacy_and_mtls_servers(client, auth_headers, tmp_path, kind):
    root, rk, inter, ik = _hier(f"Rg {kind}")
    leaf, key = make_leaf(inter, ik, f"rg-{kind}.ornek.local")
    srv = TlsServer(tmp_path, pem(leaf) + pem(inter), key_pem(key),
                    tls10=kind == "tls10", tls13=kind == "mtls13",
                    require_client_cert=kind.startswith("mtls"))
    try:
        r = client.post("/api/domains/probe-chain", headers=auth_headers,
                        json={"domain": f"127.0.0.1:{srv.port}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reachable"] is True, body
        assert [c["name"] for c in body["certificates"]] == [f"rg-{kind}.ornek.local", f"Rg {kind} Ara CA"]
    finally:
        srv.close()


# ---- 4) Kendinden imzalı sunucu sertifikası -----------------------------------------------

def _self_signed(cn: str, *, san: bool = True, key_usage: x509.KeyUsage | None = None):
    """`openssl req -x509` varsayılanı: CA:TRUE, SKI=AKI, (isteğe bağlı) SAN."""
    key = make_key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    b = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2027, 6, 1))
         .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
                        critical=False))
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False)
    if key_usage is not None:
        b = b.add_extension(key_usage, critical=True)
    return b.sign(key, hashes.SHA256()), key


def test_self_signed_server_cert_is_leaf_and_bindable(client, auth_headers, tmp_path):
    cert, key = _self_signed("rg-cihaz.ornek.local")
    assert parse_upload(pem(cert).encode())[0].cert_type == "leaf"
    # SAN'sız ama CN'i sunucu adı olan cihaz sertifikası da leaf
    no_san, _ = _self_signed("rg-cihaz2.ornek.local", san=False)
    assert parse_upload(pem(no_san).encode())[0].cert_type == "leaf"
    # Gerçek kök CA'lar kök kalır
    real_root, _ = make_ca("Rg Gercek Kok CA")
    assert parse_upload(pem(real_root).encode())[0].cert_type == "root"
    signing_root, _ = _self_signed("rg-kok.ornek.local", san=False, key_usage=x509.KeyUsage(
        digital_signature=False, content_commitment=False, key_encipherment=False,
        data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
        encipher_only=False, decipher_only=False))
    assert parse_upload(pem(signing_root).encode())[0].cert_type == "root"

    srv = TlsServer(tmp_path, pem(cert), key_pem(key))
    try:
        domain_id = _domain(client, auth_headers, f"127.0.0.1:{srv.port}(rg-cihaz)")
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["mapped_server"] == "rg-cihaz.ornek.local"
    finally:
        srv.close()
    # Elle bağlama da çalışır
    other = _domain(client, auth_headers, "rg-cihaz.ornek.local")
    cid = _cert_by_name(client, auth_headers, "rg-cihaz.ornek.local")["id"]
    r = client.post(f"/api/domains/{other}/certificates", headers=auth_headers,
                    json={"certificate_id": cid, "mapping_type": "server"})
    assert r.status_code == 200, r.text


# ---- 5) Manuel Ekle'ye zincir ---------------------------------------------------------------

def test_manual_add_keeps_whole_pasted_chain(client, auth_headers):
    root, rk, inter, ik = _hier("Rg Manuel")
    leaf, _ = make_leaf(inter, ik, "rg-manuel-zincir.ornek.local")
    r = client.post("/api/certificates", headers=auth_headers, json={
        "name": "", "pem_certificate": pem(leaf) + pem(inter) + pem(root),
        "creator": "admin", "environment": "prod"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "rg-manuel-zincir.ornek.local"
    assert body["cert_type"] == "leaf"
    assert sorted(body["chain_added"]) == ["Rg Manuel Ara CA", "Rg Manuel Kok CA"]
    inter_row = _cert_by_name(client, auth_headers, "Rg Manuel Ara CA")
    assert body["parent_id"] == inter_row["id"]
    assert inter_row["parent_id"] == _cert_by_name(client, auth_headers, "Rg Manuel Kok CA")["id"]
    # Zincir ters sırada yapıştırılsa da form bilgisi uç sertifikaya yazılır
    leaf2, _ = make_leaf(inter, ik, "rg-manuel-ters.ornek.local")
    r = client.post("/api/certificates", headers=auth_headers, json={
        "name": "", "pem_certificate": pem(root) + pem(inter) + pem(leaf2), "creator": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "rg-manuel-ters.ornek.local"
    assert r.json()["chain_added"] == []  # ara ve kök zaten kayıtlı


# ---- 6) Zincir içe aktarmada devir önerisi ---------------------------------------------------

def test_import_chain_reports_transfer_proposal(client, auth_headers, tmp_path):
    root, rk, inter, ik = _hier("Rg Yenileme")
    assert _upload(client, auth_headers, (pem(inter) + pem(root)).encode()).status_code == 200
    old, ko = make_leaf(inter, ik, "rg-odeme.ornek.local", not_before=datetime(2025, 6, 1))
    new, kn = make_leaf(inter, ik, "rg-odeme.ornek.local", not_before=datetime(2026, 3, 1))
    srv = TlsServer(tmp_path, pem(old) + pem(inter), key_pem(ko))
    domain_id = _domain(client, auth_headers, f"127.0.0.1:{srv.port}(rg-odeme)")
    try:
        assert client.post(f"/api/domains/{domain_id}/import-chain",
                           headers=auth_headers).json()["mapped_server"] == "rg-odeme.ornek.local"
    finally:
        srv.close()
    sub = tmp_path / "yeni"
    sub.mkdir()
    srv = TlsServer(sub, pem(new) + pem(inter), key_pem(kn))
    try:
        assert client.put(f"/api/domains/{domain_id}", headers=auth_headers,
                          json={"domain": f"127.0.0.1:{srv.port}(rg-odeme)"}).status_code == 200
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == ["rg-odeme.ornek.local"]
        assert body["superseded"] == ["rg-odeme.ornek.local"]  # formun göstereceği öneri
    finally:
        srv.close()


# ---- 7) PFX parolası --------------------------------------------------------------------------

def test_pfx_password_messages(client, auth_headers):
    root, rk, inter, ik = _hier("Rg PFX")
    leaf, key = make_leaf(inter, ik, "rg-pfx.ornek.local")
    pfx = pkcs12.serialize_key_and_certificates(
        b"pfx", key, leaf, [inter], serialization.BestAvailableEncryption(b"Dogru123"))
    r = _preview(client, auth_headers, pfx, "s.pfx")
    assert r.status_code == 400 and "parola korumalı" in r.json()["detail"]
    r = _preview(client, auth_headers, pfx, "s.pfx", password="yanlis")
    assert r.status_code == 400 and "parolası hatalı" in r.json()["detail"]
    r = _preview(client, auth_headers, pfx, "s.pfx", password="Dogru123")
    assert r.status_code == 200, r.text
    assert {p["name"] for p in r.json()} == {"rg-pfx.ornek.local", "Rg PFX Ara CA"}
    # Gerçekten bozuk dosyada format mesajı kalır
    r = _preview(client, auth_headers, b"\x00\x01bozuk dosya" * 10, "x.cer")
    assert r.status_code == 400 and "formatı tanınamadı" in r.json()["detail"]


# ---- 8) Domain adresi biçimleri ---------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("trade.ornek.com", ("trade.ornek.com", 443)),
    ("xxx.ornek.com:8228(Bloomberg)", ("xxx.ornek.com", 8228)),
    ("https://trade.ornek.com", ("trade.ornek.com", 443)),
    ("https://trade.ornek.com:8443/giris?x=1", ("trade.ornek.com", 8443)),
    ("trade.ornek.com/yol", ("trade.ornek.com", 443)),
    ("  HTTPS://Trade.ornek.com/  ", ("Trade.ornek.com", 443)),
    ("[2001:db8::1]:8443", ("2001:db8::1", 8443)),
    ("[::1]", ("::1", 443)),
    ("2001:db8::1", ("2001:db8::1", 443)),
    ("*.ornek.com", (None, 443)),
    ("https://*.ornek.com", (None, 443)),
])
def test_parse_target_formats(value, expected):
    assert parse_target(value) == expected


def test_probe_with_https_prefix(client, auth_headers, tmp_path):
    root, rk, inter, ik = _hier("Rg Https")
    leaf, key = make_leaf(inter, ik, "rg-https.ornek.local")
    srv = TlsServer(tmp_path, pem(leaf) + pem(inter), key_pem(key))
    try:
        r = client.post("/api/domains/probe-chain", headers=auth_headers,
                        json={"domain": f"https://127.0.0.1:{srv.port}/giris"})
        assert r.json()["reachable"] is True, r.json()
    finally:
        srv.close()


# ---- 9) CN'siz sertifika ---------------------------------------------------------------------

def test_cn_less_cert_takes_san_name(client, auth_headers):
    root, rk, inter, ik = _hier("Rg CN")
    key = make_key()
    cert = (x509.CertificateBuilder().subject_name(x509.Name([])).issuer_name(inter.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2026, 12, 1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("rg-adsiz.ornek.local")]),
                           critical=True)
            .sign(ik, hashes.SHA256()))
    r = _preview(client, auth_headers, pem(cert).encode())
    assert r.status_code == 200, r.text
    assert r.json()[0]["name"] == "rg-adsiz.ornek.local"


# ---- 10) AKI'siz sertifika -------------------------------------------------------------------

def _leaf_without_aki(ca_cert, ca_key, cn: str):
    key = make_key()
    return (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2026, 12, 1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256()))


def test_aki_less_cert_links_to_issuer(client, auth_headers):
    root, rk, inter, ik = _hier("Rg AKIsiz")
    # Önce CA'lar, sonra AKI'siz leaf
    assert _upload(client, auth_headers, (pem(inter) + pem(root)).encode()).status_code == 200
    a = _leaf_without_aki(inter, ik, "rg-akisiz-1.ornek.local")
    assert _upload(client, auth_headers, pem(a).encode()).status_code == 200
    inter_id = _cert_by_name(client, auth_headers, "Rg AKIsiz Ara CA")["id"]
    assert _cert_by_name(client, auth_headers, "rg-akisiz-1.ornek.local")["parent_id"] == inter_id

    # Önce AKI'siz leaf, sonra CA: sonradan bağlanır
    root2, rk2, inter2, ik2 = _hier("Rg AKIsiz2")
    b = _leaf_without_aki(inter2, ik2, "rg-akisiz-2.ornek.local")
    assert _upload(client, auth_headers, pem(b).encode()).status_code == 200
    assert _upload(client, auth_headers, pem(inter2).encode()).status_code == 200
    inter2_id = _cert_by_name(client, auth_headers, "Rg AKIsiz2 Ara CA")["id"]
    assert _cert_by_name(client, auth_headers, "rg-akisiz-2.ornek.local")["parent_id"] == inter2_id

    # Aynı ada sahip ama imzası tutmayan sahte CA'ya bağlanmaz
    fake, fk = make_ca("Rg AKIsiz3 Ara CA")
    real3, rk3 = make_ca("Rg AKIsiz3 Ara CA")
    assert _upload(client, auth_headers, pem(fake).encode()).status_code == 200
    c = _leaf_without_aki(real3, rk3, "rg-akisiz-3.ornek.local")
    assert _upload(client, auth_headers, pem(c).encode()).status_code == 200
    assert _cert_by_name(client, auth_headers, "rg-akisiz-3.ornek.local")["parent_id"] is None


# ---- 11) Metin biçimleri ---------------------------------------------------------------------

def test_text_encodings_and_pem_variants():
    root, rk, inter, ik = _hier("Rg Format")
    leaf, _ = make_leaf(inter, ik, "rg-format.ornek.local")
    text = pem(leaf)
    der = leaf.public_bytes(serialization.Encoding.DER)
    # Notepad "Unicode" (UTF-16 LE, BOM'lu) ve BOM'suz UTF-16
    assert parse_upload(text.encode("utf-16"))[0].name == "rg-format.ornek.local"
    assert parse_upload(text.encode("utf-16-le"))[0].name == "rg-format.ornek.local"
    # OpenSSL -trustout: DER'in ardında güven ayarları
    aux = bytes.fromhex("300c300a06082b06010505070301")
    trusted = ("-----BEGIN TRUSTED CERTIFICATE-----\n"
               + base64.encodebytes(der + aux).decode()
               + "-----END TRUSTED CERTIFICATE-----\n")
    assert parse_upload(trusted.encode())[0].name == "rg-format.ornek.local"
    # Başlıksız base64 (DER'in metin hali)
    assert parse_upload(base64.encodebytes(der))[0].name == "rg-format.ornek.local"
    # Zincir + UTF-16: tüm sertifikalar
    chain = (text + pem(inter) + pem(root)).encode("utf-16")
    assert len(parse_upload(chain)) == 3


def test_utf16_pem_upload_api(client, auth_headers):
    root, rk, inter, ik = _hier("Rg Unicode")
    leaf, _ = make_leaf(inter, ik, "rg-unicode.ornek.local")
    r = _preview(client, auth_headers, pem(leaf).encode("utf-16"))
    assert r.status_code == 200, r.text
    assert r.json()[0]["name"] == "rg-unicode.ornek.local"


# ---- 12) Oluşturan alanı ---------------------------------------------------------------------

def test_chain_import_creator_is_domain_sy_team(client, auth_headers, tmp_path):
    team = client.post("/api/teams", headers=auth_headers,
                       json={"name": "Rg-SY", "type": "SY", "email": "rg-sy@ornek.local"})
    assert team.status_code == 200, team.text
    root, rk, inter, ik = _hier("Rg Olusturan")
    leaf, key = make_leaf(inter, ik, "rg-olusturan.ornek.local")
    srv = TlsServer(tmp_path, pem(leaf) + pem(inter), key_pem(key))
    try:
        domain_id = _domain(client, auth_headers, f"127.0.0.1:{srv.port}(rg-olusturan)",
                            sy_team_id=team.json()["id"])
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.status_code == 200, r.text
    finally:
        srv.close()
    assert _cert_by_name(client, auth_headers, "rg-olusturan.ornek.local")["creator"] == "Rg-SY"
    assert _cert_by_name(client, auth_headers, "Rg Olusturan Ara CA")["creator"] == "Rg-SY"
