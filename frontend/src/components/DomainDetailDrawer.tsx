import AddLinkIcon from '@mui/icons-material/AddLink'
import CloseIcon from '@mui/icons-material/Close'
import CloudDownloadIcon from '@mui/icons-material/CloudDownload'
import LanguageIcon from '@mui/icons-material/Language'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import SwapHorizIcon from '@mui/icons-material/SwapHoriz'
import WifiTetheringIcon from '@mui/icons-material/WifiTethering'
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogContent, DialogTitle, FormControlLabel,
  IconButton, MenuItem, Skeleton, Stack, Tab, Tabs, TextField, Tooltip, Typography,
  useMediaQuery, useTheme,
} from '@mui/material'
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
  CERT_TYPE_FULL, ChainArrow, ChainCertCard, CopyField, dnPart, envLabel, fmtDate, GRID3, GRID4, hostMatches,
  InfoCard, keyText, REVOCATION, SectionBox, type Tone, ValidityCard,
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

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>{value || '—'}</Typography>
    </Box>
  )
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
      <Tooltip title="Sertifika detayını aç">
        <IconButton size="small" onClick={() => setOpenCertId(c.certificate_id)}><OpenInNewIcon fontSize="small" /></IconButton>
      </Tooltip>
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
            slotProps={{ paper: { sx: { height: { md: '88vh' } } } }}>
      {isLoading || !domain ? (
        <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={500} /></Box>
      ) : (
        <>
          <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1.25, pb: 0.5, pr: 7 }}>
            <LanguageIcon color="action" />
            <Typography variant="h6" component="span" noWrap title={domain.domain} sx={{ fontWeight: 700 }}>
              {domain.domain}
            </Typography>
            <Chip size="small" color={daysLeftColor(domain.server_days_left)} label={statusLabel(domain.server_days_left)} />
            <IconButton aria-label="Kapat" onClick={onClose} sx={{ position: 'absolute', right: 12, top: 12 }}>
              <CloseIcon />
            </IconButton>
          </DialogTitle>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant={fullScreen ? "scrollable" : "standard"} scrollButtons={false}
                sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}>
            <Tab value="summary" label="Özet" />
            <Tab value="certs" label={`Sertifikalar (${domain.certificates.length})`} />
            <Tab value="internal" label="Kurum İçi Bilgiler" />
            <Tab value="live" label="Canlı Doğrulama" />
          </Tabs>
          <DialogContent sx={{ pt: 2.5 }}>
            {(domain.pending_proposals ?? 0) > 0 && (
              <Alert severity="warning" icon={<SwapHorizIcon />} sx={{ mb: 2 }}
                     action={<Button color="inherit" size="small" component={RouterLink} to="/proposals">
                               Onaya git</Button>}>
                Bu domain için <b>{domain.pending_proposals}</b> değişiklik talebi SY onayı bekliyor.
              </Alert>
            )}

            {tab === 'summary' && (
              <Stack spacing={2}>
                <ValidityCard cert={server} emptyText="Bu domaine bağlı server sertifikası yok. Sertifikalar sekmesinden bağlayabilirsiniz." />
                <Box sx={GRID4}>
                  <InfoCard title="Common Name (CN)" onClick={() => setTab('certs')}
                            value={server?.name ?? 'Bağlanmamış'}
                            sub={server ? [CERT_TYPE_FULL[server.cert_type], envLabel(leaf?.environment)].filter(Boolean).join(' · ') : 'Server sertifikası yok'} />
                  <InfoCard title="Issuer (CA)" value={server ? dnPart(server.issuer, 'CN') ?? '—' : '—'}
                            sub={dnPart(server?.issuer, 'O') ?? undefined} />
                  <InfoCard title="Public Key" value={keyText(leaf)}
                            sub={leaf?.signature_hash ? `Signature: ${leaf.signature_hash.toUpperCase().replace('SHA', 'SHA-')}` : undefined} />
                  <InfoCard title="SubjectAltName (SAN)" value={sans.length ? `${sans.length} ad` : '—'}
                            chip={leaf ? (covers ? { label: 'Alan adını kapsıyor', color: 'success' } : { label: 'Alan adını kapsamıyor', color: 'error' }) : undefined} />
                  <InfoCard title="Zincir" onClick={() => setTab('certs')}
                            value={`${serverChain.length} sertifika`}
                            chip={chainChip(domain, serverChain)} />
                  <InfoCard title="İptal Durumu" value={leaf ? (REVOCATION[leaf.revocation_status ?? 'null'] ?? REVOCATION.null).label : '—'}
                            color={leaf ? (REVOCATION[leaf.revocation_status ?? 'null'] ?? REVOCATION.null).color : 'default'}
                            sub={leaf?.revocation_checked_at ? `Son kontrol: ${fmtDate(leaf.revocation_checked_at)}` : 'Henüz kontrol edilmedi'} />
                  <InfoCard title="Canlı Doğrulama" onClick={() => setTab('live')}
                            value={live ? live.label.split(' — ')[0] : 'Kontrol edilmedi'}
                            color={live?.color ?? 'default'}
                            sub={domain.live_check_at ? `Son kontrol: ${fmtDate(domain.live_check_at)}` : undefined} />
                  <InfoCard title="Değişiklik Talepleri" value={`${domain.pending_proposals ?? 0} bekleyen`}
                            color={(domain.pending_proposals ?? 0) > 0 ? 'warning' : 'default'}
                            sub={(domain.pending_proposals ?? 0) > 0 ? 'SY onayı bekliyor' : 'Onay bekleyen yok'} />
                  <InfoCard title="SY Takımı" onClick={() => setTab('internal')}
                            value={domain.sy_team?.name ?? '—'} sub={domain.sy_team?.email ?? undefined} />
                  <InfoCard title="UG Takımı" onClick={() => setTab('internal')}
                            value={domain.ug_team_name ?? domain.ug_team?.name ?? '—'} />
                  <InfoCard title="Bağlı Uygulamalar" value={apps.length ? `${apps.length} uygulama` : 'Yok'}
                            sub={apps.length ? apps.slice(0, 3).map((a) => a.app_name).join(', ') + (apps.length > 3 ? '…' : '') : undefined} />
                  <InfoCard title="Trusted Sertifikalar" onClick={() => setTab('certs')}
                            value={trusted.length ? `${trusted.length} sertifika` : 'Yok'}
                            sub={trusted.length ? `En yakın bitiş: ${daysLeftLabel(domain.client_days_left)}` : undefined} />
                  <InfoCard title="Dış Adres" value={domain.external_address || '—'} />
                  <InfoCard title="Bildirim Gün Sayısı"
                            value={domain.notify_days ? `${domain.notify_days} gün` : '30 gün'}
                            sub={domain.notify_days ? 'Bitişten önce uyarı' : 'Varsayılan'} />
                  <InfoCard title="Kaynak" value={leaf ? sourceLabel(leaf.source) : '—'}
                            sub={leaf?.creator ? `Oluşturan: ${leaf.creator}` : undefined} />
                  <InfoCard title="Ortam" value={envLabel(leaf?.environment) ?? '—'} />
                </Box>
                {leaf && (
                  <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2 }}>
                    <Typography variant="overline" color="text.secondary">Kimlik</Typography>
                    <Box sx={{ display: 'grid', gap: 2, mt: 0.5, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
                      <CopyField label="Serial Number" value={leaf.serial_number} />
                      <CopyField label="SHA-256 Fingerprint" value={leaf.fingerprint_sha256} />
                      <CopyField label="Subject" value={leaf.subject} />
                      <CopyField label="Issuer" value={leaf.issuer} />
                    </Box>
                  </Box>
                )}
              </Stack>
            )}

            {tab === 'certs' && (
              <Stack spacing={2}>
                <SectionBox title={`Server zinciri (${serverChain.length})`}>
                  {serverChain.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">Henüz server sertifikası bağlanmamış</Typography>
                  ) : (
                    <Stack spacing={1}>
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
                                       badges={<Chip size="small" color="info" label="Trusted" />}
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
                    label="Sertifika seç (ad, SKI, seri no ile ara)"
                    value={selectedCert} onChange={setSelectedCert}
                    disabledIds={alreadyMapped} disabledLabel="zaten bağlı"
                  />
                  {mappingType === 'server' && (
                    <Typography variant="caption" color="text.secondary">
                      Server olarak yalnız leaf (uç) sertifika seçilir — zincir (intermediate/root)
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
                <InfoCard title="SY Takımı" value={domain.sy_team?.name ?? '—'} />
                <InfoCard title="E-Mail (SY takımı)" value={domain.sy_team?.email ?? '—'} />
                <InfoCard title="UG Takımı" value={domain.ug_team_name ?? domain.ug_team?.name ?? '—'} />
                <InfoCard title="Sertifika Sahibi" value={domain.cert_owner || '—'} />
                <InfoCard title="Mail Adresleri" value={domain.mail_addresses || '—'} />
                <InfoCard title="Dış Adres" value={domain.external_address || '—'} />
                <InfoCard title="LoadBalancer Güncelleme" value={domain.lb_update || '—'} />
                <InfoCard title="WAF Güncelleme" value={domain.waf_update || '—'} />
                <InfoCard title="Ortam Güncelleme" value={domain.env_update || '—'} />
                <InfoCard title="Aksiyon Alma" value={domain.action_required || '—'} />
                <InfoCard title="SSL Pinning" value={domain.ssl_pinning || '—'} />
                <InfoCard title="Dış Firma" value={domain.external_company || '—'} />
                <InfoCard title="Bildirim Gün Sayısı"
                          value={domain.notify_days ? `${domain.notify_days} gün` : '30 gün'}
                          sub={domain.notify_days ? 'Bitişten önce uyarı' : 'Varsayılan'} />
                <InfoCard title="Güncellenecek Sunucular" value={domain.servers_to_update || '—'} />
                <InfoCard title="Keystore" value={domain.keystore || '—'} />
                <Box sx={{ gridColumn: '1 / -1', display: 'grid' }}>
                  <InfoCard title="Detay" value={domain.info || '—'} />
                </Box>
              </Box>
            )}

            {tab === 'live' && (
              <Stack spacing={2}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }} useFlexGap>
              <Button size="small" variant="outlined" startIcon={<WifiTetheringIcon />}
                      disabled={liveCheck.isPending} onClick={() => liveCheck.mutate()}>
                {liveCheck.isPending ? 'Kontrol ediliyor…' : 'Şimdi Doğrula'}
              </Button>
              {domain.live_check_status && (
                <Chip size="small" color={liveStatus(domain)?.color ?? 'default'}
                      label={liveStatus(domain)?.label ?? domain.live_check_status} />
              )}
              {domain.live_check_at && (
                <Typography variant="caption" color="text.secondary">
                  Son kontrol: {new Date(domain.live_check_at).toLocaleString('tr-TR')}
                </Typography>
              )}
            </Stack>
            {domain.live_check_detail && (() => {
              try {
                const d = JSON.parse(domain.live_check_detail)
                return (
                  <Box sx={{ bgcolor: 'background.default', borderRadius: 1, p: 1.5 }}>
                    {d.served_cn && <Field label="Sunulan Sertifika (CN)" value={`${d.served_cn} — bitiş: ${d.served_valid_to ? new Date(d.served_valid_to).toLocaleDateString('tr-TR') : '—'}`} />}
                    {d.matched_certificate && <Field label="Eşleşen Kayıt" value={d.matched_certificate} />}
                    {d.expected && <Field label="Beklenen (bağlı)" value={d.expected.join(', ')} />}
                    {d.error && <Field label="Hata" value={d.error} />}
                    {d.reason && <Field label="Not" value={d.reason} />}
                    {d.name_warning && d.name_warning !== d.reason && <Field label="Uyarı" value={d.name_warning} />}
                    {d.chain_warning && d.chain_warning !== d.reason && <Field label="Zincir uyarısı" value={d.chain_warning} />}
                    {d.date_note && <Field label="Tarih farkı" value={d.date_note} />}
                  </Box>
                )
              } catch { return null }
            })()}
            {canEdit && ((domain.live_check_status === 'mismatch' && liveStatus(domain) !== EXPIRED_SERVED)
                         || domain.live_check_status === 'no_mapping') && (
              <Box sx={{ border: 1, borderColor: 'warning.main', borderRadius: 1, p: 1.5 }}>
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
    : { label: 'Kök kayıtlı değil', color: 'default' }
}

