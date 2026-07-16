"""Sertifika uyum (politika) motoru — TAMAMEN YEREL, dış erişim YOK.

Envanter üstünde kural değerlendirir ve ihlalleri OKUMA ANINDA hesaplar (violations tablosu yok):
  • untrusted_issuer  — issuer, admin'in CA allowlist'inde değil (rogue/izinsiz issuance) — yalnız leaf.
  • weak_key          — RSA < min_rsa_bits ya da EC < min_ec_bits.
  • weak_signature    — imza özet algoritması yasak listesinde (sha1/md5…).
  • excessive_validity— leaf ömrü max_validity_days'i aşıyor (CA'lar hariç).

Kripto alanları (key_size/public_key_type/signature_hash) cert_parser tarafından PEM'den çıkarılıp
Certificate'e yazılır; null (kontrol edilmemiş) alan İHLAL SAYILMAZ.
"""

from app.db.models import Certificate
from app.services.settings_service import get_category

RULE_LABELS = {
    "untrusted_issuer": "Güvenilmeyen issuer (CA allowlist dışı)",
    "weak_key": "Zayıf anahtar",
    "weak_signature": "Zayıf imza algoritması",
    "excessive_validity": "Aşırı geçerlilik süresi",
}

_SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def get_config(db) -> dict:
    return get_category(db, "policy", mask_secrets=False)


def _issuer_allowed(issuer: str | None, allowlist: list) -> bool:
    iss = (issuer or "").lower()
    return any(str(e).strip().lower() in iss for e in allowlist if str(e).strip())


def evaluate_certificate(cert: Certificate, config: dict) -> list[dict]:
    """Bir sertifikanın ihlallerini döner: [{rule, severity, detail}]. Kural yoksa [] (uyumlu)."""
    violations: list[dict] = []
    is_leaf = cert.cert_type == "leaf"

    # untrusted_issuer — yalnız leaf; allowlist zorunlu kılındıysa ve doluysa
    if is_leaf and config.get("enforce_ca_allowlist"):
        allowlist = config.get("ca_allowlist") or []
        if allowlist and not _issuer_allowed(cert.issuer, allowlist):
            violations.append({"rule": "untrusted_issuer", "severity": "high",
                               "detail": f"Issuer allowlist dışında: {cert.issuer or '—'}"})

    # weak_key
    if cert.public_key_type == "RSA" and cert.key_size is not None:
        min_rsa = int(config.get("min_rsa_bits") or 2048)
        if cert.key_size < min_rsa:
            violations.append({"rule": "weak_key", "severity": "high",
                               "detail": f"RSA {cert.key_size} bit < asgari {min_rsa} bit"})
    elif cert.public_key_type == "EC" and cert.key_size is not None:
        min_ec = int(config.get("min_ec_bits") or 256)
        if cert.key_size < min_ec:
            violations.append({"rule": "weak_key", "severity": "medium",
                               "detail": f"EC {cert.key_size} bit < asgari {min_ec} bit"})

    # weak_signature
    banned = [str(s).strip().lower() for s in (config.get("banned_sig_hashes") or []) if str(s).strip()]
    if cert.signature_hash and cert.signature_hash.lower() in banned:
        violations.append({"rule": "weak_signature", "severity": "high",
                           "detail": f"İmza özet algoritması: {cert.signature_hash}"})

    # excessive_validity — yalnız leaf (CA'lar meşru olarak uzun ömürlüdür)
    max_days = int(config.get("max_validity_days") or 0)
    if is_leaf and max_days > 0 and cert.valid_from and cert.valid_to:
        days = (cert.valid_to - cert.valid_from).days
        if days > max_days:
            violations.append({"rule": "excessive_validity", "severity": "medium",
                               "detail": f"Geçerlilik {days} gün > azami {max_days} gün"})

    return violations


def max_severity(violations: list[dict]) -> str:
    """İhlal listesindeki en yüksek önem derecesi (yoksa 'low')."""
    return max((v["severity"] for v in violations),
               key=lambda s: _SEVERITY_ORDER.get(s, 0), default="low")


def evaluate_inventory(db) -> dict:
    """Aktif envanteri değerlendirir. Döner: {total_evaluated, compliant, rule_counts,
    violations: [(cert, [violation])]}."""
    certs = (db.query(Certificate)
             .filter(Certificate.is_active == True)  # noqa: E712 (MSSQL uyumu)
             .order_by(Certificate.valid_to.asc()).all())
    out_violations: list[tuple[Certificate, list[dict]]] = []
    rule_counts: dict[str, int] = {}
    compliant = 0
    config = get_config(db)
    for cert in certs:
        v = evaluate_certificate(cert, config)
        if v:
            out_violations.append((cert, v))
            for item in v:
                rule_counts[item["rule"]] = rule_counts.get(item["rule"], 0) + 1
        else:
            compliant += 1
    return {
        "total_evaluated": len(certs),
        "compliant": compliant,
        "rule_counts": rule_counts,
        "violations": out_violations,
    }
