import { Box } from '@mui/material'

// Jumbo AI simgesi: menüdeki Jumbo fili + başının üstünde altın ışıltı (sahibin seçimi "C2", v3.9.24)
const GOLD = '#f5b700'
const STAR = 'M12 2Q13.8 10.2 22 12Q13.8 13.8 12 22Q10.2 13.8 2 12Q10.2 10.2 12 2Z'

export default function JumboAiIcon({ size }: { size: number }) {
  return (
    <Box aria-hidden sx={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <Box component="img" src="/favicon.svg" alt="" draggable={false}
           sx={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
      <Box component="svg" viewBox="0 0 24 24"
           sx={{ position: 'absolute', left: '-6%', top: '-10%', width: '42%', height: '42%' }}>
        <path fill={GOLD} d={STAR} />
      </Box>
      <Box component="svg" viewBox="0 0 24 24"
           sx={{ position: 'absolute', left: '28%', top: '-16%', width: '18%', height: '18%' }}>
        <path fill={GOLD} d={STAR} />
      </Box>
    </Box>
  )
}
