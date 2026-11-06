import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { InfoCard } from './DetailCards'

describe('InfoCard çok satırlı metin', () => {
  it('multiline ile yazılan satır sonları korunur (pre-wrap)', () => {
    render(<InfoCard title="Detay" value={'1. satır\n2. satır'} multiline />)
    const el = screen.getByText((_, n) => n?.textContent === '1. satır\n2. satır' && n.children.length === 0)
    expect(getComputedStyle(el).whiteSpace).toBe('pre-wrap')
  })

  it('kısa değerli kartlar eskisi gibi (pre-wrap yok)', () => {
    render(<InfoCard title="Ortam" value="Prod" />)
    expect(getComputedStyle(screen.getByText('Prod')).whiteSpace).not.toBe('pre-wrap')
  })
})

describe('ValidityCard renk açıklaması', () => {
  const DAY = 86_400_000
  const mk = (fromDaysAgo: number, toInDays: number) => ({
    valid_from: new Date(Date.now() - fromDaysAgo * DAY).toISOString(),
    valid_to: new Date(Date.now() + toInDays * DAY).toISOString(),
    days_left: toInDays,
  })
  it('geçerli sertifikada geçen, güvenli, uyarı ve bugün açıklanır', async () => {
    const { ValidityCard } = await import('./DetailCards')
    render(<ValidityCard cert={mk(300, 90)} warnDays={30} />)
    const legend = screen.getByTestId('validity-legend')
    expect(legend).toHaveTextContent('Geçen süre: 300 gün')
    expect(legend).toHaveTextContent('Güvenli süre: 60 gün')
    expect(legend).toHaveTextContent('Uyarı dönemi: son 30 gün')
    expect(legend).toHaveTextContent('Bugün:')
  })
  it('uyarı döneminde geçen ve kalan uyarı günleri ayrı gösterilir', async () => {
    const { ValidityCard } = await import('./DetailCards')
    render(<ValidityCard cert={mk(345, 19)} warnDays={30} />)
    const legend = screen.getByTestId('validity-legend')
    expect(legend).toHaveTextContent('Geçen süre: 334 gün')
    expect(legend).toHaveTextContent('Uyarı dönemi, geçen: 11 gün')
    expect(legend).toHaveTextContent('Uyarı dönemi, kalan: 19 gün')
    expect(legend).not.toHaveTextContent('Güvenli süre')
  })
  it('süresi dolmuşta yalnız "Süresi doldu" açıklaması', async () => {
    const { ValidityCard } = await import('./DetailCards')
    render(<ValidityCard cert={mk(375, -10)} warnDays={30} />)
    expect(screen.getByTestId('validity-legend')).toHaveTextContent('Süresi doldu: 10 gün önce')
    expect(screen.getByTestId('validity-legend')).not.toHaveTextContent('Bugün')
  })
})
