from datetime import datetime
from app.core.timeutil import utcnow
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import (
    CertificateChainOut,
    CertificateCreate,
    CertificateOut,
    CertificateUpdate,
    CertRefOut,
    DeactivateResult,
    ImportPreview,
    MappedDomainOut,
    VaultSyncResult,
)
from app.core.certtype import cert_type_filter
from app.core.security import require_role, user_team_ids
from app.db.models import (
    AppDependency, Certificate, CertificateDomainMap, TransferProposal, User,
)
from app.db.session import get_db
from app.services import cert_parser, notifier, renewal, revocation
from app.services.audit import log_action

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
        q = q.filter(Certificate.name.ilike(like) | Certificate.serial_number.ilike(like)
                     | Certificate.issuer.ilike(like) | Certificate.subject.ilike(like)
                     | Certificate.subject_key_identifier.ilike(like))
    if cert_type:
        # normalize: DB ham ("Intermediate") tutabilir; filtre kanonik eşleşme yapar (bkz. core/certtype)
        q = q.filter(cert_type_filter(Certificate.cert_type, cert_type))
    if is_active is not None:
        q = q.filter(Certificate.is_active == is_active)  # MSSQL: BIT = 1/0 (IS 1 geçersiz)
    return [_to_out(c) for c in
            q.order_by(Certificate.cert_type, Certificate.name).offset(offset).limit(limit).all()]


@router.get("/{cert_id}", response_model=CertificateOut)
def get_certificate(cert_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("viewer"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    out = _to_out(cert)
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
            ren = dict(
                renewal_of_id=predecessor.id, renewal_of_name=predecessor.name,
                renewal_signal=renewal.renewal_signal(
                    predecessor, subject_key_identifier=parsed.subject_key_identifier,
                    subject=parsed.subject, issuer=parsed.issuer),
                renewal_of_ski=predecessor.subject_key_identifier,
                renewal_of_valid_to=predecessor.valid_to,
                renewal_of_domains=[f"{m.domain.domain} ({m.mapping_type})"
                                    for m in predecessor.domain_mappings])
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
            resolved_parent_name=parent.name if parent else None,
            renewal_also=also,
            **ren,
        ))
    return previews


def _pred_summary(p: Certificate) -> str:
    maps = ", ".join(f"{m.domain.domain} ({m.mapping_type})" for m in p.domain_mappings)
    date = f"{p.valid_to:%d.%m.%Y}" if p.valid_to else "—"
    return f"{p.name} (bitiş {date})" + (f" — eşlemeler: {maps}" if maps else "")


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
    zinciri SKI/AKI ile otomatik bağlar. supersede=true ise yeni leaf'lerin
    öncülleri (aynı SKI veya aynı subject+issuer) devralınır: eşlemeler taşınır,
    eski kayıt pasife alınır."""
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
        if supersede:
            for old in renewal.find_predecessors(
                    db, cert_type=cert.cert_type,
                    fingerprint_sha256=cert.fingerprint_sha256,
                    subject_key_identifier=cert.subject_key_identifier,
                    subject=cert.subject, issuer=cert.issuer,
                    valid_from=cert.valid_from, exclude_id=cert.id):
                # ONAY MODELİ: anında devir YOK — SY onayına düşecek öneri üret
                renewal.propose(db, cert, old, username=user.username, request=request,
                                via="import", signal=renewal.renewal_signal(
                                    old, subject_key_identifier=cert.subject_key_identifier,
                                    subject=cert.subject, issuer=cert.issuer))
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
        raise HTTPException(status_code=400, detail="Pasif bir sertifika devralamaz")
    if user.role != "admin":
        binding_teams = {m.domain.sy_team_id for m in old_cert.domain_mappings
                         if m.domain is not None}
        binding_teams |= {dep.app.sy_team_id for dep in
                          db.query(AppDependency).options(joinedload(AppDependency.app))
                          .filter(AppDependency.client_cert_id == old_cert.id).all()
                          if dep.app is not None}
        if not (binding_teams & user_team_ids(db, user)):
            raise HTTPException(status_code=403, detail=(
                "Devri yalnız sertifikanın bağlı olduğu domain/uygulamaların "
                "SY ekibi üyesi veya admin tetikleyebilir"))
    created = renewal.propose(db, new_cert, old_cert, username=user.username, request=request,
                              via="manual", reopen_rejected=True)
    db.commit()
    if not created:
        return {"proposed": 0, "message":
                "Yeni öneri oluşmadı — granüller için zaten açık öneri var ya da eski "
                "sertifikanın devredilecek bağlantısı yok"}
    return {"proposed": len(created), "message":
            f"{len(created)} devir önerisi oluşturuldu — ilgili SY ekiplerinin onayı bekleniyor"}


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
            if is_primary and cert.cert_type == "leaf":
                # Rotasyon algılama — ONAY MODELİ: Vault'ta yeni sürüm görüldü ama
                # JUMBO kendiliğinden devretmez. Öncüller için PENDING öneri üretilir;
                # eşlemeler taşınmaz, eski aktif kalır. Devir yalnız SY onayıyla olur.
                same_path = (db.query(Certificate)
                             .filter(Certificate.vault_path == path,
                                     Certificate.id != cert.id,
                                     Certificate.is_active == True).all())
                candidates = same_path or renewal.find_predecessors(
                    db, cert_type=cert.cert_type,
                    fingerprint_sha256=cert.fingerprint_sha256,
                    subject_key_identifier=cert.subject_key_identifier,
                    subject=cert.subject, issuer=cert.issuer,
                    valid_from=cert.valid_from, exclude_id=cert.id)
                for old in candidates:
                    made = renewal.propose(db, cert, old, username=user.username,
                                           request=request, via="vault-sync")
                    superseded += 1 if made else 0

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
    if body.pem_certificate and body.pem_certificate.strip():
        try:
            parsed = cert_parser.parse_pem_text(body.pem_certificate)[0]
        except (ValueError, Exception) as exc:
            raise HTTPException(status_code=400, detail=f"PEM parse edilemedi: {exc}")
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
    cert = Certificate(**data)
    if cert.parent_id is None and cert.authority_key_identifier:
        parent = cert_parser.find_ca_by_ski(db, cert.authority_key_identifier)
        cert.parent_id = parent.id if parent else None
    if not cert.creator:
        cert.creator = user.username
    db.add(cert)
    db.flush()
    cert_parser.relink_children(db, cert)
    log_action(db, user.username, "create", "certificates", cert.id, {"name": cert.name}, request)
    db.commit()
    return _to_out(cert)


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
                                   f"halef sertifikaya devredin.")


@router.put("/{cert_id}", response_model=CertificateOut)
def update_certificate(request: Request, cert_id: int, body: CertificateUpdate,
                       db: Session = Depends(get_db), user: User = Depends(require_role("editor"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    changes = body.model_dump(exclude_unset=True)
    # Aktif/pasif durumu (is_active) YALNIZ admin tarafından değiştirilir. Aksi halde SY editörü
    # deactivate ucunu baypas edip PUT is_active=false ile sertifikayı pasife alabilirdi.
    if "is_active" in changes and changes["is_active"] != cert.is_active:
        if user.role != "admin":
            raise HTTPException(status_code=403,
                                detail="Sertifikayı yalnız admin pasife alabilir/aktifleştirebilir")
        if changes["is_active"] is False:  # pasife alma → server bağı engeller (deactivate ile aynı kural)
            _ensure_deactivatable(db, cert)
    for key, value in changes.items():
        setattr(cert, key, value)
    log_action(db, user.username, "update", "certificates", cert.id, changes, request)
    db.commit()
    return _to_out(cert)


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
    bayrağından bağımsız çalışır (admin egress'i elle doğrulayabilsin). Dış erişim yoksa 'unknown' döner
    (çökme yok). Sertifikayı pasife ALMAZ — yalnız durum yazar."""
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    if not cert.pem_certificate:
        raise HTTPException(status_code=400, detail="Bu kaydın PEM'i yok, iptal durumu denetlenemez")
    config = revocation.get_config(db)
    client = revocation._client(config)
    try:
        status, _ = revocation.run_check(db, cert, client, config)
    finally:
        client.close()
    log_action(db, user.username, "revocation_check", "certificates", cert.id,
               {"name": cert.name, "status": status}, request)
    db.commit()
    return {"revocation_status": cert.revocation_status,
            "revocation_checked_at": cert.revocation_checked_at,
            "revocation_detail": cert.revocation_detail}


@router.post("/revocation-run")
def revocation_run(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    """Tüm aktif leaf sertifikalar için iptal denetimini arka planda başlatır (gece işiyle aynı motor).
    Dış erişim gerektirir; kapalı ağda çoğu sonuç 'unknown' olur (beklenen)."""
    import threading
    threading.Thread(target=revocation.check_all_certificates, daemon=True).start()
    log_action(db, user.username, "revocation_run", "certificates", None, {"trigger": "manual"}, request)
    db.commit()
    return {"message": "İptal denetimi başlatıldı — sonuçlar sertifikalara işlenecek"}


@router.delete("/{cert_id}")
def delete_certificate(request: Request, cert_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_role("admin"))):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Sertifika bulunamadı")
    for child in cert.children:
        child.parent_id = None
    # Kendine referanslı halef bağını boşalt: bu cert'i "yerine geçen" gösteren kayıtlar
    # (MSSQL self-FK'de ON DELETE SET NULL'a izin vermez → DB boşaltmaz, elle yapılır)
    db.query(Certificate).filter(Certificate.superseded_by_id == cert.id).update(
        {Certificate.superseded_by_id: None}, synchronize_session=False)
    # İlgili devir önerilerini temizle (FK NO ACTION — hem SQLite hem MSSQL'de elle sil)
    db.query(TransferProposal).filter(
        (TransferProposal.old_cert_id == cert.id)
        | (TransferProposal.new_cert_id == cert.id)).delete(synchronize_session=False)
    log_action(db, user.username, "delete", "certificates", cert.id, {"name": cert.name}, request)
    db.delete(cert)
    db.commit()
    return {"ok": True}
