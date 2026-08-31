import AddIcon from '@mui/icons-material/Add'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import BuildIcon from '@mui/icons-material/Build'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/Delete'
import DesktopWindowsIcon from '@mui/icons-material/DesktopWindows'
import DeviceHubIcon from '@mui/icons-material/DeviceHub'
import DownloadIcon from '@mui/icons-material/Download'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import RouterIcon from '@mui/icons-material/Router'
import SaveIcon from '@mui/icons-material/Save'
import ShieldIcon from '@mui/icons-material/Shield'
import TerminalIcon from '@mui/icons-material/Terminal'
import UploadIcon from '@mui/icons-material/Upload'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, Autocomplete, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, Divider, Drawer, IconButton, List, ListItemButton, ListItemText, MenuItem, Paper,
  Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dagre from 'dagre'
import { useSnackbar } from 'notistack'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  addEdge, Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlowProvider,
  useEdgesState, useNodesState, useReactFlow,
  type Connection, type Edge, type Node, type NodeProps,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useNavigate } from 'react-router-dom'
import YAML from 'yaml'
import { api, apiErrorMessage } from '../api/client'
import type {
  Application, AppUser, DeploymentEnvKind, DeploymentFlow, DeploymentFlowSummary, DeploymentRun,
  DeploymentRunSummary, DeploymentRunTriggerType, DeploymentStepStatus, FlowEdge, FlowNode,
  FlowNodeData, FlowParamRow, JenkinsJobParameter,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { deploymentNodeColors } from '../theme'
import { formatDuration } from '../utils/duration'

const NODE_W = 220
const NODE_H = 64

const ENV_LABELS: Record<DeploymentEnvKind, string> = {
  ns: 'NetScaler', waf: 'WAF', windows: 'Windows', linux: 'Linux', custom: 'Diğer',
}

// Ortam kimliği küçük bir rozet-ikonla taşınır (bkz. DeployNodeView) — düğüm çerçevesi SADECE
// duruma ayrılsın diye (aksi halde ör. WAF'ın kırmızısı ile "Başarısız" durumunun kırmızısı
// karışıyordu, bkz. kullanıcı geri bildirimi).
const ENV_ICONS: Record<DeploymentEnvKind, typeof RouterIcon> = {
  ns: RouterIcon, waf: ShieldIcon, windows: DesktopWindowsIcon, linux: TerminalIcon, custom: DeviceHubIcon,
}

/** Jenkins job adından ortamı tahmin eder (ör. "ns-cert-deploy" → ns) — yanlış tahmin ederse
 * düğüme sonradan tıklayıp düzenleme panelinden düzeltilebilir (bkz. "Düğümü Düzenle" çekmecesi).
 * Yalnız SON yol segmentine (gerçek job adı) bakar — klasörlü job'larda ("Klasör/ns-job" gibi)
 * klasör adının içindeki tesadüfi eşleşmeler (ör. "WAF-Jobs/health-check") yanlış ortam
 * tahminine yol açmasın diye. */
function guessEnvFromJob(job: string): DeploymentEnvKind {
  const leaf = job.split('/').pop() ?? job
  const j = leaf.toLowerCase()
  if (j.includes('waf')) return 'waf'
  if (j.includes('netscaler') || /(^|[-_])ns([-_]|$)/.test(j)) return 'ns'
  if (j.includes('win')) return 'windows'
  if (j.includes('linux')) return 'linux'
  return 'custom'
}

const STATUS_META: Record<string, { label: string; color: 'success' | 'error' | 'warning' | 'info' | 'default' }> = {
  pending: { label: 'Bekliyor', color: 'default' },
  running: { label: 'Çalışıyor', color: 'info' },
  success: { label: 'Başarılı', color: 'success' },
  failed: { label: 'Başarısız', color: 'error' },
  skipped: { label: 'Atlandı', color: 'default' },
  cancelled: { label: 'İptal', color: 'warning' },
}

const STATUS_BORDER: Record<string, string> = {
  running: '#42a5f5', success: '#66bb6a', failed: '#ef5350', skipped: '#9e9e9e', cancelled: '#ffa726',
}

export function StatusChip({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { label: status, color: 'default' as const }
  if (status === 'running') {
    return <Chip size="small" color="info" icon={<CircularProgress size={12} color="inherit" />} label={m.label} />
  }
  return <Chip size="small" color={m.color} label={m.label} variant="outlined" />
}

export const TRIGGER_TYPE_LABELS: Record<DeploymentRunTriggerType, string> = {
  manual: 'Manuel', retry: 'Yeniden Dene', rerun: 'Yeniden Dağıt',
}

type DeployNodeData = FlowNodeData & { status?: DeploymentStepStatus }

/** Her düğümün ("Başlat" dahil) sağında duran, akışı ileri doğru genişletme tetikleyicisi.
 * Yalnız tasarım yetkisi olanlara gösterilir (AddNodeContext.canDesign). */
const AddNodeContext = createContext<{ onAdd: (parentId: string) => void; canDesign: boolean }>({
  onAdd: () => {}, canDesign: false,
})

function AddButton({ onClick }: { onClick: () => void }) {
  return (
    <Tooltip title="Buradan devam ettir (ardışık) veya yeni bir dal ekle (paralel)">
      <IconButton size="small" onClick={(e) => { e.stopPropagation(); onClick() }}
        sx={{
          position: 'absolute', right: -14, top: '50%', transform: 'translateY(-50%)',
          width: 26, height: 26, bgcolor: 'background.paper', border: 2, borderColor: 'primary.main',
          color: 'primary.main', zIndex: 1,
          '&:hover': { bgcolor: 'primary.main', color: '#fff' },
        }}>
        <AddIcon sx={{ fontSize: 16 }} />
      </IconButton>
    </Tooltip>
  )
}

/** Ortam kimliği (küçük renkli rozet-ikon) ile çalıştırma durumu (çerçeve rengi) AYRI görsel
 * kanallar — aksi halde ör. WAF'ın (kırmızı) ortam rengiyle "Başarısız" durum çerçevesi
 * karışabiliyordu. Gövde nötr kalır, yalnız çerçeve durumu taşır. */
function DeployNodeView({ id, data, selected }: NodeProps<DeployNodeData>) {
  const { onAdd, canDesign } = useContext(AddNodeContext)
  const theme = useTheme()
  const envColor = deploymentNodeColors[data.environment] ?? deploymentNodeColors.custom
  const EnvIcon = ENV_ICONS[data.environment] ?? ENV_ICONS.custom
  const missingJob = !data.jenkins_job?.trim()
  // Durumsuz/seçilmemiş düğümler koyu temada 'transparent' çerçeveyle gövde (paper) rengine
  // neredeyse tamamen karışıyordu (kullanıcı geri bildirimi: "çok adımlı akışlarda adımlar
  // belirgin değil") — nötr ama görünür bir çerçeve HER ZAMAN çizilir.
  const idleBorder = theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.28)' : 'rgba(0,0,0,0.22)'
  const borderColor = data.status ? (STATUS_BORDER[data.status] ?? idleBorder)
    : selected ? '#1976d2' : missingJob ? '#ffa726' : idleBorder
  return (
    <Box sx={{ position: 'relative' }}>
      <Box sx={{
        minWidth: NODE_W, borderRadius: 2, overflow: 'hidden', boxShadow: selected ? 4 : 1,
        bgcolor: 'background.paper', border: `2px solid ${borderColor}`,
      }}>
        <Handle type="target" position={Position.Left} />
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', px: 1.25, py: 0.75 }}>
          <Tooltip title={ENV_LABELS[data.environment] ?? ENV_LABELS.custom}>
            <Box sx={{
              width: 24, height: 24, borderRadius: '50%', bgcolor: envColor, color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <EnvIcon sx={{ fontSize: 14 }} />
            </Box>
          </Tooltip>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="body2" sx={{ fontWeight: 700, fontSize: 12.5 }} noWrap>{data.label}</Typography>
            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
              {missingJob && (
                <Tooltip title="Jenkins job seçilmedi — bu düğüm çalıştırıldığında başarısız olur">
                  <WarningAmberIcon sx={{ fontSize: 14, color: '#ffca28', flexShrink: 0 }} />
                </Tooltip>
              )}
              <Typography variant="caption" color="text.secondary" noWrap>
                {data.jenkins_job || 'job seçilmedi'}
              </Typography>
            </Stack>
          </Box>
        </Stack>
        {data.status && (
          <Box sx={{ px: 1, py: 0.5, borderTop: 1, borderColor: 'divider', display: 'flex', justifyContent: 'center' }}>
            <StatusChip status={data.status} />
          </Box>
        )}
        <Handle type="source" position={Position.Right} />
      </Box>
      {canDesign && <AddButton onClick={() => onAdd(id)} />}
    </Box>
  )
}

/** "Başlat" çapası — silinemez/eklenemez, YAML'a/tanıma hiç yazılmaz (salt görsel + tetikleyici).
 * O an gelen oku olmayan (kök) düğümlere otomatik ok çizilir; sağındaki + ile İLK düğüm eklenir. */
function StartNodeView() {
  const { onAdd, canDesign } = useContext(AddNodeContext)
  return (
    <Box sx={{ position: 'relative' }}>
      <Box sx={{
        minWidth: 92, borderRadius: 999, px: 1.75, py: 0.9, textAlign: 'center',
        bgcolor: 'success.main', color: '#fff', fontWeight: 700, fontSize: 12.5, boxShadow: 1,
      }}>
        Başlat
        <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      </Box>
      {canDesign && <AddButton onClick={() => onAdd(START_ID)} />}
    </Box>
  )
}

const START_ID = '__start__'
const NODE_TYPES = { deploy: DeployNodeView, start: StartNodeView }

function layoutWithDagre(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', ranksep: 100, nodesep: 40 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)
  return nodes.map((n) => {
    const pos = g.node(n.id)
    return pos ? { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } } : n
  })
}

// Türkçe karakterleri harf-harf karşılığına çevirir — id'ler ASCII slug olsun diye.
const TR_TRANSLIT: Record<string, string> = {
  ç: 'c', Ç: 'c', ğ: 'g', Ğ: 'g', ı: 'i', I: 'i', İ: 'i', ö: 'o', Ö: 'o', ş: 's', Ş: 's', ü: 'u', Ü: 'u',
}
function slugify(label: string): string {
  const translit = label.replace(/[çÇğĞıIİöÖşŞüÜ]/g, (ch) => TR_TRANSLIT[ch] ?? ch)
  const slug = translit.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return slug || 'dugum'
}

/** Etiketten okunaklı bir id türetir (ör. "NetScaler" → "netscaler"), akış içinde çakışırsa
 * "-2", "-3" ekler. Id düğüm OLUŞTURULDUĞUNDA bir kere üretilir — sonradan etiket değişse
 * bile SABİT kalır (kenarlar ve geçmiş çalıştırma kayıtları bu id'ye bağlı). */
function uniqueNodeId(label: string, existingIds: Iterable<string>): string {
  const taken = new Set(existingIds)
  const base = slugify(label)
  if (!taken.has(base)) return base
  let n = 2
  while (taken.has(`${base}-${n}`)) n += 1
  return `${base}-${n}`
}

function toRFNode(n: FlowNode): Node<DeployNodeData> {
  return { id: n.id, type: 'deploy', position: n.position, data: { ...n.data } }
}
function toRFEdge(e: FlowEdge): Edge {
  // stil/markerEnd BİLEREK verilmiyor — <ReactFlow defaultEdgeOptions> tema-duyarlı (koyu/açık)
  // tek merkezden uygular; burada sabitlenirse tema değişince güncellenmez.
  return { id: e.id, source: e.source, target: e.target }
}

function emptyParamRow(): FlowParamRow { return { key: '', value: '' } }

function ParamRows({ params, onChange, disabled }: {
  params: FlowParamRow[]; onChange: (params: FlowParamRow[]) => void; disabled?: boolean
}) {
  return (
    <Stack spacing={1}>
      {params.map((row, i) => (
        <Stack key={i} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <TextField size="small" label="Anahtar" value={row.key} disabled={disabled}
                    onChange={(e) => onChange(params.map((r, j) => (j === i ? { ...r, key: e.target.value } : r)))}
                    sx={{ flex: 1 }} />
          <TextField size="small" label="Değer" value={row.value} disabled={disabled}
                    onChange={(e) => onChange(params.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))}
                    sx={{ flex: 1 }} />
          {!disabled && (
            <IconButton size="small" aria-label="Sil" onClick={() => onChange(params.filter((_, j) => j !== i))}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          )}
        </Stack>
      ))}
      {!disabled && (
        <Box>
          <Button size="small" startIcon={<AddIcon />} onClick={() => onChange([...params, emptyParamRow()])}>
            Parametre ekle
          </Button>
        </Box>
      )}
    </Stack>
  )
}

function DeploymentsInner() {
  useDocumentTitle('Dağıtım')
  const { isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const { fitView } = useReactFlow()
  const navigate = useNavigate()
  const theme = useTheme()
  // Koyu temada varsayılan react-flow kenar rengi (#b1b1b7) gövde/kanvas rengine çok yakın
  // kalıp adımlar arası bağlantıyı belirsizleştiriyordu — tema-duyarlı, daha belirgin bir ton.
  const edgeColor = theme.palette.mode === 'dark' ? '#8a97ab' : '#78909c'

  const { data: me } = useQuery<AppUser>({
    queryKey: ['auth-me'], queryFn: async () => (await api.get('/auth/me')).data,
  })
  const { data: apps } = useQuery<Application[]>({
    queryKey: ['applications-lite'],
    queryFn: async () => (await api.get('/applications')).data,
  })

  const [selectedAppId, setSelectedAppId] = useState<number | null>(null)
  useEffect(() => {
    if (selectedAppId === null && apps && apps.length > 0) setSelectedAppId(apps[0].id)
  }, [apps, selectedAppId])
  const selectedApp = useMemo(() => apps?.find((a) => a.id === selectedAppId) ?? null, [apps, selectedAppId])

  const canDesign = isAdmin || (!!selectedApp?.sy_team_id && !!me?.sy_team_ids?.includes(selectedApp.sy_team_id))

  const { data: flows } = useQuery<DeploymentFlowSummary[]>({
    queryKey: ['deployment-flows', selectedAppId],
    queryFn: async () => (await api.get('/deployments/flows', { params: { app_id: selectedAppId } })).data,
    enabled: !!selectedAppId,
  })

  const [selectedFlowId, setSelectedFlowId] = useState<number | null>(null)
  const [isDraft, setIsDraft] = useState(false)  // henüz kaydedilmemiş yeni akış
  useEffect(() => { setSelectedFlowId(null); setIsDraft(false) }, [selectedAppId])

  const { data: flowDetail } = useQuery<DeploymentFlow>({
    queryKey: ['deployment-flow', selectedFlowId],
    queryFn: async () => (await api.get(`/deployments/flows/${selectedFlowId}`)).data,
    enabled: !!selectedFlowId,
  })

  const [flowName, setFlowName] = useState('')
  const [flowDescription, setFlowDescription] = useState('')
  const [nodes, setNodes, onNodesChange] = useNodesState<DeployNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  // Seçili akış değişince (farklı bir flow açıldığında) canvas'ı yükle — aynı flow'un arka plan
  // yenilemelerinde (refetch) kullanıcının sürmekte olan düzenlemesini EZMEMEK için id'ye bağlı.
  useEffect(() => {
    if (!flowDetail) return
    setFlowName(flowDetail.name)
    setFlowDescription(flowDetail.description ?? '')
    setNodes(flowDetail.definition.nodes.map(toRFNode))
    setEdges(flowDetail.definition.edges.map(toRFEdge))
    setSelectedNodeId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowDetail?.id])

  const startDraft = () => {
    setSelectedFlowId(null)
    setIsDraft(true)
    setFlowName('Yeni Akış')
    setFlowDescription('')
    setNodes([])
    setEdges([])
    setSelectedNodeId(null)
  }

  const autoLayout = () => setNodes((ns) => layoutWithDagre(ns, edges))

  // Salt-okur modda bile ÖLÇÜM (dimensions) değişiklikleri her zaman uygulanmalı — aksi halde
  // ReactFlow düğümü ölçemediği için visibility:hidden'da kilitli kalır (bkz. displayNodes notu).
  // Sürükleme/silme zaten nodesDraggable/elementsSelectable=false ile ayrıca engelleniyor.
  const handleNodesChange: typeof onNodesChange = (changes) =>
    onNodesChange(canDesign ? changes : changes.filter((c) => c.type === 'dimensions'))

  const onConnect = (c: Connection) =>
    setEdges((es) => addEdge({ ...c, id: `e-${c.source}-${c.target}-${Date.now()}` }, es))

  // Salt görsel "Başlat" çapası + o an kök olan düğümlere otomatik ok — kaydedilen tanıma
  // (buildDefinition/YAML) HİÇ karışmaz, yalnız <ReactFlow> öğesine gösterim için beslenir.
  const rootIds = useMemo(() => {
    const withIncoming = new Set(edges.map((e) => e.target))
    return nodes.filter((n) => !withIncoming.has(n.id)).map((n) => n.id)
  }, [nodes, edges])

  const displayNodes = useMemo(() => {
    const rootYs = nodes.filter((n) => rootIds.includes(n.id)).map((n) => n.position.y)
    const minX = nodes.length ? Math.min(...nodes.map((n) => n.position.x)) : 0
    const avgY = rootYs.length ? rootYs.reduce((a, b) => a + b, 0) / rootYs.length : 0
    const startNode: Node = {
      id: START_ID, type: 'start', position: { x: minX - 160, y: avgY + NODE_H / 2 - 18 },
      draggable: false, selectable: false, connectable: false, data: {},
      // Sabit boyut ZORUNLU: bu düğüm gerçek `nodes` state'inde YOK, onNodesChange üzerinden
      // ölçüm bilgisini geri yazamaz → width/height verilmezse ReactFlow "ölçülene kadar gizle"
      // durumunda kalıp düğümü SONSUZA DEK visibility:hidden bırakır.
      width: 110, height: 44,
    }
    return [startNode, ...nodes]
  }, [nodes, rootIds])

  const displayEdges = useMemo(() => {
    const startEdges: Edge[] = rootIds.map((id) => ({
      id: `start-${id}`, source: START_ID, target: id, selectable: false,
      style: { stroke: '#66bb6a', strokeWidth: 1.5, strokeDasharray: '4 3' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#66bb6a' },
    }))
    return [...startEdges, ...edges]
  }, [edges, rootIds])

  // fitView `fitView` prop'uyla YALNIZ ilk mount'ta çalışır — düğüm eklendikçe/akış değiştikçe
  // grafik dagre ile yeniden konumlanır ama görünüm eski pan/zoom'da kalır, yeni düğümler
  // kadraj dışına taşar. Yapısal her değişiklikte imperatif olarak yeniden odakla.
  useEffect(() => {
    const t = setTimeout(() => fitView({ duration: 300, padding: 0.25 }), 60)
    return () => clearTimeout(t)
  }, [nodes.length, edges.length, selectedFlowId, isDraft, fitView])

  // Dağıt'a basmadan önce doğrulama: job'u seçilmemiş düğüm ASLA başarılı olamaz (jenkins_client
  // "Job adı boş" ile hemen döner) — bunu Başarısız görene kadar beklemek yerine baştan engelle.
  const missingJobNodeIds = useMemo(() => nodes.filter((n) => !n.data.jenkins_job?.trim()).map((n) => n.id),
                                     [nodes])
  const canRun = missingJobNodeIds.length === 0

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedNodeId) ?? null, [nodes, selectedNodeId])

  const patchSelectedNode = (patch: Partial<DeployNodeData>) => {
    if (!selectedNodeId) return
    setNodes((ns) => ns.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...patch } } : n)))
  }

  const removeSelectedNode = () => {
    if (!selectedNodeId) return
    setNodes((ns) => ns.filter((n) => n.id !== selectedNodeId))
    setEdges((es) => es.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId))
    setSelectedNodeId(null)
  }

  // ---- Rehberli düğüm ekleme: her düğümün ("Başlat" dahil) + tuşuyla açılır ----
  // Akış: 1) kaynak seç (şimdilik yalnız Jenkins) 2) Jenkins job'u listeden seç
  // 3) job'un parametreleri otomatik gelir, uygulamaya özel değerler doldurulup Ekle'ye basılır.
  const [addOpen, setAddOpen] = useState(false)
  const [addParentId, setAddParentId] = useState<string | null>(null)
  const [addStep, setAddStep] = useState<'pick-source' | 'pick-job' | 'fill-form'>('pick-source')
  const [addJobSearch, setAddJobSearch] = useState('')
  const [addEnv, setAddEnv] = useState<DeploymentEnvKind | null>(null)
  const [addLabel, setAddLabel] = useState('')
  const [addJob, setAddJob] = useState('')
  const [addParams, setAddParams] = useState<FlowParamRow[]>([])

  const openAddDialogFor = useCallback((parentId: string) => {
    setAddParentId(parentId)
    setAddStep('pick-source')
    setAddJobSearch('')
    setAddEnv(null)
    setAddLabel('')
    setAddJob('')
    setAddParams([])
    setAddOpen(true)
  }, [])

  const { data: jenkinsJobsData, isFetching: jenkinsJobsLoading } = useQuery<{ jobs: string[] }>({
    queryKey: ['jenkins-jobs'],
    queryFn: async () => (await api.get('/jenkins/jobs')).data,
    enabled: addOpen && addStep === 'pick-job',
  })
  const jenkinsJobs = jenkinsJobsData?.jobs ?? []
  const filteredJenkinsJobs = jenkinsJobs.filter((j) => j.toLowerCase().includes(addJobSearch.toLowerCase()))

  const { data: jobParamsData, isFetching: jobParamsLoading } = useQuery<{ parameters: JenkinsJobParameter[] }>({
    queryKey: ['jenkins-job-parameters', addJob],
    // Klasörlü job adları ("Klasör/Alt/job") "/" ile ayrılır — backend {job:path} bunu bekler,
    // encodeURIComponent burada YANLIŞ olurdu (%2F, path converter'ı kırar).
    queryFn: async () => (await api.get(`/jenkins/job/${addJob}/parameters`)).data,
    enabled: addOpen && addStep === 'fill-form' && !!addJob,
    staleTime: Infinity,  // arka plan yenilemesi kullanıcının doldurduğu satırları EZMESİN
  })

  // job seçildiğinde parametreler gelince satırları bir kere doldur (kullanıcı sonra düzenleyebilir)
  useEffect(() => {
    if (jobParamsData) {
      setAddParams(jobParamsData.parameters.map((p) => ({ key: p.name, value: p.default ?? '' })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobParamsData])

  const pickAddJob = (job: string) => {
    const env = guessEnvFromJob(job)
    setAddJob(job)
    setAddEnv(env)
    setAddLabel(env !== 'custom' ? ENV_LABELS[env] : job)
    setAddParams([])
    setAddStep('fill-form')
  }

  const confirmAddNode = () => {
    if (!addEnv || !addParentId) return
    const label = addLabel.trim() || ENV_LABELS[addEnv]
    const id = uniqueNodeId(label, nodes.map((n) => n.id))
    const newNode: Node<DeployNodeData> = {
      id, type: 'deploy', position: { x: 0, y: 0 },
      data: { label, jenkins_job: addJob, environment: addEnv, params: addParams },
    }
    const newEdges = addParentId === START_ID ? edges : [
      ...edges,
      { id: `e-${addParentId}-${id}-${Date.now()}`, source: addParentId, target: id },
    ]
    setEdges(newEdges)
    setNodes(layoutWithDagre([...nodes, newNode], newEdges))
    setAddOpen(false)
  }

  const addNodeCtx = useMemo(() => ({ onAdd: openAddDialogFor, canDesign }), [openAddDialogFor, canDesign])

  const buildDefinition = () => ({
    nodes: nodes.map((n) => ({
      id: n.id, position: n.position,
      data: { label: n.data.label, jenkins_job: n.data.jenkins_job, environment: n.data.environment,
              params: n.data.params },
    })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      const definition = buildDefinition()
      if (isDraft || !selectedFlowId) {
        if (!selectedAppId) throw new Error('Önce bir uygulama seçin')
        return (await api.post('/deployments/flows', {
          app_id: selectedAppId, name: flowName, description: flowDescription || null, definition,
        })).data as DeploymentFlow
      }
      return (await api.put(`/deployments/flows/${selectedFlowId}`, {
        name: flowName, description: flowDescription || null, definition,
      })).data as DeploymentFlow
    },
    onSuccess: (saved) => {
      enqueueSnackbar('Akış kaydedildi', { variant: 'success' })
      setIsDraft(false)
      setSelectedFlowId(saved.id)
      qc.invalidateQueries({ queryKey: ['deployment-flows', selectedAppId] })
      qc.invalidateQueries({ queryKey: ['deployment-flow', saved.id] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const [deleteTarget, setDeleteTarget] = useState<DeploymentFlowSummary | null>(null)
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/deployments/flows/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Akış silindi', { variant: 'success' })
      setDeleteTarget(null)
      if (selectedFlowId === deleteTarget?.id) { setSelectedFlowId(null); setIsDraft(false) }
      qc.invalidateQueries({ queryKey: ['deployment-flows', selectedAppId] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // ---- Akışı başka bir uygulamaya kopyala (YAML kopyala-yapıştıra tek-tık kısayol) ----
  const [copySource, setCopySource] = useState<DeploymentFlowSummary | null>(null)
  const [copyTargetAppId, setCopyTargetAppId] = useState<number | null>(null)
  const [copyName, setCopyName] = useState('')

  const openCopyDialogFor = (f: DeploymentFlowSummary) => {
    setCopySource(f)
    setCopyTargetAppId(null)
    setCopyName(`${f.name} (kopya)`)
  }

  const copyFlowMutation = useMutation({
    mutationFn: async () => {
      if (!copySource || !copyTargetAppId) throw new Error('Hedef uygulama seçin')
      const full = (await api.get(`/deployments/flows/${copySource.id}`)).data as DeploymentFlow
      return (await api.post('/deployments/flows', {
        app_id: copyTargetAppId, name: copyName.trim() || `${full.name} (kopya)`,
        description: full.description, definition: full.definition,
      })).data as DeploymentFlow
    },
    onSuccess: (created) => {
      enqueueSnackbar(`Akış "${created.app_name}" uygulamasına kopyalandı`, { variant: 'success' })
      setCopySource(null)
      qc.invalidateQueries({ queryKey: ['deployment-flows', created.app_id] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // ---- Çalıştırma (run) ----
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [runSearch, setRunSearch] = useState('')
  const [debouncedRunSearch, setDebouncedRunSearch] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedRunSearch(runSearch.trim()), 300)
    return () => clearTimeout(t)
  }, [runSearch])
  const { data: runs } = useQuery<DeploymentRunSummary[]>({
    queryKey: ['deployment-runs', selectedAppId, debouncedRunSearch],
    queryFn: async () => (await api.get('/deployments/runs', {
      params: { app_id: selectedAppId, q: debouncedRunSearch || undefined },
    })).data,
    enabled: !!selectedAppId,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 3000 : false),
  })

  // Bu akış için hâlâ devam eden bir run varsa "Dağıt" devre dışı — aksi halde çift tetikleme
  // riski olur (backend da aynı kuralı 409 ile uygular, bu yalnız UI'da erken engelleme).
  const activeRunForFlow = runs?.find((r) => r.flow_id === selectedFlowId
    && (r.status === 'pending' || r.status === 'running'))

  const { data: runDetail } = useQuery<DeploymentRun>({
    queryKey: ['deployment-run', selectedRunId],
    queryFn: async () => (await api.get(`/deployments/runs/${selectedRunId}`)).data,
    enabled: !!selectedRunId,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : false),
  })

  // Aktif run'ın adım durumları canvas'a yansısın (düğüm üstünde canlı rozet)
  useEffect(() => {
    if (!runDetail || runDetail.flow_id !== selectedFlowId) return
    const byNode = new Map(runDetail.steps.map((s) => [s.node_id, s.status]))
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, status: byNode.get(n.id) } })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runDetail])

  const runMutation = useMutation({
    mutationFn: async () => (await api.post(`/deployments/flows/${selectedFlowId}/run`)).data as DeploymentRun,
    onSuccess: (run) => {
      enqueueSnackbar('Dağıtım başlatıldı', { variant: 'success' })
      setSelectedRunId(run.id)
      qc.invalidateQueries({ queryKey: ['deployment-runs', selectedAppId] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // ---- YAML dışa/içe aktarım ----
  const [yamlOpen, setYamlOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importTargetAppId, setImportTargetAppId] = useState<number | null>(null)

  const yamlText = useMemo(() => {
    if (!yamlOpen) return ''
    return YAML.stringify({ name: flowName, description: flowDescription || undefined, ...buildDefinition() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [yamlOpen])

  const doImport = () => {
    try {
      const parsed = YAML.parse(importText) as { name?: string; description?: string
                                                   nodes?: FlowNode[]; edges?: FlowEdge[] }
      if (!Array.isArray(parsed?.nodes)) throw new Error('YAML içinde "nodes" listesi bulunamadı')
      const targetAppId = importTargetAppId ?? selectedAppId
      if (targetAppId !== selectedAppId) setSelectedAppId(targetAppId)
      setSelectedFlowId(null)
      setIsDraft(true)
      setFlowName(parsed.name ? `${parsed.name} (kopya)` : 'İçe Aktarılan Akış')
      setFlowDescription(parsed.description ?? '')
      setNodes(parsed.nodes.map(toRFNode))
      setEdges((parsed.edges ?? []).map(toRFEdge))
      setImportOpen(false)
      setImportText('')
      enqueueSnackbar('YAML içe aktarıldı — gözden geçirip Kaydet\'e basın', { variant: 'info' })
    } catch (e) {
      enqueueSnackbar(e instanceof Error ? e.message : 'YAML ayrıştırılamadı', { variant: 'error' })
    }
  }

  const copyYaml = async () => {
    await navigator.clipboard.writeText(yamlText)
    enqueueSnackbar('YAML panoya kopyalandı', { variant: 'success' })
  }

  const hasFlow = isDraft || !!selectedFlowId

  return (
    <Box>
      <PageHeader title="Dağıtım"
        subtitle="Solda uygulama ve akış seçin; 'Başlat'ın yanındaki + ile ilk düğümü, her düğümün yanındaki + ile ardışık veya paralel devamını ekleyin." />

      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
        {/* Sol panel — uygulama + akış listesi, TAM YÜKSEKLİKTE ve belirgin */}
        <Paper sx={{ width: 300, flexShrink: 0, p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Autocomplete
            options={apps ?? []} value={selectedApp}
            getOptionLabel={(a) => a.app_name}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, v) => setSelectedAppId(v?.id ?? null)}
            renderInput={(p) => <TextField {...p} label="Uygulama" size="small" />}
          />
          <Divider />
          <Box>
            <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, letterSpacing: '0.06em' }}>
              Akışlar
            </Typography>
            <List dense disablePadding sx={{ mt: 0.5 }}>
              {(flows ?? []).map((f) => (
                <ListItemButton key={f.id} selected={!isDraft && selectedFlowId === f.id}
                               sx={{ borderRadius: 1.5, mb: 0.5, pr: canDesign ? 8 : 5 }}
                               onClick={() => { setIsDraft(false); setSelectedFlowId(f.id) }}>
                  <ListItemText primary={f.name}
                               slotProps={{ primary: { noWrap: true, sx: { fontSize: 13.5, fontWeight: 600 } } }} />
                  <Tooltip title="Başka bir uygulamaya kopyala">
                    <IconButton size="small" aria-label="Kopyala"
                               sx={{ position: 'absolute', right: canDesign ? 36 : 4 }}
                               onClick={(e) => { e.stopPropagation(); openCopyDialogFor(f) }}>
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  {canDesign && (
                    <IconButton size="small" aria-label="Sil"
                               sx={{ position: 'absolute', right: 4 }}
                               onClick={(e) => { e.stopPropagation(); setDeleteTarget(f) }}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  )}
                </ListItemButton>
              ))}
              {(flows ?? []).length === 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                  Bu uygulamada henüz akış yok.
                </Typography>
              )}
            </List>
          </Box>
          {canDesign && (
            <Button fullWidth variant="outlined" startIcon={<AddIcon />} onClick={startDraft}>Yeni Akış</Button>
          )}
          <Button fullWidth size="small" startIcon={<UploadIcon />}
                 onClick={() => { setImportTargetAppId(selectedAppId); setImportOpen(true) }}>
            YAML İçe Aktar
          </Button>
        </Paper>

        {/* Sağ içerik — editör + çalıştırma geçmişi */}
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          {!selectedAppId ? (
            <Alert severity="info">Bir uygulama seçin veya önce Uygulamalar sayfasından bir uygulama oluşturun.</Alert>
          ) : (
            <Stack spacing={2}>
              {!hasFlow ? (
                <Alert severity="info">
                  Sol taraftan bir akış seçin ya da <b>"Yeni Akış"</b> ile boş bir akıştan başlayın.
                </Alert>
              ) : (
                <AddNodeContext.Provider value={addNodeCtx}>
                  <Paper sx={{ p: 2 }}>
                    <Stack direction="row" useFlexGap sx={{ gap: 2, alignItems: 'center', flexWrap: 'wrap', mb: 1.5 }}>
                      <TextField size="small" label="Akış Adı" value={flowName}
                                onChange={(e) => setFlowName(e.target.value)} disabled={!canDesign} sx={{ minWidth: 220 }} />
                      <TextField size="small" label="Açıklama" value={flowDescription}
                                onChange={(e) => setFlowDescription(e.target.value)} disabled={!canDesign}
                                sx={{ minWidth: 280, flexGrow: 1 }} />
                    </Stack>

                    {!canRun && nodes.length > 0 && (
                      <Alert severity="warning" sx={{ mb: 1.5 }}>
                        {missingJobNodeIds.length} düğümde Jenkins job seçilmedi (turuncu çerçeveyle işaretli) —
                        bu düğümler tetiklenince hemen başarısız olur. Devam etmeden önce her düğüme bir job atayın.
                      </Alert>
                    )}

                    {canDesign && (
                      <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
                        <Button size="small" startIcon={<AutoFixHighIcon />} onClick={autoLayout}>Otomatik Düzenle</Button>
                        <Box sx={{ flexGrow: 1 }} />
                        <Button size="small" startIcon={<ContentCopyIcon />} onClick={() => setYamlOpen(true)}>
                          YAML Dışa Aktar
                        </Button>
                        <Button size="small" variant="contained" startIcon={<SaveIcon />}
                               disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
                          Kaydet
                        </Button>
                        {isAdmin && !isDraft && selectedFlowId && (
                          <Tooltip title={
                            !canRun ? 'Bazı düğümlerde Jenkins job seçilmedi — önce düzeltin'
                              : activeRunForFlow ? `Bu akış için zaten devam eden bir dağıtım var (#${activeRunForFlow.id})`
                              : ''
                          }>
                            <span>
                              <Button size="small" variant="contained" color="success" startIcon={<RocketLaunchIcon />}
                                     disabled={runMutation.isPending || !canRun || !!activeRunForFlow}
                                     onClick={() => runMutation.mutate()}>
                                Dağıt
                              </Button>
                            </span>
                          </Tooltip>
                        )}
                      </Stack>
                    )}

                    <Box sx={{ height: 480, border: 1, borderColor: 'divider', borderRadius: 1 }}>
                      <ReactFlow
                        nodes={displayNodes} edges={displayEdges} nodeTypes={NODE_TYPES}
                        onNodesChange={handleNodesChange}
                        onEdgesChange={canDesign ? onEdgesChange : undefined}
                        onConnect={canDesign ? onConnect : undefined}
                        onNodeClick={(_, node) => { if (node.id !== START_ID) setSelectedNodeId(node.id) }}
                        nodesDraggable={canDesign} nodesConnectable={canDesign} elementsSelectable={canDesign}
                        defaultEdgeOptions={{
                          style: { stroke: edgeColor, strokeWidth: 2 },
                          markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
                        }}
                        fitView proOptions={{ hideAttribution: true }}
                      >
                        <Background />
                        <Controls />
                        <MiniMap pannable zoomable
                                nodeColor={(n) => (n.type === 'start' ? '#66bb6a'
                                  : deploymentNodeColors[(n.data as DeployNodeData)?.environment] ?? '#666')} />
                      </ReactFlow>
                    </Box>
                  </Paper>
                </AddNodeContext.Provider>
              )}

              {/* Çalıştırma geçmişi — özet liste; detay/parametreler/Yeniden Dağıt kendi sayfasında */}
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Çalıştırmalar</Typography>
                  <TextField size="small" placeholder="Akış, tetikleyen, job veya parametreye göre ara…"
                            value={runSearch} onChange={(e) => setRunSearch(e.target.value)}
                            sx={{ width: 320 }} />
                </Stack>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>#</TableCell>
                      <TableCell>Akış</TableCell>
                      <TableCell>Durum</TableCell>
                      <TableCell>Süre</TableCell>
                      <TableCell>Tetikleme</TableCell>
                      <TableCell>Tetikleyen</TableCell>
                      <TableCell>Zaman</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(runs ?? []).map((r) => (
                      <TableRow key={r.id} hover sx={{ cursor: 'pointer' }}
                               onClick={() => navigate(`/deployments/runs/${r.id}`)}>
                        <TableCell sx={{ fontWeight: 600 }}>#{r.id}</TableCell>
                        <TableCell>{r.flow_name_snapshot}</TableCell>
                        <TableCell><StatusChip status={r.status} /></TableCell>
                        <TableCell>{formatDuration(r.duration_seconds)}</TableCell>
                        <TableCell>
                          {TRIGGER_TYPE_LABELS[r.trigger_type] ?? r.trigger_type}
                          {r.source_run_id != null && ` (#${r.source_run_id})`}
                        </TableCell>
                        <TableCell>{r.triggered_by ?? '—'}</TableCell>
                        <TableCell>{new Date(r.created_at).toLocaleString('tr-TR')}</TableCell>
                      </TableRow>
                    ))}
                    {(runs ?? []).length === 0 && (
                      <TableRow><TableCell colSpan={7} sx={{ color: 'text.secondary' }}>
                        {debouncedRunSearch ? 'Aramayla eşleşen çalıştırma yok.' : 'Henüz çalıştırma yok.'}
                      </TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
              </Paper>
            </Stack>
          )}
        </Box>
      </Box>

      {/* Düğüm düzenleme paneli (mevcut düğüme tıklanınca) */}
      <Drawer anchor="right" open={!!selectedNode} onClose={() => setSelectedNodeId(null)}>
        {selectedNode && (
          <Box sx={{ width: 380, p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>Düğümü Düzenle</Typography>
            <Stack spacing={2}>
              <TextField size="small" label="Ad" value={selectedNode.data.label} disabled={!canDesign}
                        onChange={(e) => patchSelectedNode({ label: e.target.value })} />
              <Select size="small" value={selectedNode.data.environment} disabled={!canDesign}
                     onChange={(e) => patchSelectedNode({ environment: e.target.value as DeploymentEnvKind })}>
                {(Object.keys(ENV_LABELS) as DeploymentEnvKind[]).map((env) => (
                  <MenuItem key={env} value={env}>{ENV_LABELS[env]}</MenuItem>
                ))}
              </Select>
              <TextField size="small" label="Jenkins Job" value={selectedNode.data.jenkins_job} disabled={!canDesign}
                        onChange={(e) => patchSelectedNode({ jenkins_job: e.target.value })} />
              <Typography variant="subtitle2">Parametreler</Typography>
              <ParamRows params={selectedNode.data.params} disabled={!canDesign}
                        onChange={(params) => patchSelectedNode({ params })} />
              {canDesign && (
                <Button color="error" startIcon={<DeleteIcon />} onClick={removeSelectedNode}>
                  Düğümü Sil
                </Button>
              )}
            </Stack>
          </Box>
        )}
      </Drawer>

      {/* Rehberli düğüm ekleme: 1) kaynak seç 2) Jenkins job'u seç 3) parametreler otomatik gelir, doldur */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>
          {addStep === 'pick-source' ? 'Kaynak Seç'
            : addStep === 'pick-job' ? 'Jenkins Job Seç' : 'Düğüm Bilgileri'}
        </DialogTitle>
        <DialogContent>
          {addStep === 'pick-source' && (
            <Stack spacing={1} sx={{ mt: 1 }}>
              <Button variant="outlined" size="large" startIcon={<BuildIcon />}
                     sx={{ justifyContent: 'flex-start', py: 1.5 }}
                     onClick={() => setAddStep('pick-job')}>
                Jenkins
              </Button>
              <Typography variant="caption" color="text.secondary">
                Şu an yalnızca Jenkins entegrasyonu destekleniyor.
              </Typography>
            </Stack>
          )}

          {addStep === 'pick-job' && (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <TextField size="small" label="Job ara" value={addJobSearch} autoFocus
                        onChange={(e) => setAddJobSearch(e.target.value)} />
              {jenkinsJobsLoading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}><CircularProgress size={22} /></Box>
              ) : filteredJenkinsJobs.length === 0 ? (
                <Alert severity="info">
                  Jenkins job'u bulunamadı. Ayarlar &gt; Jenkins bölümünden entegrasyonu kontrol edin.
                </Alert>
              ) : (
                <List dense disablePadding sx={{ maxHeight: 320, overflow: 'auto' }}>
                  {filteredJenkinsJobs.map((job) => (
                    <ListItemButton key={job} onClick={() => pickAddJob(job)} sx={{ borderRadius: 1 }}>
                      <ListItemText primary={job} slotProps={{ primary: { sx: { fontFamily: 'monospace', fontSize: 13 } } }} />
                    </ListItemButton>
                  ))}
                </List>
              )}
            </Stack>
          )}

          {addStep === 'fill-form' && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <TextField size="small" label="Jenkins Job" value={addJob} disabled fullWidth
                          sx={{ '& .MuiInputBase-input': { fontFamily: 'monospace', fontSize: 13 } }} />
                <Button size="small" onClick={() => setAddStep('pick-job')}>Değiştir</Button>
              </Stack>
              <TextField size="small" label="Ad" value={addLabel} onChange={(e) => setAddLabel(e.target.value)} autoFocus />
              {/* Ortam seçimi burada YOK — job adından otomatik tahmin edilir (guessEnvFromJob);
                  yanlış tahmin ederse düğüme sonradan tıklayıp düzenleme panelinden düzeltilebilir. */}
              <Typography variant="subtitle2">Parametreler</Typography>
              {jobParamsLoading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}><CircularProgress size={20} /></Box>
              ) : (
                <>
                  {jobParamsData?.parameters?.length === 0 && (
                    <Typography variant="caption" color="text.secondary">
                      Bu job için tanımlı parametre bulunamadı; gerekirse elle ekleyebilirsiniz.
                    </Typography>
                  )}
                  <ParamRows params={addParams} onChange={setAddParams} />
                </>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          {addStep === 'pick-job' && <Button onClick={() => setAddStep('pick-source')}>Geri</Button>}
          {addStep === 'fill-form' && <Button onClick={() => setAddStep('pick-job')}>Geri</Button>}
          <Button onClick={() => setAddOpen(false)}>Vazgeç</Button>
          {addStep === 'fill-form' && (
            <Button variant="contained" disabled={!addLabel.trim()} onClick={confirmAddNode}>Ekle</Button>
          )}
        </DialogActions>
      </Dialog>

      {/* YAML dışa aktar */}
      <Dialog open={yamlOpen} onClose={() => setYamlOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>YAML Dışa Aktar</DialogTitle>
        <DialogContent>
          <TextField multiline fullWidth minRows={14} value={yamlText}
                    slotProps={{ input: { readOnly: true, sx: { fontFamily: 'monospace', fontSize: 12.5 } } }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setYamlOpen(false)}>Kapat</Button>
          <Button variant="contained" startIcon={<DownloadIcon />} onClick={copyYaml}>Panoya Kopyala</Button>
        </DialogActions>
      </Dialog>

      {/* YAML içe aktar */}
      <Dialog open={importOpen} onClose={() => setImportOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>YAML İçe Aktar</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Autocomplete
              size="small" options={apps ?? []} getOptionLabel={(a) => a.app_name}
              value={apps?.find((a) => a.id === importTargetAppId) ?? null}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              onChange={(_, v) => setImportTargetAppId(v?.id ?? null)}
              renderInput={(p) => <TextField {...p} label="Hedef Uygulama" />}
            />
            <TextField multiline fullWidth minRows={12} placeholder="YAML içeriğini buraya yapıştırın…"
                      value={importText} onChange={(e) => setImportText(e.target.value)}
                      slotProps={{ input: { sx: { fontFamily: 'monospace', fontSize: 12.5 } } }} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportOpen(false)}>Vazgeç</Button>
          <Button variant="contained" disabled={!importText.trim()} onClick={doImport}>İçe Aktar</Button>
        </DialogActions>
      </Dialog>

      {/* Akışı başka uygulamaya kopyala */}
      <Dialog open={!!copySource} onClose={() => setCopySource(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Akışı Kopyala</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              "{copySource?.name}" akışının tüm düğüm/bağlantıları hedef uygulamada yeni bir akış olarak oluşturulur.
            </Typography>
            <Autocomplete
              size="small" options={apps ?? []} getOptionLabel={(a) => a.app_name}
              value={apps?.find((a) => a.id === copyTargetAppId) ?? null}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              onChange={(_, v) => setCopyTargetAppId(v?.id ?? null)}
              renderInput={(p) => <TextField {...p} label="Hedef Uygulama" />}
            />
            <TextField size="small" label="Yeni Akış Adı" value={copyName}
                      onChange={(e) => setCopyName(e.target.value)} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCopySource(null)}>Vazgeç</Button>
          <Button variant="contained" disabled={!copyTargetAppId || copyFlowMutation.isPending}
                 onClick={() => copyFlowMutation.mutate()}>
            Kopyala
          </Button>
        </DialogActions>
      </Dialog>

      {/* Akış silme onayı */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Akışı Sil</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            "{deleteTarget?.name}" akışı silinecek. Geçmiş çalıştırma kayıtları ETKİLENMEZ (korunur).
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Vazgeç</Button>
          <Button color="error" variant="contained" disabled={deleteMutation.isPending}
                 onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}>
            Sil
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default function Deployments() {
  return (
    <ReactFlowProvider>
      <DeploymentsInner />
    </ReactFlowProvider>
  )
}
