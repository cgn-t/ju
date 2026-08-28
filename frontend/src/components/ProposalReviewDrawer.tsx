import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloseIcon from '@mui/icons-material/Close'
import ArrowRightAltIcon from '@mui/icons-material/ArrowRightAlt'
import EventRepeatIcon from '@mui/icons-material/EventRepeat'
import FingerprintIcon from '@mui/icons-material/Fingerprint'
import LanguageIcon from '@mui/icons-material/Language'
import HowToRegIcon from '@mui/icons-material/HowToReg'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import RuleIcon from '@mui/icons-material/Rule'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import VpnKeyIcon from '@mui/icons-material/VpnKey'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Box, Button, Chip, Divider, Drawer, IconButton, Skeleton, Stack, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Certificate, TransferProposal } from '../api/types'
import { daysLeftColor, daysLeftLabel, mappingTypeLabel, MONO_FONT, nodeColors } from '../theme'

interface Props {
  proposal: TransferProposal | null
  /** Aynı devrin (old→new cert) TÜM bekleyen domain önerileri — bu öneri dahil. Tek sertifika
   *  birden çok domaine bağlıysa her domain kendi SY ekibince ayrı onaylanır; bu liste onu gösterir. */
  group: TransferProposal[]
  onClose: () => void
  onDecide: (id: number, action: 'approve' | 'reject') => void
  deciding: boolean
}

/** Hex kimlik değerlerini (SKI/AKI/serial/fingerprint) biçimden bağımsız karşılaştır: iki nokta,
 *  boşluk, büyük/küçük harf farklarını yok say. Metin alanları için düz trim yeterli. */
const normHex = (v?: string | null) => (v ?? '').replace(/[^0-9a-fA-F]/g, '').toUpperCase()
const norm = (v?: string | null) => (v ?? '').trim()
/** Uzun hex kimliği (parmak izi/serial) kısaca göster: baş…son; tam değer tooltip'te. */
const shortHex = (v?: string | null, head = 10, tail = 6) => {
  const h = (v ?? '').trim()
  if (!h) return '—'
  return h.length > head + tail + 1 ? `${h.slice(0, head)}…${h.slice(-tail)}` : h
}
const fmtDate = (v?: string | null) =>
  v ? new Date(v).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
const fmtDateTime = (v?: string | null) => (v ? new Date(v).toLocaleString('tr-TR') : '—')

type RowKind = 'expect-same' | 'expect-change'
interface Field {
  label: string
  kind: RowKind
  oldVal?: string | null
  newVal?: string | null
  same: boolean
  mono?: boolean
  render?: 'date'
}

/** Tek bir güvenlik-kanıtı satırı: ikon + başlık + açıklama, duruma göre renk. */
function Evidence({ ok, warn, icon, title, detail }: {
  ok: boolean; warn?: boolean; icon: React.ReactNode; title: string; detail: string
}) {
  const color = ok ? 'success.main' : warn ? 'warning.main' : 'text.secondary'
  return (
    <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start', minWidth: 220, flex: '1 1 240px' }}>
      <Box sx={{ color, mt: 0.25, display: 'flex' }}>{icon}</Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, color, lineHeight: 1.3 }}>{title}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.35 }}>
          {detail}
        </Typography>
      </Box>
    </Box>
  )
}

/** Karşılaştırma satırı: durum ikonu | alan | ESKİ | YENİ. */
function CompareRow({ f }: { f: Field }) {
  const changed = !f.same
  // beklenen-aynı ama farklıysa uyarı; beklenen-değişir ve değiştiyse nötr (normal rotasyon)
  const warn = f.kind === 'expect-same' && changed
  const good = f.kind === 'expect-same' && !changed
  const statusIcon = good
    ? <CheckCircleIcon sx={{ fontSize: 17, color: 'success.main' }} />
    : warn
      ? <WarningAmberIcon sx={{ fontSize: 17, color: 'warning.main' }} />
      : <ArrowRightAltIcon sx={{ fontSize: 18, color: 'text.disabled' }} />
  const valSx = {
    fontFamily: f.mono ? MONO_FONT : undefined, fontSize: f.mono ? 11.5 : 13,
    wordBreak: 'break-all' as const, lineHeight: 1.4,
  }
  const oldText = f.render === 'date' ? fmtDate(f.oldVal) : (f.oldVal || '—')
  const newText = f.render === 'date' ? fmtDate(f.newVal) : (f.newVal || '—')
  return (
    <Box sx={{
      display: 'grid', gridTemplateColumns: '24px 132px 1fr 1fr', gap: 1.25, alignItems: 'start',
      py: 1, px: 1, borderRadius: 1,
      bgcolor: warn ? 'warning.main' : 'transparent',
      ...(warn && { bgcolor: (t: any) => t.palette.mode === 'dark' ? 'rgba(255,167,38,0.09)' : 'rgba(255,167,38,0.12)' }),
      '&:hover': { bgcolor: 'action.hover' },
    }}>
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 0.15 }}>
        <Tooltip title={good ? 'Eşleşiyor' : warn ? 'Farklı — dikkat' : 'Değişti (rotasyonda beklenen)'}>
          <Box sx={{ display: 'flex' }}>{statusIcon}</Box>
        </Tooltip>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ pt: 0.25, fontWeight: 600 }}>
        {f.label}
      </Typography>
      <Tooltip title={f.render === 'date' ? fmtDateTime(f.oldVal) : (f.oldVal || '')} placement="top-start">
        <Typography sx={{ ...valSx, color: 'text.secondary' }}>{oldText}</Typography>
      </Tooltip>
      <Tooltip title={f.render === 'date' ? fmtDateTime(f.newVal) : (f.newVal || '')} placement="top-start">
        <Typography sx={{ ...valSx, color: changed ? 'text.primary' : 'text.secondary', fontWeight: changed ? 600 : 400 }}>
          {newText}
        </Typography>
      </Tooltip>
    </Box>
  )
}

/** ESKİ / YENİ kimlik kartı — devrin iki ucunu görsel olarak ayırır. */
function CertCard({ cert, tone, kicker }: {
  cert?: Certificate; tone: 'old' | 'new'; kicker: string
}) {
  const accent = tone === 'new'
  return (
    <Box sx={{
      flex: 1, minWidth: 0, p: 2, borderRadius: 2, border: '1px solid',
      borderColor: accent ? 'info.main' : 'divider',
      bgcolor: accent ? (t: any) => t.palette.mode === 'dark' ? 'rgba(41,182,246,0.07)' : 'rgba(41,182,246,0.06)' : 'background.default',
    }}>
      <Typography variant="overline" sx={{ color: accent ? 'info.main' : 'text.secondary', fontWeight: 700, letterSpacing: 1 }}>
        {kicker}
      </Typography>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, wordBreak: 'break-all', lineHeight: 1.25, mb: 1 }}>
        {cert?.name ?? <Skeleton width={160} />}
      </Typography>
      <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.75, mb: 1.25 }}>
        {cert && (
          <Chip size="small" label={cert.cert_type.toUpperCase()}
                sx={{ bgcolor: nodeColors[cert.cert_type], color: 'rgba(0,0,0,0.87)', fontWeight: 700, height: 22 }} />
        )}
        {cert && <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)}
                       sx={{ height: 22 }} />}
      </Stack>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
        <Typography variant="caption" color="text.secondary">Geçerlilik Sonu</Typography>
        <Tooltip title={fmtDateTime(cert?.valid_to)}>
          <Typography variant="caption" sx={{ fontWeight: 600 }}>{fmtDate(cert?.valid_to)}</Typography>
        </Tooltip>
      </Box>
      {/* Parmak izi = sertifikanın BENZERSİZ kimliği. Devirde eski≠yeni olması, gerçekten yeni bir
          sertifika olduğunu kanıtlar; yan yana iki farklı değer bunu bir bakışta gösterir. */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mt: 0.5, alignItems: 'baseline' }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.4 }}>
          <FingerprintIcon sx={{ fontSize: 14 }} /> Parmak İzi
        </Typography>
        <Tooltip title={cert?.fingerprint_sha256 || 'SHA-256 kayıtlı değil'}>
          <Typography variant="caption" sx={{ fontFamily: MONO_FONT, fontSize: 11, fontWeight: 600, color: accent ? 'info.main' : 'text.primary' }}>
            {shortHex(cert?.fingerprint_sha256)}
          </Typography>
        </Tooltip>
      </Box>
    </Box>
  )
}

/** Karşılaştırma tablosunda alan grubu başlığı: eşleşmeli (kimlik) vs benzersiz (değişir). */
function GroupHeader({ label, tone }: { label: string; tone: 'match' | 'unique' }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 1, pt: 1.5, pb: 0.5 }}>
      {tone === 'match'
        ? <CheckCircleIcon sx={{ fontSize: 15, color: 'success.main' }} />
        : <FingerprintIcon sx={{ fontSize: 16, color: 'warning.main' }} />}
      <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: 0.3, color: 'text.secondary' }}>
        {label}
      </Typography>
    </Box>
  )
}

/** Kapsam satırı: tek domain onayı — domain adı, SY sahibi, karar durumu. `current` = incelenen öneri. */
function ScopeRow({ p, current }: { p: TransferProposal; current: boolean }) {
  return (
    <Box sx={{
      display: 'flex', alignItems: 'center', gap: 1, py: 0.9, px: 1.25, borderRadius: 1,
      border: '1px solid', borderColor: current ? 'info.main' : 'divider',
      bgcolor: current ? (t: any) => t.palette.mode === 'dark' ? 'rgba(41,182,246,0.08)' : 'rgba(41,182,246,0.06)' : 'transparent',
    }}>
      <LanguageIcon sx={{ fontSize: 18, color: 'text.disabled' }} />
      <Typography variant="body2" sx={{ fontWeight: 600, flexGrow: 1, minWidth: 0, wordBreak: 'break-all' }}>
        {p.domain_name ?? (p.app_dependency_id ? 'mTLS bağımlılığı' : '—')}
        {p.mapping_type && (
          <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.75 }}>
            ({mappingTypeLabel(p.mapping_type)})
          </Typography>
        )}
      </Typography>
      {p.sy_team_name
        ? <Chip size="small" label={p.sy_team_name} sx={{ height: 22 }} />
        : <Chip size="small" variant="outlined" color="warning" label="sahipsiz" sx={{ height: 22 }} />}
      {current
        ? <Chip size="small" color="info" label="inceleniyor" sx={{ height: 22 }} />
        : p.can_decide
          ? <Tooltip title="Bu domaini siz de onaylayabilirsiniz">
              <Chip size="small" color="success" variant="outlined" icon={<HowToRegIcon />} label="yetkiniz var" sx={{ height: 22 }} />
            </Tooltip>
          : <Tooltip title="Bu domaini sahibi SY ekibi onaylar">
              <Chip size="small" variant="outlined" icon={<HourglassEmptyIcon />} label="SY onayı bekliyor" sx={{ height: 22 }} />
            </Tooltip>}
    </Box>
  )
}

export default function ProposalReviewDrawer({ proposal, group, onClose, onDecide, deciding }: Props) {
  const open = proposal !== null
  // Kardeş domainler backend'den (kapsam-dışı SY üyesi de tüm domainleri görsün — sertifikanın
  // SAN'ı zaten hepsini açığa vurur). Yanıt gelene kadar sayfadan gelen (scoped) grup ile başla.
  const { data: fetchedGroup } = useQuery<TransferProposal[]>({
    queryKey: ['proposal-group', proposal?.id],
    queryFn: async () => (await api.get(`/proposals/${proposal!.id}/group`)).data,
    enabled: open,
  })
  const effGroup = fetchedGroup && fetchedGroup.length ? fetchedGroup : group
  // Bu devrin domainleri: incelenen öneri her zaman en başta, sonra kardeşleri.
  const scopeItems = proposal
    ? [proposal, ...effGroup.filter((g) => g.id !== proposal.id)]
    : []
  const multiDomain = scopeItems.length > 1
  const { data: oldCert, isLoading: loadOld } = useQuery<Certificate>({
    queryKey: ['certificate', proposal?.old_cert_id],
    queryFn: async () => (await api.get(`/certificates/${proposal!.old_cert_id}`)).data,
    enabled: open,
  })
  const { data: newCert, isLoading: loadNew } = useQuery<Certificate>({
    queryKey: ['certificate', proposal?.new_cert_id],
    queryFn: async () => (await api.get(`/certificates/${proposal!.new_cert_id}`)).data,
    enabled: open,
  })
  const loading = loadOld || loadNew || !oldCert || !newCert

  // Güvenlik kanıtı hesapları
  const keySame = !!oldCert && !!newCert && !!normHex(oldCert.subject_key_identifier) &&
    normHex(oldCert.subject_key_identifier) === normHex(newCert.subject_key_identifier)
  const subjSame = !!oldCert && norm(oldCert.subject) === norm(newCert?.subject) && !!norm(oldCert.subject)
  const caSame = !!oldCert && norm(oldCert.issuer) === norm(newCert?.issuer) && !!norm(oldCert.issuer)
  const oldDays = oldCert?.days_left
  const newDays = newCert?.days_left
  const delta = typeof oldDays === 'number' && typeof newDays === 'number' ? newDays - oldDays : null

  const fields: Field[] = oldCert && newCert ? [
    { label: 'Subject (CN)', kind: 'expect-same', oldVal: oldCert.subject, newVal: newCert.subject, same: norm(oldCert.subject) === norm(newCert.subject), mono: true },
    { label: 'SAN', kind: 'expect-same', oldVal: oldCert.san, newVal: newCert.san, same: norm(oldCert.san) === norm(newCert.san) },
    { label: 'Issuer (CA)', kind: 'expect-same', oldVal: oldCert.issuer, newVal: newCert.issuer, same: norm(oldCert.issuer) === norm(newCert.issuer), mono: true },
    { label: 'SKI (anahtar)', kind: 'expect-same', oldVal: oldCert.subject_key_identifier, newVal: newCert.subject_key_identifier, same: normHex(oldCert.subject_key_identifier) === normHex(newCert.subject_key_identifier), mono: true },
    { label: 'AKI', kind: 'expect-same', oldVal: oldCert.authority_key_identifier, newVal: newCert.authority_key_identifier, same: normHex(oldCert.authority_key_identifier) === normHex(newCert.authority_key_identifier), mono: true },
    { label: 'SHA-256 parmak izi', kind: 'expect-change', oldVal: oldCert.fingerprint_sha256, newVal: newCert.fingerprint_sha256, same: normHex(oldCert.fingerprint_sha256) === normHex(newCert.fingerprint_sha256), mono: true },
    { label: 'Serial', kind: 'expect-change', oldVal: oldCert.serial_number, newVal: newCert.serial_number, same: normHex(oldCert.serial_number) === normHex(newCert.serial_number), mono: true },
    { label: 'Başlangıç', kind: 'expect-change', oldVal: oldCert.valid_from, newVal: newCert.valid_from, same: oldCert.valid_from === newCert.valid_from, render: 'date' },
    { label: 'Bitiş', kind: 'expect-change', oldVal: oldCert.valid_to, newVal: newCert.valid_to, same: oldCert.valid_to === newCert.valid_to, render: 'date' },
  ] : []

  const identityFields = fields.filter((f) => f.kind === 'expect-same')
  const uniqueFields = fields.filter((f) => f.kind === 'expect-change')
  const fpChanged = !!oldCert && !!newCert && normHex(oldCert.fingerprint_sha256) !== normHex(newCert.fingerprint_sha256)
    && !!normHex(oldCert.fingerprint_sha256) && !!normHex(newCert.fingerprint_sha256)
  const mismatchCount = fields.filter((f) => f.kind === 'expect-same' && !f.same).length

  return (
    <Drawer anchor="right" open={open} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', md: 880 }, maxWidth: '100%' } } }}>
      {proposal && (
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Başlık */}
          <Box sx={{ px: 3, pt: 2.5, pb: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  {proposal.kind === 'trusted_add' ? 'Trust Store İncelemesi' : 'Devir İncelemesi'}
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mt: 0.5 }}>
                  <Typography variant="body2" color="text.secondary">
                    {proposal.kind === 'trusted_add'
                      ? `${proposal.app_name ?? 'uygulama'} (trust store)`
                      : (proposal.domain_name ?? (proposal.app_dependency_id ? 'mTLS bağımlılığı' : 'hedef yok'))}
                  </Typography>
                  {proposal.kind === 'trusted_add'
                    ? <Chip size="small" variant="outlined" color="secondary" label="trusted (ekle)" sx={{ height: 20 }} />
                    : proposal.mapping_type && (
                        <Chip size="small" variant="outlined" label={mappingTypeLabel(proposal.mapping_type)}
                              color={proposal.mapping_type === 'server' ? 'error' : 'info'} sx={{ height: 20 }} />
                      )}
                  {proposal.sy_team_name
                    ? <Chip size="small" label={proposal.sy_team_name} sx={{ height: 20 }} />
                    : <Chip size="small" variant="outlined" color="warning" label="sahipsiz" sx={{ height: 20 }} />}
                </Box>
              </Box>
              <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
            </Box>
          </Box>

          {/* İçerik */}
          <Box sx={{ flexGrow: 1, overflow: 'auto', px: 3, py: 2.5 }}>
            {loading ? (
              <Stack spacing={2}>
                <Skeleton variant="rounded" height={120} />
                <Skeleton variant="rounded" height={90} />
                <Skeleton variant="rounded" height={280} />
              </Stack>
            ) : (
              <Stack spacing={2.5}>
                {/* İki uç: ESKİ → YENİ */}
                <Box sx={{ display: 'flex', alignItems: 'stretch', gap: 1.5 }}>
                  <CertCard cert={oldCert} tone="old" kicker="ESKİ · ŞU AN AKTİF" />
                  <Box sx={{ display: 'flex', alignItems: 'center', color: 'info.main' }}>
                    <ArrowRightAltIcon sx={{ fontSize: 34 }} />
                  </Box>
                  <CertCard cert={newCert} tone="new" kicker="YENİ · DEVREDİLECEK" />
                </Box>

                {/* Kapsam — bu devrin domainleri ve ayrı SY onayları */}
                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
                    <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                      Kapsam · {scopeItems.length} domain
                    </Typography>
                    {multiDomain && (
                      <Chip size="small" color="info" variant="outlined" label="her domain ayrı onaylanır" sx={{ height: 22 }} />
                    )}
                  </Box>
                  {multiDomain && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.25 }}>
                      Bu sertifika birden fazla domaine bağlı. Devir, <strong>her domain için o domainin sahibi SY
                      ekibince ayrı ayrı</strong> onaylanır (admin hepsini onaylayabilir). Aşağıdaki her satır bağımsız
                      bir karardır; yalnızca <strong>inceleniyor</strong> etiketli satırı şu an karara bağlıyorsunuz.
                    </Typography>
                  )}
                  <Stack spacing={0.75}>
                    {scopeItems.map((p) => <ScopeRow key={p.id} p={p} current={p.id === proposal.id} />)}
                  </Stack>
                </Box>

                {/* Güvenlik kanıtı */}
                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                    Güvenlik Kanıtı
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mt: 1 }}>
                    <Evidence ok={keySame} warn={!keySame}
                              icon={<VpnKeyIcon fontSize="small" />}
                              title={keySame ? 'Aynı özel anahtar korunuyor' : 'Yeni anahtar çifti'}
                              detail={keySame ? 'SKI birebir eşleşiyor — özel anahtar değişmedi' : 'SKI farklı — anahtar yenilendi'} />
                    <Evidence ok={subjSame} warn={!subjSame}
                              icon={<VerifiedUserIcon fontSize="small" />}
                              title={subjSame ? 'Subject birebir aynı' : 'Subject değişti'}
                              detail={subjSame ? 'Sertifika aynı kimliği (CN) taşıyor' : 'CN farklı — birebir yenileme değil'} />
                    <Evidence ok={caSame} warn={!caSame}
                              icon={<VerifiedUserIcon fontSize="small" />}
                              title={caSame ? 'Aynı sertifika otoritesi' : 'CA değişti'}
                              detail={caSame ? 'Issuer aynı — güven zinciri korunuyor' : 'Farklı CA tarafından imzalanmış'} />
                    <Evidence ok={delta !== null && delta > 0}
                              icon={<EventRepeatIcon fontSize="small" />}
                              title="Geçerlilik uzuyor"
                              detail={`Eski ${daysLeftLabel(oldDays)} → Yeni ${daysLeftLabel(newDays)}${delta !== null ? ` (${delta >= 0 ? '+' : ''}${delta} gün)` : ''}`} />
                    <Evidence ok={fpChanged} warn={!fpChanged}
                              icon={<FingerprintIcon fontSize="small" />}
                              title={fpChanged ? 'Benzersiz sertifika' : 'Parmak izi doğrulanamadı'}
                              detail={fpChanged ? 'SHA-256 parmak izi eski≠yeni — gerçekten yeni bir sertifika' : 'Eski/yeni parmak izi kayıtlı değil ya da aynı'} />
                    <Evidence ok={proposal.live_seen}
                              icon={<TravelExploreIcon fontSize="small" />}
                              title={proposal.live_seen ? 'Canlıda görüldü' : 'Henüz canlıda görülmedi'}
                              detail={proposal.live_seen ? 'Yeni sertifika sunucuda tespit edildi' : 'Devir öncesi canlı doğrulama önerilir'} />
                    <Evidence ok icon={<RuleIcon fontSize="small" />}
                              title={proposal.signal === 'ski' ? 'Sinyal: aynı anahtar' : proposal.signal === 'subject' ? 'Sinyal: aynı CN + CA' : 'Elle eşleme'}
                              detail={`Kaynak: ${proposal.via ?? '—'}`} />
                  </Box>
                </Box>

                {/* Detaylı karşılaştırma */}
                <Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                    <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
                      Alan Karşılaştırması
                    </Typography>
                    {mismatchCount === 0
                      ? <Chip size="small" color="success" variant="outlined" icon={<CheckCircleIcon />}
                              label="Kimlik alanları eşleşiyor" sx={{ height: 22 }} />
                      : <Chip size="small" color="warning" variant="outlined" icon={<WarningAmberIcon />}
                              label={`${mismatchCount} alan beklenmedik şekilde farklı`} sx={{ height: 22 }} />}
                  </Box>
                  <Box sx={{
                    display: 'grid', gridTemplateColumns: '24px 132px 1fr 1fr', gap: 1.25,
                    px: 1, pb: 0.5, borderBottom: '1px solid', borderColor: 'divider',
                  }}>
                    <Box />
                    <Typography variant="caption" color="text.disabled" sx={{ fontWeight: 700 }}>ALAN</Typography>
                    <Typography variant="caption" color="text.disabled" sx={{ fontWeight: 700 }}>ESKİ</Typography>
                    <Typography variant="caption" color="info.main" sx={{ fontWeight: 700 }}>YENİ</Typography>
                  </Box>
                  <GroupHeader tone="match" label="KİMLİK · eşleşmeli (aynı sertifikanın yenilenmiş hali)" />
                  <Stack divider={<Divider flexItem />} sx={{ mt: 0.25 }}>
                    {identityFields.map((f) => <CompareRow key={f.label} f={f} />)}
                  </Stack>
                  <GroupHeader tone="unique" label="BENZERSİZ · her yenilemede değişmeli (yeni sertifika kanıtı)" />
                  <Stack divider={<Divider flexItem />} sx={{ mt: 0.25 }}>
                    {uniqueFields.map((f) => <CompareRow key={f.label} f={f} />)}
                  </Stack>
                  <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mt: 1 }}>
                    <strong>Kimlik</strong> alanları (Subject, CA, SKI) eşleşmeli — devrin aynı sertifikanın yenilenmiş
                    hali olduğunu gösterir. <strong>Benzersiz</strong> alanlar (parmak izi, serial) ise değişmeli —
                    gerçekten yeni bir sertifika olduğunu kanıtlar.
                  </Typography>
                </Box>
              </Stack>
            )}
          </Box>

          {/* Karar çubuğu (sticky) */}
          <Box sx={{
            px: 3, py: 2, borderTop: '1px solid', borderColor: 'divider',
            display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', bgcolor: 'background.paper',
          }}>
            {proposal.can_decide ? (
              <>
                <Typography variant="caption" color="text.secondary"
                            sx={{ flex: '1 1 220px', minWidth: 0 }}>
                  {proposal.kind === 'trusted_add'
                    ? 'Onaylandığında yeni sertifika uygulamanın trust store\'una eklenir; eski trusted sertifika KALIR (devir/pasife alma yok). Reddederseniz hiçbir değişiklik olmaz.'
                    : 'Onaylandığında eşleme yeni sertifikaya taşınır, eski kayıt pasife alınır. Reddederseniz hiçbir değişiklik olmaz.'}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5, flexShrink: 0, ml: 'auto' }}>
                  <Button variant="outlined" color="error" startIcon={<CancelIcon />} disabled={deciding}
                          onClick={() => onDecide(proposal.id, 'reject')} sx={{ whiteSpace: 'nowrap' }}>
                    Reddet
                  </Button>
                  <Button variant="contained" color="success" startIcon={<CheckCircleIcon />} disabled={deciding}
                          onClick={() => onDecide(proposal.id, 'approve')} sx={{ whiteSpace: 'nowrap' }}>
                    Onayla ve Uygula
                  </Button>
                </Box>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Bu öneriyi yalnız domain'in SY ekibi üyesi veya admin karara bağlayabilir.
              </Typography>
            )}
          </Box>
        </Box>
      )}
    </Drawer>
  )
}
