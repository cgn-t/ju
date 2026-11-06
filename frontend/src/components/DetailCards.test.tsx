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
