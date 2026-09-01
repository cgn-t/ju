"""Sertifika sağlayıcı soyutlaması.

CertificateProvider iki üretim metodu tanımlar:
  - sign_csr(): dışarıda üretilmiş bir CSR'ı imzalar — ÖZEL ANAHTAR HİÇ JUMBO'YA GİRMEZ (varsayılan/
    önerilen yol, JUMBO'nun "custody dışarıda kalır" ilkesiyle tutarlı).
  - issue(): CA'nın kendisi anahtar çifti üretir, private_key döner — yalnız
    IssuanceProfile.allow_key_return=True iken kullanılabilir; JUMBO bu değeri KALICI SAKLAMAZ,
    yalnız çağıranın (issuance servisinin) anlık kullanımına sunar ve hemen unutur.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.cert_parser import ParsedCertificate


@dataclass
class IssuedCertificate:
    pem_certificate: str                 # imzalanan/üretilen leaf sertifika (PEM)
    ca_chain_pem: str | None = None      # intermediate+root zinciri (varsa)
    private_key_pem: str | None = None   # YALNIZ issue() döner; sign_csr() hiçbir zaman doldurmaz


class CertificateProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, identifier: str) -> ParsedCertificate:
        """Sağlayıcıdan sertifikayı çeker."""

    @abstractmethod
    def sign_csr(self, csr_pem: str, common_name: str, sans: list[str],
                 ttl_hours: int | None = None) -> IssuedCertificate:
        """Dışarıda üretilmiş bir CSR'ı imzalar. Özel anahtar hiç JUMBO'ya girmez — ÖNERİLEN yol."""

    @abstractmethod
    def issue(self, common_name: str, sans: list[str],
              ttl_hours: int | None = None) -> IssuedCertificate:
        """CA'nın kendisi anahtar üretir; private_key döner. Yalnız allow_key_return=True olan
        profillerde çağrılmalı — çağıran bu değeri KALICI SAKLAMAMALIDIR."""

    @abstractmethod
    def is_available(self) -> bool:
        """Sağlayıcı yapılandırılmış ve erişilebilir mi?"""
