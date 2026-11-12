"""Sertifika Standart Adı (v3.9.39).

Biçim (v3.9.42, genelden özele): ortam_CA_Tür_alanadı_BitişTarihi   ör. prod_Dgcrt_wildcard_aaaa.com_20260814
  • Ortam  : prod | test; ortam boşsa bu parça yok, ad CA ile başlar (Ayarlar'dan kapatılabilir).
  • CA     : Issuer'dan, Ayarlar > İsimlendirme'deki kısaltma listesiyle (ilk eşleşen satır).
             Listede yoksa "Diger"; kendinden imzalı sunucu sertifikasında "Self".
  • Tür    : root | intermediate | client (yalnız mTLS istemci) | wildcard | san | single
             (san = www dışında birden fazla host adı; aaa.ai + api.aaa.ai de san)
  • Alan adı: CN küçük harf, başındaki "*." atılır; CN yoksa ilk SAN. Root/intermediate'ta
             CA'nın kendi adı (boşluksuz).
  • Tarih  : ValidTo, İstanbul saatine göre yyyyaagg.
Aynı ad başka bir sertifikada varsa sonuna _2, _3… eklenir.

Ad yalnız ÖNERİLİR: yüklemede alan dolu gelir, kişi değiştirebilir; Jumbo elle verilen adın
üzerine kendiliğinden yazmaz. Kolon yokken (betik çalıştırılmamışsa) hiçbir şey yazılmaz.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.certtype import normalize_cert_type
from app.core.timeutil import ISTANBUL
from app.db.models import Certificate
from app.services import schema_state
from app.services.settings_service import get_category

MAX_LEN = 255

_RDN_SPLIT = re.compile(r"(?<!\\),")


def _rdn(dn: str | None, attr: str) -> str | None:
    """RFC 4514 metninden ilk attr= değerini çıkarır (CN=..., O=...)."""
    if not dn:
        return None
    for part in _RDN_SPLIT.split(dn):
        k, sep, v = part.partition("=")
        if sep and k.strip().upper() == attr:
            return v.replace("\\,", ",").replace("\\", "").strip() or None
    return None


def _clean(value: str) -> str:
    v = value.strip().lower()
    v = re.sub(r"\s+", "-", v)
    v = re.sub(r"[^a-z0-9.\-_]", "", v)
    return v.strip("-._")


def _compact(value: str) -> str:
    """CA adını boşluksuz yazar: 'DigiCert Global Root G2' → 'DigiCertGlobalRootG2'."""
    return re.sub(r"[^A-Za-z0-9]", "", value)[:60]


def _sans(san: str | None) -> list[str]:
    return [s.strip().lower() for s in (san or "").split(",") if s.strip()]


def abbreviation(issuer: str | None, rules: list, unknown: str) -> str:
    text = (issuer or "").lower()
    for r in rules or []:
        m = str((r or {}).get("match") or "").strip().lower()
        a = str((r or {}).get("abbr") or "").strip()
        if m and a and m in text:
            return a
    return unknown


def kind_of(cert_type: str | None, cn: str | None, san: str | None, eku: str | None) -> str:
    # v3.9.43: prod'daki eski kayıtlar "Root"/"Intermediate"/"ROOT" yazımıyla tutulur; küçük harfe
    # indirilmezse CA sertifikaları "single" görünüyordu.
    cert_type = normalize_cert_type(cert_type)
    if cert_type in ("root", "intermediate"):
        return cert_type
    e = (eku or "").lower()
    if "clientauth" in e.replace(" ", "") and "serverauth" not in e.replace(" ", ""):
        return "client"
    names = _sans(san)
    if (cn or "").strip().startswith("*.") or any(n.startswith("*.") for n in names):
        return "wildcard"
    base = {n[4:] if n.startswith("www.") else n for n in names
            if not re.match(r"^\d+\.\d+\.\d+\.\d+$|:", n)}
    if cn:
        c = cn.strip().lower()
        base.add(c[4:] if c.startswith("www.") else c)
    return "san" if len(base) > 1 else "single"


def _date(valid_to: datetime | None) -> str | None:
    if valid_to is None:
        return None
    dt = valid_to if valid_to.tzinfo else valid_to.replace(tzinfo=timezone.utc)
    return dt.astimezone(ISTANBUL).strftime("%Y%m%d")


def build(*, issuer: str | None, subject: str | None, name: str | None, san: str | None,
          cert_type: str | None, eku: str | None, valid_to: datetime | None,
          environment: str | None, cfg: dict) -> dict:
    """Önerilen adı ve parçalarını döndürür (çakışma kontrolü YOK; bkz. suggest)."""
    cn = _rdn(subject, "CN")
    # PEM'siz elle kayıtta Issuer/Subject ada eşitlenir (bkz. create_certificate); DN değilse
    # kendinden imzalı sayılmaz.
    self_signed = bool(issuer and subject and "=" in subject and issuer.strip() == subject.strip())
    kind = kind_of(cert_type, cn or name, san, eku)
    if self_signed and kind not in ("root", "intermediate"):
        ca = cfg.get("self_signed_abbr") or "Self"
    else:
        ca = abbreviation(issuer, cfg.get("ca_abbreviations") or [], cfg.get("unknown_abbr") or "Diger")
    if kind in ("root", "intermediate"):
        main = _compact(cn or _rdn(subject, "O") or name or "")
    else:
        first = (cn or "").strip()
        if not first or " " in first:  # CN bir host adı değilse SAN'a, o da yoksa NAME'e düş
            first = next(iter(_sans(san)), "") or first or (name or "")
        if first.startswith("*."):
            first = first[2:]
        main = _clean(first)
    # v3.9.42 sıra genelden özele: ortam_CA_tür_alanadı_tarih; ortam boşsa ortam parçası yok
    parts = []
    if cfg.get("env_suffix", True) and environment in ("prod", "test"):
        parts.append(environment)
    parts += [ca, kind, main or "adsiz"]
    d = _date(valid_to)
    if d:
        parts.append(d)
    return {"name": "_".join(parts)[:MAX_LEN], "ca": ca, "kind": kind, "main": main,
            "date": d, "env": environment if cfg.get("env_suffix", True) else None,
            "unknown_ca": ca == (cfg.get("unknown_abbr") or "Diger")}


def config(db: Session) -> dict:
    return get_category(db, "naming")


def _taken(db: Session, exclude_id: int | None) -> set[str]:
    q = db.query(Certificate.id, Certificate.standard_name).filter(Certificate.standard_name.isnot(None))
    return {(n or "").lower() for i, n in q.all() if i != exclude_id and n}


def unique(name: str, taken: set[str]) -> str:
    if name.lower() not in taken:
        return name
    i = 2
    while f"{name}_{i}".lower() in taken:
        i += 1
    return f"{name}_{i}"


def from_cert(cert, cfg: dict) -> dict:
    return build(issuer=cert.issuer, subject=cert.subject, name=cert.name, san=cert.san,
                 cert_type=cert.cert_type, eku=cert.extended_key_usage, valid_to=cert.valid_to,
                 environment=cert.environment, cfg=cfg)


def suggest(db: Session, cert, cfg: dict | None = None, taken: set[str] | None = None) -> dict:
    """Bir sertifika (ORM ya da benzeri nesne) için çakışmasız öneri."""
    cfg = cfg if cfg is not None else config(db)
    out = from_cert(cert, cfg)
    if taken is None:
        taken = _taken(db, getattr(cert, "id", None)) if schema_state.standard_name_ready() else set()
    final = unique(out["name"], taken)
    out["collision"] = final != out["name"]
    out["name"] = final
    return out


# ---------- yeni kayıtlarda kendiliğinden ----------

@event.listens_for(Session, "before_flush")
def _fill_new(session: Session, _ctx, _instances) -> None:
    """Hangi yoldan gelirse gelsin (PEM yükleme, dosyadan içe aktarma, Vault, Keşif, canlı
    doğrulama) yeni sertifika standart adı boşsa doldurulur. Kullanıcının verdiği ad korunur."""
    new = [o for o in session.new if isinstance(o, Certificate)]
    if not new or not schema_state.standard_name_ready():
        return
    with session.no_autoflush:
        try:
            cfg = config(session)
            taken = _taken(session, None)
        except Exception:
            return
        for cert in new:
            if cert.__dict__.get("standard_name"):
                taken.add(cert.standard_name.lower())
                continue
            if not (cert.issuer or cert.subject or cert.name):
                continue
            # PEM'siz "yalnız isim" kaydında Issuer/tarih gerçek değil: kural uygulanmaz
            if (cert.serial_number or "").startswith("PLACEHOLDER-") and not cert.pem_certificate:
                continue
            cert.standard_name = unique(from_cert(cert, cfg)["name"], taken)
            taken.add(cert.standard_name.lower())
