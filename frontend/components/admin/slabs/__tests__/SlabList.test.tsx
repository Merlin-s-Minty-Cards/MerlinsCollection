import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import SlabList, { type SlabRow } from '../SlabList'
import { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'

const mockApi = { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), isAuthenticated: true }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})
vi.mock('@/lib/use-card-images', () => ({
  useCardImages: (ids: (string | null)[]) => ({
    imageMap: {},
    // Only a linked card has art; a card-less row must fall through to the
    // placeholder exactly as it does on every other admin list.
    getImageUrl: (id: string | null | undefined) =>
      id ? `https://img.example/${id}.png` : null,
    _ids: ids,
  }),
}))

function slab(over: Partial<SlabRow> = {}): SlabRow {
  return {
    item_id: '01J0',
    card_id: 'en:swsh8-271',
    name: 'Gengar VMAX',
    cert_number: '89787279',
    company: 'PSA',
    grade: '10',
    cost_basis: '300.00',
    status: 'available',
    market_value: '2479.50',
    value_as_of: new Date().toISOString(),
    price_source: 'provider',
    ...over,
  }
}

describe('SlabList', () => {
  it('renders "not priced" for an unpriced slab, never $0.00', () => {
    // A slab silently valued at $0 drags totals and misreports position. After
    // the verified-join rule this row is the ordinary state of a JP slab.
    render(<SlabList rows={[slab({ market_value: null, value_as_of: null, price_source: null })]} />)
    expect(screen.getByText(/not priced/i)).toBeInTheDocument()
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument()
  })

  it('badges a hand-entered value as manual', () => {
    render(<SlabList rows={[slab({ price_source: 'manual' })]} />)
    expect(screen.getByText(/manual/i)).toBeInTheDocument()
  })

  it('does not badge a provider value as manual', () => {
    render(<SlabList rows={[slab({ price_source: 'provider' })]} />)
    expect(screen.queryByText(/manual/i)).not.toBeInTheDocument()
  })

  it('renders the age of a stale value', () => {
    // T7 rotates refreshes, so staleness is a normal state to display rather
    // than an error to hide.
    const threeDaysAgo = new Date(Date.now() - 3 * 86400_000).toISOString()
    render(<SlabList rows={[slab({ value_as_of: threeDaysAgo })]} />)
    expect(screen.getByText(/3 days ago/i)).toBeInTheDocument()
  })

  it('uses the shared table thumbnail size and column width', () => {
    // Hand-picking a size per page is what put a 160px image in a 64px cell on
    // four separate admin pages (CLAUDE.md).
    const { container } = render(<SlabList rows={[slab()]} />)
    expect(TABLE_THUMB_SIZE).toBe('xs')
    // `xs` is w-14; the column it sits in is TABLE_THUMB_COLUMN.
    expect(container.querySelector(`.${TABLE_THUMB_COLUMN}`)).not.toBeNull()
    expect(container.querySelector('img.w-14')).not.toBeNull()
  })

  it('renders the placeholder for a slab with no catalog link', () => {
    const { container } = render(<SlabList rows={[slab({ card_id: null })]} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByLabelText(/no image for/i)).toBeInTheDocument()
  })

  it('shows cert, company, grade, cost and status on the row', () => {
    render(<SlabList rows={[slab()]} />)
    const row = screen.getByRole('row', { name: /gengar vmax/i })
    expect(within(row).getByText('89787279')).toBeInTheDocument()
    expect(within(row).getByText('PSA')).toBeInTheDocument()
    expect(within(row).getByText('10')).toBeInTheDocument()
    expect(within(row).getByText(/300\.00/)).toBeInTheDocument()
    expect(within(row).getByText(/available/i)).toBeInTheDocument()
  })

  it('says so when there are no slabs at all', () => {
    render(<SlabList rows={[]} />)
    expect(screen.getByText(/no slabs/i)).toBeInTheDocument()
  })
})
