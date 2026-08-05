import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import CardDetailModal from '../CardDetailModal'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => ({
      get: getMock,
      post: postMock,
      put: putMock,
      patch: vi.fn(),
      del: vi.fn(),
      isAuthenticated: true,
      isLoading: false,
    }),
  }
})

const item = {
  item_id: 'item-1',
  card_id: 'sv1-25',
  kind: 'raw',
  display_name: 'Pikachu',
  condition: 'NM',
  location: 'glass',
}

describe('CardDetailModal image resolution', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    // `get` backs PriceChart's price-history fetch (unrelated to this suite).
    // PriceChart types its state as `PriceChartData | null`; resolving with
    // `null` is the real "no data yet" shape it already renders gracefully.
    // (Originally `[]` here, which crashed PriceChart's useMemo — `[].points`
    // is undefined — and unmounted the whole tree before assertions ran; see
    // task-1-report.md GREEN section for the trace.)
    getMock.mockResolvedValue(null)
  })

  it('resolves and renders the card image itself, with no imageUrl prop and no page-level toggle', async () => {
    postMock.mockResolvedValueOnce({ 'sv1-25': 'https://images.example.com/sv1-25.png' })

    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/inventory/card-images', { card_ids: ['sv1-25'] }))

    const img = await screen.findByAltText('Pikachu')
    expect(img).toHaveAttribute('src', 'https://images.example.com/sv1-25.png')
  })

  it('shows the no-image fallback when the card has no resolvable image', async () => {
    postMock.mockResolvedValueOnce({ 'sv1-25': null })

    render(<CardDetailModal item={item} onClose={vi.fn()} />)

    await waitFor(() => expect(postMock).toHaveBeenCalled())
    expect(screen.getByLabelText('No image')).toBeInTheDocument()
  })
})
