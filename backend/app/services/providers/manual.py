from app.services.cert_parser import ParsedCertificate
from app.services.providers.base import CertificateProvider


class ManualProvider(CertificateProvider):
    """Elle import edilen sertifikalar. Otomatik yenileme desteklemez."""

    name = "manual"

    def fetch(self, identifier: str) -> ParsedCertificate:
        raise NotImplementedError("Manuel sağlayıcı uzaktan sertifika çekemez")

    def renew(self, identifier: str) -> ParsedCertificate:
        raise NotImplementedError("Manuel sertifikalar otomatik yenilenemez")

    def is_available(self) -> bool:
        return True
