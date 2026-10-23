// Genel Durum, Ekibim ve ekip detayı sayfalarının ortak parçaları.
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import {
  Box, ButtonBase, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import type { ReactNode } from 'react'
import type { SummaryProposal, TeamHealth, TeamSummaryRow } from '../api/types'
import { exportSheet } from '../utils/exportSheet'
import { CARD_SX, StatusPill, type Tone } from './DetailCards'
import { EmptyState } from './ListKit'

export const TEAM_HEALTH: Record<TeamHealth, { label: string; tone: Tone; hint: string }> = {
  critical: { label: 'Acil', tone: 'error', hint: 'Süresi dolmuş sertifika ya da canlıda EŞLEŞMİYOR domain var' },
  warning: { label: 'Dikkat', tone: 'warning', hint: 'Yakında biten sertifika, bekleyen talep, uyum ihlali ya da ekip maili eksik' },
  ok: { label: 'İyi', tone: 'success', hint: 'İşlem bekleyen bir şey yok' },
}

const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']

/** "2026-11" → "Kasım 2026" */
export function monthLabel(key: string) {
  const [y, m] = key.split('-').map(Number)
  return `${MONTHS[(m || 1) - 1]} ${y}`
}

export const dayText = (d?: number | null) => (d === null || d === undefined ? '—' : d === 0 ? 'bugün' : `${d} gün`)

/** Özet kutusu: büyük sayı + kısa açıklama; tıklanırsa ilgili listeye götürür. */
export function SummaryTile({ label, value, sub, tone = 'default', onClick }: {
  label: string; value: ReactNode; sub?: string; tone?: Tone; onClick?: () => void
}) {
  return (
    <ButtonBase component="div" disabled={!onClick} onClick={onClick}
                sx={(t) => ({ ...CARD_SX, p: 2, display: 'block', textAlign: 'left', height: '100%',
                      transition: 'border-color 150ms, transform 150ms',
                      '&:hover': onClick ? { borderColor: alpha(t.palette.primary.main, 0.45), transform: 'translateY(-1px)' } : undefined })}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography sx={(t) => ({ fontSize: 30, fontWeight: 800, lineHeight: 1.15, mt: 0.5, letterSpacing: '-0.02em',
                         color: tone === 'default' ? 'text.primary' : t.palette.mode === 'dark' ? t.palette[tone].light : t.palette[tone].dark })}>
        {value}
      </Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </ButtonBase>
  )
}

export const TILE_GRID = {
  display: 'grid', gap: 2,
  gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(3, 1fr)', lg: 'repeat(5, 1fr)' },
} as const

/** Sıfırdan büyükse renkli ve kalın, değilse soluk sayı. */
function Num({ n, tone }: { n: number; tone: Tone }) {
  return (
    <Typography component="span" variant="body2"
                sx={(t) => n > 0 && tone !== 'default'
                  ? { fontWeight: 700, color: t.palette.mode === 'dark' ? t.palette[tone].light : t.palette[tone].dark }
                  : { color: n > 0 ? 'text.primary' : 'text.disabled' }}>
      {n}
    </Typography>
  )
}

function missingTip(r: TeamSummaryRow) {
  const m = r.missing_detail
  const parts = [
    m.no_pem ? `${m.no_pem} sertifikada PEM yok` : '',
    m.domains_without_cert ? `${m.domains_without_cert} domainde sertifika ve bitiş tarihi yok` : '',
    m.no_team_email ? 'Ekibin bildirim maili tanımlı değil' : '',
  ].filter(Boolean)
  return parts.join(' · ') || 'Eksik bilgi yok'
}

/** Ekip karşılaştırma tablosu (en riskli ekip en üstte; sıralama sunucudan gelir). */
export function TeamSummaryTable({ rows, soonDays, onOpen }: {
  rows: TeamSummaryRow[]; soonDays: number; onOpen: (teamId: number) => void
}) {
  if (!rows.length) return <EmptyState title="Gösterilecek ekip yok" hint="Domaini veya sertifikası olan SY ekibi bulunamadı." />
  // Kısa başlıklar tablo tek ekrana sığsın diye; açıklaması ipucunda
  const head: [string, string][] = [['Ekip', ''], ['Durum', ''], ['Domain', ''], ['Sertifika', 'Aktif sertifika'],
    ['Dolmuş', 'Süresi dolmuş sertifika'], [`${soonDays} gün`, `${soonDays} gün içinde bitecek sertifika`],
    ['En yakın', 'En yakın bitişe kalan gün'], ['Talep', 'Onay bekleyen değişiklik talebi'],
    ['En eski', 'En eski talebin bekleme süresi'], ['Uyum', 'Uyum ihlali olan sertifika'],
    ['Eşleşmiyor', 'Canlı doğrulamada EŞLEŞMİYOR ya da ara sertifikası eksik domain'],
    ['Eksik', 'Eksik bilgili kayıt (PEM, sertifika, ekip maili)']]
  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small" sx={{ minWidth: 900 }}>
        <TableHead>
          <TableRow>
            {head.map(([h, tip], i) => (
              <TableCell key={h} align={i > 1 ? 'right' : 'left'} sx={{ whiteSpace: 'nowrap' }}>
                {tip ? <Tooltip title={tip}><span>{h}</span></Tooltip> : h}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.team_id} hover onClick={() => onOpen(r.team_id)} sx={{ cursor: 'pointer' }}>
              <TableCell sx={{ fontWeight: 650, whiteSpace: 'nowrap' }}>{r.team}</TableCell>
              <TableCell>
                <Tooltip title={TEAM_HEALTH[r.status].hint}>
                  <span><StatusPill size="small" tone={TEAM_HEALTH[r.status].tone} label={TEAM_HEALTH[r.status].label} /></span>
                </Tooltip>
              </TableCell>
              <TableCell align="right">{r.domains}</TableCell>
              <TableCell align="right">{r.certificates}</TableCell>
              <TableCell align="right"><Num n={r.expired} tone="error" /></TableCell>
              <TableCell align="right"><Num n={r.expiring_soon} tone="warning" /></TableCell>
              <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{dayText(r.nearest_days)}</TableCell>
              <TableCell align="right"><Num n={r.pending_proposals} tone="info" /></TableCell>
              <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{r.oldest_pending_days === null || r.oldest_pending_days === undefined ? '—' : `${r.oldest_pending_days} gündür`}</TableCell>
              <TableCell align="right"><Num n={r.policy_violations} tone="warning" /></TableCell>
              <TableCell align="right"><Num n={r.live_problems} tone="error" /></TableCell>
              <TableCell align="right">
                <Tooltip title={missingTip(r)}>
                  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                    <Num n={r.missing_info} tone="default" />
                    {r.missing_info > 0 && <InfoOutlinedIcon sx={{ fontSize: 15, color: 'text.disabled' }} />}
                  </Box>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export function exportTeamRows(rows: TeamSummaryRow[], soonDays: number, filename = 'ekip-ozeti.xlsx') {
  exportSheet(filename,
    ['Ekip', 'Durum', 'Domain', 'Aktif sertifika', 'Süresi dolmuş', `${soonDays} gün içinde`, 'En yakın bitiş (gün)',
     'Bekleyen talep', 'En eski talep (gün)', 'Uyum ihlali', 'EŞLEŞMİYOR', 'Eksik bilgi', 'Eksik bilgi ayrıntısı', 'Ekip maili'],
    rows.map((r) => [r.team, TEAM_HEALTH[r.status].label, r.domains, r.certificates, r.expired, r.expiring_soon,
                     r.nearest_days ?? '', r.pending_proposals, r.oldest_pending_days ?? '', r.policy_violations,
                     r.live_problems, r.missing_info, missingTip(r), r.email ?? '']))
}

/** Önümüzdeki 90 günde bitecekler, ay ay yatay çubuk. */
export function UpcomingMonths({ months }: { months: { month: string; count: number }[] }) {
  if (!months.length) {
    return <Typography variant="body2" color="text.secondary">Önümüzdeki 90 günde biten sertifika yok.</Typography>
  }
  const max = Math.max(...months.map((m) => m.count))
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {months.map((m, i) => (
        <Box key={m.month} sx={{ display: 'grid', gridTemplateColumns: '110px 1fr 40px', alignItems: 'center', gap: 1.5 }}>
          <Typography variant="body2">{monthLabel(m.month)}</Typography>
          <Box sx={{ height: 14, borderRadius: 1, bgcolor: 'action.hover', overflow: 'hidden' }}>
            <Box sx={(t) => ({ height: '100%', width: `${Math.max(4, (m.count / max) * 100)}%`, borderRadius: 1,
                       bgcolor: alpha(t.palette.warning.main, 1 - i * 0.25) })} />
          </Box>
          <Typography variant="body2" sx={{ fontWeight: 650, textAlign: 'right' }}>{m.count}</Typography>
        </Box>
      ))}
    </Box>
  )
}

/** Bekleyen talepler listesi (en eski önce). */
export function ProposalList({ items, showTeam, onOpen }: {
  items: SummaryProposal[]; showTeam?: boolean; onOpen: (id: number) => void
}) {
  if (!items.length) return <Typography variant="body2" color="text.secondary">Onay bekleyen talep yok.</Typography>
  return (
    <Box>
      {items.map((p, i) => (
        <ButtonBase key={p.id} onClick={() => onOpen(p.id)}
                    sx={{ width: '100%', display: 'flex', justifyContent: 'space-between', gap: 2, py: 1, textAlign: 'left',
                          borderTop: i ? 1 : 0, borderColor: 'divider', '&:hover': { color: 'primary.main' } }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{p.domain ?? p.app ?? p.old_cert ?? `#${p.id}`}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap component="div">
              {p.label}{p.old_cert && p.new_cert && p.old_cert !== p.new_cert ? ` · ${p.old_cert} → ${p.new_cert}` : ''}
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
            {showTeam && p.team ? `${p.team} · ` : ''}{p.age_days ? `${p.age_days} gündür` : 'bugün'}
          </Typography>
        </ButtonBase>
      ))}
    </Box>
  )
}

/** Başlıklı beyaz kart. */
export function Panel({ title, aside, children, pad = true }: { title: string; aside?: ReactNode; children: ReactNode; pad?: boolean }) {
  return (
    <Box sx={{ ...CARD_SX, overflow: 'hidden' }}>
      <Box sx={{ px: 2, pt: 1.75, pb: pad ? 1.25 : 1.75, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 650 }}>{title}</Typography>
        {aside}
      </Box>
      <Box sx={pad ? { px: 2, pb: 2 } : undefined}>{children}</Box>
    </Box>
  )
}
