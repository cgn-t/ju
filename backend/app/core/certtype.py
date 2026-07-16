"""Sertifika tipi (cert_type / CertType) normalizasyonu — TEK gerçek kaynak.

Kod tabanının her yeri cert_type'ı kanonik küçük-harf ("root" | "intermediate" | "leaf")
kabul eder: parser bu biçimde üretir, API şeması bu biçimde doğrular, harita/filtre/yenileme
bu biçimde karşılaştırır. Prod/legacy DB ise CertType kolonunu normalize edilmemiş tutabilir
("Intermediate", " LEAF ", "ROOT", NULL). Bu değerler DB'den HAM okunduğunda:
  • harita düğümü küçük-harf frontend filtresine takılıp GİZLENİR (harita boş görünür),
  • strict Literal şemada 500 verir.
Bu yardımcı, ham değeri okuma anında kanonik forma indirger; tanınmayan/boş → 'leaf'."""

VALID_CERT_TYPES = ("root", "intermediate", "leaf")


def normalize_cert_type(value) -> str:
    """Ham cert_type değerini kanonik küçük-harf forma indirger.

    "Intermediate" → "intermediate", " LEAF " → "leaf", "ROOT" → "root".
    Tanınmayan değer / boş / None → "leaf" (varsayılan; sertifikaların çoğunluğu leaf'tir
    ve leaf en kısıtsız/güvenli varsayılandır)."""
    if isinstance(value, str):
        value = value.strip().lower()
    return value if value in VALID_CERT_TYPES else "leaf"


def cert_type_filter(column, value):
    """SQL-seviyesi cert_type eşleme filtresi — normalize_cert_type ile SİMETRİK.

    Kolon DB'de ham durabilir ("Intermediate", " LEAF ", NULL); LOWER/LTRIM/RTRIM
    (MSSQL ve SQLite'ta ortak) ile kanonik forma indirip karşılaştırır. 'leaf'
    aranıyorsa NULL ve tanınmayan değerler de eşleşir (Python normalize'ın
    NULL/tanınmayan→'leaf' kuralıyla aynı sonuç kümesi)."""
    from sqlalchemy import func

    canonical = normalize_cert_type(value)
    norm_col = func.lower(func.ltrim(func.rtrim(column)))
    if canonical == "leaf":
        return column.is_(None) | norm_col.notin_(("root", "intermediate"))
    return norm_col == canonical
