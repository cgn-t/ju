import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CloseIcon from '@mui/icons-material/Close'
import CloseFullscreenIcon from '@mui/icons-material/CloseFullscreen'
import LightbulbOutlinedIcon from '@mui/icons-material/LightbulbOutlined'
import OpenInFullIcon from '@mui/icons-material/OpenInFull'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import SendIcon from '@mui/icons-material/Send'
import {
  Box, Chip, CircularProgress, Fab, IconButton, Link as MuiLink, Menu, MenuItem, Paper, Stack,
  TextField, ThemeProvider, Tooltip, Typography, createTheme, type Theme,
} from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import { BRAND_DARK, BRAND_DARKER, BRAND_GRADIENT } from '../theme'

// AI asistanı: Ayarlar > AI Asistanı açıkken her sayfanın sağ altında simge. Sohbet bu sekmede
// (sessionStorage) tutulur; AI yalnız OKUR, kayıtları sunucu tarafında soranın yetkisiyle görür.
type ChatMessage = { role: 'user' | 'assistant'; content: string; error?: boolean }
type AiStatus = { enabled: boolean; name: string; suggestions?: string[] }
type AiAnswer = { answer: string; tools_used: string[]; tool_mode: boolean }

const STORE_KEY = 'jumbo.ai.chat'
const BIG_KEY = 'jumbo.ai.big'

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

// Satır içi: **kalın**, `kod` ve [metin](/yol) bağlantıları (iç yollar sayfayı açar).
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

// Basit Markdown: başlık (#), madde (- / * / 1.) ve paragraflar.
export function AiText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, i) => {
        const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/)
        const heading = line.match(/^#{1,4}\s+(.*)$/)
        if (!line.trim()) return <Box key={i} sx={{ height: 6 }} />
        if (heading) return <Typography key={i} sx={{ fontWeight: 700, fontSize: 14, mt: 0.5 }}>{inline(heading[1])}</Typography>
        if (bullet) {
          return (
            <Box key={i} sx={{ display: 'flex', gap: 0.75, pl: 0.5 }}>
              <span>•</span><Box sx={{ minWidth: 0 }}>{inline(bullet[1])}</Box>
            </Box>
          )
        }
        return <Fragment key={i}><Box>{inline(line)}</Box></Fragment>
      })}
    </>
  )
}

export default function AiAssistant() {
  const location = useLocation()
  const { data: status } = useQuery<AiStatus>({
    queryKey: ['ai-status'],
    queryFn: async () => (await api.get('/ai/status')).data,
    staleTime: 5 * 60_000,
  })
  const [open, setOpen] = useState(false)
  const [big, setBig] = useState(readBig)
  const [messages, setMessages] = useState<ChatMessage[]>(readStored)
  const [input, setInput] = useState('')
  const [tipsAnchor, setTipsAnchor] = useState<HTMLElement | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(messages.slice(-40)))
    } catch { /* depolama kapalıysa sohbet yalnız bellekte kalır */ }
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, open])

  const toggleBig = () => setBig((b) => {
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
    onSuccess: (d) => setMessages((ms) => [...ms, { role: 'assistant', content: d.answer }]),
    onError: (e) => setMessages((ms) => [...ms, { role: 'assistant', content: apiErrorMessage(e), error: true }]),
  })

  if (!status?.enabled) return null
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

  // Normal: geniş pencere (560 × 760). Büyük: ekranın neredeyse tamamı (menü hariç değil, üstte durur).
  const size = big
    ? { width: { xs: 'calc(100vw - 16px)', sm: 'min(1100px, calc(100vw - 48px))' },
        height: { xs: 'calc(100vh - 100px)', sm: 'calc(100vh - 120px)' } }
    : { width: { xs: 'calc(100vw - 16px)', sm: 560 },
        height: { xs: 'calc(100vh - 100px)', sm: 'min(760px, calc(100vh - 120px))' } }
  const fontSize = big ? 15 : 14.5

  return (
    <ThemeProvider theme={brandTheme}>
      {open && (
        <Paper elevation={8} role="dialog" aria-label={name} sx={{
          position: 'fixed', zIndex: (t) => t.zIndex.drawer + 2, right: { xs: 8, sm: 24 }, bottom: { xs: 80, sm: 96 },
          ...size, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 3,
          transition: 'width 160ms ease, height 160ms ease',
        }}>
          <Box sx={{ px: 2, py: 1.25, display: 'flex', alignItems: 'center', gap: 1,
                     background: BRAND_GRADIENT, color: '#fff' }}>
            <AutoAwesomeIcon fontSize="small" />
            <Typography sx={{ fontWeight: 700, flexGrow: 1 }}>{name}</Typography>
            <Tooltip title="Yeni sohbet">
              <span>
                <IconButton size="small" color="inherit" aria-label="Yeni sohbet"
                            disabled={!messages.length || ask.isPending} onClick={() => setMessages([])}>
                  <RestartAltIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title={big ? 'Küçült' : 'Büyüt'}>
              <IconButton size="small" color="inherit" aria-label={big ? 'Küçült' : 'Büyüt'} onClick={toggleBig}>
                {big ? <CloseFullscreenIcon fontSize="small" /> : <OpenInFullIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <IconButton size="small" color="inherit" aria-label="Kapat" onClick={() => setOpen(false)}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          <Box sx={{ flexGrow: 1, overflowY: 'auto', px: big ? 3 : 2, py: 2, bgcolor: 'background.default' }}>
            {!messages.length && (
              <Stack spacing={1.5} sx={{ mt: 1, maxWidth: 760, mx: 'auto' }}>
                <Typography variant="body2" color="text.secondary">
                  Merhaba! Sertifikalar, domainler ve değişiklik talepleri hakkında sorabilirsiniz.
                  Yalnız görmeye yetkili olduğunuz kayıtlara bakarım, hiçbir şeyi değiştirmem.
                </Typography>
                {suggestions.map((s) => (
                  <Chip key={s} label={s} variant="outlined" onClick={() => send(s)}
                        sx={{ justifyContent: 'flex-start', height: 'auto', py: 0.75,
                              '& .MuiChip-label': { whiteSpace: 'normal' } }} />
                ))}
              </Stack>
            )}
            <Stack spacing={1.5}>
              {messages.map((m, i) => (
                <Box key={i} sx={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <Box sx={{
                    maxWidth: big ? '78%' : '88%', px: 1.75, py: 1.1, borderRadius: 2, fontSize, lineHeight: 1.55,
                    wordBreak: 'break-word',
                    ...(m.role === 'user'
                      ? { bgcolor: BRAND_DARK, color: '#fff', whiteSpace: 'pre-wrap' }
                      : m.error
                        ? { bgcolor: 'error.light', color: 'error.contrastText' }
                        : { bgcolor: 'background.paper', border: 1, borderColor: 'divider' }),
                  }}>
                    {m.role === 'user' ? m.content : <AiText text={m.content} />}
                  </Box>
                </Box>
              ))}
              {ask.isPending && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary', fontSize: 13 }}>
                  <CircularProgress size={14} /> Düşünüyor…
                </Box>
              )}
              <div ref={endRef} />
            </Stack>
          </Box>

          <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider' }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-end' }}>
              {suggestions.length > 0 && messages.length > 0 && (
                <Tooltip title="Hazır sorular">
                  <IconButton aria-label="Hazır sorular" onClick={(e) => setTipsAnchor(e.currentTarget)}>
                    <LightbulbOutlinedIcon />
                  </IconButton>
                </Tooltip>
              )}
              <TextField fullWidth size="small" multiline minRows={big ? 2 : 1} maxRows={big ? 8 : 5}
                         placeholder="Sorunuzu yazın…" value={input} onChange={(e) => setInput(e.target.value)}
                         onKeyDown={(e) => {
                           if (e.key === 'Enter' && !e.shiftKey) {
                             e.preventDefault()
                             send(input)
                           }
                         }} />
              <IconButton color="primary" aria-label="Gönder" disabled={!input.trim() || ask.isPending}
                          onClick={() => send(input)}>
                <SendIcon />
              </IconButton>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              AI yanılabilir; önemli kararlardan önce kaydı açıp kontrol edin. Shift+Enter yeni satır.
            </Typography>
          </Box>
          <Menu anchorEl={tipsAnchor} open={!!tipsAnchor} onClose={() => setTipsAnchor(null)}
                anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
                transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                slotProps={{ paper: { sx: { maxWidth: 480 } } }}>
            {suggestions.map((s) => (
              <MenuItem key={s} sx={{ whiteSpace: 'normal', fontSize: 14 }}
                        onClick={() => { setTipsAnchor(null); send(s) }}>
                {s}
              </MenuItem>
            ))}
          </Menu>
        </Paper>
      )}

      <Tooltip title={open ? '' : `${name}'a sor`} placement="left">
        <Fab aria-label={`${name}'a sor`} onClick={() => setOpen((o) => !o)}
             sx={{ position: 'fixed', right: { xs: 16, sm: 24 }, bottom: { xs: 16, sm: 24 },
                   zIndex: (t) => t.zIndex.drawer + 2, color: '#fff', background: BRAND_GRADIENT,
                   '&:hover': { background: BRAND_DARKER } }}>
          {open ? <CloseIcon /> : <AutoAwesomeIcon />}
        </Fab>
      </Tooltip>
    </ThemeProvider>
  )
}
