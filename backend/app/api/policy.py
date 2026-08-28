"""Sertifika uyum (politika) API. Uyum raporu varsayılan admin+allviewer'a açık; Ayarlar >
Erişim'den (access.policy_all_roles) tüm rollere açılabilir (bkz. security.page_visible).
Politika yapılandırması (allowlist, asgari anahtar boyu vb.) /api/settings/policy'de admin'de.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import PolicyCertResult, PolicyReportOut, PolicyViolationOut
from app.core.security import require_page_access
from app.core.timeutil import utcnow
from app.db.models import Certificate, User
from app.db.session import get_db
from app.services import policy

router = APIRouter(prefix="/api/policy", tags=["policy"])


def _days_left(valid_to) -> int | None:
    return None if valid_to is None else (valid_to - utcnow()).days


@router.get("/report", response_model=PolicyReportOut)
def policy_report(db: Session = Depends(get_db), _: User = Depends(require_page_access("policy"))):
    """Aktif envanterin uyum raporu: toplam/uyumlu/uyumsuz + kural bazında sayı + ihlal listesi."""
    config = policy.get_config(db)
    result = policy.evaluate_inventory(db)
    violations = [
        PolicyViolationOut(
            certificate_id=cert.id, name=cert.name, issuer=cert.issuer, cert_type=cert.cert_type,
            public_key_type=cert.public_key_type, key_size=cert.key_size,
            signature_hash=cert.signature_hash, valid_to=cert.valid_to,
            days_left=_days_left(cert.valid_to), severity=policy.max_severity(v),
            rules=[r["rule"] for r in v], details=[r["detail"] for r in v])
        for cert, v in result["violations"]
    ]
    return PolicyReportOut(
        enabled=bool(config.get("enabled")),
        total_evaluated=result["total_evaluated"], compliant=result["compliant"],
        non_compliant=len(violations), rule_counts=result["rule_counts"], violations=violations)


@router.get("/certificates/{cert_id}", response_model=PolicyCertResult)
def certificate_policy(cert_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_page_access("policy"))):
    """Tek bir sertifikanın uyum durumu ve ihlalleri."""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    v = policy.evaluate_certificate(cert, policy.get_config(db))
    return PolicyCertResult(certificate_id=cert_id, compliant=not v, violations=v)
