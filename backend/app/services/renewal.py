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
from app.services.audit import log_action


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


def _granule_proposal(db: Session, *, old_id, new_id, domain_id, mapping_type, dep_id,
                      app_id=None, statuses: tuple[str, ...]):
    """Aynı granül için verilen durumlardaki ilk öneriyi döndürür. app_id yalnız
    trusted_add önerilerinde doludur (grain'in bir boyutu)."""
    return (db.query(TransferProposal)
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
            live_seen: bool = False, reopen_rejected: bool = False) -> list[TransferProposal]:
    """Eski cert'in her (domain, mapping_type) eşlemesi ve her mTLS bağımlılığı için
    PENDING devir önerisi üretir. HİÇBİR mutasyon yapmaz (eşleme taşımaz, pasife almaz,
    superseded_by yazmaz). İdempotent: aynı granül için açık öneri varsa yenisini
    yazmaz, yalnız live_seen kanıtını günceller. Commit çağırana aittir.

    RED KALICIDIR: SY ekibinin REDDETTİĞİ granül otomatik yollarla (import, vault-sync,
    live-check, backfill) yeniden önerilmez — aksi halde red kararı her restart/taramada
    hortlardı. Yalnız reopen_rejected=True (bilinçli MANUEL devir tetiği) reddi yeniden açar."""
    if new_cert.id == old_cert.id:
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

    for mapping in list(old_cert.domain_mappings):
        upsert(domain_id=mapping.domain_id, mapping_type=mapping.mapping_type, dep_id=None,
               team_id=_domain_sy_team_id(db, mapping.domain_id))

    for dep in db.query(AppDependency).filter(AppDependency.client_cert_id == old_cert.id).all():
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

    db.flush()
    if created:
        log_action(db, username, "propose", "transfer_proposals", new_cert.id,
                   {"old_id": old_cert.id, "old_name": old_cert.name, "new_name": new_cert.name,
                    "count": len(created), "via": via, "live_seen": live_seen}, request)
    return created


def propose_attach_transfer(db: Session, new_cert: Certificate, old_cert: Certificate,
                            domain: Domain, mapping_type: str, *, username: str,
                            request: Request | None) -> TransferProposal | None:
    """Elle attach çakışması: bir domaine, aynı tipte zaten aktif başka bir sertifika
    eşliyken yeni eşleme eklenmek istenirse bu bir DEVİRDİR — doğrudan eklenmez, öneri olur.

    RED KALICI: bu granül daha önce REDDEDİLDİYSE None döner — attach çakışması ve
    import-chain fallback rutin yollardır, reddi yeniden açamazlar (yalnız bilinçli manuel
    supersede açar). Çağıranlar None'ı ele alır: import-chain sessizce atlar, attach ucu
    kullanıcıyı 409 ile bilgilendirir."""
    db.flush()
    existing = _open_proposal(db, old_id=old_cert.id, new_id=new_cert.id,
                              domain_id=domain.id, mapping_type=mapping_type, dep_id=None)
    if existing is not None:
        return existing
    if _granule_proposal(db, old_id=old_cert.id, new_id=new_cert.id, domain_id=domain.id,
                         mapping_type=mapping_type, dep_id=None, statuses=("rejected",)) is not None:
        return None
    prop = TransferProposal(
        old_cert_id=old_cert.id, new_cert_id=new_cert.id, domain_id=domain.id,
        mapping_type=mapping_type, sy_team_id=domain.sy_team_id, status="pending",
        via="attach", created_by=username)
    db.add(prop)
    db.flush()
    log_action(db, username, "propose", "transfer_proposals", new_cert.id,
               {"old_id": old_cert.id, "old_name": old_cert.name, "new_name": new_cert.name,
                "domain": domain.domain, "type": mapping_type, "via": "attach"}, request)
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

    # TRUSTED EKLEME: devir DEĞİL — yeni cert'i uygulamanın trust store'una EKLE, eskiyi KORU
    # (superseded_by yazma, eşleme taşıma, pasife alma YOK). Eski + yeni birlikte trusted kalır.
    if prop.kind == "trusted_add":
        if prop.app_id is not None:
            exists = (db.query(ApplicationTrustedCert)
                      .filter(ApplicationTrustedCert.app_id == prop.app_id,
                              ApplicationTrustedCert.cert_id == new_cert.id).first())
            if exists is None:
                db.add(ApplicationTrustedCert(app_id=prop.app_id, cert_id=new_cert.id,
                                              note="halef sertifika (devir önerisi onayı ile eklendi)"))
        prop.status = "applied"
        prop.applied_at = utcnow()
        db.flush()
        log_action(db, username, "trusted_add_apply", "app_trusted_certs", new_cert.id,
                   {"proposal_id": prop.id, "app_id": prop.app_id, "old_id": old_cert.id,
                    "new_name": new_cert.name}, request)
        return  # eski trusted KORUNUR — _maybe_deactivate_old çağrılmaz

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
            if old_map is not None:
                db.delete(old_map)  # yeni zaten eşli — eskiyi kaldır (uq koruması)
        elif old_map is not None:
            old_map.certificate_id = new_cert.id
        else:
            # Eski eşleme yok. İki alt-durum: (a) attach-çakışması sonrası eski ELLE kaldırıldı
            # ve yuva BOŞ → yeniyi doğrudan ekle; (b) RAKİP bir halef önerisi eskinin eşlemesini
            # başka bir halefe ZATEN taşıdı ve yuva DOLU. (b)'de körlemesine eklemek domaine
            # İKİNCİ bir aktif server cert yapıştırır (tek-aktif-server invariant'ı; DB yakalamaz,
            # çünkü uq (cert,domain,tip) üzerinde). Yalnız yuva gerçekten boşsa ekle; doluysa bu
            # devir amaçsızdır (rakip halef yuvayı çoktan doldurmuş) → no-op.
            occupant = (db.query(CertificateDomainMap)
                        .filter_by(domain_id=prop.domain_id, mapping_type=prop.mapping_type)
                        .first())
            if occupant is None:
                db.add(CertificateDomainMap(certificate_id=new_cert.id, domain_id=prop.domain_id,
                                            mapping_type=prop.mapping_type))

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
                "mapping_type": prop.mapping_type, "dep_id": prop.app_dependency_id}, request)
    _maybe_deactivate_old(db, old_cert)


def _maybe_deactivate_old(db: Session, old_cert: Certificate) -> None:
    """Eski cert, kendisine ait tüm devir önerileri sonuçlandıysa (açık pending/approved
    kalmadıysa) VE üstünde artık aktif eşleme/mTLS bağı kalmadıysa pasife alınır.
    Bir domain reddedilirse eski o domain için aktif kalır — kısmi devir doğru yönetilir."""
    db.flush()
    open_count = (db.query(TransferProposal)
                  .filter(TransferProposal.old_cert_id == old_cert.id,
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
