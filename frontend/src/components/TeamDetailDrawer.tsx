import AddIcon from '@mui/icons-material/Add'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import PersonRemoveIcon from '@mui/icons-material/PersonRemove'
import {
  Alert, Autocomplete, Box, Button, Chip, Divider, Drawer, IconButton, Skeleton, Stack, TextField, Tooltip,
  Typography,
} from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { AppUser, Team, TeamMember } from '../api/types'
import { includesTr, TEAM_TYPE_COLOR, TEAM_TYPE_LABEL } from '../utils/peopleLabels'
import { ConfirmDialog, Meta, metaGridSx, PersonAvatar, RecentActivity, SectionTitle } from './PeopleShared'

/** Ekip detayı: bilgiler (ad, bildirim e-postası), üyeler (ekle/çıkar), son işlemler, silme. */
export default function TeamDetailDrawer({ team, onClose, onChanged }: {
  team: Team | null; onClose: () => void; onChanged: () => void
}) {
  const { enqueueSnackbar } = useSnackbar()
  const [edit, setEdit] = useState(false)
  const [form, setForm] = useState({ name: '', email: '' })
  const [toAdd, setToAdd] = useState<AppUser | null>(null)
  const [memberQ, setMemberQ] = useState('')
  const [confirm, setConfirm] = useState<{ kind: 'delete' } | { kind: 'remove'; member: TeamMember } | null>(null)

  useEffect(() => {
    setEdit(false); setToAdd(null); setMemberQ(''); setConfirm(null)
    setForm({ name: team?.name ?? '', email: team?.email ?? '' })
  }, [team?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  const { data: members, isLoading } = useQuery<TeamMember[]>({
    queryKey: ['team-members', team?.id],
    queryFn: async () => (await api.get(`/teams/${team!.id}/members`)).data,
    enabled: !!team,
  })
  const { data: users } = useQuery<AppUser[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
    enabled: !!team,
  })
  const memberIds = useMemo(() => new Set((members ?? []).map((m) => m.id)), [members])
  const candidates = (users ?? []).filter((u) => !memberIds.has(u.id))
  const shownMembers = (members ?? []).filter((m) => includesTr([m.username, m.full_name, m.email], memberQ))

  const save = useMutation({
    mutationFn: async () => api.put(`/teams/${team!.id}`, { name: form.name.trim(), email: form.email.trim() || null }),
    onSuccess: () => { enqueueSnackbar('Ekip güncellendi', { variant: 'success' }); setEdit(false); onChanged() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const add = useMutation({
    mutationFn: async (userId: number) => api.post(`/teams/${team!.id}/members`, { user_id: userId }),
    onSuccess: () => { enqueueSnackbar('Üye eklendi', { variant: 'success' }); setToAdd(null); onChanged() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const removeMember = useMutation({
    mutationFn: async (userId: number) => api.delete(`/teams/${team!.id}/members/${userId}`),
    onSuccess: () => { enqueueSnackbar('Üyelikten çıkarıldı', { variant: 'info' }); setConfirm(null); onChanged() },
    onError: (e) => { enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }); setConfirm(null) },
  })
  const remove = useMutation({
    mutationFn: async () => api.delete(`/teams/${team!.id}`),
    onSuccess: () => { enqueueSnackbar('Ekip silindi', { variant: 'info' }); setConfirm(null); onClose(); onChanged() },
    onError: (e) => { enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }); setConfirm(null) },
  })

  const t = team
  const system = t?.type === 'ADMIN' || t?.type === 'VIEWER'
  const owns = (t?.domain_count ?? 0) + (t?.app_count ?? 0) > 0

  return (
    <Drawer anchor="right" open={t !== null} onClose={onClose} slotProps={{ paper: { sx: { width: { xs: '100%', sm: 620 } } } }}>
      {t && (
        <Box sx={{ p: 3 }}>
          <Stack spacing={2.25}>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.6 }}>Ekip</Typography>
                <Typography variant="h6" sx={{ lineHeight: 1.3, wordBreak: 'break-word' }}>{t.name}</Typography>
                <Chip size="small" sx={{ mt: 0.75 }} color={TEAM_TYPE_COLOR[t.type] ?? 'default'} label={TEAM_TYPE_LABEL[t.type] ?? t.type} />
              </Box>
              <Tooltip title="Kapat"><IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton></Tooltip>
            </Box>

            <Box sx={metaGridSx}>
              <Meta label="Üye">{t.member_count ?? 0}</Meta>
              <Meta label="Domain">{t.domain_count ?? 0}</Meta>
              <Meta label="Uygulama">{t.app_count ?? 0}</Meta>
              <Meta label="Bildirim adresi">{t.email ? t.email.split(/[,;]/).filter((s) => s.trim()).length : 0}</Meta>
            </Box>

            {t.type === 'SY' && !t.email && (
              <Alert severity="warning" sx={{ py: 0.25 }}
                     action={!edit && <Button color="inherit" size="small" onClick={() => setEdit(true)}>E-posta ekle</Button>}>
                Bildirim e-postası yok — bu ekibin domainleri için süre uyarısı gönderilemez.
              </Alert>
            )}
            {t.type !== 'SY' && (
              <Alert severity="info" sx={{ py: 0.25 }}>
                {system ? 'Sistem ekibi: silinemez, tipi değişmez. ' : ''}
                Bu ekibin üyeliği yalnız bilgi amaçlıdır; rol ya da veri kapsamı vermez (rol Kullanıcılar ekranından atanır).
              </Alert>
            )}

            {/* Bilgiler */}
            <Box>
              <SectionTitle action={!edit && <Button size="small" startIcon={<EditIcon />} onClick={() => setEdit(true)}>Düzenle</Button>}>
                Ekip Bilgileri
              </SectionTitle>
              {edit ? (
                <Stack spacing={1.5}>
                  <TextField size="small" label="Ekip Adı" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                  <TextField size="small" label="Bildirim E-postası" value={form.email} autoFocus={!!t.name}
                             placeholder="ör. moneytalks@banka.local, noc@banka.local"
                             helperText="Birden çok adresi virgülle ayırın."
                             onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
                  <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end' }}>
                    <Button size="small" onClick={() => { setEdit(false); setForm({ name: t.name, email: t.email ?? '' }) }}>Vazgeç</Button>
                    <Button size="small" variant="contained" disabled={!form.name.trim() || save.isPending} onClick={() => save.mutate()}>Kaydet</Button>
                  </Stack>
                </Stack>
              ) : (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {t.email
                    ? t.email.split(/[,;]/).map((s) => s.trim()).filter(Boolean).map((m) => <Chip key={m} size="small" variant="outlined" label={m} />)
                    : <Typography variant="body2" color="text.secondary">Bildirim e-postası tanımlı değil.</Typography>}
                </Box>
              )}
            </Box>

            {/* Üyeler */}
            <Box>
              <SectionTitle>Üyeler · {members?.length ?? t.member_count ?? 0}</SectionTitle>
              <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
                <Autocomplete
                  size="small" sx={{ flexGrow: 1 }} options={candidates} value={toAdd}
                  getOptionLabel={(u) => u.full_name ? `${u.full_name} (${u.username})` : u.username}
                  isOptionEqualToValue={(a, b) => a.id === b.id}
                  onChange={(_, val) => setToAdd(val)}
                  renderInput={(p) => <TextField {...p} placeholder="Kullanıcı ekle (ad soyad / kullanıcı adı)" />} />
                <Button variant="contained" startIcon={<AddIcon />} disabled={!toAdd || add.isPending}
                        onClick={() => toAdd && add.mutate(toAdd.id)}>Ekle</Button>
              </Stack>
              {(members?.length ?? 0) > 6 && (
                <TextField size="small" fullWidth placeholder="Üyelerde ara…" value={memberQ} sx={{ mb: 1 }}
                           onChange={(e) => setMemberQ(e.target.value)} />
              )}
              {isLoading && <Skeleton height={80} />}
              {!isLoading && !members?.length && (
                <Typography variant="body2" color="text.secondary">
                  Bu ekibin üyesi yok.{t.type === 'SY' ? ' Editör/İzleyici rolündeki kullanıcılar bu ekibin verisini görmek için üye olmalı.' : ''}
                </Typography>
              )}
              <Box sx={{ border: shownMembers.length ? '1px solid' : 'none', borderColor: 'divider', borderRadius: 1.5,
                         maxHeight: 360, overflowY: 'auto' }}>
                {shownMembers.map((m, i) => (
                  <Box key={m.id} sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: 1.5, py: 0.75,
                                        borderTop: i ? '1px solid' : 'none', borderColor: 'divider' }}>
                    <PersonAvatar fullName={m.full_name} username={m.username} size={28} />
                    <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{m.full_name || m.username}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap component="div">
                        {m.full_name ? m.username : ''}{m.full_name && m.email ? ' · ' : ''}{m.email ?? ''}
                      </Typography>
                    </Box>
                    <Tooltip title="Üyelikten çıkar">
                      <IconButton size="small" color="error" onClick={() => setConfirm({ kind: 'remove', member: m })}>
                        <PersonRemoveIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                ))}
              </Box>
            </Box>

            <RecentActivity params={{ table_name: 'teams,user_teams', record_id: String(t.id) }}
                            empty="Bu ekip için kayıtlı işlem yok."
                            auditLink={`/settings?tab=audit&audit_hist_t=teams,user_teams&audit_hist_id=${t.id}`} />

            <Divider />
            <Stack direction="row">
              <Box sx={{ flexGrow: 1 }} />
              <Tooltip title={system ? 'Sistem ekibi — silinemez' : owns ? 'Domain/uygulama sahibi ekip silinemez; önce sahipliği devredin' : ''}>
                <span>
                  <Button color="error" startIcon={<DeleteIcon />} disabled={system || owns}
                          onClick={() => setConfirm({ kind: 'delete' })}>Ekibi Sil</Button>
                </span>
              </Tooltip>
            </Stack>
          </Stack>

          <ConfirmDialog open={confirm?.kind === 'remove'} title="Üyelikten çıkarılsın mı?" confirmLabel="Çıkar" danger
                         busy={removeMember.isPending} onClose={() => setConfirm(null)}
                         onConfirm={() => confirm?.kind === 'remove' && removeMember.mutate(confirm.member.id)}>
            {confirm?.kind === 'remove' && <>
              <b>{confirm.member.full_name || confirm.member.username}</b> <b>{t.name}</b> ekibinden çıkarılır.
              {t.type === 'SY' && ' Editör/İzleyici rolündeyse bu ekibin domain ve uygulamalarını artık göremez.'}
            </>}
          </ConfirmDialog>
          <ConfirmDialog open={confirm?.kind === 'delete'} title="Ekip silinsin mi?" confirmLabel="Sil" danger
                         busy={remove.isPending} onClose={() => setConfirm(null)} onConfirm={() => remove.mutate()}>
            <b>{t.name}</b> silinir ve {t.member_count ?? 0} üyelik kaldırılır. Audit Log kayıtları korunur.
          </ConfirmDialog>
        </Box>
      )}
    </Drawer>
  )
}
