import HistoryIcon from '@mui/icons-material/History'
import {
  Avatar, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Skeleton, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AuditList, AuditMeta } from '../api/types'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { initials } from '../utils/peopleLabels'
import ActionDot from './AuditActionDot'

/**
 * Kullanıcılar ve Ekipler ekranlarının ortak parçaları — Audit Log / Mail Geçmişi ile aynı görsel dil:
 * sayaçlı sekme etiketi, detay çekmecesi başlık/alan bileşenleri, son işlemler listesi, onay penceresi.
 */

/** Sekme etiketi + sayaç rozeti (alarm=true → kırmızı; dikkat isteyen durumlar). */
export function CountLabel({ label, count, alarm }: { label: string; count?: number; alarm?: boolean }) {
  const on = !!alarm && !!count
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
      {label}
      <Box component="span" sx={{ px: 0.75, borderRadius: 1, fontSize: 11, lineHeight: '18px',
                                  fontVariantNumeric: 'tabular-nums',
                                  bgcolor: on ? 'warning.main' : 'action.selected',
                                  color: on ? 'warning.contrastText' : 'inherit' }}>
        {count ?? '·'}
      </Box>
    </Box>
  )
}

export function PersonAvatar({ fullName, username, size = 32, muted }: {
  fullName?: string | null; username: string; size?: number; muted?: boolean
}) {
  return (
    <Avatar sx={{ width: size, height: size, fontSize: size * 0.4, fontWeight: 600,
                  bgcolor: muted ? 'action.disabledBackground' : 'primary.main',
                  color: muted ? 'text.secondary' : 'primary.contrastText' }}>
      {initials(fullName, username)}
    </Avatar>
  )
}

export function Meta({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <Box sx={{ minWidth: 0, ...(wide && { gridColumn: 'span 2' }) }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{label}</Typography>
      <Box sx={{ typography: 'body2', wordBreak: 'break-word' }}>{children}</Box>
    </Box>
  )
}

export function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
      <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, lineHeight: 1.8, flexGrow: 1 }}>
        {children}
      </Typography>
      {action}
    </Box>
  )
}

export const metaGridSx = {
  display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' }, gap: 2,
  p: 1.5, borderRadius: 1.5, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider',
} as const

/**
 * Son işlemler — Audit Log'dan ilgili en yeni kayıtlar. `params` audit liste uç noktasının filtreleri
 * (ör. {actor: 'ahmet'} ya da {table_name: 'teams,user_teams', record_id: '5'}); `auditLink` Audit
 * Log ekranını aynı filtreyle açan adres.
 */
export function RecentActivity({ params, auditLink, empty }: {
  params: Record<string, string>; auditLink: string; empty: string
}) {
  const navigate = useNavigate()
  const { data: meta } = useQuery<AuditMeta>({
    queryKey: ['audit-meta'],
    queryFn: async () => (await api.get('/audit/meta')).data,
    staleTime: Infinity,
  })
  const { data, isLoading } = useQuery<AuditList>({
    queryKey: ['recent-activity', params],
    queryFn: async () => (await api.get('/audit', { params: { ...params, limit: 8 } })).data,
  })
  const items = data?.items ?? []
  return (
    <Box>
      <SectionTitle action={
        <Button size="small" startIcon={<HistoryIcon />} onClick={() => navigate(auditLink)}>
          Audit Log'da aç
        </Button>
      }>Son İşlemler</SectionTitle>
      {isLoading && <Skeleton height={96} />}
      {!isLoading && !items.length && (
        <Typography variant="body2" color="text.secondary">{empty}</Typography>
      )}
      <Box sx={{ display: 'flex', flexDirection: 'column' }}>
        {items.map((e) => (
          <Box key={e.id} sx={{ display: 'grid', gridTemplateColumns: '112px 1fr', gap: 1.5, py: 0.75,
                                borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="caption" color="text.secondary" title={relativeTime(e.created_at)}
                        sx={{ fontVariantNumeric: 'tabular-nums', pt: 0.25 }}>
              {formatAuditTime(e.created_at)}
            </Typography>
            <Box sx={{ minWidth: 0 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                <ActionDot action={e.action} meta={meta} withLabel />
                {e.record_label && (
                  <Typography variant="body2" noWrap sx={{ fontWeight: 500, minWidth: 0 }}>{e.record_label}</Typography>
                )}
              </Box>
              {e.summary && (
                <Typography variant="caption" color="text.secondary" sx={{
                  display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                  wordBreak: 'break-word' }}>
                  {e.summary}
                </Typography>
              )}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, onConfirm, onClose }: {
  open: boolean; title: string; children: React.ReactNode; confirmLabel: string
  danger?: boolean; busy?: boolean; onConfirm: () => void; onClose: () => void
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><Box sx={{ typography: 'body2' }}>{children}</Box></DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Vazgeç</Button>
        <Button variant="contained" color={danger ? 'error' : 'primary'} disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
