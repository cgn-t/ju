import AccountTreeIcon from '@mui/icons-material/AccountTree'
import AppsIcon from '@mui/icons-material/Apps'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong'
import CloseIcon from '@mui/icons-material/Close'
import HubIcon from '@mui/icons-material/Hub'
import LanguageIcon from '@mui/icons-material/Language'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import SearchIcon from '@mui/icons-material/Search'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import WorkspacePremiumOutlinedIcon from '@mui/icons-material/WorkspacePremiumOutlined'
import {
  Autocomplete, Box, Button, Chip, Divider, IconButton, InputAdornment, MenuItem, Paper, Select,
  Skeleton, Stack, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { alpha, useTheme, type Theme } from '@mui/material/styles'
import { useQuery } from '@tanstack/react-query'
import dagre from 'dagre'
import { toPng } from 'html-to-image'
import { memo, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import ReactFlow, {
  Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Panel, Position,
  ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api/client'
import type { AppUser, CertMapData, RelationshipsData, Team } from '../api/types'
import CertificateDetailDrawer from '../components/CertificateDetailDrawer'
import DomainDetailDrawer from '../components/DomainDetailDrawer'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useUrlId, useUrlState } from '../hooks/useUrlState'
import { nodeColors } from '../theme'
import { edgeEnds, lineage, type Lineage } from '../utils/graphLineage'

const EDGE_COLORS: Record<string, string> = {
  hierarchy: '#90a4ae', server: '#ef5350', client: '#42a5f5',
  trust: '#ab47bc', serves: '#26a69a', depends: '#ff9800',
}
const EDGE_LABELS: Record<string, string> = {
  hierarchy: 'Zincir (Issuer → Subject)', server: 'Server', client: 'Trusted',
  trust: 'Trusted → Server', serves: 'Uygulama domaini', depends: 'Dış bağımlılık',
}
// Kesikli çizgiyle ayrışan bağlantı türleri (renk körlüğüne karşı ikinci ipucu)
const DASHED = new Set(['client', 'depends'])
const NODE_W = 250
const NODE_H = 62

const NODE_TYPE_NAMES: Record<string, string> = {
  root: 'Root', intermediate: 'Intermediate', leaf: 'Leaf', domain: 'Domain', app: 'Uygulama',
}
// Arama sonuçları düğüm türüne göre gruplanır
const NODE_TYPE_LABELS: Record<string, string> = {
  root: 'Root Sertifikalar', intermediate: 'Intermediate Sertifikalar',
  leaf: 'Leaf Sertifikalar', domain: 'Domainler', app: 'Uygulamalar',
}
const NODE_TYPE_ORDER: Record<string, number> = { root: 0, intermediate: 1, leaf: 2, domain: 3, app: 4 }
const NODE_ICONS: Record<string, ReactNode> = {
  root: <WorkspacePremiumOutlinedIcon sx={{ fontSize: 15 }} />,
  intermediate: <ShieldOutlinedIcon sx={{ fontSize: 15 }} />,
  leaf: <VerifiedUserOutlinedIcon sx={{ fontSize: 15 }} />,
  domain: <LanguageIcon sx={{ fontSize: 15 }} />,
  app: <AppsIcon sx={{ fontSize: 15 }} />,
}

type RawNode = CertMapData['nodes'][number]
type RawEdge = { id: string; source: string; target: string; edge_type: string; label?: string | null }
type Emphasis = 'normal' | 'active' | 'related' | 'dim'

/** Kalan gün → durum (renk + kısa metin). null = süre bilgisi yok (uygulama düğümü). */
function statusOf(days: number | null | undefined): { tone: 'error' | 'warning' | 'success'; text: string; long: string } | null {
  if (days === null || days === undefined) return null
  if (days < 0) return { tone: 'error', text: 'Doldu', long: `Süresi ${Math.abs(days)} gün önce doldu` }
  if (days <= 30) return { tone: 'warning', text: `${days} gün`, long: `Bitişine ${days} gün kaldı` }
  return { tone: 'success', text: `${days} gün`, long: `Bitişine ${days} gün kaldı` }
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('tr-TR')
}

/** dagre ile soldan sağa hiyerarşik yerleşim */
function layoutWithDagre(nodeIds: string[], edges: { source: string; target: string }[], ranksep = 110) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', ranksep, nodesep: 22 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const id of nodeIds) g.setNode(id, { width: NODE_W, height: NODE_H })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)
  const positions = new Map<string, { x: number; y: number }>()
  for (const id of nodeIds) {
    const pos = g.node(id)
    positions.set(id, { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 })
  }
  return positions
}

interface MapNodeData {
  label: string
  nodeType: string
  daysLeft?: number | null
  emphasis: Emphasis
  selected: boolean
}

/** Harita düğümü: türe göre renkli sol şerit + ikon, ad, sağda kalan gün rozeti. */
const MapNodeCard = memo(function MapNodeCard({ data }: NodeProps<MapNodeData>) {
  const theme = useTheme()
  const color = nodeColors[data.nodeType] ?? '#78909c'
  const st = statusOf(data.daysLeft)
  const dark = theme.palette.mode === 'dark'
  const toneColor = st ? theme.palette[st.tone].main : undefined
  const lit = data.emphasis === 'active' || data.selected
  return (
    <Box
      data-testid="map-node" data-emphasis={data.emphasis}
      sx={{
        width: NODE_W, height: NODE_H, boxSizing: 'border-box', display: 'flex', alignItems: 'center',
        gap: 1.25, pl: 1.5, pr: 1.25, borderRadius: '10px', position: 'relative', cursor: 'pointer',
        bgcolor: dark ? '#1f262e' : '#fff',
        border: `1px solid ${lit ? color : st?.tone === 'error' ? alpha(theme.palette.error.main, 0.7) : theme.palette.divider}`,
        boxShadow: lit
          ? `0 0 0 3px ${alpha(color, 0.35)}, 0 8px 24px ${alpha('#000', dark ? 0.5 : 0.16)}`
          : data.emphasis === 'related'
            ? `0 0 0 1px ${alpha(color, 0.6)}, 0 4px 14px ${alpha('#000', dark ? 0.4 : 0.1)}`
            : `0 1px 2px ${alpha('#000', dark ? 0.4 : 0.08)}`,
        opacity: data.emphasis === 'dim' ? 0.16 : 1,
        filter: data.emphasis === 'dim' ? 'grayscale(0.8)' : 'none',
        transform: data.emphasis === 'active' ? 'scale(1.03)' : 'none',
        transition: 'opacity .18s ease, filter .18s ease, box-shadow .18s ease, transform .18s ease',
        overflow: 'hidden',
        '&::before': { content: '""', position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, bgcolor: color },
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0, width: 1, height: 1, border: 0 }} />
      <Box sx={{ width: 30, height: 30, borderRadius: '8px', flexShrink: 0, display: 'grid', placeItems: 'center',
                 color, bgcolor: alpha(color, dark ? 0.18 : 0.12) }}>
        {NODE_ICONS[data.nodeType] ?? <HubIcon sx={{ fontSize: 15 }} />}
      </Box>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography sx={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                          color, lineHeight: 1.3 }}>
          {NODE_TYPE_NAMES[data.nodeType] ?? data.nodeType}
        </Typography>
        <Typography noWrap title={data.label}
                    sx={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.35, color: 'text.primary' }}>
          {data.label}
        </Typography>
      </Box>
      {st && (
        <Box sx={{ flexShrink: 0, px: 0.75, py: 0.25, borderRadius: 10, fontSize: 10.5, fontWeight: 700,
                   whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums',
                   color: toneColor, bgcolor: alpha(toneColor!, dark ? 0.16 : 0.1) }}>
          {st.text}
        </Box>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0, width: 1, height: 1, border: 0 }} />
    </Box>
  )
})
const NODE_TYPES = { card: MapNodeCard }

// Tutarlı "segmented control" görünümü: sönük bir ray + seçili butonun yükseltilmiş pill'i.
const segGroupSx = (t: Theme) => ({
  bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
  border: `1px solid ${t.palette.divider}`,
  borderRadius: 2,
  p: 0.5,
  '& .MuiToggleButtonGroup-grouped': {
    border: 0, mx: 0.25, px: 1.25, py: 0.5, gap: 0.75, lineHeight: 1.7,
    borderRadius: '8px !important', textTransform: 'none', fontWeight: 600, fontSize: 13,
    color: 'text.secondary',
    '&:hover': {
      bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.04)',
      color: 'text.primary',
    },
    '&.Mui-selected': {
      color: 'text.primary',
      bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.15)' : '#fff',
      boxShadow: t.palette.mode === 'dark' ? 'none' : '0 1px 2px rgba(0,0,0,0.18)',
    },
    '&.Mui-selected:hover': { bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.19)' : '#fff' },
  },
})

// Düğüm/kenar rengini gösteren küçük nokta — hem lejant hem filtre işaretçisi
function Dot({ c }: { c: string }) {
  return <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: c, display: 'inline-block', flexShrink: 0 }} />
}

// Lejantta kenar örneği: kısa çizgi (kesikli türler kesikli)
function LineSwatch({ c, dashed }: { c: string; dashed?: boolean }) {
  return (
    <Box component="svg" width={22} height={8} sx={{ flexShrink: 0 }}>
      <line x1="1" y1="4" x2="21" y2="4" stroke={c} strokeWidth="2" strokeLinecap="round"
            strokeDasharray={dashed ? '4 3' : undefined} />
    </Box>
  )
}

// Filtre çubuğunda tek tip alan: üstte küçük büyük-harf etiket + altında kontrol
function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box>
      <Typography sx={{ display: 'block', mb: 0.5, fontSize: 10, fontWeight: 700, lineHeight: 1,
                        letterSpacing: '0.07em', textTransform: 'uppercase', color: 'text.secondary' }}>
        {label}
      </Typography>
      {children}
    </Box>
  )
}

// Harita üstü yüzen kart (lejant, bilgi kartı) ortak görünümü
const floatSx = (t: Theme) => ({
  bgcolor: alpha(t.palette.background.paper, 0.94), backdropFilter: 'blur(6px)',
  border: `1px solid ${t.palette.divider}`, borderRadius: 2.5,
  boxShadow: `0 6px 24px ${alpha('#000', t.palette.mode === 'dark' ? 0.45 : 0.12)}`,
})

function Legend({ view }: { view: 'certs' | 'relationships' }) {
  const nodeKinds = view === 'certs' ? ['root', 'intermediate', 'leaf', 'domain'] : ['domain', 'app']
  const edgeKinds = view === 'certs' ? ['hierarchy', 'server', 'client'] : ['trust', 'serves', 'depends']
  const item = { alignItems: 'center', gap: 0.75 }
  const sep = <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
  return (
    <Stack direction="row" useFlexGap data-testid="map-legend"
           sx={(t) => ({ ...floatSx(t), px: 1.5, py: 0.9, gap: 1.5, alignItems: 'center', flexWrap: 'wrap', maxWidth: 'calc(100vw - 560px)' })}>
      {nodeKinds.map((k) => (
        <Stack key={k} direction="row" sx={item}>
          <Box sx={{ color: nodeColors[k], display: 'flex' }}>{NODE_ICONS[k]}</Box>
          <Typography sx={{ fontSize: 12 }}>{NODE_TYPE_NAMES[k]}</Typography>
        </Stack>
      ))}
      {sep}
      {edgeKinds.map((k) => (
        <Stack key={k} direction="row" sx={item}>
          <LineSwatch c={EDGE_COLORS[k]} dashed={DASHED.has(k)} />
          <Typography sx={{ fontSize: 12 }}>{EDGE_LABELS[k]}</Typography>
        </Stack>
      ))}
      {sep}
      <Typography sx={{ fontSize: 11.5, color: 'text.secondary' }}>
        Üzerine gelin: ilişkililer öne çıkar · Tıklayın: sabitlenir · Çift tık: detay
      </Typography>
    </Stack>
  )
}

interface InfoProps {
  node: RawNode
  lin: Lineage
  nodesById: Map<string, RawNode>
  edges: RawEdge[]
  view: 'certs' | 'relationships'
  pinned: boolean
  onOpen: () => void
  onFocus: () => void
  onClose: () => void
}

/** Seçili/üzerine gelinen düğümün özeti: zincir yolu, bağlantı sayıları, hızlı aksiyonlar. */
function InfoCard({ node, lin, nodesById, edges, view, pinned, onOpen, onFocus, onClose }: InfoProps) {
  const theme = useTheme()
  const color = nodeColors[node.node_type] ?? '#78909c'
  const st = statusOf(node.days_left)

  // Zincir yolu: hiyerarşi kenarlarında yukarı (Issuer) yürü → Root › … › bu düğüm
  const chain = useMemo(() => {
    if (view !== 'certs') return []
    const parentOf = new Map<string, string>()
    for (const e of edges) if (e.edge_type === 'hierarchy') parentOf.set(e.target, e.source)
    // Domain düğümünde zincir, bağlı (ilk) Leaf'ten başlar
    let cur: string | undefined = node.id
    if (node.node_type === 'domain') cur = edges.find((e) => e.target === node.id)?.source
    const path: RawNode[] = []
    const seen = new Set<string>()
    while (cur && !seen.has(cur)) {
      seen.add(cur)
      const n = nodesById.get(cur)
      if (n) path.unshift(n)
      cur = parentOf.get(cur)
    }
    return path
  }, [node, edges, nodesById, view])

  const count = (pred: (n: RawNode) => boolean, set: Set<string>) =>
    [...set].map((id) => nodesById.get(id)).filter((n): n is RawNode => !!n && pred(n)).length
  const facts: [string, number][] = view === 'certs'
    ? node.node_type === 'domain'
      ? [['Bağlı sertifika', edges.filter((e) => e.target === node.id).length]]
      : [
          ['Üst zincir', count((n) => n.node_type !== 'domain', lin.up)],
          ['Alt sertifika', count((n) => n.node_type !== 'domain', lin.down)],
          ['Server domain', new Set(edges.filter((e) => e.edge_type === 'server' && lin.edges.has(e.id)).map((e) => e.target)).size],
          ['Trusted domain', new Set(edges.filter((e) => e.edge_type === 'client' && lin.edges.has(e.id)).map((e) => e.target)).size],
        ]
    : [
        ['Ona bağlananlar', lin.up.size],
        ['Bağlandıkları', lin.down.size],
      ]
  const hasDetail = node.id.startsWith('cert-') || node.id.startsWith('domain-')

  return (
    <Box sx={(t) => ({ ...floatSx(t), width: 300, overflow: 'hidden' })} data-testid="map-info">
      <Box sx={{ px: 1.75, py: 1.25, display: 'flex', gap: 1.25, alignItems: 'flex-start',
                 background: `linear-gradient(135deg, ${alpha(color, 0.22)}, ${alpha(color, 0.04)})`,
                 borderBottom: `1px solid ${theme.palette.divider}` }}>
        <Box sx={{ width: 34, height: 34, borderRadius: '9px', display: 'grid', placeItems: 'center', flexShrink: 0,
                   color: '#fff', bgcolor: color }}>
          {NODE_ICONS[node.node_type]}
        </Box>
        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Typography sx={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color }}>
            {NODE_TYPE_NAMES[node.node_type] ?? node.node_type}{pinned ? ' · seçili' : ''}
          </Typography>
          <Typography sx={{ fontSize: 13.5, fontWeight: 700, wordBreak: 'break-all', lineHeight: 1.35 }}>
            {node.label}
          </Typography>
        </Box>
        {pinned && (
          <IconButton size="small" onClick={onClose} aria-label="Seçimi kaldır" sx={{ mt: -0.5, mr: -0.75 }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        )}
      </Box>

      <Box sx={{ px: 1.75, py: 1.25 }}>
        {st && (
          <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Box>
              <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>ValidTo</Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{fmtDate(node.valid_to)}</Typography>
            </Box>
            <Box sx={{ px: 1, py: 0.35, borderRadius: 10, fontSize: 11.5, fontWeight: 700,
                       color: theme.palette[st.tone].main, bgcolor: alpha(theme.palette[st.tone].main, 0.12) }}>
              {st.long}
            </Box>
          </Stack>
        )}

        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 0.75 }}>
          {facts.map(([k, v]) => (
            <Box key={k} sx={{ border: `1px solid ${theme.palette.divider}`, borderRadius: 1.5, px: 1, py: 0.6 }}>
              <Typography sx={{ fontSize: 17, fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>{v}</Typography>
              <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{k}</Typography>
            </Box>
          ))}
        </Box>

        {chain.length > 1 && (
          <Box sx={{ mt: 1.25 }}>
            <Typography sx={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                              color: 'text.secondary', mb: 0.5 }}>Zincir</Typography>
            <Stack spacing={0}>
              {chain.map((c, i) => (
                <Stack key={c.id} direction="row" spacing={1} sx={{ alignItems: 'center', position: 'relative', py: 0.3 }}>
                  <Box sx={{ width: 10, display: 'flex', justifyContent: 'center', position: 'relative', alignSelf: 'stretch' }}>
                    {i > 0 && <Box sx={{ position: 'absolute', top: 0, height: '50%', width: '1.5px', bgcolor: 'divider' }} />}
                    {i < chain.length - 1 && <Box sx={{ position: 'absolute', bottom: 0, height: '50%', width: '1.5px', bgcolor: 'divider' }} />}
                    <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: nodeColors[c.node_type], alignSelf: 'center', zIndex: 1 }} />
                  </Box>
                  <Typography noWrap title={c.label}
                              sx={{ fontSize: 12, fontWeight: c.id === node.id ? 700 : 400, minWidth: 0, flexGrow: 1 }}>
                    {c.label}
                  </Typography>
                  <Typography sx={{ fontSize: 10.5, color: 'text.secondary', flexShrink: 0 }}>
                    {NODE_TYPE_NAMES[c.node_type]}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
        )}
      </Box>

      {pinned && (
        <Stack direction="row" spacing={1} sx={{ px: 1.75, pb: 1.5 }}>
          {hasDetail && (
            <Button size="small" variant="contained" disableElevation startIcon={<OpenInNewIcon />} onClick={onOpen}>
              Detayı aç
            </Button>
          )}
          <Button size="small" variant="outlined" startIcon={<CenterFocusStrongIcon />} onClick={onFocus}>
            Yalnız bunu göster
          </Button>
        </Stack>
      )}
    </Box>
  )
}

function CertMapInner() {
  useDocumentTitle('Sertifika Haritası')
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const [connFilter, setConnFilter] = useState<string[]>(['server', 'client'])
  const [typeFilter, setTypeFilter] = useState<string[]>(['root', 'intermediate', 'leaf'])
  const [detailCertId, setDetailCertId] = useUrlId('cert')
  const [detailDomainId, setDetailDomainId] = useUrlId('domain')
  const [view, setView] = useUrlState<'certs' | 'relationships'>('view', 'certs', ['certs', 'relationships'])
  const [focusId, setFocusId] = useState<string | null>(null)
  // Vurgulama: üzerine gelinen düğüm/kenar geçici, tıklanan düğüm kalıcı (sabit) seçimdir
  const [hoverNode, setHoverNode] = useState<string | null>(null)
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { fitView } = useReactFlow()

  // Takım filtresi: 'all' = tüm ekipler; sayı = o SY takımının mapping'i. Harita GLOBAL'dir
  // (herkes tümünü görebilir), ama VARSAYILAN olarak kullanıcının kendi SY takımı seçilir.
  // SY filtresi URL'de (?sy=3 | ?sy=all). Parametre yoksa kullanıcının ilk SY takımı varsayılandır;
  // "Tümü" açıkça 'all' yazılır ki yenilemede kendi takıma geri dönmesin.
  const [syRaw, setSyRaw] = useUrlState<string>('sy', '')
  const { data: me } = useQuery<AppUser>({
    queryKey: ['auth-me'], queryFn: async () => (await api.get('/auth/me')).data,
  })
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'], queryFn: async () => (await api.get('/teams')).data,
  })
  const syTeams = useMemo(() => (teams ?? []).filter((t) => t.type === 'SY'), [teams])
  const syFilter: number | 'all' = syRaw === 'all' ? 'all'
    : /^\d+$/.test(syRaw) ? Number(syRaw) : (me?.sy_team_ids?.[0] ?? 'all')
  const setSyFilter = (v: number | 'all') => setSyRaw(String(v))
  const syParam = syFilter === 'all' ? {} : { sy_team_id: syFilter }

  const { data, isLoading, isError, error, refetch } = useQuery<CertMapData>({
    queryKey: ['cert-map', syFilter],
    queryFn: async () => (await api.get('/cert-map', { params: syParam })).data,
  })
  const { data: relData } = useQuery<RelationshipsData>({
    queryKey: ['relationships', syFilter],
    queryFn: async () => (await api.get('/relationships', { params: syParam })).data,
    enabled: view === 'relationships',
  })

  const clearSelection = useCallback(() => { setSelectedId(null); setHoverNode(null); setHoverEdge(null) }, [])

  // 1) Görünür alt-grafik (filtre + odak) — vurgulamadan bağımsız, yerleşim yalnız bu değişince hesaplanır
  const graph = useMemo<{ nodes: RawNode[]; edges: RawEdge[] }>(() => {
    const empty = { nodes: [] as RawNode[], edges: [] as RawEdge[] }
    if (view === 'certs') {
      if (!data) return empty
      if (focusId && data.nodes.some((n) => n.id === focusId)) {
        // "Yalnız bunu göster": seçilen düğümün soy hattı (üst zincir + altındakiler), üzerine
        // gelince yananların aynısı — tür/bağlantı filtrelerinden bağımsız
        const l = lineage(data.edges, focusId)
        return { nodes: data.nodes.filter((n) => l.nodes.has(n.id)), edges: data.edges.filter((e) => l.edges.has(e.id)) }
      }
      const visibleCerts = new Set(
        data.nodes.filter((n) => n.node_type === 'domain' || typeFilter.includes(n.node_type)).map((n) => n.id),
      )
      const edges = data.edges.filter(
        (e) => visibleCerts.has(e.source) && visibleCerts.has(e.target) &&
               (e.edge_type === 'hierarchy' || connFilter.includes(e.edge_type)),
      )
      // Bağlantısı görünmeyen domainleri gizle
      const connectedDomains = new Set(edges.filter((e) => e.target.startsWith('domain-')).map((e) => e.target))
      const nodes = data.nodes.filter((n) =>
        n.node_type === 'domain' ? connectedDomains.has(n.id) : typeFilter.includes(n.node_type))
      return { nodes, edges }
    }
    // İlişki görünümü — türetilmiş client↔server grafiği
    if (!relData) return empty
    if (focusId && relData.nodes.some((n) => n.id === focusId)) {
      const l = lineage(relData.edges, focusId)
      return { nodes: relData.nodes.filter((n) => l.nodes.has(n.id)), edges: relData.edges.filter((e) => l.edges.has(e.id)) }
    }
    return { nodes: relData.nodes, edges: relData.edges as RawEdge[] }
  }, [view, data, relData, connFilter, typeFilter, focusId])

  const positions = useMemo(
    // İlişkilerde kenar etiketi (sertifika adı) sığsın diye sütunlar daha açık
    () => layoutWithDagre(graph.nodes.map((n) => n.id), graph.edges, view === 'relationships' ? 190 : 110),
    [graph, view])
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph])

  // Görünümden düşen seçim temizlenir (filtre/takım değişince)
  useEffect(() => {
    if (selectedId && !nodesById.has(selectedId)) setSelectedId(null)
  }, [selectedId, nodesById])

  // 2) Vurgulama: önce üzerine gelinen kenar/düğüm, yoksa sabit seçim
  // (öncelik: üzerine gelinen düğüm > üzerine gelinen kenar > sabit seçim)
  const activeId = hoverNode ?? (hoverEdge ? null : selectedId)
  const lin = useMemo<Lineage | null>(() => {
    if (activeId && nodesById.has(activeId)) return lineage(graph.edges, activeId)
    if (hoverEdge) return edgeEnds(graph.edges, hoverEdge)
    return null
  }, [hoverEdge, activeId, graph, nodesById])

  const nodes: Node<MapNodeData>[] = useMemo(() => graph.nodes.map((n) => ({
    id: n.id,
    type: 'card',
    // 'nopan': düğüm üzerinde basılınca harita kaydırılmaya başlamasın — yoksa hızlı tıklama
    // düğüme değil boş alana düşüp seçimi temizliyordu
    className: 'nopan',
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: {
      label: n.label, nodeType: n.node_type, daysLeft: n.days_left,
      selected: n.id === selectedId,
      emphasis: !lin ? 'normal' : n.id === activeId ? 'active' : lin.nodes.has(n.id) ? 'related' : 'dim',
    },
  })), [graph, positions, lin, activeId, selectedId])

  // Vurgulanan kenarlar dizinin sonuna alınır: SVG'de en üstte çizilir. (zIndex KULLANILMAZ —
  // React Flow farklı zIndex'li kenarları ayrı katmana taşıyıp yeniden oluşturur, tıklama kaybolur.)
  const edges: Edge[] = useMemo(() => [...graph.edges].sort((a, b) =>
    Number(lin?.edges.has(a.id) ?? false) - Number(lin?.edges.has(b.id) ?? false)).map((e) => {
    const on = lin?.edges.has(e.id) ?? false
    const off = !!lin && !on
    const c = EDGE_COLORS[e.edge_type] ?? '#90a4ae'
    const arrow = view === 'relationships' || on
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      animated: on && e.edge_type !== 'hierarchy',
      // Etiket (trust: sertifika adı; depends: mTLS client sertifika adı) yalnız vurgulanınca — kalabalığı önler
      label: on && view === 'relationships' && e.edge_type !== 'serves' ? (e.label ?? undefined) : undefined,
      labelStyle: { fontSize: 10.5, fontWeight: 600, fill: dark ? '#e0e0e0' : '#37474f' },
      labelBgStyle: { fill: dark ? '#181d23' : '#fff' },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 6,
      markerEnd: arrow ? { type: MarkerType.ArrowClosed, color: c, width: 16, height: 16 } : undefined,
      style: {
        stroke: c,
        strokeWidth: on ? 2.6 : 1.4,
        strokeOpacity: off ? 0.08 : on ? 1 : 0.55,
        strokeDasharray: DASHED.has(e.edge_type) ? '6 4' : undefined,
        transition: 'stroke-opacity .18s ease, stroke-width .18s ease',
      },
    }
  }), [graph, lin, view, dark])

  // Odaklanılan düğümün adı (rozet için)
  const focusLabel = useMemo(() => {
    const src = view === 'certs' ? data?.nodes : relData?.nodes
    return src?.find((n) => n.id === focusId)?.label
  }, [focusId, view, data, relData])

  // Odak/görünüm değişince alt-grafiğe otomatik zoom
  useEffect(() => {
    const t = setTimeout(() => fitView({ duration: 500, padding: 0.2 }), 60)
    return () => clearTimeout(t)
  }, [focusId, view, graph.nodes.length, fitView])

  // Esc: seçimi temizle
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') clearSelection() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clearSelection])

  const stats = useMemo(() => {
    const acc = { root: 0, intermediate: 0, leaf: 0, domain: 0, expired: 0, expiring: 0 }
    for (const n of data?.nodes ?? []) {
      if (n.node_type in acc) acc[n.node_type as 'root'] += 1
      if (n.node_type === 'domain') continue
      const s = statusOf(n.days_left)
      if (s?.tone === 'error') acc.expired += 1
      else if (s?.tone === 'warning') acc.expiring += 1
    }
    return acc
  }, [data])

  const openDetail = (id: string) => {
    const [kind, rawId] = id.split('-')
    if (kind === 'cert') setDetailCertId(Number(rawId))
    else if (kind === 'domain') setDetailDomainId(Number(rawId))
    // 'app' düğümlerinin ayrı bir detayı yok
  }

  const exportPng = async () => {
    const el = document.querySelector('.react-flow') as HTMLElement | null
    if (!el) return
    const dataUrl = await toPng(el, { backgroundColor: theme.palette.background.paper, pixelRatio: 2 })
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = 'sertifika-haritasi.png'
    a.click()
  }

  // Bilgi kartı yalnız TIKLANIP sabitlenen düğüm için (üzerine gelince açılsaydı altındaki
  // düğümleri örtüp titremeye yol açardı)
  const infoNode = selectedId ? nodesById.get(selectedId) : undefined
  const infoLin = infoNode ? lineage(graph.edges, infoNode.id) : null

  return (
    <Box>
      <PageHeader
        title="Sertifika Haritası"
        subtitle={view === 'certs'
          ? 'Root → Intermediate → Leaf zinciri ve bağlı domainler'
          : 'Sertifikalardan türetilen Trusted → Server ilişkileri'}
        actions={(
          <>
            {view === 'certs' && (
              <Stack direction="row" spacing={1}>
                <SummaryPill c={nodeColors.domain} label="Domain" value={stats.domain}
                             hint="Bağlı domain sayısı — tür süzgecine takılmaz" />
                <SummaryPill c={theme.palette.warning.main} label="≤ 30 gün" value={stats.expiring}
                             hint="Bitişine 30 gün veya daha az kalan sertifika" />
                <SummaryPill c={theme.palette.error.main} label="Doldu" value={stats.expired}
                             hint="Süresi dolmuş ama hâlâ aktif sertifika" />
              </Stack>
            )}
            <ToggleButtonGroup size="small" exclusive value={view} sx={segGroupSx}
                               onChange={(_, v) => { if (v) { setView(v); setFocusId(null); clearSelection() } }}>
              <ToggleButton value="certs"><AccountTreeIcon sx={{ fontSize: 17 }} />Sertifikalar</ToggleButton>
              <ToggleButton value="relationships"><HubIcon sx={{ fontSize: 17 }} />İlişkiler</ToggleButton>
            </ToggleButtonGroup>
            <Tooltip title="PNG olarak indir">
              <IconButton onClick={exportPng} aria-label="PNG olarak indir"
                          sx={{ border: (t) => `1px solid ${t.palette.divider}`, borderRadius: 2 }}>
                <PhotoCameraIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </>
        )}
      />

      {/* Filtre şeridi — tüm kontroller ortak taban hizasında, tek tip etiketlerle */}
      <Paper variant="outlined" sx={{ mb: 2, px: 2, py: 1.5 }}>
        <Stack direction="row" useFlexGap sx={{ gap: 2.5, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <FilterField label="Ara">
            <Autocomplete
              size="small" sx={{ width: 300 }} autoHighlight blurOnSelect clearOnEscape
              options={graph.nodes
                .map((n) => ({ id: n.id, label: n.label, node_type: n.node_type }))
                .sort((a, b) => (NODE_TYPE_ORDER[a.node_type] - NODE_TYPE_ORDER[b.node_type])
                                || a.label.localeCompare(b.label))}
              groupBy={(o) => NODE_TYPE_LABELS[o.node_type] ?? o.node_type}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              onChange={(_, v) => {
                // Bulunan düğüm seçilir (ilişkileri yanar) ve ekran ona yaklaşır
                setSelectedId(v?.id ?? null)
                if (v) setTimeout(() => fitView({ nodes: [{ id: v.id }], duration: 500, maxZoom: 1.1, padding: 1.2 }), 30)
              }}
              renderOption={(props, option) => {
                const { key, ...rest } = props as { key?: string } & React.HTMLAttributes<HTMLLIElement>
                return (
                  <Box component="li" key={key} {...rest} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box sx={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, bgcolor: nodeColors[option.node_type] }} />
                    <Typography variant="body2" noWrap>{option.label}</Typography>
                  </Box>
                )
              }}
              renderInput={(params) => (
                <TextField {...params} placeholder="Sertifika, domain veya uygulama…"
                  slotProps={{
                    ...params.slotProps,
                    input: {
                      ...params.slotProps.input,
                      startAdornment: (
                        <>
                          <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>
                          {params.slotProps.input.startAdornment}
                        </>
                      ),
                    },
                  }} />
              )}
            />
          </FilterField>

          <FilterField label="Takım">
            <Select size="small" value={syFilter} sx={{ minWidth: 200 }}
                    onChange={(e) => { const v = e.target.value; setSyFilter(v === 'all' ? 'all' : Number(v)); setFocusId(null); clearSelection() }}>
              <MenuItem value="all">Tüm ekipler</MenuItem>
              {syTeams.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
            </Select>
          </FilterField>

          {view === 'certs' && (
            <>
              <FilterField label="Bağlantı">
                <ToggleButtonGroup size="small" value={connFilter} sx={segGroupSx} onChange={(_, v) => setConnFilter(v)}>
                  <ToggleButton value="server"><LineSwatch c={EDGE_COLORS.server} />Server</ToggleButton>
                  <ToggleButton value="client"><LineSwatch c={EDGE_COLORS.client} dashed />Trusted</ToggleButton>
                </ToggleButtonGroup>
              </FilterField>

              <FilterField label="Sertifika Türü">
                <ToggleButtonGroup size="small" value={typeFilter} sx={segGroupSx} onChange={(_, v) => setTypeFilter(v)}>
                  {(['root', 'intermediate', 'leaf'] as const).map((k) => (
                    <ToggleButton key={k} value={k}>
                      <Dot c={nodeColors[k]} />{NODE_TYPE_NAMES[k]}
                      <Box component="span" sx={{ opacity: 0.55, fontWeight: 700 }}>{stats[k]}</Box>
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              </FilterField>
            </>
          )}

        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{
        height: 'calc(100vh - 240px)', minHeight: 520, overflow: 'hidden', bgcolor: dark ? '#13181d' : '#fafbfc',
        // Yakınlaştırma düğmeleri temaya uysun (React Flow varsayılanı beyaz)
        '& .react-flow__controls': { boxShadow: 'none', border: `1px solid ${theme.palette.divider}`, borderRadius: 2, overflow: 'hidden' },
        '& .react-flow__controls-button': {
          bgcolor: 'background.paper', borderBottom: `1px solid ${theme.palette.divider}`, width: 30, height: 30,
          '& svg': { fill: theme.palette.text.secondary },
          '&:hover': { bgcolor: alpha(theme.palette.text.primary, 0.08) },
        },
      }}>
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Skeleton variant="rounded" height="100%" />
        ) : (
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={NODE_TYPES} fitView minZoom={0.1}
            proOptions={{ hideAttribution: true }} nodesDraggable={false} nodesConnectable={false}
            elementsSelectable={false} zoomOnDoubleClick={false}
            onNodeMouseEnter={(_, n) => { setHoverNode(n.id); setHoverEdge(null) }}
            onNodeMouseLeave={() => setHoverNode(null)}
            onEdgeMouseEnter={(_, e) => setHoverEdge(e.id)}
            onEdgeMouseLeave={() => setHoverEdge(null)}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onNodeDoubleClick={(_, n) => openDetail(n.id)}
            onPaneClick={clearSelection}
            onPaneMouseLeave={() => { setHoverNode(null); setHoverEdge(null) }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1.2}
                        color={dark ? 'rgba(255,255,255,0.09)' : 'rgba(0,0,0,0.13)'} />
            <Controls showInteractive={false} position="top-left" />
            <MiniMap pannable zoomable position="bottom-right"
                     style={{ background: dark ? '#181d23' : '#fff', border: `1px solid ${theme.palette.divider}`, borderRadius: 8 }}
                     maskColor={dark ? 'rgba(0,0,0,0.55)' : 'rgba(240,242,245,0.7)'}
                     nodeColor={(n) => nodeColors[(n.data as MapNodeData).nodeType] ?? '#78909c'}
                     nodeBorderRadius={4} />
            <Panel position="bottom-left"><Legend view={view} /></Panel>
            {focusId && (
              <Panel position="top-center">
                <Chip color="primary" onDelete={() => setFocusId(null)} icon={<CenterFocusStrongIcon />}
                      label={`Yalnızca: ${focusLabel ?? "—"}`}
                      sx={{ height: 32, maxWidth: 420, boxShadow: 3, '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' } }} />
              </Panel>
            )}
            {graph.nodes.length === 0 && (
              <Panel position="top-center">
                <Box sx={(t) => ({ ...floatSx(t), px: 2, py: 1.25, mt: 8 })}>
                  <Typography variant="body2" color="text.secondary">
                    {view === 'certs'
                      ? 'Bu seçimle gösterilecek sertifika yok. Takımı “Tüm ekipler” yapmayı ya da türleri açmayı deneyin.'
                      : 'Bu seçimle türetilen bir Trusted → Server ilişkisi yok.'}
                  </Typography>
                </Box>
              </Panel>
            )}
            {infoNode && infoLin && (
              <Panel position="top-right">
                <InfoCard node={infoNode} lin={infoLin} nodesById={nodesById} edges={graph.edges} view={view}
                          pinned={infoNode.id === selectedId}
                          onOpen={() => openDetail(infoNode.id)}
                          onFocus={() => { setFocusId(infoNode.id); setSelectedId(infoNode.id) }}
                          onClose={clearSelection} />
              </Panel>
            )}
          </ReactFlow>
        )}
      </Paper>

      <CertificateDetailDrawer certId={detailCertId} onClose={() => setDetailCertId(null)}
                               onSelectCert={(id) => setDetailCertId(id)} />
      <DomainDetailDrawer domainId={detailDomainId} onClose={() => setDetailDomainId(null)} />
    </Box>
  )
}

function SummaryPill({ c, label, value, hint }: { c: string; label: string; value: number; hint: string }) {
  return (
    <Tooltip title={hint}>
      <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', px: 1.25, height: 36, borderRadius: 2,
                                                   border: (t) => `1px solid ${t.palette.divider}` }}>
        <Dot c={c} />
        <Typography variant="body2" sx={{ fontWeight: 600, fontSize: 13 }}>{label}</Typography>
        <Typography variant="body2" sx={{ fontWeight: 700, fontSize: 13, opacity: 0.6, fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
      </Stack>
    </Tooltip>
  )
}

export default function CertMap() {
  return (
    <ReactFlowProvider>
      <CertMapInner />
    </ReactFlowProvider>
  )
}
