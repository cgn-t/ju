"""Kullanım Kılavuzu (wiki): Jumbo'yla gelen sayfaların kurulumu ve arama.

- ensure_wiki_seed(): açılışta çağrılır. Jumbo'yla gelen (wiki_content.BUILTIN_PAGES) ve daha önce
  hiç eklenmemiş sayfaları ekler; eklenenler app_settings 'wiki.seeded' listesinde tutulur, böylece
  yöneticinin sildiği sayfa geri gelmez. Hiç elle düzenlenmemiş (updated_by boş) sayfanın metni
  yeni sürümdeki metinle güncellenir; yöneticinin düzenlediği sayfaya dokunulmaz.
- search(): AI asistanının ve ekrandaki aramanın ortak, harf/aksan duyarsız araması.
"""

import json
import re

from sqlalchemy.orm import Session

from app.core.textmatch import fold
from app.db.models import AppSetting, WikiPage
from app.services.wiki_content import BUILTIN_PAGES

SEEDED_KEY = "wiki.seeded"

_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def slugify(text: str) -> str:
    s = fold(text).translate(_TR)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "sayfa"


def unique_slug(db: Session, title: str, exclude_id: int | None = None) -> str:
    base = slugify(title)
    slug, n = base, 2
    while True:
        q = db.query(WikiPage.id).filter(WikiPage.slug == slug)
        if exclude_id is not None:
            q = q.filter(WikiPage.id != exclude_id)
        if q.first() is None:
            return slug
        slug, n = f"{base}-{n}", n + 1


def ensure_wiki_seed(db: Session) -> None:
    row = db.get(AppSetting, SEEDED_KEY)
    try:
        seeded = set(json.loads(row.value or "[]")) if row else set()
    except ValueError:
        seeded = set()
    changed = False
    for page in BUILTIN_PAGES:
        existing = db.query(WikiPage).filter(WikiPage.slug == page["slug"]).first()
        if page["slug"] not in seeded:
            seeded.add(page["slug"])
            changed = True
            if existing is None:
                db.add(WikiPage(slug=page["slug"], title=page["title"], category=page["category"],
                                body=page["body"], sort_order=page["sort_order"]))
                continue
        if existing is not None and existing.updated_by is None and (
                existing.title, existing.category, existing.body, existing.sort_order) != (
                page["title"], page["category"], page["body"], page["sort_order"]):
            existing.title, existing.category = page["title"], page["category"]
            existing.body, existing.sort_order = page["body"], page["sort_order"]
    if changed:
        value = json.dumps(sorted(seeded), ensure_ascii=False)
        if row is None:
            db.add(AppSetting(key=SEEDED_KEY, category="wiki", value=value))
        else:
            row.value = value
    db.commit()


def ordered(db: Session) -> list[WikiPage]:
    """Kategoriler ilk sayfalarının sırasına göre, sayfalar kendi sırasına göre."""
    pages = db.query(WikiPage).all()
    first: dict[str, int] = {}
    for p in pages:
        first[p.category] = min(first.get(p.category, p.sort_order or 0), p.sort_order or 0)
    return sorted(pages, key=lambda p: (first[p.category], p.category, p.sort_order or 0, p.title))


def _excerpt(body: str, words: list[str], size: int = 240) -> str:
    folded = fold(body).translate(_TR)
    pos = min((i for i in (folded.find(w) for w in words) if i >= 0), default=0)
    start = max(0, pos - 60)
    text = body[start:start + size].replace("\n", " ")
    return ("…" if start else "") + text + ("…" if start + size < len(body) else "")


_STOP = {"nasil", "nedir", "neden", "nerede", "hangi", "hangisi", "icin", "olan", "gibi", "ile", "bir",
         "var", "yok", "nereden", "yapilir", "yaparim", "yapabilirim", "edilir", "ederim", "neler", "kim"}


def _stem(word: str) -> str:
    """Türkçe ekleri kabaca atar: 'eklenir' → 'ekle', 'sertifikayı' → 'sertifik'."""
    return word[:max(4, len(word) - 3)] if len(word) >= 6 else word


def search(db: Session, query: str | None, limit: int = 5) -> list[tuple[WikiPage, str]]:
    """Sorgudaki kelimelerin başlıkta (3 puan) ve metinde (1 puan) geçmesine göre sıralar.
    Sorgu boşsa tüm sayfalar kılavuz sırasıyla döner."""
    pages = ordered(db)
    words = [_stem(w) for w in re.split(r"\W+", fold(query or "").translate(_TR))
             if len(w) >= 3 and w not in _STOP]
    if not words:
        return [(p, _excerpt(p.body, [])) for p in pages[:limit]]
    scored = []
    for p in pages:
        title = fold(p.title + " " + p.category).translate(_TR)
        body = fold(p.body).translate(_TR)
        score = sum(3 * (w in title) + (w in body) for w in words)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [(p, _excerpt(p.body, words)) for _, p in scored[:limit]]
