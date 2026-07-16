import EventAvailableIcon from '@mui/icons-material/EventAvailable'
import {
  Box, Button, Dialog, DialogActions, DialogContent, Divider, Stack, Typography, alpha,
} from '@mui/material'

export interface ConfirmItem {
  label: string
  value: string
  highlight?: boolean  // tarih gibi kritik alanlar vurgulu gösterilir
}

/** Kritik sertifika/domain değişikliklerinde Kaydet'e basınca çıkan ONAY diyaloğu.
 *  Kullanıcıya ne kaydedileceğinin özeti (tarihler vurgulu) gösterilir; işlem ancak
 *  "Onaylıyorum" butonuyla uygulanır. Yanlış tarihli kayıt/güncelleme kazalarını önler. */
export default function ConfirmSaveDialog({ open, onClose, onConfirm, title, description,
                                            items, confirmLabel }: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title?: string
  description?: string
  items?: ConfirmItem[]
  confirmLabel?: string
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogContent sx={{ textAlign: 'center', pt: 4 }}>
        <Box sx={{
          width: 56, height: 56, borderRadius: '50%', mx: 'auto', mb: 2,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          bgcolor: (t) => alpha(t.palette.warning.main, 0.15),
        }}>
          <EventAvailableIcon color="warning" sx={{ fontSize: 32 }} />
        </Box>
        <Typography variant="h6" gutterBottom>
          {title ?? 'Kaydetmeden Önce Kontrol Edin'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {description ?? 'Lütfen tarih bilgilerinin (geçerlilik/bitiş) doğru olduğundan emin '
            + 'olun. Onayladığınızda değişiklik kaydedilecektir.'}
        </Typography>

        {items && items.length > 0 && (
          <Stack component={Box} sx={{ mt: 2.5, textAlign: 'left', border: 1,
                                       borderColor: 'divider', borderRadius: 1 }}
                 divider={<Divider />}>
            {items.map((it) => (
              <Box key={it.label + it.value}
                   sx={{ display: 'flex', justifyContent: 'space-between', gap: 2,
                         px: 1.5, py: 1 }}>
                <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>
                  {it.label}
                </Typography>
                <Typography variant="body2"
                            sx={{ fontWeight: 600, textAlign: 'right', wordBreak: 'break-word',
                                  color: it.highlight ? 'warning.main' : 'text.primary' }}>
                  {it.value}
                </Typography>
              </Box>
            ))}
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3, gap: 1 }}>
        <Button fullWidth variant="outlined" color="inherit" onClick={onClose}>
          Geri Dön
        </Button>
        <Button fullWidth variant="contained" onClick={onConfirm} autoFocus>
          {confirmLabel ?? 'Onaylıyorum, Kaydet'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
