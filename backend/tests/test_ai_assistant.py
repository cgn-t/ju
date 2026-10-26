"""AI asistanı (v3.9.15): ayarlar, soru-cevap, araçların kullanıcı yetkisiyle çalışması.

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
        "model": "kurum-model", "assistant_name": "Fil", "daily_limit": 0, "use_tools": True})
    assert r.status_code == 200, r.text
    ai_assistant._usage.clear()
    yield
    client.put("/api/settings/ai", headers=auth_headers, json={"enabled": False, "daily_limit": 100})


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


def test_status_on_shows_name(client, auth_headers, ai_on):
    r = client.get("/api/ai/status", headers=auth_headers)
    assert r.json() == {"enabled": True, "name": "Fil"}


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


def test_tools_respect_user_scope(client, auth_headers, ai_on, monkeypatch):
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
    # Kayıt geçmişi aracı yöneticiye özel: viewer'a hiç sunulmaz
    names = [t["function"]["name"] for t in fake.bodies[0]["tools"]]
    assert "kayit_gecmisi" not in names and "sertifika_ara" in names
    assert "kayit_gecmisi" in [t["function"]["name"] for t in ai_assistant.tool_specs(
        type("U", (), {"role": "admin"})())]


def test_history_tool_refuses_non_admin_even_if_called(client, auth_headers, ai_on, monkeypatch):
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
