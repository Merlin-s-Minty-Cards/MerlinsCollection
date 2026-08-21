import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DealSearchPanel, { sourceForMode } from '../DealSearchPanel'

/**
 * RFC 0011 T14 — one search panel for Buy, Sell and Trade. The source toggle
 * exists only where it can be set two ways, and the inventory picker (which
 * has no image at all today) renders the same row as the catalog one.
 */

const getMock = vi.fn()

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => ({
      get: getMock,
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
      isAuthenticated: true,
      isLoading: false,
    }),
  }
})

vi.mock('@/lib/use-catalog-sets', () => ({
  useCatalogSets: () => ({ sets: [], loading: false }),
  toComboboxSets: () => [],
}))

vi.mock('@/lib/use-card-images', () => ({
  useCardImages: () => ({
    imageMap: {},
    getImageUrl: (id?: string | null) => (id ? `https://img/${id}.png` : null),
  }),
}))

const noop = {
  onSourceChange: vi.fn(),
  onPickCatalog: vi.fn(),
  onPickInventory: vi.fn(),
  onManualEntry: vi.fn(),
  manualEntryAllowed: true,
}

function mockInventory(items: unknown[]) {
  getMock.mockResolvedValue({ items, total: items.length })
}

beforeEach(() => {
  getMock.mockReset()
  mockInventory([])
})

describe('DealSearchPanel', () => {
  it('hides the source toggle outside trade mode', () => {
    render(<DealSearchPanel mode="buy" source="catalog" {...noop} />)
    expect(screen.queryByRole('radio', { name: /inventory/i })).not.toBeInTheDocument()
  })

  it('shows the source toggle in trade mode', () => {
    render(<DealSearchPanel mode="trade" source="catalog" {...noop} />)
    expect(screen.getByRole('radio', { name: /inventory/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /catalog/i })).toBeInTheDocument()
  })

  it('locks buy to the catalog and sell to inventory', () => {
    expect(sourceForMode('buy')).toBe('catalog')
    expect(sourceForMode('sell')).toBe('inventory')
    expect(sourceForMode('trade')).toBe('both')
  })

  it('reports a source change from the toggle', async () => {
    const user = userEvent.setup({ delay: null })
    const onSourceChange = vi.fn()
    render(<DealSearchPanel mode="trade" source="catalog" {...noop} onSourceChange={onSourceChange} />)
    await user.click(screen.getByRole('radio', { name: /inventory/i }))
    expect(onSourceChange).toHaveBeenCalledWith('inventory')
  })

  it('searches available inventory when the source is inventory', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} />)
    await user.type(screen.getByLabelText(/card name/i), 'Charizard')
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ status: 'available' }),
      ),
    )
  })

  it('shows an image on every inventory result', async () => {
    const user = userEvent.setup({ delay: null })
    mockInventory([
      { item_id: 'a', display_name: 'Charizard', card_id: 'en:base1-4', current_market_value: '120.00' },
    ])
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} />)
    await user.type(screen.getByLabelText(/card name/i), 'Char')
    expect(await screen.findByRole('img', { name: /charizard/i })).toBeInTheDocument()
  })

  it('hands the picked inventory item back', async () => {
    const user = userEvent.setup({ delay: null })
    mockInventory([
      { item_id: 'a', display_name: 'Charizard', card_id: 'en:base1-4', current_market_value: '120.00' },
    ])
    const onPickInventory = vi.fn()
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} onPickInventory={onPickInventory} />)
    await user.type(screen.getByLabelText(/card name/i), 'Char')
    await user.click(await screen.findByRole('button', { name: /charizard/i }))
    expect(onPickInventory).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'a' }))
  })

  it('does not request the whole inventory before anything is typed', async () => {
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} />)
    await new Promise((r) => setTimeout(r, 400))
    expect(getMock).not.toHaveBeenCalled()
  })

  it('offers manual entry before any search has run', () => {
    const onManualEntry = vi.fn()
    render(<DealSearchPanel mode="buy" source="catalog" {...noop} onManualEntry={onManualEntry} />)
    expect(screen.getByRole('button', { name: /manual/i })).toBeInTheDocument()
  })

  it('calls onManualEntry rather than opening a form here', async () => {
    const user = userEvent.setup({ delay: null })
    const onManualEntry = vi.fn()
    render(<DealSearchPanel mode="buy" source="catalog" {...noop} onManualEntry={onManualEntry} />)
    await user.click(screen.getByRole('button', { name: /manual/i }))
    expect(onManualEntry).toHaveBeenCalled()
  })

  it('hides manual entry when manualEntryAllowed is false (Sell mode, Important 5)', () => {
    render(<DealSearchPanel mode="sell" source="inventory" {...noop} manualEntryAllowed={false} />)
    expect(screen.queryByRole('button', { name: /manual/i })).not.toBeInTheDocument()
  })
})
