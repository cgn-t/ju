import AddLinkIcon from '@mui/icons-material/AddLink'
import AccountBalanceOutlinedIcon from '@mui/icons-material/AccountBalanceOutlined'
import AlternateEmailOutlinedIcon from '@mui/icons-material/AlternateEmailOutlined'
import AppsOutlinedIcon from '@mui/icons-material/AppsOutlined'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined'
import GppGoodOutlinedIcon from '@mui/icons-material/GppGoodOutlined'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import HandshakeOutlinedIcon from '@mui/icons-material/HandshakeOutlined'
import HubOutlinedIcon from '@mui/icons-material/HubOutlined'
import KeyOutlinedIcon from '@mui/icons-material/KeyOutlined'
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined'
import LinkIcon from '@mui/icons-material/Link'
import MailOutlineOutlinedIcon from '@mui/icons-material/MailOutlineOutlined'
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined'
import NotificationsActiveOutlinedIcon from '@mui/icons-material/NotificationsActiveOutlined'
import PersonOutlineOutlinedIcon from '@mui/icons-material/PersonOutlineOutlined'
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined'
import PushPinOutlinedIcon from '@mui/icons-material/PushPinOutlined'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import SourceOutlinedIcon from '@mui/icons-material/SourceOutlined'
import SyncOutlinedIcon from '@mui/icons-material/SyncOutlined'
import TaskAltOutlinedIcon from '@mui/icons-material/TaskAltOutlined'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import CloudDownloadIcon from '@mui/icons-material/CloudDownload'
import LanguageIcon from '@mui/icons-material/Language'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import SwapHorizIcon from '@mui/icons-material/SwapHoriz'
import WifiTetheringIcon from '@mui/icons-material/WifiTethering'
import {
  Alert, Box, Button, Checkbox, Dialog, DialogContent, FormControlLabel,
  IconButton, MenuItem, Skeleton, Stack, TextField, Tooltip, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Application, Certificate, ChainImportResult, Domain, MappedCert } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { daysLeftColor, daysLeftLabel, sourceLabel, TRANSFER_TOAST_MS } from '../theme'
import { chainImportInactiveWarning, chainImportProposalCount, chainImportSummary } from '../utils/chainImport'
import CertificateDetailDrawer from './CertificateDetailDrawer'
import CertificatePicker from './CertificatePicker'
import {
  CARD_SX, CERT_TYPE_FULL, ChainArrow, ChainCertCard, DetailHeader, DetailTabs, DIALOG_BODY_SX, DIALOG_PAPER_SX, dnPart,
  envLabel, fmtDate, GRID3, GRID4, hostMatches, IconBadge, InfoCard, keyText, MetaItem, PropList, REVOCATION, Section,
  SectionBox, StatusPill, type Tone, ValidityCard,
} from './DetailCards'

interface Props {
  domainId: number | null
  onClose: () => void
}

const LIVE_STATUS: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  match: { label: 'Eşleşiyor — sunulan sertifika envanterle aynı', color: 'success' },
  mismatch: { label: 'EŞLEŞMİYOR — sunulan sertifika bağlı sertifikadan farklı', color: 'error' },
  chain_incomplete: { label: 'Ara sertifika sunucuda eksik', color: 'warning' },
  unreachable: { label: 'Erişilemedi', color: 'warning' },
  no_mapping: { label: 'Server sertifikası bağlanmamış', color: 'warning' },
  not_checkable: { label: 'Kontrol edilemez (wildcard)', color: 'default' },
}

// Sunulan sertifika eşlenen kayıtla aynı ama süresi dolmuşsa "farklı" yerine bunu söyle.
const EXPIRED_SERVED = { label: 'SÜRESİ DOLMUŞ — sunucu süresi dolmuş sertifikayı sunuyor', color: 'error' as const }

function liveStatus(d: Pick<Domain, 'live_check_status' | 'live_check_detail'>) {
  if (d.live_check_status === 'mismatch' && d.live_check_detail) {
    try {
      if (JSON.parse(d.live_check_detail).expired_served) return EXPIRED_SERVED
    } catch { /* bozuk detay: genel etikete düş */ }
  }
  return LIVE_STATUS[d.live_check_status ?? '']
}

export default function DomainDetailDrawer({ domainId, onClose }: Props) {
  const { canEdit } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [selectedCert, setSelectedCert] = useState<Certificate | null>(null)
  const [mappingType, setMappingType] = useState<'server' | 'client'>('server')
  const [replaceOld, setReplaceOld] = useState(true)
  const [nameMismatch, setNameMismatch] = useState<string | null>(null)
  useEffect(() => setNameMismatch(null), [domainId])
  const [importEnvironment, setImportEnvironment] = useState('')
  const [openCertId, setOpenCertId] = useState<number | null>(null)
  const [tab, setTab] = useState<'summary' | 'certs' | 'internal' | 'live'>('summary')
  useEffect(() => { setTab('summary'); setOpenCertId(null) }, [domainId])
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))

  const { data: domain, isLoading } = useQuery<Domain>({
    queryKey: ['domain', domainId],
    queryFn: async () => (await api.get(`/domains/${domainId}`)).data,
    enabled: domainId !== null,
  })

  const serverLeafId = domain?.certificates.find((c) => c.mapping_type === 'server' && c.cert_type === 'leaf')?.certificate_id
  const { data: leafDetail } = useQuery<Certificate>({
    queryKey: ['certificate', serverLeafId],
    queryFn: async () => (await api.get(`/certificates/${serverLeafId}`)).data,
    enabled: domainId !== null && serverLeafId !== undefined,
  })
  const { data: allApps } = useQuery<Application[]>({
    queryKey: ['applications', ''],
    queryFn: async () => (await api.get('/applications')).data,
    enabled: domainId !== null,
  })

  const { data: certs } = useQuery<Certificate[]>({
    queryKey: ['certificates', ''],
    queryFn: async () => (await api.get('/certificates')).data,
    enabled: domainId !== null && canEdit,
  })

  // Seçilen eşleme türüyle zaten bağlı sertifikalar — tekrar bağlanamaz (409 önlenir)
  const alreadyMapped = useMemo(
    () => new Set((domain?.certificates ?? [])
      .filter((c) => c.mapping_type === mappingType)
      .map((c) => c.certificate_id)),
    [domain, mappingType],
  )

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['domain', domainId] })
    queryClient.invalidateQueries({ queryKey: ['domains'] })
    queryClient.invalidateQueries({ queryKey: ['certificates'] })
    queryClient.invalidateQueries({ queryKey: ['cert-map'] })
  }

  const attach = useMutation({
    mutationFn: async () =>
      (await api.post(`/domains/${domainId}/certificates`, {
        certificate_id: selectedCert!.id, mapping_type: mappingType,
      })).data,
    onSuccess: (d: { warning?: string } | null) => {
      enqueueSnackbar('Sertifika bağlandı', { variant: 'success' })
      if (d?.warning) {
        enqueueSnackbar(d.warning, { variant: 'warning', autoHideDuration: TRANSFER_TOAST_MS })
      }
      setSelectedCert(null)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const liveCheck = useMutation({
    mutationFn: async () => (await api.post(`/domains/${domainId}/live-check`)).data,
    onSuccess: (d: Domain) => {
      const status = liveStatus(d)
      enqueueSnackbar(status?.label ?? 'Kontrol tamamlandı',
                      { variant: status?.color === 'success' ? 'success' : status?.color === 'error' ? 'error' : 'info' })
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const detach = useMutation({
    mutationFn: async ({ certId, type }: { certId: number; type: string }) =>
      api.delete(`/domains/${domainId}/certificates/${certId}`, { params: { mapping_type: type } }),
    onSuccess: () => {
      enqueueSnackbar('Bağlantı kaldırıldı', { variant: 'success' })
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // Mismatch/no_mapping düzeltme: canlıdaki zinciri içe aktar, leaf'i server eşle.
  // ONAY MODELİ: domainde zaten aktif server varsa devir ANINDA olmaz — SY onayına
  // düşen bir öneri üretilir (canlıda görüldü kanıtıyla).
  const importChain = useMutation({
    mutationFn: async (allowNameMismatch: boolean = false) =>
      (await api.post<ChainImportResult>(`/domains/${domainId}/import-chain`,
        null, { params: { supersede: replaceOld, environment: importEnvironment || undefined,
                          allow_name_mismatch: allowNameMismatch || undefined } })).data,
    onSuccess: (r) => {
      setNameMismatch(null)
      const summary = chainImportSummary(r)
      enqueueSnackbar(summary.charAt(0).toUpperCase() + summary.slice(1),
                      { variant: 'success', autoHideDuration: chainImportProposalCount(r) ? TRANSFER_TOAST_MS : undefined })
      const inactiveWarning = chainImportInactiveWarning(r)
      if (inactiveWarning) {
        enqueueSnackbar(inactiveWarning, { variant: 'warning', autoHideDuration: TRANSFER_TOAST_MS })
      }
      invalidate()
      liveCheck.mutate()
    },
    onError: (e) => {
      // 409: sunulan sertifika domain adresini kapsamıyor — kullanıcı bilerek onaylarsa aktarılır
      if (isAxiosError(e) && e.response?.status === 409) setNameMismatch(apiErrorMessage(e))
      else enqueueSnackbar(apiErrorMessage(e), { variant: 'error' })
    },
  })

  const server = domain?.certificates.find((c) => c.mapping_type === 'server' && c.cert_type === 'leaf')
  const trusted = (domain?.certificates ?? []).filter((c) => c.mapping_type === 'client')
  const live = domain ? liveStatus(domain) : undefined
  const certActions = (c: MappedCert) => (
    <>
      {canEdit && (
        <Tooltip title="Bağlantıyı kaldır">
          <IconButton size="small" color="error"
                      onClick={() => detach.mutate({ certId: c.certificate_id, type: c.mapping_type })}>
            <LinkOffIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </>
  )
  const leaf = server ? leafDetail : undefined
  const sans = (leaf?.san ?? '').split(',').map((x) => x.trim()).filter(Boolean)
  const host = (domain?.domain ?? '').replace(/^https?:\/\//, '').split('/')[0].replace(/:\d+$/, '').toLowerCase()
  const covers = sans.some((n) => hostMatches(host, n))
  const serverChain = (domain?.certificates ?? []).filter((c) => c.mapping_type === 'server')
  const apps = (allApps ?? []).filter((a) => a.domain_id === domainId
    || (a.dependencies ?? []).some((d) => d.target_domain_id === domainId))

  return (
    <Dialog open={domainId !== null} onClose={onClose} fullScreen={fullScreen} maxWidth="lg" fullWidth
            slotProps={{ paper: { sx: DIALOG_PAPER_SX } }}>
      {isLoading || !domain ? (
        <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={500} /></Box>
      ) : (
        <>
          <DetailHeader
            icon={<LanguageIcon />} tone={statusTone(domain.server_days_left)} onClose={onClose}
            title={<span title={domain.domain}>{domain.domain}</span>}
            meta={<>
              <StatusPill tone={statusTone(domain.server_days_left)} label={statusLabel(domain.server_days_left)} />
              {server?.valid_to && <MetaItem label="ValidTo" value={new Date(server.valid_to).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' })} />}
              {domain.sy_team?.name && <MetaItem label="SY" value={domain.sy_team.name} />}
              {envLabel(leaf?.environment) && <MetaItem value={envLabel(leaf?.environment)} />}
            </>}
            actions={tab !== 'live' &&
              <Button variant="outlined" size="small" startIcon={<WifiTetheringIcon />} disabled={liveCheck.isPending}
                      onClick={() => { setTab('live'); liveCheck.mutate() }} sx={{ bgcolor: 'background.paper' }}>
                {liveCheck.isPending ? 'Kontrol ediliyor…' : 'Şimdi Doğrula'}
              </Button>
            }
            tabs={
              <DetailTabs value={tab} onChange={setTab} scrollable={fullScreen} items={[
                { value: 'summary', label: 'Özet', icon: <DashboardOutlinedIcon /> },
                { value: 'certs', label: 'Sertifikalar', icon: <VerifiedUserOutlinedIcon />, count: domain.certificates.length },
                { value: 'internal', label: 'Kurum İçi Bilgiler', icon: <BusinessOutlinedIcon /> },
                { value: 'live', label: 'Canlı Doğrulama', icon: <WifiTetheringIcon /> },
              ]} />
            } />
          <DialogContent sx={DIALOG_BODY_SX}>
            {(domain.pending_proposals ?? 0) > 0 && (
              <Alert severity="warning" icon={<SwapHorizIcon />} sx={{ mb: 2 }}
                     action={<Button color="inherit" size="small" component={RouterLink} to="/proposals">
                               Onaya git</Button>}>
                Bu domain için <b>{domain.pending_proposals}</b> değişiklik talebi SY onayı bekliyor.
              </Alert>
            )}

            {tab === 'summary' && (
              <Stack spacing={2}>
                <ValidityCard cert={server} warnDays={domain.notify_days ?? 30}
                              warnDaysNote={domain.notify_days ? "domainin Bildirim Gün Sayısı" : "varsayılan süre"}
                              emptyText="Bu domaine bağlı server sertifikası yok. Sertifikalar sekmesinden bağlayabilirsiniz." />
                <Section title="Durum">
                  <Box sx={GRID4}>
                    <InfoCard title="Zincir" icon={<LinkIcon />} onClick={() => setTab('certs')}
                              value={`${serverChain.length} sertifika`} color={chainChip(domain, serverChain).color}
                              sub={chainChip(domain, serverChain).label} />
                    <InfoCard title="İptal Durumu" icon={<GppGoodOutlinedIcon />}
                              value={leaf ? (REVOCATION[leaf.revocation_status ?? 'null'] ?? REVOCATION.null).label : '—'}
                              color={leaf ? (REVOCATION[leaf.revocation_status ?? 'null'] ?? REVOCATION.null).color : 'default'}
                              sub={leaf?.revocation_checked_at ? `Son kontrol: ${fmtDate(leaf.revocation_checked_at)}` : 'Henüz kontrol edilmedi'} />
                    <InfoCard title="Canlı Doğrulama" icon={<WifiTetheringIcon />} onClick={() => setTab('live')}
                              value={live ? live.label.split(' — ')[0] : 'Kontrol edilmedi'}
                              color={live?.color ?? 'default'}
                              sub={domain.live_check_at ? `Son kontrol: ${fmtDate(domain.live_check_at)}` : undefined} />
                    <InfoCard title="Değişiklik Talepleri" icon={<SwapHorizIcon />} value={`${domain.pending_proposals ?? 0} bekleyen`}
                              color={(domain.pending_proposals ?? 0) > 0 ? 'warning' : 'default'}
                              sub={(domain.pending_proposals ?? 0) > 0 ? 'SY onayı bekliyor' : 'Onay bekleyen yok'} />
                  </Box>
                </Section>
                <Section title="Sertifika" aside={server ? 'Bağlı server sertifikası' : undefined}>
                  <Box sx={GRID4}>
                    <InfoCard title="Common Name (CN)" icon={<BadgeOutlinedIcon />} onClick={() => setTab('certs')}
                              value={server?.name ?? 'Bağlanmamış'}
                              sub={server ? [CERT_TYPE_FULL[server.cert_type], leaf?.extras?.validation_type].filter(Boolean).join(' · ') : 'Server sertifikası yok'} />
                    <InfoCard title="Issuer (CA)" icon={<AccountBalanceOutlinedIcon />} value={server ? dnPart(server.issuer, 'CN') ?? '—' : '—'}
                              sub={dnPart(server?.issuer, 'O') ?? undefined} />
                    <InfoCard title="Public Key" icon={<KeyOutlinedIcon />} value={keyText(leaf)}
                              sub={leaf?.signature_hash ? `Signature: ${leaf.signature_hash.toUpperCase().replace('SHA', 'SHA-')}` : undefined} />
                    <InfoCard title="SubjectAltName (SAN)" icon={<DnsOutlinedIcon />} value={sans.length ? `${sans.length} ad` : '—'}
                              chip={leaf ? (covers ? { label: 'Alan adını kapsıyor', color: 'success' } : { label: 'Alan adını kapsamıyor', color: 'error' }) : undefined} />
                  </Box>
                </Section>
                <Section title="Sahiplik">
                  <Box sx={GRID4}>
                    <InfoCard title="SY Takımı" icon={<GroupsOutlinedIcon />} onClick={() => setTab('internal')}
                              value={domain.sy_team?.name ?? '—'} sub={domain.sy_team?.email ?? undefined} />
                    <InfoCard title="UG Takımı" icon={<GroupsOutlinedIcon />} onClick={() => setTab('internal')}
                              value={domain.ug_team_name ?? domain.ug_team?.name ?? '—'} />
                    <InfoCard title="Bağlı Uygulamalar" icon={<AppsOutlinedIcon />} value={apps.length ? `${apps.length} uygulama` : 'Yok'}
                              sub={apps.length ? apps.slice(0, 3).map((a) => a.app_name).join(', ') + (apps.length > 3 ? '…' : '') : undefined} />
                    <InfoCard title="Trusted Sertifikalar" icon={<HandshakeOutlinedIcon />} onClick={() => setTab('certs')}
                              value={trusted.length ? `${trusted.length} sertifika` : 'Yok'}
                              sub={trusted.length ? `En yakın bitiş: ${daysLeftLabel(domain.client_days_left)}` : undefined} />
                  </Box>
                </Section>
                <Section title="Yapılandırma">
                  <Box sx={GRID4}>
                    <InfoCard title="Dış Adres" icon={<PublicOutlinedIcon />} value={domain.external_address || '—'} />
                    <InfoCard title="Bildirim Gün Sayısı" icon={<NotificationsActiveOutlinedIcon />}
                              value={domain.notify_days ? `${domain.notify_days} gün` : '30 gün'}
                              sub={domain.notify_days ? 'Bitişten önce uyarı' : 'Varsayılan'} />
                    <InfoCard title="Kaynak" icon={<SourceOutlinedIcon />} value={leaf ? sourceLabel(leaf.source) : '—'}
                              sub={leaf?.creator ? `Oluşturan: ${leaf.creator}` : undefined} />
                    <InfoCard title="Ortam" icon={<LayersOutlinedIcon />} value={envLabel(leaf?.environment) ?? '—'} />
                  </Box>
                </Section>
                {leaf && (
                  <Section title="Kimlik">
                    <PropList rows={[
                      { label: 'Serial Number', value: leaf.serial_number },
                      { label: 'SHA-256 Fingerprint', value: leaf.fingerprint_sha256 },
                      { label: 'Subject', value: leaf.subject },
                      { label: 'Issuer', value: leaf.issuer },
                      ...(leaf.extras ? [{ label: 'SPKI Pin (SHA-256)', value: leaf.extras.spki_pin_sha256 }] : []),
                    ]} />
                  </Section>
                )}
              </Stack>
            )}

            {tab === 'certs' && (
              <Stack spacing={2}>
                <SectionBox title={`Server zinciri (${serverChain.length})`}>
                  {serverChain.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">Henüz server sertifikası bağlanmamış</Typography>
                  ) : (
                    <Stack spacing={0}>
                      {serverChain.map((c, i) => (
                        <Box key={`${c.certificate_id}-server`}>
                          {i > 0 && <ChainArrow />}
                          <ChainCertCard index={i + 1} cert={c} onOpen={() => setOpenCertId(c.certificate_id)}
                                         actions={certActions(c)} />
                        </Box>
                      ))}
                    </Stack>
                  )}
                </SectionBox>
                <SectionBox title={`Trusted sertifikalar (${trusted.length})`}>
                  {trusted.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">Bu domaine Trusted sertifika bağlanmamış</Typography>
                  ) : (
                    <Stack spacing={1}>
                      {trusted.map((c) => (
                        <ChainCertCard key={`${c.certificate_id}-client`} cert={c}
                                       badges={<StatusPill size="small" tone="info" label="Trusted" />}
                                       onOpen={() => setOpenCertId(c.certificate_id)} actions={certActions(c)} />
                      ))}
                    </Stack>
                  )}
                </SectionBox>
            {canEdit && (
              <SectionBox title="Sertifika Bağla">
                {/* Dar drawer'da tek satır sıkışıyordu (tip seçici 'S…' diye kırpılıyordu):
                    seçici kendi satırında TAM genişlik, tip + buton ikinci satırda. */}
                <Stack spacing={1.5}>
                  <CertificatePicker
                    options={(certs ?? []).filter((c) => c.is_active
                      && (mappingType !== 'server' || c.cert_type === 'leaf'))}
                    label="Sertifika seç (ad, SKI, Serial Number ile ara)"
                    value={selectedCert} onChange={setSelectedCert}
                    disabledIds={alreadyMapped} disabledLabel="zaten bağlı"
                  />
                  {mappingType === 'server' && (
                    <Typography variant="caption" color="text.secondary">
                      Server olarak yalnız Leaf sertifika seçilir — zincir (Intermediate/Root)
                      otomatik eklenir.
                    </Typography>
                  )}
                  <Stack direction="row" spacing={1}>
                    <TextField select size="small" label="Bağlantı Tipi" value={mappingType}
                               sx={{ flexGrow: 1 }}
                               onChange={(e) => setMappingType(e.target.value as 'server' | 'client')}>
                      <MenuItem value="server">Server</MenuItem>
                      <MenuItem value="client">Trusted</MenuItem>
                    </TextField>
                    <Button variant="contained" startIcon={<AddLinkIcon />} sx={{ px: 3, flexShrink: 0 }}
                            disabled={!selectedCert || alreadyMapped.has(selectedCert.id) || attach.isPending}
                            onClick={() => attach.mutate()}>
                      Bağla
                    </Button>
                  </Stack>
                </Stack>
              </SectionBox>
            )}
              </Stack>
            )}

            {tab === 'internal' && (
              <Box sx={GRID3}>
                <InfoCard title="SY Takımı" icon={<GroupsOutlinedIcon />} value={domain.sy_team?.name ?? '—'} />
                <InfoCard title="E-Mail (SY takımı)" icon={<AlternateEmailOutlinedIcon />} value={domain.sy_team?.email ?? '—'} />
                <InfoCard title="UG Takımı" icon={<GroupsOutlinedIcon />} value={domain.ug_team_name ?? domain.ug_team?.name ?? '—'} />
                <InfoCard title="Sertifika Sahibi" icon={<PersonOutlineOutlinedIcon />} value={domain.cert_owner || '—'} />
                <InfoCard title="Mail Adresleri" icon={<MailOutlineOutlinedIcon />} value={domain.mail_addresses || '—'} />
                <InfoCard title="Dış Adres" icon={<PublicOutlinedIcon />} value={domain.external_address || '—'} />
                <InfoCard title="LoadBalancer Güncelleme" icon={<HubOutlinedIcon />} value={domain.lb_update || '—'} />
                <InfoCard title="WAF Güncelleme" icon={<ShieldOutlinedIcon />} value={domain.waf_update || '—'} />
                <InfoCard title="Ortam Güncelleme" icon={<SyncOutlinedIcon />} value={domain.env_update || '—'} />
                <InfoCard title="Aksiyon Alma" icon={<TaskAltOutlinedIcon />} value={domain.action_required || '—'} />
                <InfoCard title="SSL Pinning" icon={<PushPinOutlinedIcon />} value={domain.ssl_pinning || '—'} />
                <InfoCard title="Dış Firma" icon={<BusinessOutlinedIcon />} value={domain.external_company || '—'} />
                <InfoCard title="Bildirim Gün Sayısı" icon={<NotificationsActiveOutlinedIcon />}
                          value={domain.notify_days ? `${domain.notify_days} gün` : '30 gün'}
                          sub={domain.notify_days ? 'Bitişten önce uyarı' : 'Varsayılan'} />
                <InfoCard title="Güncellenecek Sunucular" icon={<DnsOutlinedIcon />} value={domain.servers_to_update || '—'} />
                <InfoCard title="Keystore" icon={<KeyOutlinedIcon />} value={domain.keystore || '—'} />
                <Box sx={{ gridColumn: '1 / -1', display: 'grid' }}>
                  <InfoCard title="Detay" icon={<NotesOutlinedIcon />} value={domain.info || '—'} />
                </Box>
              </Box>
            )}

            {tab === 'live' && (
              <Stack spacing={2}>
            <Box sx={(t) => ({ ...CARD_SX, p: { xs: 2, md: 2.5 }, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap',
                               background: `linear-gradient(120deg, ${alpha(live && live.color !== 'default' ? t.palette[live.color].main : t.palette.text.secondary, t.palette.mode === 'dark' ? 0.14 : 0.07)} 0%, ${t.palette.background.paper} 50%)` })}>
              <IconBadge size={44} tone={live?.color ?? 'default'}><WifiTetheringIcon /></IconBadge>
              <Box sx={{ flexGrow: 1, minWidth: 200 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  {live ? live.label : domain.live_check_status ?? 'Henüz canlı doğrulama yapılmadı'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {domain.live_check_at ? `Son kontrol: ${new Date(domain.live_check_at).toLocaleString('tr-TR')}` : 'Sunucuya bağlanıp sunulan sertifikayı envanterle karşılaştırır.'}
                </Typography>
              </Box>
              <Button variant="contained" disableElevation startIcon={<WifiTetheringIcon />}
                      disabled={liveCheck.isPending} onClick={() => liveCheck.mutate()}>
                {liveCheck.isPending ? 'Kontrol ediliyor…' : 'Şimdi Doğrula'}
              </Button>
            </Box>
            {domain.live_check_detail && (() => {
              try {
                const d = JSON.parse(domain.live_check_detail)
                const rows = [
                  d.served_cn && { label: 'Sunulan Sertifika (CN)', value: `${d.served_cn} — ValidTo: ${d.served_valid_to ? new Date(d.served_valid_to).toLocaleDateString('tr-TR') : '—'}` },
                  d.matched_certificate && { label: 'Eşleşen Kayıt', value: d.matched_certificate },
                  d.expected && { label: 'Beklenen (bağlı)', value: d.expected.join(', ') },
                  d.error && { label: 'Hata', value: d.error },
                  d.reason && { label: 'Not', value: d.reason },
                  d.name_warning && d.name_warning !== d.reason && { label: 'Uyarı', value: d.name_warning },
                  d.chain_warning && d.chain_warning !== d.reason && { label: 'Zincir uyarısı', value: d.chain_warning },
                  d.date_note && { label: 'Tarih farkı', value: d.date_note },
                ].filter(Boolean) as { label: string; value: string }[]
                return rows.length ? <PropList title="Son kontrolün ayrıntısı" rows={rows.map((r) => ({ ...r, mono: false }))} /> : null
              } catch { return null }
            })()}
            {canEdit && ((domain.live_check_status === 'mismatch' && liveStatus(domain) !== EXPIRED_SERVED)
                         || domain.live_check_status === 'no_mapping') && (
              <Box sx={{ ...CARD_SX, borderColor: 'warning.main', p: 2 }}>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  Sunucudaki gerçek sertifika envanterle uyuşmuyor. Canlıdaki zinciri
                  içe aktarabilirsiniz; domain boşsa <b>server</b> olarak bağlanır, zaten
                  aktif bir sertifika varsa <b>değişiklik talebi</b> oluşturulur (SY onayına düşer).
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }} useFlexGap>
                  <TextField select required label="Ortam" size="small" sx={{ minWidth: 140 }}
                             value={importEnvironment} onChange={(e) => setImportEnvironment(e.target.value)}
                             error={!importEnvironment}>
                    <MenuItem value="prod">Prod</MenuItem>
                    <MenuItem value="test">Test</MenuItem>
                  </TextField>
                  <Button size="small" variant="contained" color="warning"
                          startIcon={<CloudDownloadIcon />}
                          disabled={importChain.isPending || liveCheck.isPending || !importEnvironment}
                          onClick={() => importChain.mutate(false)}>
                    {importChain.isPending ? 'Aktarılıyor…' : 'Canlıdaki Sertifikayı İçe Aktar'}
                  </Button>
                  <FormControlLabel
                    control={<Checkbox size="small" checked={replaceOld}
                                       onChange={(e) => setReplaceOld(e.target.checked)} />}
                    label={<Typography variant="body2">Eski kayıt için değişiklik talebi üret</Typography>}
                  />
                </Stack>
                {nameMismatch && (
                  <Alert severity="error" sx={{ mt: 1 }}
                         action={<Button color="inherit" size="small" disabled={importChain.isPending}
                                         onClick={() => importChain.mutate(true)}>Yine de aktar</Button>}>
                    {nameMismatch}
                  </Alert>
                )}
              </Box>
            )}
              </Stack>
            )}
          </DialogContent>
        </>
      )}
      <CertificateDetailDrawer certId={openCertId} onClose={() => setOpenCertId(null)} onSelectCert={setOpenCertId} />
    </Dialog>
  )
}

function statusTone(days: number | null | undefined): Tone {
  const c = daysLeftColor(days)
  return c === 'default' ? 'default' : c
}

function statusLabel(days: number | null | undefined) {
  if (days === null || days === undefined) return 'Sertifika yok'
  if (days < 0) return 'Süresi dolmuş'
  if (days <= 30) return 'Süresi yaklaşıyor'
  return 'Geçerli'
}

function chainChip(d: Domain, chain: MappedCert[]): { label: string; color: Tone } {
  if (d.live_check_status === 'chain_incomplete') return { label: 'Ara sertifika sunucuda eksik', color: 'warning' }
  if (!chain.length) return { label: 'Bağlı sertifika yok', color: 'default' }
  if (chain.some((c) => (c.days_left ?? 0) < 0)) return { label: 'Süresi dolmuş sertifika var', color: 'error' }
  return chain.some((c) => c.cert_type === 'root') ? { label: 'Zincir tam', color: 'success' }
    : { label: 'Root kayıtlı değil', color: 'default' }
}

