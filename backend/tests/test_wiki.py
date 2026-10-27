"""Kullanım Kılavuzu kurumun wiki'sinden (Confluence) okunur (v3.9.16, sahibin kararı 27.10.2026).

Gerçek wiki yerine tests/fake_confluence.py (httpx.MockTransport) kullanılır."""

import json

import httpx
import pytest

from app.db.session import SessionLocal
from app.services import wiki
from tests.fake_confluence import BASE, ROOT_LINK


def _viewer(client, headers, username="wiki_viewer"):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": "viewer", "auth_source": "local"})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _pages():
    db = SessionLocal()
    try:
        return wiki.pages(db)
    finally:
        db.close()


def _set(client, headers, **values):
    r = client.put("/api/settings/ai", headers=headers, json=values)
    assert r.status_code == 200, r.text


def test_parse_link_formats():
    assert wiki.parse_link(ROOT_LINK) == (BASE, "100", None, None)
    assert wiki.parse_link("https://wiki.firma.local/display/JUMBO/Jumbo+Kullan%C4%B1m+K%C4%B1lavuzu") == (
        "https://wiki.firma.local", None, "JUMBO", "Jumbo Kullanım Kılavuzu")
    assert wiki.parse_link("https://firma.atlassian.net/wiki/spaces/JUMBO/pages/100/Jumbo+Kilavuz") == (
        "https://firma.atlassian.net/wiki", "100", "JUMBO", None)
    assert wiki.parse_link("https://wiki.firma.local/display/JUMBO") == (
        "https://wiki.firma.local", None, "JUMBO", None)
    assert wiki.parse_link("https://firma.atlassian.net/wiki/spaces/JUMBO/overview") == (
        "https://firma.atlassian.net/wiki", None, "JUMBO", None)
    for bad, msg in [("wiki.firma.local/display/JUMBO", "http(s)://"),
                     ("https://wiki.firma.local/x/AbCd", "Kısa link"),
                     ("https://wiki.firma.local/baska/bir/yer", "Azure DevOps (TFS) wiki sayfasına benzemiyor")]:
        with pytest.raises(wiki.WikiError, match=msg.replace("(", r"\(").replace(")", r"\)")):
            wiki.parse_link(bad)


def test_storage_to_text_keeps_steps_tables_panels_and_code():
    from tests.fake_confluence import PAGES
    text = wiki.storage_to_text(PAGES["101"][2])
    assert "## Yeni domain" in text
    assert "1. Domainler ekranında Yeni Domain'e basın." in text and "2. Domain adını ve SY ekibini girin." in text
    assert "Not\n\nSY ekibi zorunludur." in text
    table = wiki.storage_to_text(PAGES["102"][2])
    assert "### Kim onaylar?" in table and "Ekip Editörü | Onaylar" in table
    code = wiki.storage_to_text(PAGES["103"][2])
    assert "curl -v https://web.ornek.com" in code and "bash" not in code


def test_reads_root_and_children_in_tree_order(wiki_on):
    pages = _pages()
    assert [(p.title, p.depth) for p in pages] == [
        ("Jumbo Kullanım Kılavuzu", 0), ("Değişiklik talepleri", 1), ("Canlı Doğrulama", 2), ("Domain ekleme", 1)]
    assert pages[3].url == f"{BASE}/display/JUMBO/Domain+ekleme"
    assert "Başka bir alanın sayfası" not in [p.title for p in pages]          # ağacın dışı okunmaz
    assert sum("/content/search" in c for c in wiki_on.calls) == 2              # sayfalı sonuç izlendi
    assert all(c.startswith(BASE + "/rest/api/") for c in wiki_on.calls)


def test_link_by_title_and_space_home(client, auth_headers, wiki_on):
    _set(client, auth_headers, wiki_url="https://wiki.firma.local/confluence/display/JUMBO/Jumbo+Kullan%C4%B1m+K%C4%B1lavuzu")
    assert len(_pages()) == 4
    _set(client, auth_headers, wiki_url="https://wiki.firma.local/confluence/display/JUMBO")
    assert _pages()[0].title == "Jumbo Kullanım Kılavuzu"


def test_basic_auth_header():
    assert wiki._headers({"wiki_auth_mode": "basic", "wiki_username": "svc", "wiki_token": "p"})[
        "Authorization"] == "Basic c3ZjOnA="
    assert wiki._headers({"wiki_auth_mode": "bearer", "wiki_token": "t"})["Authorization"] == "Bearer t"


def test_errors_are_explained(client, auth_headers, wiki_on, monkeypatch):
    cases = [
        (dict(token="baska"), "kabul etmedi (HTTP 401)"),
        (dict(status=403), "okuma yetkisi yok"),
        (dict(status=404), "bulunamadı (HTTP 404)"),
        (dict(html_login=True), "JSON değil"),
    ]
    for attrs, msg in cases:
        wiki.reset_cache()
        fake = type(wiki_on)()
        for k, v in attrs.items():
            setattr(fake, k, v)
        monkeypatch.setattr(wiki, "_client", lambda cfg, f=fake: httpx.Client(
            headers=wiki._headers(cfg), transport=httpx.MockTransport(f)))
        with pytest.raises(wiki.WikiError, match=msg.replace("(", r"\(").replace(")", r"\)")):
            _pages()

    def down(request):
        raise httpx.ConnectError("Name or service not known")
    wiki.reset_cache()
    monkeypatch.setattr(wiki, "_client", lambda cfg: httpx.Client(transport=httpx.MockTransport(down)))
    with pytest.raises(wiki.WikiError, match="bağlanılamadı"):
        _pages()


def test_cache_refresh_and_stale_copy_when_wiki_is_down(wiki_on):
    first = _pages()
    calls = len(wiki_on.calls)
    wiki_on.pages["101"][2] = "<p>Yeni metin: Domainler &gt; Yeni Domain.</p>"
    assert _pages() is first and len(wiki_on.calls) == calls            # bellekten
    db = SessionLocal()
    try:
        wiki.request_refresh(db)                                       # "Wiki'yi Şimdi Oku" (başka pod)
    finally:
        db.close()
    assert "Yeni metin" in next(p.text for p in _pages() if p.id == "101")
    # Wiki çökerse son okunan metinle devam edilir, her soruda yeniden denenmez
    db = SessionLocal()
    try:
        wiki.request_refresh(db)
    finally:
        db.close()
    wiki_on.status = 500
    assert "Yeni metin" in next(p.text for p in _pages() if p.id == "101")
    calls = len(wiki_on.calls)
    _pages()
    assert len(wiki_on.calls) == calls


def test_refresh_endpoint_admin_only_and_audited(client, auth_headers, wiki_on):
    hdr = _viewer(client, auth_headers)
    assert client.post("/api/ai/wiki/refresh", headers=hdr).status_code == 403
    r = client.post("/api/ai/wiki/refresh", headers=auth_headers).json()
    assert r["success"] and r["message"] == "4 sayfa okundu"
    assert [p["title"] for p in r["pages"]][:2] == ["Jumbo Kullanım Kılavuzu", "Değişiklik talepleri"]
    wiki_on.token = "yenilendi"                                        # token wiki'de değişti
    r = client.post("/api/ai/wiki/refresh", headers=auth_headers).json()
    assert not r["success"] and "HTTP 401" in r["message"] and r["pages"] == []
    audit = client.get("/api/audit?table_name=app_settings", headers=auth_headers).json()["items"]
    details = [json.loads(a["details"]) for a in audit[:2]]
    assert [(d["target"], d["success"]) for d in details] == [("wiki", False), ("wiki", True)]
    assert audit[1]["summary"] == "wiki: başarılı"


def test_refresh_endpoint_without_link(client, auth_headers, confluence):
    r = client.post("/api/ai/wiki/refresh", headers=auth_headers).json()
    assert not r["success"] and "linkini girip kaydedin" in r["message"]


def test_status_carries_guide_link_for_everyone(client, auth_headers, wiki_on):
    hdr = _viewer(client, auth_headers, "wiki_viewer2")
    assert client.get("/api/ai/status", headers=hdr).json()["guide_url"] == ROOT_LINK
    _set(client, auth_headers, wiki_url="")
    assert client.get("/api/ai/status", headers=hdr).json()["guide_url"] is None


def test_search_ranks_title_and_folds_turkish(wiki_on):
    pages = _pages()
    assert wiki.search(pages, "DEĞİŞİKLİK TALEBİNİ KİM ONAYLAR")[0][0].title == "Değişiklik talepleri"
    assert wiki.search(pages, "canli dogrulama")[0][0].title == "Canlı Doğrulama"
    assert wiki.search(pages, "qqqzzz") == []
    assert wiki.find(pages, "domain EKLEME").id == "101" and wiki.find(pages, "103").title == "Canlı Doğrulama"
