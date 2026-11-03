import AutorenewIcon from '@mui/icons-material/Autorenew'
import CleaningServicesIcon from '@mui/icons-material/CleaningServices'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DownloadIcon from '@mui/icons-material/Download'
import FolderZipIcon from '@mui/icons-material/FolderZip'
import GroupAddIcon from '@mui/icons-material/GroupAdd'
import MailIcon from '@mui/icons-material/MailOutlined'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import VerifiedIcon from '@mui/icons-material/VerifiedUser'
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton,
  LinearProgress, Skeleton, Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField,
  Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState, type ReactNode } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { fmtDate, StatusPill } from '../components/DetailCards'
import QueryError from '../components/QueryError'
import { ROLE_CHIP } from '../utils/peopleLabels'

// Regresyon Testi > Test Hazırlığı (v3.9.28, yalnız admin, yalnız REGRESSION_TOOLS=1 olan ortamda):
// test sertifikalarını üretir, test sitelerini Jumbo'nun içinde (localhost) açar, test ekiplerini ve
// yerel test hesaplarını açar; iş bitince hepsini temizler.
export type LabStatus = {
  enabled: boolean
  host?: string
  pfx_password?: string
  certs?: { generated_at: string | null; by: string | null; files: { name: string; what: string; section: string }[] }
  sites?: { running: boolean; until: string | null; renewed: boolean
    rows: { port: number; address: string; what: string; days: number | null; up: boolean }[] }
  data?: { at: string | null; password: string | null
    teams: { name: string; exists: boolean; email: string | null; mail_key: string | null; created_here: boolean }[]
    users: { username: string; role: string; team: string | null; exists: boolean; created_here: boolean }[] }
  mail?: { capture: boolean; count: number }
}
type MailTo = { address: string; label: string | null }
type MailRow = { id: string; at: string; subject: string; to: MailTo[] }
type MailFull = MailRow & { from: string; body: string; html: string | null }
type Cleanup = { certificates: number; domains: number; applications: number; users: number; teams: number; mails: number }

export function useLabStatus() {
  return useQuery<LabStatus>({
    queryKey: ['regression', 'lab'], queryFn: async () => (await api.get('/regression/lab')).data,
    refetchInterval: (q) => (q.state.data?.sites?.running ? 30_000 : false),
  })
}

function remaining(until: string | null | undefined, now: number) {
  if (!until) return ''
  const ms = new Date(until).getTime() - now
  if (ms <= 0) return 'birazdan'
  const m = Math.ceil(ms / 60000)
  return m >= 60 ? `${Math.floor(m / 60)} sa ${m % 60} dk` : `${m} dk`
}

async function download(path: string, name: string) {
  const res = await api.get(path, { responseType: 'blob' })
  const url = URL.createObjectURL(res.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function Step({ n, done, text }: { n: number; done: boolean; text: string }) {
  return (
    <Box component="span" sx={{ display: 'inline-flex', gap: 1.25, alignItems: 'center' }}>
      <Box component="span" sx={(t) => ({
        width: 28, height: 28, borderRadius: '50%', display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 14,
        bgcolor: done ? t.palette.success.main : t.palette.action.selected, color: done ? '#fff' : t.palette.text.secondary,
      })}>{done ? '✓' : n}</Box>
      {text}
    </Box>
  )
}

function Card({ title, aside, children }: { title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <Box sx={(t) => ({ border: 1, borderColor: 'divider', borderRadius: 3, bgcolor: t.palette.background.paper, overflow: 'hidden' })}>
      <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
        <Typography component="div" variant="subtitle1" sx={{ fontWeight: 650 }}>{title}</Typography>
        {aside}
      </Box>
      {children}
    </Box>
  )
}

function Hint({ children }: { children: ReactNode }) {
  return <Typography variant="body2" color="text.secondary" sx={{ px: 2, pb: 2 }}>{children}</Typography>
}

const EMPTY_CLEANUP: Cleanup = { certificates: 0, domains: 0, applications: 0, users: 0, teams: 0, mails: 0 }

export default function RegressionLab({ lab }: { lab: LabStatus }) {
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  const [emails, setEmails] = useState({ a: '', b: '', c: '' })
  const [cleanOpen, setCleanOpen] = useState(false)

  const act = useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: object; ok: string }) =>
      (await api.post<LabStatus>(`/regression/lab/${path}`, body ?? {})).data,
    onSuccess: (d, v) => { qc.setQueryData(['regression', 'lab'], d); enqueueSnackbar(v.ok, { variant: 'success' }) },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const preview = useQuery<Cleanup>({
    queryKey: ['regression', 'lab', 'cleanup'], enabled: cleanOpen,
    queryFn: async () => (await api.get('/regression/lab/cleanup')).data,
  })
  const clean = useMutation({
    mutationFn: async () => (await api.post<Cleanup>('/regression/lab/cleanup')).data,
    onSuccess: (c) => {
      setCleanOpen(false)
      qc.invalidateQueries({ queryKey: ['regression', 'lab'] })
      enqueueSnackbar(`Temizlendi: ${c.certificates} sertifika, ${c.domains} domain, ${c.applications} uygulama, `
        + `${c.users} hesap, ${c.teams} ekip, ${c.mails} test maili`, { variant: 'success' })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const certs = lab.certs?.files ?? []
  const hasCerts = certs.length > 0
  const sites = lab.sites
  const data = lab.data
  const dataReady = !!data?.users.some((u) => u.created_here)
  const ready = hasCerts && !!sites?.running && dataReady
  const busy = act.isPending || clean.isPending
  const run = (path: string, ok: string, body?: object) => act.mutate({ path, ok, body })
  const mailBody = { emails }
  const p = preview.data ?? EMPTY_CLEANUP

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Alert severity={ready ? 'success' : 'info'} variant="outlined"
             action={(hasCerts || dataReady) ? (
               <Button color="error" startIcon={<CleaningServicesIcon />} onClick={() => setCleanOpen(true)} disabled={busy}>
                 Test Verisini Temizle
               </Button>) : undefined}>
        {ready
          ? <>Test ortamı hazır. Test siteleri <b>{remaining(sites?.until, now)}</b> sonra kendiliğinden kapanır.
            Bu sekme yalnız test ortamında (REGRESSION_TOOLS=1) görünür; canlıda yoktur.</>
          : <>Regresyon testi için gereken sertifikaları, test sitelerini, ekipleri ve test hesaplarını buradan
            hazırlayın. Ayrı sunucu, Docker ya da betik gerekmez. Bu sekme yalnız test ortamında (REGRESSION_TOOLS=1) görünür.</>}
      </Alert>
      {busy && <LinearProgress />}

      {!ready && (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5, py: 1 }}>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center' }}>
            {(['a', 'b', 'c'] as const).map((k) => (
              <TextField key={k} size="small" label={`${k.toUpperCase()} adresi (isteğe bağlı)`} value={emails[k]}
                         onChange={(e) => setEmails((m) => ({ ...m, [k]: e.target.value }))} sx={{ width: 240 }} />
            ))}
          </Box>
          <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} disabled={busy}
                  onClick={() => run('all', 'Test ortamı hazır', mailBody)}>
            Hepsini Hazırla (1–3)
          </Button>
          <Typography variant="caption" color="text.secondary">
            A, B ve C, test ekiplerinin bildirim adresleridir (Hazırlık sayfası). Boş bırakılırsa sonradan Ayarlar &gt; Ekipler'den girilir.
          </Typography>
        </Box>
      )}

      <Card title={<Step n={1} done={hasCerts} text="Test sertifikaları" />} aside={
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          {hasCerts && (
            <Typography variant="body2" color="text.secondary">
              {fmtDate(lab.certs?.generated_at)} üretildi · ad: {lab.host} · PFX parolası: {lab.pfx_password}
            </Typography>
          )}
          {hasCerts && (
            <Button size="small" startIcon={<FolderZipIcon />}
                    onClick={() => download('/regression/lab/zip', 'jumbo-test-dosyalari.zip')
                      .catch((e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }))}>
              Tümünü İndir (zip)
            </Button>
          )}
          <Button variant={hasCerts ? 'outlined' : 'contained'} size="small" startIcon={<AutorenewIcon />} disabled={busy}
                  onClick={() => run('certs', 'Test sertifikaları üretildi')}>
            {hasCerts ? 'Yeniden Üret' : 'Üret'}
          </Button>
        </Box>
      }>
        {hasCerts ? (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 640 }}>
              <TableHead><TableRow>
                <TableCell>Dosya</TableCell><TableCell>Ne için</TableCell>
                <TableCell sx={{ width: 120 }}>Kılavuz</TableCell><TableCell sx={{ width: 56 }} />
              </TableRow></TableHead>
              <TableBody>
                {certs.map((f) => (
                  <TableRow key={f.name} hover>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 13 }}>{f.name}</TableCell>
                    <TableCell sx={{ color: 'text.secondary' }}>{f.what}</TableCell>
                    <TableCell>{f.section}</TableCell>
                    <TableCell>
                      <Tooltip title="İndir">
                        <IconButton size="small" aria-label={`${f.name} indir`}
                                    onClick={() => download(`/regression/lab/files/${encodeURIComponent(f.name)}`, f.name)
                                      .catch((e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }))}>
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Hint>26 dosya (00–25) bugünün tarihine göre üretilir. "20 gün kala" gibi sertifikalar her üretimde yeniden ayarlanır.
            Yeniden üretince açık test siteleri de yeni sertifikalara geçer.</Hint>
        )}
      </Card>

      <Card title={<Step n={2} done={!!sites?.running} text="Test siteleri" />} aside={
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          {sites?.running && (
            <FormControlLabel control={
              <Switch checked={sites.renewed} disabled={busy}
                      onChange={(e) => run('sites/renewed', e.target.checked ? '9444 yenilenmiş sertifikayı sunuyor'
                        : '9444 eski sertifikayı sunuyor', { renewed: e.target.checked })} />
            } label="9444: yenilenmiş sertifikayı sun (madde 5.6)" />
          )}
          {sites?.running
            ? <Button variant="outlined" color="error" size="small" startIcon={<StopIcon />} disabled={busy}
                      onClick={() => run('sites/stop', 'Test siteleri kapatıldı')}>Durdur</Button>
            : <Button variant="contained" size="small" startIcon={<PlayArrowIcon />} disabled={!hasCerts || busy}
                      onClick={() => run('sites/start', 'Test siteleri açıldı')}>Başlat</Button>}
        </Box>
      }>
        {sites?.running ? (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 640 }}>
              <TableHead><TableRow>
                <TableCell sx={{ width: 120 }}>Durum</TableCell><TableCell sx={{ width: 170 }}>Adres</TableCell>
                <TableCell>Ne sunar</TableCell><TableCell sx={{ width: 110 }}>Kalan süre</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {sites.rows.map((r) => (
                  <TableRow key={r.port} hover>
                    <TableCell>
                      <StatusPill size="small" tone={r.up ? 'success' : 'error'} label={r.up ? 'Çalışıyor' : 'Cevap yok'} />
                    </TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 13 }}>{r.address}</TableCell>
                    <TableCell>{r.what}</TableCell>
                    <TableCell sx={{ color: r.days !== null && r.days < 0 ? 'error.main' : 'text.secondary' }}>
                      {r.days === null ? '—' : r.days < 0 ? 'doldu' : `${r.days} gün`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Hint>7 test sitesi ve iptal listesi Jumbo'nun içinde açılır ({lab.host}:9440–9447). Jumbo bu sitelere kendi
            üstünden bağlanır; ayrı makine, DNS ya da port izni gerekmez. {hasCerts ? '' : 'Önce sertifikaları üretin.'}</Hint>
        )}
      </Card>

      <Card title={<Step n={3} done={dataReady} text="Test ekipleri ve hesapları" />} aside={
        <Button variant={dataReady ? 'outlined' : 'contained'} size="small" startIcon={<GroupAddIcon />} disabled={busy}
                onClick={() => run('data', 'Test ekipleri ve hesapları hazır', mailBody)}>
          {dataReady ? 'Yeniden Hazırla' : 'Hazırla'}
        </Button>
      }>
        {dataReady && data ? (
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1.4fr' }, px: 2, pb: 2 }}>
            <Box>
              <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>Ekipler</Typography>
              {data.teams.map((t) => (
                <Box key={t.name} sx={{ display: 'flex', gap: 1, alignItems: 'center', py: 0.5 }}>
                  <VerifiedIcon fontSize="small" color={t.exists ? 'success' : 'disabled'} />
                  <Typography variant="body2">
                    {t.name} · {t.mail_key ? (t.email ? `${t.mail_key}: ${t.email}` : `${t.mail_key} adresi girilmedi`) : 'mail yok'}
                    {t.exists && !t.created_here ? ' (önceden vardı, temizlikte silinmez)' : ''}
                  </Typography>
                </Box>
              ))}
            </Box>
            <Box>
              <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                Yerel test hesapları · parola: {data.password}
              </Typography>
              <Table size="small">
                <TableBody>
                  {data.users.map((u) => (
                    <TableRow key={u.username}>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 13, pl: 0 }}>{u.username}</TableCell>
                      <TableCell>{ROLE_CHIP[u.role]?.label ?? u.role}</TableCell>
                      <TableCell sx={{ color: 'text.secondary' }}>
                        {u.team ?? '—'}{u.exists && !u.created_here ? ' (aynı adlı hesap vardı, dokunulmadı)' : ''}
                      </TableCell>
                      <TableCell sx={{ width: 40 }}>
                        <Tooltip title="Kullanıcı adını kopyala">
                          <IconButton size="small" aria-label={`${u.username} kopyala`}
                                      onClick={() => navigator.clipboard?.writeText(u.username)}>
                            <ContentCopyIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Typography variant="caption" color="text.secondary">
                Hesaplar Jumbo'nun yerel hesaplarıdır. AD girişini sınayan adımlar için gerçek AD hesabı yine gerekir.
              </Typography>
            </Box>
          </Box>
        ) : (
          <Hint>4 SY ekibi (Türkçe adlarıyla) ve 4 yerel test hesabı rol ve ekip üyelikleriyle açılır. Aynı adlı
            ekip zaten varsa o kullanılır ve temizlikte silinmez.</Hint>
        )}
      </Card>

      <MailBox lab={lab} busy={busy} onToggle={(on) => run('mail/capture', on
        ? 'Test mail kutusu açık: mailler dışarı gitmiyor' : 'Test mail kutusu kapatıldı: mailler gerçek sunucuya gidiyor', { on })} />

      <Dialog open={cleanOpen} onClose={() => setCleanOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Test verisi temizlensin mi?</DialogTitle>
        <DialogContent>
          {preview.isError ? <QueryError error={preview.error} onRetry={() => preview.refetch()} />
            : !preview.data ? <Skeleton variant="rounded" height={160} /> : (
              <>
                <Typography variant="body2" sx={{ mb: 1.5 }}>Test siteleri kapatılır ve şu kayıtlar kalıcı olarak silinir:</Typography>
                <Box component="ul" sx={{ m: 0, pl: 2.5, '& li': { mb: 0.5 } }}>
                  <li><b>{p.certificates}</b> test sertifikası (Subject ya da Issuer'ında "O=Jumbo Regresyon Testi" olanlar) ve bağlantıları</li>
                  <li><b>{p.domains}</b> test domaini (localhost…, *.jumbo-test.local ve test ekiplerinin domainleri) ve talepleri</li>
                  <li><b>{p.applications}</b> test ekiplerinin uygulaması</li>
                  <li><b>{p.users}</b> yerel test hesabı ve <b>{p.teams}</b> test ekibi (yalnız bu sekmenin açtıkları)</li>
                  <li><b>{p.mails}</b> mail test mail kutusundan silinir ve kutu kapatılır</li>
                </Box>
                <Alert severity="info" variant="outlined" sx={{ mt: 1.5 }}>
                  Regresyon test sonuçları, Audit Log ve ayarlar değişmez. Önceden var olan ekipler ve hesaplar silinmez.
                </Alert>
              </>
            )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCleanOpen(false)}>Vazgeç</Button>
          <Button variant="contained" color="error" startIcon={<CleaningServicesIcon />}
                  disabled={!preview.data || clean.isPending} onClick={() => clean.mutate()}>
            {clean.isPending ? 'Temizleniyor…' : 'Temizle'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

// ---------------------------------------------------------------- 4) test mail kutusu (v3.9.29)
function MailBox({ lab, busy, onToggle }: { lab: LabStatus; busy: boolean; onToggle: (on: boolean) => void }) {
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const capture = !!lab.mail?.capture
  const [openId, setOpenId] = useState<string | null>(null)
  const [clearOpen, setClearOpen] = useState(false)
  const mails = useQuery<MailRow[]>({
    queryKey: ['regression', 'lab', 'mails'], queryFn: async () => (await api.get('/regression/lab/mails')).data,
    refetchInterval: capture ? 10_000 : false,
  })
  const one = useQuery<MailFull>({
    queryKey: ['regression', 'lab', 'mail', openId], enabled: !!openId,
    queryFn: async () => (await api.get(`/regression/lab/mails/${openId}`)).data,
  })
  const clear = useMutation({
    mutationFn: async () => (await api.delete<{ deleted: number }>('/regression/lab/mails')).data,
    onSuccess: (d) => {
      setClearOpen(false)
      qc.invalidateQueries({ queryKey: ['regression', 'lab'] })
      enqueueSnackbar(`Test mail kutusu boşaltıldı (${d.deleted} mail)`, { variant: 'success' })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const rows = mails.data ?? []
  const toText = (to: MailTo[]) => to.map((t) => t.label ?? t.address).join(', ')

  return (
    <Card title={<Step n={4} done={capture} text="Test mail kutusu" />} aside={
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        {rows.length > 0 && (
          <Button size="small" color="error" startIcon={<CleaningServicesIcon />} onClick={() => setClearOpen(true)}>
            Kutuyu Boşalt
          </Button>
        )}
        <FormControlLabel control={<Switch checked={capture} disabled={busy} onChange={(e) => onToggle(e.target.checked)} />}
                          label="Mailleri gerçek sunucu yerine buraya topla" />
      </Box>
    }>
      {capture && (
        <Alert severity="warning" variant="outlined" sx={{ mx: 2, mb: 1.5 }}>
          Kutu açık: Jumbo dışarıya hiç mail göndermiyor; uyarılar, hatırlatmalar ve "Test Maili Gönder" burada
          görünür. Ayarlar &gt; E-posta (SMTP)'de "E-posta Bildirimleri Etkin" açık olmalı; mail sunucusu girilmese de olur.
          Gerçek sunucuyu denemek için kutuyu kapatıp bir test maili gönderin.
        </Alert>
      )}
      {mails.isError ? <Box sx={{ px: 2, pb: 2 }}><QueryError error={mails.error} onRetry={() => mails.refetch()} /></Box>
        : rows.length ? (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 640 }}>
              <TableHead><TableRow>
                <TableCell sx={{ width: 150 }}>Zaman</TableCell><TableCell sx={{ width: 260 }}>Alıcı</TableCell>
                <TableCell>Konu</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {rows.map((m) => (
                  <TableRow key={m.id} hover sx={{ cursor: 'pointer' }} onClick={() => setOpenId(m.id)}>
                    <TableCell sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>{fmtDate(m.at)}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center' }}>
                        <MailIcon fontSize="small" color="action" />{toText(m.to)}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{m.subject}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Hint>{capture ? 'Henüz mail yok. Jumbo bir mail gönderdiğinde birkaç saniye içinde burada görünür.'
            : 'Açıkken Jumbo mail göndermez; A, B, C ve Y adreslerine gidecek mailler burada listelenir. '
              + '4 gerçek posta kutusu ya da test mail sunucusu gerekmez.'}</Hint>
        )}

      <Dialog open={!!openId} onClose={() => setOpenId(null)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ pr: 6 }}>{one.data?.subject ?? 'Mail'}</DialogTitle>
        <DialogContent dividers>
          {one.isError ? <QueryError error={one.error} onRetry={() => one.refetch()} />
            : !one.data ? <Skeleton variant="rounded" height={320} /> : (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  {fmtDate(one.data.at)} · Kimden: {one.data.from} · Kime: {one.data.to.map((t) =>
                    t.label ? `${t.address} (${t.label})` : t.address).join(', ')}
                </Typography>
                {one.data.html
                  ? <Box component="iframe" title="Mail içeriği" sandbox="" srcDoc={one.data.html}
                         sx={{ width: '100%', height: 480, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: '#fff' }} />
                  : <Box component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', m: 0 }}>{one.data.body}</Box>}
              </>
            )}
        </DialogContent>
        <DialogActions><Button onClick={() => setOpenId(null)}>Kapat</Button></DialogActions>
      </Dialog>

      <Dialog open={clearOpen} onClose={() => setClearOpen(false)}>
        <DialogTitle>Test mail kutusu boşaltılsın mı?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">Kutudaki {rows.length} mail silinir. Jumbo'nun Mail Gönderim Geçmişi değişmez.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClearOpen(false)}>Vazgeç</Button>
          <Button variant="contained" color="error" disabled={clear.isPending} onClick={() => clear.mutate()}>Boşalt</Button>
        </DialogActions>
      </Dialog>
    </Card>
  )
}
