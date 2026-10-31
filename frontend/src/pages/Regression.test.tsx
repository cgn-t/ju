import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { renderPage } from '../test/render'
import { AI_ASK_EVENT } from '../utils/aiAsk'
import Regression from './Regression'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

const CATALOG = { total: 2, version: '3.9.27', sections: [{ key: 'mail', title: 'Mail gönderimi', note: 'Kendi adresinize gönderin.',
  scenarios: [
    { id: 'MAIL-A1', sub: '', title: 'Test Maili Gönder', expected: 'Yeşil bildirim çıkar' },
    { id: 'MAIL-A2', sub: '', title: 'Var olmayan adres', expected: 'Kırmızı bildirim' },
  ] }] }
const RUN = { id: 'R1', title: 'v3.9.27 preprod', version: '3.9.27', started_by: 'admin', started_at: '2026-10-30T20:00:00Z',
  finished_at: null, finished_by: null, counts: { pass: 1, fail: 0, skip: 0, pending: 1, total: 2 } }

function mockGet(ai = true) {
  apiGet.mockImplementation(async (url: string) => {
    if (url === '/regression/catalog') return { data: CATALOG }
    if (url === '/regression/runs') return { data: [RUN] }
    if (url === '/regression/runs/R1') return { data: { ...RUN, marks: { 'MAIL-A1': { result: 'pass', note: '', by: 'admin', at: '2026-10-30T20:01:00Z' } } } }
    if (url === '/ai/status') return { data: { enabled: ai, name: 'Jumbo AI' } }
    if (url === '/regression/checks') return { data: { checks: [{ id: 'smtp', group: 'Bağlantılar', title: 'Mail sunucusu' }], last: null } }
    throw new Error(url)
  })
}

describe('Regression', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    localStorage.removeItem('jumbo.regression.run')
  })

  it('senaryoları sayılarla gösterir, işaret kaydeder', async () => {
    mockGet()
    apiPost.mockResolvedValue({ data: { result: 'fail', note: '', by: 'admin', at: '' } })
    renderPage(<Regression />, { url: '/regression' })
    expect(await screen.findByText('Test Maili Gönder')).toBeTruthy()
    expect(await screen.findByText('1 geçti')).toBeTruthy()
    expect(screen.getByText('1 bekliyor')).toBeTruthy()
    const group = screen.getByRole('group', { name: 'MAIL-A2 sonucu' })
    await userEvent.click(within(group).getByRole('button', { name: 'Kaldı' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/regression/runs/R1/marks',
      { scenario: 'MAIL-A2', result: 'fail', note: '' }))
  })

  it('AI menüsü senaryoyu AI paneline gönderir', async () => {
    mockGet()
    const seen: string[] = []
    const onAsk = (e: Event) => seen.push((e as CustomEvent<string>).detail)
    window.addEventListener(AI_ASK_EVENT, onAsk)
    renderPage(<Regression />, { url: '/regression' })
    await userEvent.click(await screen.findByRole('button', { name: 'MAIL-A2 için AI yardımı' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Adımı anlat' }))
    window.removeEventListener(AI_ASK_EVENT, onAsk)
    expect(seen[0]).toContain('MAIL-A2')
    expect(seen[0]).toContain('Beklenen: Kırmızı bildirim')
  })

  it('AI kapalıyken AI düğmeleri görünmez', async () => {
    mockGet(false)
    renderPage(<Regression />, { url: '/regression' })
    await screen.findByText('Test Maili Gönder')
    expect(screen.queryByRole('button', { name: /AI yardımı/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'AI ile Özetle' })).toBeNull()
  })
})
