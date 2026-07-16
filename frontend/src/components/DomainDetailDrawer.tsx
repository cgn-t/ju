import AddLinkIcon from '@mui/icons-material/AddLink'
import CloudDownloadIcon from '@mui/icons-material/CloudDownload'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import SwapHorizIcon from '@mui/icons-material/SwapHoriz'
import WifiTetheringIcon from '@mui/icons-material/WifiTethering'
import {
  Alert, Box, Button, Checkbox, Chip, Divider, Drawer, FormControlLabel, IconButton, MenuItem,
  Skeleton, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Certificate, ChainImportResult, Domain } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { daysLeftColor, daysLeftLabel } from '../theme'
import CertificatePicker from './CertificatePicker'
import SkiText from './SkiText'

interface Props {
  domainId: number | null
  onClose: () => void
}

const LIVE_STATUS: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  match: { label: 'Uyumlu — sunulan sertifika envanterle eşleşiyor', color: 'success' },
  mismatch: { label: 'UYUMSUZ — sunulan sertifika eşlenen sertifikadan farklı', color: 'error' },
  unreachable: { label: 'Erişilemedi', color: 'warning' },
  no_mapping: { label: 'Server sertifikası eşlenmemiş', color: 'warning' },
  not_checkable: { label: 'Kontrol edilemez (wildcard)', color: 'default' },
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

  const { data: domain, isLoading } = useQuery<Domain>({
    queryKey: ['domain', domainId],
    queryFn: async () => (await api.get(`/domains/${domainId}`)).data,
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
      api.post(`/domains/${domainId}/certificates`, {
        certificate_id: selectedCert!.id, mapping_type: mappingType,
      }),
    onSuccess: () => {
      enqueueSnackbar('Sertifika bağlandı', { variant: 'success' })
      setSelectedCert(null)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const liveCheck = useMutation({
    mutationFn: async () => (await api.post(`/domains/${domainId}/live-check`)).data,
    onSuccess: (d: Domain) => {
      const status = LIVE_STATUS[d.live_check_status ?? '']
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
      enqueueSnackbar('Eşleme kaldırıldı', { variant: 'success' })
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // Mismatch/no_mapping düzeltme: canlıdaki zinciri içe aktar, leaf'i server eşle.
  // ONAY MODELİ: domainde zaten aktif server varsa devir ANINDA olmaz — SY onayına
  // düşen bir öneri üretilir (canlıda görüldü kanıtıyla).
  const importChain = useMutation({
    mutationFn: async () =>
      (await api.post<ChainImportResult>(`/domains/${domainId}/import-chain`,
        null, { params: { supersede: replaceOld } })).data,
    onSuccess: (r) => {
      const parts = []
      if (r.created.length) parts.push(`${r.created.length} sertifika eklendi`)
      if (r.mapped_server) parts.push(`"${r.mapped_server}" server eşlendi`)
      if (r.superseded.length) parts.push(`${r.superseded.length} devir önerisi oluşturuldu (SY onayı bekliyor)`)
      enqueueSnackbar(parts.join(', ') || 'Değişiklik yok',
                      { variant: 'success', autoHideDuration: r.superseded.length ? 8000 : undefined })
      invalidate()
      liveCheck.mutate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Drawer anchor="right" open={domainId !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 560 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !domain ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2}>
            <Typography variant="h6">Domain Detayı</Typography>
            <Field label="Domain" value={domain.domain} />

            {/* Haritadan bir domaine tıklayınca EN ÖNCE bunu görmek isteniyor:
                domaine bağlı (server/client) sertifikalar → drawer'ın en üstünde. */}
            <Typography variant="subtitle2">
              Bağlı Sertifikalar{domain.certificates.length ? ` (${domain.certificates.length})` : ''}
            </Typography>
            {domain.certificates.length === 0 && (
              <Typography variant="body2" color="text.secondary">Henüz sertifika bağlanmamış</Typography>
            )}
            {domain.certificates.map((c) => (
              <Box key={`${c.certificate_id}-${c.mapping_type}`}
                   sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip size="small" label={c.mapping_type === 'server' ? 'Server' : 'Client'}
                      color={c.mapping_type === 'server' ? 'error' : 'info'} sx={{ width: 64 }} />
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography variant="body2" noWrap title={c.name}>{c.name}</Typography>
                  <SkiText value={c.subject_key_identifier} />
                </Box>
                <Chip size="small" color={daysLeftColor(c.days_left)} label={daysLeftLabel(c.days_left)} />
                {canEdit && (
                  <Tooltip title="Eşlemeyi kaldır">
                    <IconButton size="small" color="error"
                                onClick={() => detach.mutate({ certId: c.certificate_id, type: c.mapping_type })}>
                      <LinkOffIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>
            ))}
            {canEdit && (
              <>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mt: 0.5 }}>Sertifika Bağla</Typography>
                {/* Dar drawer'da tek satır sıkışıyordu (tip seçici 'S…' diye kırpılıyordu):
                    seçici kendi satırında TAM genişlik, tip + buton ikinci satırda. */}
                <Stack spacing={1.5}>
                  <CertificatePicker
                    options={certs ?? []} label="Sertifika seç (ad, SKI, seri no ile ara)"
                    value={selectedCert} onChange={setSelectedCert}
                    disabledIds={alreadyMapped} disabledLabel="zaten bağlı"
                  />
                  <Stack direction="row" spacing={1}>
                    <TextField select size="small" label="Bağlantı Tipi" value={mappingType}
                               sx={{ flexGrow: 1 }}
                               onChange={(e) => setMappingType(e.target.value as 'server' | 'client')}>
                      <MenuItem value="server">Server</MenuItem>
                      <MenuItem value="client">Client</MenuItem>
                    </TextField>
                    <Button variant="contained" startIcon={<AddLinkIcon />} sx={{ px: 3, flexShrink: 0 }}
                            disabled={!selectedCert || alreadyMapped.has(selectedCert.id) || attach.isPending}
                            onClick={() => attach.mutate()}>
                      Bağla
                    </Button>
                  </Stack>
                </Stack>
              </>
            )}
            <Divider />

            <Stack direction="row" spacing={4}>
              <Field label="Dış Adres" value={domain.external_address} />
              <Field label="E-Mail (SY takımı)" value={domain.sy_team?.email} />
            </Stack>
            <Stack direction="row" spacing={4}>
              <Field label="UG Takımı" value={domain.ug_team_name ?? domain.ug_team?.name} />
              <Field label="SY Takımı" value={domain.sy_team?.name} />
            </Stack>
            <Stack direction="row" spacing={4}>
              <Field label="LoadBalancer Güncelleme" value={domain.lb_update} />
              <Field label="WAF Güncelleme" value={domain.waf_update} />
            </Stack>
            <Field label="Güncellenecek Sunucular" value={domain.servers_to_update} />
            <Field label="Dış Firma" value={domain.external_company} />
            <Field label="Detay" value={domain.info} />
            <Stack direction="row" spacing={4}>
              <Field label="Aksiyon Alma" value={domain.action_required} />
              <Field label="SSL Pinning" value={domain.ssl_pinning} />
            </Stack>
            <Field label="Keystore" value={domain.keystore} />
            <Divider />

            {(domain.pending_proposals ?? 0) > 0 && (
              <Alert severity="warning" icon={<SwapHorizIcon />}
                     action={<Button color="inherit" size="small" component={RouterLink} to="/proposals">
                               Onaya git</Button>}>
                Bu domain için <b>{domain.pending_proposals}</b> devir önerisi SY onayı bekliyor.
              </Alert>
            )}

            <Typography variant="subtitle2">Canlı Doğrulama (Drift Detection)</Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }} useFlexGap>
              <Button size="small" variant="outlined" startIcon={<WifiTetheringIcon />}
                      disabled={liveCheck.isPending} onClick={() => liveCheck.mutate()}>
                {liveCheck.isPending ? 'Kontrol ediliyor…' : 'Şimdi Doğrula'}
              </Button>
              {domain.live_check_status && (
                <Chip size="small" color={LIVE_STATUS[domain.live_check_status]?.color ?? 'default'}
                      label={LIVE_STATUS[domain.live_check_status]?.label ?? domain.live_check_status} />
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
                    {d.expected && <Field label="Beklenen (eşlenmiş)" value={d.expected.join(', ')} />}
                    {d.error && <Field label="Hata" value={d.error} />}
                    {d.reason && <Field label="Not" value={d.reason} />}
                  </Box>
                )
              } catch { return null }
            })()}
            {canEdit && (domain.live_check_status === 'mismatch' || domain.live_check_status === 'no_mapping') && (
              <Box sx={{ border: 1, borderColor: 'warning.main', borderRadius: 1, p: 1.5 }}>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  Sunucudaki gerçek sertifika envanterle uyuşmuyor. Canlıdaki zinciri
                  içe aktarabilirsiniz; domain boşsa <b>server</b> olarak eşlenir, zaten
                  aktif bir sertifika varsa <b>devir önerisi</b> oluşturulur (SY onayına düşer).
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }} useFlexGap>
                  <Button size="small" variant="contained" color="warning"
                          startIcon={<CloudDownloadIcon />}
                          disabled={importChain.isPending || liveCheck.isPending}
                          onClick={() => importChain.mutate()}>
                    {importChain.isPending ? 'Aktarılıyor…' : 'Canlıdaki Sertifikayı İçe Aktar'}
                  </Button>
                  <FormControlLabel
                    control={<Checkbox size="small" checked={replaceOld}
                                       onChange={(e) => setReplaceOld(e.target.checked)} />}
                    label={<Typography variant="body2">Eski kayıt için devir önerisi üret</Typography>}
                  />
                </Stack>
              </Box>
            )}
            <Button onClick={onClose}>Kapat</Button>
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
