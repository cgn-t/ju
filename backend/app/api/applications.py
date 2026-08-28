from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    AppDependencyCreate, AppDependencyOut, ApplicationCreate, ApplicationOut, ApplicationUpdate,
    AppTrustedCertCreate, AppTrustedCertOut,
)
from app.core.security import (
    can_manage_team_resource, domain_scope_team_ids, require_role, user_team_ids,
)
from app.db.models import (AppDependency, Application, ApplicationTag, ApplicationTrustedCert,
                            Certificate, CertificateDomainMap, Domain, Tag, TransferProposal, User)
from app.db.session import get_db
from app.services.audit import log_action

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _query(db: Session):
    return db.query(Application).options(
        joinedload(Application.sy_team), joinedload(Application.ug_team),
        joinedload(Application.domain),
        joinedload(Application.tag_links).joinedload(ApplicationTag.tag),
        joinedload(Application.dependencies).joinedload(AppDependency.target_domain),
        joinedload(Application.dependencies).joinedload(AppDependency.client_cert),
        joinedload(Application.trusted_certs).joinedload(ApplicationTrustedCert.cert))


def _sync_app_tags(db: Session, app_id: int, tag_ids: list[int]) -> None:
    """Uygulamanın etiketlerini verilen id kümesine eşitler (UserTeam ekle/sil deseni).
    Geçersiz/olmayan tag_id'ler yok sayılır — yalnız mevcut Tag'lere bağlanır."""
    desired = set(tag_ids or [])
    if desired:
        valid = {row[0] for row in db.query(Tag.id).filter(Tag.id.in_(desired)).all()}
        desired &= valid
    current = {link.tag_id for link in db.query(ApplicationTag)
               .filter(ApplicationTag.application_id == app_id).all()}
    for tid in desired - current:
        db.add(ApplicationTag(application_id=app_id, tag_id=tid))
    remove = current - desired
    if remove:
        db.query(ApplicationTag).filter(
            ApplicationTag.application_id == app_id,
            ApplicationTag.tag_id.in_(remove)).delete(synchronize_session=False)


@router.get("", response_model=list[ApplicationOut])
def list_applications(search: str | None = None,
                      tag_ids: list[int] | None = Query(None),
                      limit: int | None = Query(None, ge=1, le=5000), offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    # RBAC: liste kullanıcının ÜYELİĞİNE göre kapsamlı — SY editör/viewer yalnız KENDİ ekiplerinin
    # uygulamalarını görür (ayrı takım filtresi yok); admin/allviewer global. none 403.
    # limit/offset OPSİYONEL: verilmezse tüm liste döner (mevcut davranış korunur).
    q = _query(db)
    if search:
        like = f"%{search}%"
        # Genel arama ETİKET adıyla da eşleşir: bu terimi taşıyan bir etikete sahip uygulamalar
        # da sonuca girer (ayrı bir etiket kutusuna gerek kalmaz — kullanıcı isteği).
        tagged = (db.query(ApplicationTag.application_id)
                  .join(Tag, Tag.id == ApplicationTag.tag_id).filter(Tag.name.ilike(like)))
        q = q.filter(Application.app_name.ilike(like) | Application.server_name.ilike(like)
                     | Application.dns.ilike(like) | Application.id.in_(tagged))
    if tag_ids:
        # AND / kesişim: uygulama SEÇİLİ HER etikete sahip olmalı (her tag_id için ayrı EXISTS).
        for tid in tag_ids:
            q = q.filter(Application.id.in_(
                db.query(ApplicationTag.application_id).filter(ApplicationTag.tag_id == tid)))
    scope = domain_scope_team_ids(db, user)
    if scope is not None:
        q = q.filter(Application.sy_team_id.in_(scope or {-1}))
    return q.order_by(Application.app_name).offset(offset).limit(limit).all()


@router.get("/{app_id}", response_model=ApplicationOut)
def get_application(app_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_role("viewer"))):
    app_row = _query(db).filter(Application.id == app_id).first()
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    # RBAC: kapsam dışıysa varlığı gizle (404) — başka ekibin uygulama detayı sızmasın.
    scope = domain_scope_team_ids(db, user)
    if scope is not None and app_row.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    return app_row


@router.post("", response_model=ApplicationOut)
def create_application(request: Request, body: ApplicationCreate, db: Session = Depends(get_db),
                       user: User = Depends(require_role("editor"))):
    # ONAY MODELİ (create_domain ile aynı kural): editör uygulamayı yalnız ÜYE OLDUĞU
    # SY ekibine atayabilir — aksi halde başka ekip adına kayıt üretebilirdi.
    if (user.role != "admin" and body.sy_team_id is not None
            and body.sy_team_id not in user_team_ids(db, user)):
        raise HTTPException(status_code=403,
                            detail="Uygulamayı yalnız üye olduğunuz bir SY ekibine atayabilirsiniz")
    # Prod applications.ip_address/server_name NOT NULL → boşsa "" ile doldur.
    data = body.model_dump()
    tag_ids = data.pop("tag_ids", [])  # kolon değil ilişki → Application(**data)'dan çıkar
    data["ip_address"] = data.get("ip_address") or ""
    data["server_name"] = data.get("server_name") or ""
    app_row = Application(**data)
    db.add(app_row)
    db.flush()
    _sync_app_tags(db, app_row.id, tag_ids)
    log_action(db, user.username, "create", "applications", app_row.id,
               {"app_name": app_row.app_name}, request)
    db.commit()
    return _query(db).filter(Application.id == app_row.id).first()


@router.put("/{app_id}", response_model=ApplicationOut)
def update_application(request: Request, app_id: int, body: ApplicationUpdate,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    # KAPSAM: SY editör yalnız GÖRDÜĞÜ (kendi ekiplerinin) uygulamasını değiştirebilir.
    # get_application ile aynı 404 — kapsam dışı id'nin varlığı dahi sızmaz (IDOR koruması).
    scope = domain_scope_team_ids(db, user)
    if scope is not None and app_row.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    # ONAY MODELİ (update_domain ile aynı kural): SAHİPLİK (sy_team_id/ug_team_id) yalnız
    # admin tarafından değiştirilir — editör uygulamayı başka ekibe devredemez.
    if user.role != "admin":
        for owner_field in ("sy_team_id", "ug_team_id"):
            if owner_field in changes and changes[owner_field] != getattr(app_row, owner_field):
                raise HTTPException(status_code=403,
                                    detail="Uygulama sahipliğini (SY/UG ekip) yalnız admin değiştirebilir")
    # tag_ids kolon değil ilişki → setattr'dan önce ayır. None = etikete dokunma; [] = tümünü kaldır.
    tag_ids = changes.pop("tag_ids", None)
    # mTLS bağımlılık devir önerileri sahibi (sy_team_id) = uygulamanın SY ekibi; öneri
    # oluşturulurken snapshot alınır. Uygulamanın SY ekibi sonradan değişince açık öneriler
    # eski ekipte kalırdı → yeni sahip onaylayamazdı. Değişimi uygulamadan ÖNCE tespit et.
    sy_changed = ("sy_team_id" in changes and changes["sy_team_id"] != app_row.sy_team_id)
    for key, value in changes.items():
        setattr(app_row, key, value)
    if tag_ids is not None:
        _sync_app_tags(db, app_id, tag_ids)
    if sy_changed:
        # Bu uygulamanın bağımlılıklarına ait HÂLÂ AÇIK (pending/approved) önerileri yeni sahibe taşı.
        dep_ids = [d.id for d in db.query(AppDependency.id)
                   .filter(AppDependency.app_id == app_id).all()]
        if dep_ids:
            db.query(TransferProposal).filter(
                TransferProposal.app_dependency_id.in_(dep_ids),
                TransferProposal.status.in_(("pending", "approved")),
            ).update({TransferProposal.sy_team_id: app_row.sy_team_id}, synchronize_session=False)
        # trusted_add önerileri app_dependency_id=NULL / app_id ile bağlıdır (dep filtresine takılmaz)
        # → onları da yeni sahibe taşı. Aksi halde öneri eski ekipte kalır: yeni sahip onaylayamaz
        # (403), eski ekip ise ARTIK sahibi OLMADIĞI uygulamanın trust store'una cert ekleyebilirdi.
        db.query(TransferProposal).filter(
            TransferProposal.app_id == app_id,
            TransferProposal.status.in_(("pending", "approved")),
        ).update({TransferProposal.sy_team_id: app_row.sy_team_id}, synchronize_session=False)
    log_action(db, user.username, "update", "applications", app_row.id, changes, request)
    db.commit()
    return _query(db).filter(Application.id == app_id).first()


@router.delete("/{app_id}")
def delete_application(request: Request, app_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_role("editor"))):
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    # KAPSAM: update_application ile aynı kural — kapsam dışı kayda silme de 404 (yıkıcı IDOR koruması).
    scope = domain_scope_team_ids(db, user)
    if scope is not None and app_row.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    # FK NO ACTION (MSSQL): uygulama silinince bağımlılıkları DB-cascade ile düşer; ama bu
    # bağımlılıklara referans veren devir önerileri önce elle silinmeli (yoksa MSSQL bloklar).
    dep_ids = [d.id for d in db.query(AppDependency.id)
               .filter(AppDependency.app_id == app_id).all()]
    if dep_ids:
        db.query(TransferProposal).filter(
            TransferProposal.app_dependency_id.in_(dep_ids)).delete(synchronize_session=False)
    # trusted_add önerileri app_id ile bu uygulamaya bağlı (NO ACTION FK) → önce sil.
    # (app_trusted_certs satırları app_id CASCADE ile DB tarafından düşer.)
    db.query(TransferProposal).filter(
        TransferProposal.app_id == app_id).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "applications", app_row.id,
               {"app_name": app_row.app_name}, request)
    db.delete(app_row)
    db.commit()
    return {"ok": True}


# ---- Dış (client) bağımlılıklar ----
def _dep_query(db: Session):
    return db.query(AppDependency).options(
        joinedload(AppDependency.target_domain), joinedload(AppDependency.client_cert))


@router.get("/{app_id}/dependencies", response_model=list[AppDependencyOut])
def list_dependencies(app_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_role("viewer"))):
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    scope = domain_scope_team_ids(db, user)
    if scope is not None and app_row.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    return _dep_query(db).filter(AppDependency.app_id == app_id).all()


def _domain_server_cert_id(db: Session, domain_id: int) -> int | None:
    """Hedef domain'in AKTİF 'server' sertifikasının id'si (en geç biteni). Bir uygulama bu
    domaine client olarak bağlandığında izlenen sertifika = domainin server sertifikasıdır;
    o yenilendiğinde renewal.propose bu bağımlılık için uygulama sahibi SY ekibine devir önerisi üretir."""
    row = (db.query(CertificateDomainMap)
           .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
           .filter(CertificateDomainMap.domain_id == domain_id,
                   CertificateDomainMap.mapping_type == "server",
                   Certificate.is_active == True)
           .order_by(Certificate.valid_to.desc())
           .first())
    return row.certificate_id if row else None


@router.post("/{app_id}/dependencies", response_model=AppDependencyOut)
def create_dependency(request: Request, app_id: int, body: AppDependencyCreate,
                      db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    target = db.get(Domain, body.target_domain_id)
    # KAPSAM: editör hedef olarak yalnız GÖRDÜĞÜ domainleri verebilir (UI zaten kapsamlı
    # listeden seçtirir). Aksi halde yanıttaki target_domain_name, id deneyerek başka
    # takımın domain adını okumaya (numaralandırma orakılı) dönerdi. Kapsam dışı da 404.
    scope = domain_scope_team_ids(db, user)
    if target is None or (scope is not None and target.sy_team_id not in scope):
        raise HTTPException(status_code=404, detail="Hedef domain bulunamadı")
    if app_row.domain_id == body.target_domain_id:
        raise HTTPException(status_code=400, detail="Uygulama kendi domainine bağımlılık ekleyemez")
    # ONAY MODELİ: SY sahibi uygulamanın mTLS bağımlılığını yalnız o ekibin üyesi/admin yönetir
    if not can_manage_team_resource(db, user, app_row.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu uygulamanın mTLS bağımlılığını yalnız sahibi SY ekibi veya admin yönetir")
    exists = (db.query(AppDependency)
              .filter(AppDependency.app_id == app_id,
                      AppDependency.target_domain_id == body.target_domain_id).first())
    if exists is not None:
        raise HTTPException(status_code=409, detail="Bu bağımlılık zaten kayıtlı")
    # Client sertifikası ELLE SEÇİLMEZ (body.client_cert_id yok sayılır): hedef domainin AKTİF
    # server sertifikası otomatik izlenir. O sertifika yenilenince uygulama sahibi SY ekibine
    # 'client değişikliği' devir önerisi gider (mevcut renewal.propose mekanizması).
    client_cert_id = _domain_server_cert_id(db, body.target_domain_id)
    dep = AppDependency(app_id=app_id, target_domain_id=body.target_domain_id,
                        client_cert_id=client_cert_id, note=body.note)
    db.add(dep)
    db.flush()
    log_action(db, user.username, "create", "app_dependencies", dep.id,
               {"app_id": app_id, "target_domain_id": body.target_domain_id}, request)
    db.commit()
    return _dep_query(db).filter(AppDependency.id == dep.id).first()


@router.delete("/dependencies/{dep_id}")
def delete_dependency(request: Request, dep_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_role("editor"))):
    dep = db.get(AppDependency, dep_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="Bağımlılık bulunamadı")
    app_row = db.get(Application, dep.app_id)
    if not can_manage_team_resource(db, user, app_row.sy_team_id if app_row else None):
        raise HTTPException(status_code=403,
                            detail="Bu uygulamanın mTLS bağımlılığını yalnız sahibi SY ekibi veya admin yönetir")
    # FK NO ACTION (MSSQL): bu bağımlılığa referans veren devir önerilerini önce sil
    db.query(TransferProposal).filter(
        TransferProposal.app_dependency_id == dep.id).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "app_dependencies", dep.id,
               {"app_id": dep.app_id, "target_domain_id": dep.target_domain_id}, request)
    db.delete(dep)
    db.commit()
    return {"ok": True}


# ---- Trust store (uygulamanın GÜVENDİĞİ / trusted sertifikaları) ----
def _trusted_query(db: Session):
    return db.query(ApplicationTrustedCert).options(joinedload(ApplicationTrustedCert.cert))


@router.get("/{app_id}/trusted", response_model=list[AppTrustedCertOut])
def list_trusted(app_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_role("viewer"))):
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    scope = domain_scope_team_ids(db, user)
    if scope is not None and app_row.sy_team_id not in scope:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    return _trusted_query(db).filter(ApplicationTrustedCert.app_id == app_id).all()


@router.post("/{app_id}/trusted", response_model=AppTrustedCertOut)
def add_trusted(request: Request, app_id: int, body: AppTrustedCertCreate,
                db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    """Uygulamanın trust store'una sertifika ekler. Trust store ÇOKLU olabilir → aynı sertifika
    tekilse eklenir (yoksa 409); farklı sertifikalar birikir (devir yok). SY sahibi/admin yönetir."""
    app_row = db.get(Application, app_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Uygulama bulunamadı")
    # ONAY MODELİ (mTLS bağımlılığı ile aynı): yalnız sahibi SY ekibi üyesi veya admin yönetir.
    if not can_manage_team_resource(db, user, app_row.sy_team_id):
        raise HTTPException(status_code=403,
                            detail="Bu uygulamanın trust store'unu yalnız sahibi SY ekibi veya admin yönetir")
    cert = db.get(Certificate, body.certificate_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    exists = (db.query(ApplicationTrustedCert)
              .filter(ApplicationTrustedCert.app_id == app_id,
                      ApplicationTrustedCert.cert_id == body.certificate_id).first())
    if exists is not None:
        raise HTTPException(status_code=409, detail="Bu sertifika zaten trust store'da")
    row = ApplicationTrustedCert(app_id=app_id, cert_id=body.certificate_id, note=body.note)
    db.add(row)
    db.flush()
    log_action(db, user.username, "create", "app_trusted_certs", row.id,
               {"app_id": app_id, "cert_id": body.certificate_id}, request)
    db.commit()
    return _trusted_query(db).filter(ApplicationTrustedCert.id == row.id).first()


@router.delete("/trusted/{trusted_id}")
def delete_trusted(request: Request, trusted_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role("editor"))):
    row = db.get(ApplicationTrustedCert, trusted_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Trusted kaydı bulunamadı")
    app_row = db.get(Application, row.app_id)
    if not can_manage_team_resource(db, user, app_row.sy_team_id if app_row else None):
        raise HTTPException(status_code=403,
                            detail="Bu uygulamanın trust store'unu yalnız sahibi SY ekibi veya admin yönetir")
    log_action(db, user.username, "delete", "app_trusted_certs", row.id,
               {"app_id": row.app_id, "cert_id": row.cert_id}, request)
    db.delete(row)
    db.commit()
    return {"ok": True}
