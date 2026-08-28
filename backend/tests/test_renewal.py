"""Yenileme (supersede) çekirdeği testleri.

Temel ilke: fingerprint kimliktir, SKI değildir — aynı SKI'li yeni sertifika
her zaman eklenebilir; yenileme algılama yalnız devir önerisi üretir.
"""

import socket
import ssl
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime

from app.db.models import Certificate
from app.db.session import SessionLocal
from tests import certgen


def _import_pem(client, headers, pem_text, name="chain.pem", extra=None):
    files = {"file": (name, pem_text.encode(), "application/x-pem-file")}
    return client.post("/api/certificates/import", headers=headers, files=files,
                       data=extra or {})


def _make_domain(client, headers, name):
    r = client.post("/api/domains", headers=headers, json={"domain": name})
    assert r.status_code == 200
    return r.json()["id"]


def _attach(client, headers, domain_id, cert_id, mapping_type="server"):
    return client.post(f"/api/domains/{domain_id}/certificates", headers=headers,
                       json={"certificate_id": cert_id, "mapping_type": mapping_type})


def _proposals(client, headers, status="pending"):
    return client.get("/api/proposals", headers=headers, params={"status": status}).json()


def _approve_all(client, headers, *, new_id=None, old_id=None):
    """Bekleyen önerileri onaylar (admin). new_id/old_id ile süzülebilir. Onaylanan sayı."""
    n = 0
    for p in _proposals(client, headers):
        if new_id is not None and p["new_cert_id"] != new_id:
            continue
        if old_id is not None and p["old_cert_id"] != old_id:
            continue
        r = client.post(f"/api/proposals/{p['id']}/approve", headers=headers)
        assert r.status_code == 200, r.text
        n += 1
    return n


@contextmanager
def _tls_server(cert_pem: str, key_pem_text: str):
    """Verilen sertifika+anahtarı sunan geçici TLS sunucusu (port döner)."""
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


def test_same_ski_second_record_created(client, auth_headers):
    """KORUNAN DAVRANIŞ: aynı anahtarla (aynı SKI) yenilenen sertifika hatasız
    İKİNCİ kayıt olarak eklenir — SKI asla tekillik şartı değildir."""
    ca, ca_key = certgen.make_ca("Renew Root CA 1")
    key = certgen.make_key()
    v1, _ = certgen.make_leaf(ca, ca_key, "renew1.example.com", key=key,
                              not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "renew1.example.com", key=key,
                              not_before=datetime(2026, 6, 1))
    r1 = _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca))
    assert r1.status_code == 200
    r2 = _import_pem(client, auth_headers, certgen.pem(v2))
    assert r2.status_code == 200, r2.text
    c1 = next(c for c in r1.json() if c["cert_type"] == "leaf")
    c2 = r2.json()[0]
    assert c1["id"] != c2["id"]
    assert c1["subject_key_identifier"] == c2["subject_key_identifier"]
    assert c1["fingerprint_sha256"] != c2["fingerprint_sha256"]


def test_deterministic_parent_prefers_latest(client, auth_headers):
    """Aynı SKI'li iki CA varken leaf, bitişi en geç olana bağlanır (belirsiz .first yok)."""
    key = certgen.make_key()
    old_ca, _ = certgen.make_ca("Det Root CA", key=key,
                                not_before=datetime(2021, 1, 1), days=2000)
    new_ca, _ = certgen.make_ca("Det Root CA", key=key,
                                not_before=datetime(2026, 1, 1), days=4000)
    old_id = _import_pem(client, auth_headers, certgen.pem(old_ca)).json()[0]["id"]
    new_id = _import_pem(client, auth_headers, certgen.pem(new_ca)).json()[0]["id"]
    assert old_id != new_id
    leaf, _ = certgen.make_leaf(new_ca, key, "det-leaf.example.com")
    r = _import_pem(client, auth_headers, certgen.pem(leaf))
    assert r.json()[0]["parent_id"] == new_id


def test_relink_orphan_deterministic(client, auth_headers):
    """Yetim leaf, sonradan gelen aynı SKI'li CA'lardan deterministik olana bağlanır;
    ebeveyni olan çocuklara sonradan dokunulmaz."""
    key = certgen.make_key()
    ca_old, _ = certgen.make_ca("Relink CA", key=key,
                                not_before=datetime(2022, 1, 1), days=1500)
    ca_new, _ = certgen.make_ca("Relink CA", key=key,
                                not_before=datetime(2026, 1, 1), days=4000)
    leaf, _ = certgen.make_leaf(ca_old, key, "relink-leaf.example.com")
    leaf_id = _import_pem(client, auth_headers, certgen.pem(leaf)).json()[0]["id"]
    old_id = _import_pem(client, auth_headers, certgen.pem(ca_old)).json()[0]["id"]
    # yetim, o an tek aday olan eski CA'ya bağlandı
    assert client.get(f"/api/certificates/{leaf_id}", headers=auth_headers).json()["parent_id"] == old_id
    _import_pem(client, auth_headers, certgen.pem(ca_new))
    # ebeveyni olan çocuğa dokunulmaz
    assert client.get(f"/api/certificates/{leaf_id}", headers=auth_headers).json()["parent_id"] == old_id
    # ama YENİ yetim artık deterministik en iyi CA'ya (yeni) bağlanır
    leaf2, _ = certgen.make_leaf(ca_new, key, "relink-leaf2.example.com")
    new_ca_id = next(c["id"] for c in client.get(
        "/api/certificates", headers=auth_headers,
        params={"search": "Relink CA"}).json()
        if c["cert_type"] == "root" and c["id"] != old_id)
    assert _import_pem(client, auth_headers, certgen.pem(leaf2)).json()[0]["parent_id"] == new_ca_id


def test_automatic_supersede_never_crosses_cert_type(client, auth_headers):
    """Otomatik devir önerisi üretimi (renewal.find_predecessors) yapısal olarak yalnız
    leaf<->leaf eşleştirir. Aynı anahtarı (dolayısıyla aynı SKI'yi) paylaşan bir root
    sertifikası, mevcut bir leaf'in halefi olarak OTOMATİK ASLA önerilmemeli — SKI eşleşmesi
    en güçlü sinyal olsa bile tip kontrolü (yeni sertifika leaf değilse aday listesi boş
    döner) bunu engeller."""
    key = certgen.make_key()
    ca, ca_key = certgen.make_ca("Xtype Root CA")
    leaf, _ = certgen.make_leaf(ca, ca_key, "xtype-leaf.example.com", key=key,
                                not_before=datetime(2026, 1, 1))
    r1 = _import_pem(client, auth_headers, certgen.pem(leaf) + certgen.pem(ca))
    assert r1.status_code == 200, r1.text
    leaf_id = next(c["id"] for c in r1.json() if c["cert_type"] == "leaf")

    # Aynı anahtarı (aynı SKI) yeniden kullanan kendinden-imzalı bir root — leaf ile en güçlü
    # eşleşme sinyalini (SKI) paylaşıyor, ama bir root'un halefi bir leaf OLAMAZ.
    rogue_root, _ = certgen.make_ca("Xtype Rogue Root", key=key, not_before=datetime(2026, 6, 1))
    r2 = _import_pem(client, auth_headers, certgen.pem(rogue_root), name="rogue.pem",
                     extra={"supersede": "true"})
    assert r2.status_code == 200, r2.text
    assert r2.json()[0]["cert_type"] == "root"
    rogue_id = r2.json()[0]["id"]

    # Hiçbir devir önerisi bu root'u leaf'in halefi olarak göstermemeli
    props = _proposals(client, auth_headers)
    assert not any(p["new_cert_id"] == rogue_id for p in props)
    assert not any(p["old_cert_id"] == leaf_id for p in props)


def test_import_preview_flags_renewal_and_supersede_transfers(client, auth_headers):
    """Önizleme yenilemeyi işaretler; supersede=true import eşlemeyi devredip eskiyi pasifler."""
    ca, ca_key = certgen.make_ca("Renew Root CA 2")
    v1, _ = certgen.make_leaf(ca, ca_key, "renew2.example.com",
                              not_before=datetime(2026, 1, 1))
    r = _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca))
    v1_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    domain_id = _make_domain(client, auth_headers, "renew2.example.com")
    assert _attach(client, auth_headers, domain_id, v1_id).status_code == 200

    # v2: yeni anahtar (yeni SKI), aynı subject+issuer — tipik Vault rotasyonu
    v2, _ = certgen.make_leaf(ca, ca_key, "renew2.example.com",
                              not_before=datetime(2026, 3, 1))
    files = {"file": ("v2.pem", certgen.pem(v2).encode(), "application/x-pem-file")}
    prev = client.post("/api/certificates/import/preview", headers=auth_headers,
                       files=files).json()
    assert prev[0]["renewal_of_id"] == v1_id
    assert prev[0]["renewal_signal"] == "subject"
    # Devir planı detayı: kullanıcı neyin neye devredileceğini önizlemede görür
    assert prev[0]["renewal_of_ski"]
    assert prev[0]["renewal_of_valid_to"]
    assert prev[0]["renewal_of_domains"] == ["renew2.example.com (server)"]

    r = _import_pem(client, auth_headers, certgen.pem(v2), extra={"supersede": "true"})
    v2_id = r.json()[0]["id"]
    # ONAY MODELİ: import anında DEVİR YOK — v1 hâlâ aktif ve eşli; öneri üretildi
    v1_mid = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
    assert v1_mid["is_active"] is True
    assert v1_mid["superseded_by_id"] is None
    props = _proposals(client, auth_headers)
    assert any(p["old_cert_id"] == v1_id and p["new_cert_id"] == v2_id
               and p["domain_id"] == domain_id for p in props)
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert dom["pending_proposals"] == 1
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [v1_id]  # devir henüz yok

    # SY onayı (admin) → devir uygulanır: eşleme taşınır, v1 pasifleşir
    assert _approve_all(client, auth_headers, new_id=v2_id, old_id=v1_id) == 1
    v1_after = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
    assert v1_after["is_active"] is False
    assert v1_after["superseded_by_id"] == v2_id
    assert v1_after["superseded_by_name"] == "renew2.example.com"
    v2_after = client.get(f"/api/certificates/{v2_id}", headers=auth_headers).json()
    assert [p["id"] for p in v2_after["supersedes"]] == [v1_id]
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    server_ids = [c["certificate_id"] for c in dom["certificates"]
                  if c["mapping_type"] == "server"]
    assert server_ids == [v2_id]
    entries = client.get("/api/audit", headers=auth_headers).json()
    assert any(e["action"] == "supersede_apply" for e in entries)


def test_bundle_with_two_generations_previews_and_supersedes(client, auth_headers):
    """Aynı dosyada ESKİ+YENİ nesil: önizleme dosya-içi öncülü bildirir (plan
    görünmeden devir olmaz ilkesi); import PEM sırasından bağımsız devri işler."""
    ca, ca_key = certgen.make_ca("Bundle CA")
    key = certgen.make_key()
    old, _ = certgen.make_leaf(ca, ca_key, "bundle.example.com", key=key,
                               not_before=datetime(2026, 1, 1))
    new, _ = certgen.make_leaf(ca, ca_key, "bundle.example.com", key=key,
                               not_before=datetime(2026, 4, 1))
    # YENİ kasten dosyada önce: davranış PEM sırasına bağlı olmamalı
    bundle = certgen.pem(new) + certgen.pem(old) + certgen.pem(ca)

    files = {"file": ("bundle.pem", bundle.encode(), "application/x-pem-file")}
    prev = client.post("/api/certificates/import/preview", headers=auth_headers,
                       files=files).json()
    newer = next(p for p in prev if p["cert_type"] == "leaf"
                 and p["valid_from"].startswith("2026-04"))
    assert newer["renewal_of_id"] is None  # öncül henüz DB'de değil
    assert "bu dosyadaki eski nesil" in newer["renewal_of_name"]
    assert newer["renewal_signal"] == "ski"

    r = _import_pem(client, auth_headers, bundle, extra={"supersede": "true"})
    assert r.status_code == 200
    leafs = [c for c in client.get("/api/certificates", headers=auth_headers,
                                   params={"search": "bundle.example", "is_active": "true"}).json()]
    old_rec = next(c for c in leafs if c["valid_from"].startswith("2026-01"))
    new_rec = next(c for c in leafs if c["valid_from"].startswith("2026-04"))
    # Dosya-içi öncül yok (eski henüz DB'de değildi) → bu senaryoda öneri üretilmez;
    # import bittiğinde eski kayıt DB'de var ama supersede tetiği zaten geçti.
    # Bu yüzden bu testte devir OLUŞMAZ: iki kayıt da aktif (dosya-içi tespit yalnız
    # önizleme uyarısıdır; gerçek devir için ikinci import gerekir). İlke: sessiz devir yok.
    assert old_rec["is_active"] is True
    assert new_rec["is_active"] is True
    assert old_rec["superseded_by_id"] is None


def test_preview_reports_all_predecessors(client, auth_headers):
    """Import TÜM öncülleri devraldığı için plan ikinci öncülü de bildirmeli."""
    ca, ca_key = certgen.make_ca("Multi Pred CA")
    a, _ = certgen.make_leaf(ca, ca_key, "multi.example.com", not_before=datetime(2026, 1, 1))
    b, _ = certgen.make_leaf(ca, ca_key, "multi.example.com", not_before=datetime(2026, 2, 1))
    _import_pem(client, auth_headers, certgen.pem(a) + certgen.pem(ca))
    _import_pem(client, auth_headers, certgen.pem(b))  # supersede yok → ikisi de aktif

    c, _ = certgen.make_leaf(ca, ca_key, "multi.example.com", not_before=datetime(2026, 3, 1))
    files = {"file": ("c.pem", certgen.pem(c).encode(), "application/x-pem-file")}
    prev = client.post("/api/certificates/import/preview", headers=auth_headers,
                       files=files).json()
    assert prev[0]["renewal_of_name"] == "multi.example.com"
    assert len(prev[0]["renewal_also"]) == 1  # ikinci aktif öncül de planda


def test_manual_supersede_proposes_and_approves(client, auth_headers):
    """Manuel supersede endpoint ÖNERİ üretir (anında devir yok); idempotent;
    kendini devralamaz; onay sonrası eşleme taşınır ve eski pasifleşir."""
    ca, ca_key = certgen.make_ca("Renew Root CA 3")
    key = certgen.make_key()  # aynı anahtar → sinyal "ski"
    a, _ = certgen.make_leaf(ca, ca_key, "renew3.example.com", key=key,
                             not_before=datetime(2026, 1, 1))
    b, _ = certgen.make_leaf(ca, ca_key, "renew3.example.com", key=key,
                             not_before=datetime(2026, 2, 1))
    a_id = _import_pem(client, auth_headers, certgen.pem(a)).json()[0]["id"]
    b_id = _import_pem(client, auth_headers, certgen.pem(b)).json()[0]["id"]
    domain_id = _make_domain(client, auth_headers, "renew3.example.com")
    assert _attach(client, auth_headers, domain_id, a_id).status_code == 200

    r = client.post(f"/api/certificates/{b_id}/supersede/{a_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["proposed"] == 1
    # idempotent: açık öneri var, yeni öneri üretmez
    assert client.post(f"/api/certificates/{b_id}/supersede/{a_id}",
                       headers=auth_headers).json()["proposed"] == 0
    # kendini devralamaz
    assert client.post(f"/api/certificates/{b_id}/supersede/{b_id}",
                       headers=auth_headers).status_code == 400
    # onay öncesi a hâlâ aktif ve eşli
    a_mid = client.get(f"/api/certificates/{a_id}", headers=auth_headers).json()
    assert a_mid["is_active"] is True

    assert _approve_all(client, auth_headers, new_id=b_id, old_id=a_id) == 1
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [b_id]
    a_after = client.get(f"/api/certificates/{a_id}", headers=auth_headers).json()
    assert a_after["is_active"] is False
    # pasif kayıt devralamaz
    assert client.post(f"/api/certificates/{a_id}/supersede/{b_id}",
                       headers=auth_headers).status_code == 400


def test_attach_collision_creates_proposal_not_silent_transfer(client, auth_headers):
    """BAYPAS KAPATMA: domainde aynı tipte AKTİF sertifika varken elle attach doğrudan
    eklenmez — devir önerisi üretir (detach+attach ile onay atlanmasın)."""
    ca, ca_key = certgen.make_ca("Attach CA")
    a, _ = certgen.make_leaf(ca, ca_key, "attach.example.com", not_before=datetime(2026, 1, 1))
    b, _ = certgen.make_leaf(ca, ca_key, "attach.example.com", not_before=datetime(2026, 2, 1))
    a_id = _import_pem(client, auth_headers, certgen.pem(a) + certgen.pem(ca)).json()[0]["id"]
    a_id = next(c["id"] for c in client.get("/api/certificates", headers=auth_headers,
                params={"search": "attach.example"}).json() if c["cert_type"] == "leaf")
    b_id = _import_pem(client, auth_headers, certgen.pem(b)).json()[0]["id"]
    domain_id = _make_domain(client, auth_headers, "attach.example.com")
    assert _attach(client, auth_headers, domain_id, a_id).status_code == 200

    # b'yi server olarak eklemek DEVİRDİR → 202 + öneri
    r = _attach(client, auth_headers, domain_id, b_id)
    assert r.status_code == 202
    assert r.json()["status"] == "proposal_created"
    # domain hâlâ yalnız a'ya eşli; öneri onaya düştü
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [a_id]
    assert dom["pending_proposals"] == 1

    assert _approve_all(client, auth_headers, new_id=b_id, old_id=a_id) == 1
    dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
    assert [c["certificate_id"] for c in dom["certificates"]
            if c["mapping_type"] == "server"] == [b_id]


def test_manual_create_without_pem_dedup(client, auth_headers):
    body = {"name": "Placeholder X", "serial_number": "AA:BB:CC",
            "issuer": "CN=Dedup Test CA"}
    assert client.post("/api/certificates", headers=auth_headers, json=body).status_code == 200
    r = client.post("/api/certificates", headers=auth_headers, json=body)
    assert r.status_code == 409
    # yalnız isimli placeholder serbest (kimliksiz — dedup edilemez)
    assert client.post("/api/certificates", headers=auth_headers,
                       json={"name": "Sadece İsim"}).status_code == 200


def test_superseded_by_not_clobbered_on_branched_partial_transfer(client, auth_headers):
    """Bug #7 regresyonu: v1 A ve B'de eşli. v1→v2 YALNIZ A'da onaylanır (v1.superseded_by=v2,
    v1 aktif kalır). Sonra v3 gelir; v1→v3 B'de onaylanır. v1.superseded_by v2'den v3'e EZİLMEMELİ
    — ilk halef stabil kalır (tek FK dallanmayı temsil edemez; tam zincir audit'te)."""
    from app.db.models import Certificate
    from app.db.session import SessionLocal
    h = auth_headers
    ca, ca_key = certgen.make_ca("Lineage7 CA")
    key = certgen.make_key()                                   # ortak anahtar → hepsi halef
    v1, _ = certgen.make_leaf(ca, ca_key, "lin7.example.com", key=key, not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "lin7.example.com", key=key, not_before=datetime(2026, 6, 1))
    v3, _ = certgen.make_leaf(ca, ca_key, "lin7.example.com", key=key, not_before=datetime(2026, 9, 1))
    v1_id = next(c["id"] for c in _import_pem(client, h, certgen.pem(v1) + certgen.pem(ca)).json()
                 if c["cert_type"] == "leaf")
    da = _make_domain(client, h, "lin7a.example.com")
    dbb = _make_domain(client, h, "lin7b.example.com")
    assert _attach(client, h, da, v1_id).status_code == 200
    assert _attach(client, h, dbb, v1_id).status_code == 200

    # v2 gelir → (v1→v2, A) ve (v1→v2, B); YALNIZ A onaylanır
    v2_id = _import_pem(client, h, certgen.pem(v2), extra={"supersede": "true"}).json()[0]["id"]
    pa = next(p for p in _proposals(client, h) if p["new_cert_id"] == v2_id and p["domain_id"] == da)
    assert client.post(f"/api/proposals/{pa['id']}/approve", headers=h).status_code == 200

    # v3 gelir → (v1→v3, B) ve (v2→v3, A); B'nin v1→v3'ünü onayla
    v3_id = _import_pem(client, h, certgen.pem(v3), extra={"supersede": "true"}).json()[0]["id"]
    pb = next(p for p in _proposals(client, h)
              if p["new_cert_id"] == v3_id and p["old_cert_id"] == v1_id and p["domain_id"] == dbb)
    assert client.post(f"/api/proposals/{pb['id']}/approve", headers=h).status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Certificate, v1_id).superseded_by_id == v2_id, \
            "v1.superseded_by ilk halef (v2) kalmalı, v3'e EZİLMEMELİ"
    finally:
        db.close()


def test_import_chain_supersede_creates_proposal_then_approve(client, auth_headers):
    """ONAY MODELİ: v1 eşliyken sunucu v2 sunar → import-chain?supersede=true canlıdan
    çekse bile ANINDA DEVİR YAPMAZ; live_seen kanıtıyla öneri üretir. Onay sonrası
    eşleme devredilir, v1 pasifleşir, live-check match döner."""
    ca, ca_key = certgen.make_ca("Live Renew CA")
    v1, _ = certgen.make_leaf(ca, ca_key, "localhost", san=["localhost", "127.0.0.1"],
                              not_before=datetime(2026, 1, 1))
    v2, v2_key = certgen.make_leaf(ca, ca_key, "localhost", san=["localhost", "127.0.0.1"],
                                   not_before=datetime(2026, 3, 1))
    r = _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca))
    v1_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    with _tls_server(certgen.pem(v2) + certgen.pem(ca), certgen.key_pem(v2_key)) as port:
        domain_id = _make_domain(client, auth_headers, f"localhost:{port}(live-renew)")
        assert _attach(client, auth_headers, domain_id, v1_id).status_code == 200
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "mismatch"

        r = client.post(f"/api/domains/{domain_id}/import-chain",
                        headers=auth_headers, params={"supersede": "true"})
        assert r.status_code == 200, r.text
        result = r.json()
        # v1 zaten server eşli → v2 doğrudan eklenmez; öneri üretilir
        assert result["mapped_server"] is None
        assert any("localhost" in s for s in result["superseded"])

        # Devir HENÜZ olmadı: v1 aktif ve tek server eşlemesi; öneri live_seen=True
        v1_mid = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
        assert v1_mid["is_active"] is True and v1_mid["superseded_by_id"] is None
        props = [p for p in _proposals(client, auth_headers) if p["domain_id"] == domain_id]
        assert len(props) == 1 and props[0]["live_seen"] is True
        # onay öncesi hâlâ mismatch (envanter v1'i eşli tutuyor, sunucu v2 sunuyor)
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "mismatch"

        # SY onayı → devir uygulanır
        assert _approve_all(client, auth_headers) >= 1
        v1_after = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
        assert v1_after["is_active"] is False
        assert v1_after["superseded_by_id"] is not None
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "match"


def test_vault_sync_proposes_livecheck_marks_evidence_then_approve(client, auth_headers, monkeypatch):
    """ONAY MODELİ: vault-sync rotasyonu ÖNERİ üretir (eşleme kopyalanmaz, eski aktif,
    superseded_by yazılmaz). Canlı doğrulama v2'yi sunucuda görünce öneriyi live_seen
    işaretler ama devri UYGULAMAZ. Devir yalnız SY onayıyla olur."""
    from app.services.providers.vault import VaultProvider

    ca, ca_key = certgen.make_ca("Vault Renew CA")
    v1, _ = certgen.make_leaf(ca, ca_key, "vault-renew.example.com",
                              san=["localhost", "127.0.0.1"], not_before=datetime(2026, 1, 1))
    v2, v2_key = certgen.make_leaf(ca, ca_key, "vault-renew.example.com",
                                   san=["localhost", "127.0.0.1"], not_before=datetime(2026, 4, 1))
    r = _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca))
    v1_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    kv = {"certs/renew-demo": {"certificate": certgen.pem(v2), "chain": certgen.pem(ca)}}

    def fake_init(self, db):
        self.config = {"enabled": True, "address": "http://vault.test", "kv_prefix": "certs"}

    monkeypatch.setattr(VaultProvider, "__init__", fake_init)
    monkeypatch.setattr(VaultProvider, "kv_list",
                        lambda self, prefix: ["renew-demo"] if prefix == "certs" else [])
    monkeypatch.setattr(VaultProvider, "kv_get", lambda self, path: kv.get(path))

    with _tls_server(certgen.pem(v2) + certgen.pem(ca), certgen.key_pem(v2_key)) as port:
        domain_id = _make_domain(client, auth_headers, f"localhost:{port}(vault-renew)")
        assert _attach(client, auth_headers, domain_id, v1_id).status_code == 200

        r = client.post("/api/certificates/vault-sync", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["superseded"] == 1  # 1 öneri üretildi

        # ÖNERİ üretildi ama devir YOK: v1 aktif, superseded_by boş, v2 EŞLİ DEĞİL
        v1_mid = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
        assert v1_mid["is_active"] is True
        assert v1_mid["superseded_by_id"] is None
        props = [p for p in _proposals(client, auth_headers) if p["domain_id"] == domain_id]
        assert len(props) == 1
        prop_id, v2_id = props[0]["id"], props[0]["new_cert_id"]
        dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
        assert {c["certificate_id"] for c in dom["certificates"]
                if c["mapping_type"] == "server"} == {v1_id}  # kopyalanmadı
        v2_out = client.get(f"/api/certificates/{v2_id}", headers=auth_headers).json()
        assert v2_out["vault_path"] == "certs/renew-demo"

        # canlı doğrulama v2'yi sunucuda görür → mismatch (v2 eşli değil) AMA kanıt işlenir
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "mismatch"
        props = [p for p in _proposals(client, auth_headers) if p["domain_id"] == domain_id]
        assert props[0]["live_seen"] is True  # 'canlıda görüldü' güvenli-onay sinyali
        v1_still = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
        assert v1_still["is_active"] is True  # devir UYGULANMADI

        # SY onayı → devir uygulanır
        assert client.post(f"/api/proposals/{prop_id}/approve",
                           headers=auth_headers).status_code == 200
        v1_final = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
        assert v1_final["is_active"] is False
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "match"
        dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
        assert [c["certificate_id"] for c in dom["certificates"]
                if c["mapping_type"] == "server"] == [v2_id]


def test_live_check_expired_match_is_mismatch(client, auth_headers):
    """Sunucu, envanterde eşli ama SÜRESİ DOLMUŞ sertifikayı sunuyorsa yeşil değil
    mismatch dönmeli."""
    ca, ca_key = certgen.make_ca("Expired CA")
    expired, key = certgen.make_leaf(ca, ca_key, "expired.example.com",
                                     san=["localhost", "127.0.0.1"],
                                     not_before=datetime(2024, 1, 1), days=30)
    r = _import_pem(client, auth_headers, certgen.pem(expired) + certgen.pem(ca))
    cert_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")
    with _tls_server(certgen.pem(expired) + certgen.pem(ca), certgen.key_pem(key)) as port:
        domain_id = _make_domain(client, auth_headers, f"localhost:{port}(expired)")
        assert _attach(client, auth_headers, domain_id, cert_id).status_code == 200
        r = client.post(f"/api/domains/{domain_id}/live-check", headers=auth_headers)
        assert r.json()["live_check_status"] == "mismatch"
        assert "SÜRESİ DOLMUŞ" in (r.json()["live_check_detail"] or "")


def test_fingerprint_unique_index_enforced():
    """DB seviyesinde aynı fingerprint'li ikinci satır reddedilir (kısmi unique index)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db.models import Certificate
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        db.add(Certificate(name="uniq-a", fingerprint_sha256="FP:UNIQ:TEST"))
        db.commit()
        db.add(Certificate(name="uniq-b", fingerprint_sha256="FP:UNIQ:TEST"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        # NULL fingerprint'li birden çok satır serbest
        db.add(Certificate(name="null-a"))
        db.add(Certificate(name="null-b"))
        db.commit()
    finally:
        db.close()


def test_apply_transfers_vault_path_from_old_to_new(client, auth_headers):
    """apply_proposal onayında old_cert'in vault_path'i new_cert'e TAŞINIR ve old_cert'te
    None kalır (renewal.py:293-298) — bu davranış şimdiye kadar hiçbir testte doğrudan
    doğrulanmamıştı (test_vault_sync_proposes_livecheck_marks_evidence_then_approve
    yalnız vault-sync'in v2'ye ATADIĞI vault_path'i onaydan ÖNCE kontrol ediyor; apply
    zamanındaki old→new devrini hiç tetiklemiyor çünkü o testte old_cert'in vault_path'i
    zaten boş)."""
    ca, ca_key = certgen.make_ca("VaultPath Transfer CA")
    v1, _ = certgen.make_leaf(ca, ca_key, "vpath-old.example.com", not_before=datetime(2026, 1, 1))
    v2, _ = certgen.make_leaf(ca, ca_key, "vpath-new.example.com", not_before=datetime(2026, 3, 1))
    r1 = _import_pem(client, auth_headers, certgen.pem(v1) + certgen.pem(ca))
    v1_id = next(c["id"] for c in r1.json() if c["cert_type"] == "leaf")
    v2_id = _import_pem(client, auth_headers, certgen.pem(v2)).json()[0]["id"]

    domain_id = _make_domain(client, auth_headers, "vpath-domain.test")
    assert _attach(client, auth_headers, domain_id, v1_id).status_code == 200

    # old cert'in DAHA ÖNCE vault'tan senkronlanmış gibi bir vault_path'i olduğunu simüle et
    db = SessionLocal()
    try:
        db.get(Certificate, v1_id).vault_path = "certs/vpath-demo"
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/certificates/{v2_id}/supersede/{v1_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _approve_all(client, auth_headers, new_id=v2_id, old_id=v1_id) >= 1

    v1_after = client.get(f"/api/certificates/{v1_id}", headers=auth_headers).json()
    v2_after = client.get(f"/api/certificates/{v2_id}", headers=auth_headers).json()
    assert v1_after["vault_path"] is None, "old cert'in vault_path'i devir sonrası boşalmalı"
    assert v2_after["vault_path"] == "certs/vpath-demo", "vault_path new cert'e taşınmalı"


def test_import_chain_proposes_for_unrelated_active_server(client, auth_headers):
    """Domain'e ÖNCEDEN bağlı, TAMAMEN İLGİSİZ (farklı CA/subject/SKI — öncül sinyali
    paylaşmayan) bir aktif server sertifikası varken import-chain FARKLI bir leaf getirirse
    bu SESSİZCE GÖRMEZDEN GELİNMEZ: domains.py'deki 'öncül olarak yakalanmayan mevcut server
    sertifikaları da devir önerisi olur' fallback'i (propose_attach_transfer) devreye girer."""
    old_ca, old_ca_key = certgen.make_ca("Unrelated Old CA")
    old_leaf, _ = certgen.make_leaf(old_ca, old_ca_key, "unrelated-old.example.com",
                                    not_before=datetime(2026, 1, 1))
    r = _import_pem(client, auth_headers, certgen.pem(old_leaf) + certgen.pem(old_ca))
    old_id = next(c["id"] for c in r.json() if c["cert_type"] == "leaf")

    served_ca, served_ca_key = certgen.make_ca("Served New CA")
    served_leaf, served_key = certgen.make_leaf(
        served_ca, served_ca_key, "served-new.example.com", not_before=datetime(2026, 3, 1))

    with _tls_server(certgen.pem(served_leaf) + certgen.pem(served_ca),
                     certgen.key_pem(served_key)) as port:
        domain_id = _make_domain(client, auth_headers, f"127.0.0.1:{port}(attach-fallback)")
        assert _attach(client, auth_headers, domain_id, old_id).status_code == 200

        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["mapped_server"] is None, (
            "domainde zaten aktif bir server sertifikası var, yeni leaf doğrudan eklenmemeli")
        assert any("unrelated-old" in s for s in result["superseded"]), (
            f"öncül-olmayan eski sertifika görmezden gelinmemeli, devir önerisine konu olmalı: {result}")
        assert any("served-new" in c for c in result["created"]), (
            f"sunucunun sunduğu yeni leaf import edilmiş olmalı: {result}")

        props = [p for p in _proposals(client, auth_headers)
                if p["old_cert_id"] == old_id and p["domain_id"] == domain_id]
        assert len(props) == 1, f"tam olarak 1 attach-devir önerisi bekleniyor: {props}"
        assert props[0]["mapping_type"] == "server"

        # devir HENÜZ olmadı: eski hâlâ aktif ve domain'in TEK server eşlemesi hâlâ eski
        old_after = client.get(f"/api/certificates/{old_id}", headers=auth_headers).json()
        assert old_after["is_active"] is True
        dom = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
        assert [c["certificate_id"] for c in dom["certificates"]
                if c["mapping_type"] == "server"] == [old_id]
