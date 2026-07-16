import LogoutIcon from '@mui/icons-material/Logout'
import GroupsIcon from '@mui/icons-material/Groups'
import { Box, Button, Paper, Stack, Typography } from '@mui/material'
import { useAuth } from '../auth/AuthContext'

/**
 * Takıma atanmamış (effective role 'none') kullanıcıya gösterilir. RBAC: LDAP ile giriş serbesttir
 * ama bir takıma üye olana kadar hiçbir içerik görünmez. Yönetici, kullanıcıyı bir takıma ekler.
 */
export default function NoTeamScreen() {
  const { username, fullName, logout } = useAuth()
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', p: 2 }}>
      <Paper variant="outlined" sx={{ maxWidth: 520, width: '100%', p: 4, textAlign: 'center' }}>
        <GroupsIcon color="disabled" sx={{ fontSize: 56, mb: 1 }} />
        <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>
          Henüz bir takıma atanmadınız
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 1 }}>
          <strong>{fullName || username}</strong> olarak giriş yaptınız. JUMBO'da içerik görebilmek ve
          işlem yapabilmek için bir takıma üye olmanız gerekir.
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          Yöneticiniz sizi bir <strong>SY</strong> (kendi domainleriniz), <strong>İzleyici</strong>
          {' '}(salt-okur) veya <strong>Yönetici</strong> takımına ekleyene kadar bu ekranı görürsünüz.
        </Typography>
        <Stack direction="row" spacing={1} sx={{ justifyContent: 'center' }}>
          <Button variant="outlined" color="inherit" startIcon={<LogoutIcon />} onClick={logout}>
            Çıkış Yap
          </Button>
        </Stack>
      </Paper>
    </Box>
  )
}
