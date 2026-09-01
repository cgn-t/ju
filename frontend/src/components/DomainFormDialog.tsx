import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, FormControlLabel, Grid, MenuItem, Paper, Switch, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { AppUser, ChainImportResult, ChainProbeResult, Domain, IssuanceProfile, Team } from '../api/types'
import ConfirmSaveDialog from './ConfirmSaveDialog'
import { useAuth } from '../auth/AuthContext'
import { daysLeftColor, daysLeftLabel, nodeColors } from '../theme'
import SkiText from './SkiText'

interface Props {
  open: boolean
  onClose: () => void
  domain?: Domain | null // varsa düzenleme modu
}

const EMPTY = {
  domain: '', external_address: '', ug_team_name: '', sy_team_id: '',
  lb_update: '', env_update: '', waf_update: '', external_company: '', expire_date: '',
  info: '', action_required: '', ssl_pinning: '', keystore: '',
  servers_to_update: '', notify_days: '',
  issuance_profile_id: '', issuance_renew_before_days: '',
}

// Zorunlu alanlar (yeni ekleme + düzenleme)
const REQUIRED = ['domain', 'lb_update', 'waf_update'] as const
const YESNO = ['Evet', 'Hayır']

// Outlined etiketi HER alanda kalıcı yukarıda tutar (notch mount'tan itibaren açık).
// Aksi hâlde etiket yalnız odak/değer ile "shrink" olur; Retina'da odak geçişi sırasında
// açılmamış çentik ile üst çizgi etiketin üstünden geçip binişme yapıyordu. Tek, tutarlı desen.
const LABEL_SHRINK = { inputLabel: { shrink: true } }

export default function DomainFormDialog({ open, onClose, domain }: Props) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Record<string, string>>(EMPTY)
  const [confirmOpen, setConfirmOpen] = useState(false)  // Kaydet → tarih kontrolü onay diyaloğu
  // Canlı zincir önizlemesi (yalnız yeni domain eklerken)
  const [probe, setProbe] = useState<ChainProbeResult | null>(null)
  const [probedFor, setProbedFor] = useState('')
  const [importChain, setImportChain] = useState(true)
  const [autoIssuance, setAutoIssuance] = useState(false)
  const [zeroTouch, setZeroTouch] = useState(false)
  const { isAdmin } = useAuth()
  const autoFilled = useRef(false)

  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
    enabled: open,
  })
  const { data: issuanceProfiles } = useQuery<IssuanceProfile[]>({
    queryKey: ['issuance-profiles'],
    queryFn: async () => (await api.get('/issuance/profiles')).data,
    enabled: open,
  })
  // Giriş yapmış kullanıcının SY ekip üyelikleri (yeni domain formunu otomatik doldurmak için)
  const { data: me } = useQuery<AppUser>({
    queryKey: ['auth-me'],
    queryFn: async () => (await api.get('/auth/me')).data,
    enabled: open,
  })

  useEffect(() => {
    if (domain) {
      setForm({
        domain: domain.domain ?? '',
        external_address: domain.external_address ?? '',
        ug_team_name: domain.ug_team_name ?? domain.ug_team?.name ?? '',
        sy_team_id: domain.sy_team_id?.toString() ?? '',
        lb_update: domain.lb_update ?? '',
        env_update: domain.env_update ?? '',
        waf_update: domain.waf_update ?? '',
        external_company: domain.external_company ?? '',
        expire_date: domain.expire_date ? domain.expire_date.slice(0, 10) : '',
        info: domain.info ?? '',
        action_required: domain.action_required ?? '',
        ssl_pinning: domain.ssl_pinning ?? '',
        keystore: domain.keystore ?? '',
        servers_to_update: domain.servers_to_update ?? '',
        notify_days: domain.notify_days?.toString() ?? '',
        issuance_profile_id: domain.issuance_profile_id?.toString() ?? '',
        issuance_renew_before_days: domain.issuance_renew_before_days?.toString() ?? '',
      })
      setAutoIssuance(domain.auto_issuance_enabled ?? false)
      setZeroTouch(domain.issuance_zero_touch ?? false)
    } else {
      setForm(EMPTY)
      setAutoIssuance(false)
      setZeroTouch(false)
    }
    setProbe(null)
    setProbedFor('')
    setImportChain(true)
    setConfirmOpen(false)
    autoFilled.current = false
  }, [domain, open])

  // Yeni domain: kullanıcının üye olduğu SY ekibini otomatik seç (birden çoksa ilki;
  // dropdown'dan değiştirilebilir). E-posta bu ekipten türetilir — ayrı alan yok.
  useEffect(() => {
    if (domain || autoFilled.current) return
    const mine = me?.sy_team_ids ?? []
    if (mine.length && !form.sy_team_id) {
      setForm((f) => ({ ...f, sy_team_id: String(mine[0]) }))
      autoFilled.current = true
    }
  }, [me, domain, form.sy_team_id])

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const probeMutation = useMutation({
    mutationFn: async (target: string) =>
      (await api.post<ChainProbeResult>('/domains/probe-chain', { domain: target })).data,
    onSuccess: (r, target) => {
      setProbe(r)
      setProbedFor(target)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // Domain alanından çıkınca zinciri otomatik sorgula.
  // Yeni domain: her zaman. Düzenleme: yalnız domain değeri değiştiyse (aksi hâlde
  // her odak kaybında gereksiz TLS bağlantısı kurulmasın; elle "Zinciri Getir" hep açık).
  const handleDomainBlur = () => {
    const target = form.domain.trim()
    if (!target || target === probedFor || probeMutation.isPending) return
    if (!domain || target !== (domain.domain ?? '').trim()) {
      probeMutation.mutate(target)
    }
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        sy_team_id: form.sy_team_id ? Number(form.sy_team_id) : null,
        expire_date: form.expire_date || null,
        notify_days: form.notify_days ? Number(form.notify_days) : null,
        issuance_profile_id: form.issuance_profile_id ? Number(form.issuance_profile_id) : null,
        issuance_renew_before_days: form.issuance_renew_before_days
          ? Number(form.issuance_renew_before_days) : null,
        auto_issuance_enabled: autoIssuance,
        issuance_zero_touch: zeroTouch,
      }
      // Boş stringleri null'a çevir
      const body = Object.fromEntries(Object.entries(payload).map(([k, v]) => [k, v === '' ? null : v]))
      const saved: Domain = domain
        ? (await api.put(`/domains/${domain.id}`, body)).data
        : (await api.post('/domains', body)).data
      // Zincir sorgulanmış ve kullanıcı istediyse: hem yeni eklemede hem düzenlemede
      // sertifikaları içe aktar + uç sertifikayı server bağla (mevcut server varsa devir önerisi).
      if (importChain && probe?.reachable && probe.certificates.length > 0) {
        try {
          const r: ChainImportResult = (await api.post(`/domains/${saved.id}/import-chain`)).data
          const parts = []
          if (r.created.length) parts.push(`${r.created.length} sertifika eklendi`)
          if (r.existing.length) parts.push(`${r.existing.length} zaten kayıtlıydı`)
          if (r.mapped_server) parts.push(`"${r.mapped_server}" server olarak bağlandı`)
          enqueueSnackbar(`Zincir aktarıldı: ${parts.join(', ') || 'değişiklik yok'}`,
                          { variant: 'success' })
        } catch (e) {
          enqueueSnackbar(`Domain kaydedildi ama zincir aktarılamadı: ${apiErrorMessage(e)}`,
                          { variant: 'warning' })
        }
      }
      return saved
    },
    onSuccess: () => {
      enqueueSnackbar(domain ? 'Domain güncellendi' : 'Domain eklendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['cert-map'] })
      onClose()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const syTeams = teams?.filter((t) => t.type === 'SY') ?? []
  // Non-admin domaini yalnız ÜYE olduğu SY ekibine atayabilir (mevcut sahip her zaman görünür)
  const mySyIds = new Set(me?.sy_team_ids ?? [])
  const syOptions = isAdmin ? syTeams
    : syTeams.filter((t) => mySyIds.has(t.id) || String(t.id) === form.sy_team_id)
  const selectedSy = syTeams.find((t) => String(t.id) === form.sy_team_id) ?? null

  // SY Takımı ZORUNLU — yeni kayıtta da düzenlemede de (sahipsiz domain
  // bildirimsiz/onaysız kalıyordu; eski sahipsiz kayıtlar da düzenlenirken sahiplendirilir).
  const syMissing = !form.sy_team_id
  const isValid = REQUIRED.every((k) => form[k]?.trim()) && !syMissing

  // Evet/Hayır seçici — mevcut serbest-metin veri varsa kaybolmaması için "(mevcut)" olarak korunur
  const yesNo = (key: string, label: string, required: boolean) => {
    const val = form[key] ?? ''
    const legacy = val && !YESNO.includes(val) ? val : null
    const err = required && !val
    return (
      <TextField select required={required} label={label} fullWidth size="small"
                 value={val} onChange={set(key)} error={err} slotProps={LABEL_SHRINK}
                 helperText={err ? 'Zorunlu alan' : undefined}>
        {required
          ? <MenuItem value="" disabled><em>Seçiniz…</em></MenuItem>
          : <MenuItem value=""><em>—</em></MenuItem>}
        {legacy && <MenuItem value={legacy}>{legacy} (mevcut)</MenuItem>}
        <MenuItem value="Evet">Evet</MenuItem>
        <MenuItem value="Hayır">Hayır</MenuItem>
      </TextField>
    )
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{domain ? `Domain Düzenle — ${domain.domain}` : 'Yeni Domain'}</DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0 }}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField required label="Domain" fullWidth size="small" value={form.domain}
                       onChange={set('domain')} onBlur={handleDomainBlur} error={!form.domain.trim()}
                       slotProps={LABEL_SHRINK}
                       helperText={!form.domain.trim() ? 'Zorunlu alan'
                         : !domain ? 'Alan doldurulunca sunulan sertifika zinciri otomatik sorgulanır' : undefined} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Dış Adres" fullWidth size="small" value={form.external_address}
                       onChange={set('external_address')} slotProps={LABEL_SHRINK} />
          </Grid>

          {/* Canlı sertifika zinciri önizlemesi — yeni eklemede otomatik, düzenlemede
              "Zinciri Getir" butonuyla her zaman elle çekilebilir (tüm zincir: leaf+ara+kök). */}
          {(domain || probeMutation.isPending || probe) && (
            <Grid size={{ xs: 12 }}>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: probe ? 1 : 0 }}>
                  <TravelExploreIcon fontSize="small" color="action" />
                  <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                    Canlı Sertifika Zinciri
                    {probe?.reachable && probe.host && (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {probe.host}:{probe.port}
                      </Typography>
                    )}
                  </Typography>
                  {probeMutation.isPending && <CircularProgress size={16} />}
                  <Button size="small" variant={probe ? 'text' : 'outlined'}
                          disabled={probeMutation.isPending || !form.domain.trim()}
                          onClick={() => probeMutation.mutate(form.domain.trim())}>
                    {probe ? 'Yeniden Sorgula' : 'Zinciri Getir'}
                  </Button>
                </Box>
                {domain && !probe && !probeMutation.isPending && (
                  <Typography variant="caption" color="text.secondary">
                    Domain’in sunduğu güncel sertifika zincirini (uç + ara + kök) canlı çekmek için
                    <b> Zinciri Getir</b>’e basın; ardından aktarabilirsiniz.
                  </Typography>
                )}
                {probe && !probe.reachable && (
                  <Alert severity="info" sx={{ py: 0 }}>
                    Zincir çekilemedi: {probe.error ?? 'bilinmeyen hata'} — domain yine de kaydedilebilir.
                  </Alert>
                )}
                {probe?.reachable && (
                  <>
                    {probe.certificates.map((c) => (
                      <Box key={c.fingerprint_sha256 ?? c.name}
                           sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5 }}>
                        <Chip size="small" label={c.cert_type[0].toUpperCase()}
                              sx={{ bgcolor: nodeColors[c.cert_type], color: 'rgba(0,0,0,0.87)',
                                    fontWeight: 700, width: 26, flexShrink: 0 }} />
                        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{c.name}</Typography>
                          <SkiText value={c.subject_key_identifier} />
                        </Box>
                        <Chip size="small" color={daysLeftColor(c.days_left)} label={daysLeftLabel(c.days_left)} />
                        {c.already_exists
                          ? <Chip size="small" color="warning" variant="outlined" label="DB'de kayıtlı" />
                          : <Chip size="small" color="success" variant="outlined" label="Yeni" />}
                      </Box>
                    ))}
                    {probe.certificates.some((c) => c.already_exists) && (
                      <Alert severity="warning" sx={{ py: 0, mt: 1 }}>
                        &quot;DB&apos;de kayıtlı&quot; işaretli sertifikalar zaten envanterde — tekrar eklenmez,
                        yalnız eksik olanlar aktarılır.
                      </Alert>
                    )}
                    <FormControlLabel
                      sx={{ mt: 0.5 }}
                      control={<Checkbox size="small" checked={importChain}
                                         onChange={(e) => setImportChain(e.target.checked)} />}
                      label={<Typography variant="body2">
                        Zinciri Sertifikalar&apos;a aktar ve uç sertifikayı bu domain&apos;e <b>server</b> olarak bağla
                      </Typography>}
                    />
                  </>
                )}
              </Paper>
            </Grid>
          )}
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select label="SY Takımı *" fullWidth size="small" slotProps={LABEL_SHRINK}
                       value={form.sy_team_id} onChange={set('sy_team_id')} error={syMissing}
                       helperText={syMissing ? 'Zorunlu alan — domainin sahibi SY takımını seçin'
                         : selectedSy
                         ? `Bildirim e-postası: ${selectedSy.email || '— (ekip e-postası tanımsız)'}`
                         : 'Bildirim e-postası sahibi SY takımından gelir (Ayarlar › SY Ekip Üyelikleri)'}>
              {syOptions.map((t) => <MenuItem key={t.id} value={t.id.toString()}>{t.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="UG Takımı" fullWidth size="small" value={form.ug_team_name}
                       onChange={set('ug_team_name')} placeholder="UG ekip adı" slotProps={LABEL_SHRINK} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Dış Firma" fullWidth size="small" value={form.external_company}
                       onChange={set('external_company')} slotProps={LABEL_SHRINK} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Manuel Bitiş Tarihi" type="date" fullWidth size="small" value={form.expire_date}
                       onChange={set('expire_date')} slotProps={LABEL_SHRINK} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Bildirim Gün Sayısı" type="number" fullWidth size="small"
                       value={form.notify_days} onChange={set('notify_days')}
                       slotProps={{ ...LABEL_SHRINK, htmlInput: { min: 1, max: 3650 } }}
                       helperText="Süre bitişine kaç gün kala mail? Boşsa Ayarlar'daki varsayılan (30 gün) kullanılır." />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Ortam Güncelleme" fullWidth size="small" value={form.env_update}
                       onChange={set('env_update')} slotProps={LABEL_SHRINK} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            {yesNo('lb_update', 'LoadBalancer Güncelleme', true)}
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            {yesNo('waf_update', 'WAF Güncelleme', true)}
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            {yesNo('action_required', 'Aksiyon Alma', false)}
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            {yesNo('ssl_pinning', 'SSL Pinning', false)}
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Güncellenecek Sunucular" fullWidth size="small" value={form.servers_to_update}
                       onChange={set('servers_to_update')} slotProps={LABEL_SHRINK} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Keystore" fullWidth size="small" value={form.keystore}
                       onChange={set('keystore')} slotProps={LABEL_SHRINK} />
          </Grid>

          {/* Otomatik CA sertifika alımı — özel anahtar JUMBO'ya hiç girmez (bkz. Sertifika Talepleri) */}
          <Grid size={{ xs: 12 }}>
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Otomatik Sertifika Alımı</Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <FormControlLabel
                    control={<Switch checked={autoIssuance}
                                     onChange={(e) => setAutoIssuance(e.target.checked)} />}
                    label="Süre yaklaşınca otomatik yenileme isteği aç" />
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <Tooltip title={isAdmin ? '' : 'Zero-touch modunu yalnız admin açıp kapatabilir'}>
                    <span>
                      <FormControlLabel
                        control={<Switch checked={zeroTouch} disabled={!isAdmin}
                                         onChange={(e) => setZeroTouch(e.target.checked)} />}
                        label="Zero-touch (onaysız tam otomatik)" />
                    </span>
                  </Tooltip>
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField select label="CA Profili" fullWidth size="small" slotProps={LABEL_SHRINK}
                             value={form.issuance_profile_id} onChange={set('issuance_profile_id')}
                             helperText="Boşsa Ayarlar > CA Profilleri'ndeki genel varsayılan kullanılır">
                    <MenuItem value=""><em>— varsayılan —</em></MenuItem>
                    {(issuanceProfiles ?? []).map((p) => (
                      <MenuItem key={p.id} value={p.id.toString()}>{p.name}</MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField label="Yenileme Eşiği (gün)" type="number" fullWidth size="small"
                             value={form.issuance_renew_before_days} onChange={set('issuance_renew_before_days')}
                             slotProps={{ ...LABEL_SHRINK, htmlInput: { min: 1, max: 365 } }}
                             helperText="Süre bitişine kaç gün kala otomatik istek açılsın? Boşsa genel varsayılan." />
                </Grid>
              </Grid>
            </Paper>
          </Grid>

          <Grid size={{ xs: 12 }}>
            <TextField label="Detay" fullWidth size="small" multiline rows={2} value={form.info}
                       onChange={set('info')} slotProps={LABEL_SHRINK} />
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Vazgeç</Button>
        {/* Kaydet önce ONAY diyaloğu açar; işlem 'Onaylıyorum' ile uygulanır */}
        <Button variant="contained" disabled={!isValid || mutation.isPending}
                onClick={() => setConfirmOpen(true)}>
          {domain ? 'Kaydet' : 'Ekle'}
        </Button>
      </DialogActions>

      <ConfirmSaveDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => { setConfirmOpen(false); mutation.mutate() }}
        items={[
          { label: 'İşlem', value: domain ? 'Domain güncelleme' : 'Yeni domain kaydı' },
          { label: 'Domain', value: form.domain || '—' },
          { label: 'Bitiş Tarihi', highlight: true,
            value: form.expire_date || 'Otomatik (bağlı sertifikadan)' },
        ]} />
    </Dialog>
  )
}
