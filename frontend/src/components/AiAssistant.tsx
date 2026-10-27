import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft'
import KeyboardDoubleArrowRightIcon from '@mui/icons-material/KeyboardDoubleArrowRight'
import LightbulbOutlinedIcon from '@mui/icons-material/LightbulbOutlined'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import SendIcon from '@mui/icons-material/Send'
import {
  Box, ButtonBase, CircularProgress, Drawer, Fab, IconButton, Link as MuiLink, Menu, MenuItem, Stack,
  TextField, ThemeProvider, Tooltip, Typography, createTheme, useMediaQuery, type Theme,
} from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import { useAiStatus } from '../hooks/useAiStatus'
import { BRAND_DARK, BRAND_DARKER, BRAND_GRADIENT } from '../theme'

// AI asistanı: Ayarlar > AI Asistanı açıkken her sayfanın sağ altında simge. Sohbet bu sekmede
// (sessionStorage) tutulur; AI yalnız OKUR. Neyi görebileceğine sunucu karar verir (Ayarlar'daki
// tam erişim; kişisel bilgiler hiçbir zaman verilmez). "Nasıl yapılır" sorularını kurum wiki'sindeki
// Kullanım Kılavuzu'ndan cevaplar.
type ChatMessage = { role: 'user' | 'assistant'; content: string; error?: boolean; sources?: string[] }
type AiAnswer = { answer: string; tools_used: string[]; tool_mode: boolean }

const STORE_KEY = 'jumbo.ai.chat'
const BIG_KEY = 'jumbo.ai.big'
const PANEL_W = 480          // normal genişlik
const PANEL_W_WIDE = 760     // "Genişlet"
const MIN_PAGE_W = 720       // sayfa bundan daralacaksa panel sayfayı itmez, üstüne açılır

// Cevabın altında "Baktığı yerler": AI'ın kullandığı araç → ekran adı
const SOURCE_LABELS: Record<string, string> = {
  sertifika_ara: 'SSL Sertifikaları', sertifika_detay: 'SSL Sertifikaları',
  domain_ara: 'Domainler', domain_detay: 'Domainler', degisiklik_talepleri: 'Değişiklik Talepleri',
  genel_durum: 'Anasayfa', kayit_gecmisi: 'Audit Log', uyum_ihlalleri: 'Uyum',
  kilavuz_ara: 'Kullanım Kılavuzu', kilavuz_oku: 'Kullanım Kılavuzu',
  veri_tablolari: 'Jumbo veritabanı', veri_sorgula: 'Jumbo veritabanı',
}

// Panel içi vurgu rengi sol menünün koyu kırmızısı (bağlantı, odak çizgisi, gönder düğmesi).
// Koyu temada koyu kırmızı yazı okunmadığı için bağlantılar açık tonda kalır; simge/başlık/balon aynı.
const brandTheme = (outer: Theme) => createTheme(outer, {
  palette: { primary: { main: outer.palette.mode === 'dark' ? '#e0707a' : BRAND_DARK } },
})

function readBig(): boolean {
  try {
    return localStorage.getItem(BIG_KEY) === '1'
  } catch {
    return false
  }
}

function readStored(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(STORE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

// Satır içi: **kalın**, `kod` ve [metin](/yol) bağlantıları (iç yollar sayfayı açar, wiki gibi dış
// adresler yeni sekmede).
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const key = `${m.index}`
    if (m[1]) {
      const href = m[2]
      out.push(href.startsWith('/')
        ? <MuiLink key={key} component={Link} to={href}>{m[1]}</MuiLink>
        : <MuiLink key={key} href={href} target="_blank" rel="noreferrer">{m[1]}</MuiLink>)
    } else if (m[3]) {
      out.push(<b key={key}>{m[3]}</b>)
    } else {
      out.push(<Box key={key} component="code" sx={{ fontSize: 12.5, bgcolor: 'action.hover', px: 0.5, borderRadius: 0.5 }}>{m[4]}</Box>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

// Basit Markdown: başlık (#), madde (- / *), numaralı adım (1.) ve paragraflar.
export function AiText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, i) => {
        const bullet = line.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/)
        const heading = line.match(/^#{1,4}\s+(.*)$/)
        if (!line.trim()) return <Box key={i} sx={{ height: 6 }} />
        if (heading) return <Typography key={i} sx={{ fontWeight: 700, fontSize: 14, mt: 0.5 }}>{inline(heading[1])}</Typography>
        if (bullet) {
          return (
            <Box key={i} sx={{ display: 'flex', gap: 0.75, pl: 0.5 }}>
              <Box component="span" sx={{ flexShrink: 0, minWidth: 14, whiteSpace: 'nowrap', color: /\d/.test(bullet[1]) ? 'primary.main' : undefined,
                                          fontWeight: /\d/.test(bullet[1]) ? 700 : undefined }}>
                {/\d/.test(bullet[1]) ? bullet[1].replace(')', '.') : '•'}
              </Box>
              <Box sx={{ minWidth: 0 }}>{inline(bullet[2])}</Box>
            </Box>
          )
        }
        return <Fragment key={i}><Box>{inline(line)}</Box></Fragment>
      })}
    </>
  )
}

type Props = {
  /** Sol menünün o anki genişliği — panelin sayfayı itip itmeyeceği hesaplanır */
  navWidth?: number
  /** Panel sayfayı itiyorsa sağda boşaltılacak genişlik (px), itmiyorsa 0 */
  onDock?: (px: number) => void
}

export default function AiAssistant({ navWidth = 0, onDock }: Props) {
  const location = useLocation()
  const { data: status } = useAiStatus()
  const [open, setOpen] = useState(false)
  const [wide, setWide] = useState(readBig)
  const [messages, setMessages] = useState<ChatMessage[]>(readStored)
  const [input, setInput] = useState('')
  const [tipsAnchor, setTipsAnchor] = useState<HTMLElement | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const width = wide ? PANEL_W_WIDE : PANEL_W
  // Ekran yetiyorsa panel sayfayı sola iter (yan yana çalışılır); yetmiyorsa sayfanın üstüne açılır.
  const canDock = useMediaQuery(`(min-width:${navWidth + width + MIN_PAGE_W}px)`)
  const enabled = !!status?.enabled
  const docked = enabled && open && canDock

  useEffect(() => {
    onDock?.(docked ? width : 0)
  }, [docked, width, onDock])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(messages.slice(-40)))
    } catch { /* depolama kapalıysa sohbet yalnız bellekte kalır */ }
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, open])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const toggleWide = () => setWide((b) => {
    try {
      localStorage.setItem(BIG_KEY, b ? '0' : '1')
    } catch { /* yalnız bu oturum için */ }
    return !b
  })

  const ask = useMutation({
    mutationFn: async (history: ChatMessage[]) => (await api.post<AiAnswer>('/ai/chat', {
      messages: history.filter((m) => !m.error).map(({ role, content }) => ({ role, content })),
      page: location.pathname + location.search,
    })).data,
    onSuccess: (d) => setMessages((ms) => [...ms, {
      role: 'assistant', content: d.answer,
      sources: [...new Set((d.tools_used ?? []).map((t) => SOURCE_LABELS[t]).filter(Boolean))],
    }]),
    onError: (e) => setMessages((ms) => [...ms, { role: 'assistant', content: apiErrorMessage(e), error: true }]),
  })

  if (!enabled) return null
  const name = status.name || 'Jumbo AI'
  const suggestions = status.suggestions ?? []

  const send = (text: string) => {
    const q = text.trim()
    if (!q || ask.isPending) return
    const next = [...messages, { role: 'user' as const, content: q }]
    setMessages(next)
    setInput('')
    ask.mutate(next)
  }
  const copy = (text: string) => {
    try {
      void navigator.clipboard?.writeText(text)
    } catch { /* pano erişimi yoksa sessizce geç */ }
  }

  return (
    <ThemeProvider theme={brandTheme}>
      {/* Değişiklik talebi penceresi gibi sağdan açılır; sayfayı karartmaz, sayfa kullanılabilir kalır */}
      <Drawer anchor="right" variant="persistent" open={open}
              slotProps={{ paper: { role: 'dialog', 'aria-label': name, sx: {
                width: { xs: '100%', md: width }, maxWidth: '100%', borderLeft: 1, borderColor: 'divider',
                boxShadow: docked ? 'none' : '-12px 0 32px rgba(0,0,0,0.18)',
                transition: 'width 180ms ease',
              } } }}
              onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Başlık — diğer yan pencerelerle aynı düzen */}
          <Box sx={{ px: 2.5, py: 1.75, borderBottom: 1, borderColor: 'divider' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
              <Box sx={{ width: 36, height: 36, borderRadius: '50%', display: 'grid', placeItems: 'center',
                         background: BRAND_GRADIENT, color: '#fff', flexShrink: 0 }}>
                <AutoAwesomeIcon sx={{ fontSize: 19 }} />
              </Box>
              <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2, flexGrow: 1, minWidth: 0 }} noWrap>
                {name}
              </Typography>
              <Tooltip title="Yeni sohbet">
                <span>
                  <IconButton size="small" aria-label="Yeni sohbet" disabled={!messages.length || ask.isPending}
                              onClick={() => setMessages([])}>
                    <RestartAltIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title={wide ? 'Daralt' : 'Genişlet'}>
                <IconButton size="small" aria-label={wide ? 'Daralt' : 'Genişlet'} onClick={toggleWide}
                            sx={{ display: { xs: 'none', md: 'inline-flex' } }}>
                  {wide ? <KeyboardDoubleArrowRightIcon fontSize="small" /> : <KeyboardDoubleArrowLeftIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
              <Tooltip title="Kapat (Esc)">
                <IconButton size="small" aria-label="Kapat" onClick={() => setOpen(false)}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* Konuşma */}
          <Box sx={{ flexGrow: 1, overflowY: 'auto', px: 2.5, py: 2, bgcolor: 'background.default' }}>
            {!messages.length && (
              <Box sx={{ maxWidth: 640, mx: 'auto', mt: 1 }}>
                <Typography sx={{ fontWeight: 700, fontSize: 17 }}>Size nasıl yardımcı olabilirim?</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
                  Jumbo'daki sertifika, domain, uygulama ve ekip kayıtlarını ya da bir işin nasıl yapılacağını
                  sorabilirsiniz. Kayıtları yalnız okurum, hiçbir şeyi değiştirmem.
                </Typography>
                {suggestions.length > 0 && (
                  <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>Hazır sorular</Typography>
                )}
                <Stack spacing={1}>
                  {suggestions.map((s) => (
                    <ButtonBase key={s} onClick={() => send(s)} sx={{
                      justifyContent: 'flex-start', textAlign: 'left', gap: 1, px: 1.5, py: 1.1,
                      borderRadius: 2, border: 1, borderColor: 'divider', bgcolor: 'background.paper',
                      fontSize: 14, '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' },
                    }}>
                      <LightbulbOutlinedIcon sx={{ fontSize: 18, color: 'primary.main' }} />
                      <Box sx={{ flexGrow: 1 }}>{s}</Box>
                      <ChevronRightIcon sx={{ fontSize: 18, color: 'text.disabled' }} />
                    </ButtonBase>
                  ))}
                </Stack>
              </Box>
            )}
            <Stack spacing={2}>
              {messages.map((m, i) => m.role === 'user' ? (
                <Box key={i} sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Box sx={{ maxWidth: '85%', px: 1.75, py: 1, borderRadius: '14px 14px 4px 14px',
                             bgcolor: BRAND_DARK, color: '#fff', fontSize: 14.5, lineHeight: 1.5,
                             whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {m.content}
                  </Box>
                </Box>
              ) : (
                <Box key={i} sx={{ display: 'flex', gap: 1.25 }}>
                  <Box sx={{ width: 26, height: 26, borderRadius: '50%', display: 'grid', placeItems: 'center',
                             background: BRAND_GRADIENT, color: '#fff', flexShrink: 0, mt: 0.25 }}>
                    <AutoAwesomeIcon sx={{ fontSize: 14 }} />
                  </Box>
                  <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                    <Box sx={{
                      px: 1.75, py: 1.25, borderRadius: '4px 14px 14px 14px', fontSize: 14.5, lineHeight: 1.55,
                      wordBreak: 'break-word', border: 1,
                      ...(m.error
                        ? { bgcolor: 'error.main', color: '#fff', borderColor: 'error.main' }
                        : { bgcolor: 'background.paper', borderColor: 'divider' }),
                    }}>
                      <AiText text={m.content} />
                    </Box>
                    {!m.error && (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5, color: 'text.secondary' }}>
                        <Typography variant="caption" sx={{ flexGrow: 1 }}>
                          {m.sources?.length ? `Baktığı yerler: ${m.sources.join(', ')}` : ''}
                        </Typography>
                        <Tooltip title="Kopyala">
                          <IconButton size="small" aria-label="Cevabı kopyala" onClick={() => copy(m.content)}>
                            <ContentCopyIcon sx={{ fontSize: 15 }} />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    )}
                  </Box>
                </Box>
              ))}
              {ask.isPending && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary', fontSize: 13, pl: 4.5 }}>
                  <CircularProgress size={14} /> Kayıtlara bakıyor…
                </Box>
              )}
              <div ref={endRef} />
            </Stack>
          </Box>

          {/* Yazma alanı */}
          <Box sx={{ px: 2, pt: 1.5, pb: 1, borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
            <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 0.5, border: 1, borderColor: 'divider',
                       borderRadius: 3, px: 1, py: 0.5, '&:focus-within': { borderColor: 'primary.main' } }}>
              {suggestions.length > 0 && messages.length > 0 && (
                <Tooltip title="Hazır sorular">
                  <IconButton size="small" aria-label="Hazır sorular" onClick={(e) => setTipsAnchor(e.currentTarget)}>
                    <LightbulbOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              <TextField fullWidth variant="standard" multiline minRows={1} maxRows={wide ? 10 : 6}
                         placeholder="Sorunuzu yazın…" value={input} inputRef={inputRef}
                         onChange={(e) => setInput(e.target.value)}
                         slotProps={{ input: { disableUnderline: true, sx: { fontSize: 14.5, py: 0.75 } } }}
                         onKeyDown={(e) => {
                           if (e.key === 'Enter' && !e.shiftKey) {
                             e.preventDefault()
                             send(input)
                           }
                         }} />
              <IconButton color="primary" aria-label="Gönder" disabled={!input.trim() || ask.isPending}
                          onClick={() => send(input)}>
                <SendIcon fontSize="small" />
              </IconButton>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, px: 0.5 }}>
              AI yanılabilir; önemli kararlardan önce kaydı açıp kontrol edin. Shift+Enter yeni satır.
            </Typography>
          </Box>
          <Menu anchorEl={tipsAnchor} open={!!tipsAnchor} onClose={() => setTipsAnchor(null)}
                anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
                transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                slotProps={{ paper: { sx: { maxWidth: 460 } } }}>
            {suggestions.map((s) => (
              <MenuItem key={s} sx={{ whiteSpace: 'normal', fontSize: 14 }}
                        onClick={() => { setTipsAnchor(null); send(s) }}>
                {s}
              </MenuItem>
            ))}
          </Menu>
        </Box>
      </Drawer>

      {!open && (
        <Tooltip title={`${name}'a sor`} placement="left">
          <Fab aria-label={`${name}'a sor`} onClick={() => setOpen(true)}
               sx={{ position: 'fixed', right: { xs: 16, sm: 24 }, bottom: { xs: 16, sm: 24 },
                     zIndex: (t) => t.zIndex.drawer + 1, color: '#fff', background: BRAND_GRADIENT,
                     '&:hover': { background: BRAND_DARKER } }}>
            <AutoAwesomeIcon />
          </Fab>
        </Tooltip>
      )}
    </ThemeProvider>
  )
}
