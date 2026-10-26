import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CloseIcon from '@mui/icons-material/Close'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import SendIcon from '@mui/icons-material/Send'
import {
  Box, Chip, CircularProgress, Fab, IconButton, Link as MuiLink, Paper, Stack, TextField, Tooltip,
  Typography,
} from '@mui/material'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'

// AI asistanı: Ayarlar > AI Asistanı açıkken her sayfanın sağ altında simge. Sohbet bu sekmede
// (sessionStorage) tutulur; AI yalnız OKUR, kayıtları sunucu tarafında soranın yetkisiyle görür.
type ChatMessage = { role: 'user' | 'assistant'; content: string; error?: boolean }
type AiStatus = { enabled: boolean; name: string }
type AiAnswer = { answer: string; tools_used: string[]; tool_mode: boolean }

const STORE_KEY = 'jumbo.ai.chat'
const SUGGESTIONS = [
  'Önümüzdeki 30 günde süresi dolacak sertifikalar hangileri?',
  'Onay bekleyen değişiklik talepleri neler?',
  'Süresi dolmuş domainleri listele',
]

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
  const [messages, setMessages] = useState<ChatMessage[]>(readStored)
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(messages.slice(-40)))
    } catch { /* depolama kapalıysa sohbet yalnız bellekte kalır */ }
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, open])

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

  const send = (text: string) => {
    const q = text.trim()
    if (!q || ask.isPending) return
    const next = [...messages, { role: 'user' as const, content: q }]
    setMessages(next)
    setInput('')
    ask.mutate(next)
  }

  return (
    <>
      {open && (
        <Paper elevation={8} role="dialog" aria-label={name} sx={{
          position: 'fixed', zIndex: (t) => t.zIndex.drawer + 2, right: { xs: 8, sm: 24 }, bottom: { xs: 80, sm: 96 },
          width: { xs: 'calc(100vw - 16px)', sm: 420 }, height: { xs: 'calc(100vh - 100px)', sm: 600 },
          maxHeight: 'calc(100vh - 110px)', display: 'flex', flexDirection: 'column', overflow: 'hidden',
          borderRadius: 3,
        }}>
          <Box sx={{ px: 2, py: 1.25, display: 'flex', alignItems: 'center', gap: 1,
                     bgcolor: 'primary.main', color: 'primary.contrastText' }}>
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
            <IconButton size="small" color="inherit" aria-label="Kapat" onClick={() => setOpen(false)}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          <Box sx={{ flexGrow: 1, overflowY: 'auto', px: 2, py: 1.5, bgcolor: 'background.default' }}>
            {!messages.length && (
              <Stack spacing={1.5} sx={{ mt: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  Merhaba! Sertifikalar, domainler ve değişiklik talepleri hakkında sorabilirsiniz.
                  Yalnız görmeye yetkili olduğunuz kayıtlara bakarım, hiçbir şeyi değiştirmem.
                </Typography>
                {SUGGESTIONS.map((s) => (
                  <Chip key={s} label={s} variant="outlined" onClick={() => send(s)}
                        sx={{ justifyContent: 'flex-start', height: 'auto', py: 0.75,
                              '& .MuiChip-label': { whiteSpace: 'normal' } }} />
                ))}
              </Stack>
            )}
            <Stack spacing={1.25}>
              {messages.map((m, i) => (
                <Box key={i} sx={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                  <Box sx={{
                    maxWidth: '88%', px: 1.5, py: 1, borderRadius: 2, fontSize: 14, lineHeight: 1.5,
                    wordBreak: 'break-word',
                    ...(m.role === 'user'
                      ? { bgcolor: 'primary.main', color: 'primary.contrastText', whiteSpace: 'pre-wrap' }
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

          <Box sx={{ p: 1.25, borderTop: 1, borderColor: 'divider' }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "flex-end" }}>
              <TextField fullWidth size="small" multiline maxRows={4} placeholder="Sorunuzu yazın…"
                         value={input} onChange={(e) => setInput(e.target.value)}
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
              AI yanılabilir; önemli kararlardan önce kaydı açıp kontrol edin.
            </Typography>
          </Box>
        </Paper>
      )}

      <Tooltip title={open ? '' : `${name}'a sor`} placement="left">
        <Fab color="primary" aria-label={`${name}'a sor`} onClick={() => setOpen((o) => !o)}
             sx={{ position: 'fixed', right: { xs: 16, sm: 24 }, bottom: { xs: 16, sm: 24 },
                   zIndex: (t) => t.zIndex.drawer + 2 }}>
          {open ? <CloseIcon /> : <AutoAwesomeIcon />}
        </Fab>
      </Tooltip>
    </>
  )
}
