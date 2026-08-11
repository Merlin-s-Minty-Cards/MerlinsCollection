import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import AdminCosignersPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const delMock = vi.fn()

const mockApi = {
  get: getMock, post: postMock, put: vi.fn(), patch: vi.fn(), del: delMock,
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi, AdminApiError: actual.AdminApiError }
})

const cosigner = {
  consignor_id: 'cons-1',
  name: 'Alice',
  email: 'alice@example.com',
  phone: null,
  payout_percent: '60',
  active: true,
  notes: null,
}

const asset = {
  item_id: 'item-1',
  display_name: 'Pikachu',
  cost_basis: '20.00',
  status: 'available',
  location: 'glass',
}

async function selectCosigner() {
  render(<AdminCosignersPage />)
  fireEvent.click(await screen.findByText('Alice'))
  await screen.findByText('Pikachu')
}

describe('AdminCosignersPage', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    delMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/cosigners') return Promise.resolve([cosigner])
      if (path === `/cosigners/${cosigner.consignor_id}/analytics`) {
        return Promise.resolve({
          consignor_id: cosigner.consignor_id,
          total_items: 1,
          items_sold: 0,
          total_value: '20.00',
        })
      }
      if (path === `/cosigners/${cosigner.consignor_id}/assets`) {
        return Promise.resolve({ items: [asset], total: 1 })
      }
      return Promise.resolve(null)
    })
  })

  it('does not unlink immediately — clicking Unlink opens a confirmation dialog first', async () => {
    // Round 6 audit finding 4: unlink used to fire on a single click, unlike
    // every other destructive action in the app (Locations delete, cosigner
    // delete). Confirm the dialog gates the call rather than firing it.
    await selectCosigner()

    fireEvent.click(screen.getByLabelText('Unlink Pikachu'))

    expect(delMock).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: /^unlink$/i })).toBeInTheDocument()
  })

  it('unlinks an item via DELETE /cosigners/{id}/assets/{item_id} after confirming', async () => {
    delMock.mockResolvedValueOnce({ status: 'unlinked', item_id: asset.item_id })
    await selectCosigner()

    fireEvent.click(screen.getByLabelText('Unlink Pikachu'))
    fireEvent.click(await screen.findByRole('button', { name: /^unlink$/i }))

    await waitFor(() =>
      expect(delMock).toHaveBeenCalledWith(
        `/cosigners/${cosigner.consignor_id}/assets/${asset.item_id}`,
      ),
    )
  })

  it('does not call DELETE when the unlink confirmation is cancelled', async () => {
    await selectCosigner()

    fireEvent.click(screen.getByLabelText('Unlink Pikachu'))
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    await act(async () => { await Promise.resolve() })
    expect(delMock).not.toHaveBeenCalled()
  })

  it('refreshes the asset list after a successful unlink', async () => {
    delMock.mockResolvedValueOnce({ status: 'unlinked', item_id: asset.item_id })
    await selectCosigner()
    const callsBefore = getMock.mock.calls.length

    fireEvent.click(screen.getByLabelText('Unlink Pikachu'))
    fireEvent.click(await screen.findByRole('button', { name: /^unlink$/i }))

    await waitFor(() => expect(getMock.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('alerts with the failed item ids returned by the link endpoint', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    postMock.mockResolvedValueOnce({
      linked: 1,
      consignor_id: cosigner.consignor_id,
      failed_item_ids: ['does-not-exist'],
    })
    await selectCosigner()

    fireEvent.click(screen.getByRole('button', { name: /link items/i }))
    fireEvent.change(screen.getByPlaceholderText('item_id_1, item_id_2, ...'), {
      target: { value: 'item-1, does-not-exist' },
    })
    const submitButtons = screen.getAllByRole('button', { name: /link items/i })
    fireEvent.click(submitButtons[submitButtons.length - 1])

    await waitFor(() =>
      expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining('does-not-exist')),
    )
    alertSpy.mockRestore()
  })

  it('does not alert when all linked items succeed', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    postMock.mockResolvedValueOnce({
      linked: 1,
      consignor_id: cosigner.consignor_id,
      failed_item_ids: [],
    })
    await selectCosigner()

    fireEvent.click(screen.getByRole('button', { name: /link items/i }))
    fireEvent.change(screen.getByPlaceholderText('item_id_1, item_id_2, ...'), {
      target: { value: 'item-1' },
    })
    const submitButtons = screen.getAllByRole('button', { name: /link items/i })
    fireEvent.click(submitButtons[submitButtons.length - 1])

    await waitFor(() => expect(postMock).toHaveBeenCalled())
    expect(alertSpy).not.toHaveBeenCalled()
    alertSpy.mockRestore()
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T1 — money fields accept what a human types
// ---------------------------------------------------------------------------

describe('AdminCosignersPage link minimum price', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    delMock.mockReset()
    postMock.mockResolvedValue({ linked: 1, failed_item_ids: [] })
    getMock.mockImplementation((path: string) => {
      if (path === '/cosigners') return Promise.resolve([cosigner])
      if (path === `/cosigners/${cosigner.consignor_id}/analytics`) {
        return Promise.resolve({ consignor_id: cosigner.consignor_id, total_items: 1, items_sold: 0, total_value: '20.00' })
      }
      if (path === `/cosigners/${cosigner.consignor_id}/assets`) {
        return Promise.resolve({ items: [asset], total: 1 })
      }
      return Promise.resolve({})
    })
  })

  // "Link Items" names both the button that opens the modal and the one that
  // submits it, so they are told apart by position: the modal's is the later.
  const submitLink = () => {
    const buttons = screen.getAllByRole('button', { name: /link items/i })
    fireEvent.click(buttons[buttons.length - 1])
  }

  async function openLinkForm() {
    await selectCosigner()
    fireEvent.click(screen.getByRole('button', { name: /link items/i }))
    fireEvent.change(screen.getByPlaceholderText(/item_id_1/i), { target: { value: 'item-1' } })
    return screen.getByLabelText(/min price/i)
  }

  it('sends 1300 when the admin types 1,300', async () => {
    const minPrice = await openLinkForm()
    fireEvent.change(minPrice, { target: { value: '1,300' } })
    submitLink()

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      `/cosigners/${cosigner.consignor_id}/link`,
      expect.objectContaining({ minimum_price: '1300' }),
    ))
  })

  it('still sends 1300 for a plain 1300 (regression gate)', async () => {
    const minPrice = await openLinkForm()
    fireEvent.change(minPrice, { target: { value: '1300' } })
    submitLink()

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      `/cosigners/${cosigner.consignor_id}/link`,
      expect.objectContaining({ minimum_price: '1300' }),
    ))
  })

  it('does not link with a minimum price it cannot read', async () => {
    const minPrice = await openLinkForm()
    fireEvent.change(minPrice, { target: { value: '1,30' } })
    submitLink()

    await act(async () => { await Promise.resolve() })
    expect(postMock).not.toHaveBeenCalledWith(
      `/cosigners/${cosigner.consignor_id}/link`,
      expect.anything(),
    )
  })
})
