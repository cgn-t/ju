import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import SearchIcon from '@mui/icons-material/Search'
import { Autocomplete, Box, Chip, Divider, IconButton, InputAdornment, MenuItem, Paper, Select, Skeleton, Stack, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import type { Theme } from '@mui/material/styles'
import { useQuery } from '@tanstack/react-query'
import dagre from 'dagre'
import { toPng } from 'html-to-image'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  Background, Controls, MarkerType, MiniMap, Position, ReactFlowProvider, useReactFlow,
  type Edge, type Node,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { api } from '../api/client'
import type { AppUser, CertMapData, RelationshipsData, Team } from '../api/types'
import CertificateDetailDrawer from '../components/CertificateDetailDrawer'
import DomainDetailDrawer from '../components/DomainDetailDrawer'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { nodeColors } from '../theme'

const EDGE_COLORS: Record<string, string> = {
  hierarchy: '#90a4ae', server: '#ef5350', client: '#42a5f5',
  trust: '#ab47bc', serves: '#26a69a', depends: '#ff9800',
}
const NODE_W = 240
const NODE_H = 56

// Arama sonuçları düğüm türüne göre gruplanır
const NODE_TYPE_LABELS: Record<string, string> = {
  root: 'Root Sertifikalar', intermediate: 'Intermediate Sertifikalar',
  leaf: 'Leaf Sertifikalar', domain: 'Domainler', app: 'Uygulamalar',
}
const NODE_TYPE_ORDER: Record<string, number> = { root: 0, intermediate: 1, leaf: 2, domain: 3, app: 4 }

/** dagre ile soldan sağa hiyerarşik yerleşim */
function layoutWithDagre(nodeIds: string[], edges: { source: string; target: string }[]) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', ranksep: 120, nodesep: 24 })
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

/** Verilen düğümden (yönsüz) erişilebilen tüm düğümleri döner — bağlı bileşen. */
function connectedComponent(
  nodeIds: string[], edges: { source: string; target: string }[], start: string,
): Set<string> {
  const adj = new Map<string, string[]>()
  for (const id of nodeIds) adj.set(id, [])
  for (const e of edges) {
    adj.get(e.source)?.push(e.target)
    adj.get(e.target)?.push(e.source)
  }
  const seen = new Set<string>([start])
  const stack = [start]
  while (stack.length) {
    const cur = stack.pop() as string
    for (const nb of adj.get(cur) ?? []) if (!seen.has(nb)) { seen.add(nb); stack.push(nb) }
  }
  return seen
}

// Tutarlı "segmented control" görünümü: sönük bir ray + seçili butonun yükseltilmiş pill'i.
// Tek yerde tanımlanır, tüm toggle gruplarında paylaşılır (görsel tutarlılık).
const segGroupSx = (t: Theme) => ({
  bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
  border: `1px solid ${t.palette.divider}`,
  borderRadius: 2,
  p: 0.5,
  '& .MuiToggleButtonGroup-grouped': {
    border: 0,
    mx: 0.25,
    px: 1.25,
    py: 0.5,
    gap: 0.75,
    lineHeight: 1.7,
    borderRadius: '8px !important',
    textTransform: 'none',
    fontWeight: 600,
    fontSize: 13,
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
    '&.Mui-selected:hover': {
      bgcolor: t.palette.mode === 'dark' ? 'rgba(255,255,255,0.19)' : '#fff',
    },
  },
})

// Düğüm/kenar rengini gösteren küçük nokta — hem lejant hem filtre işaretçisi
function Dot({ c }: { c: string }) {
  return <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: c, display: 'inline-block', flexShrink: 0 }} />
}

// Filtre çubuğunda tek tip alan: üstte küçük büyük-harf etiket + altında kontrol (hepsi aynı hizada)
function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
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

function CertMapInner() {
  useDocumentTitle('Sertifika Haritası')
  const [connFilter, setConnFilter] = useState<string[]>(['server', 'client'])
  const [typeFilter, setTypeFilter] = useState<string[]>(['root', 'intermediate', 'leaf'])
  const [detailCertId, setDetailCertId] = useState<number | null>(null)
  const [detailDomainId, setDetailDomainId] = useState<number | null>(null)
  const [view, setView] = useState<'certs' | 'relationships'>('certs')
  const [focusId, setFocusId] = useState<string | null>(null)
  const { fitView } = useReactFlow()

  // Takım filtresi: 'all' = tüm ekipler; sayı = o SY takımının mapping'i. Harita GLOBAL'dir
  // (herkes tümünü görebilir), ama VARSAYILAN olarak kullanıcının kendi SY takımı seçilir.
  const [syFilter, setSyFilter] = useState<number | 'all'>('all')
  const syInit = useRef(false)
  const { data: me } = useQuery<AppUser>({
    queryKey: ['auth-me'], queryFn: async () => (await api.get('/auth/me')).data,
  })
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'], queryFn: async () => (await api.get('/teams')).data,
  })
  const syTeams = useMemo(() => (teams ?? []).filter((t) => t.type === 'SY'), [teams])
  // İlk yüklemede kullanıcının kendi (ilk) SY takımını varsayılan filtre yap
  useEffect(() => {
    if (syInit.current) return
    const mine = me?.sy_team_ids ?? []
    if (mine.length) { setSyFilter(mine[0]); syInit.current = true }
    else if (me) syInit.current = true  // admin/allviewer: kendi SY yok → 'all' kalır
  }, [me])
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

  const certFlow = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] }

    let visibleNodes: typeof data.nodes
    let visibleEdges: typeof data.edges
    if (focusId && data.nodes.some((n) => n.id === focusId)) {
      // Odak modu: seçilen düğüme bağlı tüm alt-grafik (tür/bağlantı filtrelerinden bağımsız)
      const comp = connectedComponent(data.nodes.map((n) => n.id), data.edges, focusId)
      visibleNodes = data.nodes.filter((n) => comp.has(n.id))
      visibleEdges = data.edges.filter((e) => comp.has(e.source) && comp.has(e.target))
    } else {
      const visibleCerts = new Set(
        data.nodes.filter((n) => n.node_type === 'domain' || typeFilter.includes(n.node_type)).map((n) => n.id),
      )
      visibleEdges = data.edges.filter(
        (e) =>
          visibleCerts.has(e.source) && visibleCerts.has(e.target) &&
          (e.edge_type === 'hierarchy' || connFilter.includes(e.edge_type)),
      )
      // Bağlantısı görünmeyen domainleri gizle
      const connectedDomains = new Set(
        visibleEdges.filter((e) => e.target.startsWith('domain-')).map((e) => e.target),
      )
      visibleNodes = data.nodes.filter((n) =>
        n.node_type === 'domain' ? connectedDomains.has(n.id) : typeFilter.includes(n.node_type))
    }

    const positions = layoutWithDagre(visibleNodes.map((n) => n.id), visibleEdges)

    const flowNodes: Node[] = visibleNodes.map((n) => {
      const expired = n.days_left !== null && n.days_left !== undefined && n.days_left < 0
      const expiring = !expired && n.days_left !== null && n.days_left !== undefined && n.days_left <= 30
      return {
        id: n.id,
        position: positions.get(n.id) ?? { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ fontSize: 11, lineHeight: 1.3 }}>
              <b>{n.label}</b>
              {n.days_left !== null && n.days_left !== undefined && (
                <div style={{ opacity: 0.85 }}>
                  {expired ? `Doldu (${Math.abs(n.days_left)}g)` : `${n.days_left}g kaldı`}
                </div>
              )}
            </div>
          ),
        },
        style: {
          background: nodeColors[n.node_type],
          color: '#fff',
          border: expired ? '2px solid #ff1744' : expiring ? '2px solid #ffd740' : 'none',
          borderRadius: 8,
          padding: 6,
          width: NODE_W,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      }
    })

    const flowEdges: Edge[] = visibleEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: e.edge_type !== 'hierarchy',
      style: { stroke: EDGE_COLORS[e.edge_type], strokeWidth: e.edge_type === 'hierarchy' ? 2 : 1.2 },
    }))

    return { nodes: flowNodes, edges: flowEdges }
  }, [data, connFilter, typeFilter, focusId])

  // İlişki görünümü — türetilmiş client↔server grafiği
  const relFlow = useMemo(() => {
    if (!relData) return { nodes: [] as Node[], edges: [] as Edge[] }
    let baseNodes = relData.nodes
    let baseEdges = relData.edges
    if (focusId && relData.nodes.some((n) => n.id === focusId)) {
      const comp = connectedComponent(relData.nodes.map((n) => n.id), relData.edges, focusId)
      baseNodes = relData.nodes.filter((n) => comp.has(n.id))
      baseEdges = relData.edges.filter((e) => comp.has(e.source) && comp.has(e.target))
    }
    const positions = layoutWithDagre(baseNodes.map((n) => n.id), baseEdges)
    const flowNodes: Node[] = baseNodes.map((n) => ({
      id: n.id,
      position: positions.get(n.id) ?? { x: 0, y: 0 },
      data: { label: <div style={{ fontSize: 11, lineHeight: 1.3 }}><b>{n.label}</b></div> },
      style: {
        background: nodeColors[n.node_type] ?? '#666', color: '#fff',
        borderRadius: 8, padding: 6, width: NODE_W,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }))
    const flowEdges: Edge[] = baseEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: e.edge_type === 'trust' || e.edge_type === 'depends',
      // trust: sertifika adı; depends: (varsa) mTLS client sertifika adı
      label: e.edge_type === 'serves' ? undefined : (e.label ?? undefined),
      labelStyle: { fontSize: 10, fill: '#9e9e9e' },
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS[e.edge_type] },
      style: {
        stroke: EDGE_COLORS[e.edge_type], strokeWidth: 1.5,
        strokeDasharray: e.edge_type === 'depends' ? '6 4' : undefined,
      },
    }))
    return { nodes: flowNodes, edges: flowEdges }
  }, [relData, focusId])

  const { nodes, edges } = view === 'certs' ? certFlow : relFlow

  // Odaklanılan düğümün adı (rozet için)
  const focusLabel = useMemo(() => {
    const src = view === 'certs' ? data?.nodes : relData?.nodes
    return src?.find((n) => n.id === focusId)?.label
  }, [focusId, view, data, relData])

  // Odak/görünüm değişince alt-grafiğe otomatik zoom
  useEffect(() => {
    const t = setTimeout(() => fitView({ duration: 500, padding: 0.2 }), 60)
    return () => clearTimeout(t)
  }, [focusId, view, nodes.length, fitView])

  const stats = useMemo(() => {
    if (!data) return { root: 0, intermediate: 0, leaf: 0, domain: 0 }
    const acc = { root: 0, intermediate: 0, leaf: 0, domain: 0 }
    for (const n of data.nodes) acc[n.node_type as keyof typeof acc] += 1
    return acc
  }, [data])

  const exportPng = async () => {
    const el = document.querySelector('.react-flow') as HTMLElement | null
    if (!el) return
    const dataUrl = await toPng(el, { backgroundColor: '#101418', pixelRatio: 2 })
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = 'sertifika-haritasi.png'
    a.click()
  }

  return (
    <Box>
      <Paper sx={{ mb: 2, overflow: 'hidden' }}>
        {/* Üst şerit — başlık, birincil görünüm anahtarı, arama ve dışa aktarma */}
        <Stack direction="row" useFlexGap sx={{ px: 2, py: 1.5, gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <Box sx={{ mr: 'auto' }}>
            <Typography variant="h6" sx={{ lineHeight: 1.2 }}>Sertifika Haritası</Typography>
            <Typography variant="caption" color="text.secondary">
              {view === 'certs' ? 'Sertifika – domain ilişki ağı' : 'Türetilmiş trusted ↔ server ilişkileri'}
            </Typography>
          </Box>
          <ToggleButtonGroup size="small" exclusive value={view} sx={segGroupSx}
                             onChange={(_, v) => { if (v) { setView(v); setFocusId(null) } }}>
            <ToggleButton value="certs">Sertifikalar</ToggleButton>
            <ToggleButton value="relationships">İlişkiler</ToggleButton>
          </ToggleButtonGroup>
          <Autocomplete
            size="small" sx={{ width: 300 }} autoHighlight blurOnSelect clearOnEscape
            options={[...((view === 'certs' ? data?.nodes : relData?.nodes) ?? [])]
              .map((n) => ({ id: n.id, label: n.label, node_type: n.node_type }))
              .sort((a, b) => (NODE_TYPE_ORDER[a.node_type] - NODE_TYPE_ORDER[b.node_type])
                              || a.label.localeCompare(b.label))}
            groupBy={(o) => NODE_TYPE_LABELS[o.node_type] ?? o.node_type}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, v) => setFocusId(v?.id ?? null)}
            renderOption={(props, option) => {
              const { key, ...rest } = props as { key?: string } & React.HTMLAttributes<HTMLLIElement>
              return (
                <Box component="li" key={key} {...rest} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Box sx={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
                             bgcolor: nodeColors[option.node_type] }} />
                  <Typography variant="body2" noWrap>{option.label}</Typography>
                </Box>
              )
            }}
            renderInput={(params) => (
              <TextField {...params} placeholder="Düğüm ara ve odakla…"
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
          <Tooltip title="PNG olarak indir">
            <IconButton onClick={exportPng}
                        sx={{ border: (t) => `1px solid ${t.palette.divider}`, borderRadius: 2 }}>
              <PhotoCameraIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>

        <Divider />

        {/* Filtre şeridi — tüm kontroller ortak taban hizasında, tek tip etiketlerle */}
        <Stack direction="row" useFlexGap
               sx={{ px: 2, py: 1.5, gap: 2.5, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <FilterField label="Takım">
            <Select size="small" value={syFilter} sx={{ minWidth: 210 }}
                    onChange={(e) => { const v = e.target.value; setSyFilter(v === 'all' ? 'all' : Number(v)); setFocusId(null) }}>
              <MenuItem value="all">Tüm ekipler</MenuItem>
              {syTeams.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
            </Select>
          </FilterField>

          {view === 'certs' && (
            <>
              <FilterField label="Bağlantı">
                <ToggleButtonGroup size="small" value={connFilter} sx={segGroupSx} onChange={(_, v) => setConnFilter(v)}>
                  <ToggleButton value="server"><Dot c={EDGE_COLORS.server} />Server</ToggleButton>
                  <ToggleButton value="client"><Dot c={EDGE_COLORS.client} />Trusted</ToggleButton>
                </ToggleButtonGroup>
              </FilterField>

              <FilterField label="Sertifika Türü">
                <ToggleButtonGroup size="small" value={typeFilter} sx={segGroupSx} onChange={(_, v) => setTypeFilter(v)}>
                  <ToggleButton value="root">
                    <Dot c={nodeColors.root} />Root<Box component="span" sx={{ opacity: 0.55, fontWeight: 700 }}>{stats.root}</Box>
                  </ToggleButton>
                  <ToggleButton value="intermediate">
                    <Dot c={nodeColors.intermediate} />Intermediate<Box component="span" sx={{ opacity: 0.55, fontWeight: 700 }}>{stats.intermediate}</Box>
                  </ToggleButton>
                  <ToggleButton value="leaf">
                    <Dot c={nodeColors.leaf} />Leaf<Box component="span" sx={{ opacity: 0.55, fontWeight: 700 }}>{stats.leaf}</Box>
                  </ToggleButton>
                </ToggleButtonGroup>
              </FilterField>
            </>
          )}

          {focusId && (
            <Chip color="primary" variant="outlined" onDelete={() => setFocusId(null)}
                  label={`Yalnızca: ${focusLabel ?? '—'}`}
                  sx={{ height: 32, maxWidth: 260, '& .MuiChip-label': { overflow: 'hidden', textOverflow: 'ellipsis' } }} />
          )}

          <Box sx={{ flexGrow: 1 }} />

          {view === 'certs' && (
            <Tooltip title="Bağlı domain sayısı — tür süzgecine takılmaz, her zaman gösterilir">
              <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', px: 1.5, height: 40,
                       borderRadius: 2, border: (t) => `1px solid ${t.palette.divider}` }}>
                <Dot c={nodeColors.domain} />
                <Typography variant="body2" sx={{ fontWeight: 600, fontSize: 13 }}>Domain</Typography>
                <Typography variant="body2" sx={{ fontWeight: 700, fontSize: 13, opacity: 0.55 }}>{stats.domain}</Typography>
              </Stack>
            </Tooltip>
          )}
        </Stack>
      </Paper>

      <Paper sx={{ height: 'calc(100vh - 260px)', minHeight: 480 }}>
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Skeleton variant="rounded" height="100%" />
        ) : (
          <ReactFlow
            nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => {
              setFocusId(node.id)  // haritayı bu düğümün bağlı alt-grafiğine indirger
              const [kind, rawId] = node.id.split('-')
              if (kind === 'cert') setDetailCertId(Number(rawId))
              else if (kind === 'domain') setDetailDomainId(Number(rawId))
              // 'app' düğümlerinin ayrı bir detayı yok
            }}
          >
            <Background color="#263238" />
            <Controls />
            <MiniMap pannable zoomable nodeColor={(n) => (n.style?.background as string) ?? '#666'} />
          </ReactFlow>
        )}
      </Paper>

      <CertificateDetailDrawer certId={detailCertId} onClose={() => setDetailCertId(null)}
                               onSelectCert={(id) => setDetailCertId(id)} />
      <DomainDetailDrawer domainId={detailDomainId} onClose={() => setDetailDomainId(null)} />
    </Box>
  )
}

export default function CertMap() {
  return (
    <ReactFlowProvider>
      <CertMapInner />
    </ReactFlowProvider>
  )
}
