from datetime import datetime
from app.core.timeutil import utcnow

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.session import Base

# NOT (CANLI ŞEMA UYUMU): Tablo ve MEVCUT kolon adları canlı (prod, TMTKS00) şemasına eşlenmiştir
# (mapped_column("ProdAdı", ...)). Python attribute adları ve iş mantığı DEĞİŞMEZ. Prod'da OLMAYAN
# app-yeni kolonlar snake_case attribute adıyla durur ve prod'a ADDITIVE eklenir (bkz.
# app/main.py:ensure_new_columns + prod-additive-changes.sql). Yeni tablolar (teams,
# user_teams, transfer_proposals, app_dependencies, notifications, app_settings) prod'da yoktur;
# create_all kurar. Prod [group]/session_cache tablolarına DOKUNULMAZ.


class LowerStr(TypeDecorator):
    """Büyük/küçük harf farkını yutan string (prod 'Server'/'Client' ↔ app 'server'/'client').
    Prod verisini değiştirmeden, okur/yazarken küçük harfe indirir."""

    # MappingType yalnız 'server'/'client' (ASCII) tutar → varchar yeterli; prod da varchar(10) →
    # nvarchar'a çekmeye gerek yok (prod'a dokunmadan tam eşleşme).
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.lower() if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return value.lower() if isinstance(value, str) else value


class Team(Base):
    """SY (sistem yönetimi) ve UG (uygulama geliştirme) takımları. YENİ tablo — prod `[group]`'a
    dokunulmaz ([group] yalnız backfill'de takım e-postası kaynağıdır)."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name", "type", name="uq_team_name_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    # 'SY' (kapsamlı sahiplik) | 'UG' (yalnız etiket) | 'ADMIN' (global full) | 'VIEWER' (global salt-okur).
    # ADMIN/VIEWER singleton takımlardır (startup'ta seed); üyelik yetkiyi belirler (bkz. security.effective_role).
    type: Mapped[str] = mapped_column(Unicode(10))
    email: Mapped[str | None] = mapped_column(Unicode(255))


class Certificate(Base):
    # Prod tablo: SSLCertificates. Mevcut kolonlar prod adıyla eşlenir; app-yeni kolonlar additive.
    __tablename__ = "SSLCertificates"
    __table_args__ = (
        # TEKİL KİMLİK = SHA-256 fingerprint (best practice). SerialNumber DEĞİL: seri yalnız
        # onu VEREN CA içinde benzersizdir (RFC 5280) — farklı CA'lar aynı seriyi verebilir, bu
        # yüzden global SerialNumber unique KULLANILMAZ. SKI de değil (aynı anahtarla yenilenen
        # sertifika aynı SKI'yi taşır). app-yeni kolon; NULL'lar hariç unique.
        Index("ux_sslcertificates_fingerprint", "fingerprint_sha256", unique=True,
              sqlite_where=text("fingerprint_sha256 IS NOT NULL"),
              mssql_where=text("fingerprint_sha256 IS NOT NULL")),
        # X.509 MANTIKSAL kimliği: (Issuer, SerialNumber) — seri veren CA içinde benzersiz.
        # PEM'siz manuel kayıtlarda (fingerprint NULL) mükerrer kimliği yakalar. NULL-güvenli.
        # NOT: Index kolonları DB ADIYLA çözülür (attribute key ile değil) → Issuer/SerialNumber.
        Index("ux_sslcertificates_issuer_serial", "Issuer", "SerialNumber", unique=True,
              sqlite_where=text("SerialNumber IS NOT NULL"),
              mssql_where=text("SerialNumber IS NOT NULL")),
    )

    # --- mevcut prod kolonları (SSLCertificates) ---
    id: Mapped[int] = mapped_column("ID", Integer, primary_key=True)
    name: Mapped[str] = mapped_column("NAME", Unicode(255))
    serial_number: Mapped[str | None] = mapped_column("SerialNumber", Unicode(100))  # kimlik değil; bkz. (Issuer,Serial) index
    issuer: Mapped[str | None] = mapped_column("Issuer", Unicode(500))
    subject: Mapped[str | None] = mapped_column("Subject", Unicode(500))
    subject_key_identifier: Mapped[str | None] = mapped_column("SubjectKeyIdentifier", Unicode(100), index=True)
    authority_key_identifier: Mapped[str | None] = mapped_column("AuthorityKeyIdentifier", Unicode(100), index=True)
    cert_type: Mapped[str] = mapped_column("CertType", Unicode(50), default="leaf")  # root|intermediate|leaf
    valid_from: Mapped[datetime | None] = mapped_column("ValidFrom", DateTime)
    valid_to: Mapped[datetime | None] = mapped_column("ValidTo", DateTime, index=True)
    pem_certificate: Mapped[str | None] = mapped_column("PEMCertificate", UnicodeText)
    extended_key_usage: Mapped[str | None] = mapped_column("ExtendedKeyUsage", Unicode(255))
    is_active: Mapped[bool] = mapped_column("IsActive", Boolean, default=True)
    purchased_by: Mapped[str | None] = mapped_column("SatinAlimYapan", Unicode(255))  # Satın alım yapan ekip/kişi
    creator: Mapped[str | None] = mapped_column("CertificateCreator", Unicode(255))
    notes: Mapped[str | None] = mapped_column("Notes", UnicodeText)
    created_at: Mapped[datetime] = mapped_column("CreatedDate", DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column("ModifiedDate", DateTime, default=utcnow, onupdate=utcnow)
    # --- app-yeni kolonlar (prod'da YOK; additive eklenir) ---
    san: Mapped[str | None] = mapped_column(UnicodeText)  # SubjectAltName (virgülle ayrık DNS/IP)
    fingerprint_sha256: Mapped[str | None] = mapped_column(Unicode(100), index=True)
    # Kripto özellikleri (politika/uyum motoru + gelecekteki PQC envanteri). App-yeni kolonlar; PEM'den
    # parse edilir, mevcut satırlar için startup'ta backfill_certificate_crypto ile doldurulur.
    key_size: Mapped[int | None] = mapped_column(Integer)          # RSA modülüs bit / EC eğri boyu
    public_key_type: Mapped[str | None] = mapped_column(Unicode(20))  # RSA|EC|Ed25519|Ed448|DSA
    key_curve: Mapped[str | None] = mapped_column(Unicode(50))     # EC eğri adı (secp256r1…), else null
    signature_hash: Mapped[str | None] = mapped_column(Unicode(50))  # sha256|sha1|md5|null(EdDSA)
    # İptal (revocation) durumu — OCSP/CRL ile denetlenir (egress-gated). null = denetlenmemiş.
    revocation_status: Mapped[str | None] = mapped_column(Unicode(20))   # good|revoked|unknown|null
    revocation_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revocation_detail: Mapped[str | None] = mapped_column(UnicodeText)   # JSON: method/responder/reason
    # MSSQL kendine referanslı FK'de ON DELETE SET NULL'a izin vermez; DB-cascade YOK, boşaltma
    # uygulama seviyesinde (delete_certificate).
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("SSLCertificates.ID"), index=True)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("SSLCertificates.ID"), index=True)
    # server_default: DB seviyesinde de varsayılan → eski app/manuel INSERT NULL bırakmasın (bkz. prod-additive böl.9)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))  # prod `Internal` metninden türetilir
    source: Mapped[str] = mapped_column(Unicode(20), default="manual", server_default=text("'manual'"))  # manual|vault|live
    vault_path: Mapped[str | None] = mapped_column(Unicode(255))  # Vault KV yolu; anahtar JUMBO'da tutulmaz
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))

    parent: Mapped["Certificate | None"] = relationship(
        remote_side=[id], backref="children", foreign_keys=[parent_id])
    superseded_by: Mapped["Certificate | None"] = relationship(
        remote_side=[id], foreign_keys=[superseded_by_id])
    domain_mappings: Mapped[list["CertificateDomainMap"]] = relationship(
        back_populates="certificate", cascade="all, delete-orphan"
    )


class Domain(Base):
    # Prod tablo: domain_certificates. sy/ug SERBEST METİN kolonları prod'da durur (eski app); app
    # bunları KULLANMAZ, yeni sy_team_id/ug_team_id FK'lerini backfill ile doldurur.
    __tablename__ = "domain_certificates"

    # --- mevcut prod kolonları ---
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(Unicode(255), index=True)
    external_address: Mapped[str | None] = mapped_column(Unicode(255))
    cert_owner: Mapped[str | None] = mapped_column(Unicode(255))
    lb_update: Mapped[str | None] = mapped_column(Unicode(255))  # LoadBalancer güncelleme
    env_update: Mapped[str | None] = mapped_column(Unicode(255))
    waf_update: Mapped[str | None] = mapped_column(Unicode(255))
    external_company: Mapped[str | None] = mapped_column(Unicode(255))  # Dış firma
    expire_date: Mapped[datetime | None] = mapped_column(DateTime)
    info: Mapped[str | None] = mapped_column(UnicodeText)  # Detay
    mail_addresses: Mapped[str | None] = mapped_column(Unicode(255))
    action_required: Mapped[str | None] = mapped_column("Aksiyon_Alma", Unicode(255))  # Aksiyon alma
    ssl_pinning: Mapped[str | None] = mapped_column("SSLPinning", Unicode(255))
    keystore: Mapped[str | None] = mapped_column("Keystore", Unicode(500))
    # --- app-yeni kolonlar (prod'da YOK; additive) ---
    ug_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    sy_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    ug_team_name: Mapped[str | None] = mapped_column(Unicode(255))  # UG ekip etiketi (serbest metin)
    servers_to_update: Mapped[str | None] = mapped_column(Unicode(500))  # Güncellenecek sunucular
    # Canlı doğrulama (drift detection)
    live_check_status: Mapped[str | None] = mapped_column(Unicode(20))  # match|mismatch|unreachable|no_mapping|not_checkable
    live_check_detail: Mapped[str | None] = mapped_column(UnicodeText)
    live_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    ug_team: Mapped[Team | None] = relationship(foreign_keys=[ug_team_id])
    sy_team: Mapped[Team | None] = relationship(foreign_keys=[sy_team_id])
    certificate_mappings: Mapped[list["CertificateDomainMap"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


class CertificateDomainMap(Base):
    # Prod tablo: SSLCertificateDomainMapping (CertID/DomainID/MappingType).
    __tablename__ = "SSLCertificateDomainMapping"
    __table_args__ = (
        # NOT: UniqueConstraint kolonları DB ADIYLA çözer (attribute key ile değil) → CertID/DomainID/MappingType.
        UniqueConstraint("CertID", "DomainID", "MappingType", name="uq_cert_domain_type"),
    )

    id: Mapped[int] = mapped_column("ID", Integer, primary_key=True)
    certificate_id: Mapped[int] = mapped_column("CertID", ForeignKey("SSLCertificates.ID", ondelete="CASCADE"))
    domain_id: Mapped[int] = mapped_column("DomainID", ForeignKey("domain_certificates.id", ondelete="CASCADE"))
    mapping_type: Mapped[str] = mapped_column("MappingType", LowerStr(10))  # 'server' | 'client'

    certificate: Mapped[Certificate] = relationship(back_populates="domain_mappings")
    domain: Mapped[Domain] = relationship(back_populates="certificate_mappings")


class Application(Base):
    # Prod tablo: applications (mevcut kolonlar zaten aynı adda). domain/sy_team/ug_team prod'da
    # SERBEST METİN durur (eski app); app yeni domain_id/sy_team_id/ug_team_id FK'lerini kullanır.
    __tablename__ = "applications"

    # --- mevcut prod kolonları (adlar aynı) ---
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_name: Mapped[str] = mapped_column(Unicode(255))
    app_user: Mapped[str | None] = mapped_column(Unicode(255))
    conf_path: Mapped[str | None] = mapped_column(Unicode(500))
    control_method: Mapped[str | None] = mapped_column(Unicode(255))
    dns: Mapped[str | None] = mapped_column(Unicode(255))
    info: Mapped[str | None] = mapped_column(UnicodeText)
    ip_address: Mapped[str | None] = mapped_column(Unicode(100))
    log_path: Mapped[str | None] = mapped_column(Unicode(500))
    notes: Mapped[str | None] = mapped_column(UnicodeText)
    required_commands: Mapped[str | None] = mapped_column(UnicodeText)
    server_name: Mapped[str | None] = mapped_column(Unicode(255))
    service_provider_contact: Mapped[str | None] = mapped_column(Unicode(255))
    start_stop_method: Mapped[str | None] = mapped_column(Unicode(500))
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- app-yeni kolonlar (prod'da YOK; additive) ---
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("domain_certificates.id", ondelete="SET NULL"), index=True)
    sy_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    ug_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)

    domain: Mapped[Domain | None] = relationship()
    sy_team: Mapped[Team | None] = relationship(foreign_keys=[sy_team_id])
    ug_team: Mapped[Team | None] = relationship(foreign_keys=[ug_team_id])
    dependencies: Mapped[list["AppDependency"]] = relationship(
        back_populates="app", cascade="all, delete-orphan", foreign_keys="AppDependency.app_id"
    )
    tag_links: Mapped[list["ApplicationTag"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list["Tag"]:
        """Uygulamanın etiketleri (ApplicationTag üzerinden). Şema from_attributes bu property'yi
        okur — kodtabanı hiç secondary= kullanmadığından association-object + property deseni."""
        return [link.tag for link in self.tag_links]


class AppDependency(Base):
    """Bir uygulamanın DIŞA (client) bağımlılığı. YENİ tablo (prod'da yok)."""

    __tablename__ = "app_dependencies"
    __table_args__ = (
        UniqueConstraint("app_id", "target_domain_id", name="uq_app_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))  # uq_app_target lider kolon
    target_domain_id: Mapped[int] = mapped_column(ForeignKey("domain_certificates.id", ondelete="CASCADE"), index=True)
    client_cert_id: Mapped[int | None] = mapped_column(
        ForeignKey("SSLCertificates.ID", ondelete="SET NULL"), index=True
    )
    note: Mapped[str | None] = mapped_column(Unicode(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    app: Mapped[Application] = relationship(back_populates="dependencies", foreign_keys=[app_id])
    target_domain: Mapped[Domain] = relationship(foreign_keys=[target_domain_id])
    client_cert: Mapped[Certificate | None] = relationship(foreign_keys=[client_cert_id])

    @property
    def target_domain_name(self) -> str | None:
        return self.target_domain.domain if self.target_domain else None

    @property
    def client_cert_name(self) -> str | None:
        return self.client_cert.name if self.client_cert else None

    @property
    def client_cert_ski(self) -> str | None:
        return self.client_cert.subject_key_identifier if self.client_cert else None


class Tag(Base):
    """Kontrollü, kategorili etiket kataloğu. YENİ tablo (prod'da yok). Uygulamalara ApplicationTag
    ile bağlanır. Aynı isim FARKLI kategoride olabilir (uq_tag_category_name — Team.type deseni)."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("category", "name", name="uq_tag_category_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    category: Mapped[str] = mapped_column(Unicode(50), index=True)
    color: Mapped[str | None] = mapped_column(Unicode(20))  # opsiyonel hex, ör. #2E7D32
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicationTag(Base):
    """Uygulama ↔ etiket (çoktan-çoğa). YENİ tablo (prod'da yok). UserTeam association-object deseni."""

    __tablename__ = "application_tags"
    __table_args__ = (
        UniqueConstraint("application_id", "tag_id", name="uq_application_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped["Application"] = relationship(back_populates="tag_links")
    tag: Mapped["Tag"] = relationship()


class User(Base):
    # Prod tablo: users (username/password/email/created_at mevcut). password_hash→"password";
    # full_name/role/auth_source/is_active/last_login app-yeni (additive).
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Unicode(100), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column("password", Unicode(255))  # sadece lokal hesaplar
    email: Mapped[str | None] = mapped_column(Unicode(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # --- app-yeni kolonlar ---
    full_name: Mapped[str | None] = mapped_column(Unicode(255))
    # server_default: eski app/manuel INSERT NULL bırakmasın (bkz. prod-additive böl.9)
    role: Mapped[str] = mapped_column(Unicode(20), default="viewer", server_default=text("'viewer'"))  # admin|editor|viewer
    auth_source: Mapped[str] = mapped_column(Unicode(10), default="local", server_default=text("'ldap'"))  # local|ldap
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    # Prod tablo: AuditLog (PascalCase kolonlar). ip_address app-yeni (additive).
    __tablename__ = "AuditLog"

    id: Mapped[int] = mapped_column("ID", Integer, primary_key=True)
    username: Mapped[str] = mapped_column("Username", Unicode(100))
    action: Mapped[str] = mapped_column("Action", Unicode(20))  # create|update|delete|login|import
    table_name: Mapped[str] = mapped_column("TableName", Unicode(100))
    record_id: Mapped[str | None] = mapped_column("RecordID", Unicode(50))
    details: Mapped[str | None] = mapped_column("Details", UnicodeText)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, default=utcnow, index=True)
    # --- app-yeni kolon ---
    ip_address: Mapped[str | None] = mapped_column(Unicode(50))


class AppSetting(Base):
    """Kategori bazlı uygulama ayarları. YENİ tablo (prod'da yok)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Unicode(100), primary_key=True)
    category: Mapped[str] = mapped_column(Unicode(20), index=True)
    value: Mapped[str | None] = mapped_column(UnicodeText)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Notification(Base):
    """Gönderilen expiry uyarılarının geçmişi. YENİ tablo (prod'da yok)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    certificate_id: Mapped[int | None] = mapped_column(ForeignKey("SSLCertificates.ID", ondelete="CASCADE"), index=True)
    recipient: Mapped[str | None] = mapped_column(Unicode(500))
    subject: Mapped[str | None] = mapped_column(Unicode(500))
    days_left: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Gönderim kanalı: e-posta paydaş bildirimi 'email'; diğerleri slack|teams|webhook|… .
    # Dedup kanal-bazlıdır: (certificate_id, channel) → mail ile kanal bildirimleri birbirini engellemez.
    channel: Mapped[str] = mapped_column(Unicode(20), default="email", server_default=text("'email'"), index=True)


class MailQueue(Base):
    """SMTP gönderim kuyruğu (outbox). smtp.queue_enabled iken mailler doğrudan gönderilmek
    yerine buraya yazılır; 'mail-queue-drain' job'ı hız-limitine (queue_batch_size /
    queue_interval_minutes) uyarak batch batch gönderir. YENİ tablo (prod'da yok).
    certificate_id FK'siz tutulur (discovered_certificates deseni — MSSQL çoklu-yol cascade'inden kaçınma)."""

    __tablename__ = "mail_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    to_addresses: Mapped[str] = mapped_column(Unicode(1000))              # virgülle çoklu alıcı
    subject: Mapped[str] = mapped_column(Unicode(500))
    body_text: Mapped[str] = mapped_column(UnicodeText)
    body_html: Mapped[str | None] = mapped_column(UnicodeText)            # yoksa düz metin gider
    certificate_id: Mapped[int | None] = mapped_column(Integer, index=True)  # kayıt-bağı; FK yok
    stakeholder: Mapped[str | None] = mapped_column(Unicode(255))         # alıcı paydaş etiketi (izleme)
    days_left: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Unicode(20), default="pending",
                                        server_default=text("'pending'"), index=True)  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Unicode(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class UserTeam(Base):
    """Kullanıcı ↔ SY ekip üyeliği (çoktan-çoğa). YENİ tablo (prod'da yok)."""

    __tablename__ = "user_teams"
    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_user_team"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship()
    team: Mapped["Team"] = relationship()


class TransferProposal(Base):
    """Sertifika devir ÖNERİSİ. YENİ tablo (prod'da yok). Granül = (old_cert, new_cert, domain,
    mapping_type, app_dependency); domain sahibi SY ekibinin onayını bekler."""

    __tablename__ = "transfer_proposals"
    __table_args__ = (
        # Benzersizlik YALNIZ AÇIK öneriler (pending/approved) için — kapalı (rejected/cancelled/applied)
        # aynı granülden birden çok olabilir. Tam-kısıt olsaydı reddedilen bir öneri yeniden önerilince
        # MSSQL IntegrityError verirdi (SQLite NULL'ları ayrı sayıp vermezdi → dev/prod ayrışması).
        # Kapsam _open_proposal (renewal.py) ile birebir aynı.
        Index("uq_proposal_grain_open", "old_cert_id", "new_cert_id", "domain_id", "mapping_type",
              "app_dependency_id", unique=True,
              sqlite_where=text("status IN ('pending','approved')"),
              mssql_where=text("status IN ('pending','approved')")),
    )

    # transfer_proposals'a SSLCertificates'tan İKİ yol (old+new) gelir; MSSQL çoklu cascade yolunu
    # reddeder → FK'lerde DB-cascade YOK, temizlik uygulama seviyesinde.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    old_cert_id: Mapped[int] = mapped_column(ForeignKey("SSLCertificates.ID"), index=True)
    new_cert_id: Mapped[int] = mapped_column(ForeignKey("SSLCertificates.ID"), index=True)
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("domain_certificates.id"), index=True)
    mapping_type: Mapped[str | None] = mapped_column(LowerStr(10))  # server|client
    app_dependency_id: Mapped[int | None] = mapped_column(ForeignKey("app_dependencies.id"), index=True)
    sy_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    status: Mapped[str] = mapped_column(Unicode(12), default="pending", index=True)
    # pending | approved | applied | rejected | cancelled
    signal: Mapped[str | None] = mapped_column(Unicode(20))   # ski | subject
    via: Mapped[str | None] = mapped_column(Unicode(20))      # import|manual|vault-sync|import-chain|live-check|attach|backfill
    live_seen: Mapped[bool] = mapped_column(Boolean, default=False)
    live_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(Unicode(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    decided_by: Mapped[str | None] = mapped_column(Unicode(100))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(UnicodeText)

    old_cert: Mapped["Certificate"] = relationship(foreign_keys=[old_cert_id])
    new_cert: Mapped["Certificate"] = relationship(foreign_keys=[new_cert_id])
    domain: Mapped["Domain | None"] = relationship(foreign_keys=[domain_id])
    sy_team: Mapped["Team | None"] = relationship(foreign_keys=[sy_team_id])


class ScanTarget(Base):
    """Ağ keşif taramasının hedefi: CIDR aralığı, tekil host veya envanter domainleri. YENİ tablo
    (prod'da yok). Yalnız admin yönetir; keşif varsayılan KAPALIdır (bkz. settings 'discovery').
    sy_team_id yalnız etiket/kapsam ipucudur; DB-cascade YOK (takım silinirse orphan zararsız)."""

    __tablename__ = "scan_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(255))
    kind: Mapped[str] = mapped_column(Unicode(20))  # cidr | host | inventory
    value: Mapped[str | None] = mapped_column(Unicode(255))  # CIDR/host; inventory'de boş
    ports: Mapped[str | None] = mapped_column(Unicode(100))  # virgüllü liste; boşsa varsayılan portlar
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    sy_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sy_team: Mapped[Team | None] = relationship(foreign_keys=[sy_team_id])


class DiscoveredCertificate(Base):
    """Ağ taramasında bir endpoint'te (host:port) SUNULAN sertifika bulgusu. YENİ tablo (prod'da yok).
    Envanterdeki kayda FK ile DEĞİL, fingerprint_sha256 ile OKUMA ANINDA eşlenir → MSSQL FK cascade/
    çoklu-yol sorunlarından kaçınılır (bkz. TransferProposal notu). status:
    new (envanter dışı=shadow) | in_inventory | adopted (benimsendi) | ignored (yok sayıldı)."""

    __tablename__ = "discovered_certificates"
    __table_args__ = (
        # Bir endpoint × sunulan sertifika = tek bulgu; yeniden tarama last_seen_at'i günceller. Üç kolon
        # da non-null (bulgu ancak sertifika çekilebildiyse oluşur) → filtered/partial index gerekmez.
        UniqueConstraint("host", "port", "fingerprint_sha256", name="uq_discovered_endpoint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(Unicode(255), index=True)
    port: Mapped[int] = mapped_column(Integer)
    fingerprint_sha256: Mapped[str] = mapped_column(Unicode(100), index=True)
    name: Mapped[str | None] = mapped_column(Unicode(255))  # sunulan leaf CN
    issuer: Mapped[str | None] = mapped_column(Unicode(500))
    subject: Mapped[str | None] = mapped_column(Unicode(500))
    san: Mapped[str | None] = mapped_column(UnicodeText)
    serial_number: Mapped[str | None] = mapped_column(Unicode(100))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    pem_certificate: Mapped[str | None] = mapped_column(UnicodeText)  # benimseme (adopt) için saklanır
    status: Mapped[str] = mapped_column(Unicode(20), default="new", server_default=text("'new'"))
    # Bulgunun kaynağı: network (aktif TLS taraması) | ct (Certificate Transparency / crt.sh). CT
    # bulgularında ağ endpoint'i yoktur → host=<domain>, port=0 yazılır; benzersizlik yine (host,port,
    # fingerprint) ile korunur. crtsh_id: crt.sh giriş kimliği (dedup/izleme; PEM indirmeden önce kullanılır).
    origin: Mapped[str] = mapped_column(Unicode(20), default="network", server_default=text("'network'"))
    crtsh_id: Mapped[str | None] = mapped_column(Unicode(50))
    # Bulguyu üreten tarama hedefinin SY ekibi — benimsemede (adopt) sertifikanın "Oluşturan" (creator)
    # alanına yazılır (kullanıcı kuralı: hedefe hangi takımı verdiysem envanterdeki kayıt da aynı olsun).
    # FK YOK (bu tablonun felsefesi: referanslar okuma anında çözülür); ekip adı Team'den lookup ile alınır.
    sy_team_id: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[str | None] = mapped_column(UnicodeText)


class ScanRun(Base):
    """Bir keşif taraması çalıştırmasının özeti (görev izleme / 'son tarama'). YENİ tablo (prod'da yok)."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Unicode(12), default="running")  # running | done | error
    trigger: Mapped[str | None] = mapped_column(Unicode(20))  # manual | schedule
    kind: Mapped[str] = mapped_column(Unicode(20), default="network",
                                      server_default=text("'network'"))  # network | ct
    targets_scanned: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    hosts_reachable: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    new_findings: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(UnicodeText)
    created_by: Mapped[str | None] = mapped_column(Unicode(100))
