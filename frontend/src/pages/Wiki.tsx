import AddIcon from '@mui/icons-material/Add'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import SearchIcon from '@mui/icons-material/Search'
import {
  Autocomplete, Box, Button, ButtonBase, Dialog, DialogActions, DialogContent, DialogTitle, InputAdornment,
  List, ListItemButton, ListItemText, ListSubheader, Paper, Skeleton, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import Markdown from '../components/Markdown'
import PageHeader from '../components/PageHeader'
import { ConfirmDialog } from '../components/PeopleShared'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { foldText } from '../utils/textMatch'

export type WikiPage = {
  id: number; slug: string; title: string; category: string; body: string
  sort_order: number; updated_by: string | null; updated_at: string | null
}
type Draft = { id?: number; title: string; category: string; sort_order: number; body: string }

const EMPTY: Draft = { title: '', category: '', sort_order: 0, body: '' }

// Arama: her kelime başlıkta, kategoride ya da metinde geçmeli (harf/Türkçe karakter duyarsız)
function matches(p: WikiPage, q: string) {
  const hay = foldText(`${p.title} ${p.category} ${p.body}`)
  return foldText(q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w))
}

/** Kullanım Kılavuzu: herkes okur, yönetici sayfa ekler/düzenler/siler. AI asistanı da buradan cevaplar. */
export default function Wiki() {
  useDocumentTitle('Kullanım Kılavuzu')
  const { slug } = useParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [deleting, setDeleting] = useState<WikiPage | null>(null)

  const { data: pages, isLoading, isError, error, refetch } = useQuery<WikiPage[]>({
    queryKey: ['wiki'],
    queryFn: async () => (await api.get('/wiki')).data,
  })
  const current = pages?.find((p) => p.slug === slug) ?? null

  // /wiki → ilk sayfa
  useEffect(() => {
    if (!slug && pages?.length) navigate(`/wiki/${pages[0].slug}`, { replace: true })
  }, [slug, pages, navigate])

  const shown = useMemo(() => (pages ?? []).filter((p) => !search.trim() || matches(p, search)), [pages, search])
  const groups = useMemo(() => {
    const out: { category: string; items: WikiPage[] }[] = []
    for (const p of shown) {
      const g = out.find((x) => x.category === p.category)
      if (g) g.items.push(p)
      else out.push({ category: p.category, items: [p] })
    }
    return out
  }, [shown])
  const categories = useMemo(() => [...new Set((pages ?? []).map((p) => p.category))], [pages])
  const index = pages && current ? pages.indexOf(current) : -1
  const prev = index > 0 ? pages![index - 1] : null
  const next = pages && index >= 0 && index < pages.length - 1 ? pages[index + 1] : null

  const save = useMutation({
    mutationFn: async (d: Draft) => {
      const body = { title: d.title, category: d.category, sort_order: Number(d.sort_order) || 0, body: d.body }
      return (d.id ? await api.put(`/wiki/${d.id}`, body) : await api.post('/wiki', body)).data as WikiPage
    },
    onSuccess: (p, d) => {
      enqueueSnackbar(d.id ? 'Sayfa güncellendi' : 'Sayfa eklendi', { variant: 'success' })
      setDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['wiki'] })
      navigate(`/wiki/${p.slug}`)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const remove = useMutation({
    mutationFn: async (p: WikiPage) => api.delete(`/wiki/${p.id}`),
    onSuccess: () => {
      enqueueSnackbar('Sayfa silindi', { variant: 'success' })
      setDeleting(null)
      void queryClient.invalidateQueries({ queryKey: ['wiki'] })
      navigate('/wiki', { replace: true })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const header = (
    <PageHeader title="Kullanım Kılavuzu"
                subtitle="Jumbo ekranları ve işleri adım adım. AI asistanı da “nasıl yapılır” sorularını buradan cevaplar."
                actions={isAdmin && (
                  <Button variant="contained" disableElevation startIcon={<AddIcon />}
                          onClick={() => setDraft({ ...EMPTY, category: current?.category ?? '', sort_order: (pages?.at(-1)?.sort_order ?? 0) + 10 })}>
                    Yeni Sayfa
                  </Button>
                )} />
  )
  if (isError) return <Box>{header}<QueryError error={error} onRetry={() => refetch()} /></Box>

  return (
    <Box>
      {header}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '290px minmax(0, 1fr)' }, gap: 2.5, alignItems: 'start' }}>
        {/* Sol: arama + kategorili sayfa listesi */}
        <Paper sx={{ position: { md: 'sticky' }, top: { md: 16 }, overflow: 'hidden' }}>
          <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}>
            <TextField fullWidth size="small" placeholder="Kılavuzda ara" value={search}
                       onChange={(e) => setSearch(e.target.value)}
                       slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          </Box>
          {isLoading ? <Box sx={{ p: 2 }}><Skeleton height={320} variant="rounded" /></Box> : (
            <List dense aria-label="Kılavuz sayfaları" sx={{ py: 0.5, maxHeight: { md: 'calc(100vh - 230px)' }, overflowY: 'auto' }}>
              {groups.map((g) => (
                <Fragment key={g.category}>
                  <ListSubheader sx={{ lineHeight: '30px', fontSize: 11, fontWeight: 700, letterSpacing: '.06em',
                                       textTransform: 'uppercase', color: 'text.secondary', bgcolor: 'background.paper' }}>
                    {g.category}
                  </ListSubheader>
                  {g.items.map((p) => (
                    <ListItemButton key={p.id} component={Link} to={`/wiki/${p.slug}`} selected={p.slug === slug}
                                    sx={{ mx: 1, borderRadius: 1.5, '&.Mui-selected': { fontWeight: 700 } }}>
                      <ListItemText primary={p.title} slotProps={{ primary: { sx: { fontSize: 14, fontWeight: 'inherit' } } }} />
                    </ListItemButton>
                  ))}
                </Fragment>
              ))}
              {!groups.length && (
                <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 3, textAlign: 'center' }}>
                  “{search}” için sayfa bulunamadı. AI asistanına sormayı deneyin.
                </Typography>
              )}
            </List>
          )}
        </Paper>

        {/* Sağ: sayfa */}
        <Paper sx={{ px: { xs: 2.5, md: 5 }, py: { xs: 2.5, md: 4 }, minHeight: 420 }}>
          {isLoading && <Skeleton height={420} variant="rounded" />}
          {!isLoading && slug && !current && (
            <Typography color="text.secondary">Bu kılavuz sayfası bulunamadı. Soldaki listeden bir sayfa seçin.</Typography>
          )}
          {current && (
            <Box component="article" sx={{ maxWidth: 820 }}>
              <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 2.5 }}>
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography variant="overline" color="primary" sx={{ fontWeight: 700, letterSpacing: '.08em' }}>
                    {current.category}
                  </Typography>
                  <Typography variant="h4" component="h1" sx={{ fontWeight: 700, fontSize: { xs: 24, md: 28 }, lineHeight: 1.25 }}>
                    {current.title}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {current.updated_by
                      ? `Son düzenleme: ${current.updated_by}${current.updated_at ? ' · ' + new Date(current.updated_at).toLocaleDateString('tr-TR') : ''}`
                      : 'Jumbo ile birlikte gelen sayfa'}
                  </Typography>
                </Box>
                {isAdmin && (
                  <Box sx={{ display: 'flex', gap: 1, flexShrink: 0 }}>
                    <Button size="small" variant="outlined" startIcon={<EditOutlinedIcon />}
                            onClick={() => setDraft({ id: current.id, title: current.title, category: current.category,
                                                      sort_order: current.sort_order, body: current.body })}>
                      Düzenle
                    </Button>
                    <Button size="small" color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setDeleting(current)}>
                      Sil
                    </Button>
                  </Box>
                )}
              </Box>
              <Markdown text={current.body} />

              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mt: 4, px: 2, py: 1.5, borderRadius: 2,
                         bgcolor: 'action.hover', color: 'text.secondary' }}>
                <AutoAwesomeIcon fontSize="small" sx={{ color: 'primary.main' }} />
                <Typography variant="body2">
                  Aradığınızı bulamadıysanız sağ alttaki AI asistanına sorabilirsiniz.
                </Typography>
              </Box>
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5, mt: 2 }}>
                {[prev, next].map((p, i) => p ? (
                  <ButtonBase key={p.id} component={Link} to={`/wiki/${p.slug}`}
                              sx={{ gridColumn: i === 1 ? 2 : 1, display: 'flex', alignItems: 'center', gap: 1,
                                    justifyContent: i ? 'flex-end' : 'flex-start', textAlign: i ? 'right' : 'left',
                                    p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2,
                                    '&:hover': { borderColor: 'primary.main' } }}>
                    {i === 0 && <ChevronLeftIcon fontSize="small" />}
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="caption" color="text.secondary">{i ? 'Sonraki' : 'Önceki'}</Typography>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{p.title}</Typography>
                    </Box>
                    {i === 1 && <ChevronRightIcon fontSize="small" />}
                  </ButtonBase>
                ) : <Box key={i} />)}
              </Box>
            </Box>
          )}
        </Paper>
      </Box>

      {/* Yönetici: sayfa ekle / düzenle — solda metin, sağda önizleme */}
      <Dialog open={!!draft} onClose={() => !save.isPending && setDraft(null)} maxWidth="lg" fullWidth>
        <DialogTitle>{draft?.id ? 'Sayfayı düzenle' : 'Yeni kılavuz sayfası'}</DialogTitle>
        {draft && (
          <DialogContent dividers>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '2fr 1.4fr 90px' }, gap: 1.5, mb: 2 }}>
              <TextField size="small" label="Başlık" required value={draft.title} autoFocus
                         onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
              <Autocomplete freeSolo size="small" options={categories} value={draft.category}
                            onInputChange={(_, v) => setDraft({ ...draft, category: v })}
                            renderInput={(params) => <TextField {...params} label="Kategori" required />} />
              <TextField size="small" label="Sıra" type="number" value={draft.sort_order}
                         onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} />
            </Box>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
              <Box>
                <TextField fullWidth multiline minRows={18} maxRows={28} label="İçerik" value={draft.body}
                           onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                           slotProps={{ input: { sx: { fontFamily: '"JetBrains Mono", monospace', fontSize: 13 } } }} />
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
                  Biçim: ## başlık · - madde · 1. adım · **kalın** · [bağlantı](/domains) · &gt; not kutusu
                </Typography>
              </Box>
              <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2.5, maxHeight: 560, overflowY: 'auto' }}>
                <Typography variant="overline" color="text.secondary">Önizleme</Typography>
                <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }}>{draft.title || 'Başlık'}</Typography>
                <Markdown text={draft.body} />
              </Box>
            </Box>
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setDraft(null)} disabled={save.isPending}>Vazgeç</Button>
          <Button variant="contained" disableElevation onClick={() => draft && save.mutate(draft)}
                  disabled={save.isPending || !draft?.title.trim() || !draft?.category.trim()}>
            Kaydet
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog open={!!deleting} title="Sayfa silinsin mi?" confirmLabel="Sil" danger busy={remove.isPending}
                     onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        “{deleting?.title}” kılavuzdan kaldırılır ve AI asistanı da artık bu sayfayı kullanmaz.
        Jumbo ile gelen bir sayfaysa sonraki sürümlerde geri gelmez.
      </ConfirmDialog>
    </Box>
  )
}
