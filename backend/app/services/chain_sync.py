"""Sunulan bir TLS zincirini (leaf→root) envantere işleyip domain'in 'server' eşlemesini
HER cert_type için ayrı ayrı senkronize eder.

import_chain (manuel/otomatik import) ve live_check (günlük canlı tarama) AYNI mantığı
kullanır — biri zinciri kendi çeker, diğeri zaten çektiği zinciri yeniden kullanır (ikinci
bir TLS bağlantısı açmadan). Her cert_type (root/intermediate/leaf) BAĞIMSIZ ele alınır:
domainde o tipten zaten aktif başka bir 'server' sertifikası varsa devir önerisi üretilir
(propose_attach_transfer); yoksa doğrudan bağlanır (ilk kurulum, devir değil).

Aynı zincirde AYNI tipten birden fazla sertifika olabilir (ör. gerçek 2 katmanlı ara-CA
hiyerarşisi, ya da eski istemcilerle uyum için sunulan çapraz-imzalı bir "root" kopyası —
CN'i "Root" dese de kendi kendini imzalamadığından 'intermediate' sayılır). Bu yüzden tip
başına TEK satır değil, LİSTE tutulur; çakışma kontrolünde de aynı zincirin üyeleri
birbirine rakip sayılmaz (yalnız bu zincirin DIŞINDA kalan, önceden bağlı bir sertifika
gerçek bir rotasyon/çakışma adayıdır).
"""

from dataclasses import dataclass, field

from cryptography import x509
from fastapi import Request
from sqlalchemy.orm import Session

from app.core.certtype import cert_type_filter, normalize_cert_type
from app.db.models import Certificate, CertificateDomainMap, Domain
from app.services import cert_parser, renewal
from app.services.audit import log_action


@dataclass
class ChainSyncResult:
    created: list[str] = field(default_factory=list)       # yeni eklenen sertifika adları
    existing: list[str] = field(default_factory=list)      # zaten kayıtlı olanlar
    mapped: dict[str, str] = field(default_factory=dict)   # cert_type -> doğrudan bağlanan sertifika adı (son işlenen)
    superseded: list[str] = field(default_factory=list)    # devir ÖNERİSİ üretilen öncül adları
    rows: list[Certificate] = field(default_factory=list)  # zincirde işlenen TÜM satırlar (aynı tipten birden fazla olabilir)

    @property
    def leaf_row(self) -> Certificate | None:
        return next((r for r in self.rows if normalize_cert_type(r.cert_type) == "leaf"), None)


def sync_domain_chain_certs(db: Session, domain: Domain, served_chain: list[x509.Certificate], *,
                            username: str, request: Request | None, via: str,
                            environment: str | None = None) -> ChainSyncResult:
    """`environment` (prod|test, opsiyonel): yalnız bu çağrıda YENİ oluşturulan sertifikalara
    uygulanır — envanterde zaten var olan (find_existing ile bulunan) kayıtların ortamı
    ASLA değiştirilmez. Otomatik yollar (live-check) bunu geçmez; yalnız bir insanın
    tetiklediği import-chain isteğinde doldurulur."""
    result = ChainSyncResult()
    parsed_list = [cert_parser.parse_x509(c) for c in served_chain]
    # Önce CA'lar eklensin ki leaf parent bulabilsin
    parsed_list.sort(key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type])

    for parsed in parsed_list:
        row = cert_parser.find_existing(db, parsed)
        if row is not None:
            result.existing.append(row.name)
        else:
            row = Certificate(**parsed.__dict__, creator=username, source="live",
                              environment=environment)
            row.parent_id = cert_parser.resolve_parent(db, parsed)
            db.add(row)
            db.flush()
            cert_parser.relink_children(db, row)
            log_action(db, username, "import", "certificates", row.id,
                       {"name": row.name, "via": f"{via} {domain.domain}"}, request)
            result.created.append(row.name)
        result.rows.append(row)

    # Bu zincirin TÜM üyeleri birbirinin çakışma adayı DEĞİLDİR — yalnız bu listenin
    # dışında kalan (önceden, başka bir zincirden bağlanmış) aynı tipteki sertifikalar
    # gerçek bir rotasyon/çakışma sayılır.
    chain_ids = {r.id for r in result.rows}

    for row in result.rows:
        cert_type = normalize_cert_type(row.cert_type)
        already = db.query(CertificateDomainMap).filter_by(
            certificate_id=row.id, domain_id=domain.id, mapping_type="server").first()
        existing_servers = (
            db.query(CertificateDomainMap)
            .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
            .filter(CertificateDomainMap.domain_id == domain.id,
                    CertificateDomainMap.mapping_type == "server",
                    CertificateDomainMap.certificate_id.notin_(chain_ids),
                    cert_type_filter(Certificate.cert_type, cert_type),
                    Certificate.is_active == True).all())
        for m in existing_servers:
            p = renewal.propose_attach_transfer(db, row, m.certificate, domain, "server",
                                                username=username, request=request)
            if p is not None:
                result.superseded.append(m.certificate.name)
        if already is None and not existing_servers:
            db.add(CertificateDomainMap(certificate_id=row.id, domain_id=domain.id,
                                        mapping_type="server"))
            log_action(db, username, "create", "certificate_domain_map", None,
                       {"domain": domain.domain, "cert": row.name, "type": "server",
                        "via": via}, request)
            result.mapped[cert_type] = row.name
    return result
