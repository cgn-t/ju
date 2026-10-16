import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import HistoryIcon from '@mui/icons-material/History'
import LockIcon from '@mui/icons-material/Lock'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import {
  Alert, Box, Button, Chip, Collapse, Divider, Drawer, IconButton, Stack, Tooltip, Typography,
} from '@mui/material'
import { useState } from 'react'
import type { AuditEntry, AuditMeta } from '../api/types'
import { MONO_FONT } from '../theme'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import ActionDot from './AuditActionDot'

type Change = { old?: unknown; new?: unknown; old_label?: string; new_label?: string; masked?: boolean }

// Kaydın kendi detay çekmecesi açılabilen tablolar (silinmemişse)
const OPENABLE_TABLES = ['certificates', 'SSLCertificates', 'domains', 'applications'] as const

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Evet' : 'Hayır'
  if (Array.isArray(v)) return v.length ? v.map(fmt).join(', ') : '—'
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  const s = String(v)
  // ISO tarih-saat → okunur
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) return new Date(s).toLocaleString('tr-TR')
  return s
}

function valueLabel(meta: AuditMeta | undefined, field: string, v: unknown): unknown {
  return typeof v === 'string' ? (meta?.values[field]?.[v] ?? v) : v
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{label}</Typography>
      <Box sx={{ typography: 'body2', wordBreak: 'break-word' }}>{children}</Box>
    </Box>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, lineHeight: 1.8 }}>
      {children}
    </Typography>
  )
}

function ValueCell({ field, change, side, meta }: {
  field: string; change: Change; side: 'old' | 'new'; meta?: AuditMeta
}) {
  if (change.masked) {
    const had = change[side] !== null && change[side] !== undefined
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}>
        <LockIcon sx={{ fontSize: 14 }} />
        <Typography variant="body2" sx={{ fontStyle: 'italic' }}>{had ? 'gizli değer' : '—'}</Typography>
      </Box>
    )
  }
  const raw = change[side]
  const label = side === 'old' ? change.old_label : change.new_label
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {label ?? fmt(valueLabel(meta, field, raw))}
      </Typography>
      {label !== undefined && raw !== null && raw !== undefined && (
        <Typography variant="caption" color="text.disabled">#{String(raw)}</Typography>
      )}
    </Box>
  )
}

/** Eski | Yeni karşılaştırma tablosu — eski kırmızı, yeni yeşil zemin. */
function DiffTable({ changes, meta }: { changes: Record<string, Change>; meta?: AuditMeta }) {
  const rows = Object.entries(changes)
  if (!rows.length) {
    return <Typography variant="body2" color="text.secondary">Kaydedilen bir değer değişikliği yok.</Typography>
  }
  return (
    <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: '150px 1fr 1fr', px: 1.5, py: 0.75,
                 bgcolor: 'action.hover', borderBottom: '1px solid', borderColor: 'divider' }}>
        {['ALAN', 'ESKİ DEĞER', 'YENİ DEĞER'].map((h) => (
          <Typography key={h} variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>{h}</Typography>
        ))}
      </Box>
      {rows.map(([field, ch], i) => (
        <Box key={field} sx={{ display: 'grid', gridTemplateColumns: '150px 1fr 1fr', alignItems: 'start',
                               borderTop: i ? '1px solid' : 'none', borderColor: 'divider' }}>
          <Box sx={{ px: 1.5, py: 1 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{meta?.fields[field] ?? field}</Typography>
            {meta?.fields[field] && (
              <Typography variant="caption" color="text.disabled" sx={{ fontFamily: MONO_FONT, fontSize: 10.5 }}>
                {field}
              </Typography>
            )}
          </Box>
          <Box sx={{ px: 1.5, py: 1, bgcolor: (t) => t.palette.mode === 'dark' ? 'rgba(244,67,54,0.10)' : 'rgba(244,67,54,0.06)',
                     borderLeft: '1px solid', borderColor: 'divider', height: '100%' }}>
            <ValueCell field={field} change={ch} side="old" meta={meta} />
          </Box>
          <Box sx={{ px: 1.5, py: 1, bgcolor: (t) => t.palette.mode === 'dark' ? 'rgba(76,175,80,0.12)' : 'rgba(76,175,80,0.08)',
                     borderLeft: '1px solid', borderColor: 'divider', height: '100%' }}>
            <ValueCell field={field} change={ch} side="new" meta={meta} />
          </Box>
        </Box>
      ))}
    </Box>
  )
}

/** Anahtar/değer listesi (snapshot ve bağlam alanları). Kimlik alanları sona, soluk. */
function KeyValues({ data, meta }: { data: Record<string, unknown>; meta?: AuditMeta }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== '')
  if (!entries.length) return null
  const isId = (k: string) => k === 'id' || k.endsWith('_id')
  entries.sort(([a], [b]) => Number(isId(a)) - Number(isId(b)))
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '150px 1fr', columnGap: 1.5, rowGap: 0.75 }}>
      {entries.map(([k, v]) => (
        <Box key={k} sx={{ display: 'contents' }}>
          <Typography variant="body2" color={isId(k) ? 'text.disabled' : 'text.secondary'}>
            {meta?.fields[k] ?? k}
          </Typography>
          {Array.isArray(v) && v.length > 1 ? (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {v.map((x, i) => <Chip key={i} size="small" variant="outlined" label={fmt(x)} sx={{ height: 22 }} />)}
            </Box>
          ) : (
            <Typography variant="body2" color={isId(k) ? 'text.disabled' : 'text.primary'}
                        sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              fontFamily: typeof v === 'object' && !Array.isArray(v) ? MONO_FONT : undefined,
                              fontSize: typeof v === 'object' && !Array.isArray(v) ? 12 : undefined }}>
              {fmt(valueLabel(meta, k, v))}
            </Typography>
          )}
        </Box>
      ))}
    </Box>
  )
}

export default function AuditDetailDrawer({ entry, meta, onClose, onShowHistory, onOpenRecord }: {
  entry: AuditEntry | null
  meta?: AuditMeta
  onClose: () => void
  onShowHistory: (e: AuditEntry) => void
  onOpenRecord: (e: AuditEntry) => void
}) {
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)

  let parsed: unknown = null
  if (entry?.details) {
    try { parsed = JSON.parse(entry.details) } catch { parsed = entry.details }
  }
  const obj = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
    ? parsed as Record<string, unknown> : null
  const changes = obj?.changes as Record<string, Change> | undefined
  const snapshot = obj?.snapshot as Record<string, unknown> | undefined
  const context = obj ? Object.fromEntries(Object.entries(obj).filter(([k]) => k !== 'changes' && k !== 'snapshot')) : null
  const legacyUpdate = entry?.action === 'update' && !changes
  const canOpen = !!entry && entry.action !== 'delete' && /^\d+$/.test(entry.record_id ?? '')
    && (OPENABLE_TABLES as readonly string[]).includes(entry.table_name)
  const hasHistory = !!entry?.record_id

  const copyRaw = async () => {
    if (!entry?.details) return
    try {
      await navigator.clipboard.writeText(
        typeof parsed === 'object' ? JSON.stringify(parsed, null, 2) : entry.details)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* pano erişimi yoksa sessiz geç */ }
  }

  return (
    <Drawer anchor="right" open={entry !== null} onClose={() => { setShowRaw(false); onClose() }}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 680 } } } }}>
      {entry && (
        <Box sx={{ p: 3 }}>
          <Stack spacing={2.25}>
            {/* Başlık */}
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
                  <ActionDot action={entry.action} meta={meta} />
                  <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                    {meta?.tables[entry.table_name] ?? entry.table_name}
                  </Typography>
                </Box>
                <Typography variant="h6" sx={{ wordBreak: 'break-word', lineHeight: 1.3 }}>
                  {entry.record_label || (entry.record_id ? `#${entry.record_id}` : (meta?.actions[entry.action] ?? entry.action))}
                </Typography>
                {entry.summary && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, wordBreak: 'break-word' }}>
                    {entry.summary}
                  </Typography>
                )}
              </Box>
              <Tooltip title="Kapat">
                <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>

            {/* Kim / ne zaman / nereden */}
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' }, gap: 2,
                       p: 1.5, borderRadius: 1.5, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider' }}>
              <Meta label="Zaman">
                <Box sx={{ fontVariantNumeric: 'tabular-nums' }}>{formatAuditTime(entry.created_at, true)}</Box>
                <Typography variant="caption" color="text.secondary">{relativeTime(entry.created_at)}</Typography>
              </Meta>
              <Meta label="Kullanıcı">
                {entry.user_full_name ?? entry.username}
                {entry.user_full_name && (
                  <Typography variant="caption" color="text.secondary" component="div">{entry.username}</Typography>
                )}
              </Meta>
              <Meta label="Kategori">{(entry.category && meta?.categories[entry.category]) ?? '—'}</Meta>
              <Meta label="IP"><Box sx={{ fontFamily: MONO_FONT, fontSize: 12 }}>{entry.ip_address || '—'}</Box></Meta>
            </Box>

            {(hasHistory || canOpen) && (
              <Stack direction="row" spacing={1}>
                {hasHistory && (
                  <Button size="small" variant="outlined" startIcon={<HistoryIcon />}
                          onClick={() => onShowHistory(entry)}>
                    Bu kaydın tüm geçmişi
                  </Button>
                )}
                {canOpen && (
                  <Button size="small" variant="text" startIcon={<OpenInNewIcon />}
                          onClick={() => onOpenRecord(entry)}>
                    Kaydı aç
                  </Button>
                )}
              </Stack>
            )}

            {/* Değişiklikler */}
            {changes && (
              <Box>
                <SectionTitle>Değişiklikler · {Object.keys(changes).length} alan</SectionTitle>
                <DiffTable changes={changes} meta={meta} />
              </Box>
            )}
            {legacyUpdate && (
              <Alert severity="info" variant="outlined">
                Bu kayıt eski biçimde tutulmuş: önceki değerler kaydedilmemiş, yalnız aşağıdaki
                bilgiler mevcut. Yeni güncellemelerde eski → yeni değerler birlikte saklanır.
              </Alert>
            )}

            {/* Silinen kaydın son hali */}
            {snapshot && Object.keys(snapshot).length > 0 && (
              <Box>
                <SectionTitle>Silinmeden önceki durum</SectionTitle>
                <Box sx={{ p: 1.5, borderRadius: 1.5, border: '1px solid', borderColor: 'divider' }}>
                  <KeyValues data={snapshot} meta={meta} />
                </Box>
              </Box>
            )}

            {/* Diğer bağlam */}
            {context && Object.keys(context).length > 0 && (
              <Box>
                <SectionTitle>Ayrıntılar</SectionTitle>
                <KeyValues data={context} meta={meta} />
              </Box>
            )}
            {Array.isArray(parsed) && (
              <Box>
                <SectionTitle>Değişen alanlar</SectionTitle>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {(parsed as unknown[]).map((f) => (
                    <Chip key={String(f)} size="small" variant="outlined" label={meta?.fields[String(f)] ?? String(f)} />
                  ))}
                </Box>
              </Box>
            )}
            {typeof parsed === 'string' && (
              <Box>
                <SectionTitle>Ayrıntılar</SectionTitle>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{parsed}</Typography>
              </Box>
            )}

            {/* Ham kayıt */}
            {entry.details && (
              <>
                <Divider />
                <Box>
                  <Box sx={{ display: 'flex', alignItems: 'center' }}>
                    <Button size="small" onClick={() => setShowRaw((v) => !v)} sx={{ px: 0.5 }}>
                      {showRaw ? 'Ham kaydı gizle' : 'Ham kaydı göster (JSON)'}
                    </Button>
                    <Box sx={{ flexGrow: 1 }} />
                    <Tooltip title={copied ? 'Kopyalandı' : 'Panoya kopyala'}>
                      <IconButton size="small" onClick={copyRaw}>
                        {copied ? <CheckIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
                      </IconButton>
                    </Tooltip>
                  </Box>
                  <Collapse in={showRaw}>
                    <Box component="pre" sx={{
                      fontFamily: MONO_FONT, fontSize: 12, m: 0, mt: 1, p: 1.5, borderRadius: 1,
                      bgcolor: 'action.hover', maxHeight: 420, overflow: 'auto',
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                      {typeof parsed === 'object' ? JSON.stringify(parsed, null, 2) : entry.details}
                    </Box>
                  </Collapse>
                </Box>
              </>
            )}
            <Typography variant="caption" color="text.disabled">
              Kayıt #{entry.id}{entry.record_id ? ` · ${entry.table_name} #${entry.record_id}` : ''}
            </Typography>
          </Stack>
        </Box>
      )}
    </Drawer>
  )
}
