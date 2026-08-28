def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login-json", json={"username": "admin", "password": "yanlis"})
    assert r.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/certificates").status_code == 401


def test_import_chain_and_hierarchy(client, auth_headers, fixtures_dir):
    with open(fixtures_dir / "fullchain.pem", "rb") as f:
        r = client.post("/api/certificates/import", headers=auth_headers,
                        files={"file": ("fullchain.pem", f)})
    assert r.status_code == 200, r.text
    certs = {c["cert_type"]: c for c in r.json()}
    assert certs["intermediate"]["parent_id"] == certs["root"]["id"]
    assert certs["leaf"]["parent_id"] == certs["intermediate"]["id"]

    # Aynı dosya ikinci kez -> 409
    with open(fixtures_dir / "fullchain.pem", "rb") as f:
        r = client.post("/api/certificates/import", headers=auth_headers,
                        files={"file": ("fullchain.pem", f)})
    assert r.status_code == 409


def test_import_preview_marks_existing(client, auth_headers, fixtures_dir):
    with open(fixtures_dir / "leaf.der", "rb") as f:
        r = client.post("/api/certificates/import/preview", headers=auth_headers,
                        files={"file": ("leaf.der", f)})
    assert r.status_code == 200
    assert r.json()[0]["already_exists"] is True
    assert r.json()[0]["resolved_parent_name"] == "JUMBO Test Intermediate CA"


def test_domain_crud_and_mapping(client, auth_headers):
    r = client.post("/api/domains", headers=auth_headers,
                    json={"domain": "test.jumbo-test.com", "mail_addresses": "ops@test.com"})
    assert r.status_code == 200
    domain_id = r.json()["id"]

    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf")
    r = client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                    json={"certificate_id": leaf["id"], "mapping_type": "server"})
    assert r.status_code == 200
    assert r.json()["server_days_left"] is not None

    # Aynı eşleme ikinci kez -> 409
    r = client.post(f"/api/domains/{domain_id}/certificates", headers=auth_headers,
                    json={"certificate_id": leaf["id"], "mapping_type": "server"})
    assert r.status_code == 409

    r = client.put(f"/api/domains/{domain_id}", headers=auth_headers,
                   json={"cert_owner": "32bit(ET) Firması"})
    assert r.json()["cert_owner"] == "32bit(ET) Firması"

    r = client.delete(f"/api/domains/{domain_id}/certificates/{leaf['id']}",
                      headers=auth_headers, params={"mapping_type": "server"})
    assert r.status_code == 200


def test_manual_certificate_with_existing_pem_rejected(client, auth_headers, fixtures_dir):
    # Import edilmiş kökü manuel eklemeye çalışmak fingerprint kontrolüne takılmalı
    pem = (fixtures_dir / "root.pem").read_text()
    r = client.post("/api/certificates", headers=auth_headers,
                    json={"name": "", "pem_certificate": pem})
    assert r.status_code == 409
    assert "zaten kayıtlı" in r.json()["detail"]


def test_certificate_environment_field(client, auth_headers):
    # Create: environment opsiyonel, verilirse döner
    r = client.post("/api/certificates", headers=auth_headers,
                    json={"name": "env-test-cert", "environment": "prod"})
    assert r.status_code == 200, r.text
    cert_id = r.json()["id"]
    assert r.json()["environment"] == "prod"

    # Update: prod -> test
    r = client.put(f"/api/certificates/{cert_id}", headers=auth_headers,
                   json={"environment": "test"})
    assert r.status_code == 200
    assert r.json()["environment"] == "test"

    # Update: null ile temizlenir
    r = client.put(f"/api/certificates/{cert_id}", headers=auth_headers,
                   json={"environment": None})
    assert r.status_code == 200
    assert r.json()["environment"] is None

    # Geçersiz değer -> 422 (API/DB seviyesinde hâlâ opsiyonel, ama geçerli set dışına izin yok)
    r = client.post("/api/certificates", headers=auth_headers,
                    json={"name": "env-test-cert-2", "environment": "staging"})
    assert r.status_code == 422

    # environment hiç verilmeden create -> None (zorunluluk yalnız frontend formunda)
    r = client.post("/api/certificates", headers=auth_headers, json={"name": "env-test-cert-3"})
    assert r.status_code == 200
    assert r.json()["environment"] is None


def test_import_fills_san_and_fingerprint(client, auth_headers):
    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf")
    assert "*.jumbo-test.com" in (leaf["san"] or "")
    assert leaf["fingerprint_sha256"] and len(leaf["fingerprint_sha256"].split(":")) == 32


def test_certificate_chain(client, auth_headers):
    certs = client.get("/api/certificates", headers=auth_headers).json()
    leaf = next(c for c in certs if c["cert_type"] == "leaf")
    chain = client.get(f"/api/certificates/{leaf['id']}/chain", headers=auth_headers).json()
    # ata zinciri kökten aşağıya sıralı: root, intermediate
    assert [a["cert_type"] for a in chain["ancestors"]] == ["root", "intermediate"]
    assert chain["self"]["id"] == leaf["id"]
    # root'un chain'i: ata yok, kendisi root, children'da intermediate var
    root = next(c for c in certs if c["cert_type"] == "root")
    root_chain = client.get(f"/api/certificates/{root['id']}/chain", headers=auth_headers).json()
    assert root_chain["ancestors"] == []
    assert any(ch["cert_type"] == "intermediate" for ch in root_chain["children"])


def test_certificate_delete_admin_only(client, auth_headers):
    # RBAC: editör yetkisi bir SY takımı üyeliğinden gelir. SY üyesi sertifikayı ne SİLEBİLİR (403)
    # ne de PASİFE ALABİLİR (403) — silme ve aktif/pasif durumu yalnız admin.
    uid = client.post("/api/users", headers=auth_headers,
                      json={"username": "editor1", "password": "sifre123"}).json()["id"]
    team = client.post("/api/teams", headers=auth_headers,
                       json={"name": "CertSY", "type": "SY"}).json()
    client.post(f"/api/teams/{team['id']}/members", headers=auth_headers, json={"user_id": uid})
    r = client.post("/api/auth/login-json", json={"username": "editor1", "password": "sifre123"})
    editor_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf")
    assert client.delete(f"/api/certificates/{leaf['id']}", headers=editor_headers).status_code == 403
    # editör pasife ALAMAZ — POST /deactivate ve PUT is_active arka kapısı ikisi de 403
    assert client.post(f"/api/certificates/{leaf['id']}/deactivate",
                       headers=editor_headers).status_code == 403
    assert client.put(f"/api/certificates/{leaf['id']}", headers=editor_headers,
                      json={"is_active": False}).status_code == 403


def test_login_returns_email(client, auth_headers):
    r = client.post("/api/auth/login-json", json={"username": "admin", "password": "admin"})
    assert "email" in r.json()


def test_relationships_derivation(client, auth_headers):
    # Aynı sertifika bir domain'de server, başka domain'de client → trust kenarı türetilmeli
    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf")
    a = client.post("/api/domains", headers=auth_headers,
                    json={"domain": "server-a.rel-test.com"}).json()["id"]
    b = client.post("/api/domains", headers=auth_headers,
                    json={"domain": "client-b.rel-test.com"}).json()["id"]
    client.post(f"/api/domains/{a}/certificates", headers=auth_headers,
                json={"certificate_id": leaf["id"], "mapping_type": "server"})
    client.post(f"/api/domains/{b}/certificates", headers=auth_headers,
                json={"certificate_id": leaf["id"], "mapping_type": "client"})
    rel = client.get("/api/relationships", headers=auth_headers).json()
    trust = [e for e in rel["edges"] if e["edge_type"] == "trust"]
    match = [e for e in trust if e["source"] == f"domain-{b}" and e["target"] == f"domain-{a}"]
    assert match, "client-b → server-a trust kenarı bekleniyordu"
    assert match[0]["via_cert_id"] == leaf["id"]


def test_application_server_name_required(client, auth_headers):
    """server_name ZORUNLU: create'te eksik/boş → 422; update'te gönderilirse boş olamaz."""
    # eksik → 422
    r = client.post("/api/applications", headers=auth_headers, json={"app_name": "SunucusuzApp"})
    assert r.status_code == 422, r.text
    # yalnız boşluk → 422
    r = client.post("/api/applications", headers=auth_headers,
                    json={"app_name": "SunucusuzApp", "server_name": "   "})
    assert r.status_code == 422, r.text
    # dolu → 200 (baştaki/sondaki boşluk kırpılır)
    r = client.post("/api/applications", headers=auth_headers,
                    json={"app_name": "SunuculuApp", "server_name": "  web-01  "})
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    assert r.json()["server_name"] == "web-01"
    # update'te server_name boş gönderilirse → 422 (düzenlemede de zorunlu)
    r = client.put(f"/api/applications/{app_id}", headers=auth_headers, json={"server_name": ""})
    assert r.status_code == 422, r.text
    # update'te server_name hiç gönderilmezse dokunulmaz (başka alan güncellenebilir)
    r = client.put(f"/api/applications/{app_id}", headers=auth_headers, json={"notes": "not"})
    assert r.status_code == 200, r.text
    assert r.json()["server_name"] == "web-01"


def test_legacy_blank_server_name_still_serializes(client, auth_headers):
    """REGRESYON: server_name girdide zorunlu olsa da ÇIKTI (ApplicationOut) eski boş/NULL
    kayıtları serileştirebilmeli — aksi halde tek boş kayıt tüm listeyi 500 yapardı."""
    from app.db.models import Application
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        legacy = Application(app_name="EskiKayit", server_name="", ip_address="")
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
    finally:
        db.close()
    # Liste ve detay 500 vermemeli; boş server_name olduğu gibi döner
    r = client.get("/api/applications", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(a["id"] == legacy_id and a["server_name"] == "" for a in r.json())
    r = client.get(f"/api/applications/{legacy_id}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["server_name"] == ""


def test_app_dependency_and_depends_edge(client, auth_headers):
    # Uygulamanın dış (client) bağımlılığı → İlişkiler grafiğinde 'depends' kenarı
    host = client.post("/api/domains", headers=auth_headers,
                       json={"domain": "host.dep-test.com"}).json()["id"]
    target = client.post("/api/domains", headers=auth_headers,
                         json={"domain": "target.dep-test.com"}).json()["id"]
    app = client.post("/api/applications", headers=auth_headers,
                      json={"app_name": "Bağımlı Uygulama", "server_name": "srv-bagimli",
                            "domain_id": host}).json()
    # Kendi domainine bağımlılık reddedilir
    r = client.post(f"/api/applications/{app['id']}/dependencies", headers=auth_headers,
                    json={"target_domain_id": host})
    assert r.status_code == 400
    # Geçerli dış bağımlılık
    r = client.post(f"/api/applications/{app['id']}/dependencies", headers=auth_headers,
                    json={"target_domain_id": target, "note": "ödeme çağrısı"})
    assert r.status_code == 200, r.text
    dep_id = r.json()["id"]
    assert r.json()["target_domain_name"] == "target.dep-test.com"
    # Mükerrer → 409
    assert client.post(f"/api/applications/{app['id']}/dependencies", headers=auth_headers,
                       json={"target_domain_id": target}).status_code == 409
    # ApplicationOut dependencies içeriyor
    got = next(a for a in client.get("/api/applications", headers=auth_headers).json()
               if a["id"] == app["id"])
    assert any(d["id"] == dep_id for d in got["dependencies"])
    # Relationships 'depends' kenarı: app → target
    rel = client.get("/api/relationships", headers=auth_headers).json()
    depends = [e for e in rel["edges"] if e["edge_type"] == "depends"
               and e["source"] == f"app-{app['id']}" and e["target"] == f"domain-{target}"]
    assert depends, "app → target 'depends' kenarı bekleniyordu"
    # Sil
    assert client.delete(f"/api/applications/dependencies/{dep_id}",
                         headers=auth_headers).status_code == 200


def test_dashboard_and_map(client, auth_headers):
    d = client.get("/api/dashboard", headers=auth_headers).json()
    assert d["total_certificates"] >= 3
    m = client.get("/api/cert-map", headers=auth_headers).json()
    assert any(e["edge_type"] == "hierarchy" for e in m["edges"])


def test_role_enforcement(client, auth_headers):
    # RBAC: role="allviewer" = global salt-okur (her şeyi görür ama yazamaz).
    r = client.post("/api/users", headers=auth_headers,
                    json={"username": "izleyici", "password": "sifre123", "role": "allviewer"})
    assert r.status_code == 200
    r = client.post("/api/auth/login-json", json={"username": "izleyici", "password": "sifre123"})
    viewer_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.post("/api/domains", headers=viewer_headers, json={"domain": "yetkisiz.com"})
    assert r.status_code == 403
    # okuma serbest (global)
    assert client.get("/api/domains", headers=viewer_headers).status_code == 200


def test_settings_roundtrip_and_secret_masking(client, auth_headers):
    r = client.put("/api/settings/ldap", headers=auth_headers,
                   json={"server": "ldaps://dc.firma.local", "enabled": False,
                         "bind_password": "cok-gizli"})
    assert r.status_code == 200
    data = client.get("/api/settings/ldap", headers=auth_headers).json()
    assert data["server"] == "ldaps://dc.firma.local"
    # FERNET_KEY tanımlı değilse şifre saklanmaz; tanımlıysa maskelenir — düz metin asla dönmez
    assert data["bind_password"] != "cok-gizli"


def test_vault_test_disabled_by_default(client, auth_headers):
    # Vault ayarı varsayılan olarak kapalı → health testi başarısız ama düzgün mesajla döner
    r = client.post("/api/settings/vault/test", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "etkin değil" in body["message"]


def test_vault_sync_requires_enabled(client, auth_headers):
    # Vault kapalıyken senkron 400 döner (etkin değil)
    r = client.post("/api/certificates/vault-sync", headers=auth_headers)
    assert r.status_code == 400
    assert "etkin değil" in r.json()["detail"]


def test_certificate_out_has_vault_path(client, auth_headers):
    certs = client.get("/api/certificates", headers=auth_headers).json()
    assert all("vault_path" in c for c in certs)


def test_certificate_import_source_tag(client, auth_headers, fixtures_dir):
    # import 'source' form alanını kabul eder ve sertifikaya işler (vault etiketi)
    with open(fixtures_dir / "leaf.der", "rb") as f:
        r = client.post("/api/certificates/import", headers=auth_headers,
                        data={"source": "vault"}, files={"file": ("leaf.der", f)})
    # leaf.der zaten fixture'da kayıtlı olabilir (409) — yeni ise source=vault olmalı
    if r.status_code == 200:
        assert all(c["source"] == "vault" for c in r.json())
    else:
        assert r.status_code == 409


def test_domain_csv_import(client, auth_headers):
    csv_content = (
        "domain,sy,ug,mail_addresses,external_company\n"
        "csv1.jumbo-test.com,MoneyTalks,Integral,ops@test.com,32bit\n"
        "csv2.jumbo-test.com,IISAdmins,,iis@test.com,\n"
        "csv1.jumbo-test.com,MoneyTalks,,,\n"  # mükerrer → atlanmalı... ilk satırla aynı isim
        ",Bos,,,\n"  # domain boş → hata satırı
    )
    r = client.post("/api/domains/import-csv", headers=auth_headers,
                    files={"file": ("domains.csv", csv_content, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["skipped"] == 1
    assert len(body["errors"]) == 1
    # Takımlar otomatik oluştu mu?
    teams = client.get("/api/teams", headers=auth_headers).json()
    assert {"MoneyTalks", "IISAdmins"} <= {t["name"] for t in teams if t["type"] == "SY"}
    # Aynı dosya tekrar → hepsi atlanır
    r = client.post("/api/domains/import-csv", headers=auth_headers,
                    files={"file": ("domains.csv", csv_content, "text/csv")})
    assert r.json()["created"] == 0


def test_certificate_soft_delete_filter(client, auth_headers):
    # Kendi BAĞSIZ sertifikasını yarat: server olarak domaine bağlı cert artık pasife
    # alınamaz (409), o yüzden rastgele mevcut bir leaf yerine ayrılmış bir kayıt kullan.
    cid = client.post("/api/certificates", headers=auth_headers,
                      json={"name": "SoftDelete Filter Test"}).json()["id"]
    r = client.put(f"/api/certificates/{cid}", headers=auth_headers,
                   json={"is_active": False})
    assert r.json()["is_active"] is False
    active_only = client.get("/api/certificates?is_active=true", headers=auth_headers).json()
    assert cid not in {c["id"] for c in active_only}
    everything = client.get("/api/certificates", headers=auth_headers).json()
    assert cid in {c["id"] for c in everything}


def test_audit_populated(client, auth_headers):
    entries = client.get("/api/audit", headers=auth_headers).json()
    actions = {e["action"] for e in entries}
    assert {"login", "import", "create"} <= actions


def test_audit_export_csv(client, auth_headers):
    r = client.get("/api/audit/export", headers=auth_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("﻿")                    # UTF-8 BOM (Excel TR)
    assert "Kullanıcı" in body and "İşlem" in body       # başlık satırı
    assert len(body.strip().splitlines()) >= 2           # başlık + en az 1 kayıt


def test_audit_export_requires_admin(client):
    assert client.get("/api/audit/export").status_code == 401


def test_audit_date_filter_future_range_empty(client, auth_headers):
    # Gelecekteki aralık → hiçbir kayıt (tüm kayıtlar bugünden). date_to gün sonuna kadar dâhil.
    r = client.get("/api/audit", headers=auth_headers,
                   params={"date_from": "2099-01-01", "date_to": "2099-01-02"})
    assert r.status_code == 200 and r.json() == []


# ---- Canlı zincir çekme (probe-chain / import-chain) ----

def test_probe_chain_wildcard_and_unreachable(client, auth_headers):
    r = client.post("/api/domains/probe-chain", headers=auth_headers,
                    json={"domain": "*.jumbo-test.com"})
    assert r.status_code == 200
    assert r.json()["reachable"] is False

    # Kapalı porta bağlantı: hata değil, reachable=false döner
    r = client.post("/api/domains/probe-chain", headers=auth_headers,
                    json={"domain": "127.0.0.1:1"})
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert body["error"]


def test_import_chain_wildcard_rejected(client, auth_headers):
    r = client.post("/api/domains", headers=auth_headers, json={"domain": "*.chain-test.com"})
    domain_id = r.json()["id"]
    r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
    assert r.status_code == 400


def test_probe_and_import_chain_live_tls(client, auth_headers, fixtures_dir):
    """Gerçek TLS sunucusundan zincir çekme: fixture zinciri lokal portta sunulur;
    probe zinciri 'zaten kayıtlı' işaretler, import leaf'i domain'e server olarak eşler."""
    import socket
    import ssl
    import threading

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(fixtures_dir / "fullchain.pem", fixtures_dir / "leaf.key")
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                ctx.wrap_socket(conn, server_side=True).close()
            except Exception:
                conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        r = client.post("/api/domains/probe-chain", headers=auth_headers,
                        json={"domain": f"localhost:{port}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reachable"] is True
        assert len(body["certificates"]) == 3  # leaf + intermediate + root
        # Fixture zinciri önceki testte import edildi — hepsi kayıtlı görünmeli
        assert all(c["already_exists"] for c in body["certificates"])
        assert body["certificates"][0]["subject_key_identifier"]

        r = client.post("/api/domains", headers=auth_headers,
                        json={"domain": f"localhost:{port}(chain-e2e)"})
        domain_id = r.json()["id"]
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["created"] == []          # duplicate üretilmedi
        assert len(result["existing"]) == 3
        assert result["mapped_server"]          # leaf server olarak bağlandı

        d = client.get(f"/api/domains/{domain_id}", headers=auth_headers).json()
        server_certs = [c for c in d["certificates"] if c["mapping_type"] == "server"]
        assert len(server_certs) == 1
        assert server_certs[0]["subject_key_identifier"]  # MappedCertOut SKI taşıyor

        # İdempotent: ikinci import yeni eşleme/kayıt oluşturmaz
        r = client.post(f"/api/domains/{domain_id}/import-chain", headers=auth_headers)
        assert r.json()["created"] == []
        assert r.json()["mapped_server"] is None
    finally:
        srv.close()


def test_search_by_ski(client, auth_headers):
    leaf = next(c for c in client.get("/api/certificates", headers=auth_headers).json()
                if c["cert_type"] == "leaf" and c["subject_key_identifier"])
    fragment = leaf["subject_key_identifier"][:11]  # ilk 4 oktet
    hits = client.get("/api/certificates", headers=auth_headers,
                      params={"search": fragment}).json()
    assert leaf["id"] in {c["id"] for c in hits}
