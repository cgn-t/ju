import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, MenuItem, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs,
  TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useRef, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { ImportPreview, Team } from '../api/types'
import { MONO_FONT, TRANSFER_TOAST_MS, nodeColors } from '../theme'
import ConfirmSaveDialog, { type ConfirmItem } from './ConfirmSaveDialog'

interface Props {
  open: boolean
  onClose: () => void
}

export default function CertificateImportDialog({ open, onClose }: Props) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState(0)

  // Oluşturan = sertifikayı oluşturan SY ekibi (dinamik liste)
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
    enabled: open,
  })
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')
  const [creator, setCreator] = useState('')

  // --- Dosya import state ---
  const [file, setFile] = useState<File | null>(null)
  const [pfxPassword, setPfxPassword] = useState('')
  const [preview, setPreview] = useState<ImportPreview[] | null>(null)
  const [notes, setNotes] = useState('')
  const [purchasedBy, setPurchasedBy] = useState('')
  const [isInternal, setIsInternal] = useState(false)
  const [environment, setEnvironment] = useState('')
  const [supersedeOld, setSupersedeOld] = useState(true)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  // --- Manuel ekleme state ---
  const [manualName, setManualName] = useState('')
  const [manualPem, setManualPem] = useState('')
  const [manualNotes, setManualNotes] = useState('')
  const [manualPurchasedBy, setManualPurchasedBy] = useState('')
  const [manualInternal, setManualInternal] = useState(false)
  const [manualEnvironment, setManualEnvironment] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)  // Kaydet → tarih kontrolü onay diyaloğu

  const reset = () => {
    setFile(null); setPfxPassword(''); setPreview(null); setNotes(''); setPurchasedBy('')
    setIsInternal(false); setEnvironment(''); setSupersedeOld(true); setManualName(''); setManualPem('')
    setManualNotes(''); setManualPurchasedBy(''); setManualInternal(false); setManualEnvironment('')
    setCreator(''); setTab(0)
    setConfirmOpen(false)
  }

  // Onay diyaloğu özeti: import sekmesinde önizlemedeki sertifikalar + BİTİŞ tarihleri
  // (vurgulu); manuel sekmede yalnız ad (tarihler PEM'den kaydetme sırasında çıkarılır).
  const confirmItems: ConfirmItem[] = tab === 0
    ? (preview ?? []).filter((p) => !p.already_exists).flatMap((p) => [
        { label: 'Sertifika', value: p.name },
        { label: 'Bitiş (ValidTo)', value: (p.valid_to || '').slice(0, 10) || '—', highlight: true },
      ])
    : [{ label: 'Sertifika', value: manualName || '(PEM içeriğinden)' },
       { label: 'Tarihler', value: manualPem ? 'PEM içinden otomatik okunacak' : '—', highlight: true }]

  const close = () => { reset(); onClose() }

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['certificates'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    queryClient.invalidateQueries({ queryKey: ['cert-map'] })
    // Tekil detay/zincir cache'leri: devirle pasifleşen kayıt drawer'da bayat kalmasın
    queryClient.invalidateQueries({ queryKey: ['certificate'] })
    queryClient.invalidateQueries({ queryKey: ['certificate-chain'] })
  }

  const previewMutation = useMutation({
    mutationFn: async (selected: File) => {
      const form = new FormData()
      form.append('file', selected)
      if (pfxPassword) form.append('password', pfxPassword)
      return (await api.post<ImportPreview[]>('/certificates/import/preview', form)).data
    },
    onSuccess: (data) => setPreview(data),
    onError: (e) => {
      setPreview(null)
      enqueueSnackbar(apiErrorMessage(e), { variant: 'error' })
    },
  })

  // renewal_of_id yoksa bile renewal_of_name dolu olabilir (aynı dosyadaki eski nesil)
  const renewals = preview?.filter((p) => !p.already_exists && p.renewal_of_name) ?? []

  const importMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.append('file', file!)
      if (pfxPassword) form.append('password', pfxPassword)
      if (notes) form.append('notes', notes)
      if (purchasedBy) form.append('purchased_by', purchasedBy)
      if (creator) form.append('creator', creator)
      form.append('is_internal', String(isInternal))
      if (environment) form.append('environment', environment)
      // Onay sözleşmesi: devir yalnız kullanıcı planı GÖRDÜYSE gönderilir
      // (buton önizleme yüklenmeden kilitli, plan tüm öncülleri listeler)
      form.append('supersede', String(renewals.length > 0 && supersedeOld))
      return (await api.post('/certificates/import', form)).data
    },
    onSuccess: (data) => {
      const handedOver = supersedeOld && renewals.length > 0
        ? ` — ${renewals.length} devir önerisi oluşturuldu (SY onayı bekliyor)`
        : ''
      enqueueSnackbar(`${data.length} sertifika eklendi${handedOver}`,
                      { variant: 'success', autoHideDuration: handedOver ? TRANSFER_TOAST_MS : undefined })
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      invalidate(); close()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const manualMutation = useMutation({
    mutationFn: async () =>
      (await api.post('/certificates', {
        name: manualName, pem_certificate: manualPem || null, notes: manualNotes || null,
        purchased_by: manualPurchasedBy || null, is_internal: manualInternal,
        creator: creator || null, environment: manualEnvironment || null,
      })).data,
    onSuccess: () => {
      enqueueSnackbar('Sertifika eklendi', { variant: 'success' })
      invalidate(); close()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const pickFile = (selected: File | null) => {
    setFile(selected)
    setPreview(null)
    if (selected) previewMutation.mutate(selected)
  }

  // Oluşturan alanı: SY ekip adlarından dinamik seçim (her iki sekmede aynı)
  const creatorSelect = (
    <TextField select required label="Oluşturan Ekip" size="small" fullWidth
               value={creator} onChange={(e) => setCreator(e.target.value)} error={!creator}
               helperText={!creator ? 'Zorunlu — sertifikayı oluşturan SY ekibini seçin'
                           : (syTeams.length ? 'Sertifikayı oluşturan SY ekibi'
                                             : 'Tanımlı SY ekibi yok — Ayarlar’dan ekleyin')}>
      <MenuItem value=""><em>— seçilmedi —</em></MenuItem>
      {syTeams.map((t) => <MenuItem key={t.id} value={t.name}>{t.name}</MenuItem>)}
    </TextField>
  )

  // Ortam alanı: manuel formda zorunlu (prod/test) — otomatik yollar (vault-sync/keşif) bu
  // alanı bilemediği için yalnız burada, insan eliyle dolduruluyorken zorunlu kılınır.
  const environmentSelect = (value: string, onChange: (v: string) => void) => (
    <TextField select required label="Ortam" size="small" fullWidth
               value={value} onChange={(e) => onChange(e.target.value)} error={!value}
               helperText={!value ? 'Zorunlu — Prod veya Test seçin' : undefined}>
      <MenuItem value=""><em>— seçilmedi —</em></MenuItem>
      <MenuItem value="prod">Prod</MenuItem>
      <MenuItem value="test">Test</MenuItem>
    </TextField>
  )

  return (
    <Dialog open={open} onClose={close} maxWidth="md" fullWidth>
      <DialogTitle>Yeni Sertifika Ekle</DialogTitle>
      <DialogContent>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Dosyadan İçe Aktar (PEM / DER / PFX)" />
          <Tab label="Manuel Ekle" />
        </Tabs>

        {tab === 0 && (
          <Stack spacing={2}>
            <Box
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault(); setDragOver(false)
                if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0])
              }}
              sx={{
                border: '2px dashed', borderColor: dragOver ? 'primary.main' : 'divider',
                borderRadius: 2, p: 4, textAlign: 'center', cursor: 'pointer',
                bgcolor: dragOver ? 'action.hover' : 'transparent',
              }}
            >
              <CloudUploadIcon sx={{ fontSize: 44, color: 'text.secondary' }} />
              <Typography>
                {file ? file.name : 'Sertifika dosyasını sürükleyin veya tıklayıp seçin'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                .pem, .crt, .cer, .der, .pfx, .p12 — fullchain PEM desteklenir, zincir otomatik bağlanır
              </Typography>
              <input
                ref={fileInput} type="file" hidden
                accept=".pem,.crt,.cer,.der,.pfx,.p12,.txt"
                // value sıfırlanır: önizleme hatasından sonra AYNI dosya yeniden
                // seçilebilsin (yoksa change tetiklenmez, İçe Aktar kilitli kalır)
                onChange={(e) => { pickFile(e.target.files?.[0] ?? null); e.target.value = '' }}
              />
            </Box>

            {file?.name.match(/\.(pfx|p12)$/i) && (
              <TextField
                label="PFX Parolası" type="password" size="small" value={pfxPassword}
                onChange={(e) => setPfxPassword(e.target.value)}
                onBlur={() => file && previewMutation.mutate(file)}
                helperText="Parolayı girdikten sonra alan dışına tıklayın; önizleme yenilenir"
              />
            )}

            {preview && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>Önizleme — çıkarılan alanlar:</Typography>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Tür</TableCell>
                      <TableCell>CN</TableCell>
                      <TableCell>Bitiş</TableCell>
                      <TableCell>Üst Sertifika</TableCell>
                      <TableCell>Durum</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {preview.map((p) => (
                      <TableRow key={p.fingerprint_sha256 ?? p.serial_number}>
                        <TableCell>
                          <Chip size="small" label={p.cert_type}
                                sx={{ bgcolor: nodeColors[p.cert_type],
                                      color: 'rgba(0,0,0,0.87)', fontWeight: 700 }} />
                        </TableCell>
                        <TableCell>{p.name}</TableCell>
                        <TableCell>{new Date(p.valid_to).toLocaleDateString('tr-TR')}</TableCell>
                        <TableCell>{p.resolved_parent_name ?? (p.cert_type === 'root' ? '—' : 'bulunamadı')}</TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={0.5}>
                            {p.already_exists
                              ? <Chip size="small" color="warning" label="Zaten kayıtlı" />
                              : <Chip size="small" color="success" label="Yeni" />}
                            {p.renewal_of_name && (
                              <Tooltip title={p.renewal_signal === 'ski'
                                ? 'Aynı anahtar (SKI) — yenileme'
                                : 'Aynı CN + issuer — yenileme'}>
                                <Chip size="small" color="info" variant="outlined"
                                      label={`Yenileme → ${p.renewal_of_name}`} />
                              </Tooltip>
                            )}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {renewals.length > 0 && (
                  <Box sx={{ mt: 1.5, p: 1.25, border: '1px solid', borderColor: 'info.main',
                             borderRadius: 1, bgcolor: 'action.hover' }}>
                    <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
                      Devir planı — onay gerektirir
                    </Typography>
                    <Stack spacing={1}>
                      {renewals.map((p) => (
                        <Box key={p.fingerprint_sha256 ?? p.serial_number}>
                          <Stack direction="row" spacing={0.75} useFlexGap
                                 sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                            <Chip size="small" label="ESKİ" sx={{ fontWeight: 700 }} />
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.renewal_of_name}</Typography>
                            <Typography variant="caption" sx={{ fontFamily: MONO_FONT }} color="text.secondary">
                              {p.renewal_of_ski ?? 'SKI yok'}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              bitiş {p.renewal_of_valid_to
                                ? new Date(p.renewal_of_valid_to).toLocaleDateString('tr-TR') : '—'}
                            </Typography>
                            <Typography variant="body2" color="info.main" sx={{ px: 0.5 }}>→</Typography>
                            <Chip size="small" color="info" label="YENİ" sx={{ fontWeight: 700 }} />
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              bitiş {new Date(p.valid_to).toLocaleDateString('tr-TR')}
                            </Typography>
                          </Stack>
                          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.25 }}>
                            {p.renewal_signal === 'ski'
                              ? 'Tespit: SubjectKeyIdentifier birebir aynı — aynı anahtar yeniden sertifikalandırılmış (anahtar korunarak yenileme).'
                              : 'Tespit: aynı CN + aynı üretici CA, geçerlilik başlangıcı daha yeni — yeni anahtarla yenileme (tipik Vault rotasyonu).'}
                          </Typography>
                          <Typography variant="caption" component="div"
                                      color={p.renewal_of_domains?.length ? 'warning.main' : 'text.secondary'}>
                            {p.renewal_of_domains?.length
                              ? `Devredilecek eşlemeler: ${p.renewal_of_domains.join(', ')}`
                              : 'Devredilecek domain eşlemesi yok.'}
                          </Typography>
                          {(p.renewal_also?.length ?? 0) > 0 && (
                            <Typography variant="caption" component="div" color="warning.main">
                              Ayrıca devralınacak: {p.renewal_also!.join(' • ')}
                            </Typography>
                          )}
                        </Box>
                      ))}
                    </Stack>
                    <FormControlLabel
                      sx={{ mt: 0.5 }}
                      control={<Checkbox size="small" checked={supersedeOld}
                                         onChange={(e) => setSupersedeOld(e.target.checked)} />}
                      label={<Typography variant="body2">
                        Devir önerisi oluştur — domain sahibi SY ekibinin onayına düşer
                        (JUMBO devri kendiliğinden UYGULAMAZ)
                      </Typography>}
                    />
                    {!supersedeOld && (
                      <Typography variant="caption" color="text.secondary" component="div">
                        İşaretlenmezse öneri üretilmez; sertifika eklenir ama eski kayıt aynen kalır.
                      </Typography>
                    )}
                  </Box>
                )}
              </Box>
            )}

            {creatorSelect}
            {environmentSelect(environment, setEnvironment)}
            <Stack direction="row" spacing={2}>
              <TextField label="Satın Alım Yapan Ekip/Kişi" size="small" fullWidth
                         value={purchasedBy} onChange={(e) => setPurchasedBy(e.target.value)} />
              <FormControlLabel
                control={<Checkbox checked={isInternal} onChange={(e) => setIsInternal(e.target.checked)} />}
                label="Internal" />
            </Stack>
            <TextField label="Notlar" size="small" fullWidth multiline rows={2}
                       value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Stack>
        )}

        {tab === 1 && (
          <Stack spacing={2}>
            <Alert severity="info">
              PEM içeriği yapıştırırsanız tüm alanlar (seri no, issuer, geçerlilik, zincir) otomatik
              çıkarılır. PEM olmadan yalnızca isimle kayıt da oluşturabilirsiniz.
            </Alert>
            <TextField label="Sertifika Adı (CN)" size="small" fullWidth value={manualName}
                       onChange={(e) => setManualName(e.target.value)}
                       helperText="PEM verilirse boş bırakılabilir; CN otomatik alınır" />
            <TextField
              label="PEM İçeriği" fullWidth multiline rows={6} value={manualPem}
              onChange={(e) => setManualPem(e.target.value)}
              placeholder={'-----BEGIN CERTIFICATE-----\n…\n-----END CERTIFICATE-----'}
              slotProps={{ input: { sx: { fontFamily: 'monospace', fontSize: 12 } } }}
            />
            {creatorSelect}
            {environmentSelect(manualEnvironment, setManualEnvironment)}
            <Stack direction="row" spacing={2}>
              <TextField label="Satın Alım Yapan Ekip/Kişi" size="small" fullWidth
                         value={manualPurchasedBy} onChange={(e) => setManualPurchasedBy(e.target.value)} />
              <FormControlLabel
                control={<Checkbox checked={manualInternal} onChange={(e) => setManualInternal(e.target.checked)} />}
                label="Internal" />
            </Stack>
            <TextField label="Notlar" size="small" fullWidth multiline rows={2}
                       value={manualNotes} onChange={(e) => setManualNotes(e.target.value)} />
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Vazgeç</Button>
        {/* Kaydet/İçe Aktar önce ONAY diyaloğu açar; işlem 'Onaylıyorum' ile uygulanır */}
        {tab === 0 ? (
          <Button
            // Önizleme yüklenmeden import edilemez: yenileme/devir bilgisi önizlemeden gelir
            variant="contained"
            disabled={!file || !preview || previewMutation.isPending || importMutation.isPending
                      || preview.every((p) => p.already_exists) || !creator || !environment}
            onClick={() => setConfirmOpen(true)}
          >
            {importMutation.isPending ? 'İçe aktarılıyor…'
              : previewMutation.isPending ? 'Önizleme hazırlanıyor…' : 'İçe Aktar'}
          </Button>
        ) : (
          <Button
            variant="contained"
            disabled={(!manualName && !manualPem) || manualMutation.isPending || !creator || !manualEnvironment}
            onClick={() => setConfirmOpen(true)}
          >
            Kaydet
          </Button>
        )}
      </DialogActions>

      <ConfirmSaveDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          if (tab === 0) importMutation.mutate()
          else manualMutation.mutate()
        }}
        confirmLabel={tab === 0 ? 'Onaylıyorum, İçe Aktar' : 'Onaylıyorum, Kaydet'}
        items={confirmItems} />
    </Dialog>
  )
}
