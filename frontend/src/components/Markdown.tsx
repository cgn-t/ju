import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { Box, Link as MuiLink, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

// Satır içi: **kalın**, `kod` ve [metin](/yol) bağlantıları (iç yollar sayfayı açar, dışlar yeni sekmede).
export function inlineMd(text: string): ReactNode[] {
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
      out.push(<Box key={key} component="code" sx={{ fontSize: '0.88em', bgcolor: 'action.hover', px: 0.5, borderRadius: 0.5 }}>{m[4]}</Box>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

type Block =
  | { kind: 'h'; level: number; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[]; start: number }
  | { kind: 'note'; lines: string[] }

function parse(text: string): Block[] {
  const blocks: Block[] = []
  for (const raw of text.replace(/\r/g, '').split('\n')) {
    const line = raw.trimEnd()
    const prev = blocks[blocks.length - 1]
    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)$/)
    const note = line.match(/^>\s?(.*)$/)
    if (!line.trim()) {
      blocks.push({ kind: 'p', text: '' })
    } else if (heading) {
      blocks.push({ kind: 'h', level: heading[1].length, text: heading[2] })
    } else if (bullet) {
      if (prev?.kind === 'ul') prev.items.push(bullet[1])
      else blocks.push({ kind: 'ul', items: [bullet[1]] })
    } else if (numbered) {
      if (prev?.kind === 'ol') prev.items.push(numbered[2])
      else blocks.push({ kind: 'ol', items: [numbered[2]], start: Number(numbered[1]) })
    } else if (note) {
      if (prev?.kind === 'note') prev.lines.push(note[1])
      else blocks.push({ kind: 'note', lines: [note[1]] })
    } else if (prev?.kind === 'p' && prev.text) {
      prev.text += ' ' + line.trim()
    } else {
      blocks.push({ kind: 'p', text: line.trim() })
    }
  }
  return blocks.filter((b) => b.kind !== 'p' || b.text)
}

/** Kullanım Kılavuzu metni: ## / ### başlık, - madde, 1. adım, > not kutusu, **kalın**, `kod`, [bağlantı](/yol). */
export default function Markdown({ text }: { text: string }) {
  return (
    <Box sx={{ fontSize: 15, lineHeight: 1.65, '& > *:first-of-type': { mt: 0 } }}>
      {parse(text).map((b, i) => {
        if (b.kind === 'h') {
          return (
            <Typography key={i} component={b.level <= 2 ? 'h2' : 'h3'}
                        sx={{ fontWeight: 700, fontSize: b.level <= 2 ? 18 : 15.5, mt: b.level <= 2 ? 3 : 2, mb: 0.75 }}>
              {inlineMd(b.text)}
            </Typography>
          )
        }
        if (b.kind === 'ul' || b.kind === 'ol') {
          return (
            <Box key={i} component={b.kind} start={b.kind === 'ol' ? b.start : undefined}
                 sx={{ my: 1, pl: 3, '& li': { mb: 0.5, pl: 0.25 }, '& li::marker': { color: 'primary.main', fontWeight: 700 } }}>
              {b.items.map((it, j) => <li key={j}>{inlineMd(it)}</li>)}
            </Box>
          )
        }
        if (b.kind === 'note') {
          return (
            <Box key={i} sx={{ display: 'flex', gap: 1.25, my: 2, px: 2, py: 1.5, borderRadius: 2, border: 1,
                               borderColor: 'divider', borderLeft: 4, borderLeftColor: 'primary.main', bgcolor: 'action.hover' }}>
              <InfoOutlinedIcon sx={{ fontSize: 19, color: 'primary.main', mt: 0.3 }} />
              <Box sx={{ minWidth: 0 }}>{b.lines.map((l, j) => <Box key={j}>{inlineMd(l)}</Box>)}</Box>
            </Box>
          )
        }
        return <Typography key={i} sx={{ my: 1, fontSize: 'inherit', lineHeight: 'inherit' }}>{inlineMd(b.text)}</Typography>
      })}
    </Box>
  )
}
