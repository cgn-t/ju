"""Kanal soyutlaması + ortak yardımcılar.

Her kanal egress-gated (opsiyonel proxy) ve GRACEFUL'dur: send() hata fırlatabilir, dispatcher yakalar →
bir kanal patlarsa diğerleri sürer, uygulama asla çökmez. Custody yok — yalnız metin/olay gönderilir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx


@dataclass
class NotifyEvent:
    """Kanala gönderilecek olay (sertifika-merkezli). title/text dispatcher'da TR olarak üretilir."""
    kind: str                       # "expiry" | "expired"
    cert_id: int | None
    cert_name: str
    days_left: int
    title: str
    text: str
    fields: dict = field(default_factory=dict)   # generic webhook için ek alanlar (serial, valid_to…)


def http_client(cfg: dict) -> httpx.Client:
    """Kanal için egress-gated httpx istemcisi (ct_monitor/revocation ile aynı desen).
    proxy_url boşsa doğrudan bağlanır; timeout_seconds yoksa 10 sn."""
    return httpx.Client(
        proxy=(cfg.get("proxy_url") or None),
        timeout=float(cfg.get("timeout_seconds") or 10),
        headers={"User-Agent": "JUMBO-CLM/notify"},
    )


class NotificationChannel(ABC):
    """Bir bildirim kanalı. `name` hem kanal kimliği hem settings kategorisidir (ör. 'slack')."""

    name: str

    def is_enabled(self, cfg: dict) -> bool:
        return bool(cfg.get("enabled"))

    @abstractmethod
    def send(self, cfg: dict, event: NotifyEvent) -> bool:
        """Olayı kanala gönderir. Başarılıysa True; hedef tanımsızsa False; ağ/HTTP hatası FIRLATIR."""

    @abstractmethod
    def test(self, cfg: dict) -> tuple[bool, str]:
        """Ayarlar 'Test' butonu: kısa bir deneme mesajı gönderir → (ok, kullanıcıya mesaj)."""
