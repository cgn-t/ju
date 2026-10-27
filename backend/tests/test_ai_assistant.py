"""AI asistanı (v3.9.15, v3.9.16): ayarlar, soru-cevap, araçların kapsamı (tam erişim / soranın
yetkisi), veri tabloları aracı ve kurum wiki'sindeki Kullanım Kılavuzu aracı.

Gerçek AI servisi yerine ai_assistant._post sahte cevaplarla değiştirilir."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services import ai_assistant


def _sy_team(client, headers, name):
    r = client.post("/api/teams", headers=headers, json={"name": name, "type": "SY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user_in(client, headers, username, team_id, role="viewer"):
    client.post("/api/users", headers=headers, json={
        "username": username, "password": "x", "role": role, "auth_source": "local"})
    uid = next(u["id"] for u in client.get("/api/users", headers=headers).json()
               if u["username"] == username)
    client.post(f"/api/teams/{team_id}/members", headers=headers, json={"user_id": uid})
    tok = client.post("/api/auth/login-json",
                      json={"username": username, "password": "x"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


class FakeAi:
    """Sırayla verilen cevapları döndürür, gönderilen istekleri saklar."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies = []

    def __call__(self, cfg, body):
        self.bodies.append(json.loads(json.dumps(body)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _text(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _tool(name, args, call_id="c1"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


@pytest.fixture()
def ai_on(client, auth_headers):
    r = client.put("/api/settings/ai", headers=auth_headers, json={
        "enabled": True, "api_url": "https://ai.firma.local/v1", "api_key": "gizli-anahtar",
        "model": "kurum-model", "assistant_name": "Fil", "daily_limit": 0, "use_tools": True,
        "full_access": True})
    assert r.status_code == 200, r.text
    ai_assistant._usage.clear()
    yield
    client.put("/api/settings/ai", headers=auth_headers,
               json={"enabled": False, "daily_limit": 100, "full_access": True})


def _scoped(client, headers):
    """Tam erişim kapalı: AI yalnız soranın ekranda görebildiğini okur."""
    r = client.put("/api/settings/ai", headers=headers, json={"full_access": False})
    assert r.status_code == 200, r.text


def test_status_off_by_default_and_key_is_secret(client, auth_headers):
    r = client.get("/api/ai/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    from app.services.settings_service import SENSITIVE_KEYS
    assert "ai.api_key" in SENSITIVE_KEYS   # şifreli saklanır, ekranda ******** görünür
    r = client.post("/api/ai/chat", headers=auth_headers,
                    json={"messages": [{"role": "user", "content": "merhaba"}]})
    assert r.status_code == 400
    assert "kapalı" in r.json()["detail"]


def test_status_on_shows_name_and_default_suggestions(client, auth_headers, ai_on):
    r = client.get("/api/ai/status", headers=auth_headers)
    body = r.json()
    assert body["enabled"] is True and body["name"] == "Fil"
    assert body["suggestions"][0] == "Önümüzdeki 30 günde süresi dolacak sertifikalar hangileri?"


def test_admin_edits_suggestions(client, auth_headers, ai_on):
    r = client.put("/api/settings/ai", headers=auth_headers, json={
        "suggestions": ["  Bitecek sertifikalar? ", "", "Bitecek sertifikalar?", "Bekleyen talepler?"]})
    assert r.status_code == 200
    assert client.get("/api/ai/status", headers=auth_headers).json()["suggestions"] == [
        "Bitecek sertifikalar?", "Bekleyen talepler?"]
    client.put("/api/settings/ai", headers=auth_headers, json={"suggestions": []})
    assert client.get("/api/ai/status", headers=auth_headers).json()["suggestions"] == []
    # varsayılana dön (diğer testler etkilenmesin)
    from app.services.settings_service import DEFAULTS
    client.put("/api/settings/ai", headers=auth_headers, json={"suggestions": DEFAULTS["ai"]["suggestions"]})


def test_endpoint_and_headers():
    assert ai_assistant._endpoint({"api_url": "https://x/v1"}) == "https://x/v1/chat/completions"
    assert ai_assistant._endpoint({"api_url": "https://x/v1/chat/completions"}) == "https://x/v1/chat/completions"
    azure = "https://x/openai/deployments/m/chat/completions?api-version=2024-06-01"
    assert ai_assistant._endpoint({"api_url": azure}) == azure
    assert ai_assistant._headers({"api_key": "k"})["Authorization"] == "Bearer k"
    h = ai_assistant._headers({"api_key": "k", "auth_mode": "api-key"})
    assert h["api-key"] == "k" and "Authorization" not in h


def test_chat_uses_tool_and_answers(client, auth_headers, ai_on, monkeypatch):
    soon = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=12)).isoformat()
    r = client.post("/api/certificates", headers=auth_headers,
                    json={"name": "ai-yakinda.firma.local", "valid_to": soon, "serial_number": "AI01"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    fake = FakeAi([_tool("sertifika_ara", {"metin": "ai-yakinda", "kalan_gun_en_fazla": 30}),
                   _text("1 sertifika var: [ai-yakinda.firma.local](/certificates?cert=%d)" % cid)])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "30 günde bitecek sertifikalar?"}], "page": "/certificates"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tools_used"] == ["sertifika_ara"] and body["tool_mode"] is True
    assert f"/certificates?cert={cid}" in body["answer"]
    # 1. istek: sistem mesajı + araç tanımları; anahtar ya da PEM gövdesi gitmez
    first = fake.bodies[0]
    assert first["model"] == "kurum-model"
    assert "Fil" in first["messages"][0]["content"] and "/certificates" in first["messages"][0]["content"]
    assert "gizli-anahtar" not in json.dumps(fake.bodies)
    # 2. istek: aracın sonucu AI'a gitti
    tool_msg = fake.bodies[1]["messages"][-1]
    assert tool_msg["role"] == "tool"
    result = json.loads(tool_msg["content"])
    assert result["toplam"] == 1 and result["sertifikalar"][0]["id"] == cid
    assert result["sertifikalar"][0]["link"] == f"/certificates?cert={cid}"
    # Soru Audit Log'a yazıldı
    audit = client.get("/api/audit?action=ai_ask", headers=auth_headers).json()["items"]
    assert audit and audit[0]["summary"] == "30 günde bitecek sertifikalar?"


def test_scoped_mode_respects_user_scope(client, auth_headers, ai_on, monkeypatch):
    _scoped(client, auth_headers)
    own = _sy_team(client, auth_headers, "AiOwn")
    other = _sy_team(client, auth_headers, "AiOther")
    hdr = _user_in(client, auth_headers, "ai_viewer", own)
    ids = {}
    for key, team in (("own", own), ("other", other)):
        r = client.post("/api/domains", headers=auth_headers,
                        json={"domain": f"ai-{key}.firma.local", "sy_team_id": team})
        ids[key] = r.json()["id"]
    fake = FakeAi([_tool("domain_detay", {"id": ids["other"]}),
                   _tool("domain_ara", {"metin": "ai-"}, "c2"),
                   _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=hdr,
                    json={"messages": [{"role": "user", "content": "ai-other nedir?"}]})
    assert r.status_code == 200, r.text
    detail = json.loads(fake.bodies[1]["messages"][-1]["content"])
    assert detail == {"hata": "Domain bulunamadı"}
    found = json.loads(fake.bodies[2]["messages"][-1]["content"])
    assert [d["domain"] for d in found["domainler"]] == ["ai-own.firma.local"]
    # Kayıt geçmişi ve tablo okuma araçları viewer'a hiç sunulmaz
    names = [t["function"]["name"] for t in fake.bodies[0]["tools"]]
    assert "kayit_gecmisi" not in names and "veri_sorgula" not in names
    assert "sertifika_ara" in names
    assert "yetkili olduğu" in fake.bodies[0]["messages"][0]["content"]
    admin_names = [t["function"]["name"] for t in ai_assistant.tool_specs(
        type("U", (), {"role": "admin"})(), {"full_access": False})]
    assert "kayit_gecmisi" in admin_names and "veri_sorgula" in admin_names


def test_scoped_mode_history_refuses_non_admin_even_if_called(client, auth_headers, ai_on, monkeypatch):
    _scoped(client, auth_headers)
    own = _sy_team(client, auth_headers, "AiHist")
    hdr = _user_in(client, auth_headers, "ai_editor", own, role="editor")
    fake = FakeAi([_tool("kayit_gecmisi", {"son_gun": 7}), _text("yok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=hdr,
                    json={"messages": [{"role": "user", "content": "kim ne değiştirdi"}]})
    assert r.status_code == 200
    assert "yöneticiler" in json.loads(fake.bodies[1]["messages"][-1]["content"])["hata"]


def test_admin_history_tool(client, auth_headers, ai_on, monkeypatch):
    client.post("/api/domains", headers=auth_headers, json={"domain": "ai-gecmis.firma.local"})
    fake = FakeAi([_tool("kayit_gecmisi", {"metin": "ai-gecmis"}), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=auth_headers,
                    json={"messages": [{"role": "user", "content": "ai-gecmis'i kim ekledi"}]})
    assert r.status_code == 200
    rows = json.loads(fake.bodies[1]["messages"][-1]["content"])["kayitlar"]
    assert rows and rows[0]["islem"] == "create" and rows[0]["kullanici"]


def test_falls_back_without_tools(client, auth_headers, ai_on, monkeypatch):
    fake = FakeAi([ai_assistant._HttpError(400, "tools not supported"), _text("genel cevap")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=auth_headers,
                    json={"messages": [{"role": "user", "content": "CSR nedir?"}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"answer": "genel cevap", "tools_used": [], "tool_mode": False}
    assert "tools" not in fake.bodies[1]


def test_daily_limit(client, auth_headers, ai_on, monkeypatch):
    client.put("/api/settings/ai", headers=auth_headers, json={"daily_limit": 1})
    monkeypatch.setattr(ai_assistant, "_post", FakeAi([_text("bir"), _text("iki")]))
    q = {"messages": [{"role": "user", "content": "selam"}]}
    assert client.post("/api/ai/chat", headers=auth_headers, json=q).status_code == 200
    r = client.post("/api/ai/chat", headers=auth_headers, json=q)
    assert r.status_code == 400 and "sınır" in r.json()["detail"]


def test_service_errors_are_readable(client, auth_headers, ai_on, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_post", FakeAi([ai_assistant.AiError("AI servisi anahtarı kabul etmedi (HTTP 401)")]))
    r = client.post("/api/ai/chat", headers=auth_headers,
                    json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 400 and "anahtar" in r.json()["detail"]


def test_connection_test_admin_only(client, auth_headers, ai_on, monkeypatch):
    monkeypatch.setattr(ai_assistant, "_post", FakeAi([_text("tamam")]))
    r = client.post("/api/ai/test", headers=auth_headers)
    assert r.json()["success"] is True and "tamam" in r.json()["message"]
    own = _sy_team(client, auth_headers, "AiTest")
    hdr = _user_in(client, auth_headers, "ai_viewer2", own)
    assert client.post("/api/ai/test", headers=hdr).status_code == 403


# ---------------------------------------------------------------- v3.9.16: tam erişim
def _last_tool_result(fake, i):
    return json.loads(fake.bodies[i]["messages"][-1]["content"])


def test_full_access_viewer_sees_other_teams_and_history(client, auth_headers, ai_on, monkeypatch):
    own = _sy_team(client, auth_headers, "AiFullOwn")
    other = _sy_team(client, auth_headers, "AiFullOther")
    hdr = _user_in(client, auth_headers, "ai_full_viewer", own)
    dom = client.post("/api/domains", headers=auth_headers,
                      json={"domain": "ai-full-other.firma.local", "sy_team_id": other}).json()
    fake = FakeAi([_tool("domain_detay", {"id": dom["id"]}),
                   _tool("kayit_gecmisi", {"son_gun": 1}, "c2"), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=hdr,
                    json={"messages": [{"role": "user", "content": "ai-full-other kimin?"}]})
    assert r.status_code == 200, r.text
    assert _last_tool_result(fake, 1)["sy_ekip"] == "AiFullOther"
    rows = _last_tool_result(fake, 2)["kayitlar"]
    # Uygulama değişiklikleri görünür; girişler, kullanıcı/ayar değişiklikleri ve AI soruları görünmez
    assert any(x["nesne"] == "domains" for x in rows)
    assert not [x for x in rows if x["islem"] in ("login", "login_failed", "ai_ask")
                or x["nesne"] in ("users", "app_settings")]
    names = [t["function"]["name"] for t in fake.bodies[0]["tools"]]
    assert {"kayit_gecmisi", "veri_tablolari", "veri_sorgula"} <= set(names)
    assert "tüm uygulama verisini" in fake.bodies[0]["messages"][0]["content"]
    # Audit'e yine gerçek kullanıcı yazılır
    audit = client.get("/api/audit?action=ai_ask", headers=auth_headers).json()["items"]
    assert audit[0]["username"] == "ai_full_viewer"


def test_data_tools_hide_personal_fields(client, auth_headers, ai_on, monkeypatch):
    team = _sy_team(client, auth_headers, "AiData")
    hdr = _user_in(client, auth_headers, "ai_data_viewer", team)
    client.post("/api/domains", headers=auth_headers,
                json={"domain": "ai-data-1.firma.local", "sy_team_id": team})
    client.post("/api/domains", headers=auth_headers,
                json={"domain": "ai-data-2.firma.local", "sy_team_id": team})
    fake = FakeAi([
        _tool("veri_tablolari", {}),
        _tool("veri_tablolari", {"tablo": "kullanicilar"}, "c2"),
        _tool("veri_sorgula", {"tablo": "kullanicilar", "filtreler": [
            {"alan": "username", "islem": "=", "deger": "AI_DATA_VIEWER"}]}, "c3"),
        _tool("veri_sorgula", {"tablo": "domainler", "alanlar": ["domain", "sy_team_id"], "filtreler": [
            {"alan": "domain", "islem": "icerir", "deger": "ai-data-"}]}, "c4"),
        _tool("veri_sorgula", {"tablo": "domainler", "grupla": ["sy_team_id"], "filtreler": [
            {"alan": "domain", "islem": "baslar", "deger": "ai-data-"}]}, "c5"),
        _tool("veri_sorgula", {"tablo": "kullanicilar", "alanlar": ["email"]}, "c6"),
        _tool("veri_sorgula", {"tablo": "islem_gecmisi", "filtreler": [
            {"alan": "action", "islem": "liste", "deger": "login,ai_ask"}]}, "c7"),
        _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    r = client.post("/api/ai/chat", headers=hdr,
                    json={"messages": [{"role": "user", "content": "veri"}]})
    assert r.status_code == 200, r.text
    tables = _last_tool_result(fake, 1)["tablolar"]
    assert "domainler" in tables and "app_settings" not in tables and "ayarlar" not in tables
    fields = _last_tool_result(fake, 2)["alanlar"]
    assert "username" in fields and not {"email", "password_hash", "last_login"} & set(fields)
    users = _last_tool_result(fake, 3)
    assert users["toplam"] == 1 and set(users["satirlar"][0]) == {
        "id", "username", "full_name", "role", "auth_source", "is_active"}
    doms = _last_tool_result(fake, 4)
    assert doms["toplam"] == 2
    row = doms["satirlar"][0]
    assert row["domain"] == "ai-data-1.firma.local" and row["sy_team_adi"] == "AiData"
    assert row["link"] == f"/domains?domain={row['id']}"
    groups = _last_tool_result(fake, 5)["gruplar"]
    assert groups == [{"sy_team_id": team, "adet": 2, "sy_team_adi": "AiData"}]
    assert "email" in _last_tool_result(fake, 6)["hata"]
    assert _last_tool_result(fake, 7)["toplam"] == 0   # giriş kayıtları ve AI soruları gizli


def test_data_tool_admin_sees_logins_but_never_ai_questions(client, auth_headers, ai_on, monkeypatch):
    fake = FakeAi([_tool("veri_sorgula", {"tablo": "islem_gecmisi", "grupla": ["action"], "filtreler": [
        {"alan": "action", "islem": "liste", "deger": ["login", "ai_ask"]},
        {"alan": "created_at", "islem": ">=", "deger": "2020-01-01"}]}), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers, json={"messages": [{"role": "user", "content": "x"}]})
    groups = {g["action"]: g["adet"] for g in _last_tool_result(fake, 1)["gruplar"]}
    assert groups.get("login", 0) >= 1 and "ai_ask" not in groups


def test_data_tools_hidden_for_team_roles_in_scoped_mode(client, auth_headers, ai_on, monkeypatch):
    _scoped(client, auth_headers)
    team = _sy_team(client, auth_headers, "AiDataScoped")
    hdr = _user_in(client, auth_headers, "ai_data_scoped", team, role="editor")
    fake = FakeAi([_tool("veri_sorgula", {"tablo": "domainler"}), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=hdr, json={"messages": [{"role": "user", "content": "x"}]})
    assert _last_tool_result(fake, 1) == {"hata": "Bu araç bu kullanıcıya kapalı"}


def test_wiki_tool_answers_how_to_from_company_wiki(client, auth_headers, ai_on, wiki_on, monkeypatch):
    fake = FakeAi([_tool("kilavuz_ara", {"metin": "yeni domain nasıl eklenir"}),
                   _tool("kilavuz_oku", {"adres": "Değişiklik talepleri"}, "c2"),
                   _text("[Domain ekleme](https://wiki.firma.local/confluence/display/JUMBO/Domain+ekleme)")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    hdr = _user_in(client, auth_headers, "ai_wiki_viewer", _sy_team(client, auth_headers, "AiWikiTeam"))
    r = client.post("/api/ai/chat", headers=hdr,
                    json={"messages": [{"role": "user", "content": "Yeni domain nasıl eklenir?"}]})
    assert r.status_code == 200, r.text
    hit = _last_tool_result(fake, 1)["en_uygun"]
    assert hit["link"] == "https://wiki.firma.local/confluence/display/JUMBO/Domain+ekleme"
    assert "1. Domainler ekranında Yeni Domain'e basın." in hit["metin"]
    page = _last_tool_result(fake, 2)
    assert page["baslik"] == "Değişiklik talepleri" and "Ekip Editörü | Onaylar" in page["metin"]
    system = fake.bodies[0]["messages"][0]["content"]
    assert "kilavuz_ara" in system and "kurumun wiki" in system
    assert r.json()["tools_used"] == ["kilavuz_ara", "kilavuz_oku"]


def test_wiki_tools_hidden_until_wiki_link_is_set(client, auth_headers, ai_on, monkeypatch):
    fake = FakeAi([_text("bilmiyorum")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers, json={"messages": [{"role": "user", "content": "nasıl?"}]})
    names = [t["function"]["name"] for t in fake.bodies[0]["tools"]]
    assert "kilavuz_ara" not in names and "kilavuz_oku" not in names
    assert ai_assistant.NO_GUIDE_PROMPT in fake.bodies[0]["messages"][0]["content"]


def test_wiki_down_is_reported_to_ai(client, auth_headers, ai_on, wiki_on, monkeypatch):
    wiki_on.status = 503
    fake = FakeAi([_tool("kilavuz_ara", {"metin": "domain"}), _text("wiki'ye ulaşılamıyor")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers, json={"messages": [{"role": "user", "content": "x"}]})
    assert _last_tool_result(fake, 1)["hata"].startswith("Kullanım Kılavuzu şu an okunamıyor: Wiki hata döndürdü")


def test_policy_tool(client, auth_headers, ai_on, monkeypatch):
    fake = FakeAi([_tool("uyum_ihlalleri", {}), _text("ok")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers, json={"messages": [{"role": "user", "content": "uyum"}]})
    result = _last_tool_result(fake, 1)
    assert {"degerlendirilen", "uyumlu", "uyumsuz", "ihlaller"} <= set(result)


def test_fallback_without_tools_carries_wiki(client, auth_headers, ai_on, wiki_on, monkeypatch):
    fake = FakeAi([ai_assistant._HttpError(400, "tools not supported"), _text("kılavuzdan cevap")])
    monkeypatch.setattr(ai_assistant, "_post", fake)
    client.post("/api/ai/chat", headers=auth_headers,
                json={"messages": [{"role": "user", "content": "Domain nasıl eklenir?"}]})
    system = fake.bodies[1]["messages"][0]["content"]
    assert "KULLANIM KILAVUZU" in system
    assert "### Domain ekleme (https://wiki.firma.local/confluence/display/JUMBO/Domain+ekleme)" in system
    assert len(system) < ai_assistant.WIKI_DIGEST_CHARS + 6000
