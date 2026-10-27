import AddIcon from '@mui/icons-material/Add'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import {
  Alert, Box, Button, ButtonBase, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, FormControlLabel, Grid, IconButton, Link as MuiLink, MenuItem, Paper, Stack, Switch, Table, TableBody,
  TableCell, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { Autocomplete } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { formatAuditTime } from '../utils/auditFormat'
import type { AppUser, ScanTarget, Tag, Team, TeamMember } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import AuditLogPanel from '../components/AuditLogPanel'
import LdapQueryPanel from '../components/LdapQueryPanel'
import MailHistoryPanel from '../components/MailHistoryPanel'
import TeamsPanel from '../components/TeamsPanel'
import UsersPanel from '../components/UsersPanel'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useUrlId, useUrlState } from '../hooks/useUrlState'
import { TEAM_TYPE_LABEL } from '../utils/peopleLabels'

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

// Otomatik (zamanlanmış) çalışma kapalıyken gösterilir: çoklu pod/cluster kurulumunda işler
// uygulamada kapatılıp dışarıdan tek noktadan tetiklenir; saat alanı o zaman kullanılmaz.
function AutoOffNote({ show, trigger }: { show: boolean; trigger: string }) {
  if (!show) return null
  return (
    <Alert severity="info" sx={{ my: 1 }}>
      Otomatik çalışma <b>kapalı</b>: bu iş yalnız ekrandan elle ya da dışarıdan
      (<code>{trigger}</code> + <code>X-API-Key</code>) tetiklenince çalışır. Saat ayarı kullanılmaz.
      Aynı iş başka bir sunucuda çalışıyorsa ikinci kez başlamaz.
    </Alert>
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
            label="StartTLS (389)" />
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

      <SectionLabel>Ekip Grubu</SectionLabel>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="team_group_ou" label="Ekip grubu OU'su"
              helper="Bu OU altındaki grup kişinin ekibi sayılır; sol menüde adın altında ve Profilim'de görünür — ör. ScrumGroup (CN=SY-BBB,OU=ScrumGroup,…)" />
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
  // Test maili: önce formdaki ayarlar kaydedilir, ardından YALNIZ girilen adrese gönderilir
  // (gerçek paydaşlara uyarı gitmez; kuyruk/yedek adres kullanılmaz, sunucu hatası olduğu gibi döner).
  const [testTo, setTestTo] = useState('')
  const testMail = useMutation({
    mutationFn: async () => {
      await save.mutateAsync()
      return (await api.post('/settings/smtp/test', { to: testTo })).data
    },
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'error' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const security = form.use_ssl ? 'ssl' : form.use_tls ? 'starttls' : 'none'

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
          Kapalıyken zamanlanmış tarama mail göndermez; <b>dış API tetiği</b> (X-API-Key) ya da "Şimdi Gönder"
          ile yine gönderim yapılır.
        </Typography>
        <AutoOffNote show={form.auto_expiry_enabled === false} trigger="POST /api/notifications/expiry-run" />
      </Box>
      <Box>
        <FormControlLabel
          control={<Switch checked={form.auto_expired_enabled !== false}
                           onChange={(e) => setForm((f) => ({ ...f, auto_expired_enabled: e.target.checked }))} />}
          label="Günlük Süresi Geçmiş Hatırlatması (her sabah 08:05)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4, mt: -0.5 }}>
          Süresi dolmuş ama JUMBO'da hâlâ <b>aktif</b> görünen sertifikaların paydaşlarına "yenisini bağlayın
          ya da pasife alın" maili gider (süre uyarısıyla aynı alıcılar ve şablon; tekrar-önleme geçerli).
          Kapalıyken yalnız "Süresi Geçenleri Şimdi Gönder" / dış API ile gönderilir.
        </Typography>
        <AutoOffNote show={form.auto_expired_enabled === false} trigger="POST /api/notifications/expired-run" />
      </Box>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="host" label="SMTP Sunucusu" />
        <Text form={form} setForm={setForm} field="port" label="Port" type="number" width={{ xs: 6, sm: 3 }} />
        <Grid size={{ xs: 6, sm: 3 }}>
          <TextField select fullWidth size="small" label="Bağlantı Güvenliği" value={security}
                     helperText={security === 'ssl' ? 'Genelde port 465' : security === 'starttls' ? 'Genelde port 587 / 25' : 'Şifresiz bağlantı'}
                     onChange={(e) => setForm((f) => ({ ...f, use_tls: e.target.value === 'starttls',
                                                         use_ssl: e.target.value === 'ssl' }))}>
            <MenuItem value="none">Yok</MenuItem>
            <MenuItem value="starttls">STARTTLS</MenuItem>
            <MenuItem value="ssl">SSL / SMTPS</MenuItem>
          </TextField>
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
            "Şimdi Gönder" bu frenden etkilenmez; dış API tetiğinde fren geçerlidir (araç tekrar
            denerse aynı kişiye ikinci mail gitmez).
          </Typography>
        </Grid>
        <Text form={form} setForm={setForm} field="resend_interval_hours" label="Tekrar Aralığı (saat)" type="number"
              disabled={form.resend_dedup_enabled === false}
              helper="Pencereye giren sertifika için mailin kaç SAATTE bir tekrarlanacağı (varsayılan 3). 'Şimdi Gönder' bu freni atlar."
              width={{ xs: 6, sm: 4 }} />
        <Text form={form} setForm={setForm} field="fallback_address" label="Yedek/Varsayılan Adres"
              helper="Birincil gönderim başarısızsa ikinci deneme bu adrese yapılır (virgülle çoklu)."
              width={{ xs: 12, sm: 8 }} />
        <Text form={form} setForm={setForm} field="doc_links" label="Doküman Bağlantıları" multiline rows={3}
              helper="Maillerin en altına eklenir. Her satıra bir link/metin; http(s) linkleri tıklanabilir olur."
              width={{ xs: 12, sm: 12 }} />
        <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
              helper='Dış araç: POST /api/notifications/expiry-run (expired-run, proposal-run) + "X-API-Key: <anahtar>" başlığı. Tarama arka planda çalışır (202); durum: GET …/expiry-run/status. Boşsa dış tetikleme kapalı.'
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
        <b>Değişiklik Talebi Hatırlatması:</b> Onay kuyruğunda <b>bekleyen değişiklik talebi</b> olan SY ekiplerine
        (ekip başına <b>tek mail</b>, tüm bekleyen taleplerini listeler) hatırlatma gönderir — kuyruğun temiz
        tutulması için. Açıkken her gün belirtilen saatte; kapalıyken yalnız "Şimdi Hatırlat" / dış API ile.
      </Alert>
      <Box>
        <FormControlLabel
          control={<Switch checked={form.auto_proposal_reminder_enabled === true}
                           onChange={(e) => setForm((f) => ({ ...f, auto_proposal_reminder_enabled: e.target.checked }))} />}
          label="Günlük Değişiklik Talebi Hatırlatması" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 4, mt: -0.5 }}>
          Kapalıyken zamanlanmış hatırlatma gönderilmez; <b>dış API tetiği</b> (X-API-Key) ya da "Şimdi Hatırlat"
          ile yine gönderim yapılır.
        </Typography>
        <AutoOffNote show={form.auto_proposal_reminder_enabled !== true} trigger="POST /api/notifications/proposal-run" />
      </Box>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="proposal_reminder_hour" label="Hatırlatma Saati (0-23)" type="number"
              disabled={form.auto_proposal_reminder_enabled !== true}
              helper="Günlük hatırlatmanın gönderileceği saat (varsayılan 09:00). Dış API 'Şimdi Hatırlat' saatten bağımsızdır."
              width={{ xs: 6, sm: 4 }} />
      </Grid>

      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <TextField size="small" label="Test Maili Alıcısı" value={testTo} sx={{ minWidth: 260 }}
                   onChange={(e) => setTestTo(e.target.value)}
                   helperText="Boşsa kendi e-posta adresinize gönderilir. Ayarlar önce kaydedilir." />
        <Button variant="outlined" onClick={() => testMail.mutate()} disabled={testMail.isPending}>
          Test Maili Gönder
        </Button>
      </Stack>

      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => runNow.mutate()} disabled={runNow.isPending}>
          Süre Uyarılarını Şimdi Gönder
        </Button>
        <Button variant="outlined" color="warning" onClick={() => runExpired.mutate()} disabled={runExpired.isPending}>
          Süresi Geçenleri Şimdi Gönder
        </Button>
        <Button variant="outlined" onClick={() => runProposals.mutate()} disabled={runProposals.isPending}>
          Bekleyen Talepleri Şimdi Hatırlat
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

function MembershipsTab() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [teamId, setTeamId] = useUrlId('member_team')  // seçili ekip URL'de
  const [toAdd, setToAdd] = useState<AppUser | null>(null)
  const [emailDraft, setEmailDraft] = useState('')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)

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
  // Ekip değişince eski sayfa numarası yeni üye listesinde boş kalabilir — başa dön.
  useEffect(() => setPage(0), [effectiveTeam])
  const pageMembers = (members ?? []).slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)

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
        kullanıcılar yalnız üye oldukları SY ekiplerinin domain/uygulamalarını (ve değişiklik taleplerini)
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
          {pageMembers.map((m) => (
            <TableRow key={m.id} hover>
              <TableCell sx={{ fontWeight: 600 }}>{m.username}</TableCell>
              <TableCell>{m.full_name ?? '—'}</TableCell>
              <TableCell>{m.email ?? '—'}</TableCell>
              <TableCell align="right" sx={{ whiteSpace: 'nowrap', width: '1%' }}>
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
      <TablePagination
        component="div"
        count={members?.length ?? 0}
        page={page}
        onPageChange={(_e, newPage) => setPage(newPage)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        rowsPerPageOptions={[10, 25, 50, 100]}
        labelRowsPerPage="Sayfa başına satır"
        labelDisplayedRows={({ from, to, count }) => `${from}–${to} / ${count}`}
      />
    </Box>
  )
}


// ---------- Mail Gönderim Geçmişi ----------

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
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const categories = useMemo(() => Array.from(new Set((tags ?? []).map((t) => t.category))), [tags])
  const pageTags = (tags ?? []).slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
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
          {pageTags.map((t) => (
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
      <TablePagination
        component="div"
        count={(tags ?? []).length}
        page={page}
        onPageChange={(_e, newPage) => setPage(newPage)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        rowsPerPageOptions={[10, 25, 50, 100]}
        labelRowsPerPage="Sayfa başına satır"
        labelDisplayedRows={({ from, to, count }) => `${from}–${to} / ${count}`}
      />

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

// ---------- Erişim (sayfa görünürlüğü: Uyum/Değişiklik Talepleri/Keşif/Dağıtım) ----------
function AccessTab() {
  const { form, setForm, save } = useCategory('access')

  const SWITCHES: { key: string; label: string }[] = [
    { key: 'policy_all_roles', label: 'Uyum sayfası herkese açık' },
    { key: 'proposals_all_roles', label: 'Değişiklik Talepleri sayfası herkese açık' },
    { key: 'discovery_all_roles', label: 'Keşif sayfası herkese açık' },
    { key: 'deployments_all_roles', label: 'Dağıtım sayfası herkese açık' },
  ]

  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Varsayılan: Uyum, Değişiklik Talepleri, Keşif ve Dağıtım sayfaları yalnız <b>Yönetici</b> ve
        <b> Genel İzleyici</b> rolüne görünür. Aşağıdaki anahtarları açarsanız ilgili sayfa
        <b> tüm rollere</b> (İzleyici dahil) görünür olur. <b>Değişiklik Talepleri istisnası:</b> bu
        ayardan bağımsız olarak, bir SY ekibinin üyesi kendi ekibinin bekleyen değişiklik taleplerini
        her zaman görüp onaylayabilir — onay yetkisi bu anahtarla DEĞİŞMEZ. Dağıtımı fiilen
        <b> tetikleme</b> her durumda yalnız Yönetici'dedir; bu anahtar yalnız görüntülemeyi açar.
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
          Keşif sayfasındaki “Taramayı Başlat” ile elle ya da dış API ile çalışır.
        </Typography>
        <AutoOffNote show={!form.enabled} trigger="POST /api/discovery/scan" />
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
          <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
                helper='Dış araç: POST /api/discovery/scan + "X-API-Key: <anahtar>" başlığı; durum: GET /api/discovery/scan/status. Boşsa dış tetikleme kapalı (yalnız admin).' />
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
          label="Gece CT izleme etkin (her gün)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm envanter domainleri her gece crt.sh'ten sorgulanır. Kapalıyken sorgu yalnız Keşif
          sayfasındaki “CT İzleme” düğmesiyle elle ya da dış API ile çalışır.
        </Typography>
        <AutoOffNote show={!form.enabled} trigger="POST /api/discovery/ct-scan" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="proxy_url" label="Forward Proxy (opsiyonel)"
                helper="crt.sh'e ulaşmak için http://host:port — boşsa doğrudan bağlanır" />
          <Text form={form} setForm={setForm} field="schedule_hour" label="Gece Saati (0-23)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Gece CT izlemenin başlayacağı saat (sunucu saati)" />
          <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)" type="number"
                width={{ xs: 6, sm: 3 }} helper="crt.sh isteği için azami bekleme süresi" />
          <Text form={form} setForm={setForm} field="concurrency" label="Concurrency" type="number"
                width={{ xs: 6, sm: 3 }} helper="Domain başına eşzamanlı sertifika indirmesi — crt.sh'e nazik olmak için düşük tutun" />
          <Text form={form} setForm={setForm} field="max_entries_per_domain" label="Domain Başına Azami Giriş" type="number"
                width={{ xs: 6, sm: 3 }} helper="Bir domain için işlenecek en fazla CT kaydı" />
          <Text form={form} setForm={setForm} field="max_domains" label="Azami Domain (0 = hepsi)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Taranacak envanter domaini sayısı sınırı" />
          <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
                helper='Dış araç: POST /api/discovery/ct-scan + "X-API-Key: <anahtar>" başlığı; durum: GET /api/discovery/ct-scan/status. Boşsa dış tetikleme kapalı (yalnız admin).' />
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
          Açıkken, aşağıdaki listede olmayan bir CA'dan çıkmış leaf sertifikalar “İzin Listesi Dışı CA”
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
        opsiyonel <b>forward proxy</b> tanımlayın. Erişim yoksa sonuç <b>“Ulaşılamadı”</b>; iç/özel CA'lar
        çoğu zaman iptal adresi yayınlamaz, bu durumda sonuç <b>“Kontrol edilemez”</b> olur — ikisi de normaldir. JUMBO sertifikayı iptal görse bile
        <b> otomatik pasife almaz</b>, yalnız durumu gösterir.
      </Alert>

      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="İptal denetimi etkin" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Kapalıyken toplu denetim ve iptal maili yoktur; denetim yalnız sertifika detayındaki
          “Şimdi Kontrol Et” ile tek tek çalışır.
        </Typography>
        <FormControlLabel sx={{ display: 'block' }}
          control={<Switch checked={form.auto_enabled !== false} disabled={!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, auto_enabled: e.target.checked }))} />}
          label="Her gece otomatik çalışsın" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm aktif leaf sertifikalar her gece aşağıdaki saatte denetlenir.
        </Typography>
        <AutoOffNote show={!!form.enabled && form.auto_enabled === false} trigger="POST /api/certificates/revocation-run" />
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
          <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
                helper='Dış araç: POST /api/certificates/revocation-run + "X-API-Key: <anahtar>" başlığı; durum: GET /api/certificates/revocation-run/status. Boşsa dış tetikleme kapalı (yalnız admin).' />
        </Grid>
        <Button variant="contained" sx={{ mt: 2 }} onClick={() => save.mutate()} disabled={save.isPending}>
          Kaydet
        </Button>
      </Box>
    </Stack>
  )
}

// ---------- Canlı Doğrulama (TLS drift + zincir senkronizasyonu) ----------
type LiveCheckRunStatus = {
  running: boolean
  interrupted?: boolean
  pod?: string | null
  triggered_by?: string
  started_at?: string
  finished_at?: string | null
  result?: { status: string; total?: number; by_status?: Record<string, number>; errors?: number; error?: string } | null
}

const LIVE_STATUS_LABEL: Record<string, string> = {
  match: 'eşleşiyor', mismatch: 'eşleşmiyor', chain_incomplete: 'ara sertifika eksik', unreachable: 'erişilemedi', no_mapping: 'bağlı sertifika yok',
  not_checkable: 'kontrol edilemez',
}

function LiveCheckTab() {
  const { form, setForm, save } = useCategory('live_check')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { data: run } = useQuery<LiveCheckRunStatus>({
    queryKey: ['live-check-run-status'],
    queryFn: async () => (await api.get('/domains/live-check-run/status')).data,
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  })
  const runNow = useMutation({
    mutationFn: async () => (await api.post('/domains/live-check-run')).data,
    onSuccess: () => {
      enqueueSnackbar('Toplu canlı doğrulama başlatıldı — arka planda çalışıyor', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['live-check-run-status'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const res = run?.result
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Domainlerin canlıda TLS üzerinden sunduğu sertifika zincirini (leaf+intermediate+root)
        kontrol eder. Fark bulursa <b>yalnız o domain için</b> ekleme / değişiklik / kaldırma talebi
        oluşturur; bağlantılar onaysız değişmez — tamamen yerel, dış erişim gerekmez.
      </Alert>

      <Box>
        <FormControlLabel
          control={<Switch checked={!!form.enabled}
                           onChange={(e) => setForm((s) => ({ ...s, enabled: e.target.checked }))} />}
          label="Gece canlı doğrulaması etkin (her gün)" />
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Açıkken tüm domainler her gece otomatik canlı doğrulanır. Kapalıyken yalnız elle (“Canlı Doğrula”,
          “Şimdi Çalıştır”) ya da dış API ile çalışır.
        </Typography>
        <AutoOffNote show={!form.enabled} trigger="POST /api/domains/live-check-run" />
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Text form={form} setForm={setForm} field="schedule_hour" label="Gece Saati (0-23)" type="number"
                width={{ xs: 6, sm: 3 }} helper="Sunucu saati — kaydedince tüm sunucularda en geç 1 dakikada geçerli olur" />
          <Text form={form} setForm={setForm} field="trigger_api_key" label="Dış Tetikleme API Anahtarı"
                width={{ xs: 12, sm: 9 }}
                helper='Dış araç: POST /api/domains/live-check-run + "X-API-Key: <anahtar>" başlığı. Boşsa dış tetikleme kapalı (yalnız admin).' />
        </Grid>
        <Box sx={{ display: 'flex', gap: 1.5, mt: 2, flexWrap: 'wrap' }}>
          <Button variant="contained" onClick={() => save.mutate()} disabled={save.isPending}>
            Kaydet
          </Button>
          <Button variant="outlined" startIcon={<TravelExploreIcon />}
                  onClick={() => runNow.mutate()} disabled={runNow.isPending || !!run?.running}>
            {run?.running ? 'Çalışıyor…' : 'Şimdi Çalıştır'}
          </Button>
        </Box>
        {run?.started_at && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
            Son toplu çalıştırma: {formatAuditTime(run.started_at, true)} · tetikleyen{' '}
            {run.triggered_by === 'schedule' ? 'gece zamanlayıcısı'
              : run.triggered_by === 'external-api' ? 'dış API' : run.triggered_by}
            {run.pod ? ` · sunucu ${run.pod}` : ''}
            {run.running ? ' · çalışıyor' : run.interrupted ? ' · yarıda kaldı (sunucu yeniden başladı)' : res
              ? ` · ${res.status === 'error' ? 'hata' : 'tamamlandı'}${res.total != null ? ` · ${res.total} domain` : ''}${
                  res.by_status ? ` (${Object.entries(res.by_status).map(([k, v]) => `${v} ${LIVE_STATUS_LABEL[k] ?? k}`).join(', ')})` : ''}`
              : ''}
          </Typography>
        )}
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

// Sohbet panelindeki hazır sorular — ekle, düzelt, sırala, çıkar. Kaydet ile birlikte yazılır.
function AiSuggestionsEditor({ value, onChange }: { value: string[]; onChange: (list: string[]) => void }) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const q = draft.trim()
    if (!q || value.includes(q)) return
    onChange([...value, q])
    setDraft('')
  }
  const move = (i: number, d: -1 | 1) => {
    const next = [...value]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    onChange(next)
  }
  return (
    <Box>
      <SectionLabel>Hazır Sorular</SectionLabel>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Sohbet panelinde tek tıkla sorulabilen sorular. Sıra burada göründüğü gibidir (en fazla 20).
      </Typography>
      <Stack spacing={1}>
        {value.map((q, i) => (
          <Stack key={i} direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <TextField fullWidth size="small" value={q} aria-label={`Hazır soru ${i + 1}`}
                       onChange={(e) => onChange(value.map((x, j) => (j === i ? e.target.value : x)))} />
            <Tooltip title="Yukarı taşı"><span>
              <IconButton size="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Yukarı taşı">
                <ArrowUpwardIcon fontSize="small" />
              </IconButton>
            </span></Tooltip>
            <Tooltip title="Aşağı taşı"><span>
              <IconButton size="small" disabled={i === value.length - 1} onClick={() => move(i, 1)} aria-label="Aşağı taşı">
                <ArrowDownwardIcon fontSize="small" />
              </IconButton>
            </span></Tooltip>
            <Tooltip title="Çıkar">
              <IconButton size="small" color="error" onClick={() => onChange(value.filter((_, j) => j !== i))}
                          aria-label={`Hazır soruyu çıkar: ${q}`}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        ))}
        {!value.length && (
          <Typography variant="body2" color="text.secondary">Hazır soru yok; panelde öneri gösterilmez.</Typography>
        )}
        <Stack direction="row" spacing={1}>
          <TextField fullWidth size="small" label="Yeni hazır soru" value={draft}
                     onChange={(e) => setDraft(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
          <Button variant="outlined" startIcon={<AddIcon />} onClick={add}
                  disabled={!draft.trim() || value.length >= 20}>
            Ekle
          </Button>
        </Stack>
      </Stack>
    </Box>
  )
}

// AI Asistanı: kurum içi AI servisine (OpenAI uyumlu) bağlantı. Açıkken her sayfada sağ altta AI
// simgesi görünür. AI Jumbo verisini yalnız soran kullanıcının yetkisiyle OKUR, hiçbir şeyi değiştiremez.
function AiTab() {
  const { form, setForm, save } = useCategory('ai')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const test = useMutation({
    mutationFn: async () => (await api.post('/ai/test')).data,
    onSuccess: (d) => enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'warning' }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const saveAndRefresh = () => save.mutate(undefined, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-status'] }),
  })
  const bool = (field: string, label: string) => (
    <FormControlLabel
      control={<Switch checked={!!form[field]}
                       onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.checked }))} />}
      label={label} />
  )

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Kurum içi AI servisine bağlanır. Açıkken <b>her sayfanın sağ altında</b> AI simgesi görünür;
        kullanıcılar Jumbo kayıtlarını ve uygulamanın nasıl kullanılacağını (kurum wiki'sindeki Kullanım
        Kılavuzu) sorabilir.
        AI <b>hiçbir kaydı değiştiremez</b>. Kişisel bilgiler (e-posta, telefon, fotoğraf, şifre, giriş kayıtları)
        ve sistem ayarları AI'a hiç verilmez. Her soru Audit Log'a “AI sorusu” olarak yazılır.
      </Alert>
      {bool('enabled', 'AI Asistanı Etkin')}
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="assistant_name" label="Asistanın Adı"
              helper="Simgede ve sohbet başlığında görünür" />
        <Text form={form} setForm={setForm} field="model" label="Model Adı"
              helper="AI servisinde tanımlı model (ör. gpt-4o, llama-3.1-70b)" />
        <Text form={form} setForm={setForm} field="api_url" label="API Adresi"
              width={{ xs: 12, sm: 12 }}
              helper="OpenAI uyumlu adres: https://ai.firma.local/v1 ya da tam …/chat/completions adresi" />
        <Grid size={{ xs: 12, sm: 4 }}>
          <TextField select fullWidth size="small" label="Anahtar Gönderimi"
                     value={String(form.auth_mode ?? 'bearer')}
                     onChange={(e) => setForm((f) => ({ ...f, auth_mode: e.target.value }))}>
            <MenuItem value="bearer">Authorization: Bearer</MenuItem>
            <MenuItem value="api-key">api-key başlığı (Azure)</MenuItem>
          </TextField>
        </Grid>
        <Text form={form} setForm={setForm} field="api_key" label="API Anahtarı" type="password"
              width={{ xs: 12, sm: 8 }} helper="Şifreli saklanır" />
      </Grid>
      <Box>
        {bool('use_tools', 'AI Jumbo verisini okuyabilsin')}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          Servisin “tool calling” desteği gerekir. Desteklemiyorsa ya da kapalıysa AI kayıtlara bakamaz;
          genel sorulara ve Kullanım Kılavuzu'ndaki konulara cevap verir.
        </Typography>
      </Box>
      <Box>
        {bool('full_access', 'Herkes tüm uygulama verisini sorabilsin (kişisel bilgiler hariç)')}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          Açıkken Ekip Editörü ve Ekip İzleyici de AI'a sorarak başka ekiplerin kayıtlarını ve işlem geçmişini
          görebilir. Kapalıyken AI yalnız soran kişinin ekranda görebildiği kayıtlara bakar.
        </Typography>
      </Box>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="daily_limit" label="Kişi Başı Günlük Soru Sınırı"
              type="number" width={{ xs: 6, sm: 4 }} helper="0 = sınırsız" />
        <Text form={form} setForm={setForm} field="timeout_seconds" label="Zaman Aşımı (sn)"
              type="number" width={{ xs: 6, sm: 4 }} />
        <Text form={form} setForm={setForm} field="proxy_url" label="Proxy (opsiyonel)"
              width={{ xs: 12, sm: 4 }} />
        <Text form={form} setForm={setForm} field="extra_instructions" label="Ek Talimat (opsiyonel)"
              multiline rows={3} width={{ xs: 12, sm: 12 }}
              helper="AI'a her soruda verilir. Ör. bankanın sertifika yenileme prosedürü, iletişim adresleri." />
      </Grid>
      <AiSuggestionsEditor
        value={Array.isArray(form.suggestions) ? (form.suggestions as string[]) : []}
        onChange={(list) => setForm((f) => ({ ...f, suggestions: list }))} />
      <AiGuideSection form={form} setForm={setForm} />
      {bool('skip_cert_verify', 'TLS sertifikasını doğrulama (yalnız dev; AI servisi ve wiki için)')}
      <Stack direction="row" spacing={2}>
        <Button variant="contained" onClick={saveAndRefresh} disabled={save.isPending}>Kaydet</Button>
        <Button variant="outlined" onClick={() => test.mutate()} disabled={test.isPending}>
          AI Bağlantısını Test Et
        </Button>
      </Stack>
    </Stack>
  )
}

type WikiRefresh = { success: boolean; message: string; pages: { title: string; url: string; depth: number }[] }

// Kullanım Kılavuzu kurumun kendi wiki'sinde (Confluence ya da Azure DevOps/TFS) yazılır; AI "nasıl
// yapılır" sorularını oradan cevaplar, sol menüdeki Yardım > Kullanım Kılavuzu bu linki açar. "Wiki'yi
// Şimdi Oku" kaydedilmiş ayarlarla okur ve bulunan sayfaları listeler. Azure DevOps linkinde ("/_wiki")
// giriş her zaman kişisel erişim token'ıyla (PAT) yapılır, giriş şekli sorulmaz.
function AiGuideSection({ form, setForm }: {
  form: Record<string, unknown>
  setForm: React.Dispatch<React.SetStateAction<Record<string, unknown>>>
}) {
  const [result, setResult] = useState<WikiRefresh | null>(null)
  const refresh = useMutation({
    mutationFn: async () => (await api.post<WikiRefresh>('/ai/wiki/refresh')).data,
    onSuccess: setResult,
    onError: (e) => setResult({ success: false, message: apiErrorMessage(e), pages: [] }),
  })
  const azure = String(form.wiki_url ?? '').includes('/_wiki')
  const basic = !azure && form.wiki_auth_mode === 'basic'
  return (
    <Box>
      <Divider sx={{ mb: 1 }} />
      <SectionLabel>Kullanım Kılavuzu (kurum wiki'si)</SectionLabel>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        AI “nasıl yapılır” sorularını kurum wiki'sindeki Jumbo kılavuzundan cevaplar ve ilgili wiki sayfasının
        linkini verir. Jumbo yalnız aşağıdaki sayfayı ve altındaki sayfaları okur, wiki'de hiçbir şeyi değiştirmez.
        Link girildiğinde sol menüde <b>Yardım › Kullanım Kılavuzu</b> görünür ve bu sayfayı açar.
      </Typography>
      <Grid container spacing={2}>
        <Text form={form} setForm={setForm} field="wiki_url" label="Kılavuzun Ana Sayfası (link)"
              width={{ xs: 12, sm: 12 }}
              helper="Wiki sayfasını tarayıcıda açıp adres çubuğundaki linki yapıştırın (Confluence ya da Azure DevOps / TFS wiki)" />
        {!azure && (
          <Grid size={{ xs: 12, sm: 4 }}>
            <TextField select fullWidth size="small" label="Giriş Şekli"
                       value={String(form.wiki_auth_mode ?? 'bearer')}
                       onChange={(e) => setForm((f) => ({ ...f, wiki_auth_mode: e.target.value }))}>
              <MenuItem value="bearer">Kişisel erişim token'ı</MenuItem>
              <MenuItem value="basic">Kullanıcı adı + token/şifre</MenuItem>
            </TextField>
          </Grid>
        )}
        {basic && (
          <Text form={form} setForm={setForm} field="wiki_username" label="Kullanıcı Adı"
                width={{ xs: 12, sm: 4 }} helper="Cloud'da hesabın e-postası" />
        )}
        <Text form={form} setForm={setForm} field="wiki_token"
              label={azure ? "Kişisel Erişim Token'ı (PAT)" : basic ? 'Token / Şifre' : 'Token'}
              type="password" width={{ xs: 12, sm: azure ? 12 : basic ? 4 : 8 }}
              helper={azure ? "Şifreli saklanır. Azure DevOps'ta token için Wiki (Read) yetkisi yeterli."
                : 'Şifreli saklanır. Kılavuz sayfasını okuma yetkisi yeterli.'} />
        <Text form={form} setForm={setForm} field="wiki_refresh_minutes" label="Yenileme Aralığı (dk)"
              type="number" width={{ xs: 6, sm: 4 }} helper="Wiki'deki değişiklik en geç bu sürede AI'a yansır" />
        <Grid size={{ xs: 6, sm: 8 }} sx={{ display: 'flex', alignItems: 'flex-start' }}>
          <Button variant="outlined" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            {refresh.isPending ? 'Okunuyor…' : "Wiki'yi Şimdi Oku"}
          </Button>
          <Typography variant="caption" color="text.secondary" sx={{ ml: 1.5, mt: 0.5 }}>
            Kaydedilmiş ayarlarla okur; önce Kaydet'e basın.
          </Typography>
        </Grid>
      </Grid>
      {result && (
        <Alert severity={result.success ? 'success' : 'warning'} sx={{ mt: 2 }}>
          <b>{result.message}</b>
          {result.pages.length > 0 && (
            <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2, maxHeight: 220, overflow: 'auto' }}>
              {result.pages.map((p) => (
                <Box component="li" key={p.url} sx={{ ml: p.depth * 2, fontSize: 13 }}>
                  <MuiLink href={p.url} target="_blank" rel="noreferrer">{p.title}</MuiLink>
                </Box>
              ))}
            </Box>
          )}
        </Alert>
      )}
    </Box>
  )
}

// Ayarlar sol menüsü — ilişkili bölümler gruplanır. Bildirim kanalları (SMTP + Slack/Teams/Webhook,
// ileride ServiceNow/Zoom/Jabber) tek "Bildirimler" başlığı altında toplanır.
// wide=true → tablo ağırlıklı sekme (tam genişlik); aksi halde form okunur bir sütunda (~880px).
type NavItem = { key: string; label: string; desc: string; el: React.ReactNode; wide?: boolean }
type NavGroup = { title: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  { title: 'Kimlik & Erişim', items: [
    { key: 'users', label: 'Kullanıcılar', desc: 'Hesaplar, roller ve takım kapsamları', wide: true, el: <UsersPanel /> },
    { key: 'teams', label: 'Ekipler', desc: 'SY/UG ekiplerini oluştur ve yönet', wide: true, el: <TeamsPanel /> },
    { key: 'memberships', label: 'Ekip Üyelikleri', desc: 'Üyelik = kullanıcının veri kapsamı', wide: true, el: <MembershipsTab /> },
    { key: 'access', label: 'Erişim', desc: 'Uyum/Değişiklik Talepleri/Keşif/Dağıtım sayfa görünürlüğü', el: <AccessTab /> },
    { key: 'ldap', label: 'LDAP / Active Directory', desc: 'Kurumsal dizinle kimlik doğrulama', el: <LdapTab /> },
    { key: 'ldap-query', label: 'LDAP Sorguları', desc: 'Kişinin hangi Scrum ekibiyle geldiği ve ekiplerde kimlerin olduğu (dizinden canlı)', wide: true, el: <LdapQueryPanel /> },
  ] },
  { title: 'Bildirimler', items: [
    { key: 'smtp', label: 'E-posta (SMTP)', desc: 'Süresi yaklaşan sertifikalar için bilgilendirme e-postaları', el: <SmtpTab /> },
    { key: 'mail-history', label: 'Mail Gönderim Geçmişi', desc: 'Gönderilen bilgilendirme e-postalarının kaydı (teslim edilemeyenler dâhil)', wide: true, el: <MailHistoryPanel /> },
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
    { key: 'live_check', label: 'Canlı Doğrulama', desc: 'TLS drift kontrolü ve zincir senkronizasyonu', el: <LiveCheckTab /> },
  ] },
  { title: 'Sistem', items: [
    { key: 'tags', label: 'Etiketler', desc: 'Uygulama etiketi kataloğu', wide: true, el: <TagsTab /> },
    { key: 'vault', label: 'Vault (Hazırlık)', desc: 'Vault PKI entegrasyonu (yakında)', el: <VaultTab /> },
    { key: 'jenkins', label: 'Jenkins', desc: 'Jenkins bağlantı ayarları (tetikleme → Dağıtım sayfası)', el: <JenkinsTab /> },
    { key: 'ai', label: 'AI Asistanı', desc: 'Kurum içi AI servisine bağlantı; her sayfada AI simgesi', el: <AiTab /> },
    { key: 'audit', label: 'Audit Log', desc: 'Denetim kaydı — kim, neyi, ne zaman değiştirdi (eski → yeni); her kolon filtrelenir, CSV dışa aktarılır', wide: true, el: <AuditLogPanel /> },
  ] },
]

export default function Settings() {
  useDocumentTitle('Ayarlar')
  const { isAdmin } = useAuth()
  // Açık bölüm URL'de (?tab=audit) — yenileyince/bağlantı paylaşınca aynı bölüm açılır
  const navKeys = useMemo(() => NAV_GROUPS.flatMap((g) => g.items.map((it) => it.key)), [])
  const [active, setActive] = useUrlState('tab', 'users', navKeys)
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
