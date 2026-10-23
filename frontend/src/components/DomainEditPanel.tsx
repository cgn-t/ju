import SaveIcon from '@mui/icons-material/Save'
import { Alert, Box, Button, MenuItem, TextField } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Domain, Team } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import ConfirmSaveDialog from './ConfirmSaveDialog'
import { GRID3 } from './DetailCards'

/**
 * Domain penceresi > Kurum İçi Bilgiler sekmesinde YERİNDE düzenleme. Alanlar ve kurallar
 * "Domain Düzenle" formuyla aynıdır (zorunlu: Domain, LoadBalancer, WAF, SY Takımı; Kaydet önce
 * onay penceresi açar). Sahiplik (SY Takımı) yalnız admin tarafından değiştirilir — sunucu da
 * aynı kuralı uygular. Canlı zincir sorgusu/aktarımı bu panelde yok (Canlı Doğrulama sekmesi).
 */
const YESNO = ['Evet', 'Hayır']
const LABEL_SHRINK = { inputLabel: { shrink: true } }

function initial(d: Domain): Record<string, string> {
  return {
    domain: d.domain ?? '',
    external_address: d.external_address ?? '',
    ug_team_name: d.ug_team_name ?? d.ug_team?.name ?? '',
    sy_team_id: d.sy_team_id?.toString() ?? '',
    lb_update: d.lb_update ?? '',
    env_update: d.env_update ?? '',
    waf_update: d.waf_update ?? '',
    external_company: d.external_company ?? '',
    cert_owner: d.cert_owner ?? '',
    mail_addresses: d.mail_addresses ?? '',
    expire_date: d.expire_date ? d.expire_date.slice(0, 10) : '',
    info: d.info ?? '',
    action_required: d.action_required ?? '',
    ssl_pinning: d.ssl_pinning ?? '',
    keystore: d.keystore ?? '',
    servers_to_update: d.servers_to_update ?? '',
    notify_days: d.notify_days?.toString() ?? '',
  }
}

export default function DomainEditPanel({ domain, onDone }: { domain: Domain; onDone: () => void }) {
  const { isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Record<string, string>>(() => initial(domain))
  const [confirmOpen, setConfirmOpen] = useState(false)
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
  })
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const before = initial(domain)
  const changed = Object.keys(form).filter((k) => (form[k] ?? '').trim() !== (before[k] ?? '').trim())

  const save = useMutation({
    mutationFn: async () => {
      // Yalnız DEĞİŞEN alanlar gönderilir (audit kaydı ve sahiplik kuralı net kalsın)
      const body: Record<string, unknown> = {}
      for (const k of changed) {
        const v = form[k].trim()
        body[k] = v === '' ? null
          : k === 'sy_team_id' || k === 'notify_days' ? Number(v)
          : v
      }
      return (await api.put(`/domains/${domain.id}`, body)).data
    },
    onSuccess: () => {
      enqueueSnackbar('Domain güncellendi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['domain', domain.id] })
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['domain-options'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      onDone()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const missing = (k: string) => !form[k]?.trim()
  const isValid = !missing('domain') && !missing('lb_update') && !missing('waf_update') && !missing('sy_team_id')
  const notifyBad = !!form.notify_days && !(Number(form.notify_days) >= 1 && Number(form.notify_days) <= 3650)

  const text = (key: string, label: string, opts: { required?: boolean; type?: string; helper?: string; span?: boolean } = {}) => (
    <Box sx={opts.span ? { gridColumn: '1 / -1' } : undefined}>
      <TextField fullWidth size="small" label={label} value={form[key]} onChange={set(key)} type={opts.type}
                 required={opts.required} error={opts.required && missing(key)} slotProps={LABEL_SHRINK}
                 multiline={key === 'info'} minRows={key === 'info' ? 2 : undefined}
                 helperText={opts.required && missing(key) ? 'Zorunlu alan' : opts.helper} />
    </Box>
  )
  const yesNo = (key: string, label: string, required = false) => {
    const val = form[key] ?? ''
    const legacy = val && !YESNO.includes(val) ? val : null
    return (
      <TextField select fullWidth size="small" label={label} value={val} onChange={set(key)}
                 required={required} error={required && !val} slotProps={LABEL_SHRINK}
                 helperText={required && !val ? 'Zorunlu alan' : undefined}>
        {!required && <MenuItem value=""><em>—</em></MenuItem>}
        {legacy && <MenuItem value={legacy}>{legacy} (mevcut)</MenuItem>}
        <MenuItem value="Evet">Evet</MenuItem>
        <MenuItem value="Hayır">Hayır</MenuItem>
      </TextField>
    )
  }
  const selectedSy = syTeams.find((t) => String(t.id) === form.sy_team_id)

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 2 }}>
        Bilgileri burada değiştirip <b>Kaydet</b>&apos;e basın. Sertifika tarihleri sertifikanın kendisinden
        okunur, burada değiştirilmez.
      </Alert>
      <Box sx={GRID3}>
        {text('domain', 'Domain', { required: true })}
        {text('external_address', 'Dış Adres')}
        <TextField select fullWidth size="small" label="SY Takımı" required value={form.sy_team_id}
                   onChange={set('sy_team_id')} disabled={!isAdmin} error={missing('sy_team_id')}
                   slotProps={LABEL_SHRINK}
                   helperText={!isAdmin ? 'Sahipliği yalnız admin değiştirebilir'
                     : selectedSy ? `Bildirim e-postası: ${selectedSy.email || '— (ekip e-postası tanımsız)'}` : 'Zorunlu alan'}>
          {form.sy_team_id && !selectedSy && <MenuItem value={form.sy_team_id}>{domain.sy_team?.name ?? `#${form.sy_team_id}`}</MenuItem>}
          {syTeams.map((t) => <MenuItem key={t.id} value={t.id.toString()}>{t.name}</MenuItem>)}
        </TextField>
        {text('ug_team_name', 'UG Takımı')}
        {text('cert_owner', 'Sertifika Sahibi')}
        {text('mail_addresses', 'Mail Adresleri', { helper: 'Birden çok adresi ; ile ayırın' })}
        {yesNo('lb_update', 'LoadBalancer Güncelleme', true)}
        {yesNo('waf_update', 'WAF Güncelleme', true)}
        {text('env_update', 'Ortam Güncelleme')}
        {yesNo('action_required', 'Aksiyon Alma')}
        {yesNo('ssl_pinning', 'SSL Pinning')}
        {text('external_company', 'Dış Firma')}
        <TextField fullWidth size="small" type="number" label="Bildirim Gün Sayısı" value={form.notify_days}
                   onChange={set('notify_days')} error={notifyBad}
                   slotProps={{ ...LABEL_SHRINK, htmlInput: { min: 1, max: 3650 } }}
                   helperText={notifyBad ? '1 ile 3650 arasında olmalı' : 'Boşsa Ayarlar’daki varsayılan (30 gün)'} />
        {text('expire_date', 'Manuel Bitiş Tarihi', { type: 'date', helper: 'Boşsa bağlı sertifikadan' })}
        {text('servers_to_update', 'Güncellenecek Sunucular')}
        {text('keystore', 'Keystore')}
        {text('info', 'Detay', { span: true })}
      </Box>
      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', mt: 2 }}>
        <Button onClick={onDone} disabled={save.isPending}>Vazgeç</Button>
        <Button variant="contained" startIcon={<SaveIcon />}
                disabled={!isValid || notifyBad || changed.length === 0 || save.isPending}
                onClick={() => setConfirmOpen(true)}>
          Kaydet{changed.length ? ` (${changed.length} alan)` : ''}
        </Button>
      </Box>
      <ConfirmSaveDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => { setConfirmOpen(false); save.mutate() }}
        items={[
          { label: 'İşlem', value: 'Domain güncelleme' },
          { label: 'Domain', value: form.domain || '—' },
          { label: 'Değişen alan', value: String(changed.length) },
          { label: 'Bitiş Tarihi', highlight: true, value: form.expire_date || 'Otomatik (bağlı sertifikadan)' },
        ]} />
    </Box>
  )
}
