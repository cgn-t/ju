import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlined'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import WifiTetheringIcon from '@mui/icons-material/WifiTethering'
import { Alert, Box, Button, IconButton, InputAdornment, Stack, TextField, Typography } from '@mui/material'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const FEATURES = [
  {
    icon: <AccountTreeOutlinedIcon />,
    title: 'Envanter & Zincir',
    desc: 'SSL sertifika envanteri ve uçtan uca zincir görünürlüğü',
  },
  {
    icon: <VerifiedUserOutlinedIcon />,
    title: 'Onaylı Devir',
    desc: 'Her yenileme, sahibi SY ekibinin onayıyla güvenle devredilir',
  },
  {
    icon: <WifiTetheringIcon />,
    title: 'Canlı Doğrulama',
    desc: 'Domain’e canlı TLS bağlantısı kurup sunulan gerçek sertifikayı envanterdekiyle karşılaştırır; uyumsuzluk (drift), erişilemezlik veya eşlenmemiş sertifikayı anında yakalar.',
  },
]

function BrandMark({ size = 52 }: { size?: number }) {
  return (
    <Box
      component="img" src="/favicon.svg" alt="JUMBO"
      sx={{ width: size, height: size, borderRadius: 2.5, filter: 'drop-shadow(0 10px 24px rgba(0,0,0,0.35))' }}
    />
  )
}

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
      <Box sx={{ minHeight: '100vh', display: 'flex', bgcolor: 'background.default' }}>
      {/* ---- Sol: marka & değer paneli (md+) ---- */}
      <Box
        sx={{
          display: { xs: 'none', md: 'flex' }, flexDirection: 'column',
          flexBasis: '48%', maxWidth: 620, minWidth: 0, p: { md: 6, lg: 8 },
          color: '#fff', position: 'relative', overflow: 'hidden',
          background: 'linear-gradient(155deg, #6f1418 0%, #971d24 42%, #e53946 125%)',
        }}
      >
        {/* dekoratif ışık + ince ızgara */}
        <Box sx={{ position: 'absolute', inset: 0, pointerEvents: 'none',
                   background: 'radial-gradient(circle at 82% 12%, rgba(255,255,255,0.16), transparent 46%)' }} />
        <Box sx={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.5,
                   backgroundImage: 'linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)',
                   backgroundSize: '38px 38px', maskImage: 'radial-gradient(circle at 30% 40%, #000 20%, transparent 75%)' }} />

        <Box sx={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 1.75 }}>
          <BrandMark />
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 26, letterSpacing: '-0.02em', lineHeight: 1 }}>JUMBO</Typography>
            <Typography sx={{ opacity: 0.85, fontSize: 13 }}>Sertifika Yönetim Platformu</Typography>
          </Box>
        </Box>

        <Box sx={{ position: 'relative', mt: 'auto' }}>
          <Typography sx={{ fontWeight: 700, fontSize: { md: 28, lg: 32 }, letterSpacing: '-0.02em', lineHeight: 1.15, mb: 1.5 }}>
            Kurumsal sertifika yönetimi,<br />tek denetlenebilir panelde.
          </Typography>
          <Typography sx={{ opacity: 0.82, mb: 4.5, maxWidth: 400, fontSize: 15, lineHeight: 1.55 }}>
            SSL envanteri, zincir görünürlüğü, SY onaylı devir akışı ve canlı doğrulama —
            hepsi tam denetim iziyle tek yerde.
          </Typography>
          <Stack spacing={2.5}>
            {FEATURES.map((f) => (
              <Box key={f.title} sx={{ display: 'flex', gap: 1.75, alignItems: 'flex-start' }}>
                <Box sx={{ flexShrink: 0, width: 42, height: 42, borderRadius: 2, display: 'grid', placeItems: 'center',
                           bgcolor: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.2)' }}>
                  {f.icon}
                </Box>
                <Box sx={{ minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 15, lineHeight: 1.35 }}>{f.title}</Typography>
                  <Typography sx={{ opacity: 0.8, fontSize: 13.5, lineHeight: 1.4 }}>{f.desc}</Typography>
                </Box>
              </Box>
            ))}
          </Stack>
        </Box>

        <Typography sx={{ position: 'relative', mt: 6, opacity: 0.72, fontSize: 12.5 }}>
          🔒 LDAP / Active Directory ile kurumsal kimlik doğrulama
        </Typography>
      </Box>

      {/* ---- Sağ: giriş formu ---- */}
      <Box sx={{ flexGrow: 1, display: 'grid', placeItems: 'center', p: { xs: 3, sm: 5 }, position: 'relative' }}>
        <Box sx={{ position: 'absolute', inset: 0, pointerEvents: 'none',
                   background: 'radial-gradient(circle at 70% 8%, rgba(229,57,70,0.10), transparent 42%)' }} />
        <Box sx={{ position: 'relative', width: '100%', maxWidth: 396 }}>
          {/* Mobilde marka paneli gizli → logo formun üstünde */}
          <Box sx={{ display: { xs: 'flex', md: 'none' }, flexDirection: 'column', alignItems: 'center', gap: 1, mb: 4 }}>
            <BrandMark size={64} />
            <Typography sx={{ fontWeight: 800, fontSize: 22, letterSpacing: '-0.01em' }}>JUMBO</Typography>
            <Typography variant="body2" color="text.secondary">Sertifika Yönetim Platformu</Typography>
          </Box>

          <Typography variant="h5" sx={{ mb: 0.5 }}>Oturum Aç</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3.5 }}>
            Devam etmek için hesabınızla giriş yapın.
          </Typography>

          <form onSubmit={submit}>
            <Stack spacing={2.25}>
              <TextField
                label="Kullanıcı Adı" placeholder="kullanici.adi" fullWidth value={username} autoFocus
                onChange={(e) => setUsername(e.target.value)}
                helperText="LDAP (AD) veya lokal hesap"
                slotProps={{
                  inputLabel: { shrink: true },
                  input: {
                    startAdornment: (
                      <InputAdornment position="start"><PersonOutlineIcon fontSize="small" color="action" /></InputAdornment>
                    ),
                  },
                }}
              />
              <TextField
                label="Şifre" fullWidth value={password}
                type={showPass ? 'text' : 'password'}
                onChange={(e) => setPassword(e.target.value)}
                slotProps={{
                  inputLabel: { shrink: true },
                  input: {
                    startAdornment: (
                      <InputAdornment position="start"><LockOutlinedIcon fontSize="small" color="action" /></InputAdornment>
                    ),
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowPass((s) => !s)} edge="end" size="small"
                                    aria-label={showPass ? 'Şifreyi gizle' : 'Şifreyi göster'}>
                          {showPass ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  },
                }}
              />
              {error && <Alert severity="error">{error}</Alert>}
              <Button type="submit" variant="contained" fullWidth size="large" disableElevation
                      sx={{ py: 1.25, fontSize: 15 }}
                      disabled={busy || !username || !password}>
                {busy ? 'Giriş yapılıyor…' : 'Giriş Yap'}
              </Button>
            </Stack>
          </form>

          <Typography variant="caption" color="text.disabled"
                      sx={{ display: 'block', textAlign: 'center', mt: 4 }}>
            © 2025 JUMBO · Kurumsal Sertifika Yönetimi · v2.1
          </Typography>
        </Box>
      </Box>
      </Box>
  )
}
