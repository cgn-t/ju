"""JUMBO — Canlı doğrulamanın gördüğü sertifikayı pod içinden kontrol (READ-ONLY).

Canlı doğrulamanın KULLANDIĞI AYNI fonksiyonla (live_check.fetch_served_chain) host:port'a bağlanır,
TLS el sıkışmasında sunulan zinciri listeler ve envanterle karşılaştırır. Hiçbir şey YAZMAZ
(öneri açmaz, sertifika eklemez, domain durumunu değiştirmez).

NOT — HTTP yönlendirmesi: canlı doğrulama 301/302'yi TAKİP ETMEZ; host'un kendi TLS sertifikasına
bakar. Tarayıcı ise yönlendirme sonrası adresin sertifikasını gösterir (ör. stablex.net → stablex.com
yönlendirmesinde kilit simgesi stablex.com'u gösterir, JUMBO stablex.net'in sertifikasını görür).

Kullanım (pod içinde, /app):
    oc exec -it deploy/jumbo -- python -m scripts.live_cert_check stablex.net
    oc exec -it deploy/jumbo -- python -m scripts.live_cert_check "xxx.aaakkk.com:8228"
    oc exec -it deploy/jumbo -- python -m scripts.live_cert_check stablex.net --no-db   # yalnız TLS

Çıktı her sertifika için: tip, CN, yayıncı, geçerlilik (İstanbul saati), seri, SHA-256 parmak izi,
SAN, envanterde karşılığı (ID/ad) ve domain'e server olarak bağlı mı. Sonda domain'in açık devir
önerileri listelenir — "YENİ" sertifikanın parmak izi yukarıdaki leaf ile aynıysa öneri doğrudur.

Çıkış kodu: 0 bağlantı başarılı, 2 bağlanılamadı.
"""

import argparse
import sys
import warnings
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # /app — `python scripts/…` için de

from cryptography import x509  # noqa: E402
from cryptography.utils import CryptographyDeprecationWarning  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.x509.oid import ExtensionOID, NameOID  # noqa: E402

from app.core.timeutil import ISTANBUL  # noqa: E402
from app.services.live_check import fetch_served_chain, parse_target  # noqa: E402

# Bazı eski kök sertifikaların seri numarası 0 (RFC dışı) — teşhis çıktısını kirletmesin
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)


def _cn(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return attrs[0].value if attrs else name.rfc4514_string()


def _fp(cert: x509.Certificate) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def _kind(cert: x509.Certificate, index: int) -> str:
    if cert.subject == cert.issuer:
        return "root"
    try:
        if cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca:
            return "intermediate"
    except x509.ExtensionNotFound:
        pass
    return "leaf" if index == 0 else "intermediate?"


def _san(cert: x509.Certificate) -> list[str]:
    try:
        return cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value \
            .get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        return []


def _ist(dt) -> str:
    return dt.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser(description="Canlı doğrulamanın gördüğü sertifika zincirini gösterir (salt-okunur).")
    ap.add_argument("target", help='host, "host:port" ya da envanterdeki domain değeri (ör. "x.com:8228(Bloomberg)")')
    ap.add_argument("port", nargs="?", type=int, help="port (varsayılan 443 ya da target içindeki)")
    ap.add_argument("--no-db", action="store_true", help="envanter karşılaştırması yapma (yalnız TLS)")
    args = ap.parse_args()

    host, port = parse_target(args.target)
    if host is None:
        print("Wildcard ya da boş hedefe bağlanılamaz — gerçek bir host adı verin.", file=sys.stderr)
        return 2
    port = args.port or port

    print(f"== {host}:{port} (SNI={host}) — canlı doğrulamayla aynı bağlantı")
    try:
        chain = fetch_served_chain(host, port)
    except Exception as e:  # noqa: BLE001 — teşhis aracı: hatayı olduğu gibi göster
        print(f"Bağlanılamadı: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    db = None
    inv = {}
    bound: set[int] = set()
    domains = []
    if not args.no_db:
        from app.db.models import Certificate, CertificateDomainMap, Domain, TransferProposal
        from app.db.session import SessionLocal
        db = SessionLocal()
        fps = [_fp(c) for c in chain]
        inv = {c.fingerprint_sha256: c for c in
               db.query(Certificate).filter(Certificate.fingerprint_sha256.in_(fps)).all()}
        # Bu host'a karşılık gelen domain kayıtları (ör. "stablex.net", "stablex.net:443", "stablex.net(not)")
        domains = [d for d in db.query(Domain).filter(Domain.domain.ilike(f"%{host}%")).all()
                   if parse_target(d.domain) == (host, port)]
        if domains:
            bound = {m.certificate_id for m in db.query(CertificateDomainMap).filter(
                CertificateDomainMap.domain_id.in_([d.id for d in domains]),
                CertificateDomainMap.mapping_type == "server").all()}

    for i, cert in enumerate(chain):
        fp = _fp(cert)
        print(f"\n-- [{i}] {_kind(cert, i)}")
        print(f"   CN        : {_cn(cert.subject)}")
        print(f"   Yayıncı   : {_cn(cert.issuer)}")
        print(f"   Geçerlilik: {_ist(cert.not_valid_before_utc)} → {_ist(cert.not_valid_after_utc)} (İstanbul)")
        print(f"   Seri      : {cert.serial_number:X}")
        print(f"   SHA-256   : {fp}")
        if san := _san(cert):
            print(f"   SAN       : {', '.join(san[:10])}{' …' if len(san) > 10 else ''}")
        if db is not None:
            row = inv.get(fp)
            if row is None:
                print("   Envanter  : YOK (canlı doğrulama bunu envantere ekler)")
            else:
                state = "server olarak BAĞLI" if row.id in bound else "bu domaine bağlı DEĞİL"
                print(f"   Envanter  : #{row.id} {row.name} · {row.cert_type} · {state}")

    if db is not None:
        print()
        if not domains:
            print(f"== Envanterde {host}:{port} için domain kaydı yok.")
        for d in domains:
            print(f"== Domain #{d.id} {d.domain} — son canlı doğrulama: {d.live_check_status or '—'}"
                  f"{' @ ' + _ist(d.live_check_at.replace(tzinfo=timezone.utc)) if d.live_check_at else ''}")
            props = (db.query(TransferProposal)
                     .filter(TransferProposal.domain_id == d.id, TransferProposal.status == "pending")
                     .order_by(TransferProposal.id).all())
            if not props:
                print("   Açık öneri yok.")
            served = {_fp(c) for c in chain}
            for p in props:
                old, new = db.get(Certificate, p.old_cert_id), db.get(Certificate, p.new_cert_id)
                ok = new is not None and new.fingerprint_sha256 in served
                print(f"   Öneri #{p.id} [{p.kind or 'transfer'}] {old.name if old else p.old_cert_id} → "
                      f"{new.name if new else p.new_cert_id} · kaynak={p.via} · öneren={p.created_by}")
                if new is not None:
                    if p.kind == "server_remove":
                        verdict = ("✘ hâlâ sunuluyor — kaldırma önerisi artık geçersiz" if ok
                                   else "✔ sunulmuyor — kaldırma önerisi tutarlı")
                    else:
                        verdict = "✔ şu an sunulan zincirde" if ok else "✘ şu an sunulan zincirde DEĞİL"
                    print(f"      YENİ bitiş {_ist(new.valid_to.replace(tzinfo=timezone.utc))} · {verdict}")
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
