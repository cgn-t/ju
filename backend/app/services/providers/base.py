"""Sertifika sağlayıcı soyutlaması.

Bugün tek sağlayıcı 'manual' (elle import). Vault entegrasyonu geldiğinde
VaultProvider bu arayüzü uygulayacak ve certificates.source='vault',
auto_renew=True olan kayıtlar için renew() zamanlanmış job'dan çağrılacak.
"""

from abc import ABC, abstractmethod

from app.services.cert_parser import ParsedCertificate


class CertificateProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, identifier: str) -> ParsedCertificate:
        """Sağlayıcıdan sertifikayı çeker."""

    @abstractmethod
    def renew(self, identifier: str) -> ParsedCertificate:
        """Sertifikayı yeniler ve yeni sertifikayı döner."""

    @abstractmethod
    def is_available(self) -> bool:
        """Sağlayıcı yapılandırılmış ve erişilebilir mi?"""
