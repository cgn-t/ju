"""Zaman yardımcıları. Proje geneli NAIVE-UTC sözleşmesini korur (DB kolonları tz-bilgisiz saklar;
tüm karşılaştırmalar naive). `datetime.utcnow()` Python 3.12'de deprecated → bunu kullan.

DİKKAT: Bilinçli olarak tz-AWARE dönmez. tz-aware bir değer, mevcut naive DB/parser değerleriyle
karşılaştırıldığında TypeError verirdi (_days_left, notifier eşikleri vb.). Naive-UTC tek tip kalır.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")


def utcnow() -> datetime:
    """Şu anki UTC zamanı, NAIVE (tzinfo=None) olarak — datetime.utcnow() ile aynı sözleşme, deprecated değil."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ist_day_start_utc(d: date) -> datetime:
    """İstanbul takvim günü başlangıcı → naive-UTC (ekran İstanbul gösterir, DB naive-UTC saklar)."""
    return datetime(d.year, d.month, d.day, tzinfo=ISTANBUL).astimezone(timezone.utc).replace(tzinfo=None)


def ist_to_utc(dt: datetime) -> datetime:
    """Saat dilimsiz değer İstanbul yerel saatidir → naive-UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ISTANBUL)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def time_window(*, since_hours: int | None = None, start: datetime | None = None,
                end: datetime | None = None, date_from: date | None = None,
                date_to: date | None = None) -> tuple[datetime | None, datetime | None]:
    """Ekran zaman filtrelerini (kayan saat / mutlak İstanbul saati / İstanbul günü) tek bir
    naive-UTC [alt, üst] aralığına çevirir. Üst sınır DAHİL. Verilmeyen uç None."""
    lo = hi = None
    cands_lo, cands_hi = [], []
    if since_hours:
        cands_lo.append(utcnow() - timedelta(hours=since_hours))
    if start:
        cands_lo.append(ist_to_utc(start))
    if date_from:
        cands_lo.append(ist_day_start_utc(date_from))
    if end:
        cands_hi.append(ist_to_utc(end))
    if date_to:
        cands_hi.append(ist_day_start_utc(date_to + timedelta(days=1)) - timedelta(microseconds=1))
    if cands_lo:
        lo = max(cands_lo)
    if cands_hi:
        hi = min(cands_hi)
    return lo, hi
