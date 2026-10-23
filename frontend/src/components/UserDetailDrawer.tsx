import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import PersonSearchIcon from '@mui/icons-material/PersonSearch'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, Autocomplete, Box, Button, Chip, Divider, Drawer, IconButton, MenuItem, Stack, TextField, Tooltip,
  Typography,
} from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { AppUser, Team } from '../api/types'
import { MONO_FONT } from '../theme'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { missingScope, ROLE_CHIP, ROLE_OPTIONS, TEAM_TYPE_COLOR, TEAM_TYPE_LABEL } from '../utils/peopleLabels'
import { ConfirmDialog, Meta, metaGridSx, PersonAvatar, RecentActivity, SectionTitle } from './PeopleShared'

/** Kullanıcı detayı: profil, rol ve kapsam, takımlar, son işlemler; pasife alma ve silme. */
export default function UserDetailDrawer({ user, teams, onClose, onChanged }: {
  user: AppUser | null; teams: Team[]; onClose: () => void; onChanged: () => void
}) {
  const { enqueueSnackbar } = useSnackbar()
  const navigate = useNavigate()
  const [editProfile, setEditProfile] = useState(false)
  const [profile, setProfile] = useState({ full_name: '', email: '', password: '' })
  const [editTeams, setEditTeams] = useState(false)
  const [teamSel, setTeamSel] = useState<number[]>([])
  const [confirm, setConfirm] = useState<'delete' | 'deactivate' | null>(null)

  useEffect(() => {
    setEditProfile(false); setEditTeams(false); setConfirm(null)
    setProfile({ full_name: user?.full_name ?? '', email: user?.email ?? '', password: '' })
    setTeamSel(user?.team_ids ?? [])
  }, [user?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  const update = useMutation({
    mutationFn: async (body: Record<string, unknown>) => api.put(`/users/${user!.id}`, body),
    onSuccess: (_d, body) => {
      onChanged()
      if ('full_name' in body || 'email' in body) { setEditProfile(false); enqueueSnackbar('Profil güncellendi', { variant: 'success' }) }
      if ('is_active' in body) enqueueSnackbar(body.is_active ? 'Kullanıcı aktifleştirildi' : 'Kullanıcı pasife alındı', { variant: 'info' })
      setConfirm(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const saveTeams = useMutation({
    mutationFn: async () => {
      const before = new Set(user!.team_ids ?? [])
      const after = new Set(teamSel)
      await Promise.all([
        ...[...after].filter((id) => !before.has(id)).map((tid) => api.post(`/teams/${tid}/members`, { user_id: user!.id })),
        ...[...before].filter((id) => !after.has(id)).map((tid) => api.delete(`/teams/${tid}/members/${user!.id}`)),
      ])
    },
    onSuccess: () => { enqueueSnackbar('Takımlar güncellendi', { variant: 'success' }); setEditTeams(false); onChanged() },
    onError: (e) => { enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }); onChanged() },
  })
  const remove = useMutation({
    mutationFn: async () => api.delete(`/users/${user!.id}`),
    onSuccess: () => { enqueueSnackbar('Kullanıcı silindi', { variant: 'success' }); setConfirm(null); onClose(); onChanged() },
    onError: (e) => { enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }); setConfirm(null) },
  })

  const u = user
  const userTeams = teams.filter((t) => (u?.team_ids ?? []).includes(t.id))
  const isLdap = u?.auth_source === 'ldap'

  return (
    <Drawer anchor="right" open={u !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 620 } } } }}>
      {u && (
        <Box sx={{ p: 3 }}>
          <Stack spacing={2.25}>
            {/* Başlık */}
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
              <PersonAvatar fullName={u.full_name} username={u.username} size={48} muted={!u.is_active} />
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="h6" sx={{ lineHeight: 1.3, wordBreak: 'break-word' }}>{u.full_name || u.username}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ fontFamily: MONO_FONT }}>{u.username}</Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.75 }}>
                  <Chip size="small" color={ROLE_CHIP[u.role]?.color ?? 'default'} label={ROLE_CHIP[u.role]?.label ?? u.role} />
                  <Chip size="small" variant="outlined" label={isLdap ? 'LDAP' : 'Lokal'} />
                  <Chip size="small" variant="outlined" color={u.is_active ? 'success' : 'default'} label={u.is_active ? 'Aktif' : 'Pasif'} />
                </Box>
              </Box>
              <Tooltip title="Kapat"><IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton></Tooltip>
            </Box>

            <Box sx={metaGridSx}>
              <Meta label="E-posta" wide>{u.email || '—'}</Meta>
              <Meta label="Son giriş">
                {u.last_login ? <>
                  <Box sx={{ fontVariantNumeric: 'tabular-nums' }}>{formatAuditTime(u.last_login)}</Box>
                  <Typography variant="caption" color="text.secondary">{relativeTime(u.last_login)}</Typography>
                </> : 'Hiç giriş yapmadı'}
              </Meta>
              <Meta label="Oluşturulma">{u.created_at ? formatAuditTime(u.created_at) : '—'}</Meta>
            </Box>
            {isLdap && (
              <Button variant="outlined" size="small" startIcon={<PersonSearchIcon />} sx={{ alignSelf: 'flex-start' }}
                      onClick={() => navigate(`/profile/${u.id}`)}>
                LDAP bilgilerini gör
              </Button>
            )}

            {/* Rol ve kapsam */}
            <Box>
              <SectionTitle>Rol ve Erişim</SectionTitle>
              <TextField select size="small" fullWidth value={u.role}
                         onChange={(e) => update.mutate({ role: e.target.value })}
                         helperText={ROLE_OPTIONS.find((o) => o.value === u.role)?.hint}>
                {ROLE_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
              </TextField>
              {missingScope(u) && (
                <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mt: 1, py: 0.25 }}
                       action={<Button color="inherit" size="small" sx={{ whiteSpace: 'nowrap' }} onClick={() => setEditTeams(true)}>SY ekibi ata</Button>}>
                  <b>{ROLE_CHIP[u.role].label}</b> rolü takım-kapsamlıdır; SY ekibi olmadan hiçbir veriyi göremez.
                </Alert>
              )}
            </Box>

            {/* Takımlar */}
            <Box>
              <SectionTitle action={!editTeams && (
                <Button size="small" startIcon={<EditIcon />} onClick={() => { setTeamSel(u.team_ids ?? []); setEditTeams(true) }}>
                  Düzenle
                </Button>
              )}>Takımlar · {userTeams.length}</SectionTitle>
              {editTeams ? (
                <Stack spacing={1}>
                  <Autocomplete
                    multiple size="small" options={teams} value={teams.filter((t) => teamSel.includes(t.id))}
                    getOptionLabel={(t) => `${t.name} · ${TEAM_TYPE_LABEL[t.type] ?? t.type}`}
                    isOptionEqualToValue={(a, b) => a.id === b.id}
                    onChange={(_, val) => setTeamSel(val.map((t) => t.id))}
                    renderInput={(p) => <TextField {...p} placeholder="Takım seç" autoFocus />} />
                  <Typography variant="caption" color="text.secondary">
                    SY üyeliği kapsam belirler; ADMIN/VIEWER/UG üyeliği yalnız bilgi amaçlıdır, rol vermez.
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                    <Button size="small" onClick={() => setEditTeams(false)}>Vazgeç</Button>
                    <Button size="small" variant="contained" disabled={saveTeams.isPending} onClick={() => saveTeams.mutate()}>Kaydet</Button>
                  </Stack>
                </Stack>
              ) : userTeams.length ? (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
                  {userTeams.map((t) => (
                    <Chip key={t.id} size="small" variant="outlined" color={TEAM_TYPE_COLOR[t.type] ?? 'default'}
                          label={`${t.name} · ${t.type}`} />
                  ))}
                </Box>
              ) : <Typography variant="body2" color="text.secondary">Hiçbir takımda değil.</Typography>}
            </Box>

            {/* Profil */}
            <Box>
              <SectionTitle action={!editProfile && (
                <Button size="small" startIcon={<EditIcon />} onClick={() => setEditProfile(true)}>Düzenle</Button>
              )}>Profil</SectionTitle>
              {editProfile ? (
                <Stack spacing={1.5}>
                  {isLdap && (
                    <Alert severity="info" sx={{ py: 0.25 }}>LDAP kullanıcısı: Ad Soyad ve e-posta her girişte dizinden yeniden alınır.</Alert>
                  )}
                  <TextField size="small" label="Ad Soyad" value={profile.full_name}
                             onChange={(e) => setProfile((p) => ({ ...p, full_name: e.target.value }))} />
                  <TextField size="small" label="E-posta" value={profile.email}
                             onChange={(e) => setProfile((p) => ({ ...p, email: e.target.value }))} />
                  {!isLdap && (
                    <TextField size="small" label="Yeni şifre" type="password" value={profile.password}
                               helperText="Boş bırakılırsa şifre değişmez"
                               onChange={(e) => setProfile((p) => ({ ...p, password: e.target.value }))} />
                  )}
                  <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                    <Button size="small" onClick={() => setEditProfile(false)}>Vazgeç</Button>
                    <Button size="small" variant="contained" disabled={update.isPending}
                            onClick={() => update.mutate({
                              full_name: profile.full_name.trim() || null, email: profile.email.trim() || null,
                              ...(profile.password ? { password: profile.password } : {}),
                            })}>Kaydet</Button>
                  </Stack>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {isLdap ? 'Kimlik LDAP üzerinden doğrulanır.' : 'Lokal hesap — şifre JUMBO içinde tutulur.'}
                </Typography>
              )}
            </Box>

            <RecentActivity params={{ actor: u.username }} empty="Bu kullanıcının kayıtlı işlemi yok."
                            auditLink={`/settings?tab=audit&audit_f_user=${encodeURIComponent(u.username)}`} />

            <Divider />
            <Stack direction="row" spacing={1}>
              <Button variant="outlined" color={u.is_active ? 'warning' : 'success'}
                      onClick={() => u.is_active ? setConfirm('deactivate') : update.mutate({ is_active: true })}>
                {u.is_active ? 'Pasife Al' : 'Aktifleştir'}
              </Button>
              <Box sx={{ flexGrow: 1 }} />
              <Button color="error" startIcon={<DeleteIcon />} onClick={() => setConfirm('delete')}>Kullanıcıyı Sil</Button>
            </Stack>
          </Stack>

          <ConfirmDialog open={confirm === 'deactivate'} title="Kullanıcı pasife alınsın mı?" confirmLabel="Pasife Al"
                         busy={update.isPending} onClose={() => setConfirm(null)}
                         onConfirm={() => update.mutate({ is_active: false })}>
            <b>{u.full_name || u.username}</b> artık giriş yapamaz. Takım üyelikleri ve geçmişi korunur; istediğinizde
            yeniden aktifleştirebilirsiniz.
          </ConfirmDialog>
          <ConfirmDialog open={confirm === 'delete'} title="Kullanıcı silinsin mi?" confirmLabel="Sil" danger
                         busy={remove.isPending} onClose={() => setConfirm(null)} onConfirm={() => remove.mutate()}>
            <b>{u.full_name || u.username}</b> ({u.username}) kalıcı olarak silinir ve takım üyelikleri kaldırılır.
            Audit Log kayıtları korunur. Geçici erişim kesmek için <b>Pasife Al</b> tercih edilmelidir.
          </ConfirmDialog>
        </Box>
      )}
    </Drawer>
  )
}
