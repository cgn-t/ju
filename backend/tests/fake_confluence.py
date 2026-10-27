"""Testlerde gerçek wiki yerine: Confluence REST API'sinin Jumbo'nun kullandığı kadarını taklit eder
(httpx.MockTransport ile; ağa çıkılmaz). Bağlam yolu /confluence, kimlik Bearer token."""

import re

import httpx

BASE = "https://wiki.firma.local/confluence"
ROOT_LINK = f"{BASE}/pages/viewpage.action?pageId=100"

# id → (başlık, üst sayfa id, storage gövdesi, ağaçtaki sıra)
PAGES = {
    "100": ("Jumbo Kullanım Kılavuzu", None, "<p>Jumbo'nun kurum içi kullanım kılavuzu.</p>", None),
    "101": ("Domain ekleme", "100",
            "<h2>Yeni domain</h2><ol><li><p><strong>Domainler</strong> ekranında <strong>Yeni Domain</strong>'e "
            "basın.</p></li><li>Domain adını ve SY ekibini girin.</li></ol>"
            '<ac:structured-macro ac:name="info"><ac:parameter ac:name="title">Not</ac:parameter>'
            "<ac:rich-text-body><p>SY ekibi&nbsp;zorunludur.</p></ac:rich-text-body></ac:structured-macro>", 2),
    "102": ("Değişiklik talepleri", "100",
            "<p>Talepleri domainin SY ekibi onaylar.</p><h3>Kim onaylar?</h3><table><tbody>"
            "<tr><th>Rol</th><th>Yetki</th></tr><tr><td>Ekip Editörü</td><td>Onaylar</td></tr></tbody></table>", 1),
    "103": ("Canlı Doğrulama", "102",
            '<p>Domain detayında <strong>Şimdi Doğrula</strong>.</p><ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">bash</ac:parameter><ac:plain-text-body>'
            "<![CDATA[curl -v https://web.ornek.com]]></ac:plain-text-body></ac:structured-macro>"
            '<p><ac:link><ri:page ri:content-title="Domain ekleme" /></ac:link></p>', None),
    "200": ("Başka bir alanın sayfası", None, "<p>Jumbo okumamalı.</p>", None),
}
EXPAND = "body.storage,version,ancestors"


class FakeConfluence:
    def __init__(self, token: str = "tok", batch: int = 2):
        self.pages = {k: list(v) for k, v in PAGES.items()}
        self.token = token
        self.batch = batch
        self.calls: list[str] = []
        self.status: int | None = None       # verilirse her istek bu HTTP koduyla döner
        self.html_login = False              # SSO giriş sayfası taklidi (200 + HTML)

    def _ancestors(self, pid: str) -> list[dict]:
        out, parent = [], self.pages[pid][1]
        while parent:
            out.insert(0, {"id": parent, "title": self.pages[parent][0]})
            parent = self.pages[parent][1]
        return out

    def item(self, pid: str) -> dict:
        title, _, body, pos = self.pages[pid]
        return {"id": pid, "type": "page", "title": title,
                "extensions": {"position": pos if pos is not None else "none"},
                "body": {"storage": {"value": body, "representation": "storage"}},
                "version": {"number": 3, "when": "2026-10-27T06:00:00.000+03:00"},
                "ancestors": self._ancestors(pid),
                "_links": {"webui": "/display/JUMBO/" + title.replace(" ", "+")}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if self.status:
            return httpx.Response(self.status, text="hata")
        if self.html_login:
            return httpx.Response(200, text="<html>Giriş yapın</html>", headers={"Content-Type": "text/html"})
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Unauthorized"})
        path = request.url.path
        assert path.startswith("/confluence/rest/api/"), path
        rest, params = path[len("/confluence/rest/api"):], request.url.params
        if rest == "/content/search":
            root = re.fullmatch(r"ancestor = (\d+) and type = page", params["cql"]).group(1)
            ids = [p for p in self.pages if any(a["id"] == root for a in self._ancestors(p))]
            start = int(params.get("start", 0))
            chunk = ids[start:start + self.batch]
            links = {"base": BASE, "context": "/confluence"}
            if start + self.batch < len(ids):
                q = httpx.QueryParams({"cql": params["cql"], "expand": EXPAND, "limit": self.batch,
                                       "start": start + self.batch})
                links["next"] = f"/rest/api/content/search?{q}"
            return httpx.Response(200, json={"results": [self.item(p) for p in chunk], "start": start,
                                             "limit": self.batch, "size": len(chunk), "_links": links})
        if rest == "/content":
            found = [p for p, v in self.pages.items() if v[0] == params.get("title")]
            return httpx.Response(200, json={"results": [self.item(p) for p in found], "size": len(found)})
        m = re.fullmatch(r"/content/(\d+)", rest)
        if m:
            if m.group(1) not in self.pages:
                return httpx.Response(404, json={"message": "No content found"})
            return httpx.Response(200, json=self.item(m.group(1)))
        m = re.fullmatch(r"/space/(\w+)", rest)
        if m:
            return httpx.Response(200, json={"key": m.group(1), "homepage": {"id": "100"}})
        return httpx.Response(404, json={"message": "not found"})
