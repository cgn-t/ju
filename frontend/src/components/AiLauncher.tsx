import { ButtonBase, Menu, MenuItem, Tooltip } from '@mui/material'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import JumboAiIcon from './JumboAiIcon'

// Jumbo AI düğmesi sürüklenebilir (v3.9.25): yalnız sağ alt ve sağ üst köşede durur (sahibin isteği);
// bırakınca yakın olan köşeye geçer. Köşe bu tarayıcıda hatırlanır. Kısa tıklama paneli açar;
// sürüklemek açmaz. Sağ tık menüsünden de köşe seçilir.

const POS_KEY = 'jumbo.ai.launcherPos'
const SIZE = 68          // simge 60 + iç boşluk
const MARGIN = 24        // kenar boşluğu
const DRAG_PX = 5        // bu kadar oynamadan sürükleme sayılmaz

type Corner = 'br' | 'tr'
const CORNERS: { id: Corner; label: string }[] = [
  { id: 'br', label: 'Sağ alt (varsayılan)' }, { id: 'tr', label: 'Sağ üst' },
]
const DEFAULT_CORNER: Corner = 'br'

function readCorner(): Corner {
  try {
    const c = localStorage.getItem(POS_KEY)
    if (CORNERS.some((x) => x.id === c)) return c as Corner
  } catch { /* depolama kapalı: varsayılan */ }
  return DEFAULT_CORNER
}

function saveCorner(c: Corner) {
  try {
    if (c === DEFAULT_CORNER) localStorage.removeItem(POS_KEY)
    else localStorage.setItem(POS_KEY, c)
  } catch { /* depolama kapalıysa yalnız bu oturumda geçerli */ }
}

// Kaydırma çubuğu hariç görünen genişlik (testte clientWidth 0 olur)
const viewW = () => document.documentElement.clientWidth || window.innerWidth

// Soldaki menünün sağ kenarı (dar ekranda menü gizli → 0)
const navRight = () => document.querySelector('nav[aria-label="Ana menü"]')?.getBoundingClientRect().right ?? 0

const cornerPlace = (c: Corner) => ({ right: MARGIN, ...(c === 'br' ? { bottom: MARGIN } : { top: MARGIN }) })

export default function AiLauncher({ name, onOpen }: { name: string; onOpen: () => void }) {
  const [corner, setCorner] = useState<Corner>(readCorner)
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const start = useRef<{ px: number; py: number; ox: number; oy: number; moved: boolean } | null>(null)
  const [, setTick] = useState(0)

  // Pencere boyu değişince yeniden çiz
  useEffect(() => {
    const onResize = () => setTick((t) => t + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return
    const r = e.currentTarget.getBoundingClientRect()
    start.current = { px: e.clientX, py: e.clientY, ox: e.clientX - r.left, oy: e.clientY - r.top, moved: false }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = start.current
    if (!s) return
    if (!s.moved && Math.hypot(e.clientX - s.px, e.clientY - s.py) < DRAG_PX) return
    s.moved = true
    const x = Math.max(navRight(), Math.min(e.clientX - s.ox, viewW() - SIZE))
    const y = Math.max(0, Math.min(e.clientY - s.oy, window.innerHeight - SIZE))
    setDrag({ x, y })
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = start.current
    start.current = null
    if (!s) return
    if (!s.moved) { onOpen(); return }
    const r = e.currentTarget.getBoundingClientRect()
    const next: Corner = r.top + r.height / 2 > window.innerHeight / 2 ? 'br' : 'tr'
    setDrag(null)
    pick(next)
  }

  const pick = (c: Corner) => { setCorner(c); saveCorner(c) }
  const place = drag ? { left: drag.x, top: drag.y } : cornerPlace(corner)

  return (
    <>
      <Tooltip title={drag ? '' : `${name}'a sor · sağ üst/alt köşeye sürükleyebilirsiniz`}
               placement="left">
        <ButtonBase aria-label={`${name}'a sor`}
             onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
             onPointerCancel={() => { start.current = null; setDrag(null) }}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
             onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY }) }}
             sx={{ position: 'fixed', ...place, width: SIZE, height: SIZE, touchAction: 'none',
                   zIndex: (t) => t.zIndex.drawer + 1, p: 0.5, borderRadius: 2,
                   cursor: drag ? 'grabbing' : 'pointer',
                   filter: 'drop-shadow(0 3px 4px rgba(0,0,0,.28))',
                   transition: 'transform 150ms ease',
                   '&:hover': { transform: drag ? 'scale(1.12)' : 'scale(1.08)' },
                   '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'primary.main' } }}>
          <JumboAiIcon size={60} />
        </ButtonBase>
      </Tooltip>
      <Menu open={!!menu} onClose={() => setMenu(null)} anchorReference="anchorPosition"
            anchorPosition={menu ? { top: menu.y, left: menu.x } : undefined}>
        <MenuItem onClick={() => { setMenu(null); onOpen() }}>{name}'ı aç</MenuItem>
        {CORNERS.map((c) => (
          <MenuItem key={c.id} selected={c.id === corner} onClick={() => { setMenu(null); pick(c.id) }}>
            {c.label} köşeye taşı
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}
