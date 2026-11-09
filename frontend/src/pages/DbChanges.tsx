import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ScienceOutlinedIcon from '@mui/icons-material/ScienceOutlined'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Skeleton, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { fmtDate, StatusPill } from '../components/DetailCards'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { Panel } from '../components/TeamSummaryKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { MONO_FONT } from '../theme'

// Veritabanı Değişiklikleri (v3.9.38, yalnız admin, yalnız DB_CONSOLE=1): GitHub'daki
// db/degisiklikler/*.sql betiği buraya yapıştırılıp önce denenir (geri alınır), sonra çalıştırılır.
// Her çalıştırma tek işlemdir; kim, ne zaman, hangi SQL ve sonuç Audit Log'a yazılır.
type Pending = { key: string; version: string; title: string; table: string; column: string;
                 feature: string; script: string; applied: boolean }
type HistoryRow = { id: number; at: string; by: string; dry_run: boolean; title: string; sql: string;
                    ok: boolean; error: string | null; ms: number | null; rowcounts: number[] }
type Info = { enabled: boolean; dialect: string; database: string | null; can_alter: boolean | null;
              pending: Pending[]; history: HistoryRow[] }
type ResultSet = { columns: string[]; rows: unknown[][]; truncated: boolean }
type RunResult = { ok: boolean; dry_run: boolean; error: string | null; ms: number; results: ResultSet[];
                   rowcounts: number[] }

const fmtMs = (ms?: number | null) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 2 })} sn`)

export default function DbChanges() {
  useDocumentTitle('Veritabanı Değişiklikleri')
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [sql, setSql] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [confirm, setConfirm] = useState<{ warnings: string[] } | null>(null)
  const [word, setWord] = useState('')
  const [shown, setShown] = useState<HistoryRow | null>(null)

  const info = useQuery<Info>({ queryKey: ['db-console'], queryFn: async () => (await api.get('/db-console')).data })

  const run = useMutation({
    mutationFn: async (v: { dry_run: boolean; confirm?: string }) =>
      (await api.post<RunResult>('/db-console/run', { sql, title, ...v })).data,
    onSuccess: (r) => {
      setResult(r)
      setConfirm(null); setWord('')
      qc.invalidateQueries({ queryKey: ['db-console'] })
      if (!r.dry_run && r.ok) {
        // Bekleyen değişiklik uygulandıysa bağlı özellikler (ör. Standart Ad) açılır
        qc.invalidateQueries({ queryKey: ['auth-me'] })
        qc.invalidateQueries({ queryKey: ['certificates'] })
        enqueueSnackbar('Değişiklik uygulandı', { variant: 'success' })
      }
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const analyze = useMutation({
    mutationFn: async () => (await api.post<{ warnings: string[] }>('/db-console/analyze', { sql })).data,
    onSuccess: (r) => setConfirm({ warnings: r.warnings }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const header = (
    <PageHeader title="Veritabanı Değişiklikleri"
                subtitle="GitHub'daki db/degisiklikler klasöründen aldığınız SQL'i yapıştırıp çalıştırın. Her çalıştırma kayıt altına alınır. Yalnız yöneticiler görür." />
  )
  if (info.isError) return <Box>{header}<QueryError error={info.error} onRetry={() => info.refetch()} /></Box>
  if (!info.data) return <Box>{header}<Skeleton variant="rounded" height={520} /></Box>
  const d = info.data
  const ready = sql.trim() && title.trim() && !run.isPending
  const pendingCount = d.pending.filter((p) => !p.applied).length
  const risky = (confirm?.warnings.length ?? 0) > 0

  return (
    <Box>
      {header}
      {pendingCount > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {pendingCount} bekleyen değişiklik var. Uygulanana kadar ona bağlı özellik kapalı kalır, uygulamanın geri kalanı normal çalışır.
        </Alert>
      )}
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1.6fr 1fr' }, alignItems: 'start' }}>
        <Panel title="SQL">
          <TextField size="small" fullWidth label="Değişiklik adı" placeholder="ör. v3.9.39 Sertifikalara Standart Ad kolonu"
                     value={title} onChange={(e) => setTitle(e.target.value)} sx={{ mb: 1.5 }}
                     helperText="Geçmişte bu adla görünür (dosya adını yazabilirsiniz)" />
          <TextField fullWidth multiline minRows={8} maxRows={24} value={sql} label="SQL"
                     placeholder={"-- db/degisiklikler/v3.9.39-standart-ad.sql içeriğini buraya yapıştırın"}
                     onChange={(e) => { setSql(e.target.value); setResult(null) }}
                     onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && ready) run.mutate({ dry_run: true }) }}
                     slotProps={{ input: { sx: { fontFamily: MONO_FONT, fontSize: 13 } } }} />
          <Box sx={{ display: 'flex', gap: 1, mt: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button variant="outlined" startIcon={<ScienceOutlinedIcon />} disabled={!ready}
                    onClick={() => run.mutate({ dry_run: true })}>Dene (geri al)</Button>
            <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={!ready || analyze.isPending}
                    onClick={() => analyze.mutate()}>Çalıştır…</Button>
            <Typography variant="caption" color="text.secondary">Ctrl+Enter = Dene</Typography>
          </Box>
          {run.isPending && <Typography variant="body2" sx={{ mt: 1.5 }}>Çalışıyor…</Typography>}
          {result && <ResultView r={result} />}
        </Panel>

        <Box sx={{ display: 'grid', gap: 2 }}>
          <Panel title="Çalıştırmadan önce">
            <Box component="ul" sx={{ m: 0, pl: 2.5, '& li': { mb: 0.75 }, typography: 'body2' }}>
              <li>SQL tek işlem (transaction) içinde çalışır; hata olursa hiçbir şey değişmez.</li>
              <li>"Dene" SQL'i çalıştırır, sonucu gösterir ve her şeyi geri alır.</li>
              <li>DROP, TRUNCATE ya da WHERE'siz DELETE/UPDATE varsa onay için <b>UYGULA</b> yazmanız istenir.</li>
              <li>Kilit beklemesi en fazla 60 sn; aynı anda yalnız bir kişi çalıştırabilir.</li>
              <li>Önemli değişiklikten önce veritabanı yedeği alın.</li>
            </Box>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 0.5, columnGap: 2, mt: 1.5, typography: 'body2' }}>
              <Typography variant="body2" color="text.secondary">Veritabanı</Typography>
              <span>{d.dialect === 'mssql' ? 'MSSQL' : d.dialect}{d.database ? ` · ${d.database}` : ''}</span>
              <Typography variant="body2" color="text.secondary">ALTER yetkisi</Typography>
              <span>{d.can_alter == null ? 'bilinmiyor' : d.can_alter
                ? <StatusPill size="small" tone="success" label="Var" />
                : <StatusPill size="small" tone="error" label="Yok: SQL'i DBA'ya verin" />}</span>
            </Box>
          </Panel>
          <Panel title="Bekleyen uygulama değişiklikleri">
            {d.pending.length === 0 ? <Typography variant="body2" color="text.secondary">Yok</Typography> : (
              <Box sx={{ display: 'grid', gap: 1.25 }}>
                {d.pending.map((p) => (
                  <Box key={p.key}>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                      <StatusPill size="small" tone={p.applied ? 'success' : 'warning'} label={p.applied ? 'Uygulandı' : 'Bekliyor'} />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>v{p.version} {p.title}</Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                      {p.table}.{p.column} · {p.applied ? `${p.feature} açık` : `${p.feature} kolon eklenene kadar kapalı`}
                    </Typography>
                    {!p.applied && (
                      <Typography variant="caption" sx={{ display: 'block', fontFamily: MONO_FONT }}>{p.script}</Typography>
                    )}
                  </Box>
                ))}
              </Box>
            )}
          </Panel>
        </Box>
      </Box>

      <Box sx={{ mt: 2 }}>
        <Panel title="Geçmiş" pad={false}>
          {d.history.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ px: 2, pb: 2 }}>Henüz çalıştırma yok</Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell>Tarih</TableCell><TableCell>Değişiklik</TableCell><TableCell>Çalıştıran</TableCell>
                  <TableCell>Sonuç</TableCell><TableCell>Süre</TableCell><TableCell />
                </TableRow></TableHead>
                <TableBody>
                  {d.history.map((h) => (
                    <TableRow key={h.id} hover>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(h.at)}</TableCell>
                      <TableCell>{h.title}{h.dry_run ? ' (deneme)' : ''}</TableCell>
                      <TableCell>{h.by}</TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                          <StatusPill size="small" tone={!h.ok ? 'error' : h.dry_run ? 'info' : 'success'}
                                      label={!h.ok ? 'Hata' : h.dry_run ? 'Deneme' : 'Başarılı'} />
                          {h.error && <Typography variant="caption" color="error">{h.error}</Typography>}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtMs(h.ms)}</TableCell>
                      <TableCell align="right">
                        <Button size="small" variant="outlined" onClick={() => setShown(h)}>SQL'i gör</Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Panel>
      </Box>

      <Dialog open={confirm !== null} onClose={() => { setConfirm(null); setWord('') }} maxWidth="sm" fullWidth>
        <DialogTitle>SQL kalıcı olarak çalıştırılsın mı?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            <b>{title}</b> veritabanında ({d.database ?? d.dialect}) çalıştırılacak. Hata olursa hiçbir şey değişmez.
          </Typography>
          {risky && (
            <Alert severity="error" icon={<WarningAmberIcon />} sx={{ mb: 1.5 }}>
              <Box component="ul" sx={{ m: 0, pl: 2 }}>
                {confirm!.warnings.map((w) => <li key={w}>{w}</li>)}
              </Box>
              Devam etmek için aşağıya <b>UYGULA</b> yazın.
            </Alert>
          )}
          {risky && (
            <TextField size="small" fullWidth autoFocus label="Onay" placeholder="UYGULA" value={word}
                       onChange={(e) => setWord(e.target.value)} />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setConfirm(null); setWord('') }}>Vazgeç</Button>
          <Button variant="contained" color={risky ? 'error' : 'primary'}
                  disabled={run.isPending || (risky && word.trim() !== 'UYGULA')}
                  onClick={() => run.mutate({ dry_run: false, confirm: word.trim() })}>Çalıştır</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={shown !== null} onClose={() => setShown(null)} maxWidth="md" fullWidth>
        <DialogTitle>{shown?.title}{shown?.dry_run ? ' (deneme)' : ''}</DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="text.secondary">{shown && `${fmtDate(shown.at)} · ${shown.by} · ${fmtMs(shown.ms)}`}</Typography>
          <Box component="pre" sx={{ fontFamily: MONO_FONT, fontSize: 12.5, whiteSpace: 'pre-wrap', bgcolor: 'action.hover',
                                     p: 1.5, borderRadius: 1, mt: 1 }}>{shown?.sql}</Box>
          {shown?.error && <Alert severity="error">{shown.error}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { if (shown) { setSql(shown.sql); setTitle(shown.title); setResult(null) } setShown(null) }}>
            Düzenleyiciye al
          </Button>
          <Button variant="contained" onClick={() => setShown(null)}>Kapat</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

function ResultView({ r }: { r: RunResult }) {
  if (!r.ok) {
    return (
      <Alert severity="error" sx={{ mt: 1.5 }}>
        <b>{r.dry_run ? 'Deneme' : 'Çalıştırma'} başarısız</b> ({fmtMs(r.ms)}). Hiçbir şey değişmedi.
        <Box sx={{ fontFamily: MONO_FONT, fontSize: 12.5, mt: 0.5 }}>{r.error}</Box>
      </Alert>
    )
  }
  return (
    <Box sx={{ mt: 1.5 }}>
      <Alert severity="success">
        <b>{r.dry_run ? 'Deneme başarılı' : 'Uygulandı'}</b>, {fmtMs(r.ms)}.{' '}
        {r.dry_run ? 'Değişiklik geri alındı, veritabanında hiçbir şey değişmedi. Kalıcı yapmak için "Çalıştır…" deyin.'
          : 'Değişiklik kalıcı olarak kaydedildi.'}
        {r.rowcounts.length > 0 && ` Etkilenen satır: ${r.rowcounts.join(', ')}.`}
      </Alert>
      {r.results.map((rs, i) => (
        <TableContainer key={i} sx={{ mt: 1.5, maxHeight: 360, border: 1, borderColor: 'divider', borderRadius: 1 }}>
          <Table size="small" stickyHeader>
            <TableHead><TableRow>{rs.columns.map((c, j) => <TableCell key={j}>{c || `(kolon ${j + 1})`}</TableCell>)}</TableRow></TableHead>
            <TableBody>
              {rs.rows.map((row, k) => (
                <TableRow key={k}>{row.map((v, j) => (
                  <TableCell key={j} sx={{ fontFamily: MONO_FONT, fontSize: 12.5 }}>{v === null ? <i>NULL</i> : String(v)}</TableCell>
                ))}</TableRow>
              ))}
            </TableBody>
          </Table>
          {rs.truncated && <Typography variant="caption" sx={{ p: 1, display: 'block' }}>İlk 200 satır gösteriliyor.</Typography>}
        </TableContainer>
      ))}
    </Box>
  )
}
