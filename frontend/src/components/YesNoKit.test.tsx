import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { YesNoChecklist, YesNoSwitch } from './YesNoKit'

function Harness({ initial, required }: { initial: string; required?: boolean }) {
  const [v, setV] = useState(initial)
  return <><YesNoSwitch label="WAF Güncelleme" value={v} onChange={setV} required={required} /><output>{v}</output></>
}

describe('YesNoSwitch', () => {
  it('boş zorunlu alan "Seçilmedi" ve uyarı gösterir; açınca Evet, kapatınca Hayır olur', async () => {
    render(<Harness initial="" required />)
    expect(screen.getByText('Seçilmedi')).toBeInTheDocument()
    expect(screen.getByText(/Zorunlu alan/)).toBeInTheDocument()
    const sw = screen.getByRole('switch', { name: 'WAF Güncelleme' })
    await userEvent.click(sw)
    expect(screen.getByRole('status').textContent).toBe('Evet')
    await userEvent.click(sw)
    expect(screen.getByRole('status').textContent).toBe('Hayır')
    expect(screen.queryByText(/Zorunlu alan/)).not.toBeInTheDocument()
  })
})

describe('YesNoChecklist', () => {
  it('Evet/Hayır değerini ve anahtar durumunu gösterir; eski serbest metinde anahtar yok', () => {
    render(<YesNoChecklist title="Sertifika yenilemede yapılacaklar" rows={[
      { label: 'LB', icon: null, value: 'Evet' },
      { label: 'WAF', icon: null, value: 'Hayır' },
      { label: 'Pin', icon: null, value: 'Gerekirse' },
    ]} />)
    const lb = screen.getByTestId('yesno-LB')
    expect(lb).toHaveTextContent('Evet')
    expect(lb.querySelector('input')).toBeChecked()
    expect(screen.getByTestId('yesno-WAF').querySelector('input')).not.toBeChecked()
    expect(screen.getByTestId('yesno-Pin').querySelector('input')).toBeNull()
    expect(screen.getByTestId('yesno-Pin')).toHaveTextContent('Gerekirse')
  })
})
