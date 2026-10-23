import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { ChainCheckFinding } from '../api/types'
import { renderPage } from '../test/render'
import ChainCheckDialog from './ChainCheckDialog'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

const FINDINGS: ChainCheckFinding[] = [
  { certificate_id: 4, name: 'cihaz.jumbo.local', kind: 'type', current: 'Intermediate', expected: 'Leaf' },
  { certificate_id: 9, name: 'srv.jumbo.local', kind: 'parent', current: '—', expected: 'Jumbo Kök CA' },
]

describe('ChainCheckDialog', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('farkları listeler ve Düzelt ile uygular', async () => {
    apiGet.mockResolvedValue({ data: FINDINGS })
    apiPost.mockResolvedValue({ data: FINDINGS })
    const onClose = vi.fn()
    renderPage(<ChainCheckDialog open onClose={onClose} />, { url: '/certificates' })
    expect(await screen.findByText('cihaz.jumbo.local')).toBeInTheDocument()
    expect(screen.getByText('Leaf')).toBeInTheDocument()
    expect(screen.getByText('Parent (Issuer)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Düzelt (2)' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/certificates/chain-check/apply'))
    expect(await screen.findByText('2 düzeltme yapıldı')).toBeInTheDocument()
    expect(onClose).toHaveBeenCalled()
  })

  it('sorun yoksa bunu söyler, Düzelt kapalı', async () => {
    apiGet.mockResolvedValue({ data: [] })
    renderPage(<ChainCheckDialog open onClose={() => {}} />, { url: '/certificates' })
    expect(await screen.findByText(/Sorun bulunamadı/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Düzelt (0)' })).toBeDisabled()
  })
})
