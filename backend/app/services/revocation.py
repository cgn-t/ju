"""Sertifika iptal (revocation) durumu — OCSP ve/veya CRL ile denetler. live_check felsefesinin uzantısı.

EGRESS: OCSP responder / CRL dağıtım noktalarına DIŞ ERİŞİM gerekir. Kapalı banka/OpenShift ağında
erişilemeyebilir (ayrıca iç/özel CA'lar çoğu zaman public OCSP sunmaz → çok sayıda 'unknown' NORMALDİR).
Bu yüzden egress-gated: revocation kategorisi varsayılan KAPALI + opsiyonel proxy; erişilemezse 'unknown'
(çökme yok). Sertifikayı ASLA otomatik pasifleştirmez — yalnız durum gösterir (JUMBO onay-hattı felsefesi).

NOT: OCSP CertID'de SHA-1 kullanımı STANDARTTIR (RFC 6960) — politika motorunun weak_signature kuralıyla
ilgisi yoktur; farklı bağlam.
"""

import json
import logging

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import Certificate
from app.services.cert_parser import find_ca_by_ski
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)


def get_config(db: Session) -> dict:
    return get_category(db, "revocation", mask_secrets=False)


def _client(config: dict) -> httpx.Client:
    return httpx.Client(
        proxy=(config.get("proxy_url") or None),
        timeout=float(config.get("timeout_seconds") or 10),
        headers={"User-Agent": "JUMBO-CLM/revocation"},
        follow_redirects=True,
    )


def extract_ocsp_urls(cert: x509.Certificate) -> list[str]:
    try:
        aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
    except x509.ExtensionNotFound:
        return []
    return [d.access_location.value for d in aia
            if d.access_method == AuthorityInformationAccessOID.OCSP]


def extract_crl_urls(cert: x509.Certificate) -> list[str]:
    try:
        cdp = cert.extensions.get_extension_for_class(x509.CRLDistributionPoints).value
    except x509.ExtensionNotFound:
        return []
    urls: list[str] = []
    for dp in cdp:
        for name in (dp.full_name or []):
            val = getattr(name, "value", None)
            if isinstance(val, str) and val.lower().startswith(("http://", "https://")):
                urls.append(val)
    return urls


def _resolve_issuer(db: Session, cert: Certificate) -> x509.Certificate | None:
    """OCSP için issuer sertifikası gerekir: önce parent_id, sonra AKI→SKI eşleşmesi."""
    row = db.get(Certificate, cert.parent_id) if cert.parent_id else None
    if row is None and cert.authority_key_identifier:
        row = find_ca_by_ski(db, cert.authority_key_identifier)
    if row is not None and row.pem_certificate:
        try:
            return x509.load_pem_x509_certificate(row.pem_certificate.encode())
        except Exception:
            return None
    return None


def _revocation_time(single) -> str | None:
    dt = getattr(single, "revocation_time_utc", None) or getattr(single, "revocation_time", None)
    return dt.isoformat() if dt is not None else None


def check_ocsp(leaf: x509.Certificate, issuer: x509.Certificate, url: str,
               client: httpx.Client) -> tuple[str, dict]:
    """Tek OCSP responder'a sorar. Döner: (good|revoked|unknown, detay)."""
    try:
        req = (ocsp.OCSPRequestBuilder()
               .add_certificate(leaf, issuer, hashes.SHA1())  # CertID hash — RFC 6960 standardı
               .build())
        der = req.public_bytes(serialization.Encoding.DER)
        resp = client.post(url, content=der, headers={"Content-Type": "application/ocsp-request"})
        resp.raise_for_status()
        oc = ocsp.load_der_ocsp_response(resp.content)
        if oc.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            return "unknown", {"ocsp_response_status": oc.response_status.name}
        status = oc.certificate_status
        if status == ocsp.OCSPCertStatus.GOOD:
            return "good", {}
        if status == ocsp.OCSPCertStatus.REVOKED:
            reason = oc.revocation_reason.name if oc.revocation_reason else None
            return "revoked", {"revocation_time": _revocation_time(oc), "reason": reason}
        return "unknown", {"ocsp_cert_status": "UNKNOWN"}
    except Exception as exc:
        return "unknown", {"error": f"{type(exc).__name__}: {exc}"[:200]}


def check_crl(leaf: x509.Certificate, url: str, client: httpx.Client) -> tuple[str, dict]:
    """Tek CRL dağıtım noktasını indirip seri numarasını arar. Döner: (good|revoked|unknown, detay)."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
        try:
            crl = x509.load_der_x509_crl(data)
        except ValueError:
            crl = x509.load_pem_x509_crl(data)
        entry = crl.get_revoked_certificate_by_serial_number(leaf.serial_number)
        if entry is not None:
            return "revoked", {"revocation_date": _revocation_time(entry)}
        return "good", {}
    except Exception as exc:
        return "unknown", {"error": f"{type(exc).__name__}: {exc}"[:200]}


def check_certificate(db: Session, cert: Certificate, client: httpx.Client,
                      config: dict) -> tuple[str, dict]:
    """Bir sertifikanın iptal durumunu (method'a göre OCSP ve/veya CRL) denetler; kesin sonuç
    (good/revoked) alınınca durur. Hiçbir yerden kesin yanıt gelmezse 'unknown'."""
    if not cert.pem_certificate:
        return "unknown", {"error": "PEM yok"}
    try:
        leaf = x509.load_pem_x509_certificate(cert.pem_certificate.encode())
    except Exception:
        return "unknown", {"error": "PEM parse edilemedi"}

    method = config.get("method") or "ocsp_then_crl"
    tried: list[dict] = []

    if method in ("ocsp", "ocsp_then_crl"):
        issuer = _resolve_issuer(db, cert)
        if issuer is not None:
            for url in extract_ocsp_urls(leaf):
                status, detail = check_ocsp(leaf, issuer, url, client)
                tried.append({"method": "ocsp", "url": url, "status": status})
                if status in ("good", "revoked"):
                    return status, {"method": "ocsp", "responder": url, **detail}
        else:
            tried.append({"method": "ocsp", "status": "skipped", "reason": "issuer bulunamadı"})

    if method in ("crl", "ocsp_then_crl"):
        for url in extract_crl_urls(leaf):
            status, detail = check_crl(leaf, url, client)
            tried.append({"method": "crl", "url": url, "status": status})
            if status in ("good", "revoked"):
                return status, {"method": "crl", "crl": url, **detail}

    return "unknown", {"tried": tried,
                       "note": "kesin sonuç yok (erişim yok, uç tanımsız ya da issuer eksik)"}


def run_check(db: Session, cert: Certificate, client: httpx.Client, config: dict) -> tuple[str, dict]:
    """check_certificate + sonucu Certificate'e yazar (commit çağırana ait)."""
    status, detail = check_certificate(db, cert, client, config)
    cert.revocation_status = status
    cert.revocation_checked_at = utcnow()
    cert.revocation_detail = json.dumps(detail, ensure_ascii=False)[:3900]
    return status, detail


def check_all_certificates() -> None:
    """Zamanlanmış gece işi. Yalnız revocation ETKİNSE çalışır. Aktif leaf'leri sıralı denetler
    (check_certificate DB okur → thread havuzu yok; egress-gated + gecelik → sıralı yeterli)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        config = get_config(db)
        if not config.get("enabled"):
            logger.info("Revocation kapalı — zamanlanmış denetim atlandı")
            return
        q = db.query(Certificate).filter(Certificate.cert_type == "leaf")
        if config.get("check_active_only", True):
            q = q.filter(Certificate.is_active == True)  # noqa: E712
        certs = q.all()
        revoked = 0
        with _client(config) as client:
            for cert in certs:
                try:
                    status, _ = run_check(db, cert, client, config)
                    if status == "revoked":
                        revoked += 1
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Revocation denetim hatası (cert #%s)", cert.id)
        logger.info("Revocation denetimi bitti: %s leaf, %s revoked", len(certs), revoked)
    except Exception:
        db.rollback()
        logger.exception("Zamanlanmış revocation denetimi hatası")
    finally:
        db.close()
