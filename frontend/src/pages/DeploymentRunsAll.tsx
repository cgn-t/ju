import {
  Autocomplete, Box, Paper, Table, TableBody, TableCell, TableHead, TableRow, TextField, Stack,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Application, DeploymentRunSummary } from '../api/types'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { formatDuration } from '../utils/duration'
import { StatusChip, TRIGGER_TYPE_LABELS } from './Deployments'

/** Uygulamalar arası TÜM dağıtım çalıştırmaları — Dağıtım sayfasındaki "Çalıştırmalar" tablosu
 * tek bir uygulamayla sınırlıyken, burada "bu CERTKEY en son ne zaman/hangi uygulamada dağıtıldı"
 * gibi sorular için app_id filtresi olmadan arama yapılabilir. Ana menüde YER ALIR (Dağıtım'ın
 * altında, İşlemler grubunda) çünkü akış tasarımından bağımsız, salt bir geçmiş/arama görünümü. */
export default function DeploymentRunsAll() {
  useDocumentTitle('Tüm Çalıştırmalar')
  const navigate = useNavigate()

  const { data: apps } = useQuery<Application[]>({
    queryKey: ['applications-lite'],
    queryFn: async () => (await api.get('/applications')).data,
  })

  const [appId, setAppId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  const { data: runs, isLoading } = useQuery<DeploymentRunSummary[]>({
    queryKey: ['deployment-runs-all', appId, debouncedSearch],
    queryFn: async () => (await api.get('/deployments/runs', {
      params: { app_id: appId ?? undefined, q: debouncedSearch || undefined, limit: 200 },
    })).data,
  })

  const appName = (id: number | null | undefined) => apps?.find((a) => a.id === id)?.app_name ?? '—'

  return (
    <Box>
      <PageHeader title="Tüm Çalıştırmalar"
        subtitle="Uygulamalar arası dağıtım geçmişi — akış adı, tetikleyen, Jenkins job'u veya parametre değerine göre arayın." />

      <Paper sx={{ p: 2 }}>
        <Stack direction="row" spacing={2} sx={{ mb: 2, flexWrap: 'wrap' }}>
          <Autocomplete
            size="small" options={apps ?? []} getOptionLabel={(a) => a.app_name}
            value={apps?.find((a) => a.id === appId) ?? null}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, v) => setAppId(v?.id ?? null)}
            renderInput={(p) => <TextField {...p} label="Uygulama (tümü)" />}
            sx={{ width: 260 }}
          />
          <TextField size="small" label="Ara" placeholder="Akış, tetikleyen, job veya parametre…"
                    value={search} onChange={(e) => setSearch(e.target.value)} sx={{ width: 340 }} />
        </Stack>

        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              <TableCell>Uygulama</TableCell>
              <TableCell>Akış</TableCell>
              <TableCell>Durum</TableCell>
              <TableCell>Süre</TableCell>
              <TableCell>Tetikleme</TableCell>
              <TableCell>Tetikleyen</TableCell>
              <TableCell>Zaman</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(runs ?? []).map((r) => (
              <TableRow key={r.id} hover sx={{ cursor: 'pointer' }}
                       onClick={() => navigate(`/deployments/runs/${r.id}`)}>
                <TableCell sx={{ fontWeight: 600 }}>#{r.id}</TableCell>
                <TableCell>{appName(r.app_id)}</TableCell>
                <TableCell>{r.flow_name_snapshot}</TableCell>
                <TableCell><StatusChip status={r.status} /></TableCell>
                <TableCell>{formatDuration(r.duration_seconds)}</TableCell>
                <TableCell>
                  {TRIGGER_TYPE_LABELS[r.trigger_type] ?? r.trigger_type}
                  {r.source_run_id != null && ` (#${r.source_run_id})`}
                </TableCell>
                <TableCell>{r.triggered_by ?? '—'}</TableCell>
                <TableCell>{new Date(r.created_at).toLocaleString('tr-TR')}</TableCell>
              </TableRow>
            ))}
            {!isLoading && (runs ?? []).length === 0 && (
              <TableRow><TableCell colSpan={8} sx={{ color: 'text.secondary' }}>
                {debouncedSearch || appId ? 'Eşleşen çalıştırma yok.' : 'Henüz çalıştırma yok.'}
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  )
}
