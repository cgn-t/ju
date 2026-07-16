import AddIcon from '@mui/icons-material/Add'
import AppsOutlinedIcon from '@mui/icons-material/AppsOutlined'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import SearchIcon from '@mui/icons-material/Search'
import VisibilityIcon from '@mui/icons-material/Visibility'
import {
  Autocomplete, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, Grid,
  IconButton, InputAdornment, MenuItem, Paper, Skeleton, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { AppDependency, Application, AppUser, Domain, Tag, Team } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import ApplicationDetailDrawer from '../components/ApplicationDetailDrawer'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const EMPTY = {
  app_name: '', app_user: '', server_name: '', ip_address: '', dns: '', domain_id: '',
  conf_path: '', log_path: '', control_method: '', start_stop_method: '', required_commands: '',
  service_provider_contact: '', sy_team_id: '', ug_team_id: '', info: '', notes: '', status: 'true',
}

// Anında-oluşturmada yeni etiketin varsayılan kategorileri (mevcut kategorilerle birleşir).
const DEFAULT_CATEGORIES = ['Ürün', 'Ortam', 'Kritiklik']

// Etiket chip'i kategori rengiyle çerçevelenir (renk yoksa nötr); outlined iki temada da okunur.
const tagSx = (t: Tag) => (t.color ? { borderColor: t.color, color: t.color } : undefined)

export default function Applications() {
  useDocumentTitle('Uygulamalar')
  const { canEdit, isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Application | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Application | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [form, setForm] = useState<Record<string, string>>(EMPTY)
  const [formTags, setFormTags] = useState<Tag[]>([])
  const [newTagCategory, setNewTagCategory] = useState('Ürün')

  // Liste kullanıcının ÜYELİĞİNE göre kapsamlıdır (backend RBAC): editor/viewer yalnız kendi
  // SY ekiplerinin uygulamalarını görür; admin/allviewer global. Ayrı bir takım filtresi yok.
  const { data: apps, isLoading, isError, error, refetch } = useQuery<Application[]>({
    queryKey: ['applications', search],
    queryFn: async () => (await api.get('/applications', {
      params: { search: search || undefined },
    })).data,
  })
  const { data: allTags } = useQuery<Tag[]>({
    queryKey: ['tags'],
    queryFn: async () => (await api.get('/tags')).data,
  })
  // Yeni kategori açmak YALNIZ admin yetkisi (backend 403 verir): admin varsayılan önerileri de
  // görür; diğer kullanıcılar yalnız MEVCUT kategorilerden seçebilir.
  const categories = useMemo(() => {
    const existing = (allTags ?? []).map((t) => t.category)
    return Array.from(new Set(isAdmin ? [...DEFAULT_CATEGORIES, ...existing] : existing))
  }, [allTags, isAdmin])
  // Seçili kategori listede yoksa (ör. admin-olmayanda 'Ürün' henüz açılmamış) ilk mevcuta düş.
  const tagCategory = categories.includes(newTagCategory) ? newTagCategory : (categories[0] ?? '')
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
    enabled: formOpen,
  })
  const { data: domains } = useQuery<Domain[]>({
    queryKey: ['domains', ''],
    queryFn: async () => (await api.get('/domains')).data,
    enabled: formOpen,
  })
  // Giriş yapmış kullanıcının SY üyelikleri: editör uygulamayı yalnız KENDİ ekibine
  // atayabilir (backend de aynı kuralı uygular) — liste ona göre daraltılır, yeni kayıtta
  // ilk ekip otomatik seçilir (DomainFormDialog ile aynı desen).
  const { data: me } = useQuery<AppUser>({
    queryKey: ['auth-me'],
    queryFn: async () => (await api.get('/auth/me')).data,
    enabled: formOpen,
  })
  const { data: deps } = useQuery<AppDependency[]>({
    queryKey: ['app-dependencies', editTarget?.id],
    queryFn: async () => (await api.get(`/applications/${editTarget!.id}/dependencies`)).data,
    enabled: formOpen && !!editTarget,
  })

  const [depForm, setDepForm] = useState({ target_domain_id: '', note: '' })
  // YENİ uygulama formunda biriktirilen client bağımlılıkları: kayıt sonrası sırayla POST edilir
  // (backend bağımlılığı app id ister; önce uygulama oluşur, sonra ilişkiler eklenir).
  const [pendingDeps, setPendingDeps] = useState<{ target_domain_id: string; note: string }[]>([])
  useEffect(() => {
    setDepForm({ target_domain_id: '', note: '' })
    setPendingDeps([])
  }, [editTarget, formOpen])

  const invalidateDeps = () => {
    queryClient.invalidateQueries({ queryKey: ['app-dependencies', editTarget?.id] })
    queryClient.invalidateQueries({ queryKey: ['applications'] })
    queryClient.invalidateQueries({ queryKey: ['relationships'] })
  }
  const addDepMutation = useMutation({
    mutationFn: async () => api.post(`/applications/${editTarget!.id}/dependencies`, {
      target_domain_id: Number(depForm.target_domain_id),
      note: depForm.note || null,
    }),
    onSuccess: () => {
      enqueueSnackbar('Bağımlılık eklendi', { variant: 'success' })
      setDepForm({ target_domain_id: '', note: '' })
      invalidateDeps()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const delDepMutation = useMutation({
    mutationFn: async (depId: number) => api.delete(`/applications/dependencies/${depId}`),
    onSuccess: () => { enqueueSnackbar('Bağımlılık silindi', { variant: 'success' }); invalidateDeps() },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  useEffect(() => {
    if (editTarget) {
      setForm({
        app_name: editTarget.app_name ?? '', app_user: editTarget.app_user ?? '',
        server_name: editTarget.server_name ?? '', ip_address: editTarget.ip_address ?? '',
        dns: editTarget.dns ?? '', domain_id: editTarget.domain_id?.toString() ?? '',
        conf_path: editTarget.conf_path ?? '', log_path: editTarget.log_path ?? '',
        control_method: editTarget.control_method ?? '',
        start_stop_method: editTarget.start_stop_method ?? '',
        required_commands: editTarget.required_commands ?? '',
        service_provider_contact: editTarget.service_provider_contact ?? '',
        sy_team_id: editTarget.sy_team_id?.toString() ?? '',
        ug_team_id: editTarget.ug_team_id?.toString() ?? '',
        info: editTarget.info ?? '', notes: editTarget.notes ?? '',
        status: String(editTarget.status),
      })
      setFormTags(editTarget.tags ?? [])
    } else {
      setForm(EMPTY)
      setFormTags([])
    }
  }, [editTarget, formOpen])

  // Yeni kayıt: kullanıcının üye olduğu SY ekibini otomatik seç (birden çoksa ilki;
  // dropdown'dan değiştirilebilir) — DomainFormDialog ile aynı davranış.
  useEffect(() => {
    if (editTarget || !formOpen) return
    const mine = me?.sy_team_ids ?? []
    if (mine.length) setForm((f) => (f.sy_team_id ? f : { ...f, sy_team_id: String(mine[0]) }))
  }, [me, editTarget, formOpen])

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  // Admin tüm SY ekiplerini görür; editör yalnız üye olduğu ekipleri (mevcut sahip her zaman
  // listede kalır ki edit'te değer görünsün) — DomainFormDialog ile aynı kural.
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')
  const mySyIds = new Set(me?.sy_team_ids ?? [])
  const syOptions = isAdmin ? syTeams
    : syTeams.filter((t) => mySyIds.has(t.id) || String(t.id) === form.sy_team_id)

  // Etiket seçimi değişince: freeSolo ile YAZILAN yeni metinler (string) anında oluşturulur
  // (idempotent POST /tags, newTagCategory kategorisiyle), sonra id'ye çevrilip atanır.
  const onTagsChange = async (value: (Tag | string)[]) => {
    const resolved: Tag[] = []
    for (const item of value) {
      if (typeof item === 'string') {
        const name = item.trim()
        if (!name) continue
        if (!tagCategory) {  // hiç kategori yok (admin henüz açmamış) → oluşturma yapılamaz
          enqueueSnackbar('Önce yöneticinin bir etiket kategorisi oluşturması gerekli', { variant: 'warning' })
          continue
        }
        try {
          resolved.push((await api.post('/tags', { name, category: tagCategory })).data)
        } catch (e) { enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }) }
      } else resolved.push(item)
    }
    const seen = new Set<number>()
    setFormTags(resolved.filter((t) => (seen.has(t.id) ? false : (seen.add(t.id), true))))
    queryClient.invalidateQueries({ queryKey: ['tags'] })
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        ...Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === '' ? null : v])),
        domain_id: form.domain_id ? Number(form.domain_id) : null,
        sy_team_id: form.sy_team_id ? Number(form.sy_team_id) : null,
        ug_team_id: form.ug_team_id ? Number(form.ug_team_id) : null,
        status: form.status === 'true',
        tag_ids: formTags.map((t) => t.id),
      }
      if (editTarget) {
        await api.put(`/applications/${editTarget.id}`, body)
        return { depFails: [] as string[] }
      }
      // Yeni kayıt: önce uygulama, sonra formda biriktirilen client bağımlılıkları
      const created = (await api.post<Application>('/applications', body)).data
      const depFails: string[] = []
      for (const dep of pendingDeps) {
        try {
          await api.post(`/applications/${created.id}/dependencies`, {
            target_domain_id: Number(dep.target_domain_id), note: dep.note || null,
          })
        } catch (e) {
          const name = (domains ?? []).find((d) => d.id.toString() === dep.target_domain_id)?.domain
          depFails.push(`${name ?? dep.target_domain_id}: ${apiErrorMessage(e)}`)
        }
      }
      return { depFails }
    },
    onSuccess: ({ depFails }) => {
      enqueueSnackbar(editTarget ? 'Uygulama güncellendi' : 'Uygulama eklendi', { variant: 'success' })
      for (const f of depFails) {
        enqueueSnackbar(`Bağımlılık eklenemedi — ${f}`, { variant: 'warning', autoHideDuration: 6000 })
      }
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      setFormOpen(false)
      setEditTarget(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/applications/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Uygulama silindi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      setDeleteTarget(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Box>
      <PageHeader title="Uygulamalar" subtitle="Uygulama envanteri, sunucu ve domain ilişkileri" />
      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        {canEdit && (
          <Button variant="contained" startIcon={<AddIcon />}
                  onClick={() => { setEditTarget(null); setFormOpen(true) }}>
            Yeni Ekle
          </Button>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <TextField size="small" placeholder="Ara… (uygulama, sunucu, dns, etiket)" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ width: 320 }}
                   slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }} />
      </Box>

      <Paper>
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Skeleton variant="rounded" height={400} />
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Uygulama</TableCell>
                <TableCell>Sunucu</TableCell>
                <TableCell>IP</TableCell>
                <TableCell>DNS</TableCell>
                <TableCell>Domain</TableCell>
                <TableCell>SY</TableCell>
                <TableCell>UG</TableCell>
                <TableCell>Etiketler</TableCell>
                <TableCell>Durum</TableCell>
                <TableCell align="right">İşlemler</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(apps ?? []).map((a) => (
                <TableRow key={a.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>{a.app_name}</TableCell>
                  <TableCell>{a.server_name ?? '—'}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{a.ip_address ?? '—'}</TableCell>
                  <TableCell>{a.dns ?? '—'}</TableCell>
                  <TableCell>{a.domain?.domain ?? '—'}</TableCell>
                  <TableCell>{a.sy_team?.name ?? '—'}</TableCell>
                  <TableCell>{a.ug_team?.name ?? '—'}</TableCell>
                  <TableCell>
                    {(a.tags ?? []).length === 0 ? '—' : (
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, maxWidth: 220 }}>
                        {(a.tags ?? []).map((t) => (
                          <Chip key={t.id} size="small" label={t.name} variant="outlined" sx={tagSx(t)} />
                        ))}
                      </Box>
                    )}
                  </TableCell>
                  <TableCell>
                    <Chip size="small" color={a.status ? 'success' : 'default'}
                          label={a.status ? 'Aktif' : 'Pasif'} />
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap', width: '1%' }}>
                    <Box sx={{ display: 'inline-flex', flexWrap: 'nowrap', gap: 0.25, whiteSpace: 'nowrap' }}>
                      <Tooltip title="Detay">
                        <IconButton size="small" color="info" onClick={() => setDetailId(a.id)}>
                          <VisibilityIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {canEdit && (
                        <>
                          <Tooltip title="Düzenle">
                            <IconButton size="small" color="primary"
                                        onClick={() => { setEditTarget(a); setFormOpen(true) }}>
                              <EditIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Sil">
                            <IconButton size="small" color="error" onClick={() => setDeleteTarget(a)}>
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </>
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
              {(apps ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={10} align="center" sx={{ py: 7, color: 'text.secondary' }}>
                    <AppsOutlinedIcon sx={{ fontSize: 40, opacity: 0.35, mb: 1 }} />
                    <Typography variant="body2">Henüz uygulama kaydı yok.</Typography>
                    {canEdit && (
                      <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                        “Yeni Ekle” ile ilk uygulamayı ekleyin.
                      </Typography>
                    )}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </Paper>

      <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editTarget ? `Uygulama Düzenle — ${editTarget.app_name}` : 'Yeni Uygulama'}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Uygulama Adı *" fullWidth size="small" value={form.app_name} onChange={set('app_name')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Uygulama Kullanıcısı" fullWidth size="small" value={form.app_user} onChange={set('app_user')} /></Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <TextField label="Sunucu Adı *" fullWidth size="small" value={form.server_name}
                         onChange={set('server_name')} error={!form.server_name.trim()}
                         helperText={!form.server_name.trim() ? 'Zorunlu alan' : undefined} />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}><TextField label="IP Adresi" fullWidth size="small" value={form.ip_address} onChange={set('ip_address')} /></Grid>
            <Grid size={{ xs: 12, sm: 4 }}><TextField label="DNS" fullWidth size="small" value={form.dns} onChange={set('dns')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField select label="Bağlı Domain" fullWidth size="small" value={form.domain_id} onChange={set('domain_id')}>
                <MenuItem value="">—</MenuItem>
                {(domains ?? []).map((d) => <MenuItem key={d.id} value={d.id.toString()}>{d.domain}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              {/* SY Takımı ZORUNLU (yeni + düzenleme): sahipsiz uygulama bildirim/onay akışının dışında kalıyordu.
                  Editör yalnız ÜYE OLDUĞU ekibe atayabilir; sahiplik değişimi admin işi → edit'te kilitli. */}
              <TextField select label="SY Takımı *" fullWidth size="small"
                         value={form.sy_team_id} onChange={set('sy_team_id')}
                         disabled={!isAdmin && !!editTarget}
                         error={!form.sy_team_id}
                         helperText={!form.sy_team_id ? 'Zorunlu alan'
                           : !isAdmin && editTarget ? 'Sahipliği yalnız admin değiştirebilir' : undefined}>
                {syOptions.map((t) => <MenuItem key={t.id} value={t.id.toString()}>{t.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <TextField select label="UG Takımı" fullWidth size="small" value={form.ug_team_id}
                         onChange={set('ug_team_id')} disabled={!isAdmin && !!editTarget}>
                <MenuItem value="">—</MenuItem>
                {(teams ?? []).filter((t) => t.type === 'UG').map((t) => <MenuItem key={t.id} value={t.id.toString()}>{t.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Config Path" fullWidth size="small" value={form.conf_path} onChange={set('conf_path')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Log Path" fullWidth size="small" value={form.log_path} onChange={set('log_path')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Kontrol Yöntemi" fullWidth size="small" value={form.control_method} onChange={set('control_method')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Start/Stop Yöntemi" fullWidth size="small" value={form.start_stop_method} onChange={set('start_stop_method')} /></Grid>
            <Grid size={{ xs: 12, sm: 6 }}><TextField label="Gerekli Komutlar" fullWidth size="small" value={form.required_commands} onChange={set('required_commands')} /></Grid>
            <Grid size={{ xs: 12, sm: 3 }}><TextField label="Servis Sağlayıcı İletişim" fullWidth size="small" value={form.service_provider_contact} onChange={set('service_provider_contact')} /></Grid>
            <Grid size={{ xs: 12, sm: 3 }}>
              <TextField select label="Durum" fullWidth size="small" value={form.status} onChange={set('status')}>
                <MenuItem value="true">Aktif</MenuItem>
                <MenuItem value="false">Pasif</MenuItem>
              </TextField>
            </Grid>
            <Grid size={{ xs: 12 }}>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: 'flex-start' }}>
                <Autocomplete multiple freeSolo fullWidth size="small" options={allTags ?? []}
                              value={formTags} onChange={(_, v) => onTagsChange(v)}
                              groupBy={(o) => (typeof o === 'string' ? '' : o.category)}
                              getOptionLabel={(o) => (typeof o === 'string' ? o : o.name)}
                              isOptionEqualToValue={(o, v) =>
                                typeof o !== 'string' && typeof v !== 'string' && o.id === v.id}
                              renderValue={(value, getItemProps) => value.map((option, index) => {
                                const { key, ...rest } = getItemProps({ index })
                                return <Chip key={key} {...rest} size="small"
                                             label={typeof option === 'string' ? option : option.name}
                                             variant="outlined"
                                             sx={typeof option === 'string' ? undefined : tagSx(option)} />
                              })}
                              renderInput={(params) => <TextField {...params} label="Etiketler"
                                helperText="Listeden seç ya da yaz + Enter → yeni etiket oluşturulur" />}
                              sx={{ flexGrow: 1 }} />
                <TextField select size="small" label="Yeni etiket kategorisi" value={tagCategory}
                           onChange={(e) => setNewTagCategory(e.target.value)} sx={{ minWidth: 190 }}
                           helperText="Yazarak oluşturulan etiketin kategorisi">
                  {categories.length === 0 && <MenuItem value="" disabled>Kategori yok</MenuItem>}
                  {categories.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
                </TextField>
              </Stack>
            </Grid>
            <Grid size={{ xs: 12 }}><TextField label="Bilgi / Notlar" fullWidth size="small" multiline rows={2} value={form.notes} onChange={set('notes')} /></Grid>
          </Grid>

          {editTarget ? (
            <Box sx={{ mt: 3 }}>
              <Divider sx={{ mb: 2 }} />
              <Typography variant="subtitle2" gutterBottom>Dış Bağımlılıklar (client)</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                Bu uygulamanın <b>client olarak bağlandığı</b> hedef domainler. İzlenen sertifika <b>otomatik</b>
                olarak hedef domainin server sertifikasıdır (ayrıca seçmenize gerek yok). O sertifika yenilendiğinde
                bu uygulamanın SY ekibine <b>client değişikliği</b> için devir önerisi gider. İlişki haritasında
                turuncu kesikli okla görünür.
              </Typography>

              <Stack spacing={1} sx={{ mb: 2 }}>
                {(deps ?? []).map((d) => (
                  <Paper key={d.id} variant="outlined" sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                    <ArrowForwardIcon fontSize="small" sx={{ color: '#ff9800' }} />
                    <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{d.target_domain_name ?? `#${d.target_domain_id}`}</Typography>
                      {(d.client_cert_name || d.note) && (
                        <Typography variant="caption" color="text.secondary" noWrap
                                    title={d.client_cert_ski ? `SKI: ${d.client_cert_ski}` : undefined}>
                          {d.client_cert_name ? `mTLS: ${d.client_cert_name}` : ''}
                          {d.client_cert_name && d.client_cert_ski ? ` [${d.client_cert_ski.slice(0, 23)}…]` : ''}
                          {d.client_cert_name && d.note ? ' — ' : ''}
                          {d.note ?? ''}
                        </Typography>
                      )}
                    </Box>
                    {canEdit && (
                      <Tooltip title="Bağımlılığı sil">
                        <IconButton size="small" color="error" onClick={() => delDepMutation.mutate(d.id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Paper>
                ))}
                {(deps ?? []).length === 0 && (
                  <Typography variant="body2" color="text.secondary">Dış bağımlılık tanımlı değil.</Typography>
                )}
              </Stack>

              {canEdit && (
                <Grid container spacing={1} sx={{ alignItems: 'center' }}>
                  <Grid size={{ xs: 12, sm: 6 }}>
                    <TextField select label="Hedef Domain *" fullWidth size="small"
                               value={depForm.target_domain_id}
                               onChange={(e) => setDepForm((f) => ({ ...f, target_domain_id: e.target.value }))}>
                      <MenuItem value="">—</MenuItem>
                      {(domains ?? []).filter((d) => d.id !== editTarget.domain_id)
                        .map((d) => <MenuItem key={d.id} value={d.id.toString()}>{d.domain}</MenuItem>)}
                    </TextField>
                  </Grid>
                  <Grid size={{ xs: 12, sm: 4 }}>
                    <TextField label="Not" fullWidth size="small" value={depForm.note}
                               onChange={(e) => setDepForm((f) => ({ ...f, note: e.target.value }))} />
                  </Grid>
                  <Grid size={{ xs: 12, sm: 2 }}>
                    <Button fullWidth variant="outlined" startIcon={<AddIcon />}
                            disabled={!depForm.target_domain_id || addDepMutation.isPending}
                            onClick={() => addDepMutation.mutate()}>Ekle</Button>
                  </Grid>
                </Grid>
              )}
            </Box>
          ) : (
            <Box sx={{ mt: 3 }}>
              <Divider sx={{ mb: 2 }} />
              <Typography variant="subtitle2" gutterBottom>Dış Bağımlılıklar (client)</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
                Bu uygulamanın <b>client olarak bağlanacağı</b> hedef domainleri şimdiden ekleyebilirsiniz —
                uygulama kaydedilirken ilişkiler de oluşturulur. İzlenen sertifika otomatik olarak hedef
                domainin server sertifikasıdır.
              </Typography>

              <Stack spacing={1} sx={{ mb: 2 }}>
                {pendingDeps.map((d, i) => (
                  <Paper key={d.target_domain_id} variant="outlined"
                         sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                    <ArrowForwardIcon fontSize="small" sx={{ color: '#ff9800' }} />
                    <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>
                        {(domains ?? []).find((x) => x.id.toString() === d.target_domain_id)?.domain
                          ?? `#${d.target_domain_id}`}
                      </Typography>
                      {d.note && (
                        <Typography variant="caption" color="text.secondary" noWrap>{d.note}</Typography>
                      )}
                    </Box>
                    <Tooltip title="Listeden çıkar">
                      <IconButton size="small" color="error"
                                  onClick={() => setPendingDeps((l) => l.filter((_, j) => j !== i))}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Paper>
                ))}
                {pendingDeps.length === 0 && (
                  <Typography variant="body2" color="text.secondary">Eklenecek bağımlılık yok.</Typography>
                )}
              </Stack>

              <Grid container spacing={1} sx={{ alignItems: 'center' }}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField select label="Hedef Domain" fullWidth size="small"
                             value={depForm.target_domain_id}
                             onChange={(e) => setDepForm((f) => ({ ...f, target_domain_id: e.target.value }))}>
                    <MenuItem value="">—</MenuItem>
                    {(domains ?? [])
                      .filter((d) => d.id.toString() !== form.domain_id
                                     && !pendingDeps.some((p) => p.target_domain_id === d.id.toString()))
                      .map((d) => <MenuItem key={d.id} value={d.id.toString()}>{d.domain}</MenuItem>)}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 12, sm: 4 }}>
                  <TextField label="Not" fullWidth size="small" value={depForm.note}
                             onChange={(e) => setDepForm((f) => ({ ...f, note: e.target.value }))} />
                </Grid>
                <Grid size={{ xs: 12, sm: 2 }}>
                  <Button fullWidth variant="outlined" startIcon={<AddIcon />}
                          disabled={!depForm.target_domain_id}
                          onClick={() => {
                            setPendingDeps((l) => [...l, { ...depForm }])
                            setDepForm({ target_domain_id: '', note: '' })
                          }}>Ekle</Button>
                </Grid>
              </Grid>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormOpen(false)}>Vazgeç</Button>
          <Button variant="contained"
                  disabled={!form.app_name || saveMutation.isPending || !form.sy_team_id
                            || !form.server_name.trim()}
                  onClick={() => saveMutation.mutate()}>
            {editTarget ? 'Kaydet' : 'Ekle'}
          </Button>
        </DialogActions>
      </Dialog>

      <ApplicationDetailDrawer appId={detailId} onClose={() => setDetailId(null)} />

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Uygulama Sil</DialogTitle>
        <DialogContent>
          <Typography><b>{deleteTarget?.app_name}</b> silinecek. Emin misiniz?</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Vazgeç</Button>
          <Button color="error" variant="contained"
                  onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}>
            Sil
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
