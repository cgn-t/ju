import AccountTreeIcon from '@mui/icons-material/AccountTree'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import AccountBalanceOutlinedIcon from '@mui/icons-material/AccountBalanceOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import CategoryOutlinedIcon from '@mui/icons-material/CategoryOutlined'
import CodeIcon from '@mui/icons-material/Code'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined'
import DrawOutlinedIcon from '@mui/icons-material/DrawOutlined'
import EventAvailableOutlinedIcon from '@mui/icons-material/EventAvailableOutlined'
import EventBusyOutlinedIcon from '@mui/icons-material/EventBusyOutlined'
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined'
import GppGoodOutlinedIcon from '@mui/icons-material/GppGoodOutlined'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import HistoryIcon from '@mui/icons-material/History'
import KeyOutlinedIcon from '@mui/icons-material/KeyOutlined'
import LanguageIcon from '@mui/icons-material/Language'
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined'
import LinkIcon from '@mui/icons-material/Link'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined'
import PolicyOutlinedIcon from '@mui/icons-material/PolicyOutlined'
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew'
import RuleIcon from '@mui/icons-material/Rule'
import ShoppingCartOutlinedIcon from '@mui/icons-material/ShoppingCartOutlined'
import SourceOutlinedIcon from '@mui/icons-material/SourceOutlined'
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined'
import VerifiedOutlinedIcon from '@mui/icons-material/VerifiedOutlined'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'
import AutorenewIcon from '@mui/icons-material/Autorenew'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/Edit'
import {
  Box, Button, Chip, Dialog, DialogContent, FormControlLabel, IconButton, MenuItem, Skeleton, Stack,
  Switch, TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Certificate, CertificateChain, Team } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import CertificatePicker, { type PickerCert } from './CertificatePicker'
import ConfirmSaveDialog from './ConfirmSaveDialog'
import { EditFooter, FormSection } from './FormKit'
import {
  basicConstraintsText, CARD_SX, CERT_TYPE_FULL, ChainArrow, ChainCertCard, DetailHeader, DetailTabs, DIALOG_BODY_SX,
  DIALOG_PAPER_SX, dnPart, fmtDate, GRID3, GRID4, IconBadge, InfoCard, keyText, MetaItem, PropList, REVOCATION,
  RevocationEndpoints, Section, SectionBox, StatusPill, type Tone, VALIDATION_LABEL, ValidityCard,
} from './DetailCards'
import {
  daysLeftColor, daysLeftLabel, environmentLabel, MONO_FONT, nodeColors,
  sourceLabel, TRANSFER_TOAST_MS,
} from '../theme'

interface Props {
  certId: number | null
  onClose: () => void
  onSelectCert?: (id: number) => void // zincirde başka sertifikaya geçiş
}

const SHRINK = { inputLabel: { shrink: true } }

interface EditForm {
  name: string; purchased_by: string; creator: string; environment: string; notes: string
  is_internal: boolean; cert_type: 'root' | 'intermediate' | 'leaf'; parent: PickerCert | null
}

export default function CertificateDetailDrawer({ certId, onClose, onSelectCert }: Props) {
  const { enqueueSnackbar } = useSnackbar()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { canEdit } = useAuth()
  const [editing, setEditing] = useState(false)
  const [tab, setTab] = useState<'summary' | 'chain' | 'links' | 'technical' | 'revocation' | 'corporate'>('summary')
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const [confirmOpen, setConfirmOpen] = useState(false)  // Kaydet → tarih kontrolü onay diyaloğu
  const [form, setForm] = useState<EditForm>(
    { name: '', purchased_by: '', creator: '', environment: '', notes: '', is_internal: false, cert_type: 'leaf', parent: null })

  const { data: cert, isLoading } = useQuery<Certificate>({
    queryKey: ['certificate', certId],
    queryFn: async () => (await api.get(`/certificates/${certId}`)).data,
    enabled: certId !== null,
  })
  const { data: chain } = useQuery<CertificateChain>({
    queryKey: ['certificate-chain', certId],
    queryFn: async () => (await api.get(`/certificates/${certId}/chain`)).data,
    enabled: certId !== null,
  })
  // Oluşturan = SY ekibi; düzenlemede dinamik listeden seçilir
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
    enabled: certId !== null,
  })
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')

  // Manuel devir: halef sertifika seçimi için aktif sertifika listesi
  const [successor, setSuccessor] = useState<PickerCert | null>(null)

  // Sertifika değişince / panel kapanınca düzenleme modundan çık, halef seçimini sıfırla
  useEffect(() => { setEditing(false); setSuccessor(null); setTab('summary') }, [certId])
  // Düzenleme yetkisi: rol + sertifikanın sahibi ekip (sunucunun PUT kuralıyla aynı)
  const editable = canEdit && cert?.can_edit !== false
  const parentNow = chain?.ancestors.length ? chain.ancestors[chain.ancestors.length - 1] : null

  const supersede = useMutation({
    mutationFn: async () =>
      (await api.post(`/certificates/${successor!.id}/supersede/${certId}`)).data,
    onSuccess: (r: { proposed: number; message: string }) => {
      enqueueSnackbar(r.message, { variant: r.proposed ? 'success' : 'info',
                                   autoHideDuration: TRANSFER_TOAST_MS })
      setSuccessor(null)
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
      queryClient.invalidateQueries({ queryKey: ['certificate', certId] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const save = useMutation({
    mutationFn: async (f: EditForm) => {
      const { parent, ...rest } = f
      // environment Literal["prod","test"]|None kabul eder, boş string DEĞİL — dönüştür.
      // Üst sertifika yalnız değiştiyse gönderilir (zincir kuralı sunucuda denetlenir).
      const body: Record<string, unknown> = { ...rest, environment: rest.environment || null }
      if ((parent?.id ?? null) !== (cert?.parent_id ?? null)) body.parent_id = parent?.id ?? null
      if (rest.cert_type === cert?.cert_type) delete body.cert_type
      return api.put(`/certificates/${certId}`, body)
    },
    onSuccess: () => {
      enqueueSnackbar('Sertifika güncellendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['certificate', certId] })
      queryClient.invalidateQueries({ queryKey: ['certificate-chain', certId] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['cert-map'] })
      setEditing(false)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const revocationCheck = useMutation({
    mutationFn: async () => (await api.post(`/certificates/${certId}/revocation-check`)).data,
    onSuccess: (r: { revocation_status: string }) => {
      const msg = r.revocation_status === 'revoked' ? 'Sertifika İPTAL EDİLMİŞ (revoked)'
        : r.revocation_status === 'good' ? 'İptal edilmemiş (good)'
          : r.revocation_status === 'unknown' ? 'Bilinmiyor (unknown) — kurum bu sertifikayı tanımıyor'
            : r.revocation_status === 'unreachable' ? 'Ulaşılamadı — OCSP/CRL adresine erişilemedi'
              : 'Kontrol edilemez — sertifikada iptal bilgisi yok ya da üst sertifika envanterde yok'
      enqueueSnackbar(msg, { variant: r.revocation_status === 'revoked' ? 'error'
        : r.revocation_status === 'good' ? 'success' : 'info' })
      queryClient.invalidateQueries({ queryKey: ['certificate', certId] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const startEdit = () => {
    if (!cert) return
    setForm({
      name: cert.name ?? '', purchased_by: cert.purchased_by ?? '',
      creator: cert.creator ?? '', environment: cert.environment ?? '', notes: cert.notes ?? '',
      is_internal: !!cert.is_internal, cert_type: cert.cert_type,
      parent: parentNow ? { id: parentNow.id, name: parentNow.name, cert_type: parentNow.cert_type,
                            days_left: parentNow.days_left, subject_key_identifier: parentNow.subject_key_identifier } : null,
    })
    setEditing(true)
  }

  const copyPem = () => {
    if (cert?.pem_certificate) {
      navigator.clipboard.writeText(cert.pem_certificate)
      enqueueSnackbar('PEM panoya kopyalandı', { variant: 'success' })
    }
  }

  const downloadPem = () => {
    if (!cert?.pem_certificate) return
    const blob = new Blob([cert.pem_certificate], { type: 'application/x-pem-file' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${cert.name.replace(/[^a-zA-Z0-9.-]/g, '_')}.pem`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const revo = REVOCATION[cert?.revocation_status ?? 'null'] ?? REVOCATION.null
  const ex = cert?.extras
  const sans = (cert?.san ?? '').split(',').map((x) => x.trim()).filter(Boolean)
  const chainList = chain ? [...chain.ancestors].reverse() : []   // uçtan köke: önce üst, sonra kök

  return (
    <Dialog open={certId !== null} onClose={onClose} fullScreen={fullScreen} maxWidth="lg" fullWidth
            slotProps={{ paper: { sx: DIALOG_PAPER_SX } }}>
      {isLoading || !cert ? (
        <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={500} /></Box>
      ) : (
        <>
          <DetailHeader
            icon={<VerifiedUserOutlinedIcon />} iconColor={nodeColors[cert.cert_type]} tone={daysTone(cert.days_left)} onClose={onClose}
            title={<span title={cert.name}>{cert.name}</span>}
            titleExtra={!editing && (
              <>
                {editable && (
                  <Tooltip title="Düzenle">
                    <IconButton size="small" onClick={() => { setTab('corporate'); startEdit() }}><EditIcon fontSize="small" /></IconButton>
                  </Tooltip>
                )}
                <Tooltip title="Haritada Aç">
                  <IconButton size="small" onClick={() => navigate('/cert-map')}><AccountTreeIcon fontSize="small" /></IconButton>
                </Tooltip>
              </>
            )}
            meta={<>
              <StatusPill tone={daysTone(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
              <MetaItem value={CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type} />
              {cert.environment && <MetaItem value={environmentLabel(cert.environment)} />}
              <MetaItem label="Kaynak" value={sourceLabel(cert.source)} />
              {cert.is_internal && <StatusPill size="small" tone="default" label="Internal" />}
              {!cert.is_active && <StatusPill size="small" tone="warning" label="Pasif" />}
              {cert.superseded_by_id && (
                // Aktif + superseded_by = temkinli devir sürüyor (liste ile aynı adlandırma)
                <Tooltip title={cert.is_active
                  ? 'Yeni sertifikaya geçiş sürüyor — canlı doğrulama yeni sertifikayı sunucuda görünce bu kayıt pasife alınır. Yeni sertifikaya gitmek için tıklayın.'
                  : 'Bu sertifika yenilendi ve pasife alındı — yeni sertifikaya gitmek için tıklayın'}>
                  <Chip size="small" color="info" variant="outlined" clickable
                        label={`${cert.is_active ? 'Yenisi onay bekliyor' : 'Yenilendi'} → ${cert.superseded_by_name ?? `#${cert.superseded_by_id}`}`}
                        onClick={() => onSelectCert?.(cert.superseded_by_id!)} />
                </Tooltip>
              )}
              {cert.supersedes?.map((p) => (
                <Tooltip key={p.id} title={`Bu kayıt, ${p.name} sertifikasının yerine geçti — öncüle gitmek için tıklayın`}>
                  <Chip size="small" color="info" variant="outlined" clickable
                        label={`Devraldı ← ${p.name}${p.is_active ? '' : ' (pasif)'}`}
                        onClick={() => onSelectCert?.(p.id)} />
                </Tooltip>
              ))}
            </>}
            tabs={
              <DetailTabs value={tab} onChange={setTab} scrollable={fullScreen} items={[
                { value: 'summary', label: 'Özet', icon: <DashboardOutlinedIcon /> },
                { value: 'chain', label: 'Zincir', icon: <LinkIcon /> },
                { value: 'links', label: 'Bağlantılar', icon: <LanguageIcon />, count: cert.domains.length },
                { value: 'technical', label: 'Teknik Detay', icon: <CodeIcon /> },
                { value: 'revocation', label: 'İptal Durumu', icon: <GppGoodOutlinedIcon /> },
                { value: 'corporate', label: 'Kurumsal', icon: <BusinessOutlinedIcon /> },
              ]} />
            } />
          <DialogContent sx={DIALOG_BODY_SX}>
            {tab === 'summary' && (
              <Stack spacing={2}>
                <ValidityCard cert={cert} warnDaysNote="varsayılan süre; domainde farklı ayarlanabilir" />
                <Section title="Durum">
                  <Box sx={GRID4}>
                    <InfoCard title="Durum" icon={<PowerSettingsNewIcon />} value={cert.is_active ? 'Aktif' : 'Pasif'}
                              color={cert.is_active ? 'success' : 'warning'}
                              sub={cert.superseded_by_id ? `Yenisi: ${cert.superseded_by_name ?? `#${cert.superseded_by_id}`}` : undefined} />
                    <InfoCard title="İptal Durumu" icon={<GppGoodOutlinedIcon />} value={revo.label} color={revo.color} onClick={() => setTab('revocation')}
                              sub={cert.revocation_checked_at ? `Son kontrol: ${fmtDate(cert.revocation_checked_at)}` : 'Henüz kontrol edilmedi'} />
                    <InfoCard title="Zincir" icon={<LinkIcon />} onClick={() => setTab('chain')}
                              value={chain ? `${chain.ancestors.length + 1} sertifika` : '—'}
                              sub={chain?.children.length ? `Altında ${chain.children.length} sertifika` : undefined} />
                    <InfoCard title="Bağlı Domainler" icon={<LanguageIcon />} onClick={() => setTab('links')}
                              value={cert.domains.length ? `${cert.domains.length} domain` : 'Yok'}
                              sub={cert.domains.slice(0, 3).map((d) => d.domain).join(', ') + (cert.domains.length > 3 ? '…' : '')} />
                  </Box>
                </Section>
                <Section title="Sertifika">
                  <Box sx={GRID4}>
                    <InfoCard title="Type" icon={<CategoryOutlinedIcon />} value={CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type}
                              sub={cert.cert_type === 'root' ? 'Self-signed' : undefined} />
                    <InfoCard title="Issuer (CA)" icon={<AccountBalanceOutlinedIcon />} value={dnPart(cert.issuer, 'CN') ?? '—'}
                              sub={dnPart(cert.issuer, 'O') ?? undefined} onClick={() => setTab('chain')} />
                    <InfoCard title="Public Key" icon={<KeyOutlinedIcon />} value={keyText(cert)}
                              sub={cert.signature_hash ? `Signature: ${cert.signature_hash.toUpperCase().replace('SHA', 'SHA-')}` : undefined} />
                    <InfoCard title="SubjectAltName (SAN)" icon={<DnsOutlinedIcon />} value={sans.length ? `${sans.length} ad` : '—'}
                              sub={sans.slice(0, 3).join(', ') + (sans.length > 3 ? '…' : '')} onClick={() => setTab('technical')} />
                  </Box>
                </Section>
                <Section title="Güvenlik">
                  <Box sx={GRID4}>
                    <InfoCard title="Validation Type" icon={<VerifiedOutlinedIcon />} value={ex?.validation_type ?? '—'}
                              sub={ex?.validation_type ? VALIDATION_LABEL[ex.validation_type].split(' — ')[1] : 'Politika bilgisinde doğrulama tipi yok'} />
                    <InfoCard title="Certificate Transparency" icon={<VisibilityOutlinedIcon />} value={ex ? (ex.sct_count ? `${ex.sct_count} SCT` : 'SCT yok') : '—'}
                              color={ex && !ex.sct_count && cert.cert_type === 'leaf' && !cert.is_internal ? 'warning' : 'default'}
                              sub={ex ? (ex.sct_count ? 'Herkese açık CT loglarına kayıtlı' : 'İç CA için normal; public sertifikada tarayıcı reddedebilir') : undefined} />
                    <InfoCard title="Key Usage" icon={<TuneOutlinedIcon />} value={ex?.key_usage.length ? ex.key_usage.join(', ') : '—'} onClick={() => setTab('technical')} />
                    <InfoCard title="Basic Constraints" icon={<RuleIcon />} value={basicConstraintsText(ex)} onClick={() => setTab('technical')} />
                  </Box>
                </Section>
                <Section title="Sahiplik">
                  <Box sx={GRID4}>
                    <InfoCard title="Oluşturan Ekip" icon={<GroupsOutlinedIcon />} value={cert.creator || '—'} onClick={() => setTab('corporate')} />
                    <InfoCard title="Satın Alım Yapan" icon={<ShoppingCartOutlinedIcon />} value={cert.purchased_by || '—'} onClick={() => setTab('corporate')} />
                    <InfoCard title="Ortam" icon={<LayersOutlinedIcon />} value={environmentLabel(cert.environment) || '—'} />
                    <InfoCard title="Kaynak" icon={<SourceOutlinedIcon />} value={sourceLabel(cert.source)} sub={cert.vault_path ?? undefined} />
                  </Box>
                </Section>
                <Section title="Kimlik">
                  <PropList rows={[
                    { label: 'Serial Number', value: cert.serial_number },
                    { label: 'SHA-256 Fingerprint', value: cert.fingerprint_sha256 },
                    { label: 'Subject', value: cert.subject },
                    { label: 'Issuer', value: cert.issuer },
                    ...(ex ? [{ label: 'SPKI Pin (SHA-256)', value: ex.spki_pin_sha256 }] : []),
                  ]} />
                </Section>
              </Stack>
            )}

            {tab === 'chain' && (
              <Stack spacing={0}>
                {chainList.length === 0 && !chain?.children.length && (
                  <Typography variant="body2" color="text.secondary">
                    Bu sertifikanın envanterde üst ya da alt sertifikası yok.
                  </Typography>
                )}
                {[...(chain?.children ?? []).map((c) => ({ c, current: false })),
                  { c: cert, current: true },
                  ...chainList.map((c) => ({ c, current: false }))].map(({ c, current }, i) => (
                  <Box key={c.id}>
                    {i > 0 && <ChainArrow />}
                    <ChainCertCard cert={c} current={current}
                                   badges={current ? <StatusPill size="small" tone="info" label="Bu sertifika" /> : undefined}
                                   onOpen={current ? undefined : () => onSelectCert?.(c.id)} />
                  </Box>
                ))}
                <Typography variant="caption" color="text.secondary" sx={{ pt: 1.5 }}>
                  Yukarıdan aşağıya: Leaf → Intermediate → Root. Ayrıntı için satıra tıklayın; tekrar tıklayınca kapanır.
                </Typography>
              </Stack>
            )}

            {tab === 'links' && (
              <Stack spacing={2}>
                <SectionBox title={`Bağlı Domainler (${cert.domains.length})`}>
                  {cert.domains.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">Bu sertifika hiçbir domain'e bağlı değil</Typography>
                  ) : (
                    <Box sx={GRID3}>
                      {cert.domains.map((d) => (
                        <InfoCard key={`${d.domain_id}-${d.mapping_type}`} title={d.mapping_type === 'server' ? 'Server' : 'Trusted'}
                                  icon={<LanguageIcon />} value={d.domain} color={d.mapping_type === 'server' ? 'default' : 'info'}
                                  onClick={() => navigate(`/domains?domain=${d.domain_id}`)} />
                      ))}
                    </Box>
                  )}
                </SectionBox>
                {!editing && editable && cert.is_active && (
                  <SectionBox title="Değişiklik Talebi Oluştur">
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                  Bu sertifikanın yerine geçecek yeni sertifikayı seçin. Bağlı her domain ve uygulama
                  bağlantısı için AYRI değişiklik talebi oluşturulur; her talep kendi sahibi SY
                  ekibinin onayını bekler — onaysız hiçbir bağlantı taşınmaz.
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                  {/* Halef adayları: aktif + kendisi değil + AYNI TÜR (leaf'in halefi leaf'tir) */}
                  <CertificatePicker remote={{ is_active: true, cert_type: cert.cert_type, exclude: (c) => c.id === cert.id }}
                                     value={successor}
                                     onChange={setSuccessor} label="Yeni sertifika"
                                     sx={{ flexGrow: 1 }} />
                  <Button variant="outlined" onClick={() => supersede.mutate()}
                          disabled={!successor || supersede.isPending}
                          sx={{ flexShrink: 0, px: 2.5 }}>
                    Değişiklik Talebi Oluştur
                  </Button>
                </Stack>
                  </SectionBox>
                )}
              </Stack>
            )}

            {tab === 'technical' && (
              <Stack spacing={2}>
                <PropList title="Kimlik" rows={[
                  { label: 'Subject', value: cert.subject },
                  { label: 'Issuer', value: cert.issuer },
                  { label: 'Serial Number', value: cert.serial_number },
                  { label: 'SHA-256 Fingerprint', value: cert.fingerprint_sha256 },
                  { label: 'SubjectKeyIdentifier', value: cert.subject_key_identifier },
                  { label: 'AuthorityKeyIdentifier', value: cert.authority_key_identifier },
                  ...(ex ? [{ label: 'SPKI Pin (SHA-256)', value: ex.spki_pin_sha256 }] : []),
                ]} />
                <Box sx={GRID3}>
                  <InfoCard title="ValidFrom" icon={<EventAvailableOutlinedIcon />} value={fmtDate(cert.valid_from)} />
                  <InfoCard title="ValidTo" icon={<EventBusyOutlinedIcon />} value={fmtDate(cert.valid_to)} />
                  <InfoCard title="Public Key" icon={<KeyOutlinedIcon />} value={keyText(cert)} />
                  <InfoCard title="Signature Algorithm" icon={<DrawOutlinedIcon />} value={ex?.signature_algorithm ?? cert.signature_hash ?? '—'} />
                  <InfoCard title="ExtendedKeyUsage" icon={<TuneOutlinedIcon />} value={cert.extended_key_usage || '—'} />
                  <InfoCard title="Internal" icon={<LockOutlinedIcon />} value={cert.is_internal ? 'Evet' : 'Hayır'} />
                  <InfoCard title="Otomatik Yenileme" icon={<AutorenewIcon />} value={cert.auto_renew ? 'Açık' : 'Kapalı'} />
                  <InfoCard title="Key Usage" icon={<TuneOutlinedIcon />} value={ex?.key_usage.length ? ex.key_usage.join(', ') : '—'} />
                  <InfoCard title="Basic Constraints" icon={<RuleIcon />} value={basicConstraintsText(ex)} />
                  <InfoCard title="Validation Type" icon={<VerifiedOutlinedIcon />} value={ex?.validation_type ?? '—'}
                            sub={ex?.validation_type ? VALIDATION_LABEL[ex.validation_type] : undefined} />
                  <InfoCard title="Certificate Transparency" icon={<VisibilityOutlinedIcon />} value={ex ? `${ex.sct_count ?? 0} SCT` : '—'} />
                  <InfoCard title="Certificate Policies" icon={<PolicyOutlinedIcon />} value={ex?.policy_oids.length ? ex.policy_oids.join(', ') : '—'} />
                </Box>
                <RevocationEndpoints extras={ex} />
                <SectionBox title={`SubjectAltName (SAN) — ${sans.length}`}>
                  <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>{sans.length ? sans.join(', ') : '—'}</Typography>
                </SectionBox>
                {cert.pem_certificate && (
                  <SectionBox title="PEM Certificate" action={
                    <Box>
                      <Tooltip title="Kopyala">
                        <IconButton size="small" onClick={copyPem}><ContentCopyIcon fontSize="small" /></IconButton>
                      </Tooltip>
                      <Tooltip title="İndir (.pem)">
                        <IconButton size="small" onClick={downloadPem}><DownloadIcon fontSize="small" /></IconButton>
                      </Tooltip>
                    </Box>
                  }>
                    <Box component="pre" sx={{
                      fontFamily: MONO_FONT, fontSize: 11, bgcolor: 'action.hover',
                      p: 1.5, borderRadius: '10px', maxHeight: 260, overflow: 'auto', m: 0,
                    }}>
                      {cert.pem_certificate}
                    </Box>
                  </SectionBox>
                )}
              </Stack>
            )}

            {tab === 'revocation' && (
              <Stack spacing={2}>
                <Box sx={(t) => ({ ...CARD_SX, p: { xs: 2, md: 2.5 }, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap',
                                   background: `linear-gradient(120deg, ${alpha(revo.color !== 'default' ? t.palette[revo.color].main : t.palette.text.secondary, t.palette.mode === 'dark' ? 0.14 : 0.07)} 0%, ${t.palette.background.paper} 50%)` })}>
                  <IconBadge size={44} tone={revo.color}><GppGoodOutlinedIcon /></IconBadge>
                  <Box sx={{ flexGrow: 1, minWidth: 200 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{revo.label}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {cert.revocation_checked_at ? `Son kontrol: ${fmtDate(cert.revocation_checked_at)}` : 'Henüz kontrol edilmedi'}
                    </Typography>
                  </Box>
                  {canEdit ? (
                    <Button variant="contained" disableElevation disabled={revocationCheck.isPending} onClick={() => revocationCheck.mutate()}>
                      {revocationCheck.isPending ? 'Denetleniyor…' : 'Şimdi Kontrol Et'}
                    </Button>
                  ) : <Typography variant="caption" color="text.secondary">Kontrol için düzenleme yetkisi gerekir</Typography>}
                </Box>
                <RevocationEndpoints extras={ex} />
            <Box sx={{ ...CARD_SX, p: 2 }}>
              <Typography variant="caption" color="text.secondary" component="p" sx={{ m: 0 }}>
                Bir sertifika, son kullanma tarihi gelmeden de <b>iptal</b> edilebilir (ör. özel anahtarı
                çalınırsa). OCSP ve CRL, sertifikayı veren kuruma (CA) &quot;bu sertifika iptal edildi mi?&quot;
                diye soran iki yöntemdir; &quot;Şimdi Kontrol Et&quot; tam olarak bunu sorar. Sonuç:
              </Typography>
              <Box component="ul" sx={{ m: 0, mt: 0.75, pl: 2 }}>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>İptal edilmemiş (good)</b> — kurum &quot;geçerli, geri çekmedim&quot; diyor; sertifika güvenle kullanılabilir.
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>İptal edilmiş (revoked)</b> — kurum sertifikayı süresi dolmadan geri çekmiş; artık
                  güvenilmemeli (ör. özel anahtarı çalınmış olabilir).
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>Bilinmiyor (unknown)</b> — kuruma ulaşıldı ama kurum bu sertifikayı tanımadığını söyledi.
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>Ulaşılamadı</b> — kuruma (OCSP/CRL adresine) erişilemedi; kapalı ağda çoğu zaman normaldir.
                  Daha önce iptal edilmiş görülen sertifika bu durumda da iptal edilmiş kalır.
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>Kontrol edilemez</b> — sertifikada sorulacak adres yok (iç/özel CA'larda sık görülür) ya da
                  soru için gereken üst sertifika envanterde yok; bir hata değildir.
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>Denetlenmedi</b> — bu sertifika için henüz sorulmadı.
                </Typography>
              </Box>
            </Box>

              </Stack>
            )}

            {tab === 'corporate' && (
              editing ? (
              <Box>
                <Stack spacing={2}>
                  <FormSection icon={<BadgeOutlinedIcon />} title="Kimlik" hint="Ad, tür ve ortam">
                    <TextField size="small" fullWidth label="Sertifika Adı" value={form.name} required
                               error={!form.name.trim()} helperText={!form.name.trim() ? 'Zorunlu alan' : undefined}
                               slotProps={SHRINK} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                    <TextField select size="small" fullWidth label="Type" value={form.cert_type} slotProps={SHRINK}
                               onChange={(e) => setForm({ ...form, cert_type: e.target.value as EditForm['cert_type'] })}
                               helperText={form.cert_type !== cert.cert_type
                                 ? 'Tür normalde sertifikadan okunur; yalnız yanlış algılandıysa değiştirin.'
                                 : 'Leaf / Intermediate / Root'}>
                      <MenuItem value="leaf">Leaf</MenuItem>
                      <MenuItem value="intermediate">Intermediate</MenuItem>
                      <MenuItem value="root">Root</MenuItem>
                    </TextField>
                    <TextField select required size="small" fullWidth label="Ortam" value={form.environment} slotProps={SHRINK}
                               onChange={(e) => setForm({ ...form, environment: e.target.value })}
                               error={!form.environment}
                               helperText={!form.environment ? 'Zorunlu — Prod veya Test seçin' : undefined}>
                      <MenuItem value="prod">Prod</MenuItem>
                      <MenuItem value="test">Test</MenuItem>
                    </TextField>
                  </FormSection>
                  <FormSection icon={<AccountTreeIcon />} title="Zincir" hint="Bu sertifikayı imzalayan üst sertifika" columns={1}>
                    <CertificatePicker
                      remote={{ exclude: (c) => c.id === cert.id || c.cert_type === 'leaf' }}
                      value={form.parent} onChange={(v) => setForm({ ...form, parent: v })}
                      label="Üst sertifika (Issuer) — boş bırakılırsa zincirin başı" />
                    <FormControlLabel sx={{ ml: 0, gap: 1 }}
                      control={<Switch checked={form.is_internal} onChange={(e) => setForm({ ...form, is_internal: e.target.checked })} />}
                      label={<Box>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>Internal</Typography>
                        <Typography variant="caption" color="text.secondary">Kurum içi CA ile imzalı</Typography>
                      </Box>} />
                  </FormSection>
                  <FormSection icon={<GroupsOutlinedIcon />} title="Kurumsal bilgiler" columns={2}>
                    <TextField size="small" fullWidth label="Satın Alım Yapan" value={form.purchased_by} slotProps={SHRINK}
                               placeholder="ör. Altyapı Satın Alma"
                               onChange={(e) => setForm({ ...form, purchased_by: e.target.value })} />
                    <TextField select size="small" fullWidth label="Oluşturan Ekip" value={form.creator}
                               slotProps={{ ...SHRINK, select: { displayEmpty: true } }}
                               onChange={(e) => setForm({ ...form, creator: e.target.value })}
                               helperText={syTeams.length ? 'Sertifikayı oluşturan SY ekibi' : 'Tanımlı SY ekibi yok'}>
                      <MenuItem value=""><Typography component="span" color="text.secondary">Seçilmedi</Typography></MenuItem>
                      {form.creator && !syTeams.some((t) => t.name === form.creator) && (
                        <MenuItem value={form.creator}>{form.creator} (mevcut)</MenuItem>
                      )}
                      {syTeams.map((t) => <MenuItem key={t.id} value={t.name}>{t.name}</MenuItem>)}
                    </TextField>
                  </FormSection>
                  <FormSection icon={<NotesOutlinedIcon />} title="Notlar" columns={1}>
                    <TextField size="small" fullWidth multiline rows={3} label="Notlar" value={form.notes} slotProps={SHRINK}
                               placeholder="Bu sertifikayla ilgili notlar…"
                               onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                  </FormSection>
                </Stack>
                {/* Kaydet önce ONAY diyaloğu açar; işlem 'Onaylıyorum' ile uygulanır */}
                <EditFooter status="Tarihler sertifikanın kendisinden okunur, burada değiştirilmez."
                            onCancel={() => setEditing(false)} busy={save.isPending}
                            saveDisabled={!form.environment || !form.name.trim()}
                            onSave={() => setConfirmOpen(true)} />
                <ConfirmSaveDialog
                  open={confirmOpen}
                  onClose={() => setConfirmOpen(false)}
                  onConfirm={() => { setConfirmOpen(false); save.mutate(form) }}
                  items={[
                    { label: 'İşlem', value: 'Sertifika güncelleme' },
                    { label: 'Sertifika', value: form.name || cert?.name || '—' },
                    { label: 'ValidTo', highlight: true,
                      value: cert?.valid_to ? cert.valid_to.slice(0, 10) : '—' },
                  ]} />
              </Box>
              ) : (
                <Stack spacing={2}>
                  <Box sx={GRID3}>
                    <InfoCard title="Satın Alım Yapan" icon={<ShoppingCartOutlinedIcon />} value={cert.purchased_by || '—'} />
                    <InfoCard title="Oluşturan Ekip" icon={<GroupsOutlinedIcon />} value={cert.creator || '—'} />
                    <InfoCard title="Ortam" icon={<LayersOutlinedIcon />} value={environmentLabel(cert.environment) || '—'} />
                    <InfoCard title="Kaynak" icon={<SourceOutlinedIcon />} value={sourceLabel(cert.source)} />
                    <InfoCard title="Vault Yolu" icon={<FolderOutlinedIcon />} value={cert.vault_path || '—'} />
                    <InfoCard title="Kayıt Tarihi" icon={<HistoryIcon />} value={fmtDate(cert.created_at)} sub={`Son güncelleme: ${fmtDate(cert.updated_at)}`} />
                    <InfoCard title="Type" icon={<CategoryOutlinedIcon />} value={CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type} />
                    <InfoCard title="Üst sertifika (Issuer)" icon={<AccountTreeIcon />} value={parentNow?.name ?? '—'}
                              onClick={parentNow ? () => onSelectCert?.(parentNow.id) : undefined} />
                    <InfoCard title="Internal" icon={<LockOutlinedIcon />} value={cert.is_internal ? 'Evet' : 'Hayır'} />
                    <Box sx={{ gridColumn: '1 / -1', display: 'grid' }}>
                      <InfoCard title="Notlar" icon={<NotesOutlinedIcon />} value={cert.notes || '—'} />
                    </Box>
                  </Box>
                  {editable && (
                    <Box><Button startIcon={<EditIcon fontSize="small" />} variant="outlined" onClick={startEdit}>Düzenle</Button></Box>
                  )}
                  {canEdit && !editable && (
                    <Typography variant="caption" color="text.secondary">
                      Bu sertifika başka bir ekibe ait; yalnız o ekibin editörü veya admin düzenleyebilir.
                    </Typography>
                  )}
                </Stack>
              )
            )}
          </DialogContent>
        </>
      )}
    </Dialog>
  )
}

const daysTone = (d?: number | null): Tone => { const c = daysLeftColor(d); return c === 'default' ? 'default' : c }
