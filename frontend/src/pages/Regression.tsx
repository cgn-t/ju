import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import DownloadIcon from '@mui/icons-material/Download'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import FlagIcon from '@mui/icons-material/Flag'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Dialog, DialogActions, DialogContent,
  DialogTitle, IconButton, LinearProgress, Menu, MenuItem, Skeleton, Tab, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Tabs, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { fmtDate, StatusPill, type Tone } from '../components/DetailCards'
import { EmptyState, SearchBox, StatusTabs } from '../components/ListKit'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { Panel } from '../components/TeamSummaryKit'
import { useAiStatus } from '../hooks/useAiStatus'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { askAi } from '../utils/aiAsk'
import { exportSheet } from '../utils/exportSheet'
import { foldText } from '../utils/textMatch'
import RegressionLab, { useLabStatus } from './RegressionLab'

// Regresyon Testi (yalnız admin, v3.9.27): otomatik kontroller (yalnız okur), elle test listesi
// (Geçti / Kaldı / Atlandı + not) ve her adımda AI yardımı. Sonuçlar sunucuda Audit Log'a yazılır.
type CheckStatus = 'ok' | 'warn' | 'fail' | 'skip'
type CheckResult = { id: string; group: string; title: string; status: CheckStatus; message: string; ms?: number }
type AutoRun = { at: string; by: string; run_id: string | null; version: string; results: CheckResult[] }
type Scenario = { id: string; sub: string; title: string; expected: string }
type Section = { key: string; title: string; note: string; scenarios: Scenario[] }
type Catalog = { sections: Section[]; total: number; version: string }
type Result = 'pass' | 'fail' | 'skip'
type Mark = { result: Result; note: string; by: string; at: string }
type Counts = { pass: number; fail: number; skip: number; pending: number; total: number }
type Run = {
  id: string; title: string; version: string; started_by: string; started_at: string
  finished_at: string | null; finished_by: string | null; counts: Counts
  marks?: Record<string, Mark>; auto?: AutoRun | null
}

const CHECK_PILL: Record<CheckStatus, { tone: Tone; label: string }> = {
  ok: { tone: 'success', label: 'Tamam' }, warn: { tone: 'warning', label: 'Uyarı' },
  fail: { tone: 'error', label: 'Hata' }, skip: { tone: 'default', label: 'Kapalı' },
}
const RESULT: Record<Result, { tone: Tone; label: string }> = {
  pass: { tone: 'success', label: 'Geçti' }, fail: { tone: 'error', label: 'Kaldı' }, skip: { tone: 'default', label: 'Atlandı' },
}
const RUN_KEY = 'jumbo.regression.run'

function readRun(): string | null {
  try {
    return localStorage.getItem(RUN_KEY)
  } catch {
    return null
  }
}

function scenarioText(sc: Scenario, section: string) {
  return `Regresyon testi, senaryo ${sc.id} (${section}).\nNe yapılır: ${sc.title}\nBeklenen: ${sc.expected}`
}

export default function Regression() {
  useDocumentTitle('Regresyon Testi')
  const [tab, setTab] = useState<'manual' | 'auto' | 'lab'>('manual')
  const lab = useLabStatus()   // Test Hazırlığı yalnız REGRESSION_TOOLS=1 olan ortamda
  const [runId, setRunIdState] = useState<string | null>(readRun)
  const setRunId = (id: string | null) => {
    setRunIdState(id)
    try {
      if (id) localStorage.setItem(RUN_KEY, id)
      else localStorage.removeItem(RUN_KEY)
    } catch { /* yalnız bu oturum */ }
  }
  const { data: ai } = useAiStatus()
  const aiOn = !!ai?.enabled

  const catalog = useQuery<Catalog>({
    queryKey: ['regression', 'catalog'], queryFn: async () => (await api.get('/regression/catalog')).data,
    staleTime: Infinity,
  })
  const runs = useQuery<Run[]>({ queryKey: ['regression', 'runs'], queryFn: async () => (await api.get('/regression/runs')).data })
  const current = runs.data?.find((r) => r.id === runId) ?? null
  useEffect(() => {   // seçili test silinmiş/yoksa en sonuncusu
    if (runs.data && !current && runs.data.length) setRunId(runs.data[0].id)
  }, [runs.data, current])  // eslint-disable-line react-hooks/exhaustive-deps

  const header = (
    <PageHeader title="Regresyon Testi"
                subtitle="Sürüm öncesi kontrol: otomatik kontroller, elle test listesi ve AI yardımı. Yalnız yöneticiler görür." />
  )
  if (catalog.isError) return <Box>{header}<QueryError error={catalog.error} onRetry={() => catalog.refetch()} /></Box>
  if (!catalog.data || runs.isLoading) return <Box>{header}<Skeleton variant="rounded" height={520} /></Box>

  return (
    <Box>
      {header}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto"
            sx={{ mb: 2.5, borderBottom: 1, borderColor: 'divider' }}>
        <Tab value="manual" label={`Elle test (${catalog.data.total} senaryo)`} sx={{ textTransform: 'none', fontWeight: 600 }} />
        <Tab value="auto" label="Otomatik kontroller" sx={{ textTransform: 'none', fontWeight: 600 }} />
        {lab.data?.enabled && <Tab value="lab" label="Test Hazırlığı" sx={{ textTransform: 'none', fontWeight: 600 }} />}
      </Tabs>
      {tab === 'lab' && lab.data?.enabled ? <RegressionLab lab={lab.data} /> : tab === 'manual'
        ? <ManualTests catalog={catalog.data} runs={runs.data ?? []} runId={current?.id ?? null}
                       onSelect={setRunId} aiOn={aiOn} />
        : <AutoChecks runId={current && !current.finished_at ? current.id : null} runTitle={current?.title} aiOn={aiOn} />}
    </Box>
  )
}

// ---------------------------------------------------------------- otomatik kontroller
function AutoChecks({ runId, runTitle, aiOn }: { runId: string | null; runTitle?: string; aiOn: boolean }) {
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const checks = useQuery<{ checks: Omit<CheckResult, 'status' | 'message'>[]; last: AutoRun | null }>({
    queryKey: ['regression', 'checks'], queryFn: async () => (await api.get('/regression/checks')).data,
  })
  const run = useMutation({
    mutationFn: async () => (await api.post<AutoRun>('/regression/checks/run', { run_id: runId })).data,
    onSuccess: (d) => {
      qc.setQueryData(['regression', 'checks'], (old: typeof checks.data) => (old ? { ...old, last: d } : old))
      const bad = d.results.filter((r) => r.status === 'fail').length
      enqueueSnackbar(bad ? `${bad} kontrol hata verdi` : 'Kontroller tamamlandı', { variant: bad ? 'warning' : 'success' })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  if (checks.isError) return <QueryError error={checks.error} onRetry={() => checks.refetch()} />
  if (!checks.data) return <Skeleton variant="rounded" height={420} />

  const last = checks.data.last
  const byId = new Map((last?.results ?? []).map((r) => [r.id, r]))
  const rows = checks.data.checks.map((c) => byId.get(c.id) ?? { ...c, status: undefined, message: '' })
  const groups = [...new Set(rows.map((r) => r.group))]
  const count = (s: CheckStatus) => (last?.results ?? []).filter((r) => r.status === s).length
  const download = () => exportSheet(`otomatik-kontroller-${(last?.at ?? '').slice(0, 10)}.xlsx`,
    ['Grup', 'Kontrol', 'Durum', 'Açıklama', 'Süre (ms)'],
    (last?.results ?? []).map((r) => [r.group, r.title, CHECK_PILL[r.status].label, r.message, r.ms ?? '']))

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Alert severity="info" variant="outlined">
        Bu kontroller yalnız okur: hiçbir kaydı değiştirmez ve mail göndermez. Mail sunucusuna yalnız bağlanıp
        giriş yapılır. Sonuç Audit Log'a yazılır{runId ? `, "${runTitle}" testine bağlanır` : ''}.
      </Alert>
      <Panel title="Otomatik kontroller" aside={
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          {last && (
            <Typography variant="body2" color="text.secondary">
              Son çalışma {fmtDate(last.at)} · {last.by} · v{last.version}
            </Typography>
          )}
          <Button size="small" startIcon={<DownloadIcon />} disabled={!last} onClick={download}>Excel'e İndir</Button>
          <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? 'Çalışıyor…' : 'Kontrolleri Çalıştır'}
          </Button>
        </Box>
      } pad={false}>
        {run.isPending && <LinearProgress />}
        {last && (
          <Box sx={{ display: 'flex', gap: 1, px: 2, pb: 1.5, flexWrap: 'wrap' }}>
            <StatusPill tone="success" label={`${count('ok')} tamam`} />
            <StatusPill tone="warning" label={`${count('warn')} uyarı`} />
            <StatusPill tone="error" label={`${count('fail')} hata`} />
            <StatusPill tone="default" label={`${count('skip')} kapalı`} />
          </Box>
        )}
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 720 }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 110 }}>Durum</TableCell>
                <TableCell sx={{ width: 280 }}>Kontrol</TableCell>
                <TableCell>Sonuç</TableCell>
                {aiOn && <TableCell sx={{ width: 48 }} />}
              </TableRow>
            </TableHead>
            <TableBody>
              {groups.map((g) => (
                <Fragment key={g}>
                  <TableRow>
                    <TableCell colSpan={aiOn ? 4 : 3} sx={{ bgcolor: 'action.hover', fontWeight: 700, py: 0.75 }}>{g}</TableCell>
                  </TableRow>
                  {rows.filter((r) => r.group === g).map((r) => (
                    <TableRow key={r.id} hover>
                      <TableCell>
                        {r.status ? <StatusPill size="small" {...CHECK_PILL[r.status]} />
                          : <Typography variant="body2" color="text.disabled">—</Typography>}
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>{r.title}</TableCell>
                      <TableCell sx={{ color: 'text.secondary' }}>{r.message || (r.status ? '' : 'Henüz çalışmadı')}</TableCell>
                      {aiOn && (
                        <TableCell>
                          {(r.status === 'warn' || r.status === 'fail') && (
                            <Tooltip title="AI'a sor: ne anlama geliyor, nasıl düzeltilir?">
                              <IconButton size="small" aria-label={`${r.title} için AI'a sor`} onClick={() => askAi(
                                `Regresyon testindeki otomatik kontrol "${r.title}" (${r.group}) ${CHECK_PILL[r.status!].label.toLocaleUpperCase('tr-TR')} verdi.\n`
                                + `Mesaj: ${r.message}\nBu ne anlama geliyor, nedeni ne olabilir ve nasıl düzeltilir?`)}>
                                <AutoAwesomeIcon fontSize="small" sx={{ color: 'primary.main' }} />
                              </IconButton>
                            </Tooltip>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Panel>
    </Box>
  )
}

// ---------------------------------------------------------------- elle test
type Filter = 'all' | 'pending' | Result

function ManualTests({ catalog, runs, runId, onSelect, aiOn }: {
  catalog: Catalog; runs: Run[]; runId: string | null; onSelect: (id: string) => void; aiOn: boolean
}) {
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const [newOpen, setNewOpen] = useState(false)
  const [finishOpen, setFinishOpen] = useState(false)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState<string | false>(catalog.sections[0]?.key ?? false)

  const run = useQuery<Run>({
    queryKey: ['regression', 'run', runId], enabled: !!runId,
    queryFn: async () => (await api.get(`/regression/runs/${runId}`)).data,
  })
  const start = useMutation({
    mutationFn: async (title: string) => (await api.post<Run>('/regression/runs', { title })).data,
    onSuccess: (r) => { onSelect(r.id); setNewOpen(false); enqueueSnackbar('Yeni test başladı', { variant: 'success' }) },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const finish = useMutation({
    mutationFn: async () => (await api.post<Run>(`/regression/runs/${runId}/finish`)).data,
    onSuccess: () => { setFinishOpen(false); enqueueSnackbar('Test bitirildi', { variant: 'success' }) },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const mark = useMutation({
    mutationFn: async (v: { scenario: string; result: Result | null; note: string }) =>
      (await api.post<Mark>(`/regression/runs/${runId}/marks`, v)).data,
    onMutate: (v) => qc.setQueryData<Run>(['regression', 'run', runId], (old) => {
      if (!old) return old
      const marks = { ...(old.marks ?? {}) }
      if (v.result) marks[v.scenario] = { ...(marks[v.scenario] ?? { by: '', at: '' }), result: v.result, note: v.note }
      else delete marks[v.scenario]
      return { ...old, marks }
    }),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const marks = run.data?.marks ?? {}
  const finished = !!run.data?.finished_at
  const counts = useMemo(() => {
    const c = { pass: 0, fail: 0, skip: 0 }
    Object.values(marks).forEach((m) => { c[m.result] += 1 })
    return { ...c, pending: catalog.total - c.pass - c.fail - c.skip }
  }, [marks, catalog.total])
  const needle = foldText(q.trim())
  const visible = (sc: Scenario) => {
    const m = marks[sc.id]
    if (filter === 'pending' ? !!m : filter !== 'all' && m?.result !== filter) return false
    return !needle || foldText(`${sc.id} ${sc.title} ${sc.expected}`).includes(needle)
  }

  const download = () => {
    if (!run.data) return
    const rows: (string | number)[][] = []
    catalog.sections.forEach((s) => s.scenarios.forEach((sc) => {
      const m = marks[sc.id]
      rows.push([s.title, sc.sub, sc.id, sc.title, sc.expected, m ? RESULT[m.result].label : 'Bekliyor',
                 m?.note ?? '', m?.by ?? '', m?.at ? fmtDate(m.at) : ''])
    }))
    exportSheet(`regresyon-${run.data.id}.xlsx`,
      ['Bölüm', 'Alt başlık', 'No', 'Ne yapılır', 'Beklenen', 'Sonuç', 'Not', 'İşaretleyen', 'Zaman'], rows)
  }

  const newDialog = (
    <NewRunDialog open={newOpen} version={catalog.version} pending={start.isPending}
                  onClose={() => setNewOpen(false)} onStart={(t) => start.mutate(t)} />
  )
  if (!runs.length || !runId) {
    return (
      <Panel title="Elle test">
        <EmptyState title="Henüz test başlatılmadı"
                    hint="Yeni bir test başlatın; senaryoları tek tek Geçti, Kaldı ya da Atlandı diye işaretleyin. İşaretler kaydedilir, başka bir yönetici de aynı teste devam edebilir."
                    action={<Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => setNewOpen(true)}>Yeni Test Başlat</Button>} />
        {newDialog}
      </Panel>
    )
  }
  const done = catalog.total - counts.pending
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Panel title="Test" aside={
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Button size="small" startIcon={<DownloadIcon />} onClick={download} disabled={!run.data}>Excel'e İndir</Button>
          {aiOn && (
            <Button size="small" startIcon={<AutoAwesomeIcon />} disabled={!run.data} onClick={() => askAi(
              `Regresyon testi ${runId} ("${run.data?.title}") sonucunu özetle: bölüm bazında durum, kalan senaryolar ve `
              + 'olası nedenleri, otomatik kontrollerdeki sorunlar ve bir önceki testle fark.')}>AI ile Özetle</Button>
          )}
          {!finished && <Button size="small" startIcon={<FlagIcon />} onClick={() => setFinishOpen(true)}>Testi Bitir</Button>}
          <Button size="small" variant="contained" startIcon={<PlayArrowIcon />} onClick={() => setNewOpen(true)}>Yeni Test</Button>
        </Box>
      }>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField select size="small" label="Test" value={runId} onChange={(e) => onSelect(e.target.value)}
                     sx={{ minWidth: 320, maxWidth: '100%' }}>
            {runs.map((r) => (
              <MenuItem key={r.id} value={r.id}>
                {r.title} · {fmtDate(r.started_at)}{r.finished_at ? ' · bitti' : ''}
              </MenuItem>
            ))}
          </TextField>
          {run.data && (
            <Typography variant="body2" color="text.secondary">
              Başlatan {run.data.started_by} · sürüm v{run.data.version}
              {finished && ` · ${fmtDate(run.data.finished_at)} tarihinde ${run.data.finished_by} bitirdi`}
            </Typography>
          )}
        </Box>
        <Box sx={{ mt: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.75, gap: 1, flexWrap: 'wrap' }}>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <StatusPill tone="success" label={`${counts.pass} geçti`} />
              <StatusPill tone="error" label={`${counts.fail} kaldı`} />
              <StatusPill tone="default" label={`${counts.skip} atlandı`} />
              <StatusPill tone="info" label={`${counts.pending} bekliyor`} />
            </Box>
            <Typography variant="body2" sx={{ fontWeight: 650 }}>%{Math.round((done / Math.max(1, catalog.total)) * 100)} tamamlandı</Typography>
          </Box>
          <LinearProgress variant="determinate" value={(done / Math.max(1, catalog.total)) * 100}
                          sx={{ height: 8, borderRadius: 4 }} color={counts.fail ? 'warning' : 'success'} />
        </Box>
        {finished && <Alert severity="success" sx={{ mt: 2 }}>Bu test bitirildi; işaretler artık değiştirilemez. Yeni bir sürüm için "Yeni Test" ile başlayın.</Alert>}
      </Panel>

      <Alert severity="warning" variant="outlined">
        Kayıt ekleyen, değiştiren ya da mail gönderen adımları yalnız test kayıtlarıyla yapın (ör. adı TEST ile başlayan
        domain ve sertifikalar). Gerçek domainlerde açılan değişiklik taleplerini onaylamayın.
      </Alert>

      <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <SearchBox value={q} onChange={setQ} placeholder="Senaryo ara (no, adım, beklenen)" />
        <StatusTabs value={filter} onChange={(v) => setFilter(v as Filter)} items={[
          { value: 'all', label: 'Tümü', count: catalog.total },
          { value: 'pending', label: 'Bekliyor', count: counts.pending, tone: 'info' },
          { value: 'pass', label: 'Geçti', count: counts.pass, tone: 'success' },
          { value: 'fail', label: 'Kaldı', count: counts.fail, tone: 'error' },
          { value: 'skip', label: 'Atlandı', count: counts.skip },
        ]} />
      </Box>

      {run.isLoading ? <Skeleton variant="rounded" height={420} /> : (
        <Box>
          {catalog.sections.map((s) => {
            const items = s.scenarios.filter(visible)
            const filtering = !!needle || filter !== 'all'
            if (filtering && !items.length) return null
            const sm = s.scenarios.reduce((a, sc) => { const m = marks[sc.id]; if (m) a[m.result] += 1; return a },
              { pass: 0, fail: 0, skip: 0 })
            const isOpen = filtering || open === s.key
            return (
              <Accordion key={s.key} expanded={isOpen} disableGutters
                         onChange={(_, e) => setOpen(e ? s.key : false)}
                         sx={{ border: 1, borderColor: 'divider', borderRadius: '12px !important', mb: 1.25,
                               '&:before': { display: 'none' }, overflow: 'hidden' }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', width: '100%', pr: 1 }}>
                    <Typography sx={{ fontWeight: 700, flexGrow: 1 }}>{s.title}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {sm.pass + sm.fail + sm.skip}/{s.scenarios.length}
                    </Typography>
                    {sm.fail > 0 && <StatusPill size="small" tone="error" label={`${sm.fail} kaldı`} />}
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0, px: { xs: 1.5, sm: 2 } }}>
                  {s.note && <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{s.note}</Typography>}
                  {items.map((sc, i) => (
                    <Fragment key={sc.id}>
                      {sc.sub && sc.sub !== items[i - 1]?.sub && (
                        <Typography variant="overline" color="text.secondary" sx={{ display: 'block', fontWeight: 700, mt: i ? 1.5 : 0 }}>
                          {sc.sub}
                        </Typography>
                      )}
                      <ScenarioRow sc={sc} section={s.title} mark={marks[sc.id]} disabled={finished} aiOn={aiOn}
                                   onMark={(result, note) => mark.mutate({ scenario: sc.id, result, note })} />
                    </Fragment>
                  ))}
                </AccordionDetails>
              </Accordion>
            )
          })}
        </Box>
      )}
      {newDialog}
      <Dialog open={finishOpen} onClose={() => setFinishOpen(false)}>
        <DialogTitle>Test bitirilsin mi?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {counts.pass} geçti, {counts.fail} kaldı, {counts.skip} atlandı
            {counts.pending ? `, ${counts.pending} senaryo işaretlenmedi` : ''}. Bitirilen testin işaretleri değiştirilemez.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFinishOpen(false)}>Vazgeç</Button>
          <Button variant="contained" disabled={finish.isPending} onClick={() => finish.mutate()}>Testi Bitir</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

function NewRunDialog({ open, version, pending, onClose, onStart }: {
  open: boolean; version: string; pending: boolean; onClose: () => void; onStart: (title: string) => void
}) {
  const [title, setTitle] = useState('')
  useEffect(() => { if (open) setTitle(`v${version} preprod regresyon testi`) }, [open, version])
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Yeni test başlat</DialogTitle>
      <DialogContent>
        <TextField autoFocus fullWidth label="Test adı" value={title} onChange={(e) => setTitle(e.target.value)}
                   sx={{ mt: 1 }} helperText="Tüm senaryolar 'Bekliyor' olarak başlar. Önceki testler silinmez." />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Vazgeç</Button>
        <Button variant="contained" disabled={pending || !title.trim()} onClick={() => onStart(title.trim())}>Başlat</Button>
      </DialogActions>
    </Dialog>
  )
}

function ScenarioRow({ sc, section, mark, disabled, aiOn, onMark }: {
  sc: Scenario; section: string; mark?: Mark; disabled: boolean; aiOn: boolean
  onMark: (result: Result | null, note: string) => void
}) {
  const [note, setNote] = useState(mark?.note ?? '')
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  useEffect(() => { setNote(mark?.note ?? '') }, [mark?.note])
  // Not alanı yalnız "Kaldı"da, not varsa ya da "Not ekle" ile açılır (liste kısa kalsın)
  const showNote = !!mark && (mark.result === 'fail' || !!mark.note || noteOpen)
  const base = scenarioText(sc, section)
  const ai = (q: string) => { setAnchor(null); askAi(`${base}\n${q}`) }
  return (
    <Box sx={{ display: 'grid', gap: 1, py: 1.25, borderTop: 1, borderColor: 'divider',
               gridTemplateColumns: { xs: '1fr', md: 'minmax(0,1fr) auto' }, alignItems: 'start' }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          <Box component="span" sx={{ fontFamily: 'monospace', color: 'text.secondary', mr: 1 }}>{sc.id}</Box>
          {sc.title}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
          <Box component="span" sx={{ fontWeight: 600 }}>Beklenen: </Box>{sc.expected}
        </Typography>
        {showNote && mark && (
          <TextField size="small" fullWidth multiline maxRows={4} autoFocus={noteOpen && !mark.note} placeholder={mark.result === 'fail' ? 'Ne oldu? (kaldı nedeni)' : 'Not (isteğe bağlı)'}
                     value={note} disabled={disabled} onChange={(e) => setNote(e.target.value)}
                     onBlur={() => { if (note !== (mark.note ?? '')) onMark(mark.result, note) }}
                     sx={{ mt: 1 }} />
        )}
        {mark?.by && (
          <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 0.25 }}>
            {mark.by} · {fmtDate(mark.at)}
            {!showNote && !disabled && (
              <Box component="button" type="button" onClick={() => setNoteOpen(true)}
                   sx={{ ml: 1, p: 0, border: 0, bgcolor: 'transparent', color: 'primary.main', cursor: 'pointer', font: 'inherit' }}>
                Not ekle
              </Box>
            )}
          </Typography>
        )}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', justifyContent: { md: 'flex-end' } }}>
        <ToggleButtonGroup size="small" exclusive value={mark?.result ?? null} disabled={disabled}
                           onChange={(_, v: Result | null) => onMark(v, note)} aria-label={`${sc.id} sonucu`}>
          {(Object.keys(RESULT) as Result[]).map((r) => (
            <ToggleButton key={r} value={r} sx={{ textTransform: 'none', px: 1.25, py: 0.4,
              '&.Mui-selected': { color: `${RESULT[r].tone === 'default' ? 'text' : RESULT[r].tone}.${RESULT[r].tone === 'default' ? 'primary' : 'main'}`, fontWeight: 700 } }}>
              {RESULT[r].label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        {aiOn && (
          <>
            <Tooltip title="AI yardımı">
              <IconButton size="small" aria-label={`${sc.id} için AI yardımı`} onClick={(e) => setAnchor(e.currentTarget)}>
                <AutoAwesomeIcon fontSize="small" sx={{ color: 'primary.main' }} />
              </IconButton>
            </Tooltip>
            <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
              <MenuItem onClick={() => ai('Bu senaryoyu Jumbo\'da adım adım nasıl yaparım?')}>Adımı anlat</MenuItem>
              <MenuItem onClick={() => ai('Bu senaryoyu yaptım. Kayıtlara bakıp beklenen sonucun oluşup oluşmadığını kontrol eder misin?'
                + (note ? `\nNotum: ${note}` : ''))}>Sonucu kayıtlardan doğrula</MenuItem>
              <MenuItem onClick={() => ai(`Sonucu "Kaldı" olarak işaretledim. Notum: ${note || 'yok'}.\n`
                + 'Kayıtlara bakarak olası nedenleri söyler misin? Hata mı, ayar ya da veri sorunu mu?')}>Neden kaldı?</MenuItem>
            </Menu>
          </>
        )}
      </Box>
    </Box>
  )
}
