import { createTheme } from '@mui/material/styles'

export type ThemeMode = 'dark' | 'light'

// Kurumsal gövde yazı tipi — IBM Plex Sans (tek, sabit)
const FONT_STACK = '"IBM Plex Sans","Segoe UI","Roboto","Helvetica","Arial",sans-serif'

// Monospace: seri no, fingerprint, PEM gibi alanlar
export const MONO_FONT = '"JetBrains Mono","SFMono-Regular","Menlo","Consolas",monospace'

// Devir/import sonrası "devir önerisi oluşturuldu" bildirimi — normal bilgiden uzun ama
// eski 8000ms'den kısaltıldı (kullanıcı geri bildirimi: ekranda çok uzun kalıyordu).
export const TRANSFER_TOAST_MS = 3000

// JUMBO teması — koyu mod varsayılan (kurumsal koyu zemin + kırmızı vurgu), açık mod seçilebilir
export function createAppTheme(mode: ThemeMode) {
  return createTheme({
    palette: {
      mode,
      primary: { main: '#e53946' },
      secondary: { main: '#7c4dff' },
      ...(mode === 'dark'
        ? { background: { default: '#101418', paper: '#181d23' } }
        : { background: { default: '#f4f6f8', paper: '#ffffff' } }),
      success: { main: '#4caf50' },
      warning: { main: '#ff9800' },
      error: { main: '#f44336' },
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: FONT_STACK,
      // body1'in letterSpacing'i MUI varsayılanında bırakılırsa outlined alanların notch'unu
      // (görünür etiket transform:scale ile, gizli legend font-size ile küçülür — iki yol
      // piksel-özdeş değil) hesaplayan gizli legend metniyle görünür etiket arasında kayma
      // oluşuyor (çerçeve etiketin içinden geçiyor). 'normal' bu kaymanın letter-spacing
      // bileşenini sıfırlar.
      body1: { letterSpacing: 'normal' },
      h4: { fontWeight: 700, letterSpacing: '-0.02em' },
      h5: { fontWeight: 700, letterSpacing: '-0.01em' },
      h6: { fontWeight: 600 },
      subtitle2: { fontWeight: 600 },
      button: { fontWeight: 600 },
      overline: { fontWeight: 700, letterSpacing: '0.08em' },
    },
    components: {
      // Tarayıcı otomatik-doldurma (autofill) mavi/sarı arka planını tema zeminine sabitle.
      // !important + geniş spread: Chrome'un iç autofill boyamasını her genişlikte tamamen örter.
      MuiCssBaseline: {
        styleOverrides: {
          // Dikey kaydırma çubuğu belirince/kaybolunca sayfa yatay kaymasın: gutter'ı sürekli ayır.
          // (ör. "Pasifleri göster" ile satır artınca scrollbar çıkıp içeriği yana itmiyor.)
          html: { scrollbarGutter: 'stable' },
          'input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus, input:-webkit-autofill:active': {
            WebkitBoxShadow: `0 0 0 1000px ${mode === 'dark' ? '#101418' : '#f4f6f8'} inset !important`,
            WebkitTextFillColor: `${mode === 'dark' ? '#fff' : 'rgba(0,0,0,0.87)'} !important`,
            caretColor: mode === 'dark' ? '#fff' : 'rgba(0,0,0,0.87)',
            transition: 'background-color 9999s ease-in-out 0s',
          },
        },
      },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      // Çok satırlı alanlar (Notlar/Bilgi/PEM …): sabit yükseklikte kalır (rows), içerik taşınca
      // KUTU İÇİNDE kaydırılır — form aşağı itilip diğer alanlar gözden kaçmaz. Kullanıcı isterse
      // sağ-alt köşedeki tutamaçtan dikey büyütebilir.
      MuiInputBase: {
        styleOverrides: { root: { '& textarea': { resize: 'vertical', overflowY: 'auto' } } },
      },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiButton: { styleOverrides: { root: { textTransform: 'none' } } },
      MuiTableCell: {
        styleOverrides: {
          head: { fontWeight: 700, textTransform: 'uppercase', fontSize: 11, letterSpacing: '0.04em' },
        },
      },
      MuiDialogContent: {
        styleOverrides: {
          // MUI, başlığı takip eden içerikte paddingTop:0 uygular → ilk satırdaki outlined
          // etiket üstten kırpılır. Üst boşluğu geri veriyoruz (tüm dialoglar için tek düzeltme).
          root: { '.MuiDialogTitle-root + &': { paddingTop: 16 } },
        },
      },
    },
  })
}

/** Kalan güne göre durum rengi: yeşil / turuncu (<30g) / kırmızı (expired) */
export function daysLeftColor(days: number | null | undefined): 'success' | 'warning' | 'error' | 'default' {
  if (days === null || days === undefined) return 'default'
  if (days < 0) return 'error'
  if (days <= 30) return 'warning'
  return 'success'
}

export function daysLeftLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return '—'
  if (days < 0) return `Süresi Doldu (${Math.abs(days)}g)`
  return `${days}g kaldı`
}

/** Sertifika "Kaynak" (source) alanının kullanıcıya dönük iş-dostu adı. */
export function sourceLabel(source: string | null | undefined): string {
  switch (source) {
    case 'vault': return 'Vault'
    case 'live': return 'Canlı'
    case 'discovery': return 'Ağ Keşfi'
    case 'ct': return 'CT Log'
    default: return 'Manuel'
  }
}

/** Sertifika "Ortam" (environment) alanının kullanıcıya dönük adı. */
export function environmentLabel(environment: string | null | undefined): string {
  switch (environment) {
    case 'prod': return 'Prod'
    case 'test': return 'Test'
    default: return '—'
  }
}

/** Domain-sertifika eşleşme tipinin (mapping_type) kullanıcıya dönük adı — DB'de 'client' kalır, UX'te 'Trusted'. */
export function mappingTypeLabel(mappingType: string | null | undefined): string {
  switch (mappingType) {
    case 'server': return 'Server'
    case 'client': return 'Trusted'
    default: return mappingType ?? '—'
  }
}

export function environmentColor(environment: string | null | undefined): 'error' | 'default' {
  return environment === 'prod' ? 'error' : 'default'
}

export const nodeColors: Record<string, string> = {
  root: '#2196f3',
  intermediate: '#66bb2a',
  leaf: '#f57c00',
  domain: '#9c27b0',
  app: '#26a69a',
}

/** Dağıtım akışı düğüm türü renkleri — ortama göre (Deployments.tsx editörü). */
export const deploymentNodeColors: Record<string, string> = {
  ns: '#2196f3',
  waf: '#e53935',
  windows: '#00897b',
  linux: '#fdd835',
  custom: '#9e9e9e',
}
