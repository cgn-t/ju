"""Canlı doğrulama testleri: gerçek bir TLS sunucusu ayağa kaldırıp
leaf sertifikayı sunar, live-check'in match/mismatch/unreachable durumlarını doğrular.

Sunulan sertifika ÇALIŞMA ANINDA `certgen` ile üretilir (statik bir fixture dosyası
DEĞİL) — böylece geçerlilik penceresi her zaman "şu an"a göre ayarlanır ve zaman
ilerledikçe (fixture sertifikasının süresi dolarak) test kırılmaz."""

import json
import socket
import ssl
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from app.services.live_check import parse_target
from tests import certgen


def test_parse_target_variants():
    assert parse_target("trade.aaakkk.com") == ("trade.aaakkk.com", 443)
    assert parse_target("xxx.aaakkk.com:8228(Bloomberg)") == ("xxx.aaakkk.com", 8228)
    assert parse_target("*.aaakkk.com")[0] is None
    assert parse_target("")[0] is None
    assert parse_target("host.aaakkk.com:bozukport") == ("host.aaakkk.com", 443)


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """Çalışma anında üretilen bir leaf sertifikayı sunan minimal TLS sunucusu.
    (port, sertifika_pem) döner — testler bu PEM'i JUMBO'ya kendileri import eder
    (paylaşılan test DB'sindeki başka bir testin sertifikasına bağımlı olmaz)."""
    ca, ca_key = certgen.make_ca("Live Check Test CA")
    leaf, leaf_key = certgen.make_leaf(
        ca, ca_key, "live-check-test.local",
        not_before=datetime.utcnow() - timedelta(days=1), days=3650,
        san=["live-check-test.local"])
    leaf_pem = certgen.pem(leaf)

    cert_dir = tmp_path_factory.mktemp("tls_server_certs")
    cert_path = cert_dir / "leaf.pem"
    key_path = cert_dir / "leaf.key"
    cert_path.write_text(leaf_pem)
    key_path.write_text(certgen.key_pem(leaf_key))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
    stop = threading.Event()

    def serve():
        server.settimeout(0.3)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                context.wrap_socket(conn, server_side=True).close()
            except Exception:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port, leaf_pem
    stop.set()
    thread.join(timeout=2)
    server.close()


def _make_domain(client, auth_headers, name):
    r = client.post("/api/domains", headers=auth_headers, json={"domain": name})
    assert r.status_code == 200
    return r.json()["id"]


def _import_pem(client, auth_headers, filename, pem_text):
    r = client.post("/api/certificates/import", headers=auth_headers,
                    files={"file": (filename, pem_text.encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["cert_type"] == "leaf")


@contextmanager
def _tls_server(cert_pem: str, key_pem_text: str):
    """Verilen sertifika+anahtarı (zincir olabilir) sunan geçici TLS sunucusu (port döner)."""
    with tempfile.NamedTemporaryFile("w", suffix=".pem") as cf, \
         tempfile.NamedTemporaryFile("w", suffix=".key") as kf:
        cf.write(cert_pem)
        cf.flush()
        kf.write(key_pem_text)
        kf.flush()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cf.name, kf.name)
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        port = server.getsockname()[1]
        stop = threading.Event()

        def serve():
            server.settimeout(0.3)
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                try:
                    context.wrap_socket(conn, server_side=True).close()
                except Exception:
                    conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            stop.set()
            thread.join(timeout=2)
            server.close()


def test_live_check_match(client, auth_headers, tls_server):
    port, served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port}")
    # Sunucunun SUNDUĞU sertifikayı BİZZAT import ediyoruz — "envanterdeki ilk leaf'i al"
    # gibi kırılgan bir varsayıma değil, doğrudan aynı sertifikaya bağlıyız.
    leaf_id = _import_pem(client, auth_headers, "served-leaf.pem", served_pem)
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": leaf_id, "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["live_check_status"] == "match"
    assert "matched_certificate" in (r.json()["live_check_detail"] or "")


def test_live_check_mismatch(client, auth_headers, tls_server):
    port, _served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port}(yanlis-esleme)")
    # Sunulandan FARKLI, bu teste özel taze bir sertifika üretip eşliyoruz — paylaşılan
    # DB'de "herhangi bir root sertifika var mı" varsayımına bağımlı olmadan.
    other_ca, other_ca_key = certgen.make_ca("Mismatch Test CA")
    other_leaf, _ = certgen.make_leaf(other_ca, other_ca_key, "other-cert.local",
                                      not_before=datetime.utcnow(), days=365,
                                      san=["other-cert.local"])
    other_id = _import_pem(client, auth_headers, "other.pem", certgen.pem(other_leaf))
    client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                json={"certificate_id": other_id, "mapping_type": "server"})
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "mismatch"


def test_live_check_no_mapping(client, auth_headers, tls_server):
    port, _served_pem = tls_server
    domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port} (eslemesiz)")
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "no_mapping"


def test_live_check_unreachable(client, auth_headers):
    domain_id = _make_domain(client, auth_headers, "127.0.0.1:1")  # kapalı port
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "unreachable"


def test_live_check_wildcard_not_checkable(client, auth_headers):
    domain_id = _make_domain(client, auth_headers, "*.jumbo-test.com")
    r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
    assert r.json()["live_check_status"] == "not_checkable"


def test_live_check_per_level_type_aware(client, auth_headers):
    """Asıl bug fix: intermediate değişince leaf/root 'leaf ile eşleşmedi' diye YANLIŞ
    mismatch almamalı — her seviye kendi tipiyle (leaf↔leaf, root↔root, intermediate↔intermediate)
    karşılaştırılır."""
    h = auth_headers
    root, root_key = certgen.make_ca("LC MultiLevel Root")
    inter_old, inter_old_key = certgen.make_intermediate(root, root_key, "LC MultiLevel Inter OLD")
    inter_new, _ = certgen.make_intermediate(root, root_key, "LC MultiLevel Inter NEW")
    leaf, leaf_key = certgen.make_leaf(inter_old, inter_old_key, "lc-multilevel.test",
                                       san=["lc-multilevel.test"])

    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(inter_old)
                                              + certgen.pem(root)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    served_pem = certgen.pem(leaf) + certgen.pem(inter_new) + certgen.pem(root)
    with _tls_server(served_pem, certgen.key_pem(leaf_key)) as port:
        domain_id = _make_domain(client, h, f"127.0.0.1:{port}(lc-multilevel)")
        assert client.post(f"/api/domains/{domain_id}/certificates", headers=h,
                           json={"certificate_id": leaf_id,
                                 "mapping_type": "server"}).status_code == 200

        resp = client.post(f"/api/domains/{domain_id}/live-check", headers=h)
        assert resp.status_code == 200
        body = resp.json()
        assert body["live_check_status"] == "mismatch"
        levels = json.loads(body["live_check_detail"])["levels"]
        assert levels["leaf"]["status"] == "match", "intermediate değişti diye leaf yanlış mismatch almamalı"
        assert levels["root"]["status"] == "match", "intermediate değişti diye root yanlış mismatch almamalı"
        assert levels["intermediate"]["status"] == "mismatch"


def test_live_check_root_not_served_adds_note_without_breaking_match(client, auth_headers):
    """Root TLS el sıkışmasında pratikte hiç gönderilmez — bu BİLGİ notu olarak eklenir,
    genel durumu bozmaz (protokol kısıtı, kod hatası değil)."""
    h = auth_headers
    root, root_key = certgen.make_ca("LC RootNote Root")
    leaf, leaf_key = certgen.make_leaf(root, root_key, "lc-rootnote.test", san=["lc-rootnote.test"])
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(root)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    leaf_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    with _tls_server(certgen.pem(leaf), certgen.key_pem(leaf_key)) as port:  # root GÖNDERİLMİYOR
        domain_id = _make_domain(client, h, f"127.0.0.1:{port}(lc-rootnote)")
        assert client.post(f"/api/domains/{domain_id}/certificates", headers=h,
                           json={"certificate_id": leaf_id,
                                 "mapping_type": "server"}).status_code == 200

        resp = client.post(f"/api/domains/{domain_id}/live-check", headers=h)
        body = resp.json()
        assert body["live_check_status"] == "match"
        detail = json.loads(body["live_check_detail"])
        assert "root_note" in detail


def test_live_check_disabled_setting_skips_scheduled_scan(client, auth_headers):
    """'live_check.enabled' kapalıyken check_all_domains (zamanlanmış iş) atlanır — manuel
    tetik (/domains/{id}/live-check) bundan bağımsız her zaman çalışır."""
    from app.services.live_check import check_all_domains

    h = auth_headers
    domain_id = _make_domain(client, h, "lc-disabled-toggle.test")
    assert client.put("/api/settings/live_check", headers=h,
                      json={"enabled": False}).status_code == 200
    try:
        check_all_domains()
        dom = client.get(f"/api/domains/{domain_id}", headers=h).json()
        assert dom["live_check_at"] is None, "enabled=False iken zamanlanmış tarama hiç çalışmamalı"
    finally:
        client.put("/api/settings/live_check", headers=h, json={"enabled": True})


def test_live_check_proactively_syncs_leaf_rotation_without_import_chain(client, auth_headers):
    """Günlük canlı doğrulama, import-chain çağrılmadan da (tek TLS bağlantısıyla) zincir
    senkronizasyonu yapıp devir önerisi üretmeli (madde 7 — tek taramaya birleşik)."""
    h = auth_headers
    ca, ca_key = certgen.make_ca("LC Sync Root")
    leaf_old, _ = certgen.make_leaf(ca, ca_key, "lc-sync.test", san=["lc-sync.test"],
                                    not_before=datetime(2026, 1, 1))
    leaf_new, leaf_new_key = certgen.make_leaf(ca, ca_key, "lc-sync.test", san=["lc-sync.test"],
                                               not_before=datetime(2026, 6, 1))
    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf_old) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    leaf_old_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    with _tls_server(certgen.pem(leaf_new) + certgen.pem(ca),
                     certgen.key_pem(leaf_new_key)) as port:
        domain_id = _make_domain(client, h, f"127.0.0.1:{port}(lc-sync)")
        assert client.post(f"/api/domains/{domain_id}/certificates", headers=h,
                           json={"certificate_id": leaf_old_id,
                                 "mapping_type": "server"}).status_code == 200

        resp = client.post(f"/api/domains/{domain_id}/live-check", headers=h)
        assert resp.json()["live_check_status"] == "mismatch"

        props = [p for p in client.get("/api/proposals", headers=h,
                                       params={"status": "pending"}).json()
                if p["domain_id"] == domain_id and p["old_cert_id"] == leaf_old_id]
        assert len(props) == 1, "live-check kendisi import-chain çağrılmadan devir önerisi üretmeli"
        assert props[0]["mapping_type"] == "server"


def test_import_chain_two_intermediates_bind_without_spurious_proposal(client, auth_headers):
    """chain_sync.py bug fix: zincirde İKİ 'intermediate' tipli sertifika varsa (gerçek 2
    katmanlı ara-CA hiyerarşisi), ikisi de bağlanmalı ve birbirini 'rakip' sanıp gereksiz
    bir devir önerisi üretmemeli — attach_certificate ile aynı kök neden, import_chain'in
    kullandığı chain_sync.sync_domain_chain_certs içinde ayrıca doğrulanıyor."""
    h = auth_headers
    root, root_key = certgen.make_ca("LC TwoInter Root")
    inter_a, inter_a_key = certgen.make_intermediate(root, root_key, "LC TwoInter Inter A")
    inter_b, inter_b_key = certgen.make_intermediate(inter_a, inter_a_key, "LC TwoInter Inter B")
    leaf, leaf_key = certgen.make_leaf(inter_b, inter_b_key, "lc-two-inter.test",
                                       san=["lc-two-inter.test"])

    served_pem = certgen.pem(leaf) + certgen.pem(inter_b) + certgen.pem(inter_a) + certgen.pem(root)
    with _tls_server(served_pem, certgen.key_pem(leaf_key)) as port:
        domain_id = _make_domain(client, h, f"127.0.0.1:{port}(lc-two-inter)")
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=h)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["mapped_server"], "leaf server olarak bağlanmalı"

        dom = client.get(f"/api/domains/{domain_id}", headers=h).json()
        server = [c for c in dom["certificates"] if c["mapping_type"] == "server"]
        assert len(server) == 4, "leaf + 2 intermediate + root birlikte bağlanmalı"
        cert_types = [c["cert_type"] for c in server]
        assert cert_types.count("intermediate") == 2

        props = [p for p in client.get("/api/proposals", headers=h,
                                       params={"status": "pending"}).json()
                if p["domain_id"] == domain_id]
        assert props == [], "ilk kurulumda hiçbir devir önerisi oluşmamalı"


def test_import_chain_environment_applies_only_to_newly_created_certs(client, auth_headers):
    """'environment' parametresi (prod|test) yalnız bu istekte YENİ oluşturulan sertifikalara
    uygulanır — zaten envanterde olan bir kaydın ortamı asla ezilmez."""
    h = auth_headers
    ca, ca_key = certgen.make_ca("Env Test CA")
    leaf, leaf_key = certgen.make_leaf(ca, ca_key, "lc-env.test", san=["lc-env.test"])

    r = client.post("/api/certificates/import", headers=h,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(),
                                    "application/x-pem-file")})
    assert r.status_code == 200, r.text
    certs = {c["cert_type"]: c for c in r.json()}
    leaf_id, ca_id = certs["leaf"]["id"], certs["root"]["id"]
    assert client.get(f"/api/certificates/{leaf_id}", headers=h).json()["environment"] is None

    with _tls_server(certgen.pem(leaf) + certgen.pem(ca), certgen.key_pem(leaf_key)) as port:
        domain_id = _make_domain(client, h, f"127.0.0.1:{port}(lc-env)")
        # leaf+ca ikisi de zaten envanterde (az önce import edildi) — hiçbiri YENİ değil
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=h,
                        params={"environment": "test"})
        assert r.status_code == 200, r.text
        assert r.json()["created"] == []

    leaf_after = client.get(f"/api/certificates/{leaf_id}", headers=h).json()
    ca_after = client.get(f"/api/certificates/{ca_id}", headers=h).json()
    assert leaf_after["environment"] is None, "zaten envanterde olan kaydın ortamı EZİLMEMELİ"
    assert ca_after["environment"] is None

    # Geçersiz değer reddedilir
    r2 = client.post(f"/api/domains/{domain_id}/import-chain", headers=h,
                     params={"environment": "staging"})
    assert r2.status_code == 400

    # Hiç envanterde olmayan TAZE bir zincir (YENİ oluşturulacak) 'environment' alır
    ca2, ca2_key = certgen.make_ca("Env Test CA 2")
    leaf2, leaf2_key = certgen.make_leaf(ca2, ca2_key, "lc-env2.test", san=["lc-env2.test"])
    with _tls_server(certgen.pem(leaf2) + certgen.pem(ca2), certgen.key_pem(leaf2_key)) as port2:
        domain_id2 = _make_domain(client, h, f"127.0.0.1:{port2}(lc-env2)")
        r3 = client.post(f"/api/domains/{domain_id2}/import-chain", headers=h,
                         params={"environment": "prod"})
        assert r3.status_code == 200, r3.text
        assert len(r3.json()["created"]) == 2  # leaf2 + ca2 ikisi de YENİ

    dom2 = client.get(f"/api/domains/{domain_id2}", headers=h).json()
    for c in dom2["certificates"]:
        detail = client.get(f"/api/certificates/{c['certificate_id']}", headers=h).json()
        assert detail["environment"] == "prod", "yeni oluşturulan sertifikalar environment almalı"
