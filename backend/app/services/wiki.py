"""Kullanım Kılavuzu: kurumun kendi wiki'sinden (Confluence ya da Azure DevOps/TFS wiki) okunur;
Jumbo'da kılavuz tablosu yok.

Sahibin kararı (27.10.2026): kılavuz kurum wiki'sinde yazılır ve güncellenir, Jumbo AI oradan okur.
Ayarlar > AI Asistanı:
  wiki_url             kılavuzun wiki'deki ana sayfasının linki. Jumbo bu sayfayı ve altındaki bütün
                       sayfaları okur; wiki'nin başka hiçbir yerine bakmaz, hiçbir şey yazmaz.
  wiki_auth_mode       bearer (Data Center kişisel erişim token'ı) | basic (kullanıcı + token/şifre;
                       Cloud'da hesap e-postası + API token). Azure DevOps'ta her zaman basic: kişisel
                       erişim token'ı (PAT), kullanıcı adı boş kalabilir.
  wiki_username, wiki_token (gizli)
  wiki_refresh_minutes metin bu kadar dakika bellekte tutulur, sonra wiki'den yeniden okunur.
Desteklenen linkler (Confluence):
  …/pages/viewpage.action?pageId=123            (Data Center / Server)
  …/display/ALAN/Sayfa+Adi                      (Data Center / Server)
  …/spaces/ALAN/pages/123/Sayfa+Adi             (Cloud ve yeni Data Center)
  …/display/ALAN  ya da  …/spaces/ALAN/overview (alanın ana sayfası)
Desteklenen linkler (Azure DevOps Server / TFS ve Azure DevOps Services; linkte "/_wiki" geçer):
  …/Proje/_wiki/wikis/Proje.wiki/12/Sayfa-Adi           (sayfa numaralı)
  …/Proje/_wiki/wikis/Proje.wiki?pagePath=%2FSayfa      (sayfa yolu; eski TFS sürümleri)
  …/Proje/_wiki/wikis/Proje.wiki  ya da  …/Proje/_wiki  (bütün wiki)
  Sayfa ağacı ?recursionLevel=full ile, her sayfanın Markdown metni ayrıca okunur. Sunucunun desteklediği
  REST sürümü (6.0 → 5.0 → 4.1) kendiliğinden bulunur.
"Wiki'yi Şimdi Oku" (POST /api/ai/wiki/refresh) app_settings'e zaman damgası yazar; her pod bir sonraki
soruda bunu görüp wiki'yi yeniden okur. Wiki'ye ulaşılamazsa elde olan son metin kullanılmaya devam eder.
"""

import base64
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, unquote_plus, urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core.textmatch import fold
from app.db.models import AppSetting
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)

REFRESH_KEY = "wiki.refresh_requested"
MAX_PAGES = 300              # ana sayfa + alt sayfalar; fazlası okunmaz
MAX_PAGE_CHARS = 40_000      # bir sayfadan alınan en fazla metin
SEARCH_BATCH = 50            # CQL aramasında sayfa başına sonuç
RETRY_SECONDS = 60           # okuma başarısızsa bu süre içinde tekrar denenmez
AZURE_VERSIONS = ("6.0", "5.0", "4.1")   # Azure DevOps REST sürümleri; sunucu hangisini kabul ederse

_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


class WikiError(Exception):
    """Kullanıcıya (yöneticiye) gösterilecek, anlaşılır hata."""


class _HttpStatus(WikiError):
    def __init__(self, status: int, text: str, message: str | None = None):
        super().__init__(message or f"Wiki hata döndürdü (HTTP {status}).")
        self.status = status
        self.text = text


@dataclass
class GuidePage:
    id: str
    title: str
    url: str
    text: str
    parent: str | None = None
    position: float = float("inf")
    depth: int = 0
    updated: str | None = None


def is_configured(cfg: dict) -> bool:
    return bool((cfg.get("wiki_url") or "").strip())


def is_azure(url: str | None) -> bool:
    """Azure DevOps (TFS) wiki linki mi? Bu wiki'nin bütün adreslerinde "/_wiki" geçer."""
    return "/_wiki" in urlsplit((url or "").strip()).path


# ---------------------------------------------------------------- link çözümleme
def parse_link(url: str) -> tuple[str, str | None, str | None, str | None]:
    """Sayfa linki → (wiki tabanı, sayfa id, alan anahtarı, sayfa adı)."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise WikiError("Kılavuz linki http(s):// ile başlayan tam bir wiki sayfası linki olmalı.")
    path = parts.path
    origin = f"{parts.scheme}://{parts.netloc}"
    page_id = (parse_qs(parts.query).get("pageId") or [None])[0]
    if page_id and "/pages/" in path:
        return origin + path.split("/pages/", 1)[0], page_id, None, None
    m = re.search(r"/spaces/([^/]+)/pages/(\d+)", path)
    if m:
        return origin + path[:m.start()], m.group(2), m.group(1), None
    m = re.search(r"/spaces/([^/]+)(/overview)?/?$", path)
    if m:
        return origin + path[:m.start()], None, m.group(1), None
    m = re.search(r"/display/([^/]+)(?:/([^/]+))?/?$", path)
    if m:
        title = unquote_plus(m.group(2)) if m.group(2) else None
        return origin + path[:m.start()], None, m.group(1), title
    if re.search(r"/x/[^/]+/?$", path):
        raise WikiError("Kısa link (…/x/…) desteklenmiyor; sayfanın tam linkini girin.")
    raise WikiError("Link bir Confluence ya da Azure DevOps (TFS) wiki sayfasına benzemiyor. Örnek: "
                    "https://wiki.firma.local/display/ALAN/Sayfa+Adi ya da "
                    "https://tfs.firma.local/tfs/DefaultCollection/Proje/_wiki/wikis/Proje.wiki/12/Sayfa")


def parse_azure_link(url: str) -> tuple[str, str | None, str | None, str | None]:
    """Azure DevOps wiki linki → (proje adresi, wiki adı, sayfa yolu, sayfa numarası)."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise WikiError("Kılavuz linki http(s):// ile başlayan tam bir wiki sayfası linki olmalı.")
    prefix, _, rest = parts.path.partition("/_wiki")
    if not prefix.strip("/"):
        raise WikiError("Linkte proje adı yok. Wiki sayfasını tarayıcıda açıp adres çubuğundaki linkin "
                        "tamamını girin (…/Proje/_wiki/wikis/…).")
    segs = [unquote(s) for s in rest.split("/") if s]
    wiki_id = segs[1] if len(segs) > 1 and segs[0] == "wikis" else None
    page_id = segs[2] if len(segs) > 2 and segs[0] == "wikis" and segs[2].isdigit() else None
    page_path = (parse_qs(parts.query).get("pagePath") or [None])[0]
    return f"{parts.scheme}://{parts.netloc}{prefix}", wiki_id, page_path, page_id


# ---------------------------------------------------------------- Confluence storage → düz metin
_SKIP = {"ac:parameter", "ac:image", "ac:emoticon", "ac:placeholder", "script", "style"}
_BLOCK = {"p", "div", "table", "blockquote", "pre", "hr", "section", "ac:layout-section", "ac:layout-cell",
          "ac:rich-text-body", "ac:task-list"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.lists: list[list] = []      # [tür, sayaç]
        self.cell = 0
        self.pre = 0
        self.inline = 0                  # madde ya da tablo hücresi içi: paragraf yeni satır açmaz

    def _tail(self) -> str:
        return "".join(self.out[-4:])

    def _nl(self, blank: bool = False):
        want = 2 if blank else 1
        tail = self._tail()
        have = len(tail) - len(tail.rstrip("\n"))
        if have < want:
            self.out.append("\n" * (want - have))

    def _space(self):
        tail = self._tail()
        if tail and not tail[-1].isspace():
            self.out.append(" ")

    def handle_starttag(self, tag, attrs):
        if self.skip or tag in _SKIP:
            # Panel başlığı (ac:parameter name=title) metne dahil; diğer makro parametreleri değil
            if tag == "ac:parameter" and dict(attrs).get("ac:name") == "title" and not self.skip:
                self._nl(True)
                return
            if tag in _SKIP:
                self.skip += 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._nl(True)
            self.out.append("## " if tag in ("h1", "h2") else "### ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
        elif tag in ("li", "ac:task"):
            self.inline += 1
            self._nl()
            depth = max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol" and tag == "li":
                self.lists[-1][1] += 1
                self.out.append("  " * depth + f"{self.lists[-1][1]}. ")
            else:
                self.out.append("  " * depth + "- ")
        elif tag == "tr":
            self._nl()
            self.cell = 0
        elif tag in ("td", "th"):
            self.inline += 1
            if self.cell:
                self.out.append(" | ")
            self.cell += 1
        elif tag == "br":
            self._nl()
        elif tag in _BLOCK:
            if self.inline:
                self._space()
            else:
                self._nl(True)
        if tag in ("pre", "ac:plain-text-body"):
            self.pre += 1

    def handle_endtag(self, tag):
        if self.skip:
            if tag in _SKIP:
                self.skip -= 1
            return
        if tag in ("li", "ac:task", "td", "th") and self.inline:
            self.inline -= 1
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self._nl()
        elif re.fullmatch(r"h[1-6]", tag) or tag in _BLOCK:
            if self.inline:
                self._space()
            else:
                self._nl(True)
        elif tag == "ac:parameter":      # panel başlığı bitti
            self._nl()
        if tag in ("pre", "ac:plain-text-body") and self.pre:
            self.pre -= 1

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data if self.pre else re.sub(r"\s+", " ", data))

    def _cdata(self, data: str) -> bool:
        if data.startswith("CDATA["):
            if not self.skip:
                self.out.append("\n" + data[6:].removesuffix("]]") + "\n")
            return True
        return False

    def unknown_decl(self, data):
        self._cdata(data)

    def handle_comment(self, data):         # yeni Python sürümleri CDATA'yı yorum olarak verebilir
        if data.startswith("[CDATA["):
            self._cdata(data[1:])


def storage_to_text(html: str) -> str:
    p = _Text()
    try:
        p.feed(html or "")
        p.close()
    except Exception:      # bozuk işaretleme sayfayı düşürmesin
        logger.warning("Wiki sayfası metne çevrilirken hata", exc_info=True)
    lines = [ln.rstrip().replace("\xa0", " ") for ln in "".join(p.out).split("\n")]
    text = "\n".join(ln if ln.strip() else "" for ln in lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_PAGE_CHARS]


# ---------------------------------------------------------------- wiki'den okuma
def _headers(cfg: dict) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "JUMBO-CLM/wiki"}
    token = cfg.get("wiki_token") or ""
    if is_azure(cfg.get("wiki_url")) and token:
        # Azure DevOps kişisel erişim token'ını (PAT) Basic ":PAT" ile kabul eder. Kullanıcı adı gönderilmez:
        # Confluence için girilip ekranda gizlenen eski bir kullanıcı adı TFS'te 401'e yol açıyordu (v3.9.18)
        headers["Authorization"] = "Basic " + base64.b64encode(f":{token}".encode()).decode()
    elif cfg.get("wiki_auth_mode") == "basic":
        raw = f"{cfg.get('wiki_username') or ''}:{token}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _client(cfg: dict) -> httpx.Client:
    return httpx.Client(headers=_headers(cfg), follow_redirects=False,
                        timeout=float(cfg.get("timeout_seconds") or 30),
                        verify=not bool(cfg.get("skip_cert_verify")))


def _get(client: httpx.Client, url: str, params: dict | None = None) -> dict:
    try:
        r = client.get(url, params=params)
    except httpx.TimeoutException:
        raise WikiError("Wiki zamanında cevap vermedi (zaman aşımı).")
    except httpx.HTTPError as exc:
        raise WikiError(f"Wiki'ye bağlanılamadı: {exc}")
    if r.status_code == 401:
        raise _HttpStatus(401, r.text[:1000], "Wiki kullanıcı adını ya da token'ı kabul etmedi (HTTP 401).")
    if r.status_code == 403:
        raise _HttpStatus(403, r.text[:1000], "Bu hesabın kılavuz sayfasını okuma yetkisi yok (HTTP 403).")
    if r.status_code == 404:
        raise _HttpStatus(404, r.text[:1000], "Kılavuz sayfası wiki'de bulunamadı (HTTP 404). Linki ve "
                                              "hesabın bu sayfayı görme yetkisini kontrol edin.")
    if 300 <= r.status_code < 400:
        raise WikiError(f"Wiki isteği başka bir adrese yönlendirdi (HTTP {r.status_code}); büyük olasılıkla "
                        "giriş sayfasına. Kimlik bilgilerini kontrol edin.")
    if r.status_code >= 400:
        raise _HttpStatus(r.status_code, r.text[:1000])
    try:
        data = r.json()
    except ValueError:
        raise WikiError("Wiki'nin cevabı okunamadı (JSON değil). Link bir wiki sayfası mı, istek giriş "
                        "sayfasına mı gidiyor? Token'ı kontrol edin.")
    if not isinstance(data, dict):
        raise WikiError("Wiki'nin cevabı beklenen biçimde değil.")
    return data


_EXPAND = "body.storage,version,ancestors"


def _page(item: dict, base: str) -> GuidePage:
    links = item.get("_links") or {}
    ancestors = item.get("ancestors") or []
    pos = (item.get("extensions") or {}).get("position")
    version = item.get("version") or {}
    return GuidePage(
        id=str(item.get("id")),
        title=str(item.get("title") or "(başlıksız)"),
        url=(links.get("base") or base) + (links.get("webui") or f"/pages/viewpage.action?pageId={item.get('id')}"),
        text=storage_to_text(((item.get("body") or {}).get("storage") or {}).get("value") or ""),
        parent=str(ancestors[-1]["id"]) if ancestors and ancestors[-1].get("id") is not None else None,
        position=float(pos) if isinstance(pos, (int, float)) else float("inf"),
        updated=version.get("when"),
    )


def fetch(cfg: dict) -> list[GuidePage]:
    """Ana sayfayı ve altındaki bütün sayfaları wiki'den okur (ağaç sırasıyla)."""
    if is_azure(cfg.get("wiki_url")):
        return _fetch_azure(cfg)
    return _fetch_confluence(cfg)


def _fetch_confluence(cfg: dict) -> list[GuidePage]:
    base, page_id, space, title = parse_link(cfg.get("wiki_url") or "")
    api = f"{base}/rest/api"
    with _client(cfg) as client:
        if page_id is None and title:
            found = _get(client, f"{api}/content", {"spaceKey": space, "title": title, "type": "page"})
            if not found.get("results"):
                raise WikiError(f"'{title}' sayfası {space} alanında bulunamadı (ya da hesabın yetkisi yok).")
            page_id = str(found["results"][0]["id"])
        elif page_id is None:
            home = (_get(client, f"{api}/space/{space}", {"expand": "homepage"}).get("homepage") or {})
            if not home.get("id"):
                raise WikiError(f"{space} alanının ana sayfası bulunamadı.")
            page_id = str(home["id"])
        root = _page(_get(client, f"{api}/content/{page_id}", {"expand": _EXPAND}), base)
        pages = {root.id: root}
        data = _get(client, f"{api}/content/search", {
            "cql": f"ancestor = {page_id} and type = page", "expand": _EXPAND, "limit": SEARCH_BATCH})
        while True:
            for item in data.get("results") or []:
                if len(pages) >= MAX_PAGES:
                    break
                p = _page(item, base)
                pages.setdefault(p.id, p)
            nxt = (data.get("_links") or {}).get("next")
            if not nxt or len(pages) >= MAX_PAGES or not data.get("results"):
                break
            next_url = ((data.get("_links") or {}).get("base") or base) + nxt
            if urlsplit(next_url).netloc != urlsplit(base).netloc:   # token başka adrese gitmesin
                break
            data = _get(client, next_url)
    return _tree_order(root, pages)


def _tree_order(root: GuidePage, pages: dict[str, GuidePage]) -> list[GuidePage]:
    children: dict[str, list[GuidePage]] = {}
    for p in pages.values():
        if p is not root:
            parent = p.parent if p.parent in pages else root.id
            children.setdefault(parent, []).append(p)
    out: list[GuidePage] = []

    def walk(p: GuidePage, depth: int):
        p.depth = depth
        out.append(p)
        for c in sorted(children.get(p.id, []), key=lambda c: (c.position, fold(c.title))):
            walk(c, depth + 1)

    walk(root, 0)
    return out


# ---------------------------------------------------------------- Azure DevOps (TFS) wiki
_MD_DROP = [
    (re.compile(r"\[\[_TO(?:C|SP)_\]\]"), ""),                      # içindekiler / alt sayfa listesi
    (re.compile(r"<!--.*?-->", re.S), ""),                           # yorumlar
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),                        # resimler
    (re.compile(r"(?<!!)\[([^\]]+)\]\([^)]*\)"), r"\1"),                # bağlantı → yalnız metni
    (re.compile(r"</?(?:br|img|div|span|p|b|i|u|font|sup|sub|a|center|details|summary)\b[^>]*>", re.I), " "),
]


def markdown_to_text(md: str) -> str:
    """Azure DevOps wiki sayfası (Markdown): başlık, liste ve tablolar olduğu gibi kalır; resim,
    içindekiler ve HTML etiketleri atılır."""
    text = (md or "").replace("\r", "")
    for pattern, repl in _MD_DROP:
        text = pattern.sub(repl, text)
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_PAGE_CHARS]


def _slug_title(url: str) -> str | None:
    """Linkin son parçasındaki sayfa adı: Azure DevOps boşluğu '-', asıl '-' işaretini '%2D' yazar."""
    _, _, rest = urlsplit(url).path.partition("/_wiki")
    segs = [s for s in rest.split("/") if s]
    return unquote(segs[3].replace("-", " ")) if len(segs) > 3 else None


def _find_node(node: dict, page_id: str, title: str | None) -> dict | None:
    by_title = []

    def walk(n: dict) -> dict | None:
        if str(n.get("id")) == page_id:
            return n
        if title and (n.get("path") or "").rstrip("/").rsplit("/", 1)[-1] == title:
            by_title.append(n)
        for sub in n.get("subPages") or []:
            found = walk(sub)
            if found is not None:
                return found
        return None

    found = walk(node)
    return found or (by_title[0] if len(by_title) == 1 else None)


def _fetch_azure(cfg: dict) -> list[GuidePage]:
    project, wiki_id, page_path, page_id = parse_azure_link(cfg.get("wiki_url") or "")
    origin = urlsplit(project)
    # Koddan yayımlanan wiki'lerde linkteki dal (wikiVersion=GBmain) okunur; proje wiki'si için gerekmez
    branch = (parse_qs(urlsplit(cfg.get("wiki_url") or "").query).get("wikiVersion") or [""])[0]
    extra = ({"versionDescriptor.version": branch[2:], "versionDescriptor.versionType": "branch"}
             if branch.startswith("GB") and branch != "GBwikiMaster" else {})
    with _client(cfg) as client:
        versions = list(AZURE_VERSIONS)

        def call(url: str, params: dict | None = None) -> dict:
            """Sunucunun desteklemediği REST sürümünde bir eskisine geçer; bulunan sürüm saklanır."""
            while True:
                try:
                    return _get(client, url, {**(params or {}), **(extra if "/pages" in url else {}),
                                              "api-version": versions[0]})
                except _HttpStatus as exc:
                    out_of_range = exc.status == 400 and ("api-version" in exc.text.lower()
                                                          or "VersionOutOfRange" in exc.text)
                    if not out_of_range or len(versions) == 1:
                        raise
                    versions.pop(0)

        if wiki_id is None:
            wikis = call(f"{project}/_apis/wiki/wikis").get("value") or []
            if not wikis:
                raise WikiError("Bu projede wiki bulunamadı (ya da token'ın wiki okuma yetkisi yok).")
            wiki_id = next((w for w in wikis if w.get("type") == "projectWiki"), wikis[0]).get("name")
        api = f"{project}/_apis/wiki/wikis/{quote(wiki_id, safe='')}/pages"
        tree = None
        if page_path is None and page_id:
            try:
                page_path = call(f"{api}/{page_id}").get("path")
            except _HttpStatus as exc:
                if exc.status in (401, 403):
                    raise
                # Eski sunucular sayfayı numarayla vermez: bütün ağaçta numara ya da linkteki adla aranır
                tree = _find_node(call(api, {"path": "/", "recursionLevel": "full"}), page_id,
                                  _slug_title(cfg.get("wiki_url") or ""))
                if tree is None:
                    raise WikiError("Linkteki sayfa wiki'de bulunamadı. Sayfayı tarayıcıda açıp linki yeniden "
                                    "kopyalayın ya da ?pagePath=… içeren biçimde girin.")
        if tree is None:
            tree = call(api, {"path": page_path or "/", "recursionLevel": "full"})
        nodes: list[tuple[dict, int, str | None]] = []

        def walk(node: dict, depth: int, parent: str | None):
            if len(nodes) >= MAX_PAGES:
                return
            nodes.append((node, depth, parent))
            for sub in sorted(node.get("subPages") or [], key=lambda n: n.get("order") or 0):
                walk(sub, depth + 1, node.get("path"))

        walk(tree, 0, None)
        out = []
        for node, depth, parent in nodes:
            path = node.get("path") or "/"
            content = node.get("content")
            if content is None and path != "/":
                content = call(api, {"path": path, "includeContent": "true"}).get("content")
            web = node.get("remoteUrl") or (f"{origin.scheme}://{origin.netloc}{urlsplit(project).path}"
                                            f"/_wiki/wikis/{quote(wiki_id, safe='')}?pagePath={quote(path, safe='')}")
            out.append(GuidePage(
                id=str(node.get("id") or path), title=path.rstrip("/").rsplit("/", 1)[-1] or wiki_id,
                url=web, text=markdown_to_text(content or ""), parent=parent, position=node.get("order") or 0,
                depth=depth))
        return out


# ---------------------------------------------------------------- bellek (pod başına)
_lock = threading.Lock()
_state: dict = {"key": None, "pages": [], "fetched_at": None, "fetched_mono": 0.0, "retry_after": 0.0,
                "error": None}


def _config_key(cfg: dict) -> str:
    raw = json.dumps([cfg.get(k) for k in ("wiki_url", "wiki_auth_mode", "wiki_username", "wiki_token",
                                           "skip_cert_verify")])
    return hashlib.sha256(raw.encode()).hexdigest()


def _refresh_requested(db: Session) -> datetime | None:
    row = db.get(AppSetting, REFRESH_KEY)
    try:
        return datetime.fromisoformat(json.loads(row.value)) if row and row.value else None
    except (ValueError, TypeError):
        return None


def request_refresh(db: Session) -> None:
    """Bütün podlar bir sonraki soruda wiki'yi yeniden okusun."""
    value = json.dumps(datetime.now(timezone.utc).isoformat())
    row = db.get(AppSetting, REFRESH_KEY)
    if row is None:
        db.add(AppSetting(key=REFRESH_KEY, category="wiki", value=value))
    else:
        row.value = value
    db.commit()


def pages(db: Session, cfg: dict | None = None, force: bool = False) -> list[GuidePage]:
    """Kılavuz sayfaları. Bellekteki metin taze değilse wiki'den yeniden okunur; okunamazsa son metin
    kullanılır. Hiç metin yoksa WikiError. Kılavuz tanımlı değilse boş liste."""
    cfg = cfg if cfg is not None else get_category(db, "ai", mask_secrets=False)
    if not is_configured(cfg):
        return []
    key = _config_key(cfg)
    ttl = max(1, int(cfg.get("wiki_refresh_minutes") or 15)) * 60
    requested = _refresh_requested(db)
    with _lock:
        st = _state
        now = time.monotonic()
        same = st["key"] == key
        fresh = (same and st["fetched_at"] is not None and now - st["fetched_mono"] < ttl
                 and not (requested and requested > st["fetched_at"]))
        if fresh and not force:
            return st["pages"]
        if same and not force and now < st["retry_after"]:
            if st["pages"]:
                return st["pages"]
            raise WikiError(st["error"] or "Kılavuz okunamadı.")
        try:
            fetched = fetch(cfg)
        except WikiError as exc:
            if not same:
                st.update(key=key, pages=[], fetched_at=None)
            st.update(retry_after=now + RETRY_SECONDS, error=str(exc))
            if st["pages"] and not force:
                logger.warning("Kılavuz wiki'den okunamadı, son okunan metin kullanılıyor: %s", exc)
                return st["pages"]
            raise
        st.update(key=key, pages=fetched, fetched_at=datetime.now(timezone.utc), fetched_mono=now,
                  retry_after=0.0, error=None)
        return fetched


def refresh_now(db: Session, cfg: dict | None = None) -> list[GuidePage]:
    """Ayarlar'daki "Wiki'yi Şimdi Oku": bu pod hemen okur, diğerleri bir sonraki soruda."""
    request_refresh(db)
    return pages(db, cfg, force=True)


def reset_cache() -> None:
    with _lock:
        _state.update(key=None, pages=[], fetched_at=None, fetched_mono=0.0, retry_after=0.0, error=None)


# ---------------------------------------------------------------- arama
def _norm(text: str) -> str:
    return fold(text).translate(_TR)


def _excerpt(body: str, words: list[str], size: int = 240) -> str:
    folded = _norm(body)
    pos = min((i for i in (folded.find(w) for w in words) if i >= 0), default=0)
    start = max(0, pos - 60)
    text = body[start:start + size].replace("\n", " ")
    return ("…" if start else "") + text + ("…" if start + size < len(body) else "")


_STOP = {"nasil", "nedir", "neden", "nerede", "hangi", "hangisi", "icin", "olan", "gibi", "ile", "bir",
         "var", "yok", "nereden", "yapilir", "yaparim", "yapabilirim", "edilir", "ederim", "neler", "kim"}


def _stem(word: str) -> str:
    """Türkçe ekleri kabaca atar: 'eklenir' → 'ekle', 'sertifikayı' → 'sertifik'."""
    return word[:max(4, len(word) - 3)] if len(word) >= 6 else word


def search(guide: list[GuidePage], query: str | None, limit: int = 5) -> list[tuple[GuidePage, str]]:
    """Sorgudaki kelimelerin başlıkta (3 puan) ve metinde (1 puan) geçmesine göre sıralar; harf ve
    aksan duyarsız. Sorgu boşsa sayfalar kılavuz sırasıyla döner."""
    words = [_stem(w) for w in re.split(r"\W+", _norm(query or "")) if len(w) >= 3 and w not in _STOP]
    if not words:
        return [(p, _excerpt(p.text, [])) for p in guide[:limit]]
    scored = []
    for i, p in enumerate(guide):
        title, body = _norm(p.title), _norm(p.text)
        score = sum(3 * (w in title) + (w in body) for w in words)
        if score:
            scored.append((-score, i, p))
    scored.sort()
    return [(p, _excerpt(p.text, words)) for _, _, p in scored[:limit]]


def find(guide: list[GuidePage], ref: str) -> GuidePage | None:
    """Sayfa id'si, linki ya da başlığıyla."""
    ref = str(ref or "").strip()
    for p in guide:
        if ref in (p.id, p.url):
            return p
    return next((p for p in guide if _norm(p.title) == _norm(ref)), None)
