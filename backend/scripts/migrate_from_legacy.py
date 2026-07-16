"""Eski JUMBO veritabanından (SSLCertificates, domain_certificates,
SSLCertificateDomainMapping, applications, users, AuditLog) yeni şemaya veri taşır.

Kullanım:
    ./.venv/bin/python scripts/migrate_from_legacy.py \
        --legacy-url "mssql+pyodbc://user:pass@SUNUCU:1433/ESKIDB?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes" \
        [--dry-run]

Notlar:
- Idempotenttir: aynı (serial_number, issuer) sertifika ve aynı domain adı tekrar eklenmez.
- Sertifika hiyerarşisi eski ParentKey/GrandParentKey string alanları yerine
  SKI/AKI eşleşmesiyle yeniden kurulur (PEM varsa PEM'den doğrulanır).
- domain_certificates.sy / .ug serbest metinlerinden teams tablosu üretilir.
- --dry-run: hedef DB'ye yazmadan neyin taşınacağını raporlar.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import (  # noqa: E402
    Application,
    Certificate,
    CertificateDomainMap,
    Domain,
    Team,
    User,
)
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.services import cert_parser  # noqa: E402


def get_or_create_team(db: Session, cache: dict, name: str | None, type_: str) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    key = (name, type_)
    if key in cache:
        return cache[key]
    team = db.query(Team).filter_by(name=name, type=type_).first()
    if team is None:
        team = Team(name=name, type=type_)
        db.add(team)
        db.flush()
    cache[key] = team.id
    return team.id


def migrate(legacy_url: str, dry_run: bool) -> None:
    legacy = create_engine(legacy_url)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    team_cache: dict = {}
    stats = {"certificates": 0, "domains": 0, "mappings": 0, "applications": 0, "users": 0, "skipped": 0}

    with legacy.connect() as conn:
        # ---- Sertifikalar ----
        rows = conn.execute(text(
            "SELECT ID, NAME, SerialNumber, Issuer, Subject, SubjectKeyIdentifier, "
            "AuthorityKeyIdentifier, CertType, ValidFrom, ValidTo, PEMCertificate, "
            "ExtendedKeyUsage, IsActive, Internal, SatinAlimYapan, CertificateCreator, Notes "
            "FROM dbo.SSLCertificates"
        )).mappings().all()
        legacy_cert_ids: dict[int, int] = {}  # eski ID -> yeni ID
        for row in rows:
            # Dedup runtime ile aynı anahtarla: PEM varsa fingerprint (cert_parser.find_existing),
            # PEM yoksa serial+issuer'a düşülür. SKI asla dedup anahtarı değildir.
            exists = None
            pem = row["PEMCertificate"]
            if pem and "BEGIN CERTIFICATE" in pem:
                try:
                    exists = cert_parser.find_existing(db, cert_parser.parse_pem_text(pem)[0])
                except Exception:
                    exists = None
            if exists is None:
                exists = db.query(Certificate).filter_by(
                    serial_number=row["SerialNumber"], issuer=row["Issuer"]).first()
            if exists:
                legacy_cert_ids[row["ID"]] = exists.id
                stats["skipped"] += 1
                continue
            cert = Certificate(
                name=row["NAME"], serial_number=row["SerialNumber"], issuer=row["Issuer"],
                subject=row["Subject"], subject_key_identifier=row["SubjectKeyIdentifier"],
                authority_key_identifier=row["AuthorityKeyIdentifier"],
                cert_type=(row["CertType"] or "leaf").lower(),
                valid_from=row["ValidFrom"], valid_to=row["ValidTo"],
                pem_certificate=row["PEMCertificate"], extended_key_usage=row["ExtendedKeyUsage"],
                is_active=bool(row["IsActive"]),
                is_internal=str(row["Internal"] or "").strip().lower() in ("1", "true", "evet", "yes"),
                purchased_by=row["SatinAlimYapan"], creator=row["CertificateCreator"],
                notes=row["Notes"],
            )
            # PEM varsa alanları PEM'den doğrula/tamamla (SAN + fingerprint dahil)
            if cert.pem_certificate and "BEGIN CERTIFICATE" in cert.pem_certificate:
                try:
                    parsed = cert_parser.parse_pem_text(cert.pem_certificate)[0]
                    cert.subject_key_identifier = parsed.subject_key_identifier
                    cert.authority_key_identifier = parsed.authority_key_identifier
                    cert.cert_type = parsed.cert_type
                    cert.san = parsed.san
                    cert.fingerprint_sha256 = parsed.fingerprint_sha256
                except Exception:
                    pass
            db.add(cert)
            db.flush()
            legacy_cert_ids[row["ID"]] = cert.id
            stats["certificates"] += 1

        # Hiyerarşi: SKI/AKI eşleşmesi (deterministik: aktif + bitişi en geç CA)
        for cert in db.query(Certificate).filter(Certificate.parent_id.is_(None)).all():
            if cert.authority_key_identifier and cert.cert_type != "root":
                parent = cert_parser.find_ca_by_ski(
                    db, cert.authority_key_identifier, exclude_id=cert.id)
                if parent:
                    cert.parent_id = parent.id

        # ---- Domainler ----
        rows = conn.execute(text(
            "SELECT id, domain, external_address, ug, sy, cert_owner, lb_update, env_update, "
            "waf_update, external_company, expire_date, info, mail_addresses, Aksiyon_Alma, "
            "SSLPinning, Keystore FROM dbo.domain_certificates"
        )).mappings().all()
        legacy_domain_ids: dict[int, int] = {}
        for row in rows:
            exists = db.query(Domain).filter_by(domain=row["domain"]).first()
            if exists:
                legacy_domain_ids[row["id"]] = exists.id
                stats["skipped"] += 1
                continue
            domain = Domain(
                domain=row["domain"], external_address=row["external_address"],
                ug_team_id=get_or_create_team(db, team_cache, row["ug"], "UG"),
                sy_team_id=get_or_create_team(db, team_cache, row["sy"], "SY"),
                cert_owner=row["cert_owner"], lb_update=row["lb_update"],
                env_update=row["env_update"], waf_update=row["waf_update"],
                external_company=row["external_company"], expire_date=row["expire_date"],
                info=row["info"], mail_addresses=row["mail_addresses"],
                action_required=row["Aksiyon_Alma"], ssl_pinning=row["SSLPinning"],
                keystore=row["Keystore"],
            )
            db.add(domain)
            db.flush()
            legacy_domain_ids[row["id"]] = domain.id
            stats["domains"] += 1

        # ---- Sertifika-domain eşlemeleri ----
        rows = conn.execute(text(
            "SELECT CertID, DomainID, MappingType FROM dbo.SSLCertificateDomainMapping"
        )).mappings().all()
        for row in rows:
            cert_id = legacy_cert_ids.get(row["CertID"])
            domain_id = legacy_domain_ids.get(row["DomainID"])
            mtype = (row["MappingType"] or "server").lower()
            if not cert_id or not domain_id:
                stats["skipped"] += 1
                continue
            exists = db.query(CertificateDomainMap).filter_by(
                certificate_id=cert_id, domain_id=domain_id, mapping_type=mtype).first()
            if exists:
                stats["skipped"] += 1
                continue
            db.add(CertificateDomainMap(certificate_id=cert_id, domain_id=domain_id, mapping_type=mtype))
            stats["mappings"] += 1

        # ---- Uygulamalar ----
        rows = conn.execute(text(
            "SELECT app_name, app_user, conf_path, control_method, dns, domain, info, ip_address, "
            "log_path, notes, required_commands, server_name, service_provider_contact, "
            "start_stop_method, status, sy_team, ug_team FROM dbo.applications"
        )).mappings().all()
        for row in rows:
            if db.query(Application).filter_by(app_name=row["app_name"], server_name=row["server_name"]).first():
                stats["skipped"] += 1
                continue
            domain_row = db.query(Domain).filter_by(domain=row["domain"]).first() if row["domain"] else None
            db.add(Application(
                app_name=row["app_name"], app_user=row["app_user"], conf_path=row["conf_path"],
                control_method=row["control_method"], dns=row["dns"],
                domain_id=domain_row.id if domain_row else None, info=row["info"],
                ip_address=row["ip_address"], log_path=row["log_path"], notes=row["notes"],
                required_commands=row["required_commands"], server_name=row["server_name"],
                service_provider_contact=row["service_provider_contact"],
                start_stop_method=row["start_stop_method"], status=bool(row["status"]),
                sy_team_id=get_or_create_team(db, team_cache, row["sy_team"], "SY"),
                ug_team_id=get_or_create_team(db, team_cache, row["ug_team"], "UG"),
            ))
            stats["applications"] += 1

        # ---- Kullanıcılar (şifreler taşınmaz; LDAP veya şifre sıfırlama önerilir) ----
        rows = conn.execute(text("SELECT username, email FROM dbo.users")).mappings().all()
        for row in rows:
            if db.query(User).filter_by(username=row["username"]).first():
                stats["skipped"] += 1
                continue
            db.add(User(username=row["username"], email=row["email"], role="viewer",
                        auth_source="ldap", password_hash=None))
            stats["users"] += 1

    print(f"[{datetime.now():%H:%M:%S}] Özet: {stats}")
    if dry_run:
        print("DRY-RUN: değişiklikler geri alınıyor, hedef DB'ye yazılmadı.")
        db.rollback()
    else:
        db.commit()
        print("Migration tamamlandı.")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eski JUMBO DB'den yeni şemaya veri taşır")
    parser.add_argument("--legacy-url", required=True, help="Eski DB SQLAlchemy bağlantı adresi")
    parser.add_argument("--dry-run", action="store_true", help="Yazmadan raporla")
    args = parser.parse_args()
    migrate(args.legacy_url, args.dry_run)
