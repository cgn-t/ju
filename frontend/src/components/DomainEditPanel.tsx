import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined'
import NotificationsNoneOutlinedIcon from '@mui/icons-material/NotificationsNoneOutlined'
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined'
import { Box, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { alpha, type Theme } from '@mui/material/styles'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Domain, Team } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import ConfirmSaveDialog from './ConfirmSaveDialog'
import { EditFooter, FormSection } from './FormKit'

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

  const isChanged = (k: string) => changed.includes(k)
  // Değişen alan, kaydetmeden önce görünür olsun: hafif vurgulu çerçeve
  const changedSx = (k: string) => (isChanged(k) ? {
    '& .MuiOutlinedInput-root:not(.Mui-error) .MuiOutlinedInput-notchedOutline': { borderColor: 'info.main' },
    '& .MuiOutlinedInput-root': { bgcolor: (t: Theme) => alpha(t.palette.info.main, 0.04) },
  } : undefined)

  const text = (key: string, label: string, opts: { required?: boolean; type?: string; helper?: string; span?: boolean; placeholder?: string } = {}) => (
    <TextField key={key} fullWidth size="small" label={label} value={form[key]} onChange={set(key)} type={opts.type}
               required={opts.required} error={opts.required && missing(key)} placeholder={opts.placeholder}
               slotProps={LABEL_SHRINK}
               multiline={key === 'info'} minRows={key === 'info' ? 3 : undefined}
               sx={{ ...(opts.span ? { gridColumn: '1 / -1' } : {}), ...changedSx(key) }}
               helperText={opts.required && missing(key) ? 'Zorunlu alan' : opts.helper} />
  )
  const yesNo = (key: string, label: string, required = false) => {
    const val = form[key] ?? ''
    const legacy = val && !YESNO.includes(val) ? val : null
    return (
      <TextField key={key} select fullWidth size="small" label={label} value={val} onChange={set(key)}
                 required={required} error={required && !val} sx={changedSx(key)}
                 slotProps={{ ...LABEL_SHRINK, select: { displayEmpty: true } }}
                 helperText={required && !val ? 'Zorunlu alan' : undefined}>
        <MenuItem value="" disabled={required}><Typography component="span" color="text.secondary">Seçilmedi</Typography></MenuItem>
        {legacy && <MenuItem value={legacy}>{legacy} (mevcut)</MenuItem>}
        <MenuItem value="Evet">Evet</MenuItem>
        <MenuItem value="Hayır">Hayır</MenuItem>
      </TextField>
    )
  }
  const selectedSy = syTeams.find((t) => String(t.id) === form.sy_team_id)

  return (
    <Box>
      <Stack spacing={2}>
        <FormSection icon={<BadgeOutlinedIcon />} title="Kimlik" hint="Domain adı ve dışarıdan erişilen adres" columns={2}>
          {text('domain', 'Domain', { required: true })}
          {text('external_address', 'Dış Adres', { placeholder: 'ör. 10.0.0.1 veya dış alan adı' })}
        </FormSection>

        <FormSection icon={<GroupsOutlinedIcon />} title="Sahiplik ve iletişim" hint="Uyarı e-postaları bu bilgilere göre gönderilir" columns={2}>
          <TextField select fullWidth size="small" label="SY Takımı" required value={form.sy_team_id}
                     onChange={set('sy_team_id')} disabled={!isAdmin} error={missing('sy_team_id')}
                     slotProps={LABEL_SHRINK} sx={changedSx('sy_team_id')}
                     helperText={!isAdmin ? 'Sahipliği yalnız admin değiştirebilir'
                       : selectedSy ? `Bildirim e-postası: ${selectedSy.email || '— (ekip e-postası tanımsız)'}` : 'Zorunlu alan'}>
            {form.sy_team_id && !selectedSy && <MenuItem value={form.sy_team_id}>{domain.sy_team?.name ?? `#${form.sy_team_id}`}</MenuItem>}
            {syTeams.map((t) => <MenuItem key={t.id} value={t.id.toString()}>{t.name}</MenuItem>)}
          </TextField>
          {text('ug_team_name', 'UG Takımı')}
          {text('cert_owner', 'Sertifika Sahibi', { placeholder: 'ad.soyad@…' })}
          {text('mail_addresses', 'Ek Mail Adresleri', { helper: 'Birden çok adresi ; ile ayırın' })}
        </FormSection>

        <FormSection icon={<TuneOutlinedIcon />} title="Sertifika yenilemede yapılacaklar" hint="Yeni sertifika geldiğinde hangi bileşenlerin güncelleneceği">
          {yesNo('lb_update', 'LoadBalancer Güncelleme', true)}
          {yesNo('waf_update', 'WAF Güncelleme', true)}
          {yesNo('action_required', 'Aksiyon Alma')}
          {yesNo('ssl_pinning', 'SSL Pinning')}
          {text('env_update', 'Ortam Güncelleme')}
          {text('external_company', 'Dış Firma')}
          {text('servers_to_update', 'Güncellenecek Sunucular')}
          {text('keystore', 'Keystore')}
        </FormSection>

        <FormSection icon={<NotificationsNoneOutlinedIcon />} title="Bildirim" columns={2}>
          <TextField fullWidth size="small" type="number" label="Bildirim Gün Sayısı" value={form.notify_days}
                     onChange={set('notify_days')} error={notifyBad} placeholder="30" sx={changedSx('notify_days')}
                     slotProps={{ ...LABEL_SHRINK, htmlInput: { min: 1, max: 3650 } }}
                     helperText={notifyBad ? '1 ile 3650 arasında olmalı' : 'Bitişten kaç gün önce uyarılsın (boşsa Ayarlar’daki varsayılan)'} />
          {text('expire_date', 'Manuel Bitiş Tarihi', { type: 'date', helper: 'Normalde boş bırakın; tarih bağlı sertifikadan okunur' })}
        </FormSection>

        <FormSection icon={<NotesOutlinedIcon />} title="Notlar" columns={1}>
          {text('info', 'Detay', { span: true, placeholder: 'Bu domainle ilgili açıklama…' })}
        </FormSection>
      </Stack>

      <EditFooter
        status={changed.length
          ? <><Box component="span" sx={{ color: 'info.main', fontWeight: 600 }}>{changed.length} alan değişti</Box> · kaydetmeden önce özet gösterilir</>
          : 'Henüz değişiklik yok'}
        onCancel={onDone} busy={save.isPending}
        saveLabel={changed.length ? `Kaydet (${changed.length})` : 'Kaydet'}
        saveDisabled={!isValid || notifyBad || changed.length === 0}
        onSave={() => setConfirmOpen(true)} />
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
