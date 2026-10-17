"""Büyük/küçük harf duyarsız metin eşleştirme.

Prod MSSQL Turkish_CI_AS collation'ında 'I' ile 'i' FARKLI harftir (I↔ı, İ↔i). Bu yüzden
`ILETISIM` araması `iletisim`'i, `ISMAIL.CELIK` girişi `ismail.celik` kullanıcısını bulmaz;
ilike'ın ürettiği LOWER('I') de 'ı' olur. MSSQL'de karşılaştırma Latin1_General collation'ıyla
yapılır (I=i); SQLite (dev/test) ASCII lower ile aynı sonucu verir.
"""

from sqlalchemy import func

# Arama: harf VE aksan duyarsız → "islem"/"ISLEM"/"İŞLEM" hepsi "işlem"i bulur
_SEARCH_COLLATION = "Latin1_General_CI_AI"
# Kimlik eşitliği (kullanıcı adı, domain): yalnız harf duyarsız → "ş" ile "s" ayrı kalır
_EQUAL_COLLATION = "Latin1_General_CI_AS"


def _is_mssql() -> bool:
    from app.db.session import engine
    return engine.dialect.name == "mssql"


def ci_like(column, pattern: str):
    """`column ILIKE pattern` karşılığı; MSSQL'de Türkçe I/i sorunsuz."""
    if _is_mssql():
        return column.collate(_SEARCH_COLLATION).like(pattern)
    return column.ilike(pattern)


def ci_equals(column, value: str):
    """Büyük/küçük harf duyarsız eşitlik (ör. `ADMIN` = `admin`, `ILETISIM.x` = `iletisim.x`)."""
    if _is_mssql():
        return column.collate(_EQUAL_COLLATION) == value
    return func.lower(column) == value.lower()


def fold(text: str | None) -> str:
    """Python tarafı karşılaştırma için katlama: İ/I/ı → i, sonra küçük harf. str.lower()
    'İ'yi 'i̇' (noktalı birleşik) yapar ve 'İmza' ile 'imza' eşleşmezdi."""
    t = (text or "").replace("İ", "i").replace("I", "i").replace("ı", "i")
    return t.lower().replace("̇", "")
