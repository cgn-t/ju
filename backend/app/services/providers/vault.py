"""HashiCorp Vault PKI sağlayıcısı.

Settings > Vault sekmesindeki alanlar (adres, auth yöntemi, token/approle,
pki mount) saklanıyor. Temel ilişki READ-ONLY'dir:
  - health(): bağlantı + PKI mount kontrolü ("Bağlantıyı Test Et")
  - fetch(): PKI CA zincirini (root/intermediate) envantere almak için okur

Bunların ÜSTÜNE, otomatik CA alımı (issuance, bkz. app/services/issuance.py) için iki ÜRETİM
metodu: sign_csr() (dışarıda üretilmiş bir CSR'ı `sign/{role}` ile imzalar — özel anahtar JUMBO'ya
hiç girmez, ÖNERİLEN/varsayılan yol) ve issue() (`issue/{role}` — Vault'un KENDİSİ anahtar üretir,
private_key döner; yalnız IssuanceProfile.allow_key_return=True profillerde ve issuance servisi
tarafından KALICI SAKLANMADAN kullanılmalıdır). Adres/token bağlantı bilgisi hâlâ Settings >
Vault'tan gelir; mount/role her çağrıda IssuanceProfile'dan parametre olarak geçirilir.
"""

import httpx
from sqlalchemy.orm import Session

from app.services.cert_parser import ParsedCertificate, parse_pem_text
from app.services.providers.base import CertificateProvider, IssuedCertificate
from app.services.settings_service import get_category

# sys/health: 200 aktif, 429 standby, 472 DR standby, 473 perf-standby — hepsi "mühürsüz/erişilebilir"
_HEALTHY_STATUSES = {200, 429, 472, 473}


def _join_chain(data: dict) -> str | None:
    """Vault sign/issue yanıtından intermediate+root zincirini PEM demeti olarak birleştirir.
    Modern Vault `ca_chain` (liste) döner; eski sürümler yalnız `issuing_ca` (tek PEM) verir."""
    chain = data.get("ca_chain")
    if chain:
        return "\n".join(chain)
    issuing_ca = data.get("issuing_ca")
    return issuing_ca or None


class VaultProvider(CertificateProvider):
    name = "vault"

    def __init__(self, db: Session):
        self.config = get_category(db, "vault", mask_secrets=False)

    def _address(self) -> str:
        return (self.config.get("address") or "").rstrip("/")

    def _headers(self) -> dict:
        token = self.config.get("token") or ""
        return {"X-Vault-Token": token} if token else {}

    def is_available(self) -> bool:
        return bool(self.config.get("enabled") and self.config.get("address"))

    def health(self) -> tuple[bool, str]:
        """Bağlantı testi: sys/health + PKI mount'ın CA'sı okunabiliyor mu?"""
        if not self.is_available():
            return False, "Vault entegrasyonu etkin değil (adres veya 'enabled' eksik)"
        address = self._address()
        mount = self.config.get("pki_mount") or "pki"
        try:
            with httpx.Client(timeout=5.0) as client:
                h = client.get(f"{address}/v1/sys/health", headers=self._headers())
                if h.status_code not in _HEALTHY_STATUSES:
                    return False, f"Vault erişilemedi (sys/health HTTP {h.status_code})"
                ca = client.get(f"{address}/v1/{mount}/ca/pem", headers=self._headers())
                if ca.status_code != 200 or "BEGIN CERTIFICATE" not in ca.text:
                    return False, f"Vault erişilebilir ama '{mount}' PKI mount bulunamadı (HTTP {ca.status_code})"
        except httpx.HTTPError as exc:
            return False, f"Vault bağlantı hatası: {exc}"
        return True, f"Vault erişilebilir, PKI mount '{mount}' hazır"

    def fetch(self, identifier: str = "ca_chain") -> list[ParsedCertificate]:
        """PKI CA zincirini (intermediate + root) okur — envantere almak için (read-only)."""
        address = self._address()
        mount = self.config.get("pki_mount") or "pki"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{address}/v1/{mount}/cert/ca_chain", headers=self._headers())
            resp.raise_for_status()
            pem = resp.json().get("data", {}).get("ca_chain") or resp.text
        return parse_pem_text(pem)

    def sign_csr(self, csr_pem: str, common_name: str, sans: list[str],
                 ttl_hours: int | None = None, *, mount: str | None = None,
                 role: str | None = None) -> IssuedCertificate:
        """`POST /v1/{mount}/sign/{role}` — dışarıda üretilmiş CSR'ı imzalar. Özel anahtar hiç
        JUMBO'ya girmez/dönmez (`sign` uç noktası yalnız sertifika döner)."""
        if not role:
            raise ValueError("Vault PKI role gerekli (IssuanceProfile.vault_role)")
        address = self._address()
        mnt = mount or self.config.get("pki_mount") or "pki"
        payload: dict = {"csr": csr_pem, "common_name": common_name}
        if sans:
            payload["alt_names"] = ",".join(sans)
        if ttl_hours:
            payload["ttl"] = f"{ttl_hours}h"
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{address}/v1/{mnt}/sign/{role}", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        return IssuedCertificate(
            pem_certificate=data.get("certificate", ""),
            ca_chain_pem=_join_chain(data),
        )

    def issue(self, common_name: str, sans: list[str], ttl_hours: int | None = None, *,
             mount: str | None = None, role: str | None = None) -> IssuedCertificate:
        """`POST /v1/{mount}/issue/{role}` — Vault'un KENDİSİ anahtar çifti üretir, private_key
        döner. Yalnız `IssuanceProfile.allow_key_return=True` iken çağrılmalı; çağıran (issuance
        servisi) bu değeri KALICI SAKLAMAMALI, yalnız anlık iletim için kullanmalıdır."""
        if not role:
            raise ValueError("Vault PKI role gerekli (IssuanceProfile.vault_role)")
        address = self._address()
        mnt = mount or self.config.get("pki_mount") or "pki"
        payload: dict = {"common_name": common_name}
        if sans:
            payload["alt_names"] = ",".join(sans)
        if ttl_hours:
            payload["ttl"] = f"{ttl_hours}h"
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{address}/v1/{mnt}/issue/{role}", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        return IssuedCertificate(
            pem_certificate=data.get("certificate", ""),
            ca_chain_pem=_join_chain(data),
            private_key_pem=data.get("private_key"),
        )

    # ---- KV v2 (kasa) OKUMA — JUMBO yalnız okur, asla yazmaz ----
    def _kv_mount(self) -> str:
        return self.config.get("kv_mount") or "secret"

    def kv_list(self, prefix: str) -> list[str]:
        """KV v2 metadata altındaki anahtar adlarını listeler (prefix '/' ile biterse alt klasör)."""
        address = self._address()
        mount = self._kv_mount()
        pfx = prefix.strip("/")
        with httpx.Client(timeout=5.0) as client:
            resp = client.request("LIST", f"{address}/v1/{mount}/metadata/{pfx}", headers=self._headers())
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json().get("data", {}).get("keys", [])

    def kv_get(self, path: str) -> dict | None:
        """KV v2 girdisinin veri gövdesini döner (data.data). Yoksa None."""
        address = self._address()
        mount = self._kv_mount()
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{address}/v1/{mount}/data/{path.strip('/')}", headers=self._headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json().get("data", {}).get("data")
