"""Otomatik CA sertifika alımı (issuance) — durum makinesi.

TransferProposal'a KASITLI OLARAK dokunulmaz: o iki VAR OLAN sertifika arasındaki tek-mutasyonluk
devri modelliyor; issuance ise sertifika DOĞMADAN önce başlayan, dış CA'ya bağlı çok adımlı bir akış.
Onay UX'i (proposals.py'deki atomik CAS deseni) `app/api/issuance.py`'de KOPYALANIR.

Üç aşama:
  - create_request(): CA'ya HİÇBİR ÇAĞRI yapmaz; yalnız isteği açar. zero_touch, domain'in o anki
    issuance_zero_touch değerinin SNAPSHOT'ıdır — sonradan domain ayarı değişse bile bu isteğin
    semantiği bozulmaz.
  - execute_request(): TEK CA-çağıran kapı (renewal.apply_proposal'ın "tek mutasyon kapısı"
    felsefesiyle birebir), yalnız status=='approved' iken çalışır. Scheduler job'undan
    (notifier.run_pending_issuance) çağrılır — senkron API isteği thread'inde ASLA (CA gecikmesi
    isteği bloklamasın).
  - finalize_issued(): başarılı CA yanıtını MEVCUT import hattına besler (cert_parser.find_existing/
    resolve_parent/relink_children + renewal.find_predecessors/propose) — domains.py::import_chain
    ile AYNI desen, yeni eşleştirme mantığı YAZMAZ.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.db.models import Certificate, CertificateDomainMap, Domain, IssuanceProfile, IssuanceRequest
from app.services import cert_parser, renewal
from app.services.audit import log_action
from app.services.providers.vault import VaultProvider
from app.services.settings_service import get_category

logger = logging.getLogger(__name__)

# Bir domain için AÇIK sayılan durumlar — scan_expiring_for_issuance dedup'ı bunları kullanır
# (renewal._open_proposal ile aynı "idempotentlik" felsefesi: açık istek varken ikincisi açılmaz).
OPEN_STATUSES = ("pending_approval", "approved", "submitted", "polling")


def _domain_common_name_sans(domain: Domain) -> tuple[str, list[str]]:
    """Talebin CN/SAN'ı — bugün yalnız domainin kendi adı (çoklu-SAN genişletmesi ileride eklenebilir)."""
    return domain.domain, [domain.domain]


def _cn_matches(requested_cn: str, parsed: cert_parser.ParsedCertificate) -> bool:
    """CA'nın döndürdüğü leaf'in kimliği istekle eşleşiyor mu? san ', ' ile ayrılmış DNS/IP
    listesidir (bkz. cert_parser.parse_x509) — tam eşleşme aranır, substring KULLANILMAZ."""
    if parsed.name == requested_cn:
        return True
    sans = [s.strip() for s in (parsed.san or "").split(",")]
    return requested_cn in sans


def _fail(db: Session, req: IssuanceRequest, message: str) -> None:
    """Ortak başarısızlık kapısı: durumu yazar + ŞEFFAFLIK gereği bildirimi HER ZAMAN tetikler
    (zero-touch/onay-kapılı fark etmez — bir yenilemenin sessizce başarısız kalması en kötü senaryo)."""
    req.status = "failed"
    req.last_error = message
    req.finished_at = utcnow()
    from app.services.notifier import notify_issuance_event
    notify_issuance_event(db, req, "failed")


def has_open_request(db: Session, domain_id: int) -> bool:
    return (db.query(IssuanceRequest)
            .filter(IssuanceRequest.domain_id == domain_id,
                    IssuanceRequest.status.in_(OPEN_STATUSES)).first() is not None)


def create_request(db: Session, domain: Domain, profile: IssuanceProfile, *, username: str,
                   trigger: str) -> IssuanceRequest:
    """Yeni bir issuance isteği açar. CA'ya HİÇBİR ÇAĞRI yapılmaz — yalnız durum yazılır."""
    common_name, sans = _domain_common_name_sans(domain)
    zero_touch = bool(domain.issuance_zero_touch)
    method = "csr_sign" if profile.ca_type == "vault_pki" else "acme"
    req = IssuanceRequest(
        domain_id=domain.id, profile_id=profile.id, sy_team_id=domain.sy_team_id,
        status="approved" if zero_touch else "pending_approval",
        method=method, common_name=common_name, sans=json.dumps(sans, ensure_ascii=False),
        trigger=trigger, zero_touch=zero_touch, created_by=username,
        decided_by=username if zero_touch else None, decided_at=utcnow() if zero_touch else None,
    )
    db.add(req)
    db.flush()
    log_action(db, username, "issuance_request_create", "issuance_requests", req.id,
              {"domain": domain.domain, "profile": profile.name, "trigger": trigger,
               "zero_touch": zero_touch})
    from app.services.notifier import notify_issuance_event
    notify_issuance_event(db, req, "created")
    return req


def submit_csr(db: Session, req: IssuanceRequest, csr_pem: str, *, username: str) -> None:
    """Hedef sunucu/Ansible tarafında üretilen CSR'ı isteğe iliştirir. CSR bir PEM metin bloğudur
    (CN/SAN + talep edenin PUBLIC key'i) — private key İÇERMEZ, bu yüzden burada durması custody
    ilkesini bozmaz."""
    if req.status not in ("pending_approval", "approved"):
        raise ValueError("CSR yalnız onay bekleyen/onaylanmış bir isteğe eklenebilir")
    req.csr_pem = csr_pem
    db.flush()
    log_action(db, username, "issuance_csr_submit", "issuance_requests", req.id)


def execute_request(db: Session, req: IssuanceRequest) -> None:
    """TEK CA-çağıran kapı. Yalnız status=='approved' iken ilerler; idempotent (approved olmayan
    isteklerde no-op)."""
    if req.status != "approved":
        return
    if not get_category(db, "issuance", mask_secrets=False).get("enabled"):
        return  # global kill-switch kapalı — isteğe DOKUNMAZ (approved kalır, açılınca devam eder)
    profile = db.get(IssuanceProfile, req.profile_id)
    if profile is None or not profile.enabled:
        _fail(db, req, "CA profili bulunamadı veya kapalı")
        return
    if profile.ca_type != "vault_pki":
        return  # ACME (Faz C): poll_acme_orders devralır, burada dokunulmaz
    if req.method == "csr_sign" and not req.csr_pem:
        return  # CSR henüz gelmedi — sonraki turda yeniden denenir

    req.attempt_count = (req.attempt_count or 0) + 1
    req.submitted_at = utcnow()
    try:
        provider = VaultProvider(db)
        sans = json.loads(req.sans or "[]")
        if req.method == "issue":
            if not profile.allow_key_return:
                raise ValueError("Bu profilde issue() (anahtar dönen mod) kapalı")
            issued = provider.issue(req.common_name, sans, req.requested_ttl_hours,
                                    mount=profile.vault_mount, role=profile.vault_role)
        else:
            issued = provider.sign_csr(req.csr_pem, req.common_name, sans, req.requested_ttl_hours,
                                       mount=profile.vault_mount, role=profile.vault_role)
    except Exception as exc:  # noqa: BLE001 — CA/ağ hatası: isteği failed işaretle, çökme yok
        logger.warning("Issuance CA çağrısı başarısız (request=%s): %s", req.id, exc)
        _fail(db, req, str(exc)[:1000])
        return
    # allow_key_return=True olsa bile private_key_pem burada KULLANILMAZ/SAKLANMAZ — yalnız
    # pem_certificate/ca_chain_pem finalize_issued'e geçer, private_key GC'ye düşer.
    finalize_issued(db, req, issued.pem_certificate, issued.ca_chain_pem,
                    username="system:issuance")


def finalize_issued(db: Session, req: IssuanceRequest, pem_certificate: str,
                    ca_chain_pem: str | None, *, username: str) -> None:
    """Başarılı CA yanıtını MEVCUT import hattına besler — yeni eşleştirme mantığı YAZMAZ."""
    domain = db.get(Domain, req.domain_id)
    full_pem = pem_certificate + ("\n" + ca_chain_pem if ca_chain_pem else "")
    try:
        parsed_list = cert_parser.parse_pem_text(full_pem)
    except Exception as exc:  # noqa: BLE001
        _fail(db, req, f"CA yanıtı parse edilemedi: {exc}")
        return

    leaf_parsed = next((p for p in parsed_list if p.cert_type == "leaf"), None)
    if leaf_parsed is None or not _cn_matches(req.common_name, leaf_parsed):
        # SONUÇ DOĞRULAMA: CA yanıtı beklenenden farklıysa (yanlış profil/hatalı yönlendirme
        # ihtimaline karşı) sessizce envantere GİRMEZ.
        _fail(db, req, "CA yanıtındaki sertifika istekle eşleşmiyor (CN/SAN doğrulaması başarısız)")
        return

    order = {"root": 0, "intermediate": 1, "leaf": 2}
    parsed_list.sort(key=lambda p: order.get(p.cert_type, 1))  # CA'lar önce → leaf parent bulabilsin

    leaf_row: Certificate | None = None
    for parsed in parsed_list:
        existing = cert_parser.find_existing(db, parsed)
        if existing is not None:
            row = existing
        else:
            row = Certificate(**parsed.__dict__, creator=req.created_by or "system",
                              source="issuance")
            row.parent_id = cert_parser.resolve_parent(db, parsed)
            db.add(row)
            db.flush()
            cert_parser.relink_children(db, row)
            log_action(db, username, "import", "certificates", row.id,
                      {"name": row.name, "via": f"issuance request #{req.id}"})
        if parsed.cert_type == "leaf":
            leaf_row = row
    db.flush()

    if leaf_row is None or domain is None:
        _fail(db, req, "Leaf sertifika/domain bulunamadı")
        return

    req.result_cert_id = leaf_row.id
    req.status = "issued"
    req.finished_at = utcnow()

    already = (db.query(CertificateDomainMap)
              .filter_by(certificate_id=leaf_row.id, domain_id=domain.id, mapping_type="server")
              .first())
    predecessors = renewal.find_predecessors(
        db, cert_type=leaf_row.cert_type, fingerprint_sha256=leaf_row.fingerprint_sha256,
        subject_key_identifier=leaf_row.subject_key_identifier, subject=leaf_row.subject,
        issuer=leaf_row.issuer, valid_from=leaf_row.valid_from, exclude_id=leaf_row.id)
    proposals = []
    for old in predecessors:
        made = renewal.propose(
            db, leaf_row, old, username=username, request=None, via="issuance", live_seen=False,
            signal=renewal.renewal_signal(old, subject_key_identifier=leaf_row.subject_key_identifier,
                                          subject=leaf_row.subject, issuer=leaf_row.issuer))
        proposals.extend(made)
    if already is None and not predecessors:
        db.add(CertificateDomainMap(certificate_id=leaf_row.id, domain_id=domain.id,
                                    mapping_type="server"))

    log_action(db, username, "issuance_finalize", "issuance_requests", req.id,
              {"cert_id": leaf_row.id, "cert_name": leaf_row.name, "domain": domain.domain,
               "proposal_count": len(proposals)})

    # ZERO-TOUCH ikinci katman: sonucun eşlemeye uygulanması da onaysız geçer (audit+bildirim
    # yine de zorunlu — engelleyici değil ama görünür).
    if req.zero_touch:
        for prop in proposals:
            renewal.apply_proposal(db, prop, "system:zero-touch", None)

    from app.services.notifier import notify_issuance_event
    notify_issuance_event(db, req, "issued")
