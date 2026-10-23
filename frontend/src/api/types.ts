export interface TokenResponse {
  access_token: string
  username: string
  role: string
  full_name?: string | null
  email?: string | null
  photo?: string | null        // LDAP: AD fotoğrafı (data URL)
  team_groups?: string[]       // LDAP: ekip grupları (ör. SY-BBB)
}

export interface Team {
  id: number
  name: string
  type: 'SY' | 'UG' | 'ADMIN' | 'VIEWER'
  email?: string | null
  member_count?: number   // yalnız GET /teams
  domain_count?: number
  app_count?: number
}

export interface MappedDomain {
  domain_id: number
  domain: string
  mapping_type: 'server' | 'client'
}

export interface Certificate {
  id: number
  name: string
  serial_number?: string | null
  issuer?: string | null
  subject?: string | null
  subject_key_identifier?: string | null
  authority_key_identifier?: string | null
  cert_type: 'root' | 'intermediate' | 'leaf'
  valid_from?: string | null
  valid_to?: string | null
  pem_certificate?: string | null
  extended_key_usage?: string | null
  san?: string | null
  fingerprint_sha256?: string | null
  parent_id?: number | null
  is_active: boolean
  is_internal: boolean
  environment?: 'prod' | 'test' | null
  purchased_by?: string | null
  creator?: string | null
  source: string
  vault_path?: string | null
  auto_renew: boolean
  superseded_by_id?: number | null
  chain_added?: string[] | null
  notes?: string | null
  created_at: string
  updated_at: string
  days_left?: number | null
  domains: MappedDomain[]
  // Yenileme zinciri bağlantıları — yalnız tekil GET doldurur
  superseded_by_name?: string | null
  supersedes?: CertRef[]
  // Kripto özellikleri (politika/uyum + PQC)
  key_size?: number | null
  public_key_type?: string | null
  key_curve?: string | null
  signature_hash?: string | null
  // İptal (revocation) durumu — OCSP/CRL
  revocation_status?: string | null      // good | revoked | unknown | unreachable | not_checkable | null(denetlenmemiş)
  revocation_checked_at?: string | null
  revocation_detail?: string | null
  // PEM'den okunan ek bilgiler — yalnız tekil GET doldurur
  extras?: CertExtras | null
  can_edit?: boolean | null   // yalnız tekil GET: bu kullanıcı düzenleyebilir mi
  domain_count?: number | null // sayfalı liste: bağlı domain sayısı (domains en fazla 50 kayıt)
}

export interface CertExtras {
  spki_pin_sha256: string
  signature_algorithm?: string | null
  validation_type?: 'EV' | 'OV' | 'DV' | 'IV' | null
  policy_oids: string[]
  ocsp_urls: string[]
  ca_issuers_urls: string[]
  crl_urls: string[]
  key_usage: string[]
  basic_constraints_ca?: boolean | null
  basic_constraints_path_length?: number | null
  sct_count?: number | null
}

// ---- Politika / Uyum ----
export interface PolicyViolation {
  certificate_id: number
  name?: string | null
  issuer?: string | null
  cert_type?: string | null
  public_key_type?: string | null
  key_size?: number | null
  signature_hash?: string | null
  valid_to?: string | null
  days_left?: number | null
  severity: 'high' | 'medium' | 'low'
  rules: string[]
  details: string[]
}

export interface PolicyReport {
  enabled: boolean
  total_evaluated: number
  compliant: number
  non_compliant: number
  rule_counts: Record<string, number>
  violations: PolicyViolation[]
}

export interface PolicyCounts {
  enabled: boolean
  total_evaluated: number
  compliant: number
  non_compliant: number
  rule_counts: Record<string, number>
}

export interface PolicyViolationPage extends PolicyCounts {
  items: PolicyViolation[]
  total: number
  page: number
  size: number
  severity_counts: Record<string, number>
}

export interface CertRef {
  id: number
  name: string
  is_active: boolean
}

export interface TransferProposal {
  id: number
  old_cert_id: number
  old_cert_name?: string | null
  new_cert_id: number
  new_cert_name?: string | null
  domain_id?: number | null
  domain_name?: string | null
  mapping_type?: 'server' | 'client' | null
  app_dependency_id?: number | null
  app_id?: number | null
  app_name?: string | null
  kind?: 'transfer' | 'trusted_add' | 'server_add' | 'server_remove' | 'date_fix'
  sy_team_id?: number | null
  sy_team_name?: string | null
  status: 'pending' | 'approved' | 'applied' | 'rejected' | 'cancelled'
  signal?: 'ski' | 'subject' | null
  via?: string | null
  live_seen: boolean
  created_by?: string | null
  created_by_name?: string | null
  created_at: string
  decided_by?: string | null
  decided_at?: string | null
  note?: string | null
  can_decide: boolean
  /** date_fix: kayıttaki tarihler ve sertifikanın kendisindeki tarihler */
  record_valid_from?: string | null
  record_valid_to?: string | null
  cert_valid_from?: string | null
  cert_valid_to?: string | null
}

export interface CertificateChain {
  ancestors: Certificate[]
  self: Certificate
  children: Certificate[]
}

/** Zincir Kontrolü bulgusu: kayıttaki değer ile PEM'den hesaplanan arasındaki fark. */
export interface ChainCheckFinding {
  certificate_id: number
  name: string | null
  kind: 'type' | 'parent' | 'subject_key_identifier' | 'authority_key_identifier'
  current: string
  expected: string
}

export interface ImportPreview {
  name: string
  serial_number: string
  issuer: string
  subject: string
  subject_key_identifier?: string | null
  authority_key_identifier?: string | null
  cert_type: string
  valid_from: string
  valid_to: string
  extended_key_usage?: string | null
  san?: string | null
  fingerprint_sha256?: string | null
  pem_certificate: string
  already_exists: boolean
  resolved_parent_id?: number | null
  resolved_parent_name?: string | null
  renewal_of_id?: number | null
  renewal_of_name?: string | null
  renewal_signal?: 'ski' | 'subject' | null
  renewal_of_ski?: string | null
  renewal_of_valid_to?: string | null
  renewal_of_domains?: string[]
  renewal_of_apps?: string[]
  renewal_also?: string[]
  // Envanterdeki tüm olası öncüller (en olası önce); birden çoksa talep için kullanıcı seçer
  renewal_candidates?: RenewalCandidate[]
}

export interface RenewalCandidate {
  id: number
  name: string
  signal: 'ski' | 'subject'
  subject_key_identifier?: string | null
  valid_to?: string | null
  domains: string[]
  apps: string[]
}

export interface MappedCert {
  certificate_id: number
  name: string
  mapping_type: 'server' | 'client'
  cert_type: 'root' | 'intermediate' | 'leaf'
  valid_from?: string | null
  valid_to?: string | null
  days_left?: number | null
  issuer?: string | null
  serial_number?: string | null
  subject_key_identifier?: string | null
  is_active?: boolean
}

export interface ChainProbeCert {
  name: string
  cert_type: string
  serial_number?: string | null
  subject_key_identifier?: string | null
  fingerprint_sha256?: string | null
  valid_to?: string | null
  days_left?: number | null
  already_exists: boolean
  existing_id?: number | null
  issuer_name?: string | null
  cross_signed_root?: boolean
  extra_chain?: boolean
}

export interface ChainProbeResult {
  reachable: boolean
  host?: string | null
  port?: number | null
  error?: string | null
  certificates: ChainProbeCert[]
  name_warning?: string | null
}

export interface ChainImportResult {
  created: string[]
  existing: string[]
  mapped_server?: string | null
  superseded: string[]
  added?: string[]
  removed?: string[]
  inactive?: string[]
}

export interface Domain {
  id: number
  domain: string
  external_address?: string | null
  ug_team_id?: number | null
  sy_team_id?: number | null
  ug_team_name?: string | null
  cert_owner?: string | null
  lb_update?: string | null
  env_update?: string | null
  waf_update?: string | null
  external_company?: string | null
  expire_date?: string | null
  info?: string | null
  mail_addresses?: string | null
  action_required?: string | null
  ssl_pinning?: string | null
  keystore?: string | null
  servers_to_update?: string | null
  notify_days?: number | null
  ug_team?: Team | null
  sy_team?: Team | null
  server_days_left?: number | null
  client_days_left?: number | null
  certificates: MappedCert[]
  live_check_status?: 'match' | 'mismatch' | 'chain_incomplete' | 'unreachable' | 'no_mapping' | 'not_checkable' | null
  live_check_detail?: string | null
  live_check_at?: string | null
  pending_proposals?: number
  can_edit?: boolean | null   // yalnız tekil GET: bu kullanıcı düzenleyebilir mi
}

export interface AppDependency {
  id: number
  app_id: number
  target_domain_id: number
  target_domain_name?: string | null
  client_cert_id?: number | null
  client_cert_name?: string | null
  client_cert_ski?: string | null
  note?: string | null
}

export interface AppTrustedCert {
  id: number
  app_id: number
  cert_id?: number | null
  cert_name?: string | null
  cert_ski?: string | null
  cert_valid_to?: string | null
  note?: string | null
}

export interface Application {
  id: number
  app_name: string
  app_user?: string | null
  conf_path?: string | null
  control_method?: string | null
  dns?: string | null
  domain_id?: number | null
  info?: string | null
  ip_address?: string | null
  log_path?: string | null
  notes?: string | null
  required_commands?: string | null
  server_name?: string | null
  service_provider_contact?: string | null
  start_stop_method?: string | null
  status: boolean
  sy_team_id?: number | null
  ug_team_id?: number | null
  sy_team?: Team | null
  ug_team?: Team | null
  domain?: Domain | null
  dependencies?: AppDependency[]
  trusted_certs?: AppTrustedCert[]
  tags?: Tag[]
}

export interface Tag {
  id: number
  name: string
  category: string
  color?: string | null
}

export interface DashboardData {
  total_domains: number
  expired_domains: number
  valid_domains: number
  total_certificates: number
  expired_certificates: number
  sy_domain_counts: { team: string; count: number }[]
  expiring_certificates: {
    certificate_id: number
    name: string
    serial_number?: string | null
    valid_to?: string | null
    days_left?: number | null
    sy_teams: string
    domains: string
  }[]
}

export interface CertMapData {
  nodes: { id: string; label: string; node_type: string; valid_to?: string | null; days_left?: number | null }[]
  edges: { id: string; source: string; target: string; edge_type: string }[]
}

export interface RelationshipsData {
  nodes: { id: string; label: string; node_type: string; valid_to?: string | null; days_left?: number | null }[]
  edges: { id: string; source: string; target: string; edge_type: string; via_cert_id?: number | null; label?: string | null }[]
}

export interface AppUser {
  id: number
  username: string
  email?: string | null
  full_name?: string | null
  role: string
  auth_source: string
  is_active: boolean
  last_login?: string | null
  created_at?: string | null
  sy_team_ids?: number[]        // yalnız SY tipi (domain formu auto-fill)
  sy_team_names?: string[]
  team_ids?: number[]           // TÜM takımlar (SY/ADMIN/VIEWER/UG) — UsersTab rozetleri
  team_names?: string[]
  // Uyum/Değişiklik Talebi/Keşif/Dağıtım sayfa görünürlüğü (bkz. usePageAccess)
  page_access?: Record<string, boolean>
  // Üst navigasyon linki görünürlüğü — page_access'ten farkı: SY üyeliği carve-out'u yok
  nav_page_access?: Record<string, boolean>
}

export interface TeamMember {
  id: number
  username: string
  full_name?: string | null
  email?: string | null
}

export type AuditCategory = 'changes' | 'approval' | 'security' | 'system'

export interface AuditEntry {
  id: number
  username: string
  action: string
  table_name: string
  record_id?: string | null
  details?: string | null
  ip_address?: string | null
  created_at: string
  user_full_name?: string | null  // işlemi yapanın Ad Soyad'ı (LDAP ile dolar)
  category?: AuditCategory | null
  summary?: string | null      // tek satırlık okunur özet (sunucuda üretilir)
  record_label?: string | null // kaydın okunur adı (sertifika/domain adı…)
}

export interface AuditList {
  items: AuditEntry[]
  capped: boolean   // filtreye uyan kayıt sayısı limiti aştı
  limit: number
}

export interface AuditFacet { value: string; count: number }

export interface AuditFacets {
  actions: AuditFacet[]
  tables: AuditFacet[]
  users: AuditFacet[]
  categories: Record<AuditCategory, number>
  total: number
}

export interface AuditMeta {
  categories: Record<AuditCategory, string>
  actions: Record<string, string>
  action_tone: Record<string, 'success' | 'info' | 'error' | 'warning'>
  tables: Record<string, string>
  fields: Record<string, string>
  values: Record<string, Record<string, string>>  // alan → {kod değeri: etiket}
}

// ---- Mail gönderim geçmişi (notifications + mail_queue birleşik) ----
export interface MailHistoryEntry {
  id: number
  source: 'notification' | 'queue'
  certificate_id?: number | null
  certificate_name?: string | null
  domain_id?: number | null
  domain_name?: string | null
  recipient?: string | null
  subject?: string | null
  days_left?: number | null
  channel: string
  status: 'sent' | 'pending' | 'failed'
  error?: string | null
  attempts?: number | null
  sent_at?: string | null      // en son bilinen an: delivered_at varsa o, yoksa queued_at
  queued_at?: string | null    // karar/kuyruğa alınma anı
  delivered_at?: string | null // GERÇEK teslim anı — henüz teslim edilmediyse null
  mail_type: MailType           // konudan türetilir (sunucu)
  stakeholder?: string | null   // alıcı paydaş etiketi
  recipients: string[]          // alıcılar ayrık
  retryable: boolean            // başarısız + alıcısı belli → yeniden kuyruğa alınabilir
}

export type MailType = 'expiry' | 'expired' | 'revoked' | 'deactivated' | 'proposal' | 'other'
export type MailStatus = 'sent' | 'pending' | 'failed'

export interface MailHistoryList {
  items: MailHistoryEntry[]
  capped: boolean
  limit: number
}

export interface MailHistoryFacets {
  statuses: Record<MailStatus, number>
  types: Record<MailType, number>
  total: number
}

export interface MailHistoryDetail extends MailHistoryEntry {
  body_text?: string | null
  body_html?: string | null
}

// ---- Ağ keşfi (discovery) ----
export type DiscoveryStatus = 'new' | 'in_inventory' | 'adopted' | 'ignored'

export interface DiscoveredCertificate {
  id: number
  host: string
  port: number
  fingerprint_sha256: string
  name?: string | null
  issuer?: string | null
  subject?: string | null
  san?: string | null
  serial_number?: string | null
  valid_from?: string | null
  valid_to?: string | null
  days_left?: number | null
  status: DiscoveryStatus
  origin: 'network' | 'ct'          // network (aktif tarama) | ct (crt.sh)
  matched_certificate_id?: number | null
  matched_certificate_name?: string | null
  sy_team_id?: number | null        // hedefin SY ekibi — benimsemede "Oluşturan" olur
  sy_team_name?: string | null
  first_seen_at: string
  last_seen_at: string
  note?: string | null
  pem_certificate?: string | null   // yalnız tekil GET (detay) doldurur
  crtsh_id?: string | null          // CT bulgusunda crt.sh giriş kimliği (yalnız detay)
}

export interface ScanTarget {
  id: number
  name: string
  kind: 'cidr' | 'host' | 'inventory'
  value?: string | null
  ports?: string | null
  enabled: boolean
  sy_team_id?: number | null
  sy_team_name?: string | null
  created_at: string
  updated_at: string
}

export interface ScanRun {
  id: number
  started_at: string
  finished_at?: string | null
  status: 'running' | 'done' | 'error'
  trigger?: string | null
  kind: 'network' | 'ct'
  targets_scanned: number
  hosts_reachable: number
  new_findings: number
  error?: string | null
  created_by?: string | null
}

// ---- Dağıtım akışı (Jenkins DAG editörü) ----
export type DeploymentEnvKind = 'ns' | 'waf' | 'windows' | 'linux' | 'custom'

export interface JenkinsJobParameter {
  name: string
  type?: string | null
  default?: string | null
  description?: string | null
  choices?: string[] | null
}

export interface FlowParamRow {
  key: string
  value: string
}

export interface FlowNodeData {
  label: string
  jenkins_job: string
  environment: DeploymentEnvKind
  params: FlowParamRow[]
}

export interface FlowNode {
  id: string
  position: { x: number; y: number }
  data: FlowNodeData
}

export interface FlowEdge {
  id: string
  source: string
  target: string
}

export interface FlowDefinition {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export interface DeploymentFlowSummary {
  id: number
  app_id: number
  app_name?: string | null
  name: string
  description?: string | null
  created_by?: string | null
  updated_by?: string | null
  created_at: string
  updated_at: string
}

export interface DeploymentFlow extends DeploymentFlowSummary {
  definition: FlowDefinition
}

export type DeploymentStepStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'cancelled'
export type DeploymentRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

export type DeploymentRunTriggerType = 'manual' | 'retry' | 'rerun'

export interface DeploymentRunStep {
  id: number
  node_id: string
  node_label: string
  jenkins_job: string
  params_snapshot: Record<string, string>
  depends_on: string[]
  status: DeploymentStepStatus
  jenkins_build_number?: number | null
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number | null
  error_message?: string | null
}

export interface DeploymentRunSummary {
  id: number
  flow_id?: number | null
  app_id?: number | null
  flow_name_snapshot: string
  status: DeploymentRunStatus
  triggered_by?: string | null
  trigger_type: DeploymentRunTriggerType
  source_run_id?: number | null
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number | null
  created_at: string
}

export interface DeploymentRun extends DeploymentRunSummary {
  steps: DeploymentRunStep[]
}

// ---- Sunucu-taraflı sayfalı listeler ----
export interface PageMeta {
  total: number
  page: number
  size: number
  counts: Record<string, number>
  facets: Record<string, Record<string, number>>
}
export interface DomainPage extends PageMeta { items: Domain[] }
export interface DomainOption { id: number; domain: string; sy_team_id?: number | null }
export interface CertificateOption {
  id: number
  name: string
  cert_type: 'root' | 'intermediate' | 'leaf'
  is_active: boolean
  environment?: 'prod' | 'test' | null
  valid_to?: string | null
  days_left?: number | null
  subject_key_identifier?: string | null
  serial_number?: string | null
  san?: string | null
}
export interface CertificateTreeRow {
  cert: Certificate
  depth: number
  has_children: boolean
  root_id: number
  root_name: string
}
export interface CertificateGroupStat { members: number; domain_links: number; worst_days?: number | null }
export interface CertificatePage extends PageMeta {
  items: CertificateTreeRow[]
  groups: Record<string, CertificateGroupStat>
}
export interface ApplicationPage extends PageMeta { items: Application[] }
export interface DiscoveryPage extends PageMeta { items: DiscoveredCertificate[]; has_ct: boolean }
export interface ProposalPage extends PageMeta { items: TransferProposal[]; domain_name?: string | null }

/** Profil sayfası: kullanıcının LDAP/AD kaydı (GET /auth/me/directory, /users/{id}/directory). */
export interface DirectoryPerson {
  dn: string
  name: string
  title: string
  department: string
  mail: string
}

export interface DirectoryProfile {
  username: string
  status: 'ok' | 'local' | 'disabled' | 'not_found' | 'error'
  message: string
  dn?: string
  ou_path?: string[]
  photo?: string | null
  summary?: { key: string; label: string; value: string }[]
  account_flags?: string[]
  managers?: DirectoryPerson[]       // yakından uzağa: [0] doğrudan yönetici
  team_groups?: string[]             // Ayarlar > LDAP 'Ekip grubu OU'su' altındaki gruplar (ör. SY-BBB)
}

/** Genel Durum / Ekibim (GET /summary/teams, /summary/teams/{id}). */
export type TeamHealth = 'critical' | 'warning' | 'ok'
export interface MissingDetail {
  no_pem: number
  domains_without_cert: number
  no_team_email: boolean
  domains_without_team: number
}
export interface TeamSummaryRow {
  team_id: number
  team: string
  email?: string | null
  status: TeamHealth
  members: number
  applications: number
  domains: number
  certificates: number
  expired: number
  expiring_soon: number
  nearest_days?: number | null
  pending_proposals: number
  oldest_pending_days?: number | null
  policy_violations: number
  live_problems: number
  missing_info: number
  missing_detail: MissingDetail
}
export interface SummaryProposal {
  id: number
  label: string
  kind: string
  domain_id?: number | null
  domain?: string | null
  app?: string | null
  old_cert?: string | null
  new_cert?: string | null
  team_id?: number | null
  team?: string | null
  created_at?: string | null
  age_days?: number | null
}
export interface TeamOverview {
  scope: 'all' | 'team'
  generated_at: string
  expiring_soon_days: number
  totals: {
    teams: number
    domains: number
    certificates: number
    expired: number
    expired_teams: number
    expiring_soon: number
    nearest_days?: number | null
    pending_proposals: number
    oldest_pending_days?: number | null
    live_problems: number
    policy_violations: number
    missing_info: number
    missing_detail: MissingDetail
    status_counts: Record<TeamHealth, number>
  }
  teams: TeamSummaryRow[]
  upcoming_months: { month: string; count: number }[]
  upcoming_certs: { id: number; name: string; valid_to?: string | null; days_left?: number | null }[]
  oldest_proposals: SummaryProposal[]
}
export interface TeamAttentionCert {
  id: number
  name: string
  cert_type?: string | null
  valid_to?: string | null
  days_left?: number | null
  domains: string[]
  last_mail_at?: string | null
  open_proposals: string[]
}
export interface TeamAttentionItem {
  kind: 'live' | 'no_cert' | 'policy' | 'no_pem'
  name: string
  detail: string
  domain_id?: number | null
  certificate_id?: number | null
}
export interface TeamDetail extends TeamSummaryRow {
  expiring_soon_days: number
  certificates_attention: TeamAttentionCert[]
  pending: SummaryProposal[]
  attention: TeamAttentionItem[]
}

/** Sertifika detayı 'Etkilenenler' sekmesi (GET /certificates/{id}/impact). */
export interface CertificateImpact {
  certificate_id: number
  domains: { domain_id: number; domain: string; mapping_type?: string | null; team?: string | null }[]
  applications: { app_id: number; app_name: string; relation: string; via?: string | null; team?: string | null; active: boolean }[]
  recipients: { label: string; emails: string[]; reasons: string[]; effective_days: number; starts_on?: string | null }[]
  fallback: boolean
  mail_enabled: boolean
  expired: boolean
}

/** Sistem Sağlığı (GET /system/health, admin). */
export interface HealthJob {
  id: string
  label: string
  enabled: boolean
  last_run_at?: string | null
  manual: boolean
  status?: 'ok' | 'error' | null
  summary?: string | null
  duration_s?: number | null
  next_run_at?: string | null
}
export interface SystemHealth {
  generated_at: string
  jobs: HealthJob[]
  mail_week: { sent: number; failed: number; pending: number; refused: number; fallback: number }
  missing: {
    domains_without_team: number
    certs_without_recipient: number
    certs_without_pem: number
    apps_without_team: number
    teams_without_email: number
  }
  connections: {
    smtp: { enabled: boolean; host?: string | null; fallback_address?: string | null; queue_enabled: boolean }
    ldap: { enabled: boolean; server?: string | null }
    database: boolean
    version: string
  }
}
