import AccountTreeIcon from '@mui/icons-material/AccountTree'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/Edit'
import {
  Box, Button, Chip, Dialog, DialogContent, DialogTitle, IconButton, MenuItem, Skeleton, Stack, Tab, Tabs,
  TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Certificate, CertificateChain, Team } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import CertificatePicker from './CertificatePicker'
import ConfirmSaveDialog from './ConfirmSaveDialog'
import {
  CERT_TYPE_FULL, ChainArrow, ChainCertCard, CopyField, dnPart, fmtDate, GRID3, GRID4, InfoCard, keyText,
  REVOCATION, SectionBox, ValidityCard,
} from './DetailCards'
import {
  daysLeftColor, daysLeftLabel, environmentColor, environmentLabel, MONO_FONT, nodeColors,
  sourceLabel, TRANSFER_TOAST_MS,
} from '../theme'

interface Props {
  certId: number | null
  onClose: () => void
  onSelectCert?: (id: number) => void // zincirde başka sertifikaya geçiş
}

interface EditForm { name: string; purchased_by: string; creator: string; environment: string; notes: string }

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
    { name: '', purchased_by: '', creator: '', environment: '', notes: '' })

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
  const [successor, setSuccessor] = useState<Certificate | null>(null)

  // Sertifika değişince / panel kapanınca düzenleme modundan çık, halef seçimini sıfırla
  useEffect(() => { setEditing(false); setSuccessor(null); setTab('summary') }, [certId])
  const { data: allCerts } = useQuery<Certificate[]>({
    queryKey: ['certificates', 'picker'],
    queryFn: async () => (await api.get('/certificates')).data,
    enabled: certId !== null && canEdit,
  })
  // Halef adayları: aktif + kendisi değil + AYNI TÜR (leaf'in halefi leaf'tir — CA/intermediate
  // bir sunucu sertifikasının yerine geçmez; yanlış seçim listede hiç görünmesin)
  const successorOptions = (allCerts ?? []).filter(
    (c) => c.is_active && c.id !== certId && c.cert_type === cert?.cert_type)

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
    mutationFn: async (payload: Partial<EditForm>) =>
      // environment Literal["prod","test"]|None kabul eder, boş string DEĞİL — dönüştür
      api.put(`/certificates/${certId}`, { ...payload, environment: payload.environment || null }),
    onSuccess: () => {
      enqueueSnackbar('Sertifika güncellendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['certificate', certId] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
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
  const sans = (cert?.san ?? '').split(',').map((x) => x.trim()).filter(Boolean)
  const chainList = chain ? [...chain.ancestors].reverse() : []   // uçtan köke: önce üst, sonra kök

  return (
    <Dialog open={certId !== null} onClose={onClose} fullScreen={fullScreen} maxWidth="lg" fullWidth
            slotProps={{ paper: { sx: { height: { md: '88vh' } } } }}>
      {isLoading || !cert ? (
        <Box sx={{ p: 3 }}><Skeleton variant="rounded" height={500} /></Box>
      ) : (
        <>
          <DialogTitle sx={{ pb: 0.5, pr: 7 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
              <Chip label={CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type} size="small"
                    sx={{ bgcolor: nodeColors[cert.cert_type], color: 'rgba(0,0,0,0.87)', fontWeight: 700 }} />
              {editing ? (
                <TextField size="small" fullWidth label="Sertifika Adı" value={form.name}
                           onChange={(e) => setForm({ ...form, name: e.target.value })} />
              ) : (
                <Typography variant="h6" component="span" sx={{ fontWeight: 700, wordBreak: 'break-all' }}>{cert.name}</Typography>
              )}
              {!editing && canEdit && (
                <Tooltip title="Düzenle">
                  <IconButton size="small" onClick={() => { setTab('corporate'); startEdit() }}><EditIcon fontSize="small" /></IconButton>
                </Tooltip>
              )}
              <Tooltip title="Haritada Aç">
                <IconButton size="small" onClick={() => navigate('/cert-map')}><AccountTreeIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
                <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
                {cert.environment && (
                  <Chip size="small" color={environmentColor(cert.environment)}
                        variant="outlined" label={environmentLabel(cert.environment)} />
                )}
                {cert.is_internal && <Chip size="small" variant="outlined" label="Internal" />}
                {!cert.is_active && <Chip size="small" color="default" label="Pasif" />}
                <Chip size="small" variant="outlined"
                      label={sourceLabel(cert.source)} />
                {cert.superseded_by_id && (
                  // Aktif + superseded_by = temkinli devir sürüyor (liste ile aynı adlandırma)
                  <Tooltip title={cert.is_active
                    ? 'Yeni sertifikaya geçiş sürüyor — canlı doğrulama yeni sertifikayı sunucuda görünce bu kayıt pasife alınır. Yeni sertifikaya gitmek için tıklayın.'
                    : 'Bu sertifika yenilendi ve pasife alındı — yeni sertifikaya gitmek için tıklayın'}>
                    <Chip size="small" color="info" clickable
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
            </Box>
            <IconButton aria-label="Kapat" onClick={onClose} sx={{ position: 'absolute', right: 12, top: 12 }}>
              <CloseIcon />
            </IconButton>
          </DialogTitle>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant={fullScreen ? 'scrollable' : 'standard'} scrollButtons={false}
                sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}>
            <Tab value="summary" label="Özet" />
            <Tab value="chain" label="Zincir" />
            <Tab value="links" label={`Bağlantılar (${cert.domains.length})`} />
            <Tab value="technical" label="Teknik Detay" />
            <Tab value="revocation" label="İptal Durumu" />
            <Tab value="corporate" label="Kurumsal" />
          </Tabs>
          <DialogContent sx={{ pt: 2.5 }}>
            {tab === 'summary' && (
              <Stack spacing={2}>
                <ValidityCard cert={cert} />
                <Box sx={GRID4}>
                  <InfoCard title="Type" value={CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type}
                            sub={cert.cert_type === 'root' ? 'Self-signed' : undefined} />
                  <InfoCard title="Issuer (CA)" value={dnPart(cert.issuer, 'CN') ?? '—'}
                            sub={dnPart(cert.issuer, 'O') ?? undefined} onClick={() => setTab('chain')} />
                  <InfoCard title="Public Key" value={keyText(cert)}
                            sub={cert.signature_hash ? `Signature: ${cert.signature_hash.toUpperCase().replace('SHA', 'SHA-')}` : undefined} />
                  <InfoCard title="SubjectAltName (SAN)" value={sans.length ? `${sans.length} ad` : '—'}
                            sub={sans.slice(0, 3).join(', ') + (sans.length > 3 ? '…' : '')} onClick={() => setTab('technical')} />
                  <InfoCard title="Durum" value={cert.is_active ? 'Aktif' : 'Pasif'}
                            color={cert.is_active ? 'default' : 'warning'}
                            sub={cert.superseded_by_id ? `Yenisi: ${cert.superseded_by_name ?? `#${cert.superseded_by_id}`}` : undefined} />
                  <InfoCard title="İptal Durumu" value={revo.label} color={revo.color} onClick={() => setTab('revocation')}
                            sub={cert.revocation_checked_at ? `Son kontrol: ${fmtDate(cert.revocation_checked_at)}` : 'Henüz kontrol edilmedi'} />
                  <InfoCard title="Zincir" onClick={() => setTab('chain')}
                            value={chain ? `${chain.ancestors.length + 1} sertifika` : '—'}
                            sub={chain?.children.length ? `Altında ${chain.children.length} sertifika` : undefined} />
                  <InfoCard title="Bağlı Domainler" onClick={() => setTab('links')}
                            value={cert.domains.length ? `${cert.domains.length} domain` : 'Yok'}
                            sub={cert.domains.slice(0, 3).map((d) => d.domain).join(', ') + (cert.domains.length > 3 ? '…' : '')} />
                  <InfoCard title="Ortam" value={environmentLabel(cert.environment) || '—'} />
                  <InfoCard title="Kaynak" value={sourceLabel(cert.source)} sub={cert.vault_path ?? undefined} />
                  <InfoCard title="Oluşturan Ekip" value={cert.creator || '—'} onClick={() => setTab('corporate')} />
                  <InfoCard title="Satın Alım Yapan" value={cert.purchased_by || '—'} onClick={() => setTab('corporate')} />
                </Box>
                <SectionBox title="Kimlik">
                  <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
                    <CopyField label="Serial Number" value={cert.serial_number} />
                    <CopyField label="SHA-256 Fingerprint" value={cert.fingerprint_sha256} />
                    <CopyField label="Subject" value={cert.subject} />
                    <CopyField label="Issuer" value={cert.issuer} />
                  </Box>
                </SectionBox>
              </Stack>
            )}

            {tab === 'chain' && (
              <Stack spacing={1}>
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
                                   badges={current ? <Chip size="small" color="primary" label="Bu sertifika" /> : undefined}
                                   onOpen={current ? undefined : () => onSelectCert?.(c.id)} />
                  </Box>
                ))}
                <Typography variant="caption" color="text.secondary">
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
                                  value={d.domain} color={d.mapping_type === 'server' ? 'error' : 'info'}
                                  onClick={() => navigate(`/domains?domain=${d.domain_id}`)} />
                      ))}
                    </Box>
                  )}
                </SectionBox>
                {!editing && canEdit && cert.is_active && (
                  <SectionBox title="Değişiklik Talebi Oluştur">
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                  Bu sertifikanın yerine geçecek yeni sertifikayı seçin. Bağlı her domain ve uygulama
                  bağlantısı için AYRI değişiklik talebi oluşturulur; her talep kendi sahibi SY
                  ekibinin onayını bekler — onaysız hiçbir bağlantı taşınmaz.
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                  <CertificatePicker options={successorOptions} value={successor}
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
                <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
                  <CopyField label="Subject" value={cert.subject} />
                  <CopyField label="Issuer" value={cert.issuer} />
                  <CopyField label="Serial Number" value={cert.serial_number} />
                  <CopyField label="SHA-256 Fingerprint" value={cert.fingerprint_sha256} />
                  <CopyField label="SubjectKeyIdentifier" value={cert.subject_key_identifier} />
                  <CopyField label="AuthorityKeyIdentifier" value={cert.authority_key_identifier} />
                </Box>
                <Box sx={GRID3}>
                  <InfoCard title="ValidFrom" value={fmtDate(cert.valid_from)} />
                  <InfoCard title="ValidTo" value={fmtDate(cert.valid_to)} />
                  <InfoCard title="Public Key / Signature" value={keyText(cert)} sub={cert.signature_hash ?? undefined} />
                  <InfoCard title="ExtendedKeyUsage" value={cert.extended_key_usage || '—'} />
                  <InfoCard title="Internal" value={cert.is_internal ? 'Evet' : 'Hayır'} />
                  <InfoCard title="Otomatik Yenileme" value={cert.auto_renew ? 'Açık' : 'Kapalı'} />
                </Box>
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
                      fontFamily: MONO_FONT, fontSize: 11, bgcolor: 'background.default',
                      p: 1.5, borderRadius: 1, maxHeight: 260, overflow: 'auto', m: 0,
                    }}>
                      {cert.pem_certificate}
                    </Box>
                  </SectionBox>
                )}
              </Stack>
            )}

            {tab === 'revocation' && (
              <Stack spacing={2}>
                <Box sx={GRID3}>
                  <InfoCard title="İptal Durumu (OCSP/CRL)" value={revo.label} color={revo.color} />
                  <InfoCard title="Son Kontrol" value={cert.revocation_checked_at ? fmtDate(cert.revocation_checked_at) : 'Henüz kontrol edilmedi'} />
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', border: 1, borderColor: 'divider', borderRadius: 2, p: 2 }}>
                    {canEdit ? (
                      <Button variant="outlined" disabled={revocationCheck.isPending} onClick={() => revocationCheck.mutate()}>
                        {revocationCheck.isPending ? 'Denetleniyor…' : 'Şimdi Kontrol Et'}
                      </Button>
                    ) : <Typography variant="caption" color="text.secondary">Kontrol için düzenleme yetkisi gerekir</Typography>}
                  </Box>
                </Box>
            <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover' }}>
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
              <Stack spacing={2}>
                <TextField size="small" fullWidth label="Satın Alım Yapan" value={form.purchased_by}
                           onChange={(e) => setForm({ ...form, purchased_by: e.target.value })} />
                <TextField select size="small" fullWidth label="Oluşturan Ekip" value={form.creator}
                           onChange={(e) => setForm({ ...form, creator: e.target.value })}
                           helperText={syTeams.length ? 'Sertifikayı oluşturan SY ekibini seçin' : 'Tanımlı SY ekibi yok'}>
                  <MenuItem value=""><em>— seçilmedi —</em></MenuItem>
                  {form.creator && !syTeams.some((t) => t.name === form.creator) && (
                    <MenuItem value={form.creator}>{form.creator} (mevcut)</MenuItem>
                  )}
                  {syTeams.map((t) => <MenuItem key={t.id} value={t.name}>{t.name}</MenuItem>)}
                </TextField>
                <TextField select required size="small" fullWidth label="Ortam" value={form.environment}
                           onChange={(e) => setForm({ ...form, environment: e.target.value })}
                           error={!form.environment}
                           helperText={!form.environment ? 'Zorunlu — Prod veya Test seçin' : undefined}>
                  <MenuItem value="prod">Prod</MenuItem>
                  <MenuItem value="test">Test</MenuItem>
                </TextField>
                <TextField size="small" fullWidth multiline rows={3} label="Notlar" value={form.notes}
                           placeholder="Bu sertifikayla ilgili notlar…"
                           onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                  <Button onClick={() => setEditing(false)} disabled={save.isPending}>Vazgeç</Button>
                  {/* Kaydet önce ONAY diyaloğu açar; işlem 'Onaylıyorum' ile uygulanır */}
                  <Button variant="contained" onClick={() => setConfirmOpen(true)}
                          disabled={save.isPending || !form.environment}>
                    Kaydet
                  </Button>
                </Box>
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
              </Stack>
              ) : (
                <Stack spacing={2}>
                  <Box sx={GRID3}>
                    <InfoCard title="Satın Alım Yapan" value={cert.purchased_by || '—'} />
                    <InfoCard title="Oluşturan Ekip" value={cert.creator || '—'} />
                    <InfoCard title="Ortam" value={environmentLabel(cert.environment) || '—'} />
                    <InfoCard title="Kaynak" value={sourceLabel(cert.source)} />
                    <InfoCard title="Vault Yolu" value={cert.vault_path || '—'} />
                    <InfoCard title="Kayıt Tarihi" value={fmtDate(cert.created_at)} sub={`Son güncelleme: ${fmtDate(cert.updated_at)}`} />
                    <Box sx={{ gridColumn: '1 / -1', display: 'grid' }}>
                      <InfoCard title="Notlar" value={cert.notes || '—'} />
                    </Box>
                  </Box>
                  {canEdit && (
                    <Box><Button startIcon={<EditIcon fontSize="small" />} variant="outlined" onClick={startEdit}>Düzenle</Button></Box>
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
