import { ButtonBase, Menu, MenuItem, Tooltip } from '@mui/material'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import JumboAiIcon from './JumboAiIcon'

// Jumbo AI düğmesi sürüklenebilir (v3.9.25): bırakıldığı yerde kalır; ekran dışına ve soldaki menünün
// üstüne çıkmaz; yeri bu tarayıcıda hatırlanır (sağ/alt kenara uzaklık olarak, pencere boyu değişince
// köşeye göre yerinde kalsın). Kısa tıklama paneli açar; sürüklemek açmaz. Sağ tık: "Varsayılan yere taşı".

const POS_KEY = 'jumbo.ai.launcherPos'
const SIZE = 68          // simge 60 + iç boşluk
const MARGIN = 24        // kenar boşluğu
const DRAG_PX = 5        // bu kadar oynamadan sürükleme sayılmaz

type Pos = { right: number; bottom: number }
const DEFAULT_POS: Pos = { right: MARGIN, bottom: MARGIN }

function readPos(): Pos {
  try {
    const p = JSON.parse(localStorage.getItem(POS_KEY) || 'null')
    if (p && typeof p.right === 'number' && typeof p.bottom === 'number') return p
  } catch { /* bozuk kayıt: varsayılan */ }
  return DEFAULT_POS
}

function savePos(p: Pos | null) {
  try {
    if (p) localStorage.setItem(POS_KEY, JSON.stringify(p))
    else localStorage.removeItem(POS_KEY)
  } catch { /* depolama kapalıysa yalnız bu oturumda geçerli */ }
}

// Kaydırma çubuğu hariç görünen genişlik (testte clientWidth 0 olur)
const viewW = () => document.documentElement.clientWidth || window.innerWidth

// Soldaki menünün sağ kenarı (dar ekranda menü gizli → 0)
const navRight = () => document.querySelector('nav[aria-label="Ana menü"]')?.getBoundingClientRect().right ?? 0

const clamp = (p: Pos): Pos => ({
  right: Math.max(MARGIN, Math.min(p.right, viewW() - navRight() - SIZE - MARGIN)),
  bottom: Math.max(MARGIN, Math.min(p.bottom, window.innerHeight - SIZE - MARGIN)),
})

export default function AiLauncher({ name, onOpen }: { name: string; onOpen: () => void }) {
  const [pos, setPos] = useState<Pos>(readPos)
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const start = useRef<{ px: number; py: number; ox: number; oy: number; moved: boolean } | null>(null)
  const [, setTick] = useState(0)

  // Pencere küçülünce düğme ekranda kalsın
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
    const next = clamp({ right: viewW() - r.right, bottom: window.innerHeight - r.bottom })
    setDrag(null)
    setPos(next)
    savePos(next)
  }

  const place = drag
    ? { left: drag.x, top: drag.y }
    : clamp(pos)

  return (
    <>
      <Tooltip title={drag ? '' : `${name}'a sor · sürükleyerek taşıyabilirsiniz`}
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
                   transition: drag ? 'none' : 'transform 150ms ease, right 200ms ease, bottom 200ms ease',
                   '&:hover': { transform: drag ? 'scale(1.12)' : 'scale(1.08)' },
                   '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'primary.main' } }}>
          <JumboAiIcon size={60} />
        </ButtonBase>
      </Tooltip>
      <Menu open={!!menu} onClose={() => setMenu(null)} anchorReference="anchorPosition"
            anchorPosition={menu ? { top: menu.y, left: menu.x } : undefined}>
        <MenuItem onClick={() => { setMenu(null); onOpen() }}>{name}'ı aç</MenuItem>
        <MenuItem onClick={() => { setMenu(null); setPos(DEFAULT_POS); savePos(null) }}>
          Varsayılan yere taşı (sağ alt)
        </MenuItem>
      </Menu>
    </>
  )
}
