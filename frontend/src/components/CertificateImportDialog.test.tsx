import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { ImportPreview } from '../api/types'
import { renderPage } from '../test/render'
import CertificateImportDialog from './CertificateImportDialog'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

// Eski sertifikası (id 7) bir domaine ve bir uygulamanın trust store'una bağlı yenileme
const RENEWAL: ImportPreview = {
  name: 'devir-test.jumbo.local', serial_number: '01', issuer: 'CN=Root', subject: 'CN=devir-test.jumbo.local',
  subject_key_identifier: 'AA', authority_key_identifier: 'BB', cert_type: 'leaf',
  valid_from: '2026-06-01T00:00:00Z', valid_to: '2027-07-03T00:00:00Z', fingerprint_sha256: 'FP-NEW',
  pem_certificate: '-----BEGIN CERTIFICATE-----', already_exists: false,
  resolved_parent_id: 1, resolved_parent_name: 'Root',
  renewal_of_id: 7, renewal_of_name: 'devir-test.jumbo.local', renewal_signal: 'ski',
  renewal_of_ski: 'AA', renewal_of_valid_to: '2027-02-02T00:00:00Z',
  renewal_of_domains: ['devir-test.jumbo.local (server)'], renewal_of_apps: ['OdemeApp (trust store)'],
  renewal_also: [],
} as ImportPreview

async function pick(label: RegExp, option: string) {
  await userEvent.click(screen.getByRole('combobox', { name: label }))
  await userEvent.click(await screen.findByRole('option', { name: option }))
}

async function fillAndImport() {
  renderPage(<CertificateImportDialog open onClose={() => {}} />, { url: '/certificates' })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, new File(['pem'], 'leaf-v2.pem'))
  await screen.findByText('Yenileme tespit edildi — değişiklik talebi önerisi')
  expect(screen.getByText('Eskinin bağlı olduğu uygulamalar: OdemeApp (trust store)')).toBeInTheDocument()
  await pick(/Oluşturan Ekip/, 'Test SY Ekibi')
  await pick(/Ortam/, 'Test')
}

describe('Sertifika içe aktarma — değişiklik talebi önerisi', () => {
  beforeEach(() => {
    apiGet.mockReset(); apiPost.mockReset()
    apiGet.mockResolvedValue({ data: [{ id: 3, name: 'Test SY Ekibi', type: 'SY' }] })
    apiPost.mockImplementation(async (url: string) => {
      if (url === '/certificates/import/preview') return { data: [RENEWAL] }
      if (url === '/certificates/import') return { data: [{ id: 9, fingerprint_sha256: 'FP-NEW' }] }
      if (url === '/certificates/9/supersede/7') return { data: { proposed: 2 } }
      throw new Error(`beklenmeyen istek: ${url}`)
    })
  })

  it('işaretliyken içe aktarmadan sonra eskinin bağlantıları için talep açar', async () => {
    await fillAndImport()
    expect(screen.getByRole('checkbox', { name: /değişiklik talebi oluştur/ })).toBeChecked()

    await userEvent.click(screen.getByRole('button', { name: 'İçe Aktar' }))
    expect(await screen.findByText('devir-test.jumbo.local bağlantıları için açılacak')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Onaylıyorum, İçe Aktar' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/certificates/9/supersede/7'))
    expect(await screen.findByText(
      '1 sertifika eklendi — 2 değişiklik talebi oluşturuldu (SY onayı bekliyor)')).toBeInTheDocument()
  })

  it('işaret kaldırılırsa talep açmaz', async () => {
    await fillAndImport()
    await userEvent.click(screen.getByRole('checkbox', { name: /değişiklik talebi oluştur/ }))

    await userEvent.click(screen.getByRole('button', { name: 'İçe Aktar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Onaylıyorum, İçe Aktar' }))

    expect(await screen.findByText('1 sertifika eklendi')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalledWith('/certificates/9/supersede/7')
  })
})

// Aynı CN + aynı CA'lı iki eski sertifika: Jumbo hangisinin yerine geçildiğini bilemez
const AMBIGUOUS: ImportPreview = {
  ...RENEWAL, renewal_signal: 'subject', renewal_of_domains: ['localhost:9441 (server)'], renewal_of_apps: [],
  renewal_also: ['devir-test.jumbo.local (bitiş 13.10.2026) — bağlantılar: localhost:9446 (server)'],
  renewal_candidates: [
    { id: 7, name: 'devir-test.jumbo.local', signal: 'subject', subject_key_identifier: 'AA',
      valid_to: '2027-08-14T00:00:00Z', domains: ['localhost:9441 (server)'], apps: [] },
    { id: 8, name: 'devir-test.jumbo.local', signal: 'subject', subject_key_identifier: 'CC',
      valid_to: '2026-10-13T00:00:00Z', domains: ['localhost:9446 (server)'], apps: ['OdemeApp (istemci sertifikası)'] },
  ],
} as ImportPreview

describe('Sertifika içe aktarma — birden çok olası eski sertifika', () => {
  beforeEach(() => {
    apiGet.mockReset(); apiPost.mockReset()
    apiGet.mockResolvedValue({ data: [{ id: 3, name: 'Test SY Ekibi', type: 'SY' }] })
    apiPost.mockImplementation(async (url: string) => {
      if (url === '/certificates/import/preview') return { data: [AMBIGUOUS] }
      if (url === '/certificates/import') return { data: [{ id: 9, fingerprint_sha256: 'FP-NEW' }] }
      if (url === '/certificates/9/supersede/8') return { data: { proposed: 2 } }
      throw new Error(`beklenmeyen istek: ${url}`)
    })
  })

  async function open() {
    renderPage(<CertificateImportDialog open onClose={() => {}} />, { url: '/certificates' })
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await userEvent.upload(input, new File(['pem'], 'yeni.pem'))
    await screen.findByText(/2 eski sertifika var/)
    await pick(/Oluşturan Ekip/, 'Test SY Ekibi')
    await pick(/Ortam/, 'Test')
  }

  it('eski sertifikaları listeler, hiçbiri seçili gelmez; seçilmeden talep açılmaz', async () => {
    await open()
    const radios = screen.getAllByRole('radio')
    expect(radios).toHaveLength(2)
    radios.forEach((r) => expect(r).not.toBeChecked())
    expect(screen.getByText('Bağlantılar: localhost:9446 (server), OdemeApp (istemci sertifikası)')).toBeInTheDocument()
    expect(screen.queryByText(/Diğer olası öncüller/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'İçe Aktar' }))
    expect(await screen.findByText('Açılmayacak — eski sertifika seçilmedi')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Onaylıyorum, İçe Aktar' }))

    expect(await screen.findByText('1 sertifika eklendi')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalledWith(expect.stringContaining('/supersede/'))
  })

  it('seçilen eski sertifika için talep açar', async () => {
    await open()
    await userEvent.click(screen.getAllByRole('radio')[1])

    await userEvent.click(screen.getByRole('button', { name: 'İçe Aktar' }))
    expect(await screen.findByText('devir-test.jumbo.local (bitiş 13.10.2026) bağlantıları için açılacak'))
      .toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Onaylıyorum, İçe Aktar' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/certificates/9/supersede/8'))
    expect(apiPost).not.toHaveBeenCalledWith('/certificates/9/supersede/7')
    expect(await screen.findByText(
      '1 sertifika eklendi — 2 değişiklik talebi oluşturuldu (SY onayı bekliyor)')).toBeInTheDocument()
  })
})
