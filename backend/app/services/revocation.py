"""Sertifika iptal (revocation) durumu — OCSP ve/veya CRL ile denetler. live_check felsefesinin uzantısı.

EGRESS: OCSP responder / CRL dağıtım noktalarına DIŞ ERİŞİM gerekir. Kapalı banka/OpenShift ağında
erişilemeyebilir (ayrıca iç/özel CA'lar çoğu zaman public OCSP sunmaz → çok sayıda kesin olmayan sonuç
NORMALDİR). Bu yüzden egress-gated: revocation kategorisi varsayılan KAPALI + opsiyonel proxy; erişilemezse
'unreachable' (çökme yok).

Durumlar (literatürdeki ayrımla): good / revoked = kesin yanıt; unknown = OCSP responder sertifikayı
TANIMIYOR (RFC 6960 'unknown'); unreachable = OCSP/CRL ucuna ulaşılamadı ya da geçerli yanıt gelmedi;
not_checkable = sorulacak yer yok (sertifikada OCSP/CRL adresi yok ya da OCSP için issuer envanterde yok). Sertifikayı ASLA otomatik pasifleştirmez — yalnız durum gösterir (JUMBO onay-hattı felsefesi).

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
from app.services import job_lock
from app.services.audit import audited_job
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
    """Tek OCSP responder'a sorar. Döner: (good|revoked|unknown|unreachable, detay)."""
    try:
        req = (ocsp.OCSPRequestBuilder()
               .add_certificate(leaf, issuer, hashes.SHA1())  # CertID hash — RFC 6960 standardı
               .build())
        der = req.public_bytes(serialization.Encoding.DER)
        resp = client.post(url, content=der, headers={"Content-Type": "application/ocsp-request"})
        resp.raise_for_status()
        oc = ocsp.load_der_ocsp_response(resp.content)
        if oc.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            return "unreachable", {"ocsp_response_status": oc.response_status.name}
        status = oc.certificate_status
        if status == ocsp.OCSPCertStatus.GOOD:
            return "good", {}
        if status == ocsp.OCSPCertStatus.REVOKED:
            reason = oc.revocation_reason.name if oc.revocation_reason else None
            return "revoked", {"revocation_time": _revocation_time(oc), "reason": reason}
        return "unknown", {"ocsp_cert_status": "UNKNOWN"}
    except Exception as exc:
        return "unreachable", {"error": f"{type(exc).__name__}: {exc}"[:200]}


def check_crl(leaf: x509.Certificate, url: str, client: httpx.Client) -> tuple[str, dict]:
    """Tek CRL dağıtım noktasını indirip seri numarasını arar. Döner: (good|revoked|unreachable, detay)."""
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
        return "unreachable", {"error": f"{type(exc).__name__}: {exc}"[:200]}


def check_certificate(db: Session, cert: Certificate, client: httpx.Client,
                      config: dict) -> tuple[str, dict]:
    """Bir sertifikanın iptal durumunu (method'a göre OCSP ve/veya CRL) denetler; kesin sonuç
    (good/revoked) alınınca durur. Kesin yanıt yoksa: responder tanımıyorsa 'unknown', uca ulaşılamadıysa
    'unreachable', hiç sorulacak yer yoksa 'not_checkable'."""
    if not cert.pem_certificate:
        return "not_checkable", {"error": "PEM yok"}
    try:
        leaf = x509.load_pem_x509_certificate(cert.pem_certificate.encode())
    except Exception:
        return "not_checkable", {"error": "PEM parse edilemedi"}

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

    outcomes = {t["status"] for t in tried}
    if "unknown" in outcomes:
        return "unknown", {"tried": tried, "note": "OCSP responder sertifikayı tanımıyor"}
    if "unreachable" in outcomes:
        return "unreachable", {"tried": tried, "note": "OCSP/CRL ucuna ulaşılamadı"}
    return "not_checkable", {"tried": tried,
                             "note": "sorulacak yer yok (OCSP/CRL adresi tanımsız ya da issuer eksik)"}


def run_check(db: Session, cert: Certificate, client: httpx.Client, config: dict) -> tuple[str, dict]:
    """check_certificate + sonucu Certificate'e yazar (commit çağırana ait)."""
    status, detail = check_certificate(db, cert, client, config)
    if status not in ("good", "revoked") and cert.revocation_status == "revoked":
        # İptal geri alınamaz: kesin olmayan bir sonuç (ör. uca o an ulaşılamaması) önceki 'revoked' kaydını silmez.
        # Aksi halde durum 'Belirsiz'e düşer, uç dönünce aynı sertifika için ikinci iptal maili gider.
        try:
            previous = json.loads(cert.revocation_detail or "{}")
        except ValueError:
            previous = {}
        previous["last_attempt"] = {"at": utcnow().isoformat(), "result": status, "detail": detail}
        cert.revocation_checked_at = utcnow()
        cert.revocation_detail = json.dumps(previous, ensure_ascii=False)[:3900]
        return "revoked", previous
    cert.revocation_status = status
    cert.revocation_checked_at = utcnow()
    cert.revocation_detail = json.dumps(detail, ensure_ascii=False)[:3900]
    return status, detail


def notify_newly_revoked(db: Session, certs: list[Certificate]) -> dict | None:
    """Durumu 'revoked'a YENİ geçen sertifikalar için paydaşlara mail (bkz.
    notifier.send_revoked_notifications). Mail hatası denetimi bozmaz — loglanır."""
    if not certs:
        return None
    from app.services import notifier
    try:
        return notifier.send_revoked_notifications(db, certs)
    except Exception:
        db.rollback()
        logger.exception("İptal maili gönderilemedi")
        return None


# Ortak DB kilidi adı (bkz. job_lock): gece işi, ekrandaki toplu denetim ve dış tetik aynı
# anda iki yerde (iki pod / iki cluster) çalışmaz — iptal maili de iki kez gitmez.
JOB_NAME = "revocation"


@audited_job("İptal (OCSP/CRL) denetimi")
def check_all_certificates() -> dict:
    """Zamanlanmış gece işi. Yalnız iptal denetimi ETKİN ve 'her gece otomatik' AÇIKSA çalışır
    (auto_enabled kapalıyken yalnız ekrandan / dış tetikle). Başka pod yürütüyorsa atlanır."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        config = get_config(db)
    finally:
        db.close()
    if not config.get("enabled"):
        logger.info("Revocation kapalı — zamanlanmış denetim atlandı")
        return {"status": "skipped"}
    if not config.get("auto_enabled", True):
        logger.info("İptal denetimi gece otomatik çalışması kapalı — atlandı (dış tetik bekleniyor)")
        return {"status": "skipped"}
    return job_lock.run_job(JOB_NAME, run_all_checks, min_gap_seconds=job_lock.DAILY_GAP_SECONDS)


def run_all_checks() -> dict:
    """Toplu iptal denetiminin çekirdeği (gece işi + ekrandan/dış tetik). Aktif leaf'leri sıralı
    denetler (check_certificate DB okur → thread havuzu yok; egress-gated → sıralı yeterli).
    İptal denetimi Ayarlar'da kapalıysa hiçbir şey yapmaz (iptal maili yalnız açıkken gider)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        config = get_config(db)
        if not config.get("enabled"):
            logger.info("Revocation kapalı — toplu denetim atlandı")
            return {"status": "skipped"}
        q = db.query(Certificate).filter(Certificate.cert_type == "leaf")
        if config.get("check_active_only", True):
            q = q.filter(Certificate.is_active == True)  # noqa: E712
        certs = q.all()
        revoked = 0
        newly_revoked: list[Certificate] = []
        with _client(config) as client:
            for cert in certs:
                try:
                    previous = cert.revocation_status
                    status, _ = run_check(db, cert, client, config)
                    if status == "revoked":
                        revoked += 1
                        if previous != "revoked":
                            newly_revoked.append(cert)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Revocation denetim hatası (cert #%s)", cert.id)
        logger.info("Revocation denetimi bitti: %s leaf, %s revoked", len(certs), revoked)
        mail = notify_newly_revoked(db, newly_revoked)
        result = {"status": "ok", "checked": len(certs), "revoked": revoked}
        if mail is not None:
            result["mails_sent"] = mail.get("sent", 0)
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("Zamanlanmış revocation denetimi hatası")
        return {"status": "error", "error": str(exc)[:300]}
    finally:
        db.close()
