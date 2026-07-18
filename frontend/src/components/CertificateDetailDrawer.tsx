import AccountTreeIcon from '@mui/icons-material/AccountTree'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/Edit'
import SubdirectoryArrowRightIcon from '@mui/icons-material/SubdirectoryArrowRight'
import {
  Box, Button, Chip, Divider, Drawer, IconButton, MenuItem, Skeleton, Stack, TextField, Tooltip, Typography,
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
import { daysLeftColor, daysLeftLabel, MONO_FONT, nodeColors, sourceLabel } from '../theme'

interface Props {
  certId: number | null
  onClose: () => void
  onSelectCert?: (id: number) => void // zincirde başka sertifikaya geçiş
}

// İptal (revocation) durumu çip görünümü; 'null' = henüz denetlenmemiş
const REVOCATION_META: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  good: { label: 'İptal edilmemiş', color: 'success' },
  revoked: { label: 'İPTAL EDİLMİŞ', color: 'error' },
  unknown: { label: 'Belirsiz', color: 'warning' },
  null: { label: 'Denetlenmedi', color: 'default' },
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={mono ? { fontFamily: MONO_FONT, fontSize: 12, wordBreak: 'break-all' } : { wordBreak: 'break-word' }}>
        {value || '—'}
      </Typography>
    </Box>
  )
}

function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <Typography variant="overline" color="text.secondary">{children}</Typography>
      {action}
    </Box>
  )
}

function ChainRow({ cert, current, indent, onClick }: {
  cert: { id: number; name: string; cert_type: string; days_left?: number | null }
  current: boolean
  indent: number
  onClick?: () => void
}) {
  return (
    <Box
      onClick={current ? undefined : onClick}
      sx={{
        display: 'flex', alignItems: 'center', gap: 1, py: 0.75, pl: indent * 2.5, pr: 1,
        borderRadius: 1, cursor: current ? 'default' : 'pointer',
        bgcolor: current ? 'action.selected' : 'transparent',
        '&:hover': current ? {} : { bgcolor: 'action.hover' },
      }}
    >
      {indent > 0 && <SubdirectoryArrowRightIcon fontSize="small" sx={{ color: 'text.disabled' }} />}
      <Chip size="small" label={cert.cert_type[0].toUpperCase()}
            sx={{ bgcolor: nodeColors[cert.cert_type], color: 'rgba(0,0,0,0.87)', fontWeight: 700, width: 26 }} />
      <Typography variant="body2" sx={{ flexGrow: 1, fontWeight: current ? 700 : 400 }} noWrap>
        {cert.name}
      </Typography>
      <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
    </Box>
  )
}

interface EditForm { name: string; purchased_by: string; creator: string; notes: string }

export default function CertificateDetailDrawer({ certId, onClose, onSelectCert }: Props) {
  const { enqueueSnackbar } = useSnackbar()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { canEdit } = useAuth()
  const [editing, setEditing] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)  // Kaydet → tarih kontrolü onay diyaloğu
  const [form, setForm] = useState<EditForm>({ name: '', purchased_by: '', creator: '', notes: '' })

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
  useEffect(() => { setEditing(false); setSuccessor(null) }, [certId])
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
                                   autoHideDuration: 8000 })
      setSuccessor(null)
      queryClient.invalidateQueries({ queryKey: ['proposals'] })
      queryClient.invalidateQueries({ queryKey: ['certificate', certId] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const save = useMutation({
    mutationFn: async (payload: Partial<EditForm>) => api.put(`/certificates/${certId}`, payload),
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
          : 'Durum belirlenemedi (unknown) — OCSP/CRL erişimi veya uç yok'
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
      creator: cert.creator ?? '', notes: cert.notes ?? '',
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

  return (
    <Drawer anchor="right" open={certId !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 580 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !cert ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2.5}>
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <Chip label={cert.cert_type.toUpperCase()}
                      sx={{ bgcolor: nodeColors[cert.cert_type], color: 'rgba(0,0,0,0.87)', fontWeight: 700 }} />
                {editing ? (
                  <TextField size="small" fullWidth label="Sertifika Adı" value={form.name}
                             onChange={(e) => setForm({ ...form, name: e.target.value })} />
                ) : (
                  <Typography variant="h6" sx={{ wordBreak: 'break-all', flexGrow: 1 }}>{cert.name}</Typography>
                )}
                {!editing && (
                  <>
                    {canEdit && (
                      <Tooltip title="Düzenle">
                        <IconButton size="small" onClick={startEdit}><EditIcon fontSize="small" /></IconButton>
                      </Tooltip>
                    )}
                    <Tooltip title="Haritada Aç">
                      <IconButton size="small" onClick={() => navigate('/cert-map')}>
                        <AccountTreeIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Kapat">
                      <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  </>
                )}
              </Box>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
                {cert.is_internal && <Chip size="small" variant="outlined" label="Internal" />}
                {!cert.is_active && <Chip size="small" color="default" label="Pasif" />}
                <Chip size="small" variant="outlined"
                      label={sourceLabel(cert.source)} />
                {cert.superseded_by_id && (
                  // Aktif + superseded_by = temkinli devir sürüyor (liste ile aynı adlandırma)
                  <Tooltip title={cert.is_active
                    ? 'Temkinli devir sürüyor — canlı doğrulama halefi sunucuda görünce bu kayıt pasife alınır. Halefe gitmek için tıklayın.'
                    : 'Bu sertifika yenilendi ve pasife alındı — halefine gitmek için tıklayın'}>
                    <Chip size="small" color="info" clickable
                          label={`${cert.is_active ? 'Devri bekliyor' : 'Yenilendi'} → ${cert.superseded_by_name ?? `#${cert.superseded_by_id}`}`}
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
            </Box>

            {/* Zincir */}
            {chain && (chain.ancestors.length > 0 || chain.children.length > 0) && (
              <Box>
                <SectionTitle>Sertifika Zinciri</SectionTitle>
                <Box sx={{ mt: 0.5 }}>
                  {chain.ancestors.map((a, i) => (
                    <ChainRow key={a.id} cert={a} current={false} indent={i}
                              onClick={() => onSelectCert?.(a.id)} />
                  ))}
                  <ChainRow cert={cert} current indent={chain.ancestors.length} />
                  {chain.children.map((c) => (
                    <ChainRow key={c.id} cert={c} current={false} indent={chain.ancestors.length + 1}
                              onClick={() => onSelectCert?.(c.id)} />
                  ))}
                </Box>
              </Box>
            )}

            <Divider />
            <SectionTitle>Kimlik</SectionTitle>
            <Field label="Subject" value={cert.subject} mono />
            <Field label="Issuer" value={cert.issuer} mono />
            <Field label="SerialNumber" value={cert.serial_number} mono />
            <Field label="SHA-256 Fingerprint" value={cert.fingerprint_sha256} mono />
            <Field label="SubjectKeyIdentifier" value={cert.subject_key_identifier} mono />
            <Field label="AuthorityKeyIdentifier" value={cert.authority_key_identifier} mono />
            <Field label="SubjectAltName (SAN)" value={cert.san} />
            <Field label="ExtendedKeyUsage" value={cert.extended_key_usage} />
            <Field label="Anahtar / İmza" mono
                   value={cert.public_key_type
                     ? `${cert.public_key_type}${cert.key_size ? ` ${cert.key_size} bit` : ''}`
                       + `${cert.key_curve ? ` (${cert.key_curve})` : ''} · ${cert.signature_hash || '—'}`
                     : null} />

            <Divider />
            <SectionTitle
              action={canEdit && (
                <Button size="small" variant="outlined" disabled={revocationCheck.isPending}
                        onClick={() => revocationCheck.mutate()}>
                  {revocationCheck.isPending ? 'Denetleniyor…' : 'Şimdi Kontrol Et'}
                </Button>
              )}>
              İptal Durumu (OCSP/CRL)
            </SectionTitle>
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
              <Chip size="small" color={REVOCATION_META[cert.revocation_status ?? 'null'].color}
                    label={REVOCATION_META[cert.revocation_status ?? 'null'].label} />
              {cert.revocation_checked_at && (
                <Typography variant="caption" color="text.secondary">
                  Son denetim: {new Date(cert.revocation_checked_at).toLocaleString('tr-TR')}
                </Typography>
              )}
            </Stack>

            <Box sx={{ mt: 0.5, p: 1.5, borderRadius: 1, bgcolor: 'action.hover' }}>
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
                  <b>Belirsiz (unknown)</b> — kuruma ulaşılamadı ya da iç/özel CA bu bilgiyi yayınlamıyor;
                  çoğu zaman normaldir, bir hata değildir.
                </Typography>
                <Typography component="li" variant="caption" color="text.secondary">
                  <b>Denetlenmedi</b> — bu sertifika için henüz sorulmadı.
                </Typography>
              </Box>
            </Box>

            <Divider />
            <SectionTitle>Geçerlilik</SectionTitle>
            <Stack direction="row" spacing={4}>
              <Field label="ValidFrom" value={cert.valid_from ? new Date(cert.valid_from).toLocaleString('tr-TR') : null} />
              <Field label="ValidTo" value={cert.valid_to ? new Date(cert.valid_to).toLocaleString('tr-TR') : null} />
            </Stack>

            <Divider />
            <SectionTitle>Bağlı Domainler</SectionTitle>
            {cert.domains.length === 0 ? (
              <Typography variant="body2" color="text.secondary">Bu sertifika hiçbir domain'e bağlı değil</Typography>
            ) : (
              <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1 }}>
                {cert.domains.map((d) => (
                  <Chip key={`${d.domain_id}-${d.mapping_type}`} size="small"
                        label={`${d.domain} (${d.mapping_type === 'server' ? 'server' : 'client'})`}
                        color={d.mapping_type === 'server' ? 'error' : 'info'} variant="outlined" />
                ))}
              </Stack>
            )}

            {/* Manuel devir: otomatik sinyallerin (aynı anahtar / aynı CN+CA) yakalamadığı
                yenilemeler için sahibin elle tetiklediği yol. Yalnız ÖNERİ üretir — her
                bağlantı granülünün onayı kendi sahibi SY ekibindedir (backend sahiplik korur). */}
            {!editing && canEdit && cert.is_active && (
              <>
                <Divider />
                <SectionTitle>Devir Öner</SectionTitle>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: -1 }}>
                  Bu sertifikanın yerine geçecek halefi seçin. Bağlı her domain ve uygulama
                  bağlantısı için AYRI devir önerisi oluşturulur; her öneri kendi sahibi SY
                  ekibinin onayını bekler — onaysız hiçbir bağlantı taşınmaz.
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                  <CertificatePicker options={successorOptions} value={successor}
                                     onChange={setSuccessor} label="Halef sertifika"
                                     sx={{ flexGrow: 1 }} />
                  <Button variant="outlined" onClick={() => supersede.mutate()}
                          disabled={!successor || supersede.isPending}
                          sx={{ flexShrink: 0, px: 2.5 }}>
                    Devir Öner
                  </Button>
                </Stack>
              </>
            )}

            <Divider />
            <SectionTitle
              action={!editing && canEdit && (
                <Button size="small" startIcon={<EditIcon fontSize="small" />} onClick={startEdit}>
                  Düzenle
                </Button>
              )}>
              Kurumsal
            </SectionTitle>
            {editing ? (
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
                <TextField size="small" fullWidth multiline rows={3} label="Notlar" value={form.notes}
                           placeholder="Bu sertifikayla ilgili notlar…"
                           onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                  <Button onClick={() => setEditing(false)} disabled={save.isPending}>Vazgeç</Button>
                  {/* Kaydet önce ONAY diyaloğu açar; işlem 'Onaylıyorum' ile uygulanır */}
                  <Button variant="contained" onClick={() => setConfirmOpen(true)}
                          disabled={save.isPending}>
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
                    { label: 'Bitiş (ValidTo)', highlight: true,
                      value: cert?.valid_to ? cert.valid_to.slice(0, 10) : '—' },
                  ]} />
              </Stack>
            ) : (
              <>
                <Stack direction="row" spacing={4}>
                  <Field label="Satın Alım Yapan" value={cert.purchased_by} />
                  <Field label="Oluşturan Ekip" value={cert.creator} />
                </Stack>
                <Field label="Notlar" value={cert.notes} />
              </>
            )}

            {cert.pem_certificate && (
              <>
                <Divider />
                <SectionTitle action={
                  <Box>
                    <Tooltip title="Kopyala">
                      <IconButton size="small" onClick={copyPem}><ContentCopyIcon fontSize="small" /></IconButton>
                    </Tooltip>
                    <Tooltip title="İndir (.pem)">
                      <IconButton size="small" onClick={downloadPem}><DownloadIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  </Box>
                }>
                  PEM Certificate
                </SectionTitle>
                <Box component="pre" sx={{
                  fontFamily: MONO_FONT, fontSize: 11, bgcolor: 'background.default',
                  p: 1.5, borderRadius: 1, maxHeight: 220, overflow: 'auto', m: 0,
                }}>
                  {cert.pem_certificate}
                </Box>
              </>
            )}
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
