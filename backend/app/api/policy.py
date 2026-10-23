"""Sertifika uyum (politika) API. Uyum raporu varsayılan admin+allviewer'a açık; Ayarlar >
Erişim'den (access.policy_all_roles) tüm rollere açılabilir (bkz. security.page_visible).
Politika yapılandırması (allowlist, asgari anahtar boyu vb.) /api/settings/policy'de admin'de.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.paging import MAX_PAGE_SIZE, any_contains, page_slice, sort_key_text, sort_rows
from app.api.schemas import (
    PolicyCertResult, PolicyCountsOut, PolicyReportOut, PolicyViolationOut, PolicyViolationPage,
)
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
    violations = [_violation_out(cert, v) for cert, v in result["violations"]]
    return PolicyReportOut(
        enabled=bool(config.get("enabled")),
        total_evaluated=result["total_evaluated"], compliant=result["compliant"],
        non_compliant=len(violations), rule_counts=result["rule_counts"], violations=violations)


def _violation_out(cert, v) -> PolicyViolationOut:
    return PolicyViolationOut(
        certificate_id=cert.id, name=cert.name, issuer=cert.issuer, cert_type=cert.cert_type,
        public_key_type=cert.public_key_type, key_size=cert.key_size,
        signature_hash=cert.signature_hash, valid_to=cert.valid_to,
        days_left=_days_left(cert.valid_to), severity=policy.max_severity(v),
        rules=[r["rule"] for r in v], details=[r["detail"] for r in v])


@router.get("/counts", response_model=PolicyCountsOut)
def policy_counts(db: Session = Depends(get_db), _: User = Depends(require_page_access("policy"))):
    """Yalnız sayılar — menü rozeti her dakika bunu sorar (ihlal listesi taşınmaz)."""
    config = policy.get_config(db)
    result = policy.evaluate_inventory(db)
    return PolicyCountsOut(
        enabled=bool(config.get("enabled")), total_evaluated=result["total_evaluated"],
        compliant=result["compliant"], non_compliant=len(result["violations"]),
        rule_counts=result["rule_counts"])


_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


@router.get("/violations/page", response_model=PolicyViolationPage)
def policy_violations_page(
    rule: str | None = None,
    severity: Literal["high", "medium", "low"] | None = None,
    q: str | None = None,
    sort: Literal["severity", "name", "valid_to"] = "severity",
    dir: Literal["asc", "desc"] = "asc",
    page: int = Query(0, ge=0),
    size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    _: User = Depends(require_page_access("policy")),
):
    """Uyumsuz sertifikalar, sayfalı. Sayılar (rule_counts) tüm envanterden; severity_counts
    kural + arama filtresi uygulanmış küme üzerinden (önem filtresi hariç)."""
    config = policy.get_config(db)
    result = policy.evaluate_inventory(db)
    rows = result["violations"]
    if rule:
        rows = [(c, v) for c, v in rows if any(i["rule"] == rule for i in v)]
    if q:
        rows = [(c, v) for c, v in rows if any_contains((c.name, c.issuer), q)]
    severity_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for _c, v in rows:
        sev = policy.max_severity(v)
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    if severity:
        rows = [(c, v) for c, v in rows if policy.max_severity(v) == severity]
    desc = dir == "desc"
    if sort == "name":
        rows = sort_rows(rows, lambda r: sort_key_text(r[0].name), desc)
    elif sort == "valid_to":
        rows = sort_rows(rows, lambda r: r[0].valid_to, desc, empty=lambda r: r[0].valid_to is None)
    else:  # önem (yüksek önce), eşitlikte en yakın bitiş
        rows = sort_rows(rows, lambda r: (_SEVERITY_RANK.get(policy.max_severity(r[1]), 9),
                                          r[0].valid_to.timestamp() if r[0].valid_to else float("inf")), desc)
    total = len(rows)
    page_rows, page = page_slice(rows, page, size)
    return PolicyViolationPage(
        enabled=bool(config.get("enabled")), total_evaluated=result["total_evaluated"],
        compliant=result["compliant"], non_compliant=len(result["violations"]),
        rule_counts=result["rule_counts"], severity_counts=severity_counts,
        items=[_violation_out(c, v) for c, v in page_rows], total=total, page=page, size=size)


@router.get("/certificates/{cert_id}", response_model=PolicyCertResult)
def certificate_policy(cert_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_page_access("policy"))):
    """Tek bir sertifikanın uyum durumu ve ihlalleri."""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    v = policy.evaluate_certificate(cert, policy.get_config(db))
    return PolicyCertResult(certificate_id=cert_id, compliant=not v, violations=v)
