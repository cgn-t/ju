"""Testlerde gerçek Azure DevOps Server (TFS) wiki'si yerine: wiki REST API'sinin Jumbo'nun kullandığı
kadarını taklit eder (httpx.MockTransport ile; ağa çıkılmaz). Kimlik: Basic ":<PAT>"."""

import base64
import re

import httpx

PROJECT = "https://tfs.kurum.local/tfs/DefaultCollection/BT%20Proje"
WIKI = "BT-Proje.wiki"
ID_LINK = f"{PROJECT}/_wiki/wikis/{WIKI}/10/Jumbo-Kullan%C4%B1m-K%C4%B1lavuzu"
PATH_LINK = f"{PROJECT}/_wiki/wikis/{WIKI}?pagePath=%2FJumbo%20Kullan%C4%B1m%20K%C4%B1lavuzu&wikiVersion=GBwikiMaster"

ROOT = "/Jumbo Kullanım Kılavuzu"
# yol → (id, sıra, Markdown)
PAGES = {
    ROOT: (10, 0, "[[_TOC_]]\n\nJumbo'nun kurum içi kullanım kılavuzu."),
    f"{ROOT}/Domain ekleme": (11, 1,
        "## Yeni domain\n1. [Domainler](/Domainler) ekranında **Yeni Domain**'e basın.\n"
        "2. Domain adını ve SY ekibini girin.\n\n![ekran](/.attachments/domain.png)\n<!-- iç not -->"),
    f"{ROOT}/Değişiklik talepleri": (12, 0,
        "Talepleri domainin SY ekibi onaylar.\n\n### Kim onaylar?\n| Rol | Yetki |\n|---|---|\n| Ekip Editörü | Onaylar |"),
    f"{ROOT}/Değişiklik talepleri/Canlı Doğrulama": (13, 0, "Domain detayında **Şimdi Doğrula**.<br/>"),
    "/Başka bir sayfa": (20, 1, "Jumbo okumamalı."),
}


def _version(v: str) -> tuple[int, int]:
    major, minor = v.split("-")[0].split(".")
    return int(major), int(minor)


class FakeAzureWiki:
    def __init__(self, pat: str = "pat", max_version: str = "6.0"):
        self.pages = {k: list(v) for k, v in PAGES.items()}
        self.pat = pat
        self.max_version = max_version
        self.calls: list[str] = []

    def _node(self, path: str, content: bool = False) -> dict:
        pid, order, md = self.pages[path] if path in self.pages else (None, 0, "")
        node = {"path": path, "order": order, "gitItemPath": path + ".md",
                "isParentPage": any(p.startswith(path.rstrip("/") + "/") for p in self.pages),
                "remoteUrl": f"{PROJECT}/_wiki/wikis/{WIKI}/{pid}/" + path.rsplit("/", 1)[-1].replace(" ", "-")}
        if pid is not None:
            node["id"] = pid
        if content:
            node["content"] = md
        return node

    def _tree(self, path: str) -> dict:
        node = self._node(path)
        prefix = path.rstrip("/") + "/"
        kids = [p for p in self.pages if p.startswith(prefix) and "/" not in p[len(prefix):]]
        node["subPages"] = [self._tree(k) for k in sorted(kids, key=lambda k: self.pages[k][1])]
        return node

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        expected = "Basic " + base64.b64encode(f":{self.pat}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, text="")
        params = request.url.params
        version = params.get("api-version", "")
        if not version or _version(version) > _version(self.max_version):
            return httpx.Response(400, json={
                "typeKey": "VssVersionOutOfRangeException",
                "message": f"The requested REST API version of {version} is out of range for this server."})
        path = request.url.path
        assert request.url.raw_path.startswith(b"/tfs/DefaultCollection/BT%20Proje/_apis/wiki/wikis"), path
        if path.endswith("/_apis/wiki/wikis"):
            return httpx.Response(200, json={"count": 1, "value": [
                {"id": "a1b2", "name": WIKI, "type": "projectWiki"}]})
        m = re.fullmatch(r".*/wikis/([^/]+)/pages(?:/(\d+))?", path)
        assert m and m.group(1) == WIKI, path
        if m.group(2):
            if _version(version) < (5, 1):
                return httpx.Response(404, json={"message": "not found"})
            found = next((p for p, v in self.pages.items() if v[0] == int(m.group(2))), None)
            if found is None:
                return httpx.Response(404, json={"message": "Page not found"})
            return httpx.Response(200, json=self._node(found))
        page = params.get("path", "/")
        if page != "/" and page not in self.pages:
            return httpx.Response(404, json={"message": f"Wiki page '{page}' could not be found."})
        if params.get("recursionLevel", "").lower() == "full":
            return httpx.Response(200, json=self._tree(page))
        return httpx.Response(200, json=self._node(page, content=params.get("includeContent") == "true"))
