// Detay / Notlar için biçimli metin: görünüm ve araç çubuklu düzenleyici (v3.9.37).
import FormatBoldIcon from '@mui/icons-material/FormatBold'
import FormatClearIcon from '@mui/icons-material/FormatClear'
import FormatColorTextIcon from '@mui/icons-material/FormatColorText'
import FormatItalicIcon from '@mui/icons-material/FormatItalic'
import FormatUnderlinedIcon from '@mui/icons-material/FormatUnderlined'
import { Box, Divider, IconButton, Popover, Stack, Tooltip, Typography, useTheme } from '@mui/material'
import { alpha, type Theme } from '@mui/material/styles'
import { Fragment, type ReactNode, useEffect, useRef, useState } from 'react'
import { domToRich, parseRich, RICH_COLORS, type RichColor, type RichNode, richToEditorHtml } from '../utils/richText'

function renderNodes(nodes: RichNode[], dark: boolean): ReactNode {
  return nodes.map((n, i) => {
    if (n.kind === 'text') return <Fragment key={i}>{n.text}</Fragment>
    const inner = renderNodes(n.children, dark)
    if (n.kind === 'color') {
      const c = RICH_COLORS[n.color]
      return <Box key={i} component="span" sx={{ color: dark ? c.dark : c.light, fontWeight: 600 }}>{inner}</Box>
    }
    if (n.mark === 'b') return <Box key={i} component="strong" sx={{ fontWeight: 700 }}>{inner}</Box>
    if (n.mark === 'i') return <em key={i}>{inner}</em>
    return <u key={i}>{inner}</u>
  })
}

/** Biçimli metni gösterir (satır sonları korunur; üst kutu pre-wrap olmalı ya da bu kullanılır). */
export function RichTextView({ value, empty = '—' }: { value?: string | null; empty?: ReactNode }) {
  const dark = useTheme().palette.mode === 'dark'
  if (!value) return <>{empty}</>
  return <Box component="span" sx={{ whiteSpace: 'pre-wrap' }}>{renderNodes(parseRich(value), dark)}</Box>
}

/** Araç çubuklu düzenleyici: Kalın, İtalik, Altı çizili, Renk, Biçimi temizle. */
export function RichTextEditor({ label, value, onChange, placeholder, minRows = 3, changed, sx }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; minRows?: number
  changed?: boolean; sx?: object
}) {
  const theme = useTheme()
  const dark = theme.palette.mode === 'dark'
  const ref = useRef<HTMLDivElement>(null)
  const last = useRef<string | null>(null)
  const [focused, setFocused] = useState(false)
  const [colorAnchor, setColorAnchor] = useState<HTMLElement | null>(null)
  const savedRange = useRef<Range | null>(null)

  // Dışarıdan gelen değer (ilk açılış, Vazgeç) düzenleyiciye yazılır; yazarken imleç kaçmasın diye
  // kendi ürettiğimiz değer geri geldiğinde dokunulmaz.
  useEffect(() => {
    if (!ref.current || value === last.current) return
    ref.current.innerHTML = richToEditorHtml(value, dark)
    last.current = value
  }, [value, dark])

  const emit = () => {
    if (!ref.current) return
    const v = domToRich(ref.current)
    last.current = v
    onChange(v)
  }
  const exec = (cmd: string, arg?: string) => {
    ref.current?.focus()
    if (savedRange.current) {
      const sel = window.getSelection(); sel?.removeAllRanges(); sel?.addRange(savedRange.current)
      savedRange.current = null
    }
    document.execCommand('styleWithCSS', false, 'false')
    document.execCommand(cmd, false, arg)
    emit()
  }
  const keep = (e: React.MouseEvent) => e.preventDefault()   // düğmeye basınca seçim kaybolmasın
  const btn = (title: string, icon: ReactNode, onClick: (e: React.MouseEvent<HTMLElement>) => void) => (
    <Tooltip title={title}>
      <IconButton size="small" aria-label={title} onMouseDown={keep} onClick={onClick}>{icon}</IconButton>
    </Tooltip>
  )
  const isEmpty = !value

  return (
    <Box sx={sx}>
      <Box sx={(t: Theme) => ({
        position: 'relative', border: 1, borderRadius: 1,
        borderColor: focused ? 'primary.main' : changed ? 'info.main' : t.palette.mode === 'dark' ? 'rgba(255,255,255,0.23)' : 'rgba(0,0,0,0.23)',
        boxShadow: focused ? `inset 0 0 0 1px ${t.palette.primary.main}` : undefined,
        bgcolor: changed ? alpha(t.palette.info.main, 0.04) : undefined,
      })}>
        <Typography component="label" variant="caption" sx={{ position: 'absolute', top: -9, left: 10, px: 0.5,
                     bgcolor: 'background.paper', color: focused ? 'primary.main' : 'text.secondary', lineHeight: 1.4 }}>
          {label}
        </Typography>
        <Stack direction="row" sx={{ alignItems: 'center', gap: 0.25, px: 0.75, pt: 0.75, pb: 0.25, borderBottom: 1, borderColor: 'divider' }}>
          {btn('Kalın (Ctrl+B)', <FormatBoldIcon fontSize="small" />, () => exec('bold'))}
          {btn('İtalik (Ctrl+I)', <FormatItalicIcon fontSize="small" />, () => exec('italic'))}
          {btn('Altı çizili (Ctrl+U)', <FormatUnderlinedIcon fontSize="small" />, () => exec('underline'))}
          {btn('Yazı rengi', <FormatColorTextIcon fontSize="small" />, (e) => {
            const sel = window.getSelection()
            savedRange.current = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null
            setColorAnchor(e.currentTarget)
          })}
          <Divider orientation="vertical" flexItem sx={{ mx: 0.5, my: 0.5 }} />
          {btn('Biçimi temizle', <FormatClearIcon fontSize="small" />, () => exec('removeFormat'))}
        </Stack>
        <Box sx={{ position: 'relative' }}>
          {isEmpty && placeholder && (
            <Typography variant="body2" color="text.disabled" sx={{ position: 'absolute', top: 10, left: 14, pointerEvents: 'none' }}>
              {placeholder}
            </Typography>
          )}
          <Box ref={ref} role="textbox" aria-label={label} aria-multiline contentEditable suppressContentEditableWarning
               onInput={emit} onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); emit() }}
               onPaste={(e: React.ClipboardEvent) => {
                 // Başka yerden yapıştırılan biçim (HTML) alınmaz, yalnız düz metin.
                 e.preventDefault()
                 document.execCommand('insertText', false, e.clipboardData.getData('text/plain'))
               }}
               sx={{ minHeight: `${minRows * 1.5 + 1.25}em`, px: 1.75, py: 1.25, outline: 'none',
                     typography: 'body1', lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                     '& b, & strong': { fontWeight: 700 } }} />
        </Box>
      </Box>
      <Popover open={!!colorAnchor} anchorEl={colorAnchor} onClose={() => setColorAnchor(null)}
               anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }} disableRestoreFocus>
        <Stack direction="row" sx={{ p: 1, gap: 0.75 }}>
          {(Object.keys(RICH_COLORS) as RichColor[]).map((k) => (
            <Tooltip key={k} title={RICH_COLORS[k].label}>
              <IconButton size="small" aria-label={RICH_COLORS[k].label} onMouseDown={keep}
                          onClick={() => { setColorAnchor(null); exec('foreColor', dark ? RICH_COLORS[k].dark : RICH_COLORS[k].light) }}>
                <Box sx={{ width: 20, height: 20, borderRadius: '50%', bgcolor: dark ? RICH_COLORS[k].dark : RICH_COLORS[k].light }} />
              </IconButton>
            </Tooltip>
          ))}
        </Stack>
      </Popover>
    </Box>
  )
}
