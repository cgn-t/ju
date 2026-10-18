"""Türkçe I/İ ve büyük/küçük harf eşleştirmesi (prod MSSQL Turkish_CI_AS'de 'I' ≠ 'i').

Giriş, domain tekilliği, arama, CA izin listesi ve zamanlama saati. Testler SQLite'ta da
koşar; aynı dosya MSSQL'e karşı çalıştırıldığında collation yolunu da sınar."""

import io

import httpx
import openpyxl

from app.core.textmatch import fold
from app.services import ldap_auth
from app.services.notifier import _hour_setting
from app.services.policy import _issuer_allowed


def _h(client, username, password):
    r = client.post("/api/auth/login-json", json={"username": username, "password": password})
    return r


# ---- Giriş ----
def test_local_login_is_case_insensitive(client, auth_headers):
    client.post("/api/users", headers=auth_headers, json={
        "username": "tr.yerel", "password": "Parola.1", "role": "editor", "auth_source": "local"})
    for typed in ("tr.yerel", "TR.YEREL", "Tr.Yerel"):
        r = _h(client, typed, "Parola.1")
        assert r.status_code == 200, (typed, r.text)
        assert r.json()["username"] == "tr.yerel" and r.json()["role"] == "editor"


def test_ldap_login_with_other_case_reuses_existing_user(client, auth_headers, monkeypatch):
    """AD harf duyarsızdır: 'ISMAIL.CELIK' girişi var olan 'ismail.celik' kaydını kullanmalı,
    yeni ve rolsüz bir kullanıcı açmamalı."""
    r = client.post("/api/users", headers=auth_headers, json={
        "username": "ismail.celik", "role": "editor", "auth_source": "ldap"})
    assert r.status_code == 200, r.text
    monkeypatch.setattr(ldap_auth, "authenticate",
                        lambda db, u, p: ldap_auth.LdapResult(True, email="ismail@firma.com.tr",
                                                              full_name="İsmail Çelik"))
    for typed in ("ISMAIL.CELIK", "Ismail.Celik", "ismail.celik"):
        r = _h(client, typed, "ad-sifresi")
        assert r.status_code == 200, (typed, r.text)
        assert r.json()["username"] == "ismail.celik" and r.json()["role"] == "editor"
    names = [u["username"] for u in client.get("/api/users", headers=auth_headers).json()]
    assert sum(1 for n in names if n.lower() == "ismail.celik") == 1, names


# ---- Domain tekilliği ----
def test_duplicate_domain_rejected_case_insensitive(client, auth_headers):
    r = client.post("/api/domains", headers=auth_headers, json={"domain": "tekil.firma.com.tr"})
    assert r.status_code == 200, r.text
    first = r.json()["id"]
    for dup in ("tekil.firma.com.tr", "TEKIL.FIRMA.COM.TR", " Tekil.firma.com.tr "):
        r = client.post("/api/domains", headers=auth_headers, json={"domain": dup})
        assert r.status_code == 409, (dup, r.text)
        assert "zaten kayıtlı" in r.json()["detail"]
    other = client.post("/api/domains", headers=auth_headers, json={"domain": "tekil2.firma.com.tr"}).json()["id"]
    r = client.put(f"/api/domains/{other}", headers=auth_headers, json={"domain": "TEKIL.firma.com.tr"})
    assert r.status_code == 409, r.text
    # kendi adını büyük harfe çevirmek ikiz sayılmaz
    r = client.put(f"/api/domains/{first}", headers=auth_headers, json={"domain": "TEKIL.firma.com.tr"})
    assert r.status_code == 200, r.text


def test_excel_import_skips_case_variants_and_in_file_duplicates(client, auth_headers):
    client.post("/api/domains", headers=auth_headers, json={"domain": "excel-var.firma.com.tr"})
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["domain"])
    for name in ("EXCEL-VAR.firma.com.tr", "excel-yeni.firma.com.tr", "EXCEL-YENI.FIRMA.COM.TR"):
        ws.append([name])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/domains/import-excel", headers=auth_headers,
                    files={"file": ("d.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1 and r.json()["skipped"] == 2



def test_excel_import_unknown_team_is_reported_not_created(client, auth_headers):
    client.post("/api/teams", headers=auth_headers,
                json={"name": "Ödeme Sistemleri Excel", "type": "SY", "email": "odeme@firma.com.tr"})
    before = {t["name"] for t in client.get("/api/teams", headers=auth_headers).json()}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["domain", "sy", "ug"])
    ws.append(["excel-tr-1.firma.com.tr", "ÖDEME SİSTEMLERİ EXCEL", ""])   # Türkçe büyük harf → eşleşir
    ws.append(["excel-tr-2.firma.com.tr", "ödeme sistemleri excel ", ""])  # küçük harf + boşluk → eşleşir
    ws.append(["excel-tr-3.firma.com.tr", "ODEME SISTEMLERI EXCEL", ""])   # Türkçe harfsiz → bulunamaz
    ws.append(["excel-tr-4.firma.com.tr", "", "Olmayan UG Ekibi"])         # bilinmeyen UG → bulunamaz
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/domains/import-excel", headers=auth_headers,
                    files={"file": ("d.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert len(body["errors"]) == 2
    assert "ODEME SISTEMLERI EXCEL" in body["errors"][0] and "bulunamadı" in body["errors"][0]
    assert "Olmayan UG Ekibi" in body["errors"][1]
    after = {t["name"] for t in client.get("/api/teams", headers=auth_headers).json()}
    assert after == before  # sessizce yeni takım açılmadı
    names = {d["domain"] for d in client.get("/api/domains", headers=auth_headers).json()}
    assert {"excel-tr-1.firma.com.tr", "excel-tr-2.firma.com.tr"} <= names
    assert not {"excel-tr-3.firma.com.tr", "excel-tr-4.firma.com.tr"} & names

# ---- Arama ----
def test_search_ignores_case_of_ascii_i(client, auth_headers):
    client.post("/api/domains", headers=auth_headers, json={"domain": "iletisim-arama.firma.com.tr"})
    for q in ("iletisim-arama", "ILETISIM-ARAMA", "Iletisim-Arama"):
        names = [d["domain"] for d in client.get("/api/domains", headers=auth_headers,
                                                 params={"search": q}).json()]
        assert "iletisim-arama.firma.com.tr" in names, q


# ---- Saf yardımcılar ----
def test_fold_handles_turkish_i():
    assert fold("TÜRKTRUST İMZA") == fold("türktrust imza") == fold("TÜRKTRUST İmza")
    assert fold("ILETISIM") == fold("iletisim")


def test_ca_allowlist_matches_turkish_i_variants():
    issuer = "CN=TÜRKTRUST İmza Sunucu SM"
    assert _issuer_allowed(issuer, ["TÜRKTRUST İMZA"])
    assert _issuer_allowed(issuer, ["türktrust imza"])
    assert not _issuer_allowed(issuer, ["Başka SM"])


def test_hour_setting_accepts_midnight():
    assert _hour_setting(0, 7) == 0
    assert _hour_setting("0", 7) == 0
    assert _hour_setting(None, 7) == 7
    assert _hour_setting("", 7) == 7
    assert _hour_setting(24, 7) == 7
    assert _hour_setting(23, 7) == 23


# ---- Vault bağlantı testi ----
def _vault_with(monkeypatch, routes):
    from app.services.providers import vault as vault_mod

    def handler(request):
        for (method, suffix), resp in routes.items():
            if request.method == method and request.url.path.endswith(suffix):
                return resp
        return httpx.Response(404)
    real = httpx.Client
    monkeypatch.setattr(vault_mod.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = vault_mod.VaultProvider.__new__(vault_mod.VaultProvider)
    p.config = {"enabled": True, "address": "http://vault", "token": "t"}
    return p


def test_vault_health_ok_without_pki(monkeypatch):
    p = _vault_with(monkeypatch, {
        ("GET", "/sys/health"): httpx.Response(200, json={}),
        ("GET", "/auth/token/lookup-self"): httpx.Response(200, json={}),
        ("LIST", "/secret/metadata/certs"): httpx.Response(200, json={"data": {"keys": ["a", "b/"]}}),
    })
    ok, msg = p.health()
    assert ok, msg
    assert "2 kayıt" in msg and "senkron için gerekmez" in msg


def test_vault_health_reports_bad_token(monkeypatch):
    p = _vault_with(monkeypatch, {
        ("GET", "/sys/health"): httpx.Response(200, json={}),
        ("GET", "/auth/token/lookup-self"): httpx.Response(403, json={}),
    })
    ok, msg = p.health()
    assert not ok and "token geçersiz" in msg
