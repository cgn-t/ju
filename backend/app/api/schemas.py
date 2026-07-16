from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.certtype import normalize_cert_type


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Auth ----
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    full_name: str | None = None
    email: str | None = None


class UserOut(ORMModel):
    id: int
    username: str
    email: str | None
    full_name: str | None
    role: str                        # TÜRETİLMİŞ tier: admin|editor|viewer|none (üyelikten, bkz. effective_role)
    auth_source: str
    is_active: bool
    last_login: datetime | None
    sy_team_ids: list[int] = []      # üye olduğu SY ekiplerinin id'leri
    sy_team_names: list[str] = []
    team_ids: list[int] = []         # üye olduğu TÜM takımların (SY/ADMIN/VIEWER) id'leri
    team_names: list[str] = []


# Doğrudan atanabilen roller: admin(global tam), editor(takım-kapsamlı düzenle), viewer(takım-kapsamlı
# salt-okur), allviewer(global salt-okur), none(yetkisiz — yetkiyi geri almak için). editor/viewer için
# ayrıca SY takım üyeliği (kapsam) gerekir.
UserRole = Literal["admin", "editor", "viewer", "allviewer", "none"]


class UserCreate(BaseModel):
    username: str = Field(max_length=100)
    password: str | None = Field(default=None, max_length=128)  # SHA-256'da 72-bayt limiti yok (düz metin giriş)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    auth_source: Literal["local", "ldap"] = "local"
    role: UserRole | None = None  # verilmezse 'none' → yetkisiz (admin sonra rol atar)


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, max_length=128)  # SHA-256'da 72-bayt limiti yok
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    role: UserRole | None = None  # None = role'e dokunma; admin kullanıcının rolünü buradan değiştirir


# ---- Teams ----
class TeamOut(ORMModel):
    id: int
    name: str
    type: str
    email: str | None


class TeamCreate(BaseModel):
    name: str = Field(max_length=255)
    # ADMIN/VIEWER singleton'ları startup'ta seed edilir; API'den yalnız SY/UG üretilir (bkz. users.create_team).
    type: str = Field(pattern="^(SY|UG|ADMIN|VIEWER)$")
    email: str | None = Field(default=None, max_length=255)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)


# ---- Certificates ----
class CertificateBase(BaseModel):
    name: str = Field(max_length=255)
    serial_number: str | None = Field(default=None, max_length=100)
    issuer: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=500)
    subject_key_identifier: str | None = Field(default=None, max_length=100)
    authority_key_identifier: str | None = Field(default=None, max_length=100)
    cert_type: Literal["root", "intermediate", "leaf"] = "leaf"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    pem_certificate: str | None = None
    extended_key_usage: str | None = Field(default=None, max_length=255)
    san: str | None = None
    fingerprint_sha256: str | None = Field(default=None, max_length=100)
    parent_id: int | None = None
    is_active: bool = True
    is_internal: bool = False
    purchased_by: str | None = Field(default=None, max_length=255)
    creator: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("cert_type", mode="before")
    @classmethod
    def _normalize_cert_type(cls, v):
        """Prod/legacy CertType normalize edilmemiş olabilir ("Intermediate", " LEAF ", "ROOT",
        NULL). cert_type strict Literal olduğundan böyle değerler model_validate'te 500 verirdi —
        merkezi normalize_cert_type ile kanonik forma indirilir (bkz. app.core.certtype)."""
        return normalize_cert_type(v)


class CertificateCreate(CertificateBase):
    pass


class CertificateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    parent_id: int | None = None
    is_active: bool | None = None
    is_internal: bool | None = None
    purchased_by: str | None = Field(default=None, max_length=255)
    creator: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    cert_type: Literal["root", "intermediate", "leaf"] | None = None


class MappedDomainOut(BaseModel):
    domain_id: int
    domain: str
    mapping_type: str


class CertRefOut(BaseModel):
    """Yenileme zinciri bağlantısı için hafif sertifika referansı."""
    id: int
    name: str
    is_active: bool


class CertificateOut(CertificateBase, ORMModel):
    id: int
    source: str
    vault_path: str | None = None
    auto_renew: bool
    superseded_by_id: int | None = None  # yenileme zinciri: yerine geçen kayıt
    created_at: datetime
    updated_at: datetime
    days_left: int | None = None
    # Kripto özellikleri (politika/uyum + PQC) — ORM'den from_attributes ile dolar
    key_size: int | None = None
    public_key_type: str | None = None
    key_curve: str | None = None
    signature_hash: str | None = None
    # İptal (revocation) durumu — OCSP/CRL denetimi
    revocation_status: str | None = None
    revocation_checked_at: datetime | None = None
    revocation_detail: str | None = None
    domains: list[MappedDomainOut] = []
    # Yenileme zinciri bağlantıları — N+1 olmaması için yalnız tekil GET doldurur
    superseded_by_name: str | None = None
    supersedes: list[CertRefOut] = []


class CertificateChainOut(BaseModel):
    ancestors: list["CertificateOut"] = []  # kökten aşağıya sıralı
    self: "CertificateOut"
    children: list["CertificateOut"] = []


class VaultSyncResult(BaseModel):
    """Vault KV'den senkron sonucu."""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    superseded: int = 0  # temkinli devirle işaretlenen öncül sayısı
    errors: list[str] = []


class DeactivateResult(BaseModel):
    """Sertifikayı pasife alma sonucu + bağlı domain SY ekiplerine bilgilendirme özeti."""
    certificate: CertificateOut
    bound_domains: list[str] = []
    notified_recipients: list[str] = []
    teams: list[str] = []
    mail_sent: bool = False
    message: str


class ImportPreview(BaseModel):
    """Import edilen dosyadan çıkarılan alanların önizlemesi."""
    name: str
    serial_number: str
    issuer: str
    subject: str
    subject_key_identifier: str | None
    authority_key_identifier: str | None
    cert_type: str
    valid_from: datetime
    valid_to: datetime
    extended_key_usage: str | None
    san: str | None
    fingerprint_sha256: str
    pem_certificate: str
    already_exists: bool = False
    resolved_parent_id: int | None = None
    resolved_parent_name: str | None = None
    # Yenileme algılama: bu sertifika mevcut bir kaydın yenisi görünüyorsa
    renewal_of_id: int | None = None
    renewal_of_name: str | None = None
    renewal_signal: str | None = None  # "ski" (aynı anahtar) | "subject" (aynı CN+issuer)
    # Devir planı detayı: kullanıcı NEYİN NEYE devredileceğini görerek onaylar
    renewal_of_ski: str | None = None
    renewal_of_valid_to: datetime | None = None
    renewal_of_domains: list[str] = []  # "domain (server)" — devredilecek eşlemeler
    # İlk öncülün dışında devralınacaklar (import TÜM öncülleri devralır)
    renewal_also: list[str] = []


# ---- Domains ----
class DomainBase(BaseModel):
    domain: str = Field(max_length=255)
    external_address: str | None = Field(default=None, max_length=255)
    ug_team_id: int | None = None
    sy_team_id: int | None = None
    ug_team_name: str | None = Field(default=None, max_length=255)  # UG ekip etiketi (serbest metin)
    cert_owner: str | None = Field(default=None, max_length=255)
    lb_update: str | None = Field(default=None, max_length=255)
    env_update: str | None = Field(default=None, max_length=255)
    waf_update: str | None = Field(default=None, max_length=255)
    external_company: str | None = Field(default=None, max_length=255)
    expire_date: datetime | None = None
    info: str | None = None
    mail_addresses: str | None = Field(default=None, max_length=255)
    action_required: str | None = Field(default=None, max_length=255)
    ssl_pinning: str | None = Field(default=None, max_length=255)
    keystore: str | None = Field(default=None, max_length=500)
    servers_to_update: str | None = Field(default=None, max_length=500)


class DomainCreate(DomainBase):
    pass


class DomainUpdate(DomainBase):
    domain: str | None = Field(default=None, max_length=255)


class MappedCertOut(BaseModel):
    certificate_id: int
    name: str
    mapping_type: str
    valid_to: datetime | None
    days_left: int | None
    serial_number: str | None = None
    subject_key_identifier: str | None = None


class DomainOut(DomainBase, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime
    ug_team: TeamOut | None = None
    sy_team: TeamOut | None = None
    server_days_left: int | None = None
    client_days_left: int | None = None
    certificates: list[MappedCertOut] = []
    live_check_status: str | None = None
    live_check_detail: str | None = None
    live_check_at: datetime | None = None
    pending_proposals: int = 0  # bu domain için onay bekleyen devir önerisi sayısı


class MappingCreate(BaseModel):
    certificate_id: int
    mapping_type: str = Field(pattern="^(server|client)$")


# ---- Canlı zincir çekme (domain eklerken) ----
class ChainProbeRequest(BaseModel):
    domain: str


class ChainProbeCert(BaseModel):
    """Canlı TLS bağlantısından çekilen zincirdeki tek sertifikanın önizlemesi."""
    name: str
    cert_type: str
    serial_number: str | None = None
    subject_key_identifier: str | None = None
    fingerprint_sha256: str | None = None
    valid_to: datetime | None = None
    days_left: int | None = None
    already_exists: bool = False
    existing_id: int | None = None


class ChainProbeOut(BaseModel):
    reachable: bool
    host: str | None = None
    port: int | None = None
    error: str | None = None
    certificates: list[ChainProbeCert] = []  # leaf → root sırasıyla


class ChainImportOut(BaseModel):
    created: list[str] = []       # yeni eklenen sertifika adları
    existing: list[str] = []      # zaten kayıtlı olanlar
    mapped_server: str | None = None  # domain'e server olarak bağlanan leaf
    superseded: list[str] = []    # devir ÖNERİSİ üretilen öncül adları (onay bekliyor)


# ---- Devir önerileri (onay) ----
class TransferProposalOut(ORMModel):
    id: int
    old_cert_id: int
    old_cert_name: str | None = None
    new_cert_id: int
    new_cert_name: str | None = None
    domain_id: int | None = None
    domain_name: str | None = None
    mapping_type: str | None = None
    app_dependency_id: int | None = None
    sy_team_id: int | None = None
    sy_team_name: str | None = None
    status: str
    signal: str | None = None
    via: str | None = None
    live_seen: bool = False
    created_by: str | None = None
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    can_decide: bool = False   # bu isteği yapan kullanıcı onaylayabilir mi


class ProposalDecision(BaseModel):
    note: str | None = None


# ---- Ağ keşfi (discovery) ----
class ScanTargetBase(BaseModel):
    name: str = Field(max_length=255)
    kind: Literal["cidr", "host", "inventory"]
    value: str | None = Field(default=None, max_length=255)  # CIDR/host; inventory'de boş
    ports: str | None = Field(default=None, max_length=100)  # virgüllü; boşsa varsayılan portlar
    enabled: bool = True
    sy_team_id: int | None = None


class ScanTargetCreate(ScanTargetBase):
    pass


class ScanTargetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    value: str | None = Field(default=None, max_length=255)
    ports: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    sy_team_id: int | None = None


class ScanTargetOut(ScanTargetBase, ORMModel):
    id: int
    sy_team_name: str | None = None
    created_at: datetime
    updated_at: datetime


class DiscoveredCertificateOut(ORMModel):
    id: int
    host: str
    port: int
    fingerprint_sha256: str
    name: str | None = None
    issuer: str | None = None
    subject: str | None = None
    san: str | None = None
    serial_number: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    days_left: int | None = None
    status: str                          # new | in_inventory | adopted | ignored
    origin: str = "network"              # network (aktif tarama) | ct (crt.sh)
    matched_certificate_id: int | None = None
    matched_certificate_name: str | None = None
    sy_team_id: int | None = None        # hedefin SY ekibi — benimsemede "Oluşturan" olur
    sy_team_name: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    note: str | None = None


class DiscoveredCertificateDetail(DiscoveredCertificateOut):
    pem_certificate: str | None = None
    crtsh_id: str | None = None          # CT bulgusunda crt.sh giriş kimliği (link için)


# ---- Politika / Uyum ----
class PolicyViolationOut(BaseModel):
    certificate_id: int
    name: str | None = None
    issuer: str | None = None
    cert_type: str | None = None
    public_key_type: str | None = None
    key_size: int | None = None
    signature_hash: str | None = None
    valid_to: datetime | None = None
    days_left: int | None = None
    severity: str                        # high | medium | low
    rules: list[str]                     # ihlal kural kodları
    details: list[str]                   # insan-okur açıklamalar


class PolicyReportOut(BaseModel):
    enabled: bool
    total_evaluated: int
    compliant: int
    non_compliant: int
    rule_counts: dict[str, int]          # {rule_code: adet}
    violations: list[PolicyViolationOut]


class PolicyCertResult(BaseModel):
    certificate_id: int
    compliant: bool
    violations: list[dict]               # [{rule, severity, detail}]


class ScanRunOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str                          # running | done | error
    trigger: str | None = None
    kind: str = "network"                # network (ağ taraması) | ct (crt.sh)
    targets_scanned: int
    hosts_reachable: int
    new_findings: int
    error: str | None = None
    created_by: str | None = None


# ---- SY ekip üyeliği ----
class TeamMemberOut(ORMModel):
    id: int          # user id
    username: str
    full_name: str | None = None
    email: str | None = None


class MemberAdd(BaseModel):
    user_id: int


# ---- Etiketler (tags) ----
class TagOut(ORMModel):
    id: int
    name: str
    category: str
    color: str | None = None


class TagCreate(BaseModel):
    name: str = Field(max_length=100)
    category: str = Field(max_length=50)
    color: str | None = Field(default=None, max_length=20)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=20)


# ---- Applications ----
class ApplicationBase(BaseModel):
    app_name: str = Field(max_length=255)
    app_user: str | None = Field(default=None, max_length=255)
    conf_path: str | None = Field(default=None, max_length=500)
    control_method: str | None = Field(default=None, max_length=255)
    dns: str | None = Field(default=None, max_length=255)
    domain_id: int | None = None
    info: str | None = None
    ip_address: str | None = Field(default=None, max_length=100)
    log_path: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    required_commands: str | None = None
    # NOT: Base (dolayısıyla ApplicationOut ÇIKTISI) server_name'i opsiyonel tutar — eski
    # kayıtlarda boş/NULL olabilir; zorunluluk yalnız GİRDİ şemalarında (Create/Update).
    server_name: str | None = Field(default=None, max_length=255)
    service_provider_contact: str | None = Field(default=None, max_length=255)
    start_stop_method: str | None = Field(default=None, max_length=500)
    status: bool = True
    sy_team_id: int | None = None
    ug_team_id: int | None = None


def _server_name_not_blank(v: str | None) -> str | None:
    """Zorunlu Sunucu Adı: yalnız boşluktan oluşamaz; kenar boşlukları kırpılır."""
    if v is not None and not v.strip():
        raise ValueError("Sunucu Adı boş bırakılamaz")
    return v.strip() if v is not None else v


class ApplicationCreate(ApplicationBase):
    server_name: str = Field(min_length=1, max_length=255)  # oluştururken ZORUNLU
    tag_ids: list[int] = []  # atanacak etiket id'leri

    _v_server_name = field_validator("server_name")(_server_name_not_blank)


class ApplicationUpdate(ApplicationBase):
    app_name: str | None = Field(default=None, max_length=255)
    # Güncellemede alanlar opsiyonel (exclude_unset); ama server_name GÖNDERİLİRSE boş olamaz
    server_name: str | None = Field(default=None, min_length=1, max_length=255)
    tag_ids: list[int] | None = None  # None = etiketlere dokunma; [] = tümünü kaldır

    _v_server_name = field_validator("server_name")(_server_name_not_blank)


class AppDependencyCreate(BaseModel):
    target_domain_id: int
    client_cert_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class AppDependencyOut(ORMModel):
    id: int
    app_id: int
    target_domain_id: int
    target_domain_name: str | None = None  # hedef domain adı (kolaylık)
    client_cert_id: int | None = None
    client_cert_name: str | None = None  # mTLS client sertifika adı (varsa)
    client_cert_ski: str | None = None  # mTLS sertifikanın SubjectKeyIdentifier'ı
    note: str | None = None


class ApplicationOut(ApplicationBase, ORMModel):
    id: int
    sy_team: TeamOut | None = None
    ug_team: TeamOut | None = None
    domain: DomainOut | None = None
    dependencies: list[AppDependencyOut] = []
    tags: list[TagOut] = []


# ---- Dashboard / Map ----
class TeamDomainCount(BaseModel):
    team: str
    count: int


class ExpiringCert(BaseModel):
    certificate_id: int
    name: str
    serial_number: str | None
    valid_to: datetime | None
    days_left: int | None
    sy_teams: str
    domains: str


class DashboardOut(BaseModel):
    total_domains: int
    expired_domains: int
    valid_domains: int
    total_certificates: int
    sy_domain_counts: list[TeamDomainCount]
    expiring_certificates: list[ExpiringCert]


class MapNode(BaseModel):
    id: str
    label: str
    node_type: str  # root|intermediate|leaf|domain
    valid_to: datetime | None = None
    days_left: int | None = None


class MapEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str  # hierarchy|server|client


class CertMapOut(BaseModel):
    nodes: list[MapNode]
    edges: list[MapEdge]


class RelEdge(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str  # trust|serves|depends
    via_cert_id: int | None = None
    label: str | None = None


class RelationshipsOut(BaseModel):
    """Sertifikalardan türetilen client↔server ilişki grafiği."""
    nodes: list[MapNode]   # node_type: domain|app
    edges: list[RelEdge]


# ---- Audit ----
class AuditOut(ORMModel):
    id: int
    username: str
    action: str
    table_name: str
    record_id: str | None
    details: str | None
    ip_address: str | None
    created_at: datetime
