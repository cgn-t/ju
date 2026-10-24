import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined'
import GppGoodOutlinedIcon from '@mui/icons-material/GppGoodOutlined'
import HubOutlinedIcon from '@mui/icons-material/HubOutlined'
import PolicyOutlinedIcon from '@mui/icons-material/PolicyOutlined'
import { Box, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { CARD_SX, GRID4, IconBadge, Section, StatusPill, type Tone } from './DetailCards'

/** Canlı doğrulamanın ek kontrolleri (live_check_detail içindeki dns / multi_ip / caa / ocsp_stapling). */
interface Check { status?: string; note?: string }
interface IpRow { ip: string; result: string; cert?: string; valid_to?: string; error?: string }
export interface ExtraDetail {
  dns?: Check & { ips?: string[]; cname?: string }
  multi_ip?: Check & { ips?: IpRow[] }
  caa?: Check & { domain?: string; records?: string[]; issuer?: string; allowed?: string[] }
  ocsp_stapling?: Check & { cert_status?: string; next_update?: string }
}

const DNS: Record<string, [string, Tone]> = {
  ok: ['Kayıt var', 'success'], missing: ['Kayıt yok', 'error'],
}
const MULTI: Record<string, [string, Tone]> = {
  same: ['Hepsi aynı', 'success'], different: ['Farklı sertifika', 'error'], unknown: ['Kontrol edilemedi', 'warning'],
}
const CAA: Record<string, [string, Tone]> = {
  allowed: ['CA izinli', 'success'], not_allowed: ['CA izinli değil', 'warning'],
  none: ['Kayıt yok', 'default'], unknown: ['Sorgulanamadı', 'warning'],
}
const STAPLE: Record<string, [string, Tone]> = {
  stapled: ['Açık', 'success'], not_stapled: ['Kapalı', 'default'], stale: ['Yanıt eski', 'warning'],
  invalid: ['Geçersiz yanıt', 'warning'], not_applicable: ['Uygulanamaz', 'default'], unknown: ['Kontrol edilemedi', 'warning'],
}
const IP_RESULT: Record<string, [string, Tone]> = {
  same: ['Aynı', 'success'], other_bound: ['Farklı ama domaine bağlı', 'default'],
  different: ['FARKLI', 'error'], unreachable: ['Bağlanılamadı', 'warning'],
}

function CheckCard({ icon, title, check, map, empty, children }: {
  icon: ReactNode; title: string; check?: Check; map: Record<string, [string, Tone]>; empty: string; children?: ReactNode
}) {
  const [label, tone] = (check?.status && map[check.status]) || ['—', 'default' as Tone]
  return (
    <Box sx={{ ...CARD_SX, p: 2, display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
      <Stack direction="row" spacing={1.25} sx={{ alignItems: 'center' }}>
        <IconBadge size={32} tone={check ? tone : 'default'}>{icon}</IconBadge>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, flexGrow: 1 }}>{title}</Typography>
        {check && <StatusPill size="small" tone={tone} label={label} />}
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
        {check?.note || empty}
      </Typography>
      {children}
    </Box>
  )
}

export default function LiveExtraChecks({ detail, host }: { detail: ExtraDetail; host?: string }) {
  const { dns, multi_ip: multi, caa, ocsp_stapling: staple } = detail
  if (!dns && !multi && !caa && !staple) return null
  const isIp = !!host && /^[\d.]+$|:/.test(host)
  const singleIp = dns?.status === 'ok' && (dns.ips?.length ?? 0) < 2
  return (
    <Section title="Ek kontroller" aside="DNS, IP'ler, CAA ve OCSP Stapling. Envanterde hiçbir şeyi değiştirmez.">
      <Box sx={GRID4}>
        <CheckCard icon={<DnsOutlinedIcon fontSize="small" />} title="DNS kaydı" check={dns} map={DNS}
                   empty={isIp ? 'Adres bir IP; DNS kontrolü yapılmaz.' : 'Kontrol edilmedi.'} />
        <CheckCard icon={<HubOutlinedIcon fontSize="small" />} title="Çoklu IP" check={multi} map={MULTI}
                   empty={singleIp ? 'Ad tek bir IP gösteriyor; karşılaştırılacak başka sunucu yok.'
                     : isIp ? 'Adres bir IP; tek sunucu.' : 'Kontrol edilmedi.'}>
          {multi?.ips && multi.ips.length > 0 && (
            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
              {multi.ips.map((r) => {
                const [l, t] = IP_RESULT[r.result] ?? [r.result, 'default' as Tone]
                return (
                  <Stack key={r.ip} direction="row" spacing={1} sx={{ alignItems: 'center', minWidth: 0 }}
                         title={r.error || (r.cert ? `${r.cert}${r.valid_to ? ` — ValidTo ${new Date(r.valid_to).toLocaleDateString('tr-TR')}` : ''}` : undefined)}>
                    <Typography variant="caption" sx={{ fontFamily: 'monospace', flexGrow: 1, minWidth: 0 }} noWrap>{r.ip}</Typography>
                    <StatusPill size="small" tone={t} label={l} />
                  </Stack>
                )
              })}
            </Stack>
          )}
        </CheckCard>
        <CheckCard icon={<PolicyOutlinedIcon fontSize="small" />} title="CAA" check={caa} map={CAA}
                   empty={isIp ? 'Adres bir IP; CAA kontrolü yapılmaz.' : 'Kontrol edilmedi.'}>
          {caa?.records && caa.records.length > 0 && (
            <Box sx={{ mt: 0.5 }}>
              <Typography variant="caption" color="text.secondary">{caa.domain} kaydı:</Typography>
              {caa.records.map((r) => (
                <Typography key={r} variant="caption" component="div" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{r}</Typography>
              ))}
            </Box>
          )}
        </CheckCard>
        <CheckCard icon={<GppGoodOutlinedIcon fontSize="small" />} title="OCSP Stapling" check={staple} map={STAPLE}
                   empty="Kontrol edilmedi." />
      </Box>
    </Section>
  )
}
