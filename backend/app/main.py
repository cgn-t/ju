import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (get_swagger_ui_html,
                                   get_swagger_ui_oauth2_redirect_html)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.api import (
    applications,
    auth,
    certificates,
    dashboard,
    deployments,
    discovery,
    domains,
    issuance,
    jenkins,
    notifications,
    policy,
    proposals,
    settings_api,
    tags,
    users,
)
from app.core.certtype import normalize_cert_type
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.security import hash_password
from app.db import models  # noqa: F401 — model kayıtları için
from app.db.session import Base, SessionLocal, engine
from app.services.notifier import start_scheduler

setup_logging()  # tek biçimli log (bkz. core/logging_config) — basicConfig yerine
log = logging.getLogger(__name__)


def ensure_initial_admin() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            db.add(models.User(
                username=settings.initial_admin_username,
                password_hash=hash_password(settings.initial_admin_password),
                # prod users.email NOT NULL — seed için placeholder ver
                email=f"{settings.initial_admin_username}@jumbo.local",
                role="admin", auth_source="local", full_name="Yönetici",
            ))
            db.commit()
    finally:
        db.close()


def ensure_service_user() -> None:
    """Otomasyon için servis kullanıcısı tohumlar (AUTOMATION_USERNAME + PASSWORD set ise). Rol
    doğrudan 'admin' atanır (users.role TEK KAYNAK, bkz. security.effective_role); ayrıca ADMIN
    takımına da eklenir (roster/görünürlük tutarlılığı için — üyeliğin kendisi yetki VERMEZ)."""
    settings = get_settings()
    if not settings.automation_username:
        return
    # GÜVENLİK: şifresiz servis hesabı oluşturma. hash_password("") geçerli bir SHA-256 hex üretir
    # (is_local_password onu yerel sayar) ve boş şifreyle girişe izin verirdi. Şifre yoksa hiç tohumlama.
    if not settings.automation_password:
        log.warning("AUTOMATION_USERNAME tanımlı ama AUTOMATION_PASSWORD boş — servis kullanıcısı "
                    "OLUŞTURULMADI (boş-şifre hesabı güvenlik açığı).")
        return
    db = SessionLocal()
    try:
        user = (db.query(models.User)
                .filter(models.User.username == settings.automation_username).first())
        if user is None:
            user = models.User(
                username=settings.automation_username,
                password_hash=hash_password(settings.automation_password),
                email=f"{settings.automation_username}@jumbo.local",
                role="admin", auth_source="local", full_name="Otomasyon Servisi",
            )
            db.add(user)
            db.flush()
        admin_team = db.query(models.Team).filter_by(type="ADMIN").first()
        if admin_team is not None and db.query(models.UserTeam).filter_by(
                user_id=user.id, team_id=admin_team.id).first() is None:
            db.add(models.UserTeam(user_id=user.id, team_id=admin_team.id))
        db.commit()
    finally:
        db.close()


def ensure_tag_seed() -> None:
    """TEK SEFERLİK (app_settings 'tags.seeded'): katalog TAMAMEN boşsa birkaç örnek etiket ekler
    (evrensel eksenler: Ortam, Kritiklik) — UI ilk açılışta boş görünmesin. Kullanıcı silerse
    tekrar EKLENMEZ (flag). Ürün etiketlerini kullanıcı kendisi tanımlar (domaine özel)."""
    db = SessionLocal()
    try:
        if db.get(models.AppSetting, "tags.seeded") is not None:
            return
        if db.query(models.Tag).count() == 0:
            seed = [
                ("Ortam", "Prod", "#C62828"), ("Ortam", "Test", "#1565C0"),
                ("Kritiklik", "Yüksek", "#C62828"), ("Kritiklik", "Orta", "#EF6C00"),
                ("Kritiklik", "Düşük", "#2E7D32"),
            ]
            for category, name, color in seed:
                db.add(models.Tag(category=category, name=name, color=color))
        db.add(models.AppSetting(key="tags.seeded", category="tags", value="true"))
        db.commit()
    finally:
        db.close()


ADMIN_TEAM_NAME = "Yöneticiler"     # tek ADMIN takımı (global full yetki)
VIEWER_TEAM_NAME = "İzleyiciler"     # tek VIEWER takımı (global salt-okur)


def _ddl_type(sqlite_type: str, mssql_type: str) -> str:
    return sqlite_type if engine.dialect.name == "sqlite" else mssql_type


def ensure_team_type_width() -> None:
    """RBAC: teams.type eski NVARCHAR(2) ile kurulduysa 'ADMIN'/'VIEWER' (5-6 karakter) için
    NVARCHAR(10)'a genişletir. Unique constraint'e bağlı kolon → drop→alter→recreate. SQLite no-op
    (tip esnek). Idempotent (uzunluk kontrolü)."""
    if engine.dialect.name == "sqlite":
        return
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "teams" not in {t.lower() for t in inspector.get_table_names()}:
        return  # create_all yeni tabloyu zaten NVARCHAR(10) kurdu
    type_col = next((c for c in inspector.get_columns("teams") if c["name"].lower() == "type"), None)
    length = getattr(type_col["type"], "length", None) if type_col else None
    if length is not None and length >= 10:
        return  # zaten yeterli
    with engine.begin() as conn:
        conn.execute(text("IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name='uq_team_name_type') "
                          "ALTER TABLE [teams] DROP CONSTRAINT uq_team_name_type"))
        conn.execute(text("ALTER TABLE [teams] ALTER COLUMN type NVARCHAR(10) NOT NULL"))
        conn.execute(text("IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE name='uq_team_name_type') "
                          "ALTER TABLE [teams] ADD CONSTRAINT uq_team_name_type UNIQUE (name, type)"))
    log.info("teams.type NVARCHAR(10)'a genişletildi (ADMIN/VIEWER için)")


def ensure_rbac_seed() -> None:
    """RBAC çekirdeği. HER AÇILIŞ (idempotent): ADMIN/VIEWER singleton takımlarını garanti eder +
    break-glass (ADMIN takımının aktif üyesi yoksa seed admin'i ekler → kilit imkânsız).
    TEK SEFERLİK (app_settings 'rbac.migrated' flag'i): mevcut kullanıcıları users.role'e göre takımlara
    göç ettirir. Göç tek-seferliktir çünkü her açılışta çalışsaydı sonradan default role='viewer' ile
    oluşan YENİ kullanıcılar her restart'ta VIEWER'a düşüp global okuma kazanırdı."""
    settings = get_settings()
    db = SessionLocal()
    try:
        def get_or_create_singleton(type_: str, name: str) -> models.Team:
            team = db.query(models.Team).filter_by(type=type_).first()
            if team is None:
                team = models.Team(name=name, type=type_)
                db.add(team)
                db.flush()
            return team

        admin_team = get_or_create_singleton("ADMIN", ADMIN_TEAM_NAME)
        viewer_team = get_or_create_singleton("VIEWER", VIEWER_TEAM_NAME)

        def add_member(user_id: int, team_id: int) -> None:
            if db.query(models.UserTeam).filter_by(user_id=user_id, team_id=team_id).first() is None:
                db.add(models.UserTeam(user_id=user_id, team_id=team_id))

        def has_sy(user_id: int) -> bool:
            return (db.query(models.UserTeam)
                    .join(models.Team, models.Team.id == models.UserTeam.team_id)
                    .filter(models.UserTeam.user_id == user_id, models.Team.type == "SY")
                    .first() is not None)

        # TEK SEFERLİK eski göç (users.role → takım üyeliği). Prod'da zaten çalışmış olabilir;
        # yeni model için asıl göç aşağıdaki rbac.role_activated'dır. Taze DB'de zararsız çalışır.
        if db.get(models.AppSetting, "rbac.migrated") is None:
            for u in db.query(models.User).all():
                if u.role == "admin":
                    add_member(u.id, admin_team.id)
                elif u.role in ("viewer", "editor") and not has_sy(u.id):
                    add_member(u.id, viewer_team.id)
            db.add(models.AppSetting(key="rbac.migrated", category="rbac", value="true"))
            db.flush()

        # TEK SEFERLİK göç (takım üyeliği → users.role): rol artık users.role kolonundan OKUNUYOR
        # (effective_role). Mevcut takım-tabanlı rolleri kolona "dondur": ADMIN→admin, SY→editor,
        # VIEWER→allviewer (eski global 'viewer' artık 'allviewer'), takımsız→none.
        if db.get(models.AppSetting, "rbac.role_activated") is None:
            for u in db.query(models.User).all():
                types = {t for (t,) in db.query(models.Team.type)
                         .join(models.UserTeam, models.UserTeam.team_id == models.Team.id)
                         .filter(models.UserTeam.user_id == u.id).all()}
                if "ADMIN" in types:
                    u.role = "admin"
                elif "SY" in types:
                    u.role = "editor"
                elif "VIEWER" in types:
                    u.role = "allviewer"
                else:
                    u.role = "none"
            db.add(models.AppSetting(key="rbac.role_activated", category="rbac", value="true"))
            db.flush()

        # HER AÇILIŞ break-glass: aktif admin (users.role='admin') yoksa seed'e admin rolü ver (kilit önleme)
        from sqlalchemy import func
        active_admins = db.query(models.User).filter(
            models.User.is_active == True,
            func.lower(func.coalesce(models.User.role, "")) == "admin").count()
        if active_admins == 0:
            seed = (db.query(models.User).filter_by(username=settings.initial_admin_username).first()
                    or db.query(models.User).filter_by(is_active=True).order_by(models.User.id).first())
            if seed is not None:
                seed.role = "admin"
                add_member(seed.id, admin_team.id)  # geriye uyum: ADMIN takımına da ekle
                log.warning("Break-glass: aktif admin yoktu — '%s' admin yapıldı.", seed.username)
        db.commit()
    finally:
        db.close()


def ensure_new_columns() -> None:
    """create_all mevcut tablolara kolon EKLEMEZ. App'in prod'da (TMTKS00) OLMAYAN kolonlarını
    ilgili prod tablolarına ADDITIVE olarak (ALTER ... ADD) tamamlar. Yalnız ekleme; mevcut
    kolon/kısıt/veriye dokunmaz. Aynı liste prod-additive-changes.sql ile birebir."""
    from sqlalchemy import inspect, text

    INT = _ddl_type("INTEGER", "INT")
    BIT = _ddl_type("BOOLEAN", "BIT")
    DT = _ddl_type("DATETIME", "DATETIME2")
    TXT = _ddl_type("TEXT", "NVARCHAR(MAX)")

    def V(n: int) -> str:
        return _ddl_type(f"VARCHAR({n})", f"NVARCHAR({n})")

    additions = {
        "SSLCertificates": {
            "san": TXT, "fingerprint_sha256": V(100), "parent_id": INT,
            "superseded_by_id": INT, "is_internal": BIT, "source": V(20),
            "vault_path": V(255), "auto_renew": BIT,
            # Kripto özellikleri (politika/uyum + PQC) — PEM'den backfill_certificate_crypto ile doldurulur.
            "key_size": INT, "public_key_type": V(20), "key_curve": V(50), "signature_hash": V(50),
            # İptal (revocation) durumu — OCSP/CRL ile denetlenir (null = denetlenmemiş, backfill yok).
            "revocation_status": V(20), "revocation_checked_at": DT, "revocation_detail": TXT,
            # Ortam etiketi (prod|test) — nullable, backfill yok; yalnız manuel formda UI zorunlu kılar.
            "environment": V(20),
        },
        "domain_certificates": {
            "sy_team_id": INT, "ug_team_id": INT, "ug_team_name": V(255),
            "servers_to_update": V(500),
            "live_check_status": V(20), "live_check_detail": TXT, "live_check_at": DT,
            "created_at": DT, "updated_at": DT,
            "notify_days": INT,  # domain-başına süre-uyarı gün sayısı (NULL = global)
            # Otomatik CA alımı (issuance) — bkz. IssuanceProfile/IssuanceRequest.
            "issuance_profile_id": INT, "auto_issuance_enabled": BIT,
            "issuance_zero_touch": BIT, "issuance_renew_before_days": INT,
        },
        "applications": {"domain_id": INT, "sy_team_id": INT, "ug_team_id": INT},
        # trusted_add önerileri: hedef uygulama (app_id) + öneri türü (kind). Grain index'i
        # app_id'yi de içerir — mevcut DB'de index schema-NEW.sql ile yeniden oluşturulur.
        "transfer_proposals": {"app_id": INT, "kind": V(20)},
        "users": {
            "full_name": V(255), "role": V(20), "auth_source": V(10),
            "is_active": BIT, "last_login": DT,
        },
        "AuditLog": {"ip_address": V(50)},
        # discovered_certificates / scan_runs YENİ app tablolarıdır — create_all onları tüm kolonlarla
        # kurar; ancak ÖNCEKİ sürümde kolonsuz kurulmuş bir DB'de (ör. canlı JUMBOBP) eksik kolonlar
        # ALTER ile eklenir (idempotent). origin/crtsh_id: CT (crt.sh) izleme; kind: tarama türü.
        "discovered_certificates": {"sy_team_id": INT, "origin": V(20), "crtsh_id": V(50)},
        "scan_runs": {"kind": V(20)},
        # notifications YENİ app tablosu; önceki sürümde kolonsuz kurulmuş DB'de kanal-bazlı dedup
        # kolonu additive eklenir (idempotent). channel: email|slack|teams|webhook|…
        "notifications": {"channel": V(20)},
        # deployment_runs: rollback provenance — bu oturumda tablo ZATEN kurulduktan SONRA eklendi,
        # bu yüzden create_all'ın yeni kurulumlarda yaptığını burada additive tamamlıyoruz.
        # trigger_type: manual|retry|rerun; source_run_id: rerun'ın kaynağı olan run (FK yok,
        # diğer FK'siz snapshot alanlarıyla aynı desen — bkz. models.py DeploymentRun yorumu).
        "deployment_runs": {"trigger_type": V(20), "source_run_id": INT},
    }
    inspector = inspect(engine)
    existing_tables = {t.lower() for t in inspector.get_table_names()}
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table.lower() not in existing_tables:
                continue  # yeni tablo → create_all zaten tüm kolonlarla kurdu
            existing = {c["name"].lower() for c in inspector.get_columns(table)}
            for col, ddl_type in cols.items():
                if col.lower() not in existing:
                    conn.execute(text(f"ALTER TABLE [{table}] ADD {col} {ddl_type} NULL"))
                    log.info("Kolon eklendi: %s.%s (%s)", table, col, ddl_type)


def ensure_indexes() -> None:
    """Fingerprint için kısmi unique index (app-yeni kolon). Kirli veride mükerrer fingerprint
    varsa startup kırılmaz: index atlanır ve uyarı loglanır."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = {t.lower() for t in inspector.get_table_names()}
    if "sslcertificates" not in tables:
        return
    if any(ix["name"] == "ux_sslcertificates_fingerprint"
           for ix in inspector.get_indexes("SSLCertificates")):
        return
    with engine.begin() as conn:
        dupes = conn.execute(text(
            "SELECT fingerprint_sha256, COUNT(*) AS n FROM [SSLCertificates] "
            "WHERE fingerprint_sha256 IS NOT NULL "
            "GROUP BY fingerprint_sha256 HAVING COUNT(*) > 1")).fetchall()
        if dupes:
            log.warning("Mükerrer fingerprint'li %d grup var — unique index atlandı: %s",
                        len(dupes), [d[0][:23] for d in dupes])
            return
        conn.execute(text(
            "CREATE UNIQUE INDEX ux_sslcertificates_fingerprint ON [SSLCertificates] "
            "(fingerprint_sha256) WHERE fingerprint_sha256 IS NOT NULL"))


def backfill_certificate_fields() -> None:
    """PEM'i olan ama san/fingerprint'i boş kayıtları doldurur (tek seferlik, idempotent).
    Prod'dan gelen kayıtlar için fingerprint kimliğini PEM'den üretir."""
    import base64

    from app.services import cert_parser
    from app.services.audit import log_action

    def _parse_lenient(text: str):
        """Önce normal yol (PEM/DER/PKCS7 otomatik algı). Tutmazsa prod'un bazı kayıtlarda
        PEM zırhı OLMADAN tuttuğu çıplak base64(DER) biçimini dene: whitespace ayıkla,
        base64 çöz, DER olarak parse et. O da tutmazsa orijinal hata çağırana gider."""
        try:
            return cert_parser.parse_pem_text(text)[0]
        except Exception:
            der = base64.b64decode("".join(text.split()), validate=True)
            return cert_parser.parse_upload(der)[0]

    db = SessionLocal()
    try:
        rows = (db.query(models.Certificate)
                .filter(models.Certificate.fingerprint_sha256.is_(None),
                        models.Certificate.pem_certificate.isnot(None))
                .all())
        duplicates: list[str] = []
        for cert in rows:
            try:
                parsed = _parse_lenient(cert.pem_certificate)
                # autoflush=False: önceki iterasyonda atanan fingerprint henüz DB'de görünmez. Clash
                # sorgusu bekleyen yazımları görsün diye flush et — aksi halde aynı PEM'e sahip iki kayıt
                # da AYNI fingerprint ile dolar, mükerrer yakalanmaz ve unique index sessizce atlanır.
                db.flush()
                clash = (db.query(models.Certificate)
                         .filter(models.Certificate.fingerprint_sha256 == parsed.fingerprint_sha256,
                                 models.Certificate.id != cert.id).first())
                if clash is not None:
                    duplicates.append(f"#{cert.id} {cert.name} ≡ #{clash.id} {clash.name}")
                    log.warning("Mükerrer sertifika: #%s '%s' ile #%s '%s' aynı fingerprint — atlandı",
                                cert.id, cert.name, clash.id, clash.name)
                    cert.san = cert.san or parsed.san
                    continue
                cert.fingerprint_sha256 = parsed.fingerprint_sha256
                cert.san = parsed.san
            except Exception as exc:
                # Neden görünmezse prod'da teşhis imkânsız (yaşanan ders) — tip+mesajı logla.
                log.warning("Backfill parse hatası: %s (%s: %s)", cert.name,
                            type(exc).__name__, exc)
        if duplicates:
            log_action(db, "system", "duplicate_detected", "SSLCertificates", None,
                       {"duplicates": duplicates[:20]})
        db.commit()
    finally:
        db.close()


def backfill_certificate_crypto() -> None:
    """PEM'i olan ama kripto özellikleri (key_size/public_key_type/key_curve/signature_hash) boş
    kayıtları PEM'den doldurur (tek seferlik, idempotent). Politika/uyum motoru ve PQC envanteri
    bu kolonlara dayanır; prod'dan gelen eski kayıtlar için de doldurulmalıdır."""
    import base64

    from app.services import cert_parser

    def _parse_lenient(text: str):
        # Normal yol (PEM/DER/PKCS7). Tutmazsa prod'un PEM zırhsız çıplak base64(DER) biçimini dene.
        try:
            return cert_parser.parse_pem_text(text)[0]
        except Exception:
            der = base64.b64decode("".join(text.split()), validate=True)
            return cert_parser.parse_upload(der)[0]

    db = SessionLocal()
    try:
        rows = (db.query(models.Certificate)
                .filter(models.Certificate.key_size.is_(None),
                        models.Certificate.pem_certificate.isnot(None))
                .all())
        for cert in rows:
            try:
                parsed = _parse_lenient(cert.pem_certificate)
                cert.key_size = parsed.key_size
                cert.public_key_type = parsed.public_key_type
                cert.key_curve = parsed.key_curve
                cert.signature_hash = parsed.signature_hash
            except Exception as exc:
                log.warning("Kripto backfill parse hatası: %s (%s: %s)", cert.name,
                            type(exc).__name__, exc)
        db.commit()
    finally:
        db.close()


def backfill_parent_links() -> None:
    """Prod'da zincir ParentKey/GrandParentKey (SKI metni) ile tutuluyor; app parent_id (FK) kullanır.
    parent'ı boş leaf/intermediate için AKI→SKI eşleşmesiyle parent_id kurulur (idempotent)."""
    from app.services import cert_parser

    if not hasattr(cert_parser, "find_ca_by_ski"):
        return
    db = SessionLocal()
    try:
        rows = (db.query(models.Certificate)
                .filter(models.Certificate.parent_id.is_(None),
                        models.Certificate.authority_key_identifier.isnot(None))
                .all())
        for cert in rows:
            if normalize_cert_type(cert.cert_type) == "root":  # legacy "Root"/"ROOT" da atlansın
                continue
            parent = cert_parser.find_ca_by_ski(db, cert.authority_key_identifier, exclude_id=cert.id)
            if parent is not None:
                cert.parent_id = parent.id
        db.commit()
    finally:
        db.close()


def backfill_team_owners() -> None:
    """Prod'da domain/uygulama sahibi SY/UG ekipleri SERBEST METİN (domain_certificates.sy/ug,
    applications.sy_team/ug_team). App bunları FK ile kullanır → teams üret + sahiplik FK'lerini
    doldur. Takım e-postası prod `[group]`(name,email)'ten ada göre eşlenir. Idempotent; yalnız
    legacy metin kolonları mevcutsa çalışır (taze/SQLite'ta atlar)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = {t.lower() for t in inspector.get_table_names()}
    if "domain_certificates" not in tables and "applications" not in tables:
        return

    db = SessionLocal()
    try:
        # [group] → ad(lowercase) -> email
        group_email: dict[str, str | None] = {}
        if "group" in tables:
            try:
                for r in db.execute(text("SELECT name, email FROM [group]")).mappings():
                    if r["name"]:
                        group_email[r["name"].strip().lower()] = r["email"]
            except Exception:
                log.warning("[group] okunamadı — takım e-postası boş bırakıldı")

        cache: dict[tuple[str, str], int] = {}

        def get_or_create_team(name: str | None, type_: str) -> int | None:
            name = (name or "").strip()
            if not name:
                return None
            key = (name.lower(), type_)
            if key in cache:
                return cache[key]
            team = db.query(models.Team).filter_by(name=name, type=type_).first()
            if team is None:
                team = models.Team(name=name, type=type_, email=group_email.get(name.lower()))
                db.add(team)
                db.flush()
            elif team.email is None and group_email.get(name.lower()):
                team.email = group_email[name.lower()]
            cache[key] = team.id
            return team.id

        dc_cols = ({c["name"].lower() for c in inspector.get_columns("domain_certificates")}
                   if "domain_certificates" in tables else set())
        if {"sy", "ug"} & dc_cols:
            for r in db.execute(text("SELECT id, sy, ug FROM [domain_certificates]")).mappings():
                dom = db.get(models.Domain, r["id"])
                if dom is None:
                    continue
                if "sy" in dc_cols and dom.sy_team_id is None:
                    dom.sy_team_id = get_or_create_team(r["sy"], "SY")
                if "ug" in dc_cols and dom.ug_team_id is None:
                    dom.ug_team_id = get_or_create_team(r["ug"], "UG")

        app_cols = ({c["name"].lower() for c in inspector.get_columns("applications")}
                    if "applications" in tables else set())
        if {"sy_team", "ug_team"} & app_cols:
            for r in db.execute(text("SELECT id, sy_team, ug_team FROM [applications]")).mappings():
                app = db.get(models.Application, r["id"])
                if app is None:
                    continue
                if "sy_team" in app_cols and app.sy_team_id is None:
                    app.sy_team_id = get_or_create_team(r["sy_team"], "SY")
                if "ug_team" in app_cols and app.ug_team_id is None:
                    app.ug_team_id = get_or_create_team(r["ug_team"], "UG")

        db.commit()
    finally:
        db.close()


def backfill_prod_defaults() -> None:
    """Additive eklenen NOT-NULL-varsayılanlı kolonları mevcut prod satırları için doldurur
    (aksi halde app okurken None → şema doğrulaması patlar). Kolon adı-varlığına göre korumalı."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = {t.lower() for t in inspector.get_table_names()}

    def cols(t: str) -> set[str]:
        return {c["name"].lower() for c in inspector.get_columns(t)} if t.lower() in tables else set()

    # UTC damgası: MSSQL'de CURRENT_TIMESTAMP = GETDATE() = SUNUCU YEREL saati (UTC DEĞİL); ORM her yerde
    # naive-UTC (utcnow) yazdığından backfill de UTC üretmeli, yoksa aynı kolonda karışık zaman dilimi olur.
    utc_now = "CURRENT_TIMESTAMP" if engine.dialect.name == "sqlite" else "GETUTCDATE()"
    with engine.begin() as conn:
        c = cols("SSLCertificates")
        if "source" in c:
            conn.execute(text("UPDATE [SSLCertificates] SET source='manual' WHERE source IS NULL"))
        if "auto_renew" in c:
            conn.execute(text("UPDATE [SSLCertificates] SET auto_renew=0 WHERE auto_renew IS NULL"))
        if "is_internal" in c:
            if "internal" in c:
                conn.execute(text(
                    "UPDATE [SSLCertificates] SET is_internal = CASE WHEN "
                    "LOWER(LTRIM(RTRIM([Internal]))) IN ('1','true','evet','yes') THEN 1 ELSE 0 END "
                    "WHERE is_internal IS NULL"))
            else:
                conn.execute(text("UPDATE [SSLCertificates] SET is_internal=0 WHERE is_internal IS NULL"))
        dc = cols("domain_certificates")
        if "created_at" in dc:
            conn.execute(text(f"UPDATE [domain_certificates] SET created_at={utc_now} WHERE created_at IS NULL"))
        if "updated_at" in dc:
            conn.execute(text(f"UPDATE [domain_certificates] SET updated_at={utc_now} WHERE updated_at IS NULL"))
        u = cols("users")
        if "role" in u:
            conn.execute(text("UPDATE [users] SET role='viewer' WHERE role IS NULL"))
        if "auth_source" in u:
            conn.execute(text("UPDATE [users] SET auth_source='ldap' WHERE auth_source IS NULL"))
        if "is_active" in u:
            conn.execute(text("UPDATE [users] SET is_active=1 WHERE is_active IS NULL"))
        # CT izleme: önceki sürümde kurulmuş discovered_certificates/scan_runs satırlarına 'network' varsay.
        if "origin" in cols("discovered_certificates"):
            conn.execute(text("UPDATE [discovered_certificates] SET origin='network' WHERE origin IS NULL"))
        if "kind" in cols("scan_runs"):
            conn.execute(text("UPDATE [scan_runs] SET kind='network' WHERE kind IS NULL"))
        # rollback provenance: tablo bu kolonlardan ÖNCE kurulmuş satırlarda trigger_type NULL
        # kalır — şema (str, Optional değil) None'ı reddeder, 'manual' en makul geriye dönük varsayım.
        if "trigger_type" in cols("deployment_runs"):
            conn.execute(text("UPDATE [deployment_runs] SET trigger_type='manual' WHERE trigger_type IS NULL"))


def backfill_transfer_proposals() -> None:
    """ONAY MODELİ geçişi: superseded_by dolu ama eski hâlâ aktif YARIM devirler için PENDING öneri
    üretir. İdempotent (uq_proposal_grain)."""
    from app.services import renewal

    db = SessionLocal()
    try:
        halves = (db.query(models.Certificate)
                  .filter(models.Certificate.superseded_by_id.isnot(None),
                          models.Certificate.is_active == True).all())
        for old in halves:
            new = db.get(models.Certificate, old.superseded_by_id)
            if new is None:
                continue
            renewal.propose(db, new, old, username="system", request=None, via="backfill")
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # GÜVENLİK (CWE-798): prod'da (MSSQL) JWT imza anahtarı varsayılan/boş bırakılamaz — kaynaktaki
    # bilinen varsayılanla herkes admin token'ı üretebilir. Dev/SQLite bu kontrolden muaf.
    _s = get_settings()
    if engine.dialect.name != "sqlite" and _s.jwt_secret in ("", "change-me-in-production"):
        raise RuntimeError(
            "JWT_SECRET ayarlanmamış (veya varsayılan 'change-me-in-production') — prod başlatma "
            "engellendi. Güçlü rastgele bir anahtar verin: "
            "python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
    # Prod'da yeni tablolar create_all ile kurulur; mevcut prod tablolarına kolonlar
    # ensure_new_columns ile ADDITIVE eklenir; ardından mevcut veri backfill'lerle tamamlanır.
    Base.metadata.create_all(bind=engine)
    ensure_new_columns()
    ensure_team_type_width()        # RBAC: teams.type NVARCHAR(10) (ADMIN/VIEWER) — seed'den ÖNCE
    backfill_certificate_fields()   # PEM'den fingerprint + san
    backfill_certificate_crypto()   # PEM'den key_size/public_key_type/key_curve/signature_hash (politika/uyum)
    backfill_parent_links()         # AKI/SKI'den parent_id
    ensure_indexes()                # fingerprint kısmi unique index
    backfill_team_owners()          # sy/ug metin → teams + FK (+ [group] e-posta)
    backfill_prod_defaults()        # source/auto_renew/is_internal/role/... NULL doldur
    backfill_transfer_proposals()
    ensure_initial_admin()
    ensure_rbac_seed()              # RBAC: ADMIN/VIEWER singleton + break-glass + tek-seferlik göç
    ensure_service_user()           # otomasyon kullanıcısı (+ ADMIN takım üyeliği)
    ensure_tag_seed()               # etiket kataloğu: tek-seferlik örnek etiketler (Ortam/Kritiklik)
    start_scheduler()
    yield


settings = get_settings()
# docs_url=None: varsayılan /docs, Swagger UI'nin JS/CSS'ini cdn.jsdelivr.net'ten yükler —
# internetsiz/prod ağında (banka) CDN'e erişim yok → sayfa boş + 'SwaggerUIBundle not defined'.
# Bunun yerine aşağıda SELF-HOSTED /docs tanımlanır: aynı arayüz, dosyalar imajın içinden
# (app/static/swagger) servis edilir; internet gerekmez. (CORS ile İLGİSİ YOK: hata, script
# etiketinin dosyayı hiç indirememesinden kaynaklanır.)
app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)

# Swagger UI statikleri /docs/static altında: ön kapıdaki nginx 'location /docs' bloğu bu
# prefix'i zaten backend'e proxy'ler — nginx değişikliği GEREKMEZ.
_SWAGGER_STATIC = Path(__file__).resolve().parent / "static" / "swagger"
app.mount("/docs/static", StaticFiles(directory=str(_SWAGGER_STATIC)), name="swagger-static")


@app.get("/docs", include_in_schema=False)
def swagger_ui_docs():
    """Self-hosted Swagger UI (CDN'siz). Kaynak dosyalar: app/static/swagger/."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{settings.app_name} - Swagger UI",
        swagger_js_url="/docs/static/swagger-ui-bundle.js",
        swagger_css_url="/docs/static/swagger-ui.css",
        swagger_favicon_url="/favicon.ico",
        oauth2_redirect_url="/docs/oauth2-redirect",
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(certificates.router)
app.include_router(domains.router)
app.include_router(dashboard.router)
app.include_router(applications.router)
app.include_router(settings_api.router)
app.include_router(users.router)
app.include_router(proposals.router)
app.include_router(notifications.router)
app.include_router(tags.router)
app.include_router(discovery.router)
app.include_router(policy.router)
app.include_router(jenkins.router)
app.include_router(deployments.router)
app.include_router(issuance.router)


@app.exception_handler(IntegrityError)
async def _integrity_error_handler(request: Request, exc: IntegrityError):
    """Prod'un benzersizlik/NOT NULL kısıtları (ör. UNIQUE(SerialNumber)) ihlal edilirse 500 yerine
    temiz 409 dön. Nadir kenar durum (aynı seri no farklı CA); oturum get_db.finally ile kapanıp geri alınır."""
    log.warning("IntegrityError → 409: %s", getattr(exc, "orig", exc))
    return JSONResponse(status_code=409,
                        content={"detail": "Kayıt eklenemedi: benzersizlik/kısıt çakışması (ör. aynı seri numarası)."})


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}
