"""Yönetici Panosu, Ekibim, Sistem Sağlığı ve sertifika Mailler/Etkilenenler uçları (v3.9.9).

Görünürlük: admin ve Genel İzleyici (allviewer) TÜM ekipleri görür; editör ve Ekip İzleyici
yalnız üyesi olduğu SY ekiplerinin özetini görür (security.domain_scope_team_ids). Sertifika
uçları sertifika envanteri gibi herkese açıktır. Sistem Sağlığı yalnız admin.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    CertificateImpactOut, MailHistoryOut, SystemHealthOut, TeamDetailOut, TeamOverviewOut,
)
from app.core.security import domain_scope_team_ids, require_role
from app.db.models import Certificate, User
from app.db.session import get_db
from app.services import mail_history, team_summary

router = APIRouter(prefix="/api", tags=["summary"])

CERT_MAIL_LIMIT = 200


@router.get("/summary/teams", response_model=TeamOverviewOut)
def teams_overview(db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    """Ekip bazlı özet: yöneticiye tüm ekipler, ekip kullanıcısına kendi ekipleri."""
    return team_summary.overview(db, domain_scope_team_ids(db, user))


@router.get("/summary/teams/{team_id}", response_model=TeamDetailOut)
def team_overview(team_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_role("viewer"))):
    scope = domain_scope_team_ids(db, user)
    if scope is not None and team_id not in scope:
        raise HTTPException(status_code=403, detail="Bu ekibin özetini yalnız ekip üyeleri ve yöneticiler görür")
    out = team_summary.team_detail(db, team_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Ekip bulunamadı")
    return out


@router.get("/certificates/{cert_id}/mails", response_model=list[MailHistoryOut])
def certificate_mails(cert_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_role("viewer"))):
    """Bu sertifika için gönderilen (ve gönderilemeyen) mailler, en yeni önce. Sunucu hata
    ayrıntısı yalnız admine gösterilir."""
    if db.get(Certificate, cert_id) is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    items, _ = mail_history.list_history(
        db, mail_history._Filters(channel="email", certificate_id=cert_id), CERT_MAIL_LIMIT)
    if user.role != "admin":
        for r in items:
            r["error"] = None
    return [MailHistoryOut(**r) for r in items]


@router.get("/certificates/{cert_id}/impact", response_model=CertificateImpactOut)
def certificate_impact(cert_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_role("viewer"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    return team_summary.certificate_impact(db, cert)


@router.get("/system/health", response_model=SystemHealthOut)
def system_health(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return team_summary.system_health(db)
