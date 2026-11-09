// Detay / Notlar alanlarındaki basit biçim etiketleri (v3.9.37).
// Metin düz yazı olarak saklanır: [b]kalın[/b] [i]italik[/i] [u]altı çizili[/u] [renk=kirmizi]…[/renk]
// HTML hiçbir zaman saklanmaz ve ekrana ham basılmaz: görünüm React düğümleriyle kurulur,
// düzenleyicinin HTML'i buradaki kaçışlı üretimden gelir ve geri dönüşte yalnız izinli biçimler okunur.
// Sunucudaki karşılığı: backend/app/core/richtext.py (e-posta).

export type RichColor = 'kirmizi' | 'turuncu' | 'yesil' | 'mavi' | 'mor'

export const RICH_COLORS: Record<RichColor, { label: string; light: string; dark: string }> = {
  kirmizi: { label: 'Kırmızı', light: '#c62828', dark: '#ef9a9a' },
  turuncu: { label: 'Turuncu', light: '#e65100', dark: '#ffb74d' },
  yesil: { label: 'Yeşil', light: '#2e7d32', dark: '#81c784' },
  mavi: { label: 'Mavi', light: '#1565c0', dark: '#90caf9' },
  mor: { label: 'Mor', light: '#6a1b9a', dark: '#ce93d8' },
}

export type Mark = 'b' | 'i' | 'u'
export type RichNode =
  | { kind: 'text'; text: string }
  | { kind: 'mark'; mark: Mark; children: RichNode[] }
  | { kind: 'color'; color: RichColor; children: RichNode[] }

const TAG = /\[(\/?)(b|i|u|renk)(?:=([a-z]+))?\]/g

/** Etiketli metni ağaca çevirir. Eşleşmeyen kapanış metin kalır, kapanmamış etiket sonda kapanır. */
export function parseRich(text: string): RichNode[] {
  const root: RichNode[] = []
  const stack: { name: string; children: RichNode[] }[] = []
  const cur = () => (stack.length ? stack[stack.length - 1].children : root)
  const pushText = (t: string) => {
    if (!t) return
    const list = cur()
    const last = list[list.length - 1]
    if (last && last.kind === 'text') last.text += t
    else list.push({ kind: 'text', text: t })
  }
  let pos = 0
  for (const m of text.matchAll(TAG)) {
    const [whole, slash, name, arg] = m
    pushText(text.slice(pos, m.index))
    pos = (m.index ?? 0) + whole.length
    if (!slash) {
      const valid = name === 'renk' ? !!arg && arg in RICH_COLORS : !arg
      if (!valid) { pushText(whole); continue }
      const node: RichNode = name === 'renk'
        ? { kind: 'color', color: arg as RichColor, children: [] }
        : { kind: 'mark', mark: name as Mark, children: [] }
      cur().push(node)
      stack.push({ name, children: node.children })
    } else if (stack.some((s) => s.name === name)) {
      while (stack.length) { if (stack.pop()!.name === name) break }
    } else {
      pushText(whole)
    }
  }
  pushText(text.slice(pos))
  return root
}

/** Etiketleri atılmış düz metin (kopyalama, Excel). */
export function richToPlain(text?: string | null): string {
  if (!text) return ''
  const walk = (ns: RichNode[]): string => ns.map((n) => (n.kind === 'text' ? n.text : walk(n.children))).join('')
  return walk(parseRich(text))
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** Düzenleyici (contentEditable) için kaçışlı HTML. */
export function richToEditorHtml(text: string, dark = false): string {
  const walk = (ns: RichNode[]): string => ns.map((n) => {
    if (n.kind === 'text') return esc(n.text).replace(/\r\n?/g, '\n').replace(/\n/g, '<br>')
    if (n.kind === 'mark') return `<${n.mark}>${walk(n.children)}</${n.mark}>`
    const c = RICH_COLORS[n.color]
    return `<font color="${dark ? c.dark : c.light}">${walk(n.children)}</font>`
  }).join('')
  return walk(parseRich(text))
}

function normColor(c: string): string {
  const s = c.trim().toLowerCase()
  const m = s.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  if (m) return '#' + [m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, '0')).join('')
  if (/^#[0-9a-f]{3}$/.test(s)) return '#' + s.slice(1).split('').map((x) => x + x).join('')
  return s
}

/** Tarayıcı rengini paletteki karşılığına çevirir (açık/koyu tema renkleri ikisi de tanınır). */
export function colorKey(css?: string | null): RichColor | null {
  if (!css) return null
  const n = normColor(css)
  for (const [k, v] of Object.entries(RICH_COLORS)) {
    if (normColor(v.light) === n || normColor(v.dark) === n) return k as RichColor
  }
  return null
}

const BLOCK = new Set(['DIV', 'P', 'LI', 'UL', 'OL', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'PRE'])

/** Düzenleyicinin DOM'unu etiketli metne çevirir; yalnız kalın/italik/altı çizili/renk okunur. */
export function domToRich(root: Node): string {
  let out = ''
  let pendingBreak = false
  const emit = (s: string) => {
    if (!s) return
    if (pendingBreak) { out += '\n'; pendingBreak = false }
    out += s
  }
  const walk = (node: Node): string => {
    // Alt ağacı ayrı bir tamponda topla ki biçim etiketleri yalnız boş olmayan içeriği sarsın.
    const saved = out; const savedPending = pendingBreak
    out = ''; pendingBreak = false
    node.childNodes.forEach((child, idx) => {
      if (child.nodeType === Node.TEXT_NODE) { emit((child.textContent ?? '').replace(/ /g, ' ')); return }
      if (child.nodeType !== Node.ELEMENT_NODE) return
      const el = child as HTMLElement
      const tag = el.tagName
      if (tag === 'SCRIPT' || tag === 'STYLE') return
      if (tag === 'BR') {
        const isLastInBlock = idx === node.childNodes.length - 1 && node !== root
        if (!isLastInBlock) { if (pendingBreak) { out += '\n'; pendingBreak = false } out += '\n' }
        return
      }
      const block = BLOCK.has(tag)
      if (block) {
        if (out.length || pendingBreak) { out += '\n'; pendingBreak = false }
      }
      let inner = walk(el)
      const style = el.style
      const fw = style?.fontWeight
      const color = colorKey(tag === 'FONT' ? el.getAttribute('color') : style?.color)
      if (inner) {
        if (color) inner = `[renk=${color}]${inner}[/renk]`
        if (tag === 'U' || style?.textDecoration?.includes('underline') || style?.textDecorationLine?.includes('underline')) inner = `[u]${inner}[/u]`
        if (tag === 'I' || tag === 'EM' || style?.fontStyle === 'italic') inner = `[i]${inner}[/i]`
        if (tag === 'B' || tag === 'STRONG' || fw === 'bold' || Number(fw) >= 600) inner = `[b]${inner}[/b]`
      }
      emit(inner)
      if (block) pendingBreak = true
    })
    const res = out
    out = saved; pendingBreak = savedPending
    return res
  }
  return walk(root)
}
