import { ButtonBase, Menu, MenuItem, Tooltip } from '@mui/material'
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import JumboAiIcon from './JumboAiIcon'

// Jumbo AI düğmesi sürüklenebilir (v3.9.25): hep sağ kenarda kalır, yalnız yukarı-aşağı taşınır
// (sahibin isteği). Yüksekliği bu tarayıcıda alt kenara uzaklık olarak hatırlanır; pencere küçülünce
// ekranda kalır. Kısa tıklama paneli açar; sürüklemek açmaz. Sağ tık: "Varsayılan yere taşı".
const POS_KEY = 'jumbo.ai.launcherBottom'
const SIZE = 68          // simge 60 + iç boşluk
const MARGIN = 24        // kenar boşluğu
const DRAG_PX = 5        // bu kadar oynamadan sürükleme sayılmaz

function readBottom(): number {
  try {
    const b = Number(localStorage.getItem(POS_KEY))
    if (Number.isFinite(b) && b > 0) return b
  } catch { /* depolama kapalı: varsayılan */ }
  return MARGIN
}

function saveBottom(b: number | null) {
  try {
    if (b === null) localStorage.removeItem(POS_KEY)
    else localStorage.setItem(POS_KEY, String(Math.round(b)))
  } catch { /* depolama kapalıysa yalnız bu oturumda geçerli */ }
}

const clampBottom = (b: number) => Math.max(MARGIN, Math.min(b, window.innerHeight - SIZE - MARGIN))

export default function AiLauncher({ name, onOpen }: { name: string; onOpen: () => void }) {
  const [bottom, setBottom] = useState(readBottom)
  const [dragTop, setDragTop] = useState<number | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const start = useRef<{ py: number; oy: number; moved: boolean } | null>(null)
  const [, setTick] = useState(0)

  // Pencere boyu değişince düğme ekranda kalsın
  useEffect(() => {
    const onResize = () => setTick((t) => t + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return
    const r = e.currentTarget.getBoundingClientRect()
    start.current = { py: e.clientY, oy: e.clientY - r.top, moved: false }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = start.current
    if (!s) return
    if (!s.moved && Math.abs(e.clientY - s.py) < DRAG_PX) return
    s.moved = true
    setDragTop(Math.max(MARGIN, Math.min(e.clientY - s.oy, window.innerHeight - SIZE - MARGIN)))
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const s = start.current
    start.current = null
    if (!s) return
    if (!s.moved) { onOpen(); return }
    const top = dragTop ?? e.currentTarget.getBoundingClientRect().top
    const next = clampBottom(window.innerHeight - top - SIZE)
    setDragTop(null)
    setBottom(next)
    saveBottom(next)
  }

  const place = dragTop !== null ? { top: dragTop } : { bottom: clampBottom(bottom) }

  return (
    <>
      <Tooltip title={dragTop !== null ? '' : `${name}'a sor · yukarı-aşağı sürükleyebilirsiniz`} placement="left">
        <ButtonBase aria-label={`${name}'a sor`}
             onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
             onPointerCancel={() => { start.current = null; setDragTop(null) }}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
             onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY }) }}
             sx={{ position: 'fixed', right: MARGIN, ...place, width: SIZE, height: SIZE, touchAction: 'none',
                   zIndex: (t) => t.zIndex.drawer + 1, p: 0.5, borderRadius: 2,
                   cursor: dragTop !== null ? 'grabbing' : 'pointer',
                   filter: 'drop-shadow(0 3px 4px rgba(0,0,0,.28))',
                   transition: 'transform 150ms ease',
                   '&:hover': { transform: dragTop !== null ? 'scale(1.12)' : 'scale(1.08)' },
                   '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'primary.main' } }}>
          <JumboAiIcon size={60} />
        </ButtonBase>
      </Tooltip>
      <Menu open={!!menu} onClose={() => setMenu(null)} anchorReference="anchorPosition"
            anchorPosition={menu ? { top: menu.y, left: menu.x } : undefined}>
        <MenuItem onClick={() => { setMenu(null); onOpen() }}>{name}'ı aç</MenuItem>
        <MenuItem onClick={() => { setMenu(null); setBottom(MARGIN); saveBottom(null) }}>
          Varsayılan yere taşı (sağ alt)
        </MenuItem>
      </Menu>
    </>
  )
}
