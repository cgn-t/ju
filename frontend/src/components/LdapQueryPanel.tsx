import FileDownloadIcon from '@mui/icons-material/FileDownload'
import GroupsIcon from '@mui/icons-material/Groups'
import PersonSearchIcon from '@mui/icons-material/PersonSearch'
import {
  Alert, Autocomplete, Box, Button, Chip, LinearProgress, Paper, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { exportSheet } from '../utils/exportSheet'
import { ROLE_CHIP } from '../utils/peopleLabels'

/**
 * LDAP Sorguları — dizinden canlı, salt okuma:
 *  1) Kişi giriş yapınca hangi Scrum ekibiyle (Ekip grubu OU'su altındaki grup) gelir?
 *  2) Bir Scrum ekibinde hangi kullanıcılar var?
 * Her ikisinde de kişinin Jumbo'daki hesabı (rol, Jumbo ekipleri) yan yana gösterilir.
 */

type JumboUser = { id: number; role: string; active: boolean; teams: string[] } | null
type Lookup = {
  status: string; message: string; dn?: string; account?: string; name?: string; mail?: string
  title?: string; department?: string; team_groups?: string[]; jumbo?: JumboUser
}
type Member = {
  dn: string; name: string; account: string; mail: string; title: string; department: string; jumbo: JumboUser
}
type MembersResult = { status: string; message: string; team?: string; dn?: string; members: Member[]; truncated?: boolean }
type TeamsResult = { status: string; message: string; groups?: { name: string; dn: string }[] }

function JumboCell({ jumbo }: { jumbo: JumboUser | undefined }) {
  if (!jumbo) return <Typography variant="body2" color="text.secondary">Jumbo'da hesabı yok</Typography>
  const role = ROLE_CHIP[jumbo.role] ?? { label: jumbo.role, color: 'default' as const }
  return (
    <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
      <Chip size="small" label={role.label} color={role.color} variant="outlined" />
      {jumbo.teams.map((t) => <Chip key={t} size="small" label={t} />)}
      {!jumbo.active && <Chip size="small" label="Pasif" color="warning" />}
    </Stack>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.25, sm: 2 }} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 190 }}>{label}</Typography>
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
    </Stack>
  )
}

export default function LdapQueryPanel() {
  const [username, setUsername] = useState('')
  const [team, setTeam] = useState('')

  const lookup = useMutation({
    mutationFn: async (u: string) =>
      (await api.get<Lookup>('/settings/ldap/lookup-user', { params: { username: u } })).data,
  })
  const members = useMutation({
    mutationFn: async (t: string) =>
      (await api.get<MembersResult>('/settings/ldap/team-members', { params: { team: t } })).data,
  })
  const teams = useQuery({
    queryKey: ['ldap-teams'],
    queryFn: async () => (await api.get<TeamsResult>('/settings/ldap/teams')).data,
    staleTime: 5 * 60_000,
  })

  const runLookup = (u = username) => { if (u.trim()) { setUsername(u); lookup.mutate(u.trim()) } }
  const runMembers = (t = team) => { if (t.trim()) { setTeam(t); members.mutate(t.trim()) } }

  const r = lookup.data
  const m = members.data
  const teamNames = (teams.data?.groups ?? []).map((g) => g.name)

  const onExport = () => m && exportSheet(
    `${m.team ?? team}-uyeler.xlsx`,
    ['Ad Soyad', 'Hesap', 'E-posta', 'Unvan', 'Departman', "Jumbo'da rol", 'Jumbo ekipleri'],
    m.members.map((x) => [x.name, x.account, x.mail, x.title, x.department,
      x.jumbo ? (ROLE_CHIP[x.jumbo.role]?.label ?? x.jumbo.role) : 'Hesabı yok', x.jumbo?.teams.join(', ') ?? '']),
  )

  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Sorgular dizinden canlı ve yalnız okunarak yapılır; hiçbir şey değiştirilmez. Ekip, Ayarlar &gt; LDAP &gt;
        Ekip Grubu'ndaki OU altındaki gruptur (girişte sol menüde adın altında görünen ekip).
      </Alert>

      {/* 1) Kişi → ekip */}
      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1.5 }}>
          <PersonSearchIcon color="primary" />
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Kişi hangi Scrum ekibiyle gelir?</Typography>
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <TextField
            size="small" label="Kullanıcı adı" placeholder="ör. ismail.celik" value={username}
            onChange={(e) => setUsername(e.target.value)} sx={{ flex: 1, maxWidth: { sm: 360 } }}
            onKeyDown={(e) => { if (e.key === 'Enter') runLookup() }}
          />
          <Button variant="contained" onClick={() => runLookup()} disabled={!username.trim() || lookup.isPending}>
            Sorgula
          </Button>
        </Stack>
        {lookup.isPending && <LinearProgress sx={{ mt: 2 }} />}
        {lookup.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(lookup.error)}</Alert>}
        {r && !lookup.isPending && (r.status !== 'ok'
          ? <Alert severity={r.status === 'not_found' ? 'warning' : 'error'} sx={{ mt: 2 }}>{r.message}</Alert>
          : (
            <Box sx={{ mt: 2 }}>
              <Typography variant="h6">{r.name || r.account}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {[r.account, r.title, r.department].filter(Boolean).join(' · ')}
              </Typography>
              <Row label="Giriş yapınca geleceği ekip">
                {r.team_groups?.length
                  ? (
                    <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                      {r.team_groups.map((t) => (
                        <Chip key={t} label={t} color="primary" onClick={() => runMembers(t)}
                              title="Bu ekibin üyelerini aşağıda göster" />
                      ))}
                    </Stack>
                  )
                  : <Typography variant="body2" color="warning.main">Ekip grubu yok — girişte sol menüde ekip görünmez</Typography>}
              </Row>
              <Row label="Jumbo'daki hesabı"><JumboCell jumbo={r.jumbo} /></Row>
              {r.mail && <Row label="E-posta"><Typography variant="body2">{r.mail}</Typography></Row>}
              <Row label="DN">
                <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{r.dn}</Typography>
              </Row>
            </Box>
          ))}
      </Paper>

      {/* 2) Ekip → kişiler */}
      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1.5 }}>
          <GroupsIcon color="primary" />
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Scrum ekibinde kimler var?</Typography>
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <Autocomplete
            freeSolo size="small" options={teamNames} loading={teams.isLoading} inputValue={team}
            onInputChange={(_, v) => setTeam(v)} onChange={(_, v) => { if (v) runMembers(v) }}
            sx={{ flex: 1, maxWidth: { sm: 360 } }}
            renderInput={(p) => (
              <TextField {...p} label="Scrum ekibi" placeholder="ör. SY-BBB"
                         helperText={teams.data && teams.data.status === 'ok'
                           ? `Dizinde ${teamNames.length} ekip var` : teams.data?.message} />
            )}
          />
          <Box>
            <Button variant="contained" onClick={() => runMembers()} disabled={!team.trim() || members.isPending}>
              Üyeleri Getir
            </Button>
          </Box>
        </Stack>
        {members.isPending && <LinearProgress sx={{ mt: 2 }} />}
        {members.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(members.error)}</Alert>}
        {m && !members.isPending && (m.status !== 'ok'
          ? <Alert severity={m.status === 'not_found' ? 'warning' : 'error'} sx={{ mt: 2 }}>{m.message}</Alert>
          : (
            <Box sx={{ mt: 2 }}>
              <Stack direction="row" sx={{ alignItems: 'center', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flex: 1 }}>
                  {m.team} — {m.members.length} kişi
                  {m.members.length > 0 && ` (${m.members.filter((x) => !x.jumbo).length} kişinin Jumbo hesabı yok)`}
                </Typography>
                {m.members.length > 0 && (
                  <Button size="small" startIcon={<FileDownloadIcon />} onClick={onExport}>Excel</Button>
                )}
              </Stack>
              {m.truncated && <Alert severity="warning" sx={{ mb: 1 }}>Liste ilk {m.members.length} kişiyle sınırlandı.</Alert>}
              {m.members.length === 0
                ? <Typography variant="body2" color="text.secondary">Bu ekipte doğrudan üye yok.</Typography>
                : (
                  <Box sx={{ overflowX: 'auto' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Ad Soyad</TableCell><TableCell>Hesap</TableCell><TableCell>E-posta</TableCell>
                          <TableCell>Unvan</TableCell><TableCell>Jumbo'da</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {m.members.map((x) => (
                          <TableRow key={x.dn} hover sx={{ cursor: x.account ? 'pointer' : 'default' }}
                                    onClick={() => x.account && runLookup(x.account)}>
                            <TableCell>{x.name}</TableCell>
                            <TableCell>{x.account}</TableCell>
                            <TableCell>{x.mail}</TableCell>
                            <TableCell>{x.title}</TableCell>
                            <TableCell><JumboCell jumbo={x.jumbo} /></TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Box>
                )}
            </Box>
          ))}
      </Paper>
    </Stack>
  )
}
