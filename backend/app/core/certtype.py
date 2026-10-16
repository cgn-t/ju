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


# SQL karşılaştırmasında kabul edilen yazımlar. LOWER() KULLANILMAZ: Türkçe collation'da
# (Turkish_CI_AS) LOWER('Intermediate') = 'ıntermediate' (noktasız ı) olur ve kayıt 'leaf'
# sayılırdı (2026-10-16 prod vakası). Sabit yazım listesi collation'dan bağımsızdır.
_SQL_SPELLINGS = {t: (t, t.capitalize(), t.upper()) for t in VALID_CERT_TYPES}


def cert_type_filter(column, value):
    """SQL-seviyesi cert_type eşleme filtresi — normalize_cert_type ile SİMETRİK.

    Kolon DB'de ham durabilir ("Intermediate", " LEAF ", NULL); LTRIM/RTRIM sonrası
    bilinen yazımlarla (küçük / Baş harf büyük / BÜYÜK) karşılaştırılır. 'leaf'
    aranıyorsa NULL ve tanınmayan değerler de eşleşir (Python normalize'ın
    NULL/tanınmayan→'leaf' kuralıyla aynı sonuç kümesi)."""
    from sqlalchemy import func

    canonical = normalize_cert_type(value)
    trimmed = func.ltrim(func.rtrim(column))
    if canonical == "leaf":
        ca_spellings = _SQL_SPELLINGS["root"] + _SQL_SPELLINGS["intermediate"]
        return column.is_(None) | trimmed.notin_(ca_spellings)
    return trimmed.in_(_SQL_SPELLINGS[canonical])
