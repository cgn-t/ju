from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    CertMapOut, DashboardOut, ExpiringCert, MapEdge, MapNode, RelationshipsOut, RelEdge,
    TeamDomainCount,
)
from app.core.certtype import normalize_cert_type
from app.core.security import domain_scope_team_ids, require_role
from app.db.models import (
    AppDependency, Application, Certificate, CertificateDomainMap, Domain, Team, User,
)
from app.db.session import get_db
from app.services.settings_service import get_category

router = APIRouter(prefix="/api", tags=["dashboard"])


def _days_left(valid_to: datetime | None) -> int | None:
    return (valid_to - utcnow()).days if valid_to else None


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    general = get_category(db, "general")
    cert_count = int(general.get("dashboard_cert_count") or 20)
    now = utcnow()

    # RBAC: domain-bazlı metrikler kullanıcının GÖRDÜĞÜ domainlere kapsanır (SY editör kendi ekipleri;
    # admin/viewer global). Sertifika envanteri sayımları GLOBAL kalır (envanter herkese açık).
    scope = domain_scope_team_ids(db, user)

    def scoped(q):
        return q if scope is None else q.filter(Domain.sy_team_id.in_(scope or {-1}))

    total_domains = scoped(db.query(func.count(Domain.id))).scalar() or 0
    expired_domains = scoped(
        db.query(func.count(func.distinct(Domain.id)))
        .join(CertificateDomainMap, CertificateDomainMap.domain_id == Domain.id)
        .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
        .filter(Certificate.valid_to < now)
    ).scalar() or 0

    sy_counts = scoped(
        db.query(Team.name, func.count(Domain.id))
        .join(Domain, Domain.sy_team_id == Team.id)
        .filter(Team.type == "SY")
        .group_by(Team.name)
        .order_by(func.count(Domain.id).desc())
    ).all()

    expiring = (
        db.query(Certificate)
        .options(joinedload(Certificate.domain_mappings)
                 .joinedload(CertificateDomainMap.domain).joinedload(Domain.sy_team))
        .filter(Certificate.is_active == True, Certificate.valid_to.isnot(None))
        .order_by(Certificate.valid_to.asc())
        .limit(cert_count)
        .all()
    )
    expiring_out = []
    for cert in expiring:
        domains = [m.domain for m in cert.domain_mappings]
        sy_names = sorted({d.sy_team.name for d in domains if d.sy_team})
        expiring_out.append(ExpiringCert(
            certificate_id=cert.id,
            name=cert.name,
            serial_number=cert.serial_number,
            valid_to=cert.valid_to,
            days_left=_days_left(cert.valid_to),
            sy_teams=", ".join(sy_names),
            domains=", ".join(d.domain for d in domains),
        ))

    return DashboardOut(
        total_domains=total_domains,
        expired_domains=expired_domains,
        valid_domains=total_domains - expired_domains,
        total_certificates=db.query(func.count(Certificate.id)).scalar() or 0,
        sy_domain_counts=[TeamDomainCount(team=n, count=c) for n, c in sy_counts],
        expiring_certificates=expiring_out,
    )


@router.get("/cert-map", response_model=CertMapOut)
def cert_map(sy_team_id: int | None = Query(None), db: Session = Depends(get_db),
             _: User = Depends(require_role("viewer"))):
    """React Flow için node/edge listesi: sertifika hiyerarşisi + domain bağlantıları.
    Harita GLOBAL: her kullanıcı (viewer+) tüm ekiplerin mapping'ini görebilir. Opsiyonel
    `sy_team_id` ile YALNIZ o SY takımının domainlerine (+ onlara bağlı sertifika ata zinciri)
    daraltılır — frontend varsayılan olarak kullanıcının kendi takımını seçer, 'Tümü' ile kaldırır."""
    certs = db.query(Certificate).filter(Certificate.is_active == True).all()
    mappings = db.query(CertificateDomainMap).options(
        joinedload(CertificateDomainMap.domain)).all()

    if sy_team_id is not None:
        team_dom_ids = {r[0] for r in db.query(Domain.id)
                        .filter(Domain.sy_team_id == sy_team_id).all()}
        mappings = [m for m in mappings if m.domain_id in team_dom_ids]
        # Görünür sertifikalar: filtreli domainlere bağlı olanlar + ata zincirleri (zincir bütünlüğü)
        cert_by_id = {c.id: c for c in certs}
        visible: set[int] = set()
        for m in mappings:
            cid = m.certificate_id
            while cid is not None and cid not in visible:
                visible.add(cid)
                c = cert_by_id.get(cid)
                cid = c.parent_id if c else None
        certs = [c for c in certs if c.id in visible]

    cert_ids = {c.id for c in certs}
    nodes: list[MapNode] = []
    edges: list[MapEdge] = []
    for cert in certs:
        nodes.append(MapNode(id=f"cert-{cert.id}", label=cert.name,
                             node_type=normalize_cert_type(cert.cert_type),
                             valid_to=cert.valid_to, days_left=_days_left(cert.valid_to)))
        if cert.parent_id and cert.parent_id in cert_ids:  # kenar yalnız ata da görünürse
            edges.append(MapEdge(id=f"h-{cert.parent_id}-{cert.id}", source=f"cert-{cert.parent_id}",
                                 target=f"cert-{cert.id}", edge_type="hierarchy"))

    domain_ids_seen: set[int] = set()
    for m in mappings:
        if m.domain_id not in domain_ids_seen:
            domain_ids_seen.add(m.domain_id)
            nodes.append(MapNode(id=f"domain-{m.domain_id}", label=m.domain.domain,
                                 node_type="domain", valid_to=m.domain.expire_date,
                                 days_left=_days_left(m.domain.expire_date)))
        edges.append(MapEdge(id=f"m-{m.id}", source=f"cert-{m.certificate_id}",
                             target=f"domain-{m.domain_id}", edge_type=m.mapping_type))
    return CertMapOut(nodes=nodes, edges=edges)


@router.get("/relationships", response_model=RelationshipsOut)
def relationships(sy_team_id: int | None = Query(None), db: Session = Depends(get_db),
                  _: User = Depends(require_role("viewer"))):
    """Sertifikalardan OTOMATİK türetilen client↔server ilişkileri.

    Bir sertifika bir domain'de 'server', başka domain'de 'client' olarak eşlenmişse,
    o client domain ile server domain arasında bir 'trust' (güven/bağımlılık) ilişkisi
    çıkarılır. Ayrıca ilgili domainlere bağlı uygulamalar 'serves'/'depends' kenarlarıyla.

    Harita GLOBAL: her kullanıcı (viewer+) tüm ekiplerin ilişkilerini görebilir. Opsiyonel
    `sy_team_id` ile YALNIZ o SY takımının domain ve uygulamalarına daraltılır (frontend
    varsayılan olarak kullanıcının kendi takımını seçer, 'Tümü' ile kaldırır)."""
    mappings = db.query(CertificateDomainMap).options(
        joinedload(CertificateDomainMap.domain),
        joinedload(CertificateDomainMap.certificate),
    ).all()
    if sy_team_id is not None:
        team_dom_ids = {r[0] for r in db.query(Domain.id)
                        .filter(Domain.sy_team_id == sy_team_id).all()}
        mappings = [m for m in mappings if m.domain_id in team_dom_ids]

    # Sertifika bazında server/client domainlerini topla
    by_cert: dict[int, dict] = {}
    for m in mappings:
        grp = by_cert.setdefault(m.certificate_id, {"cert": m.certificate, "server": [], "client": []})
        if m.mapping_type in ("server", "client"):
            grp[m.mapping_type].append(m.domain)

    nodes: dict[str, MapNode] = {}
    edges: dict[str, RelEdge] = {}
    involved: set[int] = set()

    def add_domain(d: Domain) -> None:
        nid = f"domain-{d.id}"
        if nid not in nodes:
            nodes[nid] = MapNode(id=nid, label=d.domain, node_type="domain",
                                 valid_to=d.expire_date, days_left=_days_left(d.expire_date))
        involved.add(d.id)

    for cid, grp in by_cert.items():
        servers, clients = grp["server"], grp["client"]
        if not servers or not clients:
            continue
        cert = grp["cert"]
        for cd in clients:
            add_domain(cd)
            for sd in servers:
                add_domain(sd)
                if cd.id == sd.id:
                    continue  # domain kendine bağlanmaz
                eid = f"trust-{cid}-{cd.id}-{sd.id}"
                edges[eid] = RelEdge(id=eid, source=f"domain-{cd.id}", target=f"domain-{sd.id}",
                                     edge_type="trust", via_cert_id=cid, label=cert.name)

    # Uygulamalar: (a) trust'a katılan domainlerde sunanlar 'serves' kenarıyla bağlam olarak,
    # (b) açıkça tanımlı DIŞ bağımlılıklar 'depends' kenarıyla (uygulama → hedef domain).
    deps = (db.query(AppDependency)
            .options(joinedload(AppDependency.app).joinedload(Application.domain),
                     joinedload(AppDependency.target_domain),
                     joinedload(AppDependency.client_cert))
            .all())
    if sy_team_id is not None:
        # Filtre: yalnız o SY takımının uygulamaları (ve onların bağımlılık kenarları)
        deps = [d for d in deps if d.app is not None and d.app.sy_team_id == sy_team_id]

    show_apps: dict[int, Application] = {}
    if involved:
        app_q = db.query(Application).options(joinedload(Application.domain)).filter(
            Application.domain_id.in_(involved))
        if sy_team_id is not None:
            app_q = app_q.filter(Application.sy_team_id == sy_team_id)
        for a in app_q.all():
            show_apps[a.id] = a
    for dep in deps:
        show_apps[dep.app_id] = dep.app

    for a in show_apps.values():
        aid = f"app-{a.id}"
        nodes[aid] = MapNode(id=aid, label=a.app_name, node_type="app")
        if a.domain_id and a.domain:
            add_domain(a.domain)
            eid = f"serves-{a.id}"
            edges[eid] = RelEdge(id=eid, source=aid, target=f"domain-{a.domain_id}",
                                 edge_type="serves")

    for dep in deps:
        td = dep.target_domain
        nid = f"domain-{td.id}"
        if nid not in nodes:
            nodes[nid] = MapNode(id=nid, label=td.domain, node_type="domain",
                                 valid_to=td.expire_date, days_left=_days_left(td.expire_date))
        eid = f"depends-{dep.id}"
        edges[eid] = RelEdge(id=eid, source=f"app-{dep.app_id}", target=nid,
                             edge_type="depends", via_cert_id=dep.client_cert_id,
                             label=dep.client_cert.name if dep.client_cert else None)

    return RelationshipsOut(nodes=list(nodes.values()), edges=list(edges.values()))
