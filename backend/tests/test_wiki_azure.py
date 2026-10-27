"""Kullanım Kılavuzu Azure DevOps Server (TFS) wiki'sinden (v3.9.17; sahibin wiki'si Azure DevOps).

Gerçek sunucu yerine tests/fake_azure_wiki.py (httpx.MockTransport) kullanılır."""

import pytest

from app.db.session import SessionLocal
from app.services import ai_assistant, wiki
from tests.fake_azure_wiki import ID_LINK, PATH_LINK, PROJECT, WIKI
from tests.test_ai_assistant import FakeAi, _last_tool_result, _text, _tool, ai_on  # noqa: F401


def _pages():
    db = SessionLocal()
    try:
        return wiki.pages(db)
    finally:
        db.close()


def _set(client, headers, **values):
    r = client.put("/api/settings/ai", headers=headers, json=values)
    assert r.status_code == 200, r.text
    wiki.reset_cache()


def test_parse_azure_links():
    assert wiki.is_azure(ID_LINK) and not wiki.is_azure("https://wiki.firma.local/display/JUMBO")
    assert wiki.parse_azure_link(ID_LINK) == (PROJECT, WIKI, None, "10")
    assert wiki.parse_azure_link(PATH_LINK) == (PROJECT, WIKI, "/Jumbo Kullanım Kılavuzu", None)
    assert wiki.parse_azure_link("https://dev.azure.com/firma/Proje/_wiki/wikis/Proje.wiki/5/Kilavuz") == (
        "https://dev.azure.com/firma/Proje", "Proje.wiki", None, "5")
    assert wiki.parse_azure_link(f"{PROJECT}/_wiki?pagePath=%2FJumbo") == (PROJECT, None, "/Jumbo", None)
    with pytest.raises(wiki.WikiError, match="proje adı yok"):
        wiki.parse_azure_link("https://tfs.kurum.local/_wiki/wikis/x")


def test_markdown_cleanup():
    text = wiki.markdown_to_text("[[_TOC_]]\n## Adım\n1. [Domainler](/Domainler) ekranı<br/>\n"
                                 "![resim](/.attachments/a.png)\n<!-- not -->\n\n\n\n| a | b |")
    assert text == "## Adım\n1. Domainler ekranı\n\n| a | b |"


def test_reads_page_and_subpages_with_pat(azure_wiki):
    pages = _pages()
    assert [(p.title, p.depth) for p in pages] == [
        ("Jumbo Kullanım Kılavuzu", 0), ("Değişiklik talepleri", 1), ("Canlı Doğrulama", 2), ("Domain ekleme", 1)]
    domain = pages[3]
    assert domain.url == f"{PROJECT}/_wiki/wikis/{WIKI}/11/Domain-ekleme"
    assert "1. Domainler ekranında **Yeni Domain**'e basın." in domain.text
    assert ".attachments" not in domain.text and "iç not" not in domain.text
    assert "| Ekip Editörü | Onaylar |" in pages[1].text
    assert "Başka bir sayfa" not in [p.title for p in pages]
    assert all("api-version=6.0" in c for c in azure_wiki.calls)


def test_older_server_version_and_page_path_link(client, auth_headers, azure_wiki):
    azure_wiki.max_version = "5.0"                       # ör. Azure DevOps Server 2019
    _set(client, auth_headers, wiki_url=PATH_LINK)
    assert len(_pages()) == 4
    assert any("api-version=6.0" in c for c in azure_wiki.calls)
    assert all("api-version=5.0" in c for c in azure_wiki.calls[1:])   # bulunan sürüm saklanır
    # Eski sunucu sayfayı numarayla vermez → bütün ağaçta numarayla bulunur
    _set(client, auth_headers, wiki_url=ID_LINK)
    assert [p.title for p in _pages()][:2] == ["Jumbo Kullanım Kılavuzu", "Değişiklik talepleri"]
    # Ağaçta numara yoksa (çok eski sürüm) linkteki addan bulunur
    for v in azure_wiki.pages.values():
        v[0] = None
    wiki.reset_cache()
    assert len(_pages()) == 4
    _set(client, auth_headers, wiki_url=f"{PROJECT}/_wiki/wikis/{WIKI}/99/Olmayan-Sayfa")
    with pytest.raises(wiki.WikiError, match=r"pagePath"):
        _pages()


def test_code_wiki_branch_is_passed(client, auth_headers, azure_wiki):
    _set(client, auth_headers, wiki_url=PATH_LINK.replace("GBwikiMaster", "GBmain"))
    assert len(_pages()) == 4
    assert all("versionDescriptor.version=main" in c for c in azure_wiki.calls)
    azure_wiki.calls.clear()
    _set(client, auth_headers, wiki_url=PATH_LINK)
    _pages()
    assert not any("versionDescriptor" in c for c in azure_wiki.calls)


def test_whole_wiki_link_uses_project_wiki(client, auth_headers, azure_wiki):
    _set(client, auth_headers, wiki_url=f"{PROJECT}/_wiki")
    titles = [p.title for p in _pages()]
    assert titles[0] == WIKI and "Başka bir sayfa" in titles and "Canlı Doğrulama" in titles


def test_wrong_pat_and_missing_page(client, auth_headers, azure_wiki):
    azure_wiki.pat = "yenisi"
    with pytest.raises(wiki.WikiError, match=r"HTTP 401"):
        _pages()
    azure_wiki.pat = "pat"
    _set(client, auth_headers, wiki_url=f"{PROJECT}/_wiki/wikis/{WIKI}?pagePath=%2FYok")
    with pytest.raises(wiki.WikiError, match=r"HTTP 404"):
        _pages()


def test_refresh_endpoint_and_ai_answer(client, auth_headers, azure_wiki, ai_on, monkeypatch):
    r = client.post("/api/ai/wiki/refresh", headers=auth_headers).json()
    assert r["success"] and r["message"] == "4 sayfa okundu"
    fake = FakeAi([_tool("kilavuz_ara", {"metin": "yeni domain nasıl eklenir"}), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers,
                json={"messages": [{"role": "user", "content": "Yeni domain nasıl eklenir?"}]})
    hit = _last_tool_result(fake, 1)["en_uygun"]
    assert hit["link"] == f"{PROJECT}/_wiki/wikis/{WIKI}/11/Domain-ekleme" and "Yeni Domain" in hit["metin"]
    assert client.get("/api/ai/status", headers=auth_headers).json()["guide_url"] == ID_LINK


def test_ai_test_button_explains_wiki_is_separate(client, auth_headers):
    """Sahip yalnız wiki'yi girip alttaki AI testine bastı (27.10.2026): mesaj wiki butonunu göstersin."""
    _set(client, auth_headers, api_url="", model="")
    r = client.post("/api/ai/test", headers=auth_headers).json()
    assert not r["success"] and "Wiki'yi Şimdi Oku" in r["message"]


def test_pat_is_sent_without_saved_username(client, auth_headers, azure_wiki):
    """Confluence için girilmiş, ekranda gizli kalan kullanıcı adı TFS'e gönderilmez (v3.9.18; sahipte 401)."""
    _set(client, auth_headers, wiki_auth_mode="basic", wiki_username="DOMAIN\\kullanici")
    assert len(_pages()) == 4
