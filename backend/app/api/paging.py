"""Sunucu-taraflı sayfalama yardımcıları (Domainler, Sertifikalar, Uygulamalar, Keşif,
Değişiklik Talepleri).

Liste uçları önce HAFİF bir projeksiyon (yalnız filtre/sıralama kolonları) çeker, süzme ve
sıralamayı Python'da yapar, yalnız istenen sayfanın kayıtlarını tam yükleyip serileştirir.
Birkaç bin satırlık projeksiyon milisaniyeler sürer; asıl yavaşlık (tüm kayıtların ilişkileriyle
serileştirilmesi ve tarayıcıda binlerce satır çizilmesi) ortadan kalkar. Süzme Python'da olduğu
için SQLite (test) ile MSSQL (prod, Turkish_CI_AS) aynı sonucu verir; DB değişikliği gerekmez.
"""

import unicodedata
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")

MAX_PAGE_SIZE = 200


def fold_search(text: str | None) -> str:
    """Arama katlaması — frontend `foldText` ve MSSQL Latin1_General_CI_AI ile aynı davranış:
    büyük/küçük harf, Türkçe I/İ/ı ve aksan farkı yok sayılır ("islem" → "İşlem"i bulur)."""
    t = (text or "").replace("İ", "i").replace("I", "i").replace("ı", "i")
    t = unicodedata.normalize("NFD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def contains(haystack: str | None, needle: str | None) -> bool:
    """`needle` boşsa her şey eşleşir."""
    if not needle:
        return True
    return fold_search(needle) in fold_search(haystack)


def any_contains(values: Iterable[str | None], needle: str | None) -> bool:
    if not needle:
        return True
    n = fold_search(needle)
    return any(n in fold_search(v) for v in values)


def sort_key_text(value: str | None) -> tuple[int, str]:
    """Boş değerler sona — artan/azalan sıralamada da hep sonda kalsın diye ayrı tutulur."""
    return (0, fold_search(value)) if value else (1, "")


def sort_rows(rows: list[T], key: Callable[[T], object], descending: bool,
              empty: Callable[[T], bool] | None = None) -> list[T]:
    """Kararlı sıralama; `empty` verilirse boş değerli satırlar yön ne olursa olsun sonda kalır."""
    if empty is None:
        return sorted(rows, key=key, reverse=descending)
    filled = [r for r in rows if not empty(r)]
    blank = [r for r in rows if empty(r)]
    return sorted(filled, key=key, reverse=descending) + blank


def page_slice(rows: Sequence[T], page: int, size: int) -> tuple[list[T], int]:
    """(sayfadaki satırlar, düzeltilmiş sayfa no). Sayfa aralık dışındaysa son sayfaya çekilir —
    filtre daralınca 'boş 5. sayfa' görünmez."""
    total = len(rows)
    last = max(0, (total - 1) // size) if total else 0
    page = min(max(0, page), last)
    start = page * size
    return list(rows[start:start + size]), page


def count_by(rows: Iterable[T], key: Callable[[T], str], options: Iterable[str]) -> dict[str, int]:
    """Kolon-başı (huni) filtre menüsündeki seçenek sayaçları; 'all' = toplam."""
    counts = {o: 0 for o in options}
    total = 0
    for r in rows:
        total += 1
        v = key(r)
        if v in counts:
            counts[v] += 1
    counts["all"] = total
    return counts


def validity_bucket(days: int | None) -> str:
    """Kalan gün → durum kovası (frontend validityBucket/certStatus ile aynı eşikler)."""
    if days is None:
        return "none"
    if days < 0:
        return "expired"
    if days <= 30:
        return "expiring"
    return "valid"
