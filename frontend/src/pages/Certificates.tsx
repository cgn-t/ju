import AddIcon from '@mui/icons-material/Add'
import CloudSyncIcon from '@mui/icons-material/CloudSync'
import DeleteIcon from '@mui/icons-material/Delete'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import GridViewIcon from '@mui/icons-material/GridView'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight'
import LanguageIcon from '@mui/icons-material/Language'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutlined'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutlined'
import SearchIcon from '@mui/icons-material/Search'
import TableRowsIcon from '@mui/icons-material/TableRows'
import VisibilityIcon from '@mui/icons-material/Visibility'
import {
  Box, Button, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControlLabel, IconButton, InputAdornment, Paper, Skeleton, Switch, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup,
  Tooltip, Typography, useMediaQuery,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Certificate } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import CertificateDetailDrawer from '../components/CertificateDetailDrawer'
import CertificateImportDialog from '../components/CertificateImportDialog'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from '../components/ColumnFilters'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import SkiText from '../components/SkiText'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { daysLeftColor, daysLeftLabel, environmentColor, environmentLabel, nodeColors, sourceLabel } from '../theme'
import { exportCsv } from '../utils/csv'

const TYPE_LABEL: Record<string, string> = { root: 'R', intermediate: 'I', leaf: 'L' }
const TYPE_FULL: Record<string, string> = {
  root: 'Kök CA (Root)', intermediate: 'Ara CA (Intermediate)', leaf: 'Uç Sertifika (Leaf)',
}

// Kolon-başı (huni) filtreleri. Kaynak + Geçerlilik durum kolonları; gerisi metin.
const KNOWN_SRC = new Set(['vault', 'live', 'discovery', 'ct'])
function validityBucket(days: number | null | undefined): string {
  if (days === null || days === undefined) return 'none'
  if (days < 0) return 'expired'
  if (days <= 30) return 'expiring'
  return 'valid'
}
const SRC_OPTS = [
  { value: 'all', label: 'Tümü' },
  { value: 'manual', label: 'Manuel' },
  { value: 'vault', label: 'Vault' },
  { value: 'live', label: 'Canlı' },
  { value: 'discovery', label: 'Ağ Keşfi' },
  { value: 'ct', label: 'CT Log' },
]
const VAL_OPTS = [
  { value: 'all', label: 'Tümü' },
  { value: 'valid', label: 'Geçerli' },
  { value: 'expiring', label: 'Yaklaşan (≤30g)' },
  { value: 'expired', label: 'Süresi Dolmuş' },
  { value: 'none', label: 'Tarihsiz' },
]
const ENV_OPTS = [
  { value: 'all', label: 'Tümü' },
  { value: 'prod', label: 'Prod' },
  { value: 'test', label: 'Test' },
  { value: 'none', label: 'Belirtilmemiş' },
]
const CERT_COLS: ColDef<Certificate>[] = [
  { key: 'name', label: 'Ad', kind: 'text', get: (c) => c.name },
  { key: 'ski', label: 'SKI', kind: 'text', get: (c) => c.subject_key_identifier },
  { key: 'saniss', label: 'SAN / Issuer', kind: 'text', get: (c) => c.san || c.issuer },
  { key: 'source', label: 'Kaynak', kind: 'status', options: SRC_OPTS,
    get: (c) => (KNOWN_SRC.has(c.source ?? '') ? (c.source as string) : 'manual') },
  { key: 'environment', label: 'Ortam', kind: 'status', options: ENV_OPTS,
    get: (c) => c.environment ?? 'none' },
  { key: 'valid', label: 'Geçerlilik', kind: 'status', options: VAL_OPTS,
    get: (c) => validityBucket(c.days_left) },
]

// İşlemler VE Geçerlilik birlikte sağa sabitlenir (sticky): tablo yan kaydırma
// gerektirdiğinde "durum + aksiyon" ikilisi hep tam görünür kalır — taşma olduğunda yalnız
// ortadaki ikincil kolonlar (SKI/SAN/Kaynak/Ortam, zaten detay çekmecesinde de var) kayar.
// İki kolon birbirine bitişik sabitlendiği için Geçerlilik, İşlemler'in ALTINDA kalmaz.
// İşlemler'in genişliği buton sayısına göre değişir (admin: göz+duraklat+sil, diğer: yalnız göz).
const ACTIONS_COL_WIDTH = { admin: 128, other: 56 }
const stickyCellSx = (right: number) => ({
  position: 'sticky' as const, right,
  bgcolor: 'background.paper',
  boxShadow: right === 0 ? '-6px 0 6px -6px rgba(0,0,0,0.35)' : undefined,
  '.MuiTableRow-hover:hover &': { bgcolor: 'action.hover' },
})

interface TreeRow {
  cert: Certificate
  depth: number
}

function buildTree(certs: Certificate[]): TreeRow[] {
  const byParent = new Map<number | null, Certificate[]>()
  const ids = new Set(certs.map((c) => c.id))
  for (const cert of certs) {
    const key = cert.parent_id && ids.has(cert.parent_id) ? cert.parent_id : null
    byParent.set(key, [...(byParent.get(key) ?? []), cert])
  }
  const rows: TreeRow[] = []
  const walk = (parentId: number | null, depth: number) => {
    for (const cert of byParent.get(parentId) ?? []) {
      rows.push({ cert, depth })
      walk(cert.id, depth + 1)
    }
  }
  walk(null, 0)
  return rows
}

export default function Certificates() {
  useDocumentTitle('SSL Sertifikaları')
  const { canEdit, isAdmin } = useAuth()
  // İşlemler kolonundaki buton sayısı role göre değişir (admin: göz+duraklat+sil, diğer: yalnız
  // göz) — Geçerlilik'in sticky right ofseti bu genişliğe göre ayarlanır ki üst üste binmesin.
  const actionsColWidth = isAdmin ? ACTIONS_COL_WIDTH.admin : ACTIONS_COL_WIDTH.other
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [view, setView] = useState<'table' | 'cards'>('table')
  const [search, setSearch] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Certificate | null>(null)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [collapsedGroups, setCollapsedGroups] = useState<Set<number>>(new Set())
  const [showInactive, setShowInactive] = useState(false)
  const twoCols = useMediaQuery('(min-width:1200px)')

  const { data: certs, isLoading, isError, error, refetch } = useQuery<Certificate[]>({
    queryKey: ['certificates', search, showInactive],
    queryFn: async () => (await api.get('/certificates', {
      params: { search: search || undefined, is_active: showInactive ? undefined : true },
    })).data,
    // Filtre/arama değişince listeyi koruyup skeleton'a düşme → "Pasifleri göster" tıklamasında
    // tablo çökmez, sayfa yukarı kaymaz.
    placeholderData: keepPreviousData,
  })

  const toggleActive = useMutation({
    // Pasife alma bilgilendirme tetikler (bağlı domain SY ekiplerine); aktifleştirme sade PUT.
    mutationFn: async (cert: Certificate) => {
      if (cert.is_active) return (await api.post(`/certificates/${cert.id}/deactivate`)).data
      return (await api.put(`/certificates/${cert.id}`, { is_active: true })).data
    },
    onSuccess: (data, cert) => {
      if (!cert.is_active) {
        enqueueSnackbar('Sertifika aktifleştirildi', { variant: 'success' })
      } else if (data?.bound_domains?.length) {
        enqueueSnackbar(data.message,
                        { variant: data.mail_sent ? 'success' : 'warning', autoHideDuration: 7000 })
      } else {
        enqueueSnackbar('Sertifika pasife alındı', { variant: 'success' })
      }
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['cert-map'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/certificates/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Sertifika silindi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['cert-map'] })
      setDeleteTarget(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const vaultSync = useMutation({
    mutationFn: async () =>
      (await api.post<{ created: number; updated: number; skipped: number; errors: string[] }>(
        '/certificates/vault-sync')).data,
    onSuccess: (r) => {
      enqueueSnackbar(`Vault: ${r.created} yeni, ${r.updated} güncellendi, ${r.skipped} atlandı`,
                      { variant: r.errors.length ? 'warning' : 'success' })
      if (r.errors.length) console.warn('vault-sync hataları:', r.errors)
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['cert-map'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // Yenileme zinciri: halef adı yüklü listeden çözülür (filtre dışındaysa #id)
  const certNames = useMemo(() => new Map((certs ?? []).map((c) => [c.id, c.name])), [certs])

  const handleExport = () =>
    // DB'deki tüm sertifika kolonları (PEM gövdesi hariç) — eksiksiz dışa aktarım
    exportCsv('sertifikalar.csv',
      ['name', 'cert_type', 'serial_number', 'subject_key_identifier', 'authority_key_identifier',
       'fingerprint_sha256', 'subject', 'issuer', 'san', 'extended_key_usage',
       'valid_from', 'valid_to', 'kalan_gun', 'aktif', 'halef', 'internal', 'ortam', 'kaynak', 'vault_path',
       'auto_renew', 'satin_alan', 'olusturan', 'notlar', 'olusturulma', 'domainler'],
      (certs ?? []).map((c) => [c.name, c.cert_type, c.serial_number, c.subject_key_identifier,
                                c.authority_key_identifier, c.fingerprint_sha256, c.subject,
                                c.issuer, c.san, c.extended_key_usage, c.valid_from, c.valid_to,
                                c.days_left, c.is_active ? 'evet' : 'hayir',
                                // yenileme zinciri: yerine geçen kaydın adı (varsa)
                                c.superseded_by_id
                                  ? (certNames.get(c.superseded_by_id) ?? `#${c.superseded_by_id}`) : '',
                                c.is_internal ? 'evet' : 'hayir', environmentLabel(c.environment),
                                c.source, c.vault_path,
                                c.auto_renew ? 'evet' : 'hayir', c.purchased_by, c.creator,
                                c.notes, c.created_at,
                                c.domains.map((d) => `${d.domain}(${d.mapping_type})`).join(' ')]))

  const rows = useMemo(() => {
    if (!certs) return []
    const tree = buildTree(certs)
    const hidden = new Set<number>()
    const result: TreeRow[] = []
    for (const row of tree) {
      if (row.cert.parent_id && hidden.has(row.cert.parent_id)) {
        hidden.add(row.cert.id)
        continue
      }
      if (collapsed.has(row.cert.id)) hidden.add(row.cert.id)
      result.push(row)
    }
    return result
  }, [certs, collapsed])

  const cf = useColumnFilters(CERT_COLS)  // kolon-başı (huni) filtreleri
  // Kolon filtresi AKTİFSE ağaç yerine DÜZ eşleşen liste (hiyerarşi filtrede korunamaz); yoksa ağaç.
  const displayRows = useMemo(() =>
    cf.anyActive
      ? (certs ?? []).filter(cf.matches).map((cert) => ({ cert, depth: 0 }))
      : rows,
    [cf.values, certs, rows])

  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const hasChildren = (id: number) => certs?.some((c) => c.parent_id === id) ?? false

  // Kart görünümü için zincir gruplaması (her kök → altındaki tüm sertifikalar)
  const chainGroups = useMemo(() => {
    const tree = buildTree(certs ?? [])
    const groups: { root: TreeRow; members: TreeRow[] }[] = []
    let current: { root: TreeRow; members: TreeRow[] } | null = null
    for (const row of tree) {
      if (row.depth === 0) {
        current = { root: row, members: [row] }
        groups.push(current)
      } else if (current) {
        current.members.push(row)
      }
    }
    return groups
  }, [certs])

  const toggleGroup = (id: number) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // Panelleri tahmini yüksekliğe göre kolonlara dengeli dağıt — grid'in aksine
  // kısa panellerin altında ölü boşluk bırakmaz
  const panelColumns = useMemo(() => {
    const cols: (typeof chainGroups)[] = twoCols ? [[], []] : [[]]
    const heights = cols.map(() => 0)
    for (const g of chainGroups) {
      const open = !collapsedGroups.has(g.root.cert.id)
      const h = g.members.length === 1 ? 58 : 58 + (open ? g.members.length * 40 + 12 : 0)
      const idx = heights.indexOf(Math.min(...heights))
      cols[idx].push(g)
      heights[idx] += h + 16
    }
    return cols
  }, [chainGroups, collapsedGroups, twoCols])

  // Aktif + superseded_by = temkinli devir sürüyor; pasif + superseded_by = devir tamam
  const renewalChip = (cert: Certificate, compact = false, sx: object = {}) => {
    if (!cert.superseded_by_id) return null
    const successor = certNames.get(cert.superseded_by_id) ?? `#${cert.superseded_by_id}`
    const state = cert.is_active ? 'Devri bekliyor' : 'Yenilendi'
    return (
      <Tooltip title={cert.is_active
        ? `Temkinli devir sürüyor — canlı doğrulama halefi (${successor}) sunucuda görünce bu kayıt pasife alınır. Halefe gitmek için tıklayın.`
        : `Bu kayıt yenilendi ve PASİFE alındı — halefi: ${successor}. Gitmek için tıklayın.`}>
        <Chip size="small" color="info" variant="outlined" clickable
              label={compact ? `${state} →` : `${state} → ${successor}`}
              onClick={(e) => { e.stopPropagation(); setDetailId(cert.superseded_by_id!) }}
              // maxWidth: uzun halef CN'i tabloyu yatay taşırmasın (etiket ellipsis'lenir)
              sx={{ flexShrink: 0, maxWidth: 240, ...sx }} />
      </Tooltip>
    )
  }

  const rowActions = (cert: Certificate) => (
    <Box sx={{ display: 'inline-flex', flexWrap: 'nowrap', gap: 0.25, whiteSpace: 'nowrap' }}>
      <Tooltip title="Detay & Zincir">
        <IconButton size="small" color="info" onClick={() => setDetailId(cert.id)}>
          <VisibilityIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      {/* Aktif/pasif durumu YALNIZ admin değiştirir — SY editörleri sertifikayı pasife alamaz/aktifleştiremez */}
      {isAdmin && (
        <Tooltip title={cert.is_active ? 'Pasife Al' : 'Aktifleştir'}>
          <IconButton size="small" color={cert.is_active ? 'warning' : 'success'}
                      onClick={() => toggleActive.mutate(cert)}>
            {cert.is_active ? <PauseCircleOutlineIcon fontSize="small" /> : <PlayCircleOutlineIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      )}
      {isAdmin && (
        <Tooltip title="Sil (kalıcı)">
          <IconButton size="small" color="error" onClick={() => setDeleteTarget(cert)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  )

  const typeChip = (cert: Certificate) => (
    <Tooltip title={TYPE_FULL[cert.cert_type]}>
      <Chip size="small" label={TYPE_LABEL[cert.cert_type]} aria-label={TYPE_FULL[cert.cert_type]}
            sx={{ bgcolor: nodeColors[cert.cert_type], color: 'rgba(0,0,0,0.87)',
                  fontWeight: 700, width: 26, flexShrink: 0 }} />
    </Tooltip>
  )

  // Kart görünümü satırı: sabit kolon şablonu sayesinde SKI / tarih / domain / durum
  // tüm satırlarda aynı hizada durur. parentK = ebeveyn satırın kaç satır yukarıda olduğu.
  const chainRow = (cert: Certificate, depth: number, parentK: number) => (
    <Box key={cert.id}
         sx={{ position: 'relative', display: 'grid', alignItems: 'center', columnGap: 1,
               gridTemplateColumns: {
                 xs: 'minmax(0,1fr) 92px auto',
                 md: 'minmax(0,1fr) minmax(60px,116px) 72px 52px 92px auto',
               },
               height: 40, px: 0.5, borderRadius: 1, opacity: cert.is_active ? 1 : 0.55,
               '& .row-actions': { opacity: { xs: 1, md: 0 }, transition: 'opacity .15s' },
               '&:hover, &:focus-within': { bgcolor: 'action.hover' },
               '&:hover .row-actions, &:focus-within .row-actions': { opacity: 1 },
               '@media (hover: none)': { '& .row-actions': { opacity: 1 } } }}>
      {depth > 0 && (
        // ebeveyn satırın çipinden kesintisiz inen dirsek (kardeşlerde de kopmaz)
        <Box sx={{ position: 'absolute', left: `${(depth - 1) * 24 + 17}px`,
                   top: `${32 - 40 * parentK}px`, width: 12, height: `${40 * parentK - 12}px`,
                   borderLeft: 1, borderBottom: 1, borderColor: 'divider',
                   borderBottomLeftRadius: 6, pointerEvents: 'none' }} />
      )}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, pl: `${depth * 24}px` }}>
        {typeChip(cert)}
        <Typography variant="body2" noWrap
                    title={cert.san ? `${cert.name} — SAN: ${cert.san}` : cert.name}
                    sx={{ fontWeight: depth === 0 ? 700 : 500, minWidth: 0 }}>
          {cert.name}
        </Typography>
        {cert.environment && (
          <Chip size="small" color={environmentColor(cert.environment)} variant="outlined"
                label={environmentLabel(cert.environment)}
                sx={{ flexShrink: 0, display: { xs: 'none', sm: 'inline-flex' } }} />
        )}
        {cert.is_internal && (
          <Chip size="small" variant="outlined" label="Internal"
                sx={{ flexShrink: 0, display: { xs: 'none', sm: 'inline-flex' } }} />
        )}
        {/* Devralınmış kayıt zaten pasif: iki çip yerine tek "Yenilendi →" (ad ezilmesin) */}
        {!cert.is_active && !cert.superseded_by_id && <Chip size="small" label="Pasif" sx={{ flexShrink: 0 }} />}
        {renewalChip(cert, true)}
      </Box>
      <SkiText value={cert.subject_key_identifier}
               sx={{ display: { xs: 'none', md: 'flex' } }} />
      <Typography variant="caption" color="text.secondary" noWrap
                  sx={{ display: { xs: 'none', md: 'block' }, textAlign: 'right',
                        fontVariantNumeric: 'tabular-nums' }}>
        {cert.valid_to ? new Date(cert.valid_to).toLocaleDateString('tr-TR') : '—'}
      </Typography>
      <Box sx={{ display: { xs: 'none', md: 'flex' }, justifyContent: 'center' }}>
        {cert.domains.length > 0 && (
          <Tooltip title={cert.domains.map((d) => `${d.domain} (${d.mapping_type})`).join(', ')}>
            <Chip size="small" variant="outlined" icon={<LanguageIcon sx={{ fontSize: 13 }} />}
                  label={cert.domains.length}
                  sx={{ '& .MuiChip-label': { px: 0.75 } }} />
          </Tooltip>
        )}
      </Box>
      <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)}
            sx={{ width: '100%' }} />
      <Box className="row-actions" sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        {rowActions(cert)}
      </Box>
    </Box>
  )

  const groupPanel = (group: { root: TreeRow; members: TreeRow[] }) => {
    const rootId = group.root.cert.id
    // Tek sertifikalı grup: başlık + satır tekrarı yerine tek kompakt satır
    if (group.members.length === 1) {
      return (
        <Paper key={rootId} variant="outlined" sx={{ px: 1, py: 0.75 }}>
          {chainRow(group.root.cert, 0, 1)}
        </Paper>
      )
    }
    const open = !collapsedGroups.has(rootId)
    const domainCount = group.members.reduce((n, m) => n + m.cert.domains.length, 0)
    const days = group.members.map((m) => m.cert.days_left).filter((d): d is number => d != null)
    const worst = days.length ? Math.min(...days) : null
    return (
      <Paper key={rootId} variant="outlined" sx={{ overflow: 'hidden' }}>
        <Box onClick={() => toggleGroup(rootId)}
             sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.75,
                   cursor: 'pointer', userSelect: 'none', bgcolor: 'action.hover',
                   borderBottom: open ? 1 : 0, borderColor: 'divider' }}>
          <IconButton size="small" aria-label={open ? 'Zinciri kapat' : 'Zinciri aç'}>
            {open ? <KeyboardArrowDownIcon fontSize="small" /> : <KeyboardArrowRightIcon fontSize="small" />}
          </IconButton>
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Typography variant="subtitle2" noWrap title={group.root.cert.name}>
              {group.root.cert.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {group.members.length} sertifika · {domainCount} domain bağlantısı
            </Typography>
          </Box>
          <Tooltip title="Zincirdeki en yakın bitiş">
            <Chip size="small" variant="outlined" color={daysLeftColor(worst)}
                  label={`en kritik: ${daysLeftLabel(worst)}`} />
          </Tooltip>
        </Box>
        <Collapse in={open} timeout="auto">
          <Box sx={{ px: 1, py: 0.75 }}>
            {group.members.map(({ cert, depth }, i) => {
              let parentK = 1
              for (let j = i - 1; j >= 0; j--) {
                if (group.members[j].depth === depth - 1) { parentK = i - j; break }
              }
              return chainRow(cert, depth, parentK)
            })}
          </Box>
        </Collapse>
      </Paper>
    )
  }

  return (
    <Box>
      <PageHeader
        title="SSL Sertifikaları"
        subtitle="Sertifika envanteri, zincir hiyerarşisi ve domain bağlantıları"
        actions={
          <>
            {canEdit && (
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setImportOpen(true)}>
                Yeni Ekle
              </Button>
            )}
            {canEdit && (
              <Button variant="outlined" startIcon={<CloudSyncIcon />}
                      onClick={() => vaultSync.mutate()} disabled={vaultSync.isPending}>
                Vault'tan Senkronize Et
              </Button>
            )}
            <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
              <ToggleButton value="table"><Tooltip title="Tablo görünümü"><TableRowsIcon fontSize="small" /></Tooltip></ToggleButton>
              <ToggleButton value="cards"><Tooltip title="Kart görünümü"><GridViewIcon fontSize="small" /></Tooltip></ToggleButton>
            </ToggleButtonGroup>
          </>
        }
      />

      <Paper variant="outlined" sx={{ p: 1, mb: 2, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <TextField
          size="small" placeholder="Ara… (ad, SKI, seri no, issuer)" value={search}
          onChange={(e) => setSearch(e.target.value)} sx={{ width: { xs: '100%', sm: 340 } }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
        />
        {cf.anyActive && (
          <Chip size="small" color="primary" variant="outlined"
                label={`Kolon filtreleri (${displayRows.length})`} onDelete={cf.clearAll} />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" sx={{ color: 'text.secondary' }}
                onClick={() => view === 'table'
                  ? setCollapsed(new Set(certs?.filter((c) => c.cert_type !== 'leaf').map((c) => c.id)))
                  : setCollapsedGroups(new Set(chainGroups.filter((g) => g.members.length > 1)
                      .map((g) => g.root.cert.id)))}>
          Tümünü Kapat
        </Button>
        <Button size="small" sx={{ color: 'text.secondary' }}
                onClick={() => view === 'table' ? setCollapsed(new Set()) : setCollapsedGroups(new Set())}>
          Tümünü Aç
        </Button>
        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
        <FormControlLabel
          control={<Switch size="small" checked={showInactive}
                           onChange={(e) => setShowInactive(e.target.checked)} />}
          label={<Typography variant="body2">Pasifleri göster</Typography>} sx={{ mr: 0.5 }} />
        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
        <Tooltip title="Görünen listeyi CSV olarak indirir">
          <Button size="small" variant="outlined" color="inherit" startIcon={<FileDownloadIcon fontSize="small" />}
                  onClick={handleExport}>CSV İndir</Button>
        </Tooltip>
      </Paper>

      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <Skeleton variant="rounded" height={400} />
      ) : view === 'table' ? (
        <Paper>
          <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 760 }}>
            <TableHead>
              <TableRow>
                {CERT_COLS.map((c) => (
                  <ColHeaderCell key={c.key} def={c} cf={cf}
                                 sx={c.key === 'valid' ? stickyCellSx(actionsColWidth) : undefined} />
                ))}
                <TableCell align="right" sx={stickyCellSx(0)}>İşlemler</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {displayRows.map(({ cert, depth }) => (
                <TableRow key={cert.id} hover>
                  <TableCell>
                    {/* Sabit hizalama: girinti + kontrol yuvası + tip çipi ASLA küçülmez (flexShrink:0);
                        böylece uzun ad/ek çipler olsa da her derinlikte L/I/R aynı hizada başlar. */}
                    <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
                      {depth > 0 && <Box sx={{ width: depth * 24, flexShrink: 0 }} />}
                      <Box sx={{ width: 34, flexShrink: 0, display: 'flex', justifyContent: 'center' }}>
                        {!cf.anyActive && hasChildren(cert.id) && (
                          <IconButton size="small" onClick={() => toggle(cert.id)}>
                            {collapsed.has(cert.id) ? <KeyboardArrowRightIcon /> : <KeyboardArrowDownIcon />}
                          </IconButton>
                        )}
                      </Box>
                      <Tooltip title={TYPE_FULL[cert.cert_type]}>
                        <Chip size="small" label={TYPE_LABEL[cert.cert_type]}
                              aria-label={TYPE_FULL[cert.cert_type]}
                              sx={{ mr: 1, flexShrink: 0, bgcolor: nodeColors[cert.cert_type],
                                    color: 'rgba(0,0,0,0.87)', fontWeight: 700, width: 28 }} />
                      </Tooltip>
                      <Typography variant="body2" sx={{ fontWeight: depth === 0 ? 700 : 400, minWidth: 0 }}>
                        {cert.name}
                      </Typography>
                      {cert.is_internal && <Chip size="small" label="Internal" variant="outlined" sx={{ ml: 1, flexShrink: 0 }} />}
                      {!cert.is_active && !cert.superseded_by_id && <Chip size="small" label="Pasif" sx={{ ml: 1, flexShrink: 0 }} />}
                      {renewalChip(cert, false, { ml: 1 })}
                    </Box>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 170 }}>
                    <SkiText value={cert.subject_key_identifier} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                             title={cert.san || cert.issuer || undefined}>
                    {cert.san || cert.issuer}
                  </TableCell>
                  <TableCell>
                    <Chip size="small" variant="outlined"
                          label={sourceLabel(cert.source)} />
                  </TableCell>
                  <TableCell>
                    <Chip size="small" color={environmentColor(cert.environment)}
                          variant="outlined" label={environmentLabel(cert.environment)} />
                  </TableCell>
                  <TableCell sx={{ ...stickyCellSx(actionsColWidth), width: '1%', whiteSpace: 'nowrap' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" component="span" sx={{ color: 'text.secondary' }}>
                        {cert.valid_to ? new Date(cert.valid_to).toLocaleDateString('tr-TR') : '—'}
                      </Typography>
                      <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
                    </Box>
                  </TableCell>
                  <TableCell align="right" sx={{ ...stickyCellSx(0), whiteSpace: 'nowrap', width: '1%' }}>
                    {rowActions(cert)}
                  </TableCell>
                </TableRow>
              ))}
              {displayRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                    <Typography color="text.secondary">
                      {search || cf.anyActive ? 'Filtreyle eşleşen sertifika yok' : 'Henüz sertifika eklenmemiş — "Yeni Ekle" ile başlayın'}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          </TableContainer>
        </Paper>
      ) : chainGroups.length === 0 ? (
        <Paper sx={{ p: 6, textAlign: 'center' }}>
          <Typography color="text.secondary">
            {search ? 'Aramayla eşleşen sertifika yok' : 'Henüz sertifika eklenmemiş — "Yeni Ekle" ile başlayın'}
          </Typography>
        </Paper>
      ) : (
        // Kart görünümü — paneller yüksekliğe göre dengeli kolonlara dağıtılır (ölü boşluk yok)
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
          {panelColumns.map((col, ci) => (
            <Box key={ci} sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {col.map(groupPanel)}
            </Box>
          ))}
        </Box>
      )}

      <ColumnFilterMenu cf={cf} facetRows={certs ?? []} />

      <CertificateImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
      <CertificateDetailDrawer certId={detailId} onClose={() => setDetailId(null)}
                               onSelectCert={(id) => setDetailId(id)} />

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Sertifikayı Kalıcı Sil</DialogTitle>
        <DialogContent>
          <Typography>
            <b>{deleteTarget?.name}</b> kalıcı olarak silinecek. Alt sertifikalar silinmez,
            hiyerarşiden ayrılır.
            {deleteTarget && deleteTarget.domains.length > 0 && (
              <> Bu sertifika <b>{deleteTarget.domains.length}</b> domain eşlemesine sahip; eşlemeler de silinir.</>
            )}
            <br /><br />İz kaybını önlemek için silmek yerine <b>Pasife Al</b>mayı düşünün.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Vazgeç</Button>
          <Button color="error" variant="contained" onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}>
            Kalıcı Sil
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
