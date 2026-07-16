"""Zaman yardımcıları. Proje geneli NAIVE-UTC sözleşmesini korur (DB kolonları tz-bilgisiz saklar;
tüm karşılaştırmalar naive). `datetime.utcnow()` Python 3.12'de deprecated → bunu kullan.

DİKKAT: Bilinçli olarak tz-AWARE dönmez. tz-aware bir değer, mevcut naive DB/parser değerleriyle
karşılaştırıldığında TypeError verirdi (_days_left, notifier eşikleri vb.). Naive-UTC tek tip kalır.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Şu anki UTC zamanı, NAIVE (tzinfo=None) olarak — datetime.utcnow() ile aynı sözleşme, deprecated değil."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
