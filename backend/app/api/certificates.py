from datetime import datetime
from app.core.textmatch import ci_like
from app.core.timeutil import utcnow
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, defer, joinedload

from app.api.schemas import (
    CertificateChainOut,
    CertificateCreate,
    CertificateGroupStat,
    CertificateOption,
    CertificatePage,
    CertificateTreeRow,
    ChainCheckFinding,
    CertificateOut,
    CertificateUpdate,
    CertExtrasOut,
    CertRefOut,
    DeactivateResult,
    ImportPreview,
    MappedDomainOut,
    RenewalCandidate,
    VaultSyncResult,
)
from app.api.paging import MAX_PAGE_SIZE, contains, count_by, fold_search, page_slice, validity_bucket
from app.core.certtype import cert_type_filter, normalize_cert_type
from app.core.security import ROLE_LEVELS, require_role, user_team_ids
from app.db.models import (
    AppDependency, Application, ApplicationTrustedCert, Certificate, CertificateDomainMap, Domain,
    Team, TransferProposal, User,
)
from app.db.session import get_db
from app.api.trigger_auth import EXTERNAL_ACTOR, external_cooldown, trigger_actor
from app.services import cert_parser, chain_repair, job_lock, notifier, renewal, revocation
from app.services.audit import audited_job, diff_fields, label_ids, log_action, snapshot
from app.services.cert_extras import pem_extras

router = APIRouter(prefix="/api/certificates", tags=["certificates"])


def _days_left(valid_to: datetime | None) -> int | None:
    return (valid_to - utcnow()).days if valid_to else None


# Dedup'un tek adresi cert_parser.find_existing — fingerprint kimliktir, SKI değil.
_find_existing = cert_parser.find_existing


def _to_out(cert: Certificate) -> CertificateOut:
    out = CertificateOut.model_validate(cert)
    out.days_left = _days_left(cert.valid_to)
    out.domains = [
        MappedDomainOut(domain_id=m.domain_id, domain=m.domain.domain, mapping_type=m.mapping_type)
        for m in cert.domain_mappings
    ]
    return out


@router.get("", response_model=list[CertificateOut])
def list_certificates(search: str | None = None, cert_type: str | None = None,
                      is_active: bool | None = None,
                      limit: int | None = Query(None, ge=1, le=5000), offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    # RBAC: envanter GLOBAL görünür (tüm takım üyelerine); require_role("viewer") takımsız (none) 403.
    # limit/offset OPSİYONEL: verilmezse tüm liste döner (mevcut davranış korunur, sessiz kırpma yok).
    q = db.query(Certificate).options(
        joinedload(Certificate.domain_mappings).joinedload(CertificateDomainMap.domain)
    )
    if search:
        like = f"%{search}%"
        q = q.filter(ci_like(Certificate.name, like) | ci_like(Certificate.serial_number, like)
                     | ci_like(Certificate.issuer, like) | ci_like(Certificate.subject, like)
                     | ci_like(Certificate.subject_key_identifier, like))
    if cert_type:
        # normalize: DB ham ("Intermediate") tutabilir; filtre kanonik eşleşme yapar (bkz. core/certtype)
        q = q.filter(cert_type_filter(Certificate.cert_type, cert_type))
    if is_active is not None:
        q = q.filter(Certificate.is_active == is_active)  # MSSQL: BIT = 1/0 (IS 1 geçersiz)
    return [_to_out(c) for c in
            q.order_by(Certificate.cert_type, Certificate.name).offset(offset).limit(limit).all()]


_LIGHT_SKIP = {"pem_certificate", "extras", "domains", "supersedes", "days_left", "superseded_by_name",
               "can_edit", "chain_added", "domain_count"}
_LIST_DOMAIN_CAP = 50   # Root/Intermediate yüzlerce domaine bağlı olabilir; liste satırı ilk 50'yi taşır
_SOURCES = ("manual", "vault", "live", "discovery", "ct")
_KNOWN_SRC = {"vault", "live", "discovery", "ct"}
_TYPE_SORT = {"intermediate": 0, "leaf": 1, "root": 2}   # eski ORDER BY cert_type ile aynı sıra


def _light_out(cert: Certificate, domains: list[MappedDomainOut],
               names: dict[int, str], cap: int | None = _LIST_DOMAIN_CAP) -> CertificateOut:
    """PEM'siz liste kaydı. ORM nesnesindeki PEM ertelendiği (defer) için okunmaz — binlerce
    sertifikada her satırın PEM'ini taşımak listeyi şişiriyordu."""
    data = {f: getattr(cert, f) for f in CertificateOut.model_fields if f not in _LIGHT_SKIP}
    out = CertificateOut.model_validate(data)
    out.days_left = _days_left(cert.valid_to)
    out.domain_count = len(domains)
    out.domains = domains[:cap] if cap else domains
    if cert.superseded_by_id:
        out.superseded_by_name = names.get(cert.superseded_by_id)
    return out


@router.get("/page", response_model=CertificatePage)
def page_certificates(page: int = Query(0, ge=0), size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
                      all: bool = False, q: str | None = None, is_active: bool | None = True,
                      f_name: str | None = None, f_ski: str | None = None,
                      f_saniss: str | None = None, f_source: str | None = None,
                      f_environment: str | None = None, f_valid: str | None = None,
                      collapsed: str | None = None, collapse_all: bool = False,
                      expanded: str | None = None,
                      db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    """SSL Sertifikaları listesi — sunucu tarafında arama, kolon filtresi ve sayfalama.
    Kolon filtresi yoksa satırlar ZİNCİR AĞACI sırasında (Root → Intermediate → Leaf) ve
    derinlikleriyle gelir; kapatılan düğümlerin (collapsed / collapse_all + expanded) altları
    sayfalamadan önce çıkarılır. Kolon filtresi varsa eşleşenler düz liste olarak gelir.
    PEM gövdesi listede yok (detay penceresi tekil GET ile alır)."""
    base = db.query(Certificate).options(defer(Certificate.pem_certificate))
    if q:
        like = f"%{q}%"
        base = base.filter(ci_like(Certificate.name, like) | ci_like(Certificate.serial_number, like)
                           | ci_like(Certificate.issuer, like) | ci_like(Certificate.subject, like)
                           | ci_like(Certificate.subject_key_identifier, like))
    if is_active is not None:
        base = base.filter(Certificate.is_active == is_active)  # MSSQL: BIT = 1/0
    certs = sorted(base.all(), key=lambda c: (_TYPE_SORT.get(normalize_cert_type(c.cert_type), 9), fold_search(c.name)))
    names = dict(db.query(Certificate.id, Certificate.name).all())
    links: dict[int, int] = dict(db.query(CertificateDomainMap.certificate_id, func.count())
                                 .group_by(CertificateDomainMap.certificate_id).all())

    def src(c): return c.source if c.source in _KNOWN_SRC else "manual"
    def env(c): return c.environment or "none"
    def val(c): return validity_bucket(_days_left(c.valid_to))

    facets = {"source": count_by(certs, src, _SOURCES),
              "environment": count_by(certs, env, ("prod", "test", "none")),
              "valid": count_by(certs, val, ("valid", "expiring", "expired", "none"))}
    flat = any((f_name, f_ski, f_saniss)) or any(
        v not in (None, "", "all") for v in (f_source, f_environment, f_valid))

    ids = {c.id for c in certs}
    by_id = {c.id: c for c in certs}
    children: dict[int | None, list[Certificate]] = {}
    for c in certs:
        key = c.parent_id if c.parent_id in ids and c.parent_id != c.id else None
        children.setdefault(key, []).append(c)

    rows: list[tuple[Certificate, int, int]] = []   # (sertifika, derinlik, kök id)
    if flat:
        for c in certs:
            if (contains(c.name, f_name) and contains(c.subject_key_identifier, f_ski)
                    and contains(c.san or c.issuer, f_saniss)
                    and f_source in (None, "", "all", src(c))
                    and f_environment in (None, "", "all", env(c))
                    and f_valid in (None, "", "all", val(c))):
                rows.append((c, 0, c.id))
    else:
        closed = {int(x) for x in (collapsed or "").split(",") if x.strip().isdigit()}
        opened = {int(x) for x in (expanded or "").split(",") if x.strip().isdigit()}

        def is_closed(cid: int) -> bool:
            return (cid not in opened) if collapse_all else (cid in closed)

        shown: set[int] = set()

        def walk(parent: int | None, depth: int, root: int | None) -> None:
            for c in children.get(parent, []):
                if c.id in shown:
                    continue
                shown.add(c.id)
                r = root if root is not None else c.id
                rows.append((c, depth, r))
                if children.get(c.id) and not is_closed(c.id):
                    walk(c.id, depth + 1, r)
                else:
                    # kapalı dalın altındakiler listede yok ama tekrar kök olarak da görünmesin
                    stack = list(children.get(c.id, []))
                    while stack:
                        x = stack.pop()
                        if x.id not in shown:
                            shown.add(x.id)
                            stack.extend(children.get(x.id, []))
        walk(None, 0, None)
        for c in certs:   # döngüdeki kayıtlar (A→B→A) hiçbir dala düşmez; kaybolmasınlar
            if c.id not in shown:
                rows.append((c, 0, c.id))

    # Kart görünümü özetleri: her kökün TÜM üyeleri (kapalı dallar dahil)
    groups: dict[int, CertificateGroupStat] = {}

    def subtree(root_id: int) -> list[Certificate]:
        out, stack, seen = [], [root_id], set()
        while stack:
            x = stack.pop()
            if x in seen or x not in by_id:
                continue
            seen.add(x)
            out.append(by_id[x])
            stack.extend(ch.id for ch in children.get(x, []))
        return out

    total = len(rows)
    if all:
        chosen, page, size = rows, 0, max(total, 1)
    else:
        chosen, page = page_slice(rows, page, size)
    if not flat:
        for rid in {r for _, _, r in chosen}:
            members = subtree(rid)
            days = [d for d in (_days_left(m.valid_to) for m in members) if d is not None]
            groups[rid] = CertificateGroupStat(members=len(members),
                                               domain_links=sum(links.get(m.id, 0) for m in members),
                                               worst_days=min(days) if days else None)
    page_ids = [c.id for c, _, _ in chosen]
    mapped: dict[int, list[MappedDomainOut]] = {}
    if page_ids:
        for m in (db.query(CertificateDomainMap).options(joinedload(CertificateDomainMap.domain))
                  .filter(CertificateDomainMap.certificate_id.in_(page_ids)).all()):
            mapped.setdefault(m.certificate_id, []).append(
                MappedDomainOut(domain_id=m.domain_id, domain=m.domain.domain, mapping_type=m.mapping_type))
    items = [CertificateTreeRow(cert=_light_out(c, mapped.get(c.id, []), names, None if all else _LIST_DOMAIN_CAP),
                                depth=depth,
                                has_children=bool(children.get(c.id)), root_id=r,
                                root_name=names.get(r, ""))
             for c, depth, r in chosen]
    return CertificatePage(items=items, total=total, page=page, size=size, facets=facets,
                           counts={"total": len(certs)}, groups=groups)


@router.get("/options", response_model=list[CertificateOption])
def certificate_options(q: str | None = None, cert_type: str | None = None,
                        is_active: bool | None = None, limit: int = Query(50, ge=1, le=200),
                        include: list[int] | None = Query(None),
                        db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    """Sertifika seçicileri için hafif ARAMA ucu (ad, SKI, Serial Number, SAN). Tüm envanteri
    (PEM'leriyle) indirmek yerine yazdıkça en fazla `limit` kayıt döner. `include` ile seçili
    kayıt(lar) her zaman listede gelir."""
    cols = (Certificate.id, Certificate.name, Certificate.cert_type, Certificate.is_active,
            Certificate.environment, Certificate.valid_to, Certificate.subject_key_identifier,
            Certificate.serial_number, Certificate.san)
    query = db.query(*cols)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(ci_like(Certificate.name, like) | ci_like(Certificate.serial_number, like)
                             | ci_like(Certificate.subject_key_identifier, like)
                             | ci_like(Certificate.san, like))
    if cert_type:
        query = query.filter(cert_type_filter(Certificate.cert_type, cert_type))
    if is_active is not None:
        query = query.filter(Certificate.is_active == is_active)
    rows = query.order_by(Certificate.name).limit(limit).all()
    if include:
        have = {r[0] for r in rows}
        rows += db.query(*cols).filter(Certificate.id.in_([i for i in include if i not in have] or [-1])).all()

    def opt(r):
        san = r[8]
        return CertificateOption(id=r[0], name=r[1], cert_type=normalize_cert_type(r[2]), is_active=bool(r[3]),
                                 environment=r[4], valid_to=r[5], days_left=_days_left(r[5]),
                                 subject_key_identifier=r[6], serial_number=r[7],
                                 san=(san[:300] + "…") if san and len(san) > 300 else san)
    return [opt(r) for r in rows]


_revocation_trigger = trigger_actor("revocation", "iptal denetimi")


@router.get("/revocation-run/status")
def revocation_run_status(actor: str = Depends(_revocation_trigger)):
    """Son toplu iptal denetiminin durumu (hangi sunucuda çalışırsa çalışsın aynı).
    /{cert_id}'den ÖNCE tanımlı olmalı (aksi halde 'revocation-run' sertifika id'si sanılır)."""
    return job_lock.job_status(revocation.JOB_NAME)


@router.get("/chain-check", response_model=list[ChainCheckFinding])
def chain_check(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Zincir Kontrolü (değiştirmez): tür, üst sertifika ve anahtar kimliği farkları."""
    return chain_repair.check(db)


@router.post("/chain-check/apply", response_model=list[ChainCheckFinding])
def chain_check_apply(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_role("admin"))):
    """Zincir Kontrolü farklarını düzeltir; her düzeltme işlem kaydına yazılır."""
    applied = chain_repair.apply(db)
    for f in applied:
        log_action(db, user.username, "chain_repair", "certificates", f["certificate_id"],
                   {"name": f["name"], "field": chain_repair.KIND_LABEL[f["kind"]],
                    "old": f["current"], "new": f["expected"]},
                   request)
    db.commit()
    return applied


@router.get("/{cert_id}", response_model=CertificateOut)
def get_certificate(cert_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("viewer"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    out = _to_out(cert)
    # Düzenleme penceresi yalnız PUT'un kabul edeceği kullanıcıya açılsın (aynı kural)
    if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS["editor"]:
        out.can_edit = False
    elif user.role == "admin":
        out.can_edit = True
    else:
        owners = _cert_owner_team_ids(db, cert)
        out.can_edit = not owners or bool(owners & user_team_ids(db, user))
    # Yenileme zinciri iki yönlü gezilebilsin: halefin adı + devraldığı öncüller
    if cert.superseded_by_id:
        successor = db.get(Certificate, cert.superseded_by_id)
        out.superseded_by_name = successor.name if successor else None
    out.supersedes = [
        CertRefOut(id=p.id, name=p.name, is_active=p.is_active)
        for p in db.query(Certificate)
                   .filter(Certificate.superseded_by_id == cert.id)
                   .order_by(Certificate.valid_to.desc()).all()
    ]
    extras = pem_extras(cert.pem_certificate)
    out.extras = CertExtrasOut(**extras) if extras else None
    return out


@router.get("/{cert_id}/chain", response_model=CertificateChainOut)
def get_chain(cert_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    """Sertifikanın zinciri: ata sertifikalar (kökten aşağıya sıralı), kendisi ve doğrudan
    alt sertifikalar. Döngüye karşı ziyaret edilenler izlenir."""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")

    ancestors: list[Certificate] = []
    seen = {cert.id}
    node = cert
    while node.parent_id and node.parent_id not in seen:
        parent = db.get(Certificate, node.parent_id)
        if parent is None:
            break
        ancestors.append(parent)
        seen.add(parent.id)
        node = parent
    ancestors.reverse()  # kökten aşağıya

    children = (db.query(Certificate)
                .filter(Certificate.parent_id == cert.id)
                .order_by(Certificate.cert_type, Certificate.name).all())

    return CertificateChainOut(
        ancestors=[_to_out(c) for c in ancestors],
        self=_to_out(cert),
        children=[_to_out(c) for c in children],
    )


@router.post("/import/preview", response_model=list[ImportPreview])
def import_preview(file: UploadFile = File(...), password: str | None = Form(None),
                   db: Session = Depends(get_db), _: User = Depends(require_role("editor"))):
    """Dosyayı parse eder, kaydetmeden alanları ve zincir eşleşmesini önizler."""
    try:
        parsed_list = cert_parser.parse_upload(file.file.read(), password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    previews = []
    for parsed in parsed_list:
        existing = _find_existing(db, parsed)
        parent_id = cert_parser.resolve_parent(db, parsed)
        parent = db.get(Certificate, parent_id) if parent_id else None
        parent_name = parent.name if parent else None
        if parent_name is None:
            # Üst sertifika envanterde yok ama AYNI dosyada geliyorsa (fullchain/p7b) import onu
            # önce kaydedip zinciri bağlar; önizleme "bulunamadı" demesin
            in_file = _find_file_parent(parsed, parsed_list)
            if in_file is not None:
                parent_name = f"{in_file.name} (bu dosyada)"
        preds: list[Certificate] = []
        file_pred = None
        if existing is None:
            preds = renewal.find_predecessors(
                db, cert_type=parsed.cert_type,
                fingerprint_sha256=parsed.fingerprint_sha256,
                subject_key_identifier=parsed.subject_key_identifier,
                subject=parsed.subject, issuer=parsed.issuer,
                valid_from=parsed.valid_from)
            file_pred = _find_file_predecessor(parsed, parsed_list)
        predecessor = preds[0] if preds else None
        # Devir planı TÜM öncülleri bildirmeli: import her öncülü devralır,
        # kullanıcı yalnız ilkini görürse eksik bir planı onaylamış olur
        also = [_pred_summary(p) for p in preds[1:]]
        if predecessor is not None and file_pred is not None:
            also.append(f"{file_pred.name} (bu dosyadaki eski nesil, "
                        f"bitiş {file_pred.valid_to:%d.%m.%Y})")
        if predecessor is not None:
            candidates = [RenewalCandidate(
                id=p.id, name=p.name,
                signal=renewal.renewal_signal(
                    p, subject_key_identifier=parsed.subject_key_identifier,
                    subject=parsed.subject, issuer=parsed.issuer),
                subject_key_identifier=p.subject_key_identifier, valid_to=p.valid_to,
                domains=[f"{m.domain.domain} ({m.mapping_type})" for m in p.domain_mappings],
                apps=_pred_app_bindings(db, p)) for p in preds]
            first = candidates[0]
            ren = dict(
                renewal_of_id=first.id, renewal_of_name=first.name,
                renewal_signal=first.signal,
                renewal_of_ski=first.subject_key_identifier,
                renewal_of_valid_to=first.valid_to,
                renewal_of_domains=first.domains,
                renewal_of_apps=first.apps,
                renewal_candidates=candidates)
        elif file_pred is not None:
            same_ski = (parsed.subject_key_identifier
                        and file_pred.subject_key_identifier == parsed.subject_key_identifier)
            ren = dict(
                renewal_of_id=None,
                renewal_of_name=f"{file_pred.name} (bu dosyadaki eski nesil)",
                renewal_signal="ski" if same_ski else "subject",
                renewal_of_ski=file_pred.subject_key_identifier,
                renewal_of_valid_to=file_pred.valid_to,
                renewal_of_domains=[])
        else:
            ren = {}
        previews.append(ImportPreview(
            **parsed.__dict__,
            already_exists=existing is not None,
            resolved_parent_id=parent_id,
            resolved_parent_name=parent_name,
            renewal_also=also,
            **ren,
        ))
    return previews


def _pred_summary(p: Certificate) -> str:
    maps = ", ".join(f"{m.domain.domain} ({m.mapping_type})" for m in p.domain_mappings)
    date = f"{p.valid_to:%d.%m.%Y}" if p.valid_to else "—"
    return f"{p.name} (bitiş {date})" + (f" — bağlantılar: {maps}" if maps else "")


def _find_file_parent(parsed, parsed_list):
    """Aynı dosyadaki üst sertifikayı (AKI = üstün SKI'si, yoksa issuer = üstün subject'i) bulur."""
    if parsed.cert_type == "root":
        return None
    for other in parsed_list:
        if other is parsed or other.cert_type == "leaf":
            continue
        if parsed.authority_key_identifier and other.subject_key_identifier:
            if other.subject_key_identifier == parsed.authority_key_identifier:
                return other
        elif other.subject == parsed.issuer:
            return other
    return None


def _pred_app_bindings(db: Session, pred: Certificate) -> list[str]:
    """Eski sertifikanın uygulama tarafındaki bağlantıları: mTLS istemci sertifikası olarak
    kullanan uygulamalar ve trust store'unda tutan uygulamalar (değişiklik talebi kapsamı)."""
    out = []
    for dep in (db.query(AppDependency).options(joinedload(AppDependency.app))
                .filter(AppDependency.client_cert_id == pred.id).all()):
        if dep.app is not None:
            out.append(f"{dep.app.app_name} (istemci sertifikası)")
    for (name,) in (db.query(Application.app_name)
                    .join(ApplicationTrustedCert, ApplicationTrustedCert.app_id == Application.id)
                    .filter(ApplicationTrustedCert.cert_id == pred.id).all()):
        out.append(f"{name} (trust store)")
    return sorted(set(out))


def _find_file_predecessor(parsed, parsed_list):
    """Aynı dosyada birlikte yüklenen ESKİ nesli bulur. Import, flush sonrası bu
    kardeşi de öncül olarak devralacağı için plan önizlemede görünmek zorunda."""
    if parsed.cert_type != "leaf":
        return None
    best = None
    for other in parsed_list:
        if other is parsed or other.cert_type != "leaf":
            continue
        if other.fingerprint_sha256 == parsed.fingerprint_sha256:
            continue
        same_ski = (parsed.subject_key_identifier
                    and other.subject_key_identifier == parsed.subject_key_identifier)
        same_subject = (parsed.subject and parsed.issuer
                        and other.subject == parsed.subject and other.issuer == parsed.issuer)
        if not (same_ski or same_subject):
            continue
        if not (other.valid_from and parsed.valid_from
                and other.valid_from < parsed.valid_from):
            continue
        if best is None or other.valid_to > best.valid_to:
            best = other
    return best


@router.post("/import", response_model=list[CertificateOut])
def import_certificates(request: Request, file: UploadFile = File(...),
                        password: str | None = Form(None), notes: str | None = Form(None),
                        purchased_by: str | None = Form(None), is_internal: bool = Form(False),
                        source: str = Form("manual"), supersede: bool = Form(False),
                        creator: str | None = Form(None), environment: str | None = Form(None),
                        db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    """Binary import: PEM (fullchain destekli) / DER / PFX. Var olanları atlar,
    zinciri SKI/AKI ile otomatik bağlar. Değişiklik talebi ÜRETMEZ (supersede etkisiz);
    önizleme yenileme bulduysa arayüz kullanıcıya sorar ve onay verilirse içe aktarmadan sonra
    /{yeni}/supersede/{eski} ile talepleri açar."""
    if environment not in (None, "", "prod", "test"):
        raise HTTPException(status_code=400, detail="environment yalnız 'prod' veya 'test' olabilir")
    try:
        parsed_list = cert_parser.parse_upload(file.file.read(), password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    created: list[Certificate] = []
    # Önce CA'lar (leaf'ler parent bulsun), leaf'lerde önce ESKİ nesil (valid_from):
    # aynı dosyada iki nesil varsa devir dosyadaki PEM sırasından bağımsız işler
    parsed_list.sort(key=lambda p: ({"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type],
                                    p.valid_from or datetime.min))
    for parsed in parsed_list:
        if _find_existing(db, parsed):
            continue
        cert = Certificate(**parsed.__dict__, notes=notes, purchased_by=purchased_by,
                           is_internal=is_internal, creator=creator or user.username, source=source,
                           environment=environment or None)
        cert.parent_id = cert_parser.resolve_parent(db, parsed)
        db.add(cert)
        db.flush()
        cert_parser.relink_children(db, cert)
        log_action(db, user.username, "import", "certificates", cert.id,
                   {"name": cert.name, "serial": cert.serial_number}, request)
        # Dosyadan içe aktarma kendi başına değişiklik talebi ÜRETMEZ (`supersede` geriye uyum için
        # kabul edilir, etkisizdir): talep canlı doğrulamadan (yalnız o domain için), içe aktarma
        # penceresindeki "değişiklik talebi oluştur" onayından ya da sertifika detayındaki
        # "Değişiklik Talebi Oluştur"den gelir — ikisi de /supersede ucunu çağırır.
        created.append(cert)
    db.commit()
    if not created:
        raise HTTPException(status_code=409, detail="Dosyadaki tüm sertifikalar zaten kayıtlı")
    return [_to_out(c) for c in created]


@router.post("/{new_id}/supersede/{old_id}")
def supersede_certificate(request: Request, new_id: int, old_id: int,
                          db: Session = Depends(get_db),
                          user: User = Depends(require_role("editor"))):
    """old_id → new_id devri için ÖNERİ üretir (anında devir YOK). Her bağlantı granülü
    (domain eşlemesi / mTLS bağımlılığı) için AYRI öneri doğar ve o granülün sahibi SY
    ekibinin onayını bekler. İdempotent; oluşan öneri sayısını döndürür.

    SAHİPLİK: editör devri yalnız KENDİ ekibinin kullandığı (en az bir bağlantısı kendi
    SY ekibine ait olan) sertifika için tetikleyebilir; admin her sertifika için.
    Bilinçli manuel tetik olduğundan REDDEDİLMİŞ granülleri de yeniden açar (reopen)."""
    if new_id == old_id:
        raise HTTPException(status_code=400, detail="Sertifika kendisini devralamaz")
    new_cert = db.get(Certificate, new_id)
    old_cert = db.get(Certificate, old_id)
    if new_cert is None or old_cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    if not new_cert.is_active:
        raise HTTPException(status_code=400, detail="Pasif bir sertifika yeni sertifika olarak seçilemez")
    if not renewal.same_type(new_cert, old_cert):
        raise HTTPException(status_code=400, detail=(
            "Değişiklik yalnız aynı seviyedeki sertifikalar arasında yapılabilir "
            "(leaf → leaf, intermediate → intermediate, root → root)"))
    if user.role != "admin":
        binding_teams = {m.domain.sy_team_id for m in old_cert.domain_mappings
                         if m.domain is not None}
        binding_teams |= {dep.app.sy_team_id for dep in
                          db.query(AppDependency).options(joinedload(AppDependency.app))
                          .filter(AppDependency.client_cert_id == old_cert.id).all()
                          if dep.app is not None}
        # Trust store'unda tutan uygulamanın ekibi de kendi trusted sertifikası için talep açabilir
        binding_teams |= {r[0] for r in db.query(Application.sy_team_id)
                          .join(ApplicationTrustedCert, ApplicationTrustedCert.app_id == Application.id)
                          .filter(ApplicationTrustedCert.cert_id == old_cert.id).all()}
        if not (binding_teams & user_team_ids(db, user)):
            raise HTTPException(status_code=403, detail=(
                "Değişiklik talebini yalnız sertifikanın bağlı olduğu domain/uygulamaların "
                "SY ekibi üyesi veya admin tetikleyebilir"))
    created = renewal.propose(db, new_cert, old_cert, username=user.username, request=request,
                              via="manual", reopen_rejected=True)
    db.commit()
    if not created:
        return {"proposed": 0, "message":
                "Yeni talep oluşmadı — bu bağlantılar için zaten açık talep var ya da eski "
                "sertifikanın yeni sertifikaya taşınacak bağlantısı yok"}
    return {"proposed": len(created), "message":
            f"{len(created)} değişiklik talebi oluşturuldu — ilgili SY ekiplerinin onayı bekleniyor"}


@router.post("/vault-sync", response_model=VaultSyncResult)
def vault_sync(request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_role("editor"))):
    """Vault KV kasasındaki sertifikaları envantere çeker (yalnız PUBLIC cert okunur;
    özel anahtar alanına ASLA dokunulmaz). Kullanıcı sertifikayı doğrudan Vault'a yükler,
    JUMBO buradan senkronize eder."""
    from app.services.providers.vault import VaultProvider

    provider = VaultProvider(db)
    if not provider.is_available():
        raise HTTPException(status_code=400, detail="Vault entegrasyonu etkin değil (Ayarlar → Vault)")
    prefix = (provider.config.get("kv_prefix") or "certs").strip("/")
    try:
        # Özyinelemeli tara: certs/ ve certs/<ekip>/ gibi alt klasörlerdeki tüm sertifikalar
        leaf_paths: list[str] = []
        stack = [prefix]
        while stack:
            node = stack.pop()
            for key in provider.kv_list(node):
                full = f"{node}/{key}".strip("/")
                if key.endswith("/"):
                    stack.append(full)   # alt klasör (ör. ekip) → içine in
                else:
                    leaf_paths.append(full)
    except Exception as exc:  # bağlantı/format hatası
        raise HTTPException(status_code=502, detail=f"Vault KV listelenemedi: {exc}")

    created = updated = skipped = superseded = 0
    errors: list[str] = []
    for path in leaf_paths:
        try:
            entry = provider.kv_get(path)
            if not entry:
                continue
            pem = entry.get("certificate") or entry.get("cert")  # anahtar (private_key) OKUNMAZ
            if not pem or "BEGIN CERTIFICATE" not in pem:
                skipped += 1
                continue
            chain = entry.get("chain") or ""
            text = pem if "BEGIN CERTIFICATE" not in chain else f"{pem}\n{chain}"
            parsed_list = cert_parser.parse_pem_text(text)
            # KV girdisinin 'certificate' alanındaki ilk sertifika = uç (endpoint) sertifika;
            # vault_path'i buna bağla (self-signed/leaf fark etmeksizin doğru olsun).
            primary_fp = parsed_list[0].fingerprint_sha256 if parsed_list else None
        except Exception as exc:
            errors.append(f"{path}: {exc}")  # hatayı işlenen YOL ile raporla (önceki `key` listeleme döngüsünündü)
            continue

        parsed_list.sort(key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}.get(p.cert_type, 3))
        for parsed in parsed_list:
            is_primary = parsed.fingerprint_sha256 == primary_fp
            existing = _find_existing(db, parsed)
            if existing:
                changed = False
                if existing.source != "vault":
                    existing.source, changed = "vault", True
                if is_primary and existing.vault_path != path:
                    existing.vault_path, changed = path, True
                updated += 1 if changed else 0
                skipped += 0 if changed else 1
                continue
            cert = Certificate(**parsed.__dict__, source="vault", creator=user.username,
                               vault_path=path if is_primary else None)
            cert.parent_id = cert_parser.resolve_parent(db, parsed)
            db.add(cert)
            db.flush()
            cert_parser.relink_children(db, cert)
            created += 1
            # Vault senkronu değişiklik talebi ÜRETMEZ (superseded hep 0) — yalnız envantere ekler.
            # Öneri, yeni sertifikanın deploy edildiği domainin canlı doğrulamasından gelir.

    log_action(db, user.username, "vault_sync", "certificates", None,
               {"created": created, "updated": updated, "skipped": skipped,
                "superseded": superseded, "paths": leaf_paths}, request)
    db.commit()
    return VaultSyncResult(created=created, updated=updated, skipped=skipped,
                           superseded=superseded, errors=errors)


@router.post("", response_model=CertificateOut)
def create_certificate(request: Request, body: CertificateCreate, db: Session = Depends(get_db),
                       user: User = Depends(require_role("editor"))):
    """Manuel ekleme. PEM verilmişse alanlar PEM'den doğrulanıp tamamlanır."""
    data = body.model_dump()
    extra: list = []  # PEM'e zincir yapıştırıldıysa ana sertifika dışındakiler (ara/kök)
    if body.pem_certificate and body.pem_certificate.strip():
        try:
            parsed_all = cert_parser.parse_pem_text(body.pem_certificate)
        except (ValueError, Exception) as exc:
            raise HTTPException(status_code=400, detail=f"PEM parse edilemedi: {exc}")
        # Ana kayıt: formdaki bilgiler zincirdeki TEK uç sertifikaya aittir; uç yoksa/birden
        # çoksa ilk sertifika. Diğerleri dosyadan içe aktarmadaki gibi ayrıca kaydedilir.
        leaves = [p for p in parsed_all if p.cert_type == "leaf"]
        parsed = leaves[0] if len(leaves) == 1 else parsed_all[0]
        extra = [p for p in parsed_all if p is not parsed]
        for field in ("serial_number", "issuer", "subject", "subject_key_identifier",
                      "authority_key_identifier", "cert_type", "valid_from", "valid_to",
                      "extended_key_usage", "pem_certificate", "san", "fingerprint_sha256",
                      "key_size", "public_key_type", "key_curve", "signature_hash"):
            data[field] = getattr(parsed, field)
        if not data.get("name"):
            data["name"] = parsed.name
        existing = _find_existing(db, parsed)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Bu sertifika zaten kayıtlı: {existing.name} (ID {existing.id})")
    elif body.serial_number and body.issuer:
        # PEM'siz kayıtta fingerprint yok; serial+issuer ile mükerrer engellenir.
        # (Yalnız isimle "placeholder" kayıt serbesttir — kimliksiz, dedup edilemez.)
        existing = db.query(Certificate).filter(
            Certificate.serial_number == body.serial_number,
            Certificate.issuer == body.issuer).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Bu sertifika zaten kayıtlı: {existing.name} (ID {existing.id})")
    # Prod şeması: SerialNumber NOT NULL+UNIQUE, Issuer/Subject NOT NULL. PEM'siz "placeholder"
    # (yalnız-isim) kayıtlarda bu alanlar boş kalır → prod'un reddetmemesi için doldur. Sentetik
    # serial tanınır ve benzersizdir; issuer/subject boşsa isme düşer. (PEM'li yolda hepsi zaten dolu.)
    if not data.get("serial_number"):
        data["serial_number"] = f"PLACEHOLDER-{uuid4().hex}"
    if not data.get("issuer"):
        data["issuer"] = data.get("name")
    if not data.get("subject"):
        data["subject"] = data.get("name")
    if not data.get("valid_from"):  # prod ValidFrom/ValidTo NOT NULL → placeholder'da nominal doldur
        data["valid_from"] = utcnow()
    if not data.get("valid_to"):
        data["valid_to"] = data["valid_from"]
    chain_added = _add_chain_extras(db, extra, data, user, request)
    cert = Certificate(**data)
    if cert.parent_id is None and cert.pem_certificate:
        cert.parent_id = cert_parser.resolve_parent(db, parsed)
    elif cert.parent_id is None and cert.authority_key_identifier:
        parent = cert_parser.find_ca_by_ski(db, cert.authority_key_identifier)
        cert.parent_id = parent.id if parent else None
    if not cert.creator:
        cert.creator = user.username
    db.add(cert)
    db.flush()
    cert_parser.relink_children(db, cert)
    log_action(db, user.username, "create", "certificates", cert.id, {"name": cert.name}, request)
    db.commit()
    out = _to_out(cert)
    out.chain_added = chain_added
    return out


def _add_chain_extras(db: Session, extra: list, data: dict, user: User,
                      request: Request) -> list[str]:
    """Manuel Ekle'de PEM'e yapıştırılan zincirin ana sertifika dışındaki üyeleri: kayıtlı
    olmayanlar dosyadan içe aktarmadaki gibi eklenir (CA'lar önce, ana kayıt parent bulsun)."""
    added: list[str] = []
    extra = sorted(extra, key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type])
    for parsed in extra:
        if _find_existing(db, parsed):
            continue
        row = Certificate(**parsed.__dict__, creator=data.get("creator") or user.username,
                          environment=data.get("environment"), source="manual")
        row.parent_id = cert_parser.resolve_parent(db, parsed)
        db.add(row)
        db.flush()
        cert_parser.relink_children(db, row)
        log_action(db, user.username, "import", "certificates", row.id,
                   {"name": row.name, "serial": row.serial_number, "via": "manuel zincir"}, request)
        added.append(row.name)
    return added


def _ensure_deactivatable(db: Session, cert: Certificate) -> None:
    """İş kuralı: bir domaine SERVER olarak bağlı sertifika PASİFE ALINAMAZ — canlı hizmet
    veriyor demektir; önce server bağlantısı halef sertifikaya devredilmeli (devir onayı).
    Client/Trusted/mTLS bağı engellemez (bunlar pasife almayı bloklamaz)."""
    bound = (db.query(CertificateDomainMap)
             .options(joinedload(CertificateDomainMap.domain))
             .filter(CertificateDomainMap.certificate_id == cert.id,
                     CertificateDomainMap.mapping_type == "server").all())
    names = [m.domain.domain for m in bound if m.domain]
    if names:
        raise HTTPException(status_code=409,
                            detail=f"Bu sertifika şu domain(ler)e SERVER olarak bağlı: "
                                   f"{', '.join(names)}. Pasife almadan önce server bağlantısını "
                                   f"Değişiklik Talebi ile yeni sertifikaya taşıyın.")


def _cert_owner_team_ids(db: Session, cert: Certificate) -> set[int]:
    """Sertifikanın SAHİP SY ekipleri: Oluşturan Ekip + bağlı olduğu domainlerin, mTLS
    bağımlılığında kullanan ve trust store'una ekleyen uygulamaların SY ekipleri. Boş küme →
    sahipsiz/ortak kayıt (ör. hiçbir yere bağlı olmayan kök/ara sertifika)."""
    owners: set[int] = set()
    if cert.creator:
        team = db.query(Team).filter(Team.name == cert.creator, Team.type == "SY").first()
        if team is not None:
            owners.add(team.id)
    owners.update(r[0] for r in db.query(Domain.sy_team_id)
                  .join(CertificateDomainMap, CertificateDomainMap.domain_id == Domain.id)
                  .filter(CertificateDomainMap.certificate_id == cert.id,
                          Domain.sy_team_id.isnot(None)).all())
    owners.update(r[0] for r in db.query(Application.sy_team_id)
                  .join(AppDependency, AppDependency.app_id == Application.id)
                  .filter(AppDependency.client_cert_id == cert.id,
                          Application.sy_team_id.isnot(None)).all())
    owners.update(r[0] for r in db.query(Application.sy_team_id)
                  .join(ApplicationTrustedCert, ApplicationTrustedCert.app_id == Application.id)
                  .filter(ApplicationTrustedCert.cert_id == cert.id,
                          Application.sy_team_id.isnot(None)).all())
    return owners


def _ensure_can_edit_cert(db: Session, user: User, cert: Certificate) -> None:
    """Editör yalnız KENDİ ekibine ait (ya da sahipsiz/ortak) sertifikayı düzenler; başka
    ekibin sertifikasının adı/türü/notu o ekibin uyarılarını etkiler. Admin her zaman."""
    if user.role == "admin":
        return
    owners = _cert_owner_team_ids(db, cert)
    if owners and not owners & user_team_ids(db, user):
        raise HTTPException(status_code=403,
                            detail="Bu sertifika başka bir ekibe ait; yalnız o ekibin editörü "
                                   "veya admin düzenleyebilir")


# Sertifikanın kendisinden gelen bilgiler — elle düzeltmeyi yalnız admin yapar
ADMIN_ONLY_FIELDS = ("name", "cert_type", "parent_id", "is_internal")


@router.put("/{cert_id}", response_model=CertificateOut)
def update_certificate(request: Request, cert_id: int, body: CertificateUpdate,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    _ensure_can_edit_cert(db, user, cert)
    changes = body.model_dump(exclude_unset=True)
    # Aktif/pasif durumu (is_active) YALNIZ admin tarafından değiştirilir. Aksi halde SY editörü
    # deactivate ucunu baypas edip PUT is_active=false ile sertifikayı pasife alabilirdi.
    if "is_active" in changes and changes["is_active"] != cert.is_active:
        if user.role != "admin":
            raise HTTPException(status_code=403,
                                detail="Sertifikayı yalnız admin pasife alabilir/aktifleştirebilir")
        if changes["is_active"] is False:  # pasife alma → server bağı engeller (deactivate ile aynı kural)
            _ensure_deactivatable(db, cert)
    # Sertifikadan okunan bilgilerin elle düzeltilmesi (ad, tür, üst sertifika, Internal) YALNIZ
    # admin işidir; editör yalnız kurumsal alanları (Ortam, Satın Alım, Oluşturan Ekip, Notlar)
    # değiştirebilir. Aynı değerin geri gönderilmesi değişiklik sayılmaz.
    if user.role != "admin":
        locked = [k for k in ADMIN_ONLY_FIELDS if k in changes and changes[k] != getattr(cert, k)]
        if locked:
            raise HTTPException(status_code=403,
                                detail="Sertifika adı, Type, üst sertifika ve Internal bilgisini "
                                       "yalnız admin değiştirebilir")
    if changes.get("parent_id") is not None:
        _ensure_valid_parent(db, cert, changes["parent_id"])
    diff = label_ids(db, diff_fields(cert, changes))
    for key, value in changes.items():
        setattr(cert, key, value)
    log_action(db, user.username, "update", "certificates", cert.id,
               {"name": cert.name, "changes": diff}, request)
    db.commit()
    return _to_out(cert)


def _ensure_valid_parent(db: Session, cert: Certificate, parent_id: int) -> None:
    """Elle verilen üst sertifika: kendisi olamaz, zinciri kendi içine döndüremez."""
    parent = db.get(Certificate, parent_id)
    if parent is None:
        raise HTTPException(status_code=400, detail="Seçilen üst sertifika bulunamadı")
    seen: set[int] = set()
    cur = parent
    while cur is not None and cur.id not in seen:
        if cur.id == cert.id:
            raise HTTPException(status_code=400,
                                detail="Bir sertifika kendisinin ya da kendi alt sertifikasının altına bağlanamaz")
        seen.add(cur.id)
        cur = cur.parent


@router.post("/{cert_id}/deactivate", response_model=DeactivateResult)
def deactivate_certificate(request: Request, cert_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_role("admin"))):
    """Sertifikayı pasife alır — YALNIZ admin (SY editörleri sertifikayı pasife alamaz).
    Bağlı domain varsa o domainlerin SY ekiplerine
    bilgilendirme gönderilir (JUMBO devir yapmaz — ekip yerine geçecek sertifikayı
    kendi onaylar). İdempotent: zaten pasif sertifika yeniden bilgilendirme üretmez.
    (Aktifleştirme için PUT /{id} is_active=true kullanılır.)"""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    if not cert.is_active:
        return DeactivateResult(certificate=_to_out(cert), message="Sertifika zaten pasif.")
    _ensure_deactivatable(db, cert)  # server olarak domaine bağlıysa 409 — önce devret
    cert.is_active = False
    log_action(db, user.username, "deactivate", "certificates", cert.id, {"name": cert.name}, request)
    db.commit()
    result = notifier.notify_certificate_deactivated(db, cert, user.username)
    return DeactivateResult(certificate=_to_out(cert), bound_domains=result["bound_domains"],
                            notified_recipients=result["recipients"], teams=result["teams"],
                            mail_sent=result["mail_sent"], message=result["message"])


@router.post("/{cert_id}/revocation-check")
def revocation_check(request: Request, cert_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_role("editor"))):
    """Sertifikanın iptal durumunu OCSP/CRL ile CANLI denetler ve kaydeder. Global 'revocation.enabled'
    bayrağından bağımsız çalışır (admin egress'i elle doğrulayabilsin). Dış erişim yoksa 'unreachable' döner
    (çökme yok). Sertifikayı pasife ALMAZ — yalnız durum yazar."""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    if not cert.pem_certificate:
        raise HTTPException(status_code=400, detail="Bu kaydın PEM'i yok, iptal durumu denetlenemez")
    config = revocation.get_config(db)
    client = revocation._client(config)
    previous = cert.revocation_status
    try:
        status, _ = revocation.run_check(db, cert, client, config)
    finally:
        client.close()
    log_action(db, user.username, "revocation_check", "certificates", cert.id,
               {"name": cert.name, "status": status}, request)
    db.commit()
    if status == "revoked" and previous != "revoked":
        revocation.notify_newly_revoked(db, [cert])
    return {"revocation_status": cert.revocation_status,
            "revocation_checked_at": cert.revocation_checked_at,
            "revocation_detail": cert.revocation_detail}


@audited_job("İptal (OCSP/CRL) denetimi (tetiklenen)")
def _triggered_revocation_run() -> dict:
    return revocation.run_all_checks()


@router.post("/revocation-run")
def revocation_run(request: Request, db: Session = Depends(get_db),
                   actor: str = Depends(_revocation_trigger)):
    """Tüm aktif leaf sertifikalar için iptal denetimini arka planda başlatır (gece işiyle aynı motor).
    Admin JWT VEYA dış araç (X-API-Key: revocation.trigger_api_key); 'gece otomatik' ayarından
    bağımsız. Dış erişim gerektirir; kapalı ağda çoğu sonuç kesin olmayan (unreachable/not_checkable)
    olur (beklenen). Ayarlarda iptal denetimi KAPALIYSA "başlatıldı" deyip boşa bekletmemek için
    409 verilir (iptal maili yalnız açıkken gider). Aynı denetim başka yerde sürüyorsa da 409.
    (Tek sertifikalık /revocation-check bilerek ayardan bağımsız.)"""
    if actor == EXTERNAL_ACTOR:
        external_cooldown("revocation-run")
    if not revocation.get_config(db).get("enabled"):
        raise HTTPException(status_code=409,
                            detail="İptal kontrolü Ayarlar'da kapalı; toplu denetim için önce açın")
    if not job_lock.start_in_background(revocation.JOB_NAME, _triggered_revocation_run,
                                        triggered_by=actor, thread_name="revocation-bulk"):
        raise HTTPException(status_code=409, detail="İptal denetimi şu anda çalışıyor (bu ya da "
                                                    "başka bir sunucuda) — bitince tekrar deneyin")
    log_action(db, actor, "revocation_run", "certificates", None,
               {"trigger": "external" if actor == EXTERNAL_ACTOR else "manual"}, request)
    db.commit()
    return {"message": "İptal denetimi başlatıldı — sonuçlar sertifikalara işlenecek",
            "status_url": "/api/certificates/revocation-run/status"}


@router.delete("/{cert_id}")
def delete_certificate(request: Request, cert_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_role("admin"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    children = list(cert.children)
    for child in children:
        child.parent_id = None
    # Kendine referanslı halef bağını boşalt: bu cert'i "yerine geçen" gösteren kayıtlar
    # (MSSQL self-FK'de ON DELETE SET NULL'a izin vermez → DB boşaltmaz, elle yapılır)
    db.query(Certificate).filter(Certificate.superseded_by_id == cert.id).update(
        {Certificate.superseded_by_id: None}, synchronize_session=False)
    # İlgili değişiklik taleplerini temizle (FK NO ACTION — hem SQLite hem MSSQL'de elle sil)
    db.query(TransferProposal).filter(
        (TransferProposal.old_cert_id == cert.id)
        | (TransferProposal.new_cert_id == cert.id)).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "certificates", cert.id,
               {"name": cert.name,
                "snapshot": snapshot(cert, ("name", "cert_type", "subject", "issuer", "serial_number",
                                            "fingerprint_sha256", "valid_from", "valid_to",
                                            "environment", "source", "is_active")),
                "domains": [f"{m.domain.domain} ({m.mapping_type})"
                            for m in cert.domain_mappings if m.domain]}, request)
    db.delete(cert)
    db.flush()
    # Çocuklar üstsüz kalmasın: aynı anahtarlı başka bir CA kaydı (yenilenmiş ara CA) varsa ona bağlanır
    for child in children:
        child.parent_id = cert_parser.resolve_parent(db, child, exclude_id=cert.id)
    db.commit()
    return {"ok": True}
