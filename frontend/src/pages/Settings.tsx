import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import GroupsIcon from '@mui/icons-material/Groups'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import {
  Alert, Box, Button, ButtonBase, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, FormControlLabel, Grid, IconButton, MenuItem, Paper, Stack, Switch, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { Autocomplete } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type {
  AppUser, AuditEntry, IssuanceProfile, MailHistoryEntry, ScanTarget, Tag, Team, TeamMember,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { daysLeftColor, daysLeftLabel } from '../theme'
import { exportCsv } from '../utils/csv'

// ---------- Ortak kategori formu kancası ----------
function useCategory(category: string) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Record<string, unknown>>({})

  const { data } = useQuery<Record<string, unknown>>({
    queryKey: ['settings', category],
    queryFn: async () => (await api.get(`/settings/${category}`)).data,
  })

  useEffect(() => {
    if (data) setForm(data)
  }, [data])

  const save = useMutation({
    mutationFn: async () => api.put(`/settings/${category}`, form),
    onSuccess: () => {
      enqueueSnackbar('Ayarlar kaydedildi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['settings', category] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return { form, setForm, save }
}

function Text({ form, setForm, field, label, type, helper, width, multiline, rows, disabled }: {
  form: Record<string, unknown>
  setForm: React.Dispatch<React.SetStateAction<Record<string, unknown>>>
  field: string
  label: string
  type?: string
  helper?: string
  width?: { xs: number; sm: number }
  multiline?: boolean
  rows?: number
  disabled?: boolean
}) {
  return (
    <Grid size={width ?? { xs: 12, sm: 6 }}>
      <TextField
        label={label} type={type} fullWidth size="small" helperText={helper} disabled={disabled}
        multiline={multiline} rows={rows}
        value={String(form[field] ?? '')}
        onChange={(e) => setForm((f) => ({ ...f, [field]: type === 'number' ? Number(e.target.value) : e.target.value }))}
      />
    </Grid>
  )
}

// LDAP form bölüm başlığı (CONNECTION / USER SEARCH / GROUP LOOKUP gibi)
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="overline" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
      {children}
    </Typography>
  )
}

// ---------- LDAP ----------
function LdapTab() {
  const { form, setForm, save } = useCategory('ldap')
  const { enqueueSnackbar } = useSnackbar()

  const test = useMutation({
    mutationFn: async () => (await api.post('/settings/ldap/test')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'error' }),
  })

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        LDAP etkinleştirildiğinde lokal olmayan kullanıcılar Active Directory ile doğrulanır. Giriş
        serbesttir ancak <b>yetki AD gruplarından DEĞİL, JUMBO'daki takım üyeliğinden</b> gelir:
        yeni giren kullanıcı, bir yönetici onu <b>Kullanıcılar</b> sekmesinden bir takıma ekleyene kadar
        hiçbir şey göremez. Acil erişim için lokal admin her zaman çalışır.
      </Alert>
      <FormControlLabel
        control={<Switch checked={!!form.enabled}
                         onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />}
        label="LDAP Kimlik Doğrulama Etkin" />

      <SectionLabel>Bağlantı</SectionLabel>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="server" label="Host (ldaps://dc.firma.local)"
              width={{ xs: 12, sm: 8 }} />
        <Text form={form} setForm={setForm} field="port" label="Port" type="number"
              helper="636 = LDAPS, 389 = düz/StartTLS" width={{ xs: 12, sm: 4 }} />
        <Grid size={{ xs: 12, sm: 4 }}>
          <FormControlLabel
            control={<Switch checked={!!form.use_ssl}
                             onChange={(e) => setForm((f) => ({ ...f, use_ssl: e.target.checked, ...(e.target.checked ? { start_tls: false } : {}) }))} />}
            label="LDAPS (doğrudan TLS, 636)" />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <FormControlLabel
            control={<Switch checked={!!form.start_tls} disabled={!!form.use_ssl}
                             onChange={(e) => setForm((f) => ({ ...f, start_tls: e.target.checked }))} />}
            label="StartTLS (legacy, 389)" />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <FormControlLabel
            control={<Switch checked={!!form.skip_cert_verify}
                             onChange={(e) => setForm((f) => ({ ...f, skip_cert_verify: e.target.checked }))} />}
            label="Sertifika doğrulamasını atla (dev)" />
        </Grid>
        <Text form={form} setForm={setForm} field="ca_cert"
              label="Dahili CA sertifikası (PEM, opsiyonel)" multiline rows={3}
              helper="AD dahili CA kullanıyorsa PEM demetini yapıştırın; boşsa sistem kökleri kullanılır."
              width={{ xs: 12, sm: 12 }} />
        <Text form={form} setForm={setForm} field="bind_dn" label="Bind DN (servis hesabı)"
              helper="Kullanıcı + grup araması için kullanılır" />
        <Text form={form} setForm={setForm} field="bind_password" label="Bind Şifresi" type="password"
              helper="Servis hesabı şifresi" />
      </Grid>

      <SectionLabel>Kullanıcı Araması</SectionLabel>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="base_dn" label="Base DN (DC=firma,DC=local)"
              helper="Kullanıcıların aranacağı yer" />
        <Text form={form} setForm={setForm} field="user_filter" label="Kullanıcı arama filtresi"
              helper="{username} çalışma anında değiştirilir" />
        <Text form={form} setForm={setForm} field="user_attr" label="Kullanıcı attribute"
              helper="ör. sAMAccountName" width={{ xs: 12, sm: 4 }} />
        <Text form={form} setForm={setForm} field="email_attr" label="E-posta attribute"
              helper="ör. mail" width={{ xs: 12, sm: 4 }} />
        <Text form={form} setForm={setForm} field="display_attr" label="Görünen ad attribute"
              helper="ör. displayName" width={{ xs: 12, sm: 4 }} />
      </Grid>

      <SectionLabel>Grup Araması (opsiyonel)</SectionLabel>
      <Alert severity="info">
        Bazı dizinler kullanıcı girdisinde <code>memberOf</code> doldurmaz. Grup tabanı + filtre
        verirseniz ayrı bir grup araması yapılır; aksi halde boş bırakın.
      </Alert>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="group_base" label="Grup arama tabanı"
              helper="ör. OU=Groups,DC=firma,DC=local" />
        <Text form={form} setForm={setForm} field="group_filter" label="Grup filtresi"
              helper="{user_dn} çalışma anında değiştirilir — ör. (member={user_dn})" />
      </Grid>

      <Stack direction="row" spacing={2}>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => test.mutate()} disabled={test.isPending}>
          Bağlantıyı Test Et
        </Button>
      </Stack>
    </Stack>
  )
}

// ---------- SMTP ----------
function SmtpTab() {
  const { form, setForm, save } = useCategory('smtp')
  const { enqueueSnackbar } = useSnackbar()

  const runNow = useMutation({
    mutationFn: async () => (await api.post('/notifications/expiry-run')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.enabled && d.sent > 0 ? 'success' : 'info' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const runExpired = useMutation({
    mutationFn: async () => (await api.post('/notifications/expired-run')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.enabled && d.sent > 0 ? 'success' : 'info' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const runProposals = useMutation({
    mutationFn: async () => (await api.post('/notifications/proposal-run')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.enabled && d.sent > 0 ? 'success' : 'info' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Etkinleştirilip <b>Günlük Otomatik Tarama</b> açıkken her sabah 08:00'de, bitişine
        <b> uyarı eşiğinden az gün kalan</b> sertifikalar için bilgilendirme maili gönderilir. Alıcılar (her biri <b>ayrı mail</b> alır): sertifikanın{' '}
        <b>sahibi</b> (oluşturan kullanıcı), bağlı olduğu <b>domainlerin SY ekipleri</b> ve client olarak
        bağlı olduğu <b>uygulamaların sahibi SY ekipleri</b>. "Şimdi Gönder" ile tarama anında da çalıştırılabilir.
      </Alert>
      <FormControlLabel
        control={<Switch checked={!!form.enabled}
                         onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />}
        label="E-posta Bildirimleri Etkin" />
      <Box>
        <FormControlLabel
          control={<Switch checked={form.auto_expiry_enabled !== false}
                           onChange={(e) => setForm((f) => ({ ...f, auto_expiry_enabled: e.target.checked }))} />}
          label="Günlük Otomatik Tarama (her sabah 08:00)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4, mt: -0.5 }}>
          Kapalıyken zamanlanmış tarama mail göndermez; <b>dış API tetiği</b> (X-API-Key / "Şimdi Gönder")
          çağrıldığında yine gönderim yapılır.
        </Typography>
      </Box>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="host" label="SMTP Sunucusu" />
        <Text form={form} setForm={setForm} field="port" label="Port" type="number" width={{ xs: 6, sm: 3 }} />
        <Grid size={{ xs: 6, sm: 3 }}>
          <FormControlLabel
            control={<Switch checked={!!form.use_tls}
                             onChange={(e) => setForm((f) => ({ ...f, use_tls: e.target.checked }))} />}
            label="STARTTLS" />
        </Grid>
        <Text form={form} setForm={setForm} field="username" label="Kullanıcı (opsiyonel)" />
        <Text form={form} setForm={setForm} field="password" label="Şifre" type="password" />
        <Text form={form} setForm={setForm} field="from_address" label="Gönderen Adres (From)"
              helper="Maillerin hangi adresten gideceği" />
        <Text form={form} setForm={setForm} field="expiry_warning_days" label="Uyarı Eşiği (gün)" type="number"
              helper="Bitişe bu kadar gün kalınca bilgilendirme gönderilir" />
        <Grid size={{ xs: 12, sm: 8 }}>
          <FormControlLabel
            control={<Switch checked={form.resend_dedup_enabled !== false}
                             onChange={(e) => setForm((f) => ({ ...f, resend_dedup_enabled: e.target.checked }))} />}
            label="Tekrar-Önleme Etkin (aynı sertifikaya kısa sürede tekrar mail atma)" />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4, mt: -0.5 }}>
            Kapatılırsa her tarama mail gönderir (günlük cron doğal olarak günde bir çalışır).
            "Şimdi Gönder" / dış API bu frenden zaten etkilenmez.
          </Typography>
        </Grid>
        <Text form={form} setForm={setForm} field="resend_interval_hours" label="Tekrar Aralığı (saat)" type="number"
              disabled={form.resend_dedup_enabled === false}
              helper="Pencereye giren sertifika için mailin kaç SAATTE bir tekrarlanacağı (varsayılan 3). Dış API 'Şimdi Gönder' bu freni atlar."
              width={{ xs: 6, sm: 4 }} />
        <Text form={form} setForm={setForm} field="fallback_address" label="Yedek/Varsayılan Adres"
              helper="Birincil gönderim başarısızsa ikinci deneme bu adrese yapılır (virgülle çoklu)."
              width={{ xs: 12, sm: 8 }} />
        <Text form={form} setForm={setForm} field="doc_links" label="Doküman Bağlantıları" multiline rows={3}
              helper="Maillerin en altına eklenir. Her satıra bir link/metin; http(s) linkleri tıklanabilir olur."
              width={{ xs: 12, sm: 12 }} />
        <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
              helper='Dış araç: POST /api/notifications/expiry-run + "X-API-Key: <anahtar>" başlığı. Boşsa dış tetikleme kapalı.'
              width={{ xs: 12, sm: 12 }} />
      </Grid>

      <Alert severity="info" sx={{ mt: 1 }}>
        <b>Gönderim Kuyruğu:</b> SMTP sağlayıcınızın gönderim limiti varsa mailler doğrudan gönderilmek
        yerine kuyruğa alınır ve <b>her boşaltma aralığında en fazla "tur başına mail"</b> kadarı gönderilir.
      </Alert>
      <FormControlLabel
        control={<Switch checked={!!form.queue_enabled}
                         onChange={(e) => setForm((f) => ({ ...f, queue_enabled: e.target.checked }))} />}
        label="Gönderim Kuyruğu Etkin" />
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="queue_batch_size" label="Tur Başına Azami Mail" type="number"
              helper="Her boşaltmada gönderilecek en fazla mail" width={{ xs: 6, sm: 4 }} />
        <Text form={form} setForm={setForm} field="queue_interval_minutes" label="Boşaltma Aralığı (dk)" type="number"
              helper="Kuyruğun kaç dakikada bir boşaltılacağı (>=1)" width={{ xs: 6, sm: 4 }} />
      </Grid>

      <Alert severity="info" sx={{ mt: 1 }}>
        <b>Devir Onayı Hatırlatması:</b> Onay kuyruğunda <b>bekleyen devir önerisi</b> olan SY ekiplerine
        (ekip başına <b>tek mail</b>, tüm bekleyen önerilerini listeler) hatırlatma gönderir — kuyruğun temiz
        tutulması için. Açıkken her gün belirtilen saatte; kapalıyken yalnız "Şimdi Hatırlat" / dış API ile.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={form.auto_proposal_reminder_enabled === true}
                           onChange={(e) => setForm((f) => ({ ...f, auto_proposal_reminder_enabled: e.target.checked }))} />}
          label="Günlük Devir Onayı Hatırlatması" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4, mt: -0.5 }}>
          Kapalıyken zamanlanmış hatırlatma gönderilmez; <b>dış API tetiği</b> (X-API-Key / "Şimdi Hatırlat")
          çağrıldığında yine gönderim yapılır.
        </Typography>
      </Box>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="proposal_reminder_hour" label="Hatırlatma Saati (0-23)" type="number"
              disabled={form.auto_proposal_reminder_enabled !== true}
              helper="Günlük hatırlatmanın gönderileceği saat (varsayılan 09:00). Dış API 'Şimdi Hatırlat' saatten bağımsızdır."
              width={{ xs: 6, sm: 4 }} />
      </Grid>

      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => runNow.mutate()} disabled={runNow.isPending}>
          Süre Uyarılarını Şimdi Gönder
        </Button>
        <Button variant="outlined" color="warning" onClick={() => runExpired.mutate()} disabled={runExpired.isPending}>
          Süresi Geçenleri Şimdi Gönder
        </Button>
        <Button variant="outlined" onClick={() => runProposals.mutate()} disabled={runProposals.isPending}>
          Bekleyen Önerileri Şimdi Hatırlat
        </Button>
      </Stack>
    </Stack>
  )
}

// ---------- Vault ----------
function VaultTab() {
  const { form, setForm, save } = useCategory('vault')
  const { enqueueSnackbar } = useSnackbar()
  const test = useMutation({
    mutationFn: async () => (await api.post('/settings/vault/test')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'warning' }),
  })
  return (
    <Stack spacing={2}>
      <Alert severity="warning">
        <b>Vault entegrasyonu — hazırlık aşaması.</b> Ayarlar şimdiden kaydedilir; otomatik sertifika
        yenileme (Vault PKI) bir sonraki fazda etkinleşecek. Sertifika kayıtlarında{' '}
        <code>source=vault</code> ve <code>auto_renew</code> alanları hazır.
      </Alert>
      <FormControlLabel
        control={<Switch checked={!!form.enabled}
                         onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />}
        label="Vault Entegrasyonu (yakında)" />
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="address" label="Vault Adresi (https://vault.firma.local:8200)" />
        <Grid size={{ xs: 12, sm: 6 }}>
          <TextField select fullWidth size="small" label="Kimlik Doğrulama"
                     value={String(form.auth_method ?? 'token')}
                     onChange={(e) => setForm((f) => ({ ...f, auth_method: e.target.value }))}>
            <MenuItem value="token">Token</MenuItem>
            <MenuItem value="approle">AppRole</MenuItem>
          </TextField>
        </Grid>
        {form.auth_method === 'approle' ? (
          <>
            <Text form={form} setForm={setForm} field="role_id" label="Role ID" />
            <Text form={form} setForm={setForm} field="secret_id" label="Secret ID" type="password" />
          </>
        ) : (
          <Text form={form} setForm={setForm} field="token" label="Token" type="password" />
        )}
        <Text form={form} setForm={setForm} field="pki_mount" label="PKI Mount Path" />
      </Grid>
      <Stack direction="row" spacing={2}>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => test.mutate()}>Bağlantıyı Test Et</Button>
      </Stack>
    </Stack>
  )
}

// ---------- Kullanıcılar ----------
const ROLE_CHIP: Record<string, { label: string; color: 'default' | 'error' | 'primary' | 'warning' | 'info' }> = {
  admin: { label: 'Yönetici', color: 'error' },
  editor: { label: 'Ekip Editörü', color: 'primary' },
  viewer: { label: 'Ekip İzleyici', color: 'info' },
  allviewer: { label: 'Genel İzleyici', color: 'default' },
  none: { label: 'Yetkisiz', color: 'warning' },
}
// Rol atama seçenekleri (Kullanıcılar sekmesi). Açıklamalar dropdown'da gösterilir.
const ROLE_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: 'admin', label: 'Yönetici', hint: 'Her şeyi görür ve düzenler' },
  { value: 'editor', label: 'Ekip Editörü', hint: 'Yalnız kendi SY ekiplerini görür ve düzenler' },
  { value: 'viewer', label: 'Ekip İzleyici', hint: 'Yalnız kendi SY ekiplerini görür (düzenleyemez)' },
  { value: 'allviewer', label: 'Genel İzleyici', hint: 'Her şeyi görür ama düzenleyemez' },
  { value: 'none', label: 'Yetkisiz', hint: 'Rol atanmadı — hiçbir şey göremez' },
]

function UsersTab() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', email: '', full_name: '', auth_source: 'local', role: 'none' })
  // Takım düzenleme diyaloğu: hangi kullanıcı + seçili takım id'leri
  const [teamEdit, setTeamEdit] = useState<AppUser | null>(null)
  const [teamSel, setTeamSel] = useState<number[]>([])

  const { data: users } = useQuery<AppUser[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
  })
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams', 'all'],
    queryFn: async () => (await api.get('/teams')).data,
  })
  // Tüm takım tipleri (SY/ADMIN/VIEWER/UG) burada yönetilir — rol HER ZAMAN users.role'den atanır,
  // üyelik tek başına rol VERMEZ (SY yalnız kapsam belirler; ADMIN/VIEWER/UG roster bilgi amaçlı).
  const manageableTeams = useMemo(() => teams ?? [], [teams])

  const openTeamEdit = (u: AppUser) => { setTeamEdit(u); setTeamSel(u.team_ids ?? []) }
  const saveTeams = useMutation({
    mutationFn: async () => {
      if (!teamEdit) return
      const before = new Set(teamEdit.team_ids ?? [])
      const after = new Set(teamSel)
      const toAdd = [...after].filter((id) => !before.has(id))
      // yalnız bu picker'ın bildiği (manageableTeams) takımlardan çıkar
      const toRemove = [...before].filter((id) => !after.has(id)
        && manageableTeams.some((t) => t.id === id))
      await Promise.all([
        ...toAdd.map((tid) => api.post(`/teams/${tid}/members`, { user_id: teamEdit.id })),
        ...toRemove.map((tid) => api.delete(`/teams/${tid}/members/${teamEdit.id}`)),
      ])
    },
    onSuccess: () => {
      enqueueSnackbar('Kullanıcının takımları güncellendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['team-members'] })
      setTeamEdit(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const create = useMutation({
    mutationFn: async () => api.post('/users', { ...form, password: form.password || null }),
    onSuccess: () => {
      enqueueSnackbar('Kullanıcı eklendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDialogOpen(false)
      setForm({ username: '', password: '', email: '', full_name: '', auth_source: 'local', role: 'none' })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const update = useMutation({
    mutationFn: async ({ id, body }: { id: number; body: Record<string, unknown> }) => api.put(`/users/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/users/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Kullanıcı silindi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Rolü doğrudan <b>Rol</b> sütunundan atarsınız: <b>Yönetici</b> (her şeyi görür+düzenler),
        {' '}<b>Ekip Editörü</b> (kendi SY ekiplerini görür+düzenler), <b>Ekip İzleyici</b> (kendi SY
        ekiplerini yalnız görür), <b>Genel İzleyici</b> (her şeyi görür, düzenleyemez). <b>Editör</b> ve
        {' '}<b>Ekip İzleyici</b> takım-kapsamlıdır — kapsamı belirlemek için ayrıca bir <b>SY takımına</b>
        {' '}(Takımlar sütunu) ekleyin. Rolü <b>Yetkisiz</b> olan hiçbir şey göremez.
      </Alert>
      <Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
          Kullanıcı Ekle
        </Button>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Kullanıcı</TableCell>
            <TableCell>Ad Soyad</TableCell>
            <TableCell>E-posta</TableCell>
            <TableCell>Kaynak</TableCell>
            <TableCell>Rol</TableCell>
            <TableCell>Takımlar (kapsam)</TableCell>
            <TableCell>Aktif</TableCell>
            <TableCell>Son Giriş</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {(users ?? []).map((u) => (
            <TableRow key={u.id} hover>
              <TableCell sx={{ fontWeight: 600 }}>{u.username}</TableCell>
              <TableCell>{u.full_name ?? '—'}</TableCell>
              <TableCell>{u.email ?? '—'}</TableCell>
              <TableCell><Chip size="small" variant="outlined" label={u.auth_source.toUpperCase()} /></TableCell>
              <TableCell>
                <TextField select size="small" variant="standard" value={u.role}
                           onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })}
                           sx={{ minWidth: 140 }}>
                  {ROLE_OPTIONS.map((o) => (
                    <MenuItem key={o.value} value={o.value}>
                      <Chip size="small" color={ROLE_CHIP[o.value]?.color ?? 'default'} label={o.label}
                            sx={{ mr: 1, pointerEvents: 'none' }} />
                    </MenuItem>
                  ))}
                </TextField>
              </TableCell>
              <TableCell>
                {(u.team_names && u.team_names.length > 0)
                  ? <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                      {u.team_names.map((n) => <Chip key={n} size="small" variant="outlined" label={n} />)}
                    </Stack>
                  : <span style={{ opacity: 0.5 }}>—</span>}
              </TableCell>
              <TableCell>
                <Switch size="small" checked={u.is_active}
                        onChange={(e) => update.mutate({ id: u.id, body: { is_active: e.target.checked } })} />
              </TableCell>
              <TableCell>{u.last_login ? new Date(u.last_login).toLocaleString('tr-TR') : '—'}</TableCell>
              <TableCell align="right">
                <Tooltip title="Takımları Düzenle">
                  <IconButton size="small" color="primary" onClick={() => openTeamEdit(u)}>
                    <GroupsIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Sil">
                  <IconButton size="small" color="error" onClick={() => remove.mutate(u.id)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Kullanıcı Ekle</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Kullanıcı Adı" size="small" value={form.username}
                       onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
            <TextField select label="Kaynak" size="small" value={form.auth_source}
                       onChange={(e) => setForm((f) => ({ ...f, auth_source: e.target.value }))}>
              <MenuItem value="local">Lokal</MenuItem>
              <MenuItem value="ldap">LDAP (ön kayıt)</MenuItem>
            </TextField>
            {form.auth_source === 'local' && (
              <TextField label="Şifre" type="password" size="small" value={form.password}
                         onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
            )}
            <TextField label="Ad Soyad" size="small" value={form.full_name}
                       onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
            <TextField label="E-posta" size="small" value={form.email}
                       onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            <TextField select label="Rol" size="small" value={form.role}
                       onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                       helperText={ROLE_OPTIONS.find((o) => o.value === form.role)?.hint}>
              {ROLE_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
            </TextField>
            {(form.role === 'editor' || form.role === 'viewer') && (
              <Alert severity="info" sx={{ py: 0.5 }}>
                <b>{form.role === 'editor' ? 'Ekip Editörü' : 'Ekip İzleyici'}</b> takım-kapsamlıdır:
                ekledikten sonra <b>Ekip Üyelikleri</b>'nden bir <b>SY takımına</b> atayın — aksi halde
                hangi ekibi göreceği belirsizdir (boş kapsam).
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => create.mutate()}
                  disabled={!form.username || (form.auth_source === 'local' && !form.password)}>
            Ekle
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!teamEdit} onClose={() => setTeamEdit(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Takımları Düzenle — {teamEdit?.username}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info" sx={{ py: 0.5 }}>
              <b>SY ekip üyeliği kapsam belirler</b>: <b>Ekip Editörü/İzleyici</b> rolündeki
              kullanıcı yalnız seçilen SY ekiplerinin domain/uygulamalarını görür. <b>ADMIN/
              VIEWER/UG üyeliği yalnız roster (bilgi) amaçlıdır — tek başına rol/yetki VERMEZ.</b>{' '}
              <b>Rol</b> her zaman Rol sütunundan atanır. Birden çok ekip seçilebilir.
            </Alert>
            <Autocomplete
              multiple size="small" options={manageableTeams}
              value={manageableTeams.filter((t) => teamSel.includes(t.id))}
              getOptionLabel={(t) => `${t.name} · ${TEAM_TYPE_LABEL[t.type] ?? t.type}`}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              onChange={(_, v) => setTeamSel(v.map((t) => t.id))}
              renderInput={(p) => <TextField {...p} label="Takımlar" placeholder="Takım seç" />}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTeamEdit(null)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => saveTeams.mutate()} disabled={saveTeams.isPending}>
            Kaydet
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

// ---------- Ekipler / Ekip Üyelikleri ----------
const TEAM_TYPE_LABEL: Record<string, string> = {
  ADMIN: 'Yönetici (tam yetki)', VIEWER: 'İzleyici (salt-okur)', SY: 'SY ekibi', UG: 'UG',
}
const TEAM_TYPE_COLOR: Record<string, 'error' | 'warning' | 'primary' | 'default'> = {
  ADMIN: 'error', VIEWER: 'warning', SY: 'primary', UG: 'default',
}

// ---------- Ekipler (takım oluştur / düzenle / sil) ----------
function TeamsTab() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Team | null>(null)
  const [form, setForm] = useState({ name: '', type: 'SY', email: '' })

  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams', 'all'],
    queryFn: async () => (await api.get('/teams')).data,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['teams'] })

  const openCreate = () => { setEditTarget(null); setForm({ name: '', type: 'SY', email: '' }); setDialogOpen(true) }
  const openEdit = (t: Team) => {
    setEditTarget(t); setForm({ name: t.name, type: t.type, email: t.email ?? '' }); setDialogOpen(true)
  }

  const save = useMutation({
    mutationFn: async () => {
      const email = form.email.trim() || null
      if (editTarget) return api.put(`/teams/${editTarget.id}`, { name: form.name.trim(), email })
      return api.post('/teams', { name: form.name.trim(), type: form.type, email })
    },
    onSuccess: () => {
      enqueueSnackbar(editTarget ? 'Ekip güncellendi' : 'Ekip eklendi', { variant: 'success' })
      invalidate(); setDialogOpen(false)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/teams/${id}`),
    onSuccess: () => { enqueueSnackbar('Ekip silindi', { variant: 'info' }); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const isSingleton = (t: Team) => t.type === 'ADMIN' || t.type === 'VIEWER'

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Ekipler yetkinin temelidir: <b>SY</b> ekipleri domain/uygulama sahibi olur (bildirim e-postası
        buradan gelir); <b>UG</b> yalnız etikettir. <b>Yönetici</b> ve <b>İzleyici</b> sistem tekilidir —
        silinemez, tipi değişmez. Üyeleri <b>Ekip Üyelikleri</b> sekmesinden yönetin.
      </Alert>
      <Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>Ekip Ekle</Button>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Ekip Adı</TableCell>
            <TableCell>Tip</TableCell>
            <TableCell>Bildirim E-postası</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {(teams ?? []).map((t) => (
            <TableRow key={t.id} hover>
              <TableCell sx={{ fontWeight: 600 }}>{t.name}</TableCell>
              <TableCell>
                <Chip size="small" color={TEAM_TYPE_COLOR[t.type] ?? 'default'}
                      label={TEAM_TYPE_LABEL[t.type] ?? t.type} />
              </TableCell>
              <TableCell sx={{ color: t.email ? 'inherit' : 'text.disabled' }}>{t.email ?? '—'}</TableCell>
              <TableCell align="right">
                <Tooltip title="Düzenle">
                  <IconButton size="small" onClick={() => openEdit(t)}><EditIcon fontSize="small" /></IconButton>
                </Tooltip>
                <Tooltip title={isSingleton(t) ? 'Sistem takımı — silinemez' : 'Sil'}>
                  <span>
                    <IconButton size="small" color="error" disabled={isSingleton(t) || remove.isPending}
                                onClick={() => remove.mutate(t.id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {teams && teams.length === 0 && (
            <TableRow><TableCell colSpan={4} align="center" sx={{ py: 4 }}>Henüz ekip yok</TableCell></TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{editTarget ? `Ekip Düzenle — ${editTarget.name}` : 'Ekip Ekle'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Ekip Adı" size="small" value={form.name} autoFocus
                       onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            {editTarget ? (
              <TextField label="Tip" size="small" disabled
                         value={TEAM_TYPE_LABEL[form.type] ?? form.type}
                         helperText="Ekip tipi oluşturulduktan sonra değiştirilemez" />
            ) : (
              <TextField select label="Tip" size="small" value={form.type}
                         onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
                         helperText="Yönetici/İzleyici sistem tekilidir; API'den yalnız SY/UG oluşturulur">
                <MenuItem value="SY">SY ekibi (domain/uygulama sahibi)</MenuItem>
                <MenuItem value="UG">UG (yalnız etiket)</MenuItem>
              </TextField>
            )}
            <TextField label="Bildirim E-postası" size="small" type="email" value={form.email}
                       onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                       placeholder="ör. moneytalks@banka.local, noc@banka.local"
                       helperText="SY ekipleri için bildirim kaynağı. Birden çok adresi virgülle ayırın (opsiyonel)." />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => save.mutate()}
                  disabled={!form.name.trim() || save.isPending}>
            {editTarget ? 'Kaydet' : 'Ekle'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

function MembershipsTab() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [teamId, setTeamId] = useState<number | null>(null)
  const [toAdd, setToAdd] = useState<AppUser | null>(null)
  const [emailDraft, setEmailDraft] = useState('')

  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams', 'all'],
    queryFn: async () => (await api.get('/teams')).data,
  })
  const { data: users } = useQuery<AppUser[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
  })
  const { data: members } = useQuery<TeamMember[]>({
    queryKey: ['team-members', teamId],
    queryFn: async () => (await api.get(`/teams/${teamId}/members`)).data,
    enabled: teamId != null,
  })

  // Tüm takım tipleri (SY/ADMIN/VIEWER/UG) burada yönetilir. SY üyeliği KAPSAM belirler; diğerleri
  // (ADMIN/VIEWER/UG) yalnız roster/bilgi amaçlıdır — rol her zaman Kullanıcılar sekmesinden atanır.
  const manageable = useMemo(() => teams ?? [], [teams])
  const effectiveTeam = teamId ?? manageable[0]?.id ?? null
  const selectedTeam = manageable.find((t) => t.id === effectiveTeam) ?? null
  const memberIds = useMemo(() => new Set((members ?? []).map((m) => m.id)), [members])
  const candidates = (users ?? []).filter((u) => !memberIds.has(u.id))

  // Seçili ekip değişince e-posta taslağını ekibin kayıtlı adresiyle senkronla
  useEffect(() => { setEmailDraft(selectedTeam?.email ?? '') }, [selectedTeam?.id, selectedTeam?.email])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['team-members'] })
    queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  const saveEmail = useMutation({
    mutationFn: async () =>
      (await api.put(`/teams/${effectiveTeam}`, { email: emailDraft.trim() || null })).data,
    onSuccess: () => {
      enqueueSnackbar('Ekip e-postası güncellendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const add = useMutation({
    mutationFn: async (userId: number) =>
      (await api.post(`/teams/${effectiveTeam}/members`, { user_id: userId })).data,
    onSuccess: () => { enqueueSnackbar('Üye eklendi', { variant: 'success' }); setToAdd(null); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const remove = useMutation({
    mutationFn: async (userId: number) =>
      (await api.delete(`/teams/${effectiveTeam}/members/${userId}`)).data,
    onSuccess: () => { enqueueSnackbar('Üyelik kaldırıldı', { variant: 'info' }); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 2 }}>
        SY ekip üyeliği <b>kapsamı</b> belirler: <b>Ekip Editörü</b> ve <b>Ekip İzleyici</b> rolündeki
        kullanıcılar yalnız üye oldukları SY ekiplerinin domain/uygulamalarını (ve devir önerilerini)
        görür. <b>ADMIN/VIEWER/UG üyeliği yalnız roster (bilgi) amaçlıdır — tek başına rol/yetki
        VERMEZ.</b> <b>Rolün kendisi</b> (Yönetici/Editör/İzleyici) her zaman <b>Kullanıcılar</b>
        sekmesinden atanır.
      </Alert>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField select size="small" label="Takım" sx={{ minWidth: 260 }}
                   value={effectiveTeam ?? ''} onChange={(e) => setTeamId(Number(e.target.value))}>
          {manageable.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.name} · {TEAM_TYPE_LABEL[t.type] ?? t.type}
            </MenuItem>
          ))}
        </TextField>
        <Autocomplete
          size="small" sx={{ minWidth: 280, flexGrow: 1 }} options={candidates}
          value={toAdd}
          getOptionLabel={(u) => `${u.username}${u.full_name ? ` — ${u.full_name}` : ''}`}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          onChange={(_, v) => setToAdd(v)}
          renderInput={(p) => <TextField {...p} label="Giriş yapmış kullanıcı ekle" />}
        />
        <Button variant="contained" startIcon={<AddIcon />} disabled={!toAdd || add.isPending}
                onClick={() => toAdd && add.mutate(toAdd.id)}>Ekle</Button>
      </Stack>

      {selectedTeam?.type === 'SY' && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}
               sx={{ mt: 2, alignItems: { sm: 'flex-start' } }}>
          <TextField size="small" type="email" sx={{ minWidth: 320, flexGrow: 1 }}
                     label={`${selectedTeam?.name ?? 'Ekip'} bildirim e-postası`}
                     placeholder="ör. moneytalks@banka.local, noc@banka.local"
                     value={emailDraft} onChange={(e) => setEmailDraft(e.target.value)}
                     helperText="Bu ekibin domainleri için TEK bildirim kaynağı. Birden çok adresi virgülle ayırın." />
          <Button variant="outlined" sx={{ mt: 0.25 }}
                  disabled={!effectiveTeam || saveEmail.isPending
                            || emailDraft.trim() === (selectedTeam?.email ?? '')}
                  onClick={() => saveEmail.mutate()}>E-postayı Kaydet</Button>
        </Stack>
      )}

      <Table size="small" sx={{ mt: 2 }}>
        <TableHead>
          <TableRow>
            <TableCell>Kullanıcı</TableCell>
            <TableCell>Ad Soyad</TableCell>
            <TableCell>E-posta</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {(members ?? []).map((m) => (
            <TableRow key={m.id} hover>
              <TableCell sx={{ fontWeight: 600 }}>{m.username}</TableCell>
              <TableCell>{m.full_name ?? '—'}</TableCell>
              <TableCell>{m.email ?? '—'}</TableCell>
              <TableCell align="right">
                <Tooltip title="Üyelikten çıkar">
                  <IconButton size="small" color="error" onClick={() => remove.mutate(m.id)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {members && members.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} align="center" sx={{ py: 4 }}>
                Bu ekibin üyesi yok
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Box>
  )
}

// ---------- Audit ----------
function AuditTab() {
  const { enqueueSnackbar } = useSnackbar()
  const [filterUser, setFilterUser] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  // Aynı parametreler hem listeyi filtreler hem export'a gider → ekranda gördüğün = indirdiğin.
  const params = {
    username: filterUser || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  }
  const { data: entries } = useQuery<AuditEntry[]>({
    queryKey: ['audit', filterUser, dateFrom, dateTo],
    queryFn: async () => (await api.get('/audit', { params })).data,
  })
  const exportCsv = useMutation({
    mutationFn: async () => {
      const res = await api.get('/audit/export', { params, responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit_${dateFrom || 'all'}_${dateTo || 'all'}.csv`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const ACTION_COLOR: Record<string, 'success' | 'info' | 'error' | 'warning' | 'default'> = {
    create: 'success', import: 'success', update: 'info', delete: 'error', login: 'default',
  }
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ alignItems: { md: 'center' } }}>
        <TextField size="small" label="Kullanıcıya göre filtrele" value={filterUser}
                   onChange={(e) => setFilterUser(e.target.value)} sx={{ minWidth: 220 }} />
        <TextField size="small" type="date" label="Başlangıç" value={dateFrom}
                   onChange={(e) => setDateFrom(e.target.value)} sx={{ width: 170 }}
                   slotProps={{ inputLabel: { shrink: true } }} />
        <TextField size="small" type="date" label="Bitiş" value={dateTo}
                   onChange={(e) => setDateTo(e.target.value)} sx={{ width: 170 }}
                   slotProps={{ inputLabel: { shrink: true } }} />
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="outlined" startIcon={<FileDownloadIcon />}
                onClick={() => exportCsv.mutate()} disabled={exportCsv.isPending}>
          Dışa Aktar (CSV)
        </Button>
      </Stack>
      <Typography variant="caption" color="text.secondary">
        Tarihler <b>dâhil</b>dir (bitiş günü gün sonuna kadar). Liste en çok 1000 satır gösterir; <b>export
        tüm aralığı</b> indirir. Boş bırakılan tarih = sınırsız uç.
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Tarih</TableCell>
            <TableCell>Kullanıcı</TableCell>
            <TableCell>İşlem</TableCell>
            <TableCell>Tablo</TableCell>
            <TableCell>Kayıt</TableCell>
            <TableCell>Detay</TableCell>
            <TableCell>IP</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {(entries ?? []).map((e) => (
            <TableRow key={e.id} hover>
              <TableCell>{new Date(e.created_at).toLocaleString('tr-TR')}</TableCell>
              <TableCell>{e.username}</TableCell>
              <TableCell><Chip size="small" color={ACTION_COLOR[e.action] ?? 'default'} label={e.action} /></TableCell>
              <TableCell>{e.table_name}</TableCell>
              <TableCell>{e.record_id ?? '—'}</TableCell>
              <TableCell sx={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 11 }}>
                {e.details ?? '—'}
              </TableCell>
              <TableCell sx={{ fontFamily: 'monospace', fontSize: 11 }}>{e.ip_address ?? '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Stack>
  )
}

// ---------- Mail Gönderim Geçmişi ----------
const MAIL_STATUS: Record<string, { color: 'success' | 'warning' | 'error'; label: string }> = {
  sent: { color: 'success', label: 'Gönderildi' },
  pending: { color: 'warning', label: 'Kuyrukta' },
  failed: { color: 'error', label: 'Başarısız' },
}

function MailHistoryTab() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('email')  // vars. mail; 'Tümü' → tüm kanallar
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const params = {
    search: search || undefined, status: status || undefined, channel: channel || undefined,
    date_from: dateFrom || undefined, date_to: dateTo || undefined,
  }
  const { data: entries, isLoading } = useQuery<MailHistoryEntry[]>({
    queryKey: ['mail-history', search, status, channel, dateFrom, dateTo],
    queryFn: async () => (await api.get('/notifications/history', { params })).data,
  })
  const rows = entries ?? []
  // Ekranda görünen = indirilen (aynı satırlar). CSV util'i \r-güvenli (çok-satırlı konu/hata bozmaz).
  const onExport = () => exportCsv(
    `mail_gecmisi_${dateFrom || 'all'}_${dateTo || 'all'}.csv`,
    ['Tarih', 'Alıcı', 'Sertifika', 'Konu', 'Kalan Gün', 'Kanal', 'Durum', 'Hata'],
    rows.map((r) => [
      r.sent_at ? new Date(r.sent_at).toLocaleString('tr-TR') : '',
      r.recipient ?? '', r.certificate_name ?? '', r.subject ?? '',
      r.days_left ?? '', r.channel, MAIL_STATUS[r.status]?.label ?? r.status, r.error ?? '',
    ]),
  )
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}
             sx={{ alignItems: { md: 'center' }, flexWrap: 'wrap' }}>
        <TextField size="small" label="Alıcı / konu ara" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 220 }} />
        <TextField select size="small" label="Durum" value={status}
                   onChange={(e) => setStatus(e.target.value)} sx={{ width: 150 }}
                   slotProps={{ inputLabel: { shrink: true } }}>
          <MenuItem value="">Tümü</MenuItem>
          <MenuItem value="sent">Gönderildi</MenuItem>
          <MenuItem value="pending">Kuyrukta</MenuItem>
          <MenuItem value="failed">Başarısız</MenuItem>
        </TextField>
        <TextField select size="small" label="Kanal" value={channel}
                   onChange={(e) => setChannel(e.target.value)} sx={{ width: 150 }}
                   slotProps={{ inputLabel: { shrink: true } }}>
          <MenuItem value="email">E-posta</MenuItem>
          <MenuItem value="">Tümü</MenuItem>
        </TextField>
        <TextField size="small" type="date" label="Başlangıç" value={dateFrom}
                   onChange={(e) => setDateFrom(e.target.value)} sx={{ width: 170 }}
                   slotProps={{ inputLabel: { shrink: true } }} />
        <TextField size="small" type="date" label="Bitiş" value={dateTo}
                   onChange={(e) => setDateTo(e.target.value)} sx={{ width: 170 }}
                   slotProps={{ inputLabel: { shrink: true } }} />
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="outlined" startIcon={<FileDownloadIcon />} onClick={onExport}
                disabled={!rows.length}>Dışa Aktar (CSV)</Button>
      </Stack>
      <Typography variant="caption" color="text.secondary">
        Gönderilen bilgilendirme e-postaları <b>ve teslim edilemeyen</b> (kuyrukta/başarısız)
        kayıtlar. Tarihler <b>dâhil</b>dir; liste en çok 1000 satır gösterir. Boş tarih = sınırsız uç.
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Tarih</TableCell>
            <TableCell>Alıcı</TableCell>
            <TableCell>Sertifika</TableCell>
            <TableCell>Konu</TableCell>
            <TableCell>Kalan Gün</TableCell>
            <TableCell>Kanal</TableCell>
            <TableCell>Durum</TableCell>
            <TableCell>Hata</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={`${r.source}-${r.id}`} hover>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>
                {r.sent_at ? new Date(r.sent_at).toLocaleString('tr-TR') : '—'}
              </TableCell>
              <TableCell sx={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.recipient ?? '—'}
              </TableCell>
              <TableCell>{r.certificate_name ?? '—'}</TableCell>
              <TableCell sx={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.subject ?? '—'}
              </TableCell>
              <TableCell>
                {r.days_left === null || r.days_left === undefined
                  ? '—'
                  : <Chip size="small" color={daysLeftColor(r.days_left)} label={daysLeftLabel(r.days_left)} />}
              </TableCell>
              <TableCell>{r.channel}</TableCell>
              <TableCell>
                <Chip size="small" color={MAIL_STATUS[r.status]?.color ?? 'default'}
                      label={MAIL_STATUS[r.status]?.label ?? r.status} />
              </TableCell>
              <TableCell sx={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis',
                               whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 11, color: 'error.main' }}>
                {r.error ?? '—'}
              </TableCell>
            </TableRow>
          ))}
          {!isLoading && !rows.length && (
            <TableRow>
              <TableCell colSpan={8}>
                <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
                  Kayıt yok — henüz mail gönderilmemiş ya da filtrelerle eşleşen kayıt bulunamadı.
                </Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Stack>
  )
}

// ---------- Etiketler (tag kataloğu) ----------
function TagsTab() {
  const { isAdmin } = useAuth()  // yeni KATEGORİ + düzenle/sil yalnız admin; etiket ekleme herkes
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { data: tags } = useQuery<Tag[]>({
    queryKey: ['tags'],
    queryFn: async () => (await api.get('/tags')).data,
  })
  const [addForm, setAddForm] = useState({ category: '', name: '', color: '#1565C0' })
  const [editTarget, setEditTarget] = useState<Tag | null>(null)
  const [editForm, setEditForm] = useState({ category: '', name: '', color: '' })
  const [deleteTarget, setDeleteTarget] = useState<Tag | null>(null)
  const categories = useMemo(() => Array.from(new Set((tags ?? []).map((t) => t.category))), [tags])
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['tags'] })

  const addMutation = useMutation({
    mutationFn: async () => api.post('/tags', {
      name: addForm.name.trim(), category: addForm.category.trim(), color: addForm.color.trim() || null,
    }),
    onSuccess: () => {
      enqueueSnackbar('Etiket eklendi', { variant: 'success' })
      setAddForm((f) => ({ category: f.category, name: '', color: '' }))  // kategoriyi koru (seri ekleme)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const editMutation = useMutation({
    mutationFn: async () => api.put(`/tags/${editTarget!.id}`, {
      name: editForm.name.trim(), category: editForm.category.trim(), color: editForm.color.trim() || null,
    }),
    onSuccess: () => { enqueueSnackbar('Etiket güncellendi', { variant: 'success' }); setEditTarget(null); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/tags/${id}`),
    onSuccess: () => { enqueueSnackbar('Etiket silindi', { variant: 'success' }); setDeleteTarget(null); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const openEdit = (t: Tag) => { setEditForm({ category: t.category, name: t.name, color: t.color ?? '#1565C0' }); setEditTarget(t) }

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 2 }}>
        Etiketler kontrollü kataloğdur — uygulamalara atanıp <b>kategori</b> bazında filtrelenir.
        Herkes mevcut bir kategoriye etiket ekleyebilir; <b>yeni kategori açma ve düzenleme/silme
        yalnız yöneticidedir</b>. Aynı ad farklı kategoride olabilir.
        {isAdmin && ' Bir etiketi silmek onu tüm uygulamalardan kaldırır.'}
      </Alert>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 2, alignItems: 'flex-start' }}>
        {isAdmin ? (
          // Admin: mevcutlardan seç VEYA yazarak YENİ kategori aç
          <Autocomplete freeSolo options={categories} size="small" sx={{ minWidth: 180 }}
                        value={addForm.category}
                        onInputChange={(_, v) => setAddForm((f) => ({ ...f, category: v }))}
                        renderInput={(params) => <TextField {...params} label="Kategori"
                          placeholder="Ürün" helperText="Yazarak yeni kategori açabilirsiniz" />} />
        ) : (
          // Diğer kullanıcılar: yalnız MEVCUT kategorilerden seçim (yeni kategori admin işi)
          <TextField select size="small" label="Kategori" sx={{ minWidth: 180 }}
                     value={addForm.category}
                     onChange={(e) => setAddForm((f) => ({ ...f, category: e.target.value }))}
                     helperText="Yeni kategoriyi yönetici açar">
            {categories.length === 0 && <MenuItem value="" disabled>Kategori yok</MenuItem>}
            {categories.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
          </TextField>
        )}
        <TextField size="small" label="Etiket adı" value={addForm.name} sx={{ minWidth: 180 }}
                   onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))} />
        <TextField size="small" type="color" label="Renk" value={addForm.color} sx={{ width: 90 }}
                   onChange={(e) => setAddForm((f) => ({ ...f, color: e.target.value }))}
                   slotProps={{ inputLabel: { shrink: true } }} />
        <Button variant="contained" startIcon={<AddIcon />} sx={{ mt: 0.25 }}
                disabled={!addForm.name.trim() || !addForm.category.trim() || addMutation.isPending}
                onClick={() => addMutation.mutate()}>Ekle</Button>
      </Stack>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Kategori</TableCell>
            <TableCell>Etiket</TableCell>
            <TableCell>Renk</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {(tags ?? []).map((t) => (
            <TableRow key={t.id} hover>
              <TableCell>{t.category}</TableCell>
              <TableCell>
                <Chip size="small" label={t.name} variant="outlined"
                      sx={t.color ? { borderColor: t.color, color: t.color } : undefined} />
              </TableCell>
              <TableCell>
                {t.color ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box sx={{ width: 16, height: 16, borderRadius: '3px', bgcolor: t.color }} />
                    <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{t.color}</Typography>
                  </Box>
                ) : '—'}
              </TableCell>
              <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                {isAdmin && (
                  <>
                    <Tooltip title="Düzenle">
                      <IconButton size="small" color="primary" onClick={() => openEdit(t)}><EditIcon fontSize="small" /></IconButton>
                    </Tooltip>
                    <Tooltip title="Sil">
                      <IconButton size="small" color="error" onClick={() => setDeleteTarget(t)}><DeleteIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  </>
                )}
              </TableCell>
            </TableRow>
          ))}
          {(tags ?? []).length === 0 && (
            <TableRow><TableCell colSpan={4} align="center" sx={{ py: 5, color: 'text.secondary' }}>
              Henüz etiket yok. Yukarıdan ekleyin.
            </TableCell></TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={!!editTarget} onClose={() => setEditTarget(null)}>
        <DialogTitle>Etiket Düzenle</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1, minWidth: 320 }}>
            <Autocomplete freeSolo options={categories} value={editForm.category} size="small"
                          onInputChange={(_, v) => setEditForm((f) => ({ ...f, category: v }))}
                          renderInput={(params) => <TextField {...params} label="Kategori" />} />
            <TextField size="small" label="Etiket adı" value={editForm.name}
                       onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
            <TextField size="small" type="color" label="Renk" value={editForm.color || '#1565C0'}
                       onChange={(e) => setEditForm((f) => ({ ...f, color: e.target.value }))}
                       slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 120 }} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Vazgeç</Button>
          <Button variant="contained"
                  disabled={!editForm.name.trim() || !editForm.category.trim() || editMutation.isPending}
                  onClick={() => editMutation.mutate()}>Kaydet</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Etiket Sil</DialogTitle>
        <DialogContent>
          <Typography><b>{deleteTarget?.category}: {deleteTarget?.name}</b> silinecek ve tüm
            uygulamalardan kaldırılacak. Emin misiniz?</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Vazgeç</Button>
          <Button color="error" variant="contained"
                  onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}>Sil</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}


// ---------- Ağ Keşfi (Discovery) ----------
const KIND_LABEL: Record<ScanTarget['kind'], string> = {
  cidr: 'CIDR', host: 'Host', inventory: 'Envanter',
}

function ScanTargetDialog({ open, target, syTeams, onClose }: {
  open: boolean
  target: ScanTarget | null
  syTeams: Team[]
  onClose: () => void
}) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  type Form = { name: string; kind: ScanTarget['kind']; value: string; ports: string; enabled: boolean; sy_team_id: number | '' }
  const [f, setF] = useState<Form>({ name: '', kind: 'cidr', value: '', ports: '', enabled: true, sy_team_id: '' })

  useEffect(() => {
    if (!open) return
    setF(target
      ? { name: target.name, kind: target.kind, value: target.value ?? '', ports: target.ports ?? '',
          enabled: target.enabled, sy_team_id: target.sy_team_id ?? '' }
      : { name: '', kind: 'cidr', value: '', ports: '', enabled: true, sy_team_id: '' })
  }, [open, target])

  const mut = useMutation({
    mutationFn: async () => {
      const payload = {
        name: f.name, kind: f.kind, value: f.kind === 'inventory' ? null : f.value,
        ports: f.ports || null, enabled: f.enabled, sy_team_id: f.sy_team_id === '' ? null : f.sy_team_id,
      }
      return target ? api.put(`/discovery/targets/${target.id}`, payload)
                    : api.post('/discovery/targets', payload)
    },
    onSuccess: () => {
      enqueueSnackbar(target ? 'Hedef güncellendi' : 'Hedef eklendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['discovery', 'targets'] })
      onClose()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const valid = f.name.trim() !== '' && (f.kind === 'inventory' || f.value.trim() !== '')

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{target ? 'Hedefi Düzenle' : 'Tarama Hedefi Ekle'}</DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Ad" fullWidth size="small" required value={f.name}
                       onChange={(e) => setF({ ...f, name: e.target.value })} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select label="Tür" fullWidth size="small" value={f.kind}
                       onChange={(e) => setF({ ...f, kind: e.target.value as ScanTarget['kind'] })}>
              <MenuItem value="cidr">CIDR aralığı</MenuItem>
              <MenuItem value="host">Tekil host / IP</MenuItem>
              <MenuItem value="inventory">Envanter domainleri</MenuItem>
            </TextField>
          </Grid>
          {f.kind !== 'inventory' && (
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField label={f.kind === 'cidr' ? 'CIDR (ör. 10.1.2.0/24)' : 'Host / IP'} required
                         fullWidth size="small" value={f.value}
                         onChange={(e) => setF({ ...f, value: e.target.value })} />
            </Grid>
          )}
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField label="Portlar (boşsa varsayılan)" fullWidth size="small" placeholder="443,8443"
                       value={f.ports} onChange={(e) => setF({ ...f, ports: e.target.value })} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select label="SY Ekip (opsiyonel)" fullWidth size="small" value={f.sy_team_id}
                       onChange={(e) => setF({ ...f, sy_team_id: e.target.value === '' ? '' : Number(e.target.value) })}>
              <MenuItem value="">— (yok)</MenuItem>
              {syTeams.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <FormControlLabel control={<Switch checked={f.enabled}
                              onChange={(e) => setF({ ...f, enabled: e.target.checked })} />} label="Etkin" />
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>İptal</Button>
        <Button variant="contained" disabled={!valid || mut.isPending} onClick={() => mut.mutate()}>
          {target ? 'Kaydet' : 'Ekle'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------- Erişim (sayfa görünürlüğü: Uyum/Devir Önerileri/Keşif/Dağıtım) ----------
function AccessTab() {
  const { form, setForm, save } = useCategory('access')

  const SWITCHES: { key: string; label: string }[] = [
    { key: 'policy_all_roles', label: 'Uyum sayfası herkese açık' },
    { key: 'proposals_all_roles', label: 'Devir Önerileri sayfası herkese açık' },
    { key: 'discovery_all_roles', label: 'Keşif sayfası herkese açık' },
    { key: 'deployments_all_roles', label: 'Dağıtım sayfası herkese açık' },
    { key: 'issuance_all_roles', label: 'Sertifika Talepleri sayfası herkese açık' },
  ]

  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Varsayılan: Uyum, Devir Önerileri, Keşif, Dağıtım ve Sertifika Talepleri sayfaları yalnız
        <b> Yönetici</b> ve <b>Global İzleyici</b> rolüne görünür. Aşağıdaki anahtarları açarsanız
        ilgili sayfa <b>tüm rollere</b> (İzleyici dahil) görünür olur. <b>Devir Önerileri/Sertifika
        Talepleri istisnası:</b> bu ayardan bağımsız olarak, bir SY ekibinin üyesi kendi ekibinin
        bekleyen tekliflerini/isteklerini her zaman görüp onaylayabilir — onay yetkisi bu anahtarla
        DEĞİŞMEZ. Dağıtımı fiilen <b>tetikleme</b> her durumda yalnız Yönetici'dedir; bu anahtar
        yalnız görüntülemeyi açar.
      </Alert>
      <Box>
        <SectionLabel>SAYFA GÖRÜNÜRLÜĞÜ</SectionLabel>
        {SWITCHES.map((s) => (
          <FormControlLabel key={s.key}
            control={<Switch checked={!!form[s.key]}
                             onChange={(e) => setForm((f) => ({ ...f, [s.key]: e.target.checked }))} />}
            label={s.label} sx={{ display: 'block' }} />
        ))}
        <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
          Kaydet
        </Button>
      </Box>
    </Stack>
  )
}

function DiscoveryTab() {
  const { form, setForm, save } = useCategory('discovery')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<ScanTarget | 'new' | null>(null)

  const { data: targets } = useQuery<ScanTarget[]>({
    queryKey: ['discovery', 'targets'],
    queryFn: async () => (await api.get('/discovery/targets')).data,
  })
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
  })
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')

  const del = useMutation({
    mutationFn: async (id: number) => api.delete(`/discovery/targets/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Hedef silindi', { variant: 'info' })
      queryClient.invalidateQueries({ queryKey: ['discovery', 'targets'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const detectLocal = useMutation({
    mutationFn: async () => (await api.post('/discovery/targets/detect-local')).data,
    onSuccess: (d: { suggested_cidr?: string | null; note?: string }) =>
      enqueueSnackbar(d.suggested_cidr ? `Önerilen CIDR: ${d.suggested_cidr} — ${d.note}` : (d.note ?? ''),
                      { variant: 'info', autoHideDuration: 7000 }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Stack spacing={3}>
      <Alert severity="warning">
        Aktif ağ taraması port taraması gibi görünür — hedef VLAN'lar için <b>ağ/güvenlik ekibi onayı</b> ve
        container→VLAN <b>firewall/routing izni</b> gerekir. Tarama yalnız aşağıda tanımlı hedeflere ve
        portlara TLS bağlantısı kurar; sertifika üretmez, yalnız envanterler.
      </Alert>

      <Box>
        <SectionLabel>TARAMA AYARLARI</SectionLabel>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Gece taraması etkin (her gün)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm etkin hedefler her gece aşağıdaki saatte otomatik taranır. Kapalıyken tarama yalnız
          Keşif sayfasındaki “Taramayı Başlat” ile elle çalışır.
        </Typography>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="default_ports" label="Varsayılan Portlar"
                helper="Hedefte port yazılmazsa bu portlara TLS bağlantısı denenir (virgülle ayırın)" />
          <Text form={form} setForm={setForm} field="schedule_hour" label="Gece Saati (0-23)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Gece taramasının başlayacağı saat (sunucu saati)" />
          <Text form={form} setForm={setForm} field="concurrency" label="Concurrency" type="number"
                width={{ xs: 6, sm: 3 }} helper="Aynı anda kurulacak TLS bağlantısı sayısı — yüksek değer hızlı ama ağda daha gürültülü" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Bir host bu süre içinde yanıt vermezse erişilemez sayılır" />
          <Text form={form} setForm={setForm} field="max_hosts" label="Azami Hedef (host×port)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Tek taramada denenecek en fazla host×port — güvenlik freni; büyük CIDR'lerde bu sınırda kesilir" />
        </Grid>
        <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
          Kaydet
        </Button>
      </Box>

      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <SectionLabel>TARAMA HEDEFLERİ</SectionLabel>
          <Box sx={{ flexGrow: 1 }} />
          <Button size="small" startIcon={<TravelExploreIcon />} onClick={() => detectLocal.mutate()}
                  disabled={detectLocal.isPending}>Yerel /24 Öner</Button>
          <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={() => setDialog('new')}>
            Hedef Ekle
          </Button>
        </Box>
        <Paper variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Ad</TableCell>
                <TableCell>Tür</TableCell>
                <TableCell>Değer</TableCell>
                <TableCell>Portlar</TableCell>
                <TableCell>SY Ekip</TableCell>
                <TableCell>Durum</TableCell>
                <TableCell align="right">İşlem</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(targets ?? []).length === 0 && (
                <TableRow><TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                  Tanımlı tarama hedefi yok — "Hedef Ekle" ile başlayın.
                </TableCell></TableRow>
              )}
              {(targets ?? []).map((t) => (
                <TableRow key={t.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>{t.name}</TableCell>
                  <TableCell><Chip size="small" variant="outlined" label={KIND_LABEL[t.kind]} /></TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 13 }}>{t.value || '—'}</TableCell>
                  <TableCell>{t.ports || '(varsayılan)'}</TableCell>
                  <TableCell>{t.sy_team_name || '—'}</TableCell>
                  <TableCell>
                    <Chip size="small" color={t.enabled ? 'success' : 'default'}
                          label={t.enabled ? 'Etkin' : 'Kapalı'} />
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap', width: '1%' }}>
                    <Box sx={{ display: 'inline-flex', flexWrap: 'nowrap', gap: 0.25 }}>
                      <Tooltip title="Düzenle">
                        <IconButton size="small" onClick={() => setDialog(t)}><EditIcon fontSize="small" /></IconButton>
                      </Tooltip>
                      <Tooltip title="Sil">
                        <IconButton size="small" color="error" onClick={() => del.mutate(t.id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      </Box>

      <ScanTargetDialog open={dialog !== null} target={dialog === 'new' ? null : dialog}
                        syTeams={syTeams} onClose={() => setDialog(null)} />
    </Stack>
  )
}

// ---------- CT / Certificate Transparency (crt.sh) ----------
function CtTab() {
  const { form, setForm, save } = useCategory('ct')
  return (
    <Stack spacing={3}>
      <Alert severity="warning">
        Certificate Transparency izleme <b>crt.sh'e dış internet erişimi</b> gerektirir. Kapalı ağda
        doğrudan erişilemez → aşağıya bir <b>forward proxy</b> tanımlayın; erişim yoksa tarama sessizce
        hatayı kaydedip geçer (çökme olmaz). Bu özellik ağa TLS bağlantısı KURMAZ, yalnız CT loglarını okur.
      </Alert>

      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Gece CT taraması etkin (her gün)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm envanter domainleri her gece crt.sh'ten sorgulanır. Kapalıyken tarama yalnız Keşif
          sayfasındaki “CT Taraması” düğmesiyle elle çalışır.
        </Typography>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="crt.sh'e ulaşmak için http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="schedule_hour" label="Gece Saati (0-23)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Gece CT taramasının başlayacağı saat (sunucu saati)" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 3 }} helper="crt.sh isteği için azami bekleme süresi" />
          <Text form={form} setForm={setForm} field="concurrency" label="Concurrency" type="number"
                width={{ xs: 6, sm: 3 }} helper="Domain başına eşzamanlı sertifika indirmesi — crt.sh'e nazik olmak için düşük tutun" />
          <Text form={form} setForm={setForm} field="max_entries_per_domain" label="Domain Başına Azami Giriş" type="number"
                width={{ xs: 6, sm: 3 }} helper="Bir domain için işlenecek en fazla CT kaydı" />
          <Text form={form} setForm={setForm} field="max_domains" label="Azami Domain (0 = hepsi)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Taranacak envanter domaini sayısı sınırı" />
        </Grid>
        <FormControlLabel sx={{ mt: 1 }}
          control={<Switch checked={!!form.match_wildcards}
                           onChange={(e) => setForm((s) => ({ ...s, match_wildcards: e.target.checked }))} />}
          label="Wildcard domainlerde taban alanı sorgula (*.x.com → x.com)" />
        <Box>
          <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
            Kaydet
          </Button>
        </Box>
      </Box>
    </Stack>
  )
}

// ---------- Politika / Uyum ----------
function PolicyTab() {
  const { form, setForm, save } = useCategory('policy')
  const strArr = (v: unknown): string[] => (Array.isArray(v) ? (v as string[]) : [])
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Uyum değerlendirmesi <b>tamamen yereldir</b> (dış erişim yok) — envanterdeki sertifikalar bu
        kurallara göre denetlenir. İhlaller <b>Uyum</b> sayfasında görünür. Kontrol edilmemiş (kripto
        bilgisi olmayan) kayıtlar ihlal sayılmaz.
      </Alert>

      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Uyum değerlendirmesi etkin" />
        <FormControlLabel sx={{ display: 'block' }}
          control={<Switch checked={!!form.enforce_ca_allowlist}
                           onChange={(e) => setForm((s) => ({ ...s, enforce_ca_allowlist: e.target.checked }))} />}
          label="CA allowlist zorunlu (liste dışı issuer = ihlal)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          Açıkken, aşağıdaki listede olmayan bir CA'dan çıkmış leaf sertifikalar “Güvenilmeyen Issuer”
          olarak işaretlenir. Liste boşken zorlama uygulanmaz (yanlış-pozitif önlemi).
        </Typography>

        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="min_rsa_bits" label="Asgari RSA (bit)" type="number"
                width={{ xs: 6, sm: 4 }} helper="Bundan küçük RSA anahtarı zayıf sayılır (ör. 2048)" />
          <Text form={form} setForm={setForm} field="min_ec_bits" label="Asgari EC (bit)" type="number"
                width={{ xs: 6, sm: 4 }} helper="Bundan küçük EC eğrisi zayıf sayılır (ör. 256)" />
          <Text form={form} setForm={setForm} field="max_validity_days" label="Azami Ömür (gün)" type="number"
                width={{ xs: 6, sm: 4 }} helper="Leaf ömrü bunu aşarsa ihlal; 0 = kapalı (ör. 398)" />
        </Grid>

        <Box sx={{ mt: 2 }}>
          <Autocomplete multiple freeSolo options={[]} value={strArr(form.ca_allowlist)}
            onChange={(_, val) => setForm((s) => ({ ...s, ca_allowlist: val }))}
            renderInput={(params) => (
              <TextField {...params} label="CA Allowlist" size="small"
                helperText="İzinli issuer parçaları (issuer/CN alt-dizesi) — yazıp Enter'a basın" />
            )} />
        </Box>
        <Box sx={{ mt: 2 }}>
          <Autocomplete multiple freeSolo options={['sha1', 'md5', 'sha224']}
            value={strArr(form.banned_sig_hashes)}
            onChange={(_, val) => setForm((s) => ({ ...s, banned_sig_hashes: val.map((x) => x.toLowerCase()) }))}
            renderInput={(params) => (
              <TextField {...params} label="Yasak İmza Özet Algoritmaları" size="small"
                helperText="Bu özetle imzalanmış sertifikalar zayıf sayılır (ör. sha1, md5)" />
            )} />
        </Box>

        <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
          Kaydet
        </Button>
      </Box>
    </Stack>
  )
}

// ---------- İptal Durumu (Revocation — OCSP/CRL) ----------
function RevocationTab() {
  const { form, setForm, save } = useCategory('revocation')
  return (
    <Stack spacing={3}>
      <Alert severity="warning">
        İptal denetimi <b>OCSP/CRL uçlarına dış erişim</b> gerektirir. Kapalı ağda erişilemeyebilir →
        opsiyonel <b>forward proxy</b> tanımlayın. İç/özel CA'lar çoğu zaman public OCSP sunmaz; bu
        durumda sonuç <b>“Belirsiz”</b> olur — bu normaldir. JUMBO sertifikayı iptal görse bile
        <b> otomatik pasife almaz</b>, yalnız durumu gösterir.
      </Alert>

      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Gece iptal denetimi etkin (her gün)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm aktif leaf sertifikalar her gece denetlenir. Kapalıyken denetim yalnız sertifika
          detayındaki “Şimdi Kontrol Et” ile elle çalışır.
        </Typography>
        <FormControlLabel sx={{ display: 'block', mb: 1 }}
          control={<Switch checked={!!form.check_active_only}
                           onChange={(e) => setForm((s) => ({ ...s, check_active_only: e.target.checked }))} />}
          label="Yalnız aktif sertifikaları denetle" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth size="small" label="Yöntem" value={String(form.method ?? 'ocsp_then_crl')}
                       helperText="Önce OCSP, olmazsa CRL — ya da yalnız biri"
                       onChange={(e) => setForm((s) => ({ ...s, method: e.target.value }))}>
              <MenuItem value="ocsp_then_crl">OCSP → CRL (önerilen)</MenuItem>
              <MenuItem value="ocsp">Yalnız OCSP</MenuItem>
              <MenuItem value="crl">Yalnız CRL</MenuItem>
            </TextField>
          </Grid>
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                width={{ xs: 12, sm: 6 }} helper="OCSP/CRL uçlarına ulaşmak için http://host:port" />
          <Text form={form} setForm={setForm} field="schedule_hour" label="Gece Saati (0-23)" type="number"
                width={{ xs: 6, sm: 6 }} helper="Gece denetiminin başlayacağı saat (sunucu saati)" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} helper="Her OCSP/CRL isteği için azami bekleme" />
        </Grid>
        <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
          Kaydet
        </Button>
      </Box>
    </Stack>
  )
}

// ---------- Bildirim kanalları (Slack / Teams / Webhook) ----------
// Süre uyarıları e-postaya EK olarak bu kanallara da yayınlanır (notify dispatcher).
function ChannelTestButton({ category }: { category: string }) {
  const { enqueueSnackbar } = useSnackbar()
  const test = useMutation({
    mutationFn: async () => (await api.post(`/settings/${category}/notify-test`)).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'warning' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  return (
    <Button variant="outlined" onClick={() => test.mutate()} disabled={test.isPending}>
      Test Mesajı Gönder
    </Button>
  )
}

function SlackTab() {
  const { form, setForm, save } = useCategory('slack')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarıları e-postaya <b>ek olarak</b> Slack kanalına yayınlanır. Slack <b>dış SaaS</b>'tır;
        kapalı ağda erişmek için opsiyonel <b>forward proxy</b> tanımlayın (erişilemezse bildirim atlanır,
        çökme olmaz). Webhook URL gizli tutulur (kaydedince maskelenir).
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Slack bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="webhook_url" label="Incoming Webhook URL"
                width={{ xs: 12, sm: 12 }} helper="Slack 'Incoming Webhooks' uygulamasından alınan URL" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="slack" />
        </Stack>
      </Box>
    </Stack>
  )
}

function MsTeamsTab() {
  const { form, setForm, save } = useCategory('teams')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarıları e-postaya <b>ek olarak</b> Microsoft Teams kanalına yayınlanır (Incoming Webhook /
        MessageCard). Teams <b>dış SaaS</b>'tır; kapalı ağda opsiyonel <b>forward proxy</b> gerekebilir.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Teams bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="webhook_url" label="Incoming Webhook URL"
                width={{ xs: 12, sm: 12 }} helper="Teams kanalında 'Incoming Webhook' konnektöründen alınan URL" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="teams" />
        </Stack>
      </Box>
    </Stack>
  )
}

function WebhookTab() {
  const { form, setForm, save } = useCategory('webhook')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarıları için hedef bir URL'e olay JSON'ı POST edilir (ServiceNow-dışı entegrasyonlar —
        PagerDuty, Opsgenie, kendi API'niz…). İsteğe bağlı <b>kimlik başlığı</b> eklenebilir. Hedef iç
        sistemse proxy gerekmez.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Webhook bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="url" label="Hedef URL"
                width={{ xs: 12, sm: 12 }} helper="Olay JSON'ının POST edileceği adres" />
          <Text form={form} setForm={setForm} field="auth_header" label="Kimlik Başlığı (opsiyonel)"
                width={{ xs: 12, sm: 12 }} helper="'Başlık: değer' — ör. 'Authorization: Bearer xxx' (gizli tutulur)" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="webhook" />
        </Stack>
      </Box>
    </Stack>
  )
}

function ServiceNowTab() {
  const { form, setForm, save } = useCategory('servicenow')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarısı için ServiceNow'da bir <b>incident</b> (olay kaydı) açılır (Table API, Basic Auth).
        Süresi geçmiş sertifika <b>Yüksek</b>, yaklaşan <b>Orta</b> aciliyetle kaydedilir. ServiceNow bulut
        örneği <b>dış SaaS</b>'tır; kapalı ağda opsiyonel <b>forward proxy</b> gerekebilir. <b>Test</b>,
        incident <b>açmadan</b> yalnız bağlantı ve kimliği doğrular. Şifre gizli tutulur.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="ServiceNow bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="instance_url" label="Instance URL"
                width={{ xs: 12, sm: 12 }} helper="ör. https://firma.service-now.com" />
          <Text form={form} setForm={setForm} field="username" label="Kullanıcı"
                helper="Incident oluşturma yetkili entegrasyon kullanıcısı" />
          <Text form={form} setForm={setForm} field="password" label="Şifre" type="password" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="servicenow" />
        </Stack>
      </Box>
    </Stack>
  )
}

function JiraTab() {
  const { form, setForm, save } = useCategory('jira')
  const bearer = String(form.auth_mode ?? 'basic') === 'bearer'
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarısı için Jira'da bir <b>issue</b> (talep/görev) açılır (REST API v2). Telekomda genelde
        on-prem <b>Data Center</b> kullanılır → <b>Bearer (PAT)</b> kimlik önerilir; Jira Cloud için{' '}
        <b>Basic</b> (hesap e-postası + API token). <b>Test</b>, issue <b>açmadan</b> yalnız kimliği doğrular
        (<code>/myself</code>). Cloud dış SaaS'tır; kapalı ağda <b>forward proxy</b> gerekebilir. Token gizli.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Jira bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="base_url" label="Base URL"
                width={{ xs: 12, sm: 8 }}
                helper="Cloud: https://firma.atlassian.net — DC: https://jira.firma.local" />
          <Grid size={{ xs: 12, sm: 4 }}>
            <TextField select fullWidth size="small" label="Kimlik Modu"
                       value={String(form.auth_mode ?? 'basic')}
                       helperText={bearer ? 'PAT → Authorization: Bearer' : 'kullanıcı + token/şifre'}
                       onChange={(e) => setForm((s) => ({ ...s, auth_mode: e.target.value }))}>
              <MenuItem value="basic">Basic (kullanıcı + token)</MenuItem>
              <MenuItem value="bearer">Bearer (Data Center PAT)</MenuItem>
            </TextField>
          </Grid>
          {!bearer && (
            <Text form={form} setForm={setForm} field="username" label="Kullanıcı"
                  helper="Cloud: hesap e-postası · DC: kullanıcı adı" />
          )}
          <Text form={form} setForm={setForm} field="api_token"
                label={bearer ? 'Personal Access Token (PAT)' : 'API Token / Şifre'} type="password"
                width={bearer ? { xs: 12, sm: 12 } : { xs: 12, sm: 6 }} />
          <Text form={form} setForm={setForm} field="project_key" label="Proje Anahtarı"
                width={{ xs: 6, sm: 6 }} helper="ör. OPS — issue bu projede açılır" />
          <Text form={form} setForm={setForm} field="issue_type" label="Issue Tipi"
                width={{ xs: 6, sm: 6 }} helper="ör. Task · Incident · Service Request" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="jira" />
        </Stack>
      </Box>
    </Stack>
  )
}

function ZoomTab() {
  const { form, setForm, save } = useCategory('zoom')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarıları e-postaya <b>ek olarak</b> Zoom Team Chat kanalına yayınlanır ('Incoming Webhook'
        uygulaması: Endpoint URL + doğrulama token'ı). Zoom <b>dış SaaS</b>'tır; kapalı ağda opsiyonel
        <b> forward proxy</b> gerekebilir. Token gizli tutulur.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Zoom bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="webhook_url" label="Endpoint URL"
                width={{ xs: 12, sm: 12 }} helper="Zoom 'Incoming Webhook' uygulamasından alınan uç nokta" />
          <Text form={form} setForm={setForm} field="token" label="Doğrulama Token'ı" type="password"
                width={{ xs: 12, sm: 12 }} helper="Authorization başlığı olarak gönderilir (gizli)" />
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="zoom" />
        </Stack>
      </Box>
    </Stack>
  )
}

function JabberTab() {
  const { form, setForm, save } = useCategory('jabber')
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Süre uyarıları e-postaya <b>ek olarak</b> bir Jabber/XMPP hedefine yollanır (ejabberd / Openfire /
        Cisco Jabber). Her bildirimde kısa bir oturum açılır, mesaj gönderilir, kapatılır. Hedef bir kişi
        (<b>tekil JID</b>) ya da bir <b>MUC grup odası</b> olabilir. Genelde <b>iç ağdadır</b> → proxy
        gerekmez. Şifre gizli tutulur. <b>Test</b> gerçek bir mesaj gönderir.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Jabber bildirimleri etkin" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="host" label="Sunucu Host (opsiyonel)"
                helper="Boşsa JID alanından DNS SRV ile çözülür" width={{ xs: 12, sm: 8 }} />
          <Text form={form} setForm={setForm} field="port" label="Port" type="number"
                width={{ xs: 12, sm: 4 }} helper="XMPP istemci portu (varsayılan 5222)" />
          <Text form={form} setForm={setForm} field="jid" label="Gönderen JID"
                helper="ör. jumbo@firma.local" />
          <Text form={form} setForm={setForm} field="password" label="Şifre" type="password" />
          <Text form={form} setForm={setForm} field="target" label="Hedef (JID veya MUC oda JID'i)"
                width={{ xs: 12, sm: 12 }} helper="Kişi: ali@firma.local — Oda: noc@conference.firma.local" />
          <Grid size={{ xs: 12, sm: 6 }}>
            <FormControlLabel
              control={<Switch checked={!!form.is_muc}
                               onChange={(e) => setForm((s) => ({ ...s, is_muc: e.target.checked }))} />}
              label="Hedef bir MUC (grup) odası" />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <FormControlLabel
              control={<Switch checked={!!form.skip_cert_verify}
                               onChange={(e) => setForm((s) => ({ ...s, skip_cert_verify: e.target.checked }))} />}
              label="Sertifika doğrulamasını atla (dev)" />
          </Grid>
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 6 }} />
        </Grid>
        <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
          <ChannelTestButton category="jabber" />
        </Stack>
      </Box>
    </Stack>
  )
}

// Jenkins entegrasyonu: ayarlar + bağlantı testi + GENEL "Job Tetikle" (herhangi bir job + parametre).
// NetScaler cert değişimi bunun bir kullanımıdır (netscaler-deploy job'u, CERTKEY domain başına).
function JenkinsTab() {
  const { form, setForm, save } = useCategory('jenkins')
  const { enqueueSnackbar } = useSnackbar()
  const test = useMutation({
    mutationFn: async () => (await api.post('/settings/jenkins/test')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'warning' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        JUMBO Jenkins <b>job'larını tetikler</b> (genel — herhangi bir job + parametre). NetScaler cert
        değişimi bunun bir kullanımıdır: <code>netscaler-deploy</code> job'u <code>CERTKEY</code> (domain
        başına) + <code>VAULT_PATH</code> ile çağrılır. Özel anahtar <b>Vault→Jenkins→NITRO</b> yolunu izler,
        JUMBO'ya girmez.
      </Alert>
      <FormControlLabel
        control={<Switch checked={!!form.enabled}
                         onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />}
        label="Jenkins Entegrasyonu" />
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="base_url" label="Jenkins Adresi (http://jumbo-jenkins:8080)" />
        <Text form={form} setForm={setForm} field="username" label="Kullanıcı" />
        <Text form={form} setForm={setForm} field="api_token" label="API Token / Parola" type="password" />
        <Text form={form} setForm={setForm} field="netscaler_job" label="NetScaler Deploy Job'u" />
        <Text form={form} setForm={setForm} field="jobs_folder"
              label="Job Klasörü (opsiyonel, ör. Certificate-deployment)"
              helper="Boşsa Jenkins kökü taranır. Alt klasörler otomatik (özyinelemeli) dahil edilir." />
      </Grid>
      <FormControlLabel
        control={<Switch checked={!!form.skip_cert_verify}
                         onChange={(e) => setForm((f) => ({ ...f, skip_cert_verify: e.target.checked }))} />}
        label="TLS sertifikasını doğrulama (yalnız dev)" />
      <Stack direction="row" spacing={2}>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => test.mutate()}>Bağlantıyı Test Et</Button>
      </Stack>

      <Divider />
      <Alert severity="info">
        Job <b>tetikleme</b> artık üst menüdeki <b>Dağıtım</b> sayfasındadır (canlı build geçmişiyle).
        Burası yalnız Jenkins bağlantı ayarlarıdır.
      </Alert>
    </Stack>
  )
}

function CaProfilesTab() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { form, setForm, save } = useCategory('issuance')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<IssuanceProfile | null>(null)
  const EMPTY_PROFILE = {
    name: '', ca_type: 'vault_pki', enabled: true, vault_mount: '', vault_role: '',
    acme_directory_url: '', eab_kid: '', eab_hmac_key: '', acme_account_key: '', proxy_url: '',
  }
  const [pForm, setPForm] = useState(EMPTY_PROFILE)

  const { data: profiles } = useQuery<IssuanceProfile[]>({
    queryKey: ['issuance-profiles'],
    queryFn: async () => (await api.get('/issuance/profiles')).data,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['issuance-profiles'] })

  const openCreate = () => { setEditTarget(null); setPForm(EMPTY_PROFILE); setDialogOpen(true) }
  const openEdit = (p: IssuanceProfile) => {
    setEditTarget(p)
    setPForm({
      name: p.name, ca_type: p.ca_type, enabled: p.enabled,
      vault_mount: p.vault_mount ?? '', vault_role: p.vault_role ?? '',
      acme_directory_url: p.acme_directory_url ?? '', eab_kid: p.eab_kid ?? '',
      eab_hmac_key: '', acme_account_key: '', proxy_url: p.proxy_url ?? '',
    })
    setDialogOpen(true)
  }

  const saveProfile = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        name: pForm.name.trim(), ca_type: pForm.ca_type, enabled: pForm.enabled,
        vault_mount: pForm.vault_mount.trim() || null, vault_role: pForm.vault_role.trim() || null,
        acme_directory_url: pForm.acme_directory_url.trim() || null,
        eab_kid: pForm.eab_kid.trim() || null, proxy_url: pForm.proxy_url.trim() || null,
      }
      // Hassas alanlar yalnız DOLDURULMUŞSA gönderilir — boş bırakmak mevcut değeri KORUR
      // (settings_service secret-masking felsefesiyle tutarlı; bkz. api/issuance.py).
      if (pForm.eab_hmac_key.trim()) body.eab_hmac_key = pForm.eab_hmac_key.trim()
      if (pForm.acme_account_key.trim()) body.acme_account_key = pForm.acme_account_key.trim()
      if (editTarget) return api.put(`/issuance/profiles/${editTarget.id}`, body)
      return api.post('/issuance/profiles', body)
    },
    onSuccess: () => {
      enqueueSnackbar(editTarget ? 'CA profili güncellendi' : 'CA profili eklendi', { variant: 'success' })
      invalidate(); setDialogOpen(false)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/issuance/profiles/${id}`),
    onSuccess: () => { enqueueSnackbar('CA profili silindi', { variant: 'info' }); invalidate() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>Genel Ayarlar</Typography>
        <Alert severity="warning" sx={{ mb: 2 }}>
          Genel anahtar kapalıyken hiçbir CA profiline (etkin olsa bile) gerçek çağrı yapılmaz.
          Özel anahtar velayeti her zaman JUMBO dışında kalır — CSR hedef sunucu/otomasyon
          tarafında üretilir, JUMBO'ya yalnız genel anahtar içeren metin olarak gelir.
        </Alert>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <FormControlLabel control={<Switch checked={!!form.enabled}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />}
              label="Otomatik Alım Etkin (genel anahtar)" />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth size="small" label="Varsayılan CA Profili"
                       value={form.default_profile_id != null ? String(form.default_profile_id) : ''}
                       onChange={(e) => setForm((f) => ({
                         ...f, default_profile_id: e.target.value ? Number(e.target.value) : null,
                       }))}>
              <MenuItem value="">— yok —</MenuItem>
              {(profiles ?? []).map((p) => (
                <MenuItem key={p.id} value={String(p.id)}>{p.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Text form={form} setForm={setForm} field="default_renew_before_days"
                label="Varsayılan Yenileme Eşiği (gün)" type="number" width={{ xs: 12, sm: 6 }}
                helper="Domain kendi eşiğini belirtmezse kullanılır" />
        </Grid>
        <Box sx={{ mt: 2 }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        </Box>
      </Box>

      <Divider />

      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2">CA Profilleri</Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>Profil Ekle</Button>
        </Box>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Ad</TableCell>
              <TableCell>Tip</TableCell>
              <TableCell>Etkin</TableCell>
              <TableCell>Bağlantı</TableCell>
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {(profiles ?? []).map((p) => (
              <TableRow key={p.id} hover>
                <TableCell sx={{ fontWeight: 600 }}>{p.name}</TableCell>
                <TableCell>
                  <Chip size="small" label={p.ca_type === 'vault_pki' ? 'Vault PKI' : 'ACME'} />
                </TableCell>
                <TableCell>
                  {p.enabled
                    ? <Chip size="small" color="success" variant="outlined" label="etkin" />
                    : <Chip size="small" variant="outlined" label="kapalı" />}
                </TableCell>
                <TableCell>
                  {p.ca_type === 'vault_pki'
                    ? `${p.vault_mount ?? '—'} / ${p.vault_role ?? '—'}`
                    : (p.acme_directory_url ?? '—')}
                </TableCell>
                <TableCell align="right">
                  <Tooltip title="Düzenle">
                    <IconButton size="small" onClick={() => openEdit(p)}><EditIcon fontSize="small" /></IconButton>
                  </Tooltip>
                  <Tooltip title="Sil">
                    <IconButton size="small" color="error" disabled={remove.isPending}
                                onClick={() => remove.mutate(p.id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {profiles && profiles.length === 0 && (
              <TableRow><TableCell colSpan={5} align="center" sx={{ py: 4 }}>Henüz CA profili yok</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Box>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editTarget ? `Profil Düzenle — ${editTarget.name}` : 'CA Profili Ekle'}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Profil Adı" size="small" value={pForm.name} autoFocus
                       onChange={(e) => setPForm((f) => ({ ...f, name: e.target.value }))} />
            <TextField select label="CA Tipi" size="small" value={pForm.ca_type}
                       onChange={(e) => setPForm((f) => ({ ...f, ca_type: e.target.value }))}>
              <MenuItem value="vault_pki">Vault PKI (özel CA)</MenuItem>
              <MenuItem value="acme">Public ACME (ileride)</MenuItem>
            </TextField>
            <FormControlLabel control={<Switch checked={pForm.enabled}
              onChange={(e) => setPForm((f) => ({ ...f, enabled: e.target.checked }))} />}
              label="Etkin" />
            {pForm.ca_type === 'vault_pki' ? (
              <>
                <TextField label="Vault PKI Mount" size="small" value={pForm.vault_mount}
                           placeholder="pki_int"
                           onChange={(e) => setPForm((f) => ({ ...f, vault_mount: e.target.value }))} />
                <TextField label="Vault Role" size="small" value={pForm.vault_role}
                           placeholder="jumbo-demo"
                           onChange={(e) => setPForm((f) => ({ ...f, vault_role: e.target.value }))}
                           helperText="Vault adres/token Ayarlar > Vault sekmesinden paylaşılır" />
              </>
            ) : (
              <>
                <TextField label="ACME Directory URL" size="small" value={pForm.acme_directory_url}
                           onChange={(e) => setPForm((f) => ({ ...f, acme_directory_url: e.target.value }))} />
                <TextField label="EAB Key ID" size="small" value={pForm.eab_kid}
                           onChange={(e) => setPForm((f) => ({ ...f, eab_kid: e.target.value }))} />
                <TextField label="EAB HMAC Key" size="small" type="password" value={pForm.eab_hmac_key}
                           placeholder={editTarget ? '(değiştirmemek için boş bırakın)' : ''}
                           onChange={(e) => setPForm((f) => ({ ...f, eab_hmac_key: e.target.value }))} />
              </>
            )}
            <TextField label="Proxy URL (opsiyonel)" size="small" value={pForm.proxy_url}
                       onChange={(e) => setPForm((f) => ({ ...f, proxy_url: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => saveProfile.mutate()}
                  disabled={!pForm.name.trim() || saveProfile.isPending}>
            {editTarget ? 'Kaydet' : 'Ekle'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}

// Ayarlar sol menüsü — ilişkili bölümler gruplanır. Bildirim kanalları (SMTP + Slack/Teams/Webhook,
// ileride ServiceNow/Zoom/Jabber) tek "Bildirimler" başlığı altında toplanır.
// wide=true → tablo ağırlıklı sekme (tam genişlik); aksi halde form okunur bir sütunda (~880px).
type NavItem = { key: string; label: string; desc: string; el: React.ReactNode; wide?: boolean }
type NavGroup = { title: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  { title: 'Kimlik & Erişim', items: [
    { key: 'users', label: 'Kullanıcılar', desc: 'Hesaplar, roller ve takım kapsamları', wide: true, el: <UsersTab /> },
    { key: 'teams', label: 'Ekipler', desc: 'SY/UG ekiplerini oluştur ve yönet', wide: true, el: <TeamsTab /> },
    { key: 'memberships', label: 'Ekip Üyelikleri', desc: 'Üyelik = kullanıcının veri kapsamı', wide: true, el: <MembershipsTab /> },
    { key: 'access', label: 'Erişim', desc: 'Uyum/Devir Önerileri/Keşif/Dağıtım sayfa görünürlüğü', el: <AccessTab /> },
    { key: 'ldap', label: 'LDAP / Active Directory', desc: 'Kurumsal dizinle kimlik doğrulama', el: <LdapTab /> },
  ] },
  { title: 'Bildirimler', items: [
    { key: 'smtp', label: 'E-posta (SMTP)', desc: 'Süresi yaklaşan sertifikalar için bilgilendirme e-postaları', el: <SmtpTab /> },
    { key: 'mail-history', label: 'Mail Gönderim Geçmişi', desc: 'Gönderilen bilgilendirme e-postalarının kaydı (teslim edilemeyenler dâhil)', wide: true, el: <MailHistoryTab /> },
    { key: 'slack', label: 'Slack', desc: 'Süre uyarılarını bir Slack kanalına yayınlar', el: <SlackTab /> },
    { key: 'teams-notify', label: 'Microsoft Teams', desc: 'Süre uyarılarını bir Teams kanalına yayınlar', el: <MsTeamsTab /> },
    { key: 'webhook', label: 'Webhook', desc: 'Olay verisini genel bir uç noktaya (URL) POST eder', el: <WebhookTab /> },
    { key: 'servicenow', label: 'ServiceNow', desc: 'Süre uyarısında otomatik incident (olay kaydı) açar', el: <ServiceNowTab /> },
    { key: 'jira', label: 'Jira', desc: 'Süre uyarısında otomatik issue (talep) açar', el: <JiraTab /> },
    { key: 'zoom', label: 'Zoom', desc: 'Süre uyarılarını Zoom Team Chat kanalına yayınlar', el: <ZoomTab /> },
    { key: 'jabber', label: 'Jabber / XMPP', desc: 'Süre uyarılarını on-prem XMPP hedefine yollar', el: <JabberTab /> },
  ] },
  { title: 'Keşif & Uyum', items: [
    { key: 'discovery', label: 'Keşif', desc: 'Ağ taramasıyla envanter-dışı sertifikaları bulur', wide: true, el: <DiscoveryTab /> },
    { key: 'ct', label: 'CT (crt.sh)', desc: 'Certificate Transparency loglarını izler', el: <CtTab /> },
    { key: 'policy', label: 'Uyum', desc: 'Sertifika uyum politikası kuralları', el: <PolicyTab /> },
    { key: 'revocation', label: 'İptal (OCSP/CRL)', desc: 'İptal durumu denetimi (OCSP/CRL)', el: <RevocationTab /> },
  ] },
  { title: 'Sistem', items: [
    { key: 'tags', label: 'Etiketler', desc: 'Uygulama etiketi kataloğu', wide: true, el: <TagsTab /> },
    { key: 'vault', label: 'Vault (Hazırlık)', desc: 'Vault PKI entegrasyonu (yakında)', el: <VaultTab /> },
    { key: 'ca-profiles', label: 'CA Profilleri', desc: 'Otomatik sertifika alımı — CA tanımları ve genel anahtar', wide: true, el: <CaProfilesTab /> },
    { key: 'jenkins', label: 'Jenkins', desc: 'Jenkins bağlantı ayarları (tetikleme → Dağıtım sayfası)', el: <JenkinsTab /> },
    { key: 'audit', label: 'Audit Log', desc: 'Denetim kaydı — filtrele ve CSV dışa aktar', wide: true, el: <AuditTab /> },
  ] },
]

export default function Settings() {
  useDocumentTitle('Ayarlar')
  const { isAdmin } = useAuth()
  const [active, setActive] = useState('users')
  // Gruplar açılır/kapanır (accordion) — yer kaplamasın. Başlangıçta yalnız aktif öğenin grubu açık.
  const groupTitleOf = (key: string) =>
    NAV_GROUPS.find((g) => g.items.some((it) => it.key === key))?.title ?? ''
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(
    () => ({ [groupTitleOf(active)]: true }),
  )
  const toggleGroup = (title: string) =>
    setOpenGroups((o) => ({ ...o, [title]: !o[title] }))

  // Admin olmayan kullanıcılar Ayarlar'da YALNIZ etiket kataloğunu görür (etiket ekleyebilsinler
  // diye — yeni kategori/düzenleme/silme yine admin). Diğer sekmeler admin işi.
  if (!isAdmin) {
    return (
      <Box>
        <PageHeader title="Etiketler" subtitle="Etiket kataloğu — mevcut kategorilere yeni etiket ekleyebilirsiniz" />
        <Paper sx={{ p: 3 }}><TagsTab /></Paper>
      </Box>
    )
  }

  const activeItem = NAV_GROUPS.flatMap((g) => g.items).find((it) => it.key === active)

  return (
    <Box>
      <PageHeader title="Ayarlar" subtitle="Entegrasyonlar, kullanıcı yönetimi ve denetim kaydı" />
      {/* Sol: gruplu açılır-kapanır menü · Sağ: seçili bölümün başlığı + formu (formlar okunur genişlikte). */}
      <Paper sx={{ display: 'flex', alignItems: 'stretch', minHeight: 600, overflow: 'hidden' }}>
        <Box component="nav" sx={{
          flexShrink: 0, borderRight: 1, borderColor: 'divider',
          width: { xs: 200, sm: 264 }, py: 1.5, overflowY: 'auto', bgcolor: 'action.hover',
        }}>
          {NAV_GROUPS.map((g) => {
            const open = !!openGroups[g.title]
            const hasActive = g.items.some((it) => it.key === active)
            return (
              <Box key={g.title} sx={{ mb: 0.25 }}>
                <ButtonBase focusRipple onClick={() => toggleGroup(g.title)} sx={{
                  display: 'flex', width: '100%', justifyContent: 'space-between', alignItems: 'center',
                  px: 2, py: 1, '&:hover': { bgcolor: 'action.selected' },
                }}>
                  <Typography variant="overline" sx={{
                    // Grup kapalıyken aktif sekme içindeyse başlığı vurgula (nerede olduğun belli olsun).
                    color: (!open && hasActive) ? 'primary.main' : 'text.secondary',
                    fontWeight: 700, fontSize: 10.5, letterSpacing: '0.1em', lineHeight: 1.6,
                  }}>
                    {g.title}
                  </Typography>
                  <ExpandMoreIcon sx={{
                    fontSize: 18, color: (!open && hasActive) ? 'primary.main' : 'text.disabled',
                    transition: 'transform .2s', transform: open ? 'none' : 'rotate(-90deg)',
                  }} />
                </ButtonBase>
                <Collapse in={open} unmountOnExit>
                  <Box sx={{ pb: 0.5 }}>
                    {g.items.map((it) => {
                      const selected = active === it.key
                      return (
                        <ButtonBase key={it.key} focusRipple onClick={() => setActive(it.key)} sx={{
                          display: 'block', width: '100%', textAlign: 'left', pl: 2.5, pr: 1.5, py: 0.85,
                          borderLeft: '3px solid', borderColor: selected ? 'primary.main' : 'transparent',
                          bgcolor: selected ? 'background.paper' : 'transparent',
                          '&:hover': { bgcolor: selected ? 'background.paper' : 'action.selected' },
                          transition: 'background-color .12s, border-color .12s',
                        }}>
                          <Typography noWrap sx={{
                            fontSize: 13.5, fontWeight: selected ? 700 : 500,
                            color: selected ? 'primary.main' : 'text.primary',
                          }}>
                            {it.label}
                          </Typography>
                        </ButtonBase>
                      )
                    })}
                  </Box>
                </Collapse>
              </Box>
            )
          })}
        </Box>
        <Box sx={{ flexGrow: 1, minWidth: 0, overflowX: 'auto' }}>
          <Box sx={{ maxWidth: activeItem?.wide ? 'none' : 880, px: { xs: 2.5, md: 4 }, py: 3.5 }}>
            <Box sx={{ mb: 2.5 }}>
              <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.25 }}>
                {activeItem?.label}
              </Typography>
              {activeItem?.desc && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {activeItem.desc}
                </Typography>
              )}
            </Box>
            <Divider sx={{ mb: 3 }} />
            {activeItem?.el}
          </Box>
        </Box>
      </Paper>
    </Box>
  )
}
