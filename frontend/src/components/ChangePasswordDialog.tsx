import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment, Stack,
  TextField, Typography,
} from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState, type FormEvent } from 'react'
import { api, apiErrorMessage } from '../api/client'

export const MIN_PASSWORD_LEN = 8

/** Yerel hesabın (ör. admin) kendi şifresini değiştirmesi: mevcut şifre + yeni şifre iki kez.
 *  AD hesaplarında bu diyalog hiç gösterilmez (şifre AD'de). */
export default function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { enqueueSnackbar } = useSnackbar()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [show, setShow] = useState(false)
  const [tried, setTried] = useState(false)

  const reset = () => { setCurrent(''); setNext(''); setAgain(''); setShow(false); setTried(false); save.reset() }
  const close = () => { reset(); onClose() }

  const save = useMutation({
    mutationFn: async () => (await api.post('/auth/change-password',
      { current_password: current, new_password: next })).data,
    onSuccess: () => { enqueueSnackbar('Şifreniz değiştirildi', { variant: 'success' }); close() },
  })

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD_LEN
  const mismatch = again.length > 0 && next !== again
  const sameAsOld = next.length > 0 && next === current
  const valid = !!current && next.length >= MIN_PASSWORD_LEN && next === again && !sameAsOld

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTried(true)
    if (valid) save.mutate()
  }

  const eye = (
    <InputAdornment position="end">
      <IconButton size="small" edge="end" aria-label={show ? 'Şifreleri gizle' : 'Şifreleri göster'}
                  onClick={() => setShow((s) => !s)}>
        {show ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
      </IconButton>
    </InputAdornment>
  )
  const type = show ? 'text' : 'password'

  return (
    <Dialog open={open} onClose={close} maxWidth="xs" fullWidth>
      <form onSubmit={submit} noValidate>
        <DialogTitle>Şifre Değiştir</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Önce mevcut şifrenizi, sonra yeni şifrenizi iki kez girin. Yeni şifre en az {MIN_PASSWORD_LEN} karakter olmalı.
          </Typography>
          <Stack spacing={2}>
            <TextField label="Mevcut şifre" type={type} value={current} autoFocus required fullWidth
                       autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)}
                       error={tried && !current} helperText={tried && !current ? 'Mevcut şifrenizi girin' : ' '}
                       slotProps={{ input: { endAdornment: eye } }} />
            <TextField label="Yeni şifre" type={type} value={next} required fullWidth
                       autoComplete="new-password" onChange={(e) => setNext(e.target.value)}
                       error={tooShort || sameAsOld || (tried && !next)}
                       helperText={sameAsOld ? 'Yeni şifre mevcut şifreyle aynı olamaz'
                         : tooShort || (tried && !next) ? `En az ${MIN_PASSWORD_LEN} karakter` : ' '} />
            <TextField label="Yeni şifre (tekrar)" type={type} value={again} required fullWidth
                       autoComplete="new-password" onChange={(e) => setAgain(e.target.value)}
                       error={mismatch || (tried && !again)}
                       helperText={mismatch ? 'Yeni şifreler aynı değil' : tried && !again ? 'Yeni şifreyi tekrar girin' : ' '} />
          </Stack>
          {save.isError && <Alert severity="error" sx={{ mt: 1 }}>{apiErrorMessage(save.error)}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={close}>Vazgeç</Button>
          <Button type="submit" variant="contained" disabled={save.isPending}>Şifreyi Değiştir</Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
