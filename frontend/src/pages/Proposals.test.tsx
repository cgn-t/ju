import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { TransferProposal } from '../api/types'
import { renderPage } from '../test/render'
import Proposals from './Proposals'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../hooks/usePageAccess', () => ({ usePageAccess: () => ({ proposals: true }) }))
const apiGet = vi.mocked(api.get)

const PROP: TransferProposal = {
  id: 7, old_cert_id: 1, old_cert_name: 'eski.akbank.com', new_cert_id: 2, new_cert_name: 'yeni.akbank.com',
  domain_id: 42, domain_name: 'www.akbank.com', mapping_type: 'server', kind: 'transfer', sy_team_id: 3,
  sy_team_name: 'Kanallar SY', status: 'pending', live_seen: true, created_by: 'system',
  created_at: '2026-10-23T08:00:00Z', can_decide: true,
}

function mockApi() {
  apiGet.mockImplementation(async (url: string) => {
    if (url === '/proposals/page') {
      return { data: { items: [PROP], total: 1, page: 0, size: 25, domain_name: 'www.akbank.com',
                       counts: { pending: 1, applied: 4, approved: 0, rejected: 2, cancelled: 0, all: 7 },
                       facets: { kind: { transfer: 1, all: 1 } } } }
    }
    if (url === '/teams') return { data: [{ id: 3, name: 'Kanallar SY', type: 'SY' }] }
    if (url === '/domains/options') return { data: [{ id: 42, domain: 'www.akbank.com' }] }
    if (url.startsWith('/proposals/')) return { data: [] }
    throw new Error(`beklenmeyen istek: ${url}`)
  })
}

describe('Değişiklik Talepleri sayfası', () => {
  beforeEach(() => { apiGet.mockReset(); mockApi() })

  it('domain penceresindeki "Onaya git" bağlantısıyla o domaine filtreli açılır', async () => {
    renderPage(<Proposals />, { url: '/proposals?domain=42' })
    expect(await screen.findByText('Domain: www.akbank.com')).toBeInTheDocument()
    expect(apiGet).toHaveBeenCalledWith('/proposals/page', {
      params: expect.objectContaining({ status: 'pending', domain_id: 42, page: 0, size: 25 }),
    })
    // Durum sekmeleri sayılarıyla
    expect(screen.getByRole('tab', { name: /Bekleyen\s*1/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Uygulanan\s*4/ })).toBeInTheDocument()
  })

  it('filtre çipi kaldırılınca domain filtresi adresten silinir', async () => {
    renderPage(<Proposals />, { url: '/proposals?domain=42&kind=transfer' })
    const chip = await screen.findByText('Domain: www.akbank.com')
    await userEvent.click(chip.parentElement!.querySelector('svg')!)
    await waitFor(() => expect(window.location.search).not.toContain('domain='))
    expect(window.location.search).toContain('kind=transfer')
  })

  it('sekme değişince durum adrese yazılır ve sunucuya gider', async () => {
    renderPage(<Proposals />, { url: '/proposals' })
    await userEvent.click(await screen.findByRole('tab', { name: /Reddedilen/ }))
    await waitFor(() => expect(window.location.search).toContain('status=rejected'))
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/proposals/page', {
      params: expect.objectContaining({ status: 'rejected' }),
    }))
  })
})
