import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Certificate, TransferProposal } from '../api/types'
import { renderPage } from '../test/render'
import ProposalReviewDrawer from './ProposalReviewDrawer'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)

const CERT: Certificate = {
  id: 7, name: 'portal.jumbo.local', cert_type: 'leaf', is_active: true, is_internal: true,
  source: 'live', auto_renew: false, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
  subject: 'CN=portal.jumbo.local', san: 'portal.jumbo.local, www.portal.jumbo.local',
  issuer: 'CN=Jumbo Ara CA', subject_key_identifier: 'AA:BB:CC', authority_key_identifier: 'DD:EE:FF',
  fingerprint_sha256: '0123456789ABCDEF0123456789ABCDEF', serial_number: '1F2E3D',
  valid_from: '2026-01-01T00:00:00Z', valid_to: '2027-01-01T00:00:00Z', days_left: 74,
  public_key_type: 'RSA', key_size: 2048, signature_hash: 'sha256',
  domains: [
    { domain_id: 3, domain: 'portal.jumbo.local', mapping_type: 'server' },
    { domain_id: 5, domain: 'api.jumbo.local', mapping_type: 'server' },
  ],
}

const proposal = (kind: TransferProposal['kind']): TransferProposal => ({
  id: 11, kind, old_cert_id: 7, new_cert_id: 7, domain_id: 3, domain_name: 'portal.jumbo.local',
  mapping_type: 'server', status: 'pending', live_seen: true, created_at: '2026-10-19T08:00:00Z',
  can_decide: true, via: 'drift',
})

describe('ProposalReviewDrawer — EKLE / KALDIR', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockImplementation(async (url: string) =>
      ({ data: url.startsWith('/certificates/') ? CERT : [] }) as never)
  })

  it.each([
    ['server_add', 'EKLENECEK SERTİFİKA'],
    ['server_remove', 'KALDIRILACAK SERTİFİKA'],
  ] as const)('%s talebinde sertifikanın tüm alanları görünür', async (kind, header) => {
    renderPage(<ProposalReviewDrawer proposal={proposal(kind)} group={[]} onClose={() => {}}
                                     onDecide={() => {}} deciding={false} />, { url: '/proposals' })
    expect(await screen.findByText('Sertifika Detayı')).toBeInTheDocument()
    expect(screen.getByText(header)).toBeInTheDocument()
    for (const v of ['CN=portal.jumbo.local', 'portal.jumbo.local, www.portal.jumbo.local', 'CN=Jumbo Ara CA',
                     'AA:BB:CC', 'DD:EE:FF', '0123456789ABCDEF0123456789ABCDEF', '1F2E3D', 'RSA 2048', 'sha256']) {
      expect(screen.getByText(v)).toBeInTheDocument()
    }
    // Talebin kendi domaini "diğer bağlantılar"da tekrarlanmaz
    expect(screen.getByText('api.jumbo.local (Server)')).toBeInTheDocument()
    expect(screen.queryByText('portal.jumbo.local (Server)')).not.toBeInTheDocument()
  })
})
