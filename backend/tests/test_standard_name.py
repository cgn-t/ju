"""v3.9.39 Sertifika Standart Adı; v3.9.42 sırası: ortam_CA_Tür_alanadı_yyyymmdd (ortam boşsa ortam parçası yok).

NAME (prod kolonu) hiç değişmez; Standart Ad ayrı StandardName kolonunda. Kolon pod açılışında
eklenmez (Veritabanı Değişiklikleri sayfasından betik çalıştırılır); kolon yokken uygulama
eski haliyle çalışır. Düzeltme: admin ya da sahibi ekibin editörü, sahipsiz sertifikada yalnız admin."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.db.models import Certificate, CertificateDomainMap, Domain
from app.db.session import SessionLocal, engine
from app.services import cert_naming, schema_state
from tests import certgen

CFG = {"ca_abbreviations": [{"match": "DigiCert", "abbr": "Dgcrt"}, {"match": "Sectigo", "abbr": "Sctg"}],
       "unknown_abbr": "Diger", "self_signed_abbr": "Self", "env_suffix": True}
VT = datetime(2026, 8, 14, 9, 0)


@pytest.fixture()
def std_on():
    schema_state.override["standard_name"] = True
    yield
    schema_state.override["standard_name"] = False


def _b(**kw):
    base = dict(issuer="CN=DigiCert Global G2 TLS RSA SHA256 2020 CA1,O=DigiCert Inc,C=US",
                subject="CN=*.aaaa.com", name="*.aaaa.com", san="*.aaaa.com, aaaa.com",
                cert_type="leaf", eku="serverAuth, clientAuth", valid_to=VT, environment="prod", cfg=CFG)
    base.update(kw)
    return cert_naming.build(**base)


# ---------- kural ----------
def test_rule_wildcard_digicert_prod():
    assert _b()["name"] == "prod_Dgcrt_wildcard_aaaa.com_20260814"


def test_rule_kinds_and_suffix():
    assert _b(subject="CN=odeme.aaaa.com", san="odeme.aaaa.com", environment="test",
              issuer="CN=Sectigo RSA Domain Validation Secure Server CA,O=Sectigo Limited")["name"] \
        == "test_Sctg_single_odeme.aaaa.com_20260814"
    # www + kök aynı site sayılır → single; farklı alan adları → san
    assert _b(subject="CN=aaaa.com", san="aaaa.com, www.aaaa.com")["kind"] == "single"
    # birden fazla host adı (alt alan adı da olsa) → san; IP sayılmaz
    assert _b(subject="CN=portal.aaaa.com", san="portal.aaaa.com, api.aaaa.com")["kind"] == "san"
    assert _b(subject="CN=aaa.ai", san="aaa.ai, 10.1.2.3")["kind"] == "single"
    # yalnız istemci (mTLS) sertifikası
    assert _b(subject="CN=jumbo-batch", san=None, eku="clientAuth")["name"] == "prod_Dgcrt_client_jumbo-batch_20260814"
    # v3.9.42: ortam başta; boşsa ortam parçası yok; ayarda kapalıysa da yok
    assert _b(environment=None)["name"] == "Dgcrt_wildcard_aaaa.com_20260814"
    assert _b(cfg={**CFG, "env_suffix": False})["name"] == "Dgcrt_wildcard_aaaa.com_20260814"


def test_rule_ca_certs_unknown_and_self_signed():
    inter = _b(cert_type="intermediate", subject="CN=DigiCert Global G2 TLS RSA SHA256 2020 CA1,O=DigiCert Inc",
               issuer="CN=DigiCert Global Root G2,O=DigiCert Inc", san=None, environment=None)
    assert inter["name"] == "Dgcrt_intermediate_DigiCertGlobalG2TLSRSASHA2562020CA1_20260814"
    unk = _b(issuer="CN=Example Corp CA", subject="CN=eski.aaaa.com", san="eski.aaaa.com")
    assert unk["name"].startswith("prod_Diger_single_eski.aaaa.com_") and unk["unknown_ca"]
    self_ = _b(issuer="CN=fw.local", subject="CN=fw.local", san="fw.local")
    assert self_["name"] == "prod_Self_single_fw.local_20260814"


def test_rule_date_uses_istanbul_day():
    # 2026-08-14 22:30 UTC = 15 Ağustos 01:30 İstanbul → ekranda görülen gün
    assert _b(valid_to=datetime(2026, 8, 14, 22, 30))["date"] == "20260815"


def test_unique_adds_number():
    assert cert_naming.unique("A_b", {"a_b"}) == "A_b_2"
    assert cert_naming.unique("A_b", {"a_b", "a_b_2"}) == "A_b_3"
    assert cert_naming.unique("A_b", set()) == "A_b"


# ---------- uygulama ----------
def _mk_user(client, admin, username, role="editor", pw="Parola!123"):
    r = client.post("/api/users", headers=admin, json={"username": username, "password": pw, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login(client, username, pw="Parola!123"):
    r = client.post("/api/auth/login-json", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _pems(cn, san=None, ca_cn="DigiCert SN Test CA", days=200):
    ca, ca_key = certgen.make_ca(ca_cn)
    leaf, _ = certgen.make_leaf(ca, ca_key, cn, not_before=datetime.utcnow() - timedelta(days=1),
                                days=days, san=san or [cn])
    return leaf, ca


def _import(client, h, cn, *, san=None, env="prod", names=None, ca_cn="DigiCert SN Test CA"):
    leaf, ca = _pems(cn, san, ca_cn)
    data = {"environment": env}
    if names is not None:
        import json
        data["standard_names"] = json.dumps(names)
    r = client.post("/api/certificates/import", headers=h, data=data,
                    files={"file": ("c.pem", (certgen.pem(leaf) + certgen.pem(ca)).encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    return r.json(), leaf


def _ymd(cert_out):
    from app.core.timeutil import ISTANBUL
    from datetime import timezone
    vt = datetime.fromisoformat(cert_out["valid_to"].replace("Z", "+00:00"))
    if vt.tzinfo is None:
        vt = vt.replace(tzinfo=timezone.utc)
    return vt.astimezone(ISTANBUL).strftime("%Y%m%d")


def test_not_ready_keeps_old_behaviour(client, auth_headers):
    """Betik çalıştırılmadan (varsayılan): ad üretilmez, alan boş, düzenleme 409."""
    out, _ = _import(client, auth_headers, "kapali.sn.test")
    leaf = next(c for c in out if c["cert_type"] == "leaf")
    assert leaf["standard_name"] is None
    r = client.put(f"/api/certificates/{leaf['id']}", headers=auth_headers, json={"standard_name": "X"})
    assert r.status_code == 409
    me = client.get("/api/auth/me", headers=auth_headers).json()
    assert me["features"]["standard_name"] is False


def test_import_fills_standard_name_and_list_search(client, auth_headers, std_on):
    out, _ = _import(client, auth_headers, "*.sn-wild.test", san=["*.sn-wild.test", "sn-wild.test"])
    leaf = next(c for c in out if c["cert_type"] == "leaf")
    root = next(c for c in out if c["cert_type"] != "leaf")
    assert leaf["name"] == "*.sn-wild.test"                    # NAME değişmez
    assert leaf["standard_name"] == f"prod_Dgcrt_wildcard_sn-wild.test_{_ymd(leaf)}"
    assert root["standard_name"].startswith("prod_Dgcrt_root_DigiCertSNTestCA_")
    # listede ve aramada standart ad
    page = client.get("/api/certificates/page", headers=auth_headers,
                      params={"q": "prod_Dgcrt_wildcard_sn-wild"}).json()
    assert [r["cert"]["id"] for r in page["items"]] == [leaf["id"]]
    assert page["items"][0]["cert"]["standard_name"] == leaf["standard_name"]
    single = client.get(f"/api/certificates/{leaf['id']}", headers=auth_headers).json()
    assert single["standard_name"] == leaf["standard_name"] and single["can_edit_standard_name"] is True


def test_import_keeps_user_given_name_and_rejects_duplicate(client, auth_headers, std_on):
    leaf_cert, ca = _pems("verilen.sn.test")
    from app.services.cert_parser import parse_pem_text
    fp = parse_pem_text(certgen.pem(leaf_cert))[0].fingerprint_sha256
    import json
    r = client.post("/api/certificates/import", headers=auth_headers,
                    data={"environment": "test", "standard_names": json.dumps({fp: "Benim_Adim"})},
                    files={"file": ("c.pem", (certgen.pem(leaf_cert) + certgen.pem(ca)).encode(), "application/x-pem-file")})
    assert r.status_code == 200, r.text
    assert next(c for c in r.json() if c["cert_type"] == "leaf")["standard_name"] == "Benim_Adim"
    # aynı ad (büyük/küçük harf farkıyla) ikinci kez verilemez
    leaf2, ca2 = _pems("verilen2.sn.test")
    fp2 = parse_pem_text(certgen.pem(leaf2))[0].fingerprint_sha256
    r = client.post("/api/certificates/import", headers=auth_headers,
                    data={"environment": "test", "standard_names": json.dumps({fp2: "benim_adim"})},
                    files={"file": ("c.pem", (certgen.pem(leaf2) + certgen.pem(ca2)).encode(), "application/x-pem-file")})
    assert r.status_code == 409


def test_manual_create_with_pem_and_name(client, auth_headers, std_on):
    leaf, ca = _pems("manuel.sn.test")
    r = client.post("/api/certificates", headers=auth_headers, json={
        "name": "", "pem_certificate": certgen.pem(leaf), "environment": "prod", "standard_name": "  Manuel_Ad  "})
    assert r.status_code == 200, r.text
    assert r.json()["standard_name"] == "Manuel_Ad"
    # PEM'siz yalnız-isim kaydına kural uygulanmaz (Issuer/tarih gerçek değil)
    r = client.post("/api/certificates", headers=auth_headers, json={"name": "yalniz isim sn", "environment": "prod"})
    assert r.status_code == 200 and r.json()["standard_name"] is None


def test_suggest_endpoint_uses_form_environment(client, auth_headers, std_on):
    out, _ = _import(client, auth_headers, "oneri.sn.test", env="prod")
    leaf = next(c for c in out if c["cert_type"] == "leaf")
    r = client.post("/api/certificates/standard-name/suggest", headers=auth_headers,
                    json={"id": leaf["id"], "environment": "test"})
    assert r.status_code == 200, r.text
    # kendi adı çakışma sayılmaz; ortam formdaki
    assert r.json()["standard_name"] == f"test_Dgcrt_single_oneri.sn.test_{_ymd(leaf)}"
    leaf2, _ = _pems("pem.sn.test")
    r = client.post("/api/certificates/standard-name/suggest", headers=auth_headers,
                    json={"pem_certificate": certgen.pem(leaf2), "environment": None})
    assert r.json()["standard_name"].startswith("Dgcrt_single_pem.sn.test_") and r.json()["env"] is None


def test_edit_rights(client, auth_headers, std_on):
    h = auth_headers
    out, _ = _import(client, h, "yetki.sn.test")
    cid = next(c for c in out if c["cert_type"] == "leaf")["id"]
    db = SessionLocal()
    try:
        db.get(Certificate, cid).creator = None   # sahipsiz
        db.commit()
    finally:
        db.close()
    uid = _mk_user(client, h, "sn_editor")
    eh = _login(client, "sn_editor")
    # sahipsiz sertifika: editör düzeltemez, admin düzeltir
    assert client.get(f"/api/certificates/{cid}", headers=eh).json()["can_edit_standard_name"] is False
    r = client.put(f"/api/certificates/{cid}", headers=eh, json={"standard_name": "Editor_Adi"})
    assert r.status_code == 403
    # diğer alanları editör yine düzenleyebilir (eski kural değişmedi)
    assert client.put(f"/api/certificates/{cid}", headers=eh, json={"notes": "not"}).status_code == 200
    assert client.put(f"/api/certificates/{cid}", headers=h, json={"standard_name": "Admin_Adi"}).status_code == 200
    # sahibi ekibin editörü düzeltir
    team = client.post("/api/teams", headers=h, json={"name": "SN Sahip SY", "type": "SY"}).json()["id"]
    assert client.post(f"/api/teams/{team}/members", headers=h, json={"user_id": uid}).status_code == 200
    db = SessionLocal()
    try:
        dom = Domain(domain="yetki.sn.test", sy_team_id=team)
        db.add(dom)
        db.flush()
        db.add(CertificateDomainMap(certificate_id=cid, domain_id=dom.id, mapping_type="server"))
        db.commit()
    finally:
        db.close()
    assert client.get(f"/api/certificates/{cid}", headers=eh).json()["can_edit_standard_name"] is True
    r = client.put(f"/api/certificates/{cid}", headers=eh, json={"standard_name": "Ekip_Adi"})
    assert r.status_code == 200 and r.json()["standard_name"] == "Ekip_Adi"
    # başka ekibin editörü düzeltemez
    _mk_user(client, h, "sn_other")
    other_team = client.post("/api/teams", headers=h, json={"name": "SN Diger SY", "type": "SY"}).json()["id"]
    oid = next(u["id"] for u in client.get("/api/users", headers=h).json() if u["username"] == "sn_other")
    client.post(f"/api/teams/{other_team}/members", headers=h, json={"user_id": oid})
    oh = _login(client, "sn_other")
    assert client.put(f"/api/certificates/{cid}", headers=oh, json={"standard_name": "Baska"}).status_code == 403
    # düzeltme işlem geçmişine yazılır
    hist = client.get("/api/users/audit", headers=h, params={"table_name": "certificates", "record_id": str(cid)})
    if hist.status_code == 200:
        assert "Ekip_Adi" in hist.text


def test_bulk_preview_and_apply(client, auth_headers, std_on):
    h = auth_headers
    out, _ = _import(client, h, "toplu.sn.test")
    cid = next(c for c in out if c["cert_type"] == "leaf")["id"]
    db = SessionLocal()
    try:
        db.get(Certificate, cid).standard_name = None   # eski kayıt gibi: adı yok
        db.commit()
    finally:
        db.close()
    rows = client.get("/api/certificates/standard-name/bulk", headers=h, params={"only_missing": True}).json()["rows"]
    row = next(r for r in rows if r["id"] == cid)
    assert row["suggested"].startswith("prod_Dgcrt_single_toplu.sn.test_") and row["standard_name"] is None
    r = client.post("/api/certificates/standard-name/bulk", headers=h,
                    json={"items": [{"id": cid, "standard_name": row["suggested"]}]})
    assert r.status_code == 200 and r.json()["changed"] == 1
    assert client.get(f"/api/certificates/{cid}", headers=h).json()["standard_name"] == row["suggested"]
    # yalnız admin
    _mk_user(client, h, "sn_bulk_editor")
    eh = _login(client, "sn_bulk_editor")
    assert client.get("/api/certificates/standard-name/bulk", headers=eh).status_code == 403
    # aynı adı iki sertifikaya verme
    out2, _ = _import(client, h, "toplu2.sn.test")
    cid2 = next(c for c in out2 if c["cert_type"] == "leaf")["id"]
    r = client.post("/api/certificates/standard-name/bulk", headers=h,
                    json={"items": [{"id": cid2, "standard_name": row["suggested"]}]})
    assert r.status_code == 409


def test_bulk_requires_environment(client, auth_headers, std_on):
    """v3.9.42: ortamı boş sertifikaya toplu ad verilirken ortam seçmek zorunlu; ikisi birlikte kaydedilir."""
    h = auth_headers
    out, _ = _import(client, h, "ortamsiz.sn.test")
    cid = next(c for c in out if c["cert_type"] == "leaf")["id"]
    db = SessionLocal()
    try:
        c = db.get(Certificate, cid)
        c.environment = None
        c.standard_name = None
        db.commit()
    finally:
        db.close()
    rows = client.get("/api/certificates/standard-name/bulk", headers=h, params={"only_no_env": True}).json()["rows"]
    row = next(r for r in rows if r["id"] == cid)
    assert row["needs_env"] is True and row["suggested"].startswith("Dgcrt_single_ortamsiz.sn.test_")
    assert all(r["needs_env"] for r in rows)
    r = client.post("/api/certificates/standard-name/bulk", headers=h,
                    json={"items": [{"id": cid, "standard_name": row["suggested"]}]})
    assert r.status_code == 400 and "ortam" in r.json()["detail"].lower()
    assert client.post("/api/certificates/standard-name/bulk", headers=h,
                       json={"items": [{"id": cid, "standard_name": "x", "environment": "uat"}]}).status_code == 400
    sug = client.post("/api/certificates/standard-name/suggest", headers=h,
                      json={"id": cid, "environment": "test"}).json()["standard_name"]
    assert sug.startswith("test_Dgcrt_single_ortamsiz.sn.test_")
    r = client.post("/api/certificates/standard-name/bulk", headers=h,
                    json={"items": [{"id": cid, "standard_name": sug, "environment": "test"}]})
    assert r.status_code == 200 and r.json()["changed"] == 1
    got = client.get(f"/api/certificates/{cid}", headers=h).json()
    assert got["environment"] == "test" and got["standard_name"] == sug


def test_mail_shows_standard_name(client, auth_headers, std_on):
    from app.services import notifier
    out, _ = _import(client, auth_headers, "mail.sn.test")
    cid = next(c for c in out if c["cert_type"] == "leaf")["id"]
    db = SessionLocal()
    try:
        cert = db.get(Certificate, cid)
        rows = dict(notifier._cert_rows(cert))
        assert rows["NAME"] == "mail.sn.test"
        assert rows["Standart Ad"].startswith("prod_Dgcrt_single_mail.sn.test_")
    finally:
        db.close()


def test_missing_column_app_still_works(client, auth_headers):
    """Prod'daki gerçek durum: kolon YOK (betik çalıştırılmamış). Liste, detay, yükleme,
    düzenleme, AI sorgusu ve mail eskisi gibi çalışır; kolon eklenince özellik açılır."""
    h = auth_headers
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE "SSLCertificates" DROP COLUMN "StandardName"'))
    schema_state.override.pop("standard_name", None)
    try:
        schema_state.refresh()
        assert schema_state.standard_name_ready() is False
        out, _ = _import(client, h, "kolonsuz.sn.test")
        cid = next(c for c in out if c["cert_type"] == "leaf")["id"]
        assert client.get("/api/certificates/page", headers=h, params={"q": "kolonsuz"}).status_code == 200
        assert client.get("/api/certificates", headers=h, params={"search": "kolonsuz"}).status_code == 200
        got = client.get(f"/api/certificates/{cid}", headers=h).json()
        assert got["standard_name"] is None and got["can_edit_standard_name"] is False
        assert client.put(f"/api/certificates/{cid}", headers=h, json={"notes": "x"}).status_code == 200
        assert client.post("/api/certificates/standard-name/suggest", headers=h, json={"id": cid}).status_code == 409
        db = SessionLocal()
        try:
            from app.services import notifier
            assert "Standart Ad" not in dict(notifier._cert_rows(db.get(Certificate, cid)))
        finally:
            db.close()
        st = client.get("/api/auth/me", headers=h).json()["features"]
        assert st["standard_name"] is False
    finally:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE "SSLCertificates" ADD COLUMN "StandardName" VARCHAR(255)'))
        schema_state.refresh()
        schema_state.override["standard_name"] = False
    # kolon eklenince (betik çalıştırılınca) özellik kendiliğinden açılır
    schema_state.override.pop("standard_name", None)
    try:
        assert schema_state.standard_name_ready() is True
    finally:
        schema_state.override["standard_name"] = False
