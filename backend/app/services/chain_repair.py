"""Zincir Kontrolü: envanterdeki kayıtların türünü (kök/ara/uç), üst sertifikasını ve anahtar
kimliklerini PEM'lerinden yeniden hesaplar; farkları listeler ve istenirse düzeltir.

Türler yalnız içe aktarma anında hesaplanır. Eski sürümlerin (ya da prod'daki eski uygulamanın)
yanlış yazdığı tür ve üst bağları kendiliğinden düzelmez; bu araç onları bulur:
  • tür: parse_x509 sonucu + kendinden imzalı 'uç' sanılan sertifika başka bir kaydı
    imzalamışsa kök (cert_parser._promote_file_signers ile aynı kural);
  • üst: mevcut üst sertifikayı gerçekten imzalamışsa DOKUNULMAZ (aynı anahtarlı geçerli
    alternatifler arasında gereksiz oynama yapılmaz); imzalamamışsa, kendinden imzalı kayda
    üst verilmişse ya da üst yoksa imzası doğrulanan en iyi aday seçilir;
  • anahtar kimliği (SKI/AKI): DB'deki değer PEM'den hesaplanandan farklı biçimdeyse
    (eski kayıt) yeni bağlamalar eşleşmez → PEM'deki değere çekilir.
PEM'i olmayan kayıtlar doğrulanamaz, atlanır. Üstü PEM'siz olan kaydın bağı korunur."""

from dataclasses import dataclass

from cryptography import x509
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
from app.db.models import Certificate
from app.services import cert_parser

TYPE_LABEL = {"root": "Root", "intermediate": "Intermediate", "leaf": "Leaf"}
KIND_LABEL = {"type": "Tür", "parent": "Üst sertifika", "subject_key_identifier": "SKI",
              "authority_key_identifier": "AKI"}


@dataclass
class _Row:
    cert: Certificate
    x509: x509.Certificate
    parsed: cert_parser.ParsedCertificate
    expected_type: str
    self_signed: bool


def _signed_by(child: _Row, parent: _Row) -> bool:
    return child.cert.id != parent.cert.id and cert_parser._signed_by(child.x509, parent.x509)


def _load(db: Session) -> list[_Row]:
    rows: list[_Row] = []
    for cert in db.query(Certificate).filter(Certificate.pem_certificate.isnot(None)).all():
        try:
            xc = x509.load_pem_x509_certificate(cert.pem_certificate.encode())
            parsed = cert_parser.parse_x509(xc)
        except Exception:
            continue
        p = parsed
        rows.append(_Row(cert, xc, parsed, parsed.cert_type, cert_parser.is_self_signed(
            p.issuer, p.subject, p.authority_key_identifier, p.subject_key_identifier)))
    return rows


def _expected_parent(row: _Row, by_ski: dict, by_subject: dict, by_id: dict,
                     all_ids: set[int]) -> int | None:
    """Beklenen üst sertifika id'si. Mevcut bağ geçerliyse (üst gerçekten imzalamış) korunur;
    tek istisna: aynı anahtarın aktif kökü varken çapraz imzalı kopyaya bağlı olması."""
    if row.self_signed or row.expected_type == "root":
        return None
    aki = row.parsed.authority_key_identifier
    pool = by_ski.get(aki, []) if aki else by_subject.get(row.parsed.issuer, [])
    candidates = [c for c in pool if c.expected_type != "leaf" and _signed_by(row, c)]
    best = min(candidates, key=lambda c: (
        not c.cert.is_active, c.expected_type != "root",
        -(c.cert.valid_to.timestamp() if c.cert.valid_to else 0), -c.cert.id)) if candidates else None
    current = row.cert.parent_id
    if current is not None:
        cur = by_id.get(current)
        if cur is None:
            # Üst kaydın PEM'i yok: imzası doğrulanamaz, bağ korunur
            return current if current in all_ids else (best.cert.id if best else None)
        if cur.expected_type != "leaf" and _signed_by(row, cur):
            prefer_root = (best is not None and best.expected_type == "root" and best.cert.is_active
                           and cur.expected_type != "root")
            return best.cert.id if prefer_root else current
    return best.cert.id if best else None


def check(db: Session) -> list[dict]:
    rows = _load(db)
    by_issuer: dict[str, list[_Row]] = {}
    for r in rows:
        by_issuer.setdefault(r.parsed.issuer, []).append(r)
    # Kendinden imzalı 'uç' sanılan sertifika başka bir kaydı imzalamışsa köktür
    for r in rows:
        if r.expected_type == "leaf" and r.self_signed:
            if any(not c.self_signed and _signed_by(c, r) for c in by_issuer.get(r.parsed.subject, [])):
                r.expected_type = "root"

    by_id = {r.cert.id: r for r in rows}
    all_ids = {cid for (cid,) in db.query(Certificate.id).all()}
    by_ski: dict[str, list[_Row]] = {}
    by_subject: dict[str, list[_Row]] = {}
    for r in rows:
        if r.parsed.subject_key_identifier:
            by_ski.setdefault(r.parsed.subject_key_identifier, []).append(r)
        by_subject.setdefault(r.parsed.subject, []).append(r)

    names = {cid: name for cid, name in db.query(Certificate.id, Certificate.name).all()}
    findings: list[dict] = []
    for r in sorted(rows, key=lambda r: (r.cert.name or "", r.cert.id)):
        c, p = r.cert, r.parsed
        current_type = normalize_cert_type(c.cert_type)
        if current_type != r.expected_type:
            findings.append(dict(certificate_id=c.id, name=c.name, kind="type",
                                 current=TYPE_LABEL[current_type], expected=TYPE_LABEL[r.expected_type],
                                 expected_value=r.expected_type))
        expected_parent = _expected_parent(r, by_ski, by_subject, by_id, all_ids)
        if expected_parent != c.parent_id:
            findings.append(dict(certificate_id=c.id, name=c.name, kind="parent",
                                 current=names.get(c.parent_id, "—") if c.parent_id else "—",
                                 expected=names.get(expected_parent, "—") if expected_parent else "— (üstü yok)",
                                 expected_value=expected_parent))
        for field, label in (("subject_key_identifier", "SKI"), ("authority_key_identifier", "AKI")):
            want = getattr(p, field)
            have = getattr(c, field)
            if want and have != want:
                findings.append(dict(certificate_id=c.id, name=c.name, kind=field,
                                     current=f"{label}: {have or '—'}", expected=f"{label}: {want}",
                                     expected_value=want))
    return findings


def apply(db: Session) -> list[dict]:
    """Bulguları uygular; uygulananları döner (çağıran kaydı ve commit'i yapar)."""
    findings = check(db)
    for f in findings:
        cert = db.get(Certificate, f["certificate_id"])
        if f["kind"] == "type":
            cert.cert_type = f["expected_value"]
        elif f["kind"] == "parent":
            cert.parent_id = f["expected_value"]
        else:
            setattr(cert, f["kind"], f["expected_value"])
    return findings
