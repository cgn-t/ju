"""Sunulan bir TLS zincirini (leaf→root) envantere işleyip domain'in 'server' eşlemesini
HER cert_type için ayrı ayrı senkronize eder.

import_chain (manuel/otomatik import) ve live_check (günlük canlı tarama) AYNI mantığı
kullanır — biri zinciri kendi çeker, diğeri zaten çektiği zinciri yeniden kullanır (ikinci
bir TLS bağlantısı açmadan). Her cert_type (root/intermediate/leaf) BAĞIMSIZ ele alınır:
YALNIZ bu domain ele alınır — öneri eski sertifikanın diğer domainlerine yayılmaz.

  • import_chain (live=False, insan tetikli): bağlı olmayan seviye doğrudan bağlanır (ilk
    kurulum); seviyede zincir dışı bağlı sertifika varsa canlı doğrulamayla aynı kuralla
    DEĞİŞİKLİK (tek halef) / EKLEME / KALDIRMA önerisi üretilir.
  • live_check (live=True): hiçbir eşleme kendiliğinden değişmez; her seviye için EKLEME /
    DEĞİŞİKLİK (devir) / KALDIRMA önerisi üretilir. Root sunulmadığında envanterdeki üst
    sertifikadan türetilir; türetilen root için kaldırma önerisi üretilmez.

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

from app.core.certtype import normalize_cert_type
from app.db.models import Certificate, CertificateDomainMap, Domain
from app.services import cert_parser, renewal
from app.services.audit import log_action


@dataclass
class ChainSyncResult:
    created: list[str] = field(default_factory=list)       # yeni eklenen sertifika adları
    existing: list[str] = field(default_factory=list)      # zaten kayıtlı olanlar
    mapped: dict[str, str] = field(default_factory=dict)   # cert_type -> doğrudan bağlanan sertifika adı (son işlenen)
    superseded: list[str] = field(default_factory=list)    # devir ÖNERİSİ üretilen öncül adları
    added: list[str] = field(default_factory=list)         # EKLEME önerisi üretilenler (canlı)
    removed: list[str] = field(default_factory=list)       # KALDIRMA önerisi üretilenler (canlı)
    inactive: list[str] = field(default_factory=list)      # sunulan ama envanterde PASİF olanlar — bağlanmaz
    rows: list[Certificate] = field(default_factory=list)  # zincirde işlenen TÜM satırlar (aynı tipten birden fazla olabilir)

    @property
    def leaf_row(self) -> Certificate | None:
        return next((r for r in self.rows if normalize_cert_type(r.cert_type) == "leaf"), None)


def sync_domain_chain_certs(db: Session, domain: Domain, served_chain: list[x509.Certificate], *,
                            username: str, request: Request | None, via: str,
                            environment: str | None = None, live: bool = False) -> ChainSyncResult:
    """`environment` (prod|test, opsiyonel): yalnız bu çağrıda YENİ oluşturulan sertifikalara
    uygulanır — envanterde zaten var olan (find_existing ile bulunan) kayıtların ortamı
    ASLA değiştirilmez. Otomatik yollar (live-check) bunu geçmez; yalnız bir insanın
    tetiklediği import-chain isteğinde doldurulur."""
    result = ChainSyncResult()
    # "Oluşturan" alanı dosyadan içe aktarmadaki gibi ekip adıdır: domainin SY ekibi; ekip
    # yoksa işlemi yapan kullanıcı (otomatik taramada "system").
    creator = domain.sy_team.name if domain.sy_team is not None else username
    parsed_list = [cert_parser.parse_x509(c) for c in served_chain]
    # Önce CA'lar eklensin ki leaf parent bulabilsin
    parsed_list.sort(key=lambda p: {"root": 0, "intermediate": 1, "leaf": 2}[p.cert_type])

    for parsed in parsed_list:
        row = cert_parser.find_existing(db, parsed)
        if row is not None:
            result.existing.append(row.name)
        else:
            row = Certificate(**parsed.__dict__, creator=creator, source="live",
                              environment=environment)
            row.parent_id = cert_parser.resolve_parent(db, parsed)
            db.add(row)
            db.flush()
            cert_parser.relink_children(db, row)
            log_action(db, username, "import", "certificates", row.id,
                       {"name": row.name, "via": f"{via} {domain.domain}"}, request)
            result.created.append(row.name)
        result.rows.append(row)

    # İş kuralı: domaine bağlı sertifika pasif olamaz. Sunucuda hâlâ duran pasif bir sertifika
    # ne doğrudan bağlanır ne de ekleme/devir önerisi olur; yalnız raporlanır.
    result.inactive = [r.name for r in result.rows if not r.is_active]
    served_by_type: dict[str, list[Certificate]] = {}
    for row in (r for r in result.rows if r.is_active):
        served_by_type.setdefault(normalize_cert_type(row.cert_type), []).append(row)
    seen_by_type = {t: list(v) for t, v in served_by_type.items()}
    if live and "root" not in seen_by_type:
        # Sunucular el sıkışmada root'u pratikte GÖNDERMEZ — root, sunulan zincirin envanterdeki
        # üst sertifikasından (parent_id) türetilir. Türetilen root kaldırma kanıtı SAYILMAZ.
        root = _derived_root(db, result.rows)
        if root is not None:
            seen_by_type["root"] = [root]

    # Domaindeki aktif 'server' eşlemeleri, Python'da normalize edilmiş tipe göre (SQL LOWER yok)
    bound_by_type: dict[str, list[CertificateDomainMap]] = {}
    for m in (db.query(CertificateDomainMap)
              .join(Certificate, Certificate.id == CertificateDomainMap.certificate_id)
              .filter(CertificateDomainMap.domain_id == domain.id,
                      CertificateDomainMap.mapping_type == "server",
                      Certificate.is_active == True).all()):
        bound_by_type.setdefault(normalize_cert_type(m.certificate.cert_type), []).append(m)

    for cert_type in ("root", "intermediate", "leaf"):
        seen = seen_by_type.get(cert_type, [])
        if not seen:
            continue  # bu seviye canlıda yok (ör. root sunulmadı, türetilemedi) — dokunulmaz
        bound = bound_by_type.get(cert_type, [])
        seen_ids = {r.id for r in seen}
        bound_ids = {m.certificate_id for m in bound}
        stale = [m for m in bound if m.certificate_id not in seen_ids]
        unbound = [r for r in seen if r.id not in bound_ids]
        if live:
            _reconcile_live(db, domain, cert_type, seen, stale, unbound,
                            matched=bool(seen_ids & bound_ids),
                            served=cert_type in served_by_type,
                            username=username, request=request, via=via, result=result)
        else:
            _reconcile_import(db, domain, cert_type, seen, stale, unbound,
                              matched=bool(seen_ids & bound_ids),
                              username=username, request=request, via=via, result=result)
    return result


def _derived_root(db: Session, rows: list[Certificate]) -> Certificate | None:
    for row in rows:
        cur, hops = row, 0
        while cur is not None and hops < 6:
            if normalize_cert_type(cur.cert_type) == "root":
                return cur
            cur = db.get(Certificate, cur.parent_id) if cur.parent_id else None
            hops += 1
    return None


def _target_for(old: Certificate, seen: list[Certificate]) -> Certificate:
    """Eskinin halefi: aynı subject'li sunulan sertifika, yoksa ilk sunulan."""
    return next((r for r in seen if old.subject and r.subject == old.subject), seen[0])


def _reconcile_live(db: Session, domain: Domain, cert_type: str, seen, stale, unbound, *,
                    matched: bool, served: bool, username: str, request: Request | None,
                    via: str, result: ChainSyncResult) -> None:
    """CANLI DOĞRULAMA: hiçbir eşleme kendiliğinden değişmez — her fark bu domain için öneri olur.
      • eşleşme var + fazladan bağlı olan → KALDIRMA (yalnız bu seviye canlıda gerçekten sunulduysa)
      • eşleşme yok + bağlı olan var      → DEĞİŞİKLİK (devir: eski → canlıdaki)
      • bağlı değil                       → EKLEME"""
    targeted: set[int] = set()
    if matched:
        if served:
            for m in stale:
                if renewal.propose_server_mapping(db, "server_remove", m.certificate, domain,
                                                  username=username, request=request, via=via,
                                                  live_seen=True):
                    result.removed.append(m.certificate.name)
    else:
        for m in stale:
            target = _target_for(m.certificate, seen)
            targeted.add(target.id)
            p = renewal.propose_attach_transfer(db, target, m.certificate, domain, "server",
                                                username=username, request=request, via=via,
                                                live_seen=True)
            if p is not None:
                result.superseded.append(m.certificate.name)
    for row in unbound:
        if row.id in targeted:
            continue
        if renewal.propose_server_mapping(db, "server_add", row, domain, username=username,
                                          request=request, via=via, live_seen=True):
            result.added.append(row.name)


def _reconcile_import(db: Session, domain: Domain, cert_type: str, seen, stale, unbound, *,
                      matched: bool, username: str, request: Request | None, via: str,
                      result: ChainSyncResult) -> None:
    """ZİNCİR İÇE AKTARMA (insan tetikli): bağlı olmayan seviye doğrudan eklenir (ilk kurulum).
    Seviyede zincir dışında kalan bağlı sertifika varsa (rotasyon) canlı doğrulamayla AYNI kural:
      • eşleşme var (bağlılardan biri hâlâ sunuluyor) + fazladan bağlı → KALDIRMA önerisi
      • eşleşme yok + bağlı olan var → her eskiye TEK halef (_target_for) için DEVİR önerisi
      • halef seçilmeyen yeni sertifika → EKLEME önerisi
    Eskiden her eski×yeni çifti için devir önerisi açılıyordu: aynı seviyede iki yeni sertifika
    (2 katmanlı ara CA) varsa iki rakip öneri doğuyor, onaydan sonra biri hiç bağlanmıyordu."""
    if not stale:
        for row in unbound:
            db.add(CertificateDomainMap(certificate_id=row.id, domain_id=domain.id,
                                        mapping_type="server"))
            log_action(db, username, "create", "certificate_domain_map", None,
                       {"domain": domain.domain, "cert": row.name, "type": "server",
                        "via": via}, request)
            result.mapped[cert_type] = row.name
        return
    targeted: set[int] = set()
    if matched:
        for m in stale:
            if renewal.propose_server_mapping(db, "server_remove", m.certificate, domain,
                                              username=username, request=request, via=via):
                result.removed.append(m.certificate.name)
    else:
        for m in stale:
            target = _target_for(m.certificate, seen)
            targeted.add(target.id)
            p = renewal.propose_attach_transfer(db, target, m.certificate, domain, "server",
                                                username=username, request=request, via=via)
            if p is not None:
                result.superseded.append(m.certificate.name)
    for row in unbound:
        if row.id in targeted:
            continue
        if renewal.propose_server_mapping(db, "server_add", row, domain, username=username,
                                          request=request, via=via):
            result.added.append(row.name)
