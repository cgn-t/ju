import CloseIcon from '@mui/icons-material/Close'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import ReplayIcon from '@mui/icons-material/Replay'
import { Box, Button, Dialog, IconButton, Stack, Typography } from '@mui/material'
import { alpha } from '@mui/material/styles'
import axios from 'axios'
import { apiErrorMessage } from '../api/client'

/** Kayıt türü → ekranda geçen ad (ör. "Bu domain..."). */
const KIND_LABEL = {
  domain: 'domain',
  application: 'uygulama',
  certificate: 'sertifika',
  finding: 'keşif kaydı',
} as const
export type RecordKind = keyof typeof KIND_LABEL

/** Sunucu kapsam dışı kaydı VARLIĞINI GİZLEMEK için 404 döner (403 değil); bu yüzden
 *  404 ve 403 aynı "erişilemiyor" mesajını gösterir. Diğer hatalar (ağ, 500) yeniden dene sunar. */
export function isNoAccessError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false
  const s = error.response?.status
  return s === 403 || s === 404
}

/**
 * Detay penceresi açılamadığında (kayıt başka SY ekibine ait / silinmiş / hata) boş-gri
 * iskelet yerine gösterilen açıklayıcı ekran.
 *  - `team` verilirse (çağıran kaydın ekibini biliyorsa) mesaj kesin: "X ekibine ait".
 *  - verilmezse (doğrudan link, harita, AI bağlantısı) sunucu ayırt etmediği için iki olasılık söylenir.
 */
export function RecordUnavailable({ kind, name, team, error, onClose, onRetry }: {
  kind: RecordKind; name?: string | null; team?: string | null; error?: unknown
  onClose: () => void; onRetry?: () => void
}) {
  const label = KIND_LABEL[kind]
  const noAccess = error === undefined || isNoAccessError(error)
  const title = noAccess ? 'Bu kaydı görüntüleme yetkiniz yok' : 'Kayıt yüklenemedi'
  return (
    <Box data-testid="record-unavailable" sx={{ p: { xs: 2.5, sm: 3.5 }, position: 'relative' }}>
      <IconButton aria-label="Kapat" onClick={onClose} sx={{ position: 'absolute', top: 12, right: 12 }}>
        <CloseIcon />
      </IconButton>
      <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center', maxWidth: 460, mx: 'auto', py: 2 }}>
        <Box sx={(t) => {
          const c = noAccess ? t.palette.warning.main : t.palette.error.main
          return { width: 64, height: 64, borderRadius: '50%', display: 'grid', placeItems: 'center',
                   color: c, backgroundColor: alpha(c, t.palette.mode === 'dark' ? 0.18 : 0.12) }
        }}>
          {noAccess ? <LockOutlinedIcon sx={{ fontSize: 32 }} /> : <ErrorOutlineIcon sx={{ fontSize: 32 }} />}
        </Box>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>{title}</Typography>
        {name && (
          <Typography variant="body2" sx={{ fontWeight: 600, wordBreak: 'break-all' }}>{name}</Typography>
        )}
        {noAccess ? (
          team ? (
            <Typography variant="body2" color="text.secondary">
              Bu {label} <b>{team}</b> ekibine ait. Detayını yalnız o ekibin üyeleri ve yöneticiler
              görebilir. Bilgiye ihtiyacınız varsa {team} ekibiyle ya da bir yöneticiyle iletişime geçin.
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Bu {label} sizin SY ekibinize ait değil ya da silinmiş olabilir. Başka bir ekibin
              kayıtlarını yalnız o ekibin üyeleri ve yöneticiler görebilir.
            </Typography>
          )
        ) : (
          <Typography variant="body2" color="text.secondary">{apiErrorMessage(error)}</Typography>
        )}
        <Stack direction="row" spacing={1}>
          {!noAccess && onRetry && (
            <Button variant="outlined" startIcon={<ReplayIcon />} onClick={onRetry}>Yeniden Dene</Button>
          )}
          <Button variant="contained" onClick={onClose}>Tamam</Button>
        </Stack>
      </Stack>
    </Box>
  )
}

/** Listeden/karttan tıklanan ama açılamayacak kayıt için küçük uyarı penceresi. */
export function NoAccessDialog({ open, kind, name, team, onClose }: {
  open: boolean; kind: RecordKind; name?: string | null; team?: string | null; onClose: () => void
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <RecordUnavailable kind={kind} name={name} team={team} onClose={onClose} />
    </Dialog>
  )
}
