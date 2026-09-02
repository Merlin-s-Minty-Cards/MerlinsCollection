import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import AdminShowPrepPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()
// A stable object identity is required: the page's fetch callbacks depend on
// `api` in their useEffect/useCallback deps, and a new object every render
// (as a naive factory would produce) causes an infinite fetch loop.
const mockApi = {
  get: getMock,
  post: postMock,
  del: vi.fn(),
  put: putMock,
  patch: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => mockApi,
  }
})

const mispricedItem = {
  item_id: 'item-1',
  name: 'Pikachu VMAX',
  location: 'binder-a',
  cost_basis: '10.00',
  current_market_value: '30.00',
  sticker_price: '25.00',
  sticker_notes: 'verify grade before pricing',
  tcg_url: 'https://www.tcgplayer.com/product/12345',
  delta_pct: '200',
}

describe('AdminShowPrepPage inline sticker editing', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/show-prep/mispriced') {
        return Promise.resolve({ items: [mispricedItem], total_flagged: 1 })
      }
      if (path === '/show-prep/location-summary') {
        return Promise.resolve({ locations: { 'binder-a': 1 }, total: 1 })
      }
      if (path === '/locations') {
        return Promise.resolve([{ value: 'binder-a', label: 'Binder A' }])
      }
      return Promise.resolve({})
    })
  })

  it('saves an edited sticker price via PUT and refetches the mispriced list', async () => {
    render(<AdminShowPrepPage />)

    await act(async () => {
      await Promise.resolve()
    })

    const stickerDisplay = await screen.findByRole('button', { name: /edit sticker price for pikachu vmax/i })
    fireEvent.click(stickerDisplay)

    const input = screen.getByPlaceholderText('0.00')
    fireEvent.change(input, { target: { value: '19.99' } })

    const mispricedCallsBefore = getMock.mock.calls.filter((c) => c[0] === '/show-prep/mispriced').length

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
      await Promise.resolve()
    })

    expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '19.99' })

    const mispricedCallsAfter = getMock.mock.calls.filter((c) => c[0] === '/show-prep/mispriced').length
    expect(mispricedCallsAfter).toBeGreaterThan(mispricedCallsBefore)
  })

  it('does not PUT when the sticker price is reopened but left unchanged', async () => {
    render(<AdminShowPrepPage />)
    await act(async () => {
      await Promise.resolve()
    })

    const stickerDisplay = await screen.findByRole('button', { name: /edit sticker price for pikachu vmax/i })
    fireEvent.click(stickerDisplay)
    const input = screen.getByPlaceholderText('0.00')

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
      await Promise.resolve()
    })

    expect(putMock).not.toHaveBeenCalled()
  })

  it('edits location inline via a select (RFC 0022 T4a)', async () => {
    render(<AdminShowPrepPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Location' }))
    const select = screen.getByRole('combobox', { name: 'Edit Location' })
    await act(async () => {
      fireEvent.change(select, { target: { value: 'binder-a' } })
    })
    // Same value as stored -> dirty-check skips the round trip.
    expect(putMock).not.toHaveBeenCalledWith('/inventory/item-1', expect.objectContaining({ location: expect.anything() }))
  })

  it('edits cost_basis inline as money (RFC 0022 T4a)', async () => {
    render(<AdminShowPrepPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Price Paid' }))
    const input = screen.getByRole('textbox', { name: 'Edit Price Paid' })
    fireEvent.change(input, { target: { value: '12.50' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { cost_basis: '12.5' })
  })

  it('surfaces a failure message and keeps the editor open when the PUT rejects', async () => {
    putMock.mockRejectedValueOnce(new Error('boom'))
    render(<AdminShowPrepPage />)
    await act(async () => {
      await Promise.resolve()
    })

    const stickerDisplay = await screen.findByRole('button', { name: /edit sticker price for pikachu vmax/i })
    fireEvent.click(stickerDisplay)
    const input = screen.getByPlaceholderText('0.00')
    fireEvent.change(input, { target: { value: '19.99' } })

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(await screen.findByText('boom')).toBeInTheDocument()
    // Editor stays open on failure rather than silently reverting.
    expect(screen.getByPlaceholderText('0.00')).toBeInTheDocument()
  })

  it('renders the stored tcg_url in the TCG Price column instead of the generated search fallback', async () => {
    render(<AdminShowPrepPage />)
    await act(async () => {
      await Promise.resolve()
    })
    const link = await screen.findByTitle('https://www.tcgplayer.com/product/12345')
    expect(link).toHaveAttribute('href', 'https://www.tcgplayer.com/product/12345')
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T1 — money fields accept what a human types
// ---------------------------------------------------------------------------

describe('AdminShowPrepPage money input', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/show-prep/mispriced') {
        return Promise.resolve({ items: [mispricedItem], total_flagged: 1 })
      }
      if (path === '/show-prep/location-summary') {
        return Promise.resolve({ locations: { 'binder-a': 1 }, total: 1 })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder-a', label: 'Binder A' }])
      return Promise.resolve({})
    })
  })

  async function renderWithSelection() {
    render(<AdminShowPrepPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByLabelText(/select all/i))
    return screen.getByLabelText('Bulk sticker price')
  }

  it('bulk sticker sends the PARSED number, never the raw typed string', async () => {
    const input = await renderWithSelection()
    fireEvent.change(input, { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '1300' }))
  })

  it('still sends a plain 1300 unchanged (regression gate)', async () => {
    const input = await renderWithSelection()
    fireEvent.change(input, { target: { value: '1300' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '1300' }))
  })

  it('does not apply a bulk sticker price it cannot read', async () => {
    const input = await renderWithSelection()
    fireEvent.change(input, { target: { value: '1,30' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('inline sticker edit commits a comma-grouped amount as its parsed value', async () => {
    render(<AdminShowPrepPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/edit sticker price for/i))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1,300' } })
    await act(async () => { fireEvent.keyDown(input, { key: 'Enter' }) })

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '1300' }))
  })
})
