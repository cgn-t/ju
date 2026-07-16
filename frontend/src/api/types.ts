export interface TokenResponse {
  access_token: string
  username: string
  role: string
  full_name?: string | null
  email?: string | null
}

export interface Team {
  id: number
  name: string
  type: 'SY' | 'UG' | 'ADMIN' | 'VIEWER'
  email?: string | null
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
  purchased_by?: string | null
  creator?: string | null
  source: string
  vault_path?: string | null
  auto_renew: boolean
  superseded_by_id?: number | null
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
  revocation_status?: string | null      // good | revoked | unknown | null(denetlenmemiş)
  revocation_checked_at?: string | null
  revocation_detail?: string | null
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
  sy_team_id?: number | null
  sy_team_name?: string | null
  status: 'pending' | 'approved' | 'applied' | 'rejected' | 'cancelled'
  signal?: 'ski' | 'subject' | null
  via?: string | null
  live_seen: boolean
  created_by?: string | null
  created_at: string
  decided_by?: string | null
  decided_at?: string | null
  note?: string | null
  can_decide: boolean
}

export interface CertificateChain {
  ancestors: Certificate[]
  self: Certificate
  children: Certificate[]
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
  renewal_also?: string[]
}

export interface MappedCert {
  certificate_id: number
  name: string
  mapping_type: 'server' | 'client'
  valid_to?: string | null
  days_left?: number | null
  serial_number?: string | null
  subject_key_identifier?: string | null
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
}

export interface ChainProbeResult {
  reachable: boolean
  host?: string | null
  port?: number | null
  error?: string | null
  certificates: ChainProbeCert[]
}

export interface ChainImportResult {
  created: string[]
  existing: string[]
  mapped_server?: string | null
  superseded: string[]
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
  ug_team?: Team | null
  sy_team?: Team | null
  server_days_left?: number | null
  client_days_left?: number | null
  certificates: MappedCert[]
  live_check_status?: 'match' | 'mismatch' | 'unreachable' | 'no_mapping' | 'not_checkable' | null
  live_check_detail?: string | null
  live_check_at?: string | null
  pending_proposals?: number
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
  sy_team_ids?: number[]        // yalnız SY tipi (domain formu auto-fill)
  sy_team_names?: string[]
  team_ids?: number[]           // TÜM takımlar (SY/ADMIN/VIEWER) — UsersTab rozetleri
  team_names?: string[]
}

export interface TeamMember {
  id: number
  username: string
  full_name?: string | null
  email?: string | null
}

export interface AuditEntry {
  id: number
  username: string
  action: string
  table_name: string
  record_id?: string | null
  details?: string | null
  ip_address?: string | null
  created_at: string
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
