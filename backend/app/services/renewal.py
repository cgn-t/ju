"""Sertifika yenileme (rotation/renewal) çekirdeği.

Yeni bir sertifika envantere girdiğinde muhtemel ÖNCÜLLERİNİ (yerine geçtiği
kayıtları) bulur. Kimlik daima fingerprint'tir; SKI yalnız "aynı anahtar"
sinyalidir — aynı SKI'li yeni kayıt eklemek hiçbir zaman hata değildir, yalnızca
yenileme adayı üretir.

ONAY MODELİ (JUMBO yalnız ÖNERİR): Hiçbir devir kendiliğinden uygulanmaz. Her
devir yolu (import, manuel, vault-sync, import-chain, canlı doğrulama) yalnızca
`propose()` ile PENDING öneri(ler) üretir — hiçbir mutasyon yapmaz. Gerçek devir
(eşleme taşıma, mTLS bağımlılık taşıma, eskiyi pasife alma) YALNIZ `apply_proposal()`
içinde ve domain sahibi SY ekibinin (veya admin) onayından sonra gerçekleşir.
`apply_proposal` tüm mutasyonların TEK kapısıdır.
"""

from datetime import datetime
from app.core.timeutil import utcnow

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.certtype import cert_type_filter, normalize_cert_type
from app.db.models import (
    AppDependency,
    ApplicationTrustedCert,
    Certificate,
    CertificateDomainMap,
    Domain,
    TransferProposal,
)
from app.services import cert_parser
from app.services.audit import diff_fields, log_action


def find_predecessors(db: Session, *, cert_type: str, fingerprint_sha256: str | None,
                      subject_key_identifier: str | None, subject: str | None,
                      issuer: str | None, valid_from, exclude_id: int | None = None,
                      ) -> list[Certificate]:
    """Yeni (leaf) sertifikanın muhtemel öncüllerini döndürür (en olası önce).

    Sinyaller: aynı SKI (aynı anahtar yeniden sertifikalandı) VEYA aynı
    subject+issuer (tipik Vault re-issue: aynı CN, yeni anahtar). SAN kesişimi
    bilinçli olarak kullanılmaz — multi-SAN sertifikalarda yanlış pozitif üretir.
    Yön koruması: yalnız valid_from'u yeniden ESKİ kayıtlar aday olur (eski bir
    yedek dosyası import edildiğinde asıl kaydın pasife alınmasını önler).
    """
    # normalize: prod/legacy "Leaf"/" LEAF " gibi ham değerlerle de çalışsın (bkz. core/certtype)
    if normalize_cert_type(cert_type) != "leaf":
        return []
    signals = []
    if subject_key_identifier:
        signals.append(Certificate.subject_key_identifier == subject_key_identifier)
    if subject and issuer:
        signals.append((Certificate.subject == subject) & (Certificate.issuer == issuer))
    if not signals:
        return []
    signal_filter = signals[0]
    for s in signals[1:]:
        signal_filter = signal_filter | s
    q = (db.query(Certificate)
         .filter(cert_type_filter(Certificate.cert_type, "leaf"),
                 Certificate.is_active == True,
                 signal_filter))
    if fingerprint_sha256:
        q = q.filter(Certificate.fingerprint_sha256 != fingerprint_sha256)
    if valid_from is not None:
        q = q.filter(Certificate.valid_from < valid_from)
    if exclude_id is not None:
        q = q.filter(Certificate.id != exclude_id)
    return q.order_by(Certificate.valid_to.desc()).all()


def renewal_signal(old: Certificate, *, subject_key_identifier: str | None,
                   subject: str | None, issuer: str | None) -> str:
    """Öncül eşleşmesinin hangi sinyalden geldiğini raporlar (UI bilgisi)."""
    if subject_key_identifier and old.subject_key_identifier == subject_key_identifier:
        return "ski"
    if subject and issuer and old.subject == subject and old.issuer == issuer:
        return "subject"
    return "subject"


def _domain_sy_team_id(db: Session, domain_id: int | None) -> int | None:
    if domain_id is None:
        return None
    dom = db.get(Domain, domain_id)
    return dom.sy_team_id if dom else None


def _dep_sy_team_id(db: Session, dep: AppDependency) -> int | None:
    """mTLS bağımlılık devrini onaylayacak SY ekibi = ilgili uygulamanın SY ekibi."""
    return dep.app.sy_team_id if dep.app else None


def same_type(a: Certificate, b: Certificate) -> bool:
    """Devir yalnız AYNI seviyedeki sertifikalar arasında olabilir (leaf↔leaf,
    intermediate↔intermediate, root↔root). Ham CertType normalize edilerek karşılaştırılır."""
    return normalize_cert_type(a.cert_type) == normalize_cert_type(b.cert_type)


def _granule_proposal(db: Session, *, old_id, new_id, domain_id, mapping_type, dep_id,
                      app_id=None, statuses: tuple[str, ...], kind: str | None = None):
    """Aynı granül için verilen durumlardaki ilk öneriyi döndürür. app_id yalnız
    trusted_add önerilerinde doludur (grain'in bir boyutu). `kind` verilirse yalnız o
    türdeki öneriler sayılır (server_add / server_remove aynı granülü paylaşır)."""
    q = db.query(TransferProposal)
    if kind is not None:
        q = q.filter(TransferProposal.kind == kind)
    return (q
            .filter(TransferProposal.old_cert_id == old_id,
                    TransferProposal.new_cert_id == new_id,
                    TransferProposal.domain_id.is_(domain_id) if domain_id is None
                    else TransferProposal.domain_id == domain_id,
                    TransferProposal.mapping_type.is_(mapping_type) if mapping_type is None
                    else TransferProposal.mapping_type == mapping_type,
                    TransferProposal.app_dependency_id.is_(dep_id) if dep_id is None
                    else TransferProposal.app_dependency_id == dep_id,
                    TransferProposal.app_id.is_(app_id) if app_id is None
                    else TransferProposal.app_id == app_id,
                    TransferProposal.status.in_(statuses))
            .first())


def _open_proposal(db: Session, *, old_id, new_id, domain_id, mapping_type, dep_id, app_id=None):
    """Aynı granül için mevcut açık (pending/approved) öneriyi döndürür (idempotentlik)."""
    return _granule_proposal(db, old_id=old_id, new_id=new_id, domain_id=domain_id,
                             mapping_type=mapping_type, dep_id=dep_id, app_id=app_id,
                             statuses=("pending", "approved"))


def propose(db: Session, new_cert: Certificate, old_cert: Certificate, *, username: str,
            request: Request | None, via: str, signal: str | None = None,
            live_seen: bool = False, reopen_rejected: bool = False,
            domain_id: int | None = None, include_domains: bool = True,
            dep_ids: set[int] | None = None) -> list[TransferProposal]:
    """Eski cert'in her (domain, mapping_type) eşlemesi ve her mTLS bağımlılığı için
    PENDING değişiklik talebi üretir. HİÇBİR mutasyon yapmaz (eşleme taşımaz, pasife almaz,
    superseded_by yazmaz). İdempotent: aynı granül için açık öneri varsa yenisini
    yazmaz, yalnız live_seen kanıtını günceller. Commit çağırana aittir.

    RED KALICIDIR: SY ekibinin REDDETTİĞİ granül otomatik yollarla (import, vault-sync,
    live-check, backfill) yeniden önerilmez — aksi halde red kararı her restart/taramada
    hortlardı. Yalnız reopen_rejected=True (bilinçli MANUEL devir tetiği) reddi yeniden açar.

    KAPSAM: `domain_id` verilirse yalnız eski cert'in O domaindeki eşlemeleri için öneri
    üretilir (mTLS/trust store kapsam dışı) — canlı doğrulama ve zincir içe aktarma yalnız
    kendi domaini için kanıt taşır, eskinin diğer domainlerine YAYILMAZ (SSLVA vakası).
    Elle devir domain_id geçmez: bilinçli karar, tüm bağlantılara yayılır.

    TAKİPÇİLER: `include_domains=False` domain eşlemelerini atlar; `dep_ids` verilirse yalnız o
    mTLS bağımlılıkları önerilir (bkz. _propose_followers — domain devri uygulanınca).

    TİP: farklı seviyeler (root/intermediate/leaf) arasında değişiklik talebi ÜRETİLMEZ."""
    if new_cert.id == old_cert.id or not same_type(new_cert, old_cert):
        return []
    db.flush()  # autoflush=False: bekleyen kayıtlar aşağıdaki sorgularda görünsün
    created: list[TransferProposal] = []

    def upsert(*, domain_id, mapping_type, dep_id, team_id, app_id=None, kind="transfer"):
        existing = _open_proposal(db, old_id=old_cert.id, new_id=new_cert.id,
                                  domain_id=domain_id, mapping_type=mapping_type, dep_id=dep_id,
                                  app_id=app_id)
        if existing is not None:
            if live_seen and not existing.live_seen:
                existing.live_seen = True
                existing.live_seen_at = utcnow()
            return
        # Zaten UYGULANMIŞ granül yeniden önerilmez. transfer/dep'te apply kaynağı kopardığından
        # (eşleme taşınır, dep yeniye geçer) bu granül buraya hiç gelmez; ama trusted_add apply
        # eskiyi KORUDUĞUNDAN, her startup backfill'i aynı grain'i yeniden üretirdi — kısmi
        # uq_proposal_grain_open 'applied'ı saymaz, DB de engellemez → onay kuyruğunda phantom.
        # reopen_rejected'tan bağımsızdır: manuel supersede yalnız REDDİ açar, uygulananı değil.
        if _granule_proposal(db, old_id=old_cert.id, new_id=new_cert.id, domain_id=domain_id,
                             mapping_type=mapping_type, dep_id=dep_id, app_id=app_id,
                             statuses=("applied",)) is not None:
            return
        if not reopen_rejected and _granule_proposal(
                db, old_id=old_cert.id, new_id=new_cert.id, domain_id=domain_id,
                mapping_type=mapping_type, dep_id=dep_id, app_id=app_id,
                statuses=("rejected",)) is not None:
            return  # red kalıcı — otomatik yol bu granülü yeniden açamaz
        prop = TransferProposal(
            old_cert_id=old_cert.id, new_cert_id=new_cert.id, domain_id=domain_id,
            mapping_type=mapping_type, app_dependency_id=dep_id, app_id=app_id, kind=kind,
            sy_team_id=team_id, status="pending", signal=signal, via=via, live_seen=live_seen,
            live_seen_at=utcnow() if live_seen else None, created_by=username)
        db.add(prop)
        created.append(prop)

    for mapping in (list(old_cert.domain_mappings) if include_domains else []):
        if domain_id is not None and mapping.domain_id != domain_id:
            continue
        upsert(domain_id=mapping.domain_id, mapping_type=mapping.mapping_type, dep_id=None,
               team_id=_domain_sy_team_id(db, mapping.domain_id))

    if domain_id is not None:
        return _log_proposals(db, created, new_cert, old_cert, username=username, request=request,
                              via=via, live_seen=live_seen)

    for dep in db.query(AppDependency).filter(AppDependency.client_cert_id == old_cert.id).all():
        if dep_ids is not None and dep.id not in dep_ids:
            continue
        upsert(domain_id=None, mapping_type=None, dep_id=dep.id,
               team_id=_dep_sy_team_id(db, dep))

    # TRUSTED: eski cert bir uygulamanın trust store'undaysa DEVİR değil — yeni cert'i de
    # trust store'a EKLEME önerisi (kind=trusted_add). Onaylanınca eski trusted KALIR,
    # yeni trusted olarak eklenir (kullanıcı kararı: eski+yeni birlikte).
    for tr in (db.query(ApplicationTrustedCert)
               .filter(ApplicationTrustedCert.cert_id == old_cert.id).all()):
        app_row = tr.app
        if app_row is None:
            continue
        upsert(domain_id=None, mapping_type=None, dep_id=None, app_id=app_row.id,
               kind="trusted_add", team_id=app_row.sy_team_id)

    return _log_proposals(db, created, new_cert, old_cert, username=username, request=request,
                          via=via, live_seen=live_seen)


def _log_proposals(db: Session, created: list[TransferProposal], new_cert: Certificate,
                   old_cert: Certificate, *, username: str, request: Request | None, via: str,
                   live_seen: bool) -> list[TransferProposal]:
    db.flush()
    if created:
        domains = sorted({d.domain for d in (db.get(Domain, p.domain_id) for p in created
                                             if p.domain_id) if d is not None})
        log_action(db, username, "propose", "transfer_proposals", new_cert.id,
                   {"old_id": old_cert.id, "old_name": old_cert.name, "new_name": new_cert.name,
                    "count": len(created), "via": via, "live_seen": live_seen,
                    "domains": domains}, request)
    return created


def propose_server_mapping(db: Session, kind: str, cert: Certificate, domain: Domain, *,
                           username: str, request: Request | None, via: str,
                           live_seen: bool = False) -> TransferProposal | None:
    """Canlı doğrulamanın EKLEME / KALDIRMA önerisi (tek domain, 'server' eşlemesi).

    server_add: sertifika canlıda sunuluyor ama domaine bağlı değil → onayla eşleme eklenir.
    server_remove: sertifika bağlı ama canlıda artık sunulmuyor → onayla eşleme kaldırılır.
    Şema değişmeden (old/new NOT NULL) iki alana da AYNI sertifika yazılır; anlam `kind`'dadır.
    Açık öneri varsa yalnız live_seen güncellenir; REDDEDİLEN aynı tür granül yeniden açılmaz."""
    assert kind in ("server_add", "server_remove")
    if kind == "server_add" and not cert.is_active:
        return None  # pasif sertifika domaine bağlanamaz — ekleme önerisi de üretilmez
    db.flush()
    grain = dict(old_id=cert.id, new_id=cert.id, domain_id=domain.id, mapping_type="server",
                 dep_id=None)
    existing = _open_proposal(db, **grain)
    if existing is not None:
        if live_seen and not existing.live_seen:
            existing.live_seen = True
            existing.live_seen_at = utcnow()
        return None
    if _granule_proposal(db, **grain, statuses=("rejected",), kind=kind) is not None:
        return None
    prop = TransferProposal(
        old_cert_id=cert.id, new_cert_id=cert.id, domain_id=domain.id, mapping_type="server",
        kind=kind, sy_team_id=domain.sy_team_id, status="pending", via=via, live_seen=live_seen,
        live_seen_at=utcnow() if live_seen else None, created_by=username)
    db.add(prop)
    db.flush()
    log_action(db, username, "propose", "transfer_proposals", cert.id,
               {"kind": kind, "cert_id": cert.id, "cert_name": cert.name,
                "cert_type": normalize_cert_type(cert.cert_type), "domain": domain.domain,
                "via": via, "live_seen": live_seen}, request)
    return prop


def propose_date_fix(db: Session, cert: Certificate, domain: Domain, *, username: str,
                     request: Request | None, via: str) -> TransferProposal:
    """Canlı doğrulamanın TARİH GÜNCELLEME talebi: sunucudaki sertifika envanterdeki kayıtla
    AYNI (fingerprint eşit) ama kayıttaki başlangıç/bitiş tarihi sertifikanınkinden farklı
    (ör. eski uygulama kayda yeni sertifikanın PEM'ini yazıp tarihi güncellememiş).
    Onaylanınca tarihler PEM'den yeniden okunur (apply_proposal). Talep SERTİFİKA başınadır:
    sertifika çok domainde sunulsa da tek açık talep olur (ilk görüldüğü domainin SY'sine).
    Granül server_add/server_remove ile çakışmasın diye mapping_type boş bırakılır.
    Açık ya da REDDEDİLMİŞ tarih talebi varsa yenisi açılmaz, o talep döner."""
    db.flush()
    prior = (db.query(TransferProposal)
             .filter(TransferProposal.kind == "date_fix",
                     TransferProposal.old_cert_id == cert.id,
                     TransferProposal.status.in_(("pending", "approved", "rejected"))).first())
    if prior is not None:
        return prior
    prop = TransferProposal(
        old_cert_id=cert.id, new_cert_id=cert.id, domain_id=domain.id, mapping_type=None,
        kind="date_fix", sy_team_id=domain.sy_team_id, status="pending", via=via, live_seen=True,
        live_seen_at=utcnow(), created_by=username)
    db.add(prop)
    db.flush()
    log_action(db, username, "propose", "transfer_proposals", cert.id,
               {"kind": "date_fix", "cert_id": cert.id, "cert_name": cert.name,
                "domain": domain.domain, "via": via}, request)
    return prop


def propose_attach_transfer(db: Session, new_cert: Certificate, old_cert: Certificate,
                            domain: Domain, mapping_type: str, *, username: str,
                            request: Request | None, via: str = "attach",
                            live_seen: bool = False) -> TransferProposal | None:
    """Elle attach çakışması: bir domaine, aynı tipte zaten aktif başka bir sertifika
    eşliyken yeni eşleme eklenmek istenirse bu bir DEVİRDİR — doğrudan eklenmez, öneri olur.

    RED KALICI: bu granül daha önce REDDEDİLDİYSE None döner — attach çakışması ve
    import-chain fallback rutin yollardır, reddi yeniden açamazlar (yalnız bilinçli manuel
    supersede açar). Çağıranlar None'ı ele alır: import-chain sessizce atlar, attach ucu
    kullanıcıyı 409 ile bilgilendirir.

    Canlı doğrulama da bu yolu `via="live-check"` + live_seen ile kullanır (tek domain).
    TİP: çağıranlar çakışmayı aynı seviyede arar; farklı seviyeler yine de öneri üretmez."""
    if new_cert.id == old_cert.id or not same_type(new_cert, old_cert) or not new_cert.is_active:
        return None
    db.flush()
    existing = _open_proposal(db, old_id=old_cert.id, new_id=new_cert.id,
                              domain_id=domain.id, mapping_type=mapping_type, dep_id=None)
    if existing is not None:
        if live_seen and not existing.live_seen:
            existing.live_seen = True
            existing.live_seen_at = utcnow()
        return existing
    if _granule_proposal(db, old_id=old_cert.id, new_id=new_cert.id, domain_id=domain.id,
                         mapping_type=mapping_type, dep_id=None, statuses=("rejected",)) is not None:
        return None
    prop = TransferProposal(
        old_cert_id=old_cert.id, new_cert_id=new_cert.id, domain_id=domain.id,
        mapping_type=mapping_type, sy_team_id=domain.sy_team_id, status="pending",
        via=via, live_seen=live_seen, live_seen_at=utcnow() if live_seen else None,
        created_by=username)
    db.add(prop)
    db.flush()
    log_action(db, username, "propose", "transfer_proposals", new_cert.id,
               {"old_id": old_cert.id, "old_name": old_cert.name, "new_name": new_cert.name,
                "domain": domain.domain, "type": mapping_type, "via": via}, request)
    return prop


def apply_proposal(db: Session, prop: TransferProposal, username: str,
                   request: Request | None) -> None:
    """Devrin TEK mutasyon kapısı. Yalnız onaydan sonra çağrılır. İdempotent.
    Bir granülü (domain eşlemesi VEYA mTLS bağımlılığı) eskiden yeniye taşır,
    ardından eski cert'in tüm devri tamamlandıysa onu pasife alır."""
    if prop.status == "applied":
        return
    db.flush()
    new_cert = db.get(Certificate, prop.new_cert_id)
    old_cert = db.get(Certificate, prop.old_cert_id)
    if new_cert is None or old_cert is None:
        prop.status = "cancelled"
        return
    # Eski sürümlerden kalan farklı seviyeli (ör. root → leaf) devir onaylansa bile UYGULANMAZ.
    if prop.kind == "transfer" and not same_type(old_cert, new_cert):
        prop.status = "cancelled"
        prop.note = "Geçersiz: sertifika tipleri farklı — değişiklik uygulanmadı"
        return

    # İş kuralı: domaine bağlı sertifika pasif olamaz — öneri beklerken yeni sertifika pasife
    # alındıysa bağlama yapılmaz.
    if prop.kind != "server_remove" and not new_cert.is_active:
        prop.status = "cancelled"
        prop.note = "Geçersiz: sertifika pasif — pasif sertifika domaine bağlanamaz"
        return

    # EKLEME / KALDIRMA (canlı doğrulama): devir DEĞİL — tek domainde 'server' eşlemesi
    # eklenir ya da kaldırılır. superseded_by yazılmaz, sertifika pasife alınmaz.
    if prop.kind in ("server_add", "server_remove"):
        mapping = (db.query(CertificateDomainMap)
                   .filter_by(certificate_id=new_cert.id, domain_id=prop.domain_id,
                              mapping_type="server").first())
        if prop.kind == "server_add" and mapping is None and prop.domain_id is not None:
            db.add(CertificateDomainMap(certificate_id=new_cert.id, domain_id=prop.domain_id,
                                        mapping_type="server"))
        elif prop.kind == "server_remove" and mapping is not None:
            db.delete(mapping)
        prop.status = "applied"
        prop.applied_at = utcnow()
        db.flush()
        dom = db.get(Domain, prop.domain_id) if prop.domain_id else None
        log_action(db, username, f"{prop.kind}_apply", "certificate_domain_map", new_cert.id,
                   {"proposal_id": prop.id, "cert_name": new_cert.name,
                    "domain": dom.domain if dom else None, "mapping_type": "server"}, request)
        return

    # TARİH GÜNCELLEME: devir DEĞİL — kaydın başlangıç/bitiş tarihi PEM'den yeniden okunur.
    if prop.kind == "date_fix":
        dates = cert_parser.pem_dates(new_cert.pem_certificate)
        if dates is None:
            prop.status = "cancelled"
            prop.note = "Geçersiz: kayıtta okunabilir sertifika içeriği yok — tarih güncellenmedi"
            return
        diff = diff_fields(new_cert, {"valid_from": dates[0], "valid_to": dates[1]})
        new_cert.valid_from, new_cert.valid_to = dates
        prop.status = "applied"
        prop.applied_at = utcnow()
        db.flush()
        log_action(db, username, "date_fix_apply", "certificates", new_cert.id,
                   {"proposal_id": prop.id, "name": new_cert.name, "changes": diff}, request)
        return

    # TRUSTED EKLEME: devir DEĞİL — yeni cert'i uygulamanın trust store'una EKLE, eskiyi KORU
    # (superseded_by yazma, eşleme taşıma, pasife alma YOK). Eski + yeni birlikte trusted kalır.
    if prop.kind == "trusted_add":
        if prop.app_id is not None:
            exists = (db.query(ApplicationTrustedCert)
                      .filter(ApplicationTrustedCert.app_id == prop.app_id,
                              ApplicationTrustedCert.cert_id == new_cert.id).first())
            if exists is None:
                db.add(ApplicationTrustedCert(app_id=prop.app_id, cert_id=new_cert.id,
                                              note="yeni sertifika (değişiklik talebi onayı ile eklendi)"))
        prop.status = "applied"
        prop.applied_at = utcnow()
        db.flush()
        log_action(db, username, "trusted_add_apply", "app_trusted_certs", new_cert.id,
                   {"proposal_id": prop.id, "app_id": prop.app_id, "old_id": old_cert.id,
                    "new_name": new_cert.name}, request)
        return  # eski trusted KORUNUR — _maybe_deactivate_old çağrılmaz

    moved = False  # domain yuvası fiilen yeni cert'e geçti mi (takipçi önerileri için)
    if prop.app_dependency_id is not None:
        dep = db.get(AppDependency, prop.app_dependency_id)
        if dep is not None and dep.client_cert_id == old_cert.id:
            dep.client_cert_id = new_cert.id
    elif prop.domain_id is not None:
        old_map = db.query(CertificateDomainMap).filter_by(
            certificate_id=old_cert.id, domain_id=prop.domain_id,
            mapping_type=prop.mapping_type).first()
        target = db.query(CertificateDomainMap).filter_by(
            certificate_id=new_cert.id, domain_id=prop.domain_id,
            mapping_type=prop.mapping_type).first()
        if target is not None:
            moved = True
            if old_map is not None:
                db.delete(old_map)  # yeni zaten eşli — eskiyi kaldır (uq koruması)
        elif old_map is not None:
            old_map.certificate_id = new_cert.id
            moved = True
        else:
            # Eski eşleme yok. İki alt-durum: (a) attach-çakışması sonrası eski ELLE kaldırıldı
            # ve yuva BOŞ → yeniyi doğrudan ekle; (b) RAKİP bir halef önerisi eskinin eşlemesini
            # başka bir halefe ZATEN taşıdı ve yuva DOLU. (b)'de körlemesine eklemek domaine
            # İKİNCİ bir aktif server cert yapıştırır (tek-aktif-server invariant'ı; DB yakalamaz,
            # çünkü uq (cert,domain,tip) üzerinde). Yalnız yuva gerçekten boşsa ekle; doluysa bu
            # devir amaçsızdır (rakip halef yuvayı çoktan doldurmuş) → no-op.
            # Yuva TİP bazındadır: 'server' eşlemesi zinciri (intermediate/root) de taşıdığından
            # tip süzgeci olmadan domaindeki intermediate/root yuvayı "dolu" gösterir ve eski leaf
            # elle kaldırılmışsa yeni leaf HİÇ bağlanmaz (domain leaf'siz kalırdı).
            occupant = (db.query(CertificateDomainMap)
                        .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
                        .filter(CertificateDomainMap.domain_id == prop.domain_id,
                                CertificateDomainMap.mapping_type == prop.mapping_type,
                                cert_type_filter(Certificate.cert_type,
                                                 normalize_cert_type(new_cert.cert_type)))
                        .first())
            if occupant is None:
                db.add(CertificateDomainMap(certificate_id=new_cert.id, domain_id=prop.domain_id,
                                            mapping_type=prop.mapping_type))
                moved = True

    # Halef işareti: İLK halefi kaydet, sonraki (farklı domain → farklı halef) onaylar EZMESİN.
    # Tek FK dallanmayı temsil edemez (bir cert farklı domainlerde farklı haleflere geçebilir);
    # ilk kaydı stabil tut, gerçek/tam zincir supersede_apply audit kayıtlarında kalır.
    if old_cert.superseded_by_id is None:
        old_cert.superseded_by_id = new_cert.id
    # vault_path devri superseded_by'dan BAĞIMSIZ: yol, eski hangisinde hâlâ duruyorsa o onayda
    # taşınır; taşındıktan sonra old.vault_path None olur → ikinci kez çalışmaz (davranış korunur).
    if old_cert.vault_path:
        if not new_cert.vault_path:
            new_cert.vault_path = old_cert.vault_path
            old_cert.vault_path = None
        elif new_cert.vault_path == old_cert.vault_path:
            old_cert.vault_path = None

    prop.status = "applied"
    prop.applied_at = utcnow()
    db.flush()
    log_action(db, username, "supersede_apply", "certificates", new_cert.id,
               {"proposal_id": prop.id, "old_id": old_cert.id, "old_name": old_cert.name,
                "new_name": new_cert.name, "domain_id": prop.domain_id,
                "domain": dom.domain if (dom := db.get(Domain, prop.domain_id) if prop.domain_id else None) else None,
                "mapping_type": prop.mapping_type, "dep_id": prop.app_dependency_id}, request)
    if moved:
        _propose_followers(db, new_cert, old_cert, prop, username=username, request=request)
    _maybe_deactivate_old(db, old_cert)


def _propose_followers(db: Session, new_cert: Certificate, old_cert: Certificate,
                       prop: TransferProposal, *, username: str, request: Request | None) -> None:
    """Domain kapsamlı bir devir UYGULANDIĞINDA eski cert'e bağlı mTLS bağımlılıkları ve trust
    store kayıtları geride kalmasın. Canlı doğrulama / zincir içe aktarma / attach çakışması
    yalnız o domaini önerir; o domainin server sertifikası fiilen değiştiğinde:
      • bu domaini hedefleyen ve hâlâ eski cert'i izleyen mTLS bağımlılıkları → değişiklik talebi
        (uygulama sahibi SY onayı),
      • eski cert'i trust store'unda tutan uygulamalar → trusted_add önerisi.
    Öneri yine ONAY bekler (mutasyon yok); idempotent ve red kalıcı (propose ile aynı kurallar).
    Bekleyen bu öneriler eski cert'in pasife alınmasını haklı olarak erteler."""
    deps = []
    if prop.mapping_type == "server":
        deps = (db.query(AppDependency)
                .filter(AppDependency.client_cert_id == old_cert.id,
                        AppDependency.target_domain_id == prop.domain_id).all())
    trusted = (db.query(ApplicationTrustedCert)
               .filter(ApplicationTrustedCert.cert_id == old_cert.id).all())
    if not deps and not trusted:
        return
    propose(db, new_cert, old_cert, username=username, request=request, via=prop.via or "attach",
            signal=prop.signal, live_seen=bool(prop.live_seen), include_domains=False,
            dep_ids={d.id for d in deps})


def _maybe_deactivate_old(db: Session, old_cert: Certificate) -> None:
    """Eski cert, kendisine ait tüm değişiklik talepleri sonuçlandıysa (açık pending/approved
    kalmadıysa) VE üstünde artık aktif eşleme/mTLS bağı kalmadıysa pasife alınır.
    Bir domain reddedilirse eski o domain için aktif kalır — kısmi devir doğru yönetilir."""
    db.flush()
    open_count = (db.query(TransferProposal)
                  .filter(TransferProposal.old_cert_id == old_cert.id,
                          TransferProposal.kind != "date_fix",  # tarih talebi devir değildir
                          TransferProposal.status.in_(("pending", "approved"))).count())
    if open_count > 0:
        return
    has_mappings = db.query(CertificateDomainMap).filter_by(
        certificate_id=old_cert.id).first() is not None
    has_deps = db.query(AppDependency).filter(
        AppDependency.client_cert_id == old_cert.id).first() is not None
    # Eski cert hâlâ bir uygulamanın trust store'undaysa PASİFE ALINMAZ — trusted sertifika
    # devredilmez; eski + yeni birlikte güvenilir kalabilir (trusted_add akışı).
    has_trusted = db.query(ApplicationTrustedCert).filter(
        ApplicationTrustedCert.cert_id == old_cert.id).first() is not None
    if not has_mappings and not has_deps and not has_trusted:
        old_cert.is_active = False
