/**
 * RFC 0010 T8 — the price chart's x-axis labels were a day early.
 *
 * Same construct as Show Analytics: `new Date("2026-08-10")` is UTC midnight,
 * formatted in the browser's zone. THE TZ PIN IS THE TEST — at UTC this passes
 * against the unfixed code.
 */
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import PriceChart from '../PriceChart'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

const getMock = vi.fn()

const mockApi = {
  get: getMock,
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

// Chart.js paints to a canvas jsdom cannot read, so the labels are surfaced as
// text instead. The assertion is on what the component COMPUTED, which is where
// the date bug lives.
vi.mock('react-chartjs-2', () => ({
  Line: ({ data }: { data: { labels: string[] } }) => (
    <div data-testid="chart-labels">{data.labels.join('|')}</div>
  ),
}))

let restoreTz: () => void
beforeAll(() => { restoreTz = pinTimeZone(PACIFIC) })
afterAll(() => restoreTz())

beforeEach(() => {
  getMock.mockReset()
  getMock.mockResolvedValue({
    item_id: 'item-1',
    timeframe: '1yr',
    buy_marker: null,
    points: [
      { date: '2026-08-10', market_value: '12.00' },
      { date: '2026-08-11', market_value: '13.00' },
    ],
  })
})

describe('PriceChart axis labels (RFC 0010 T8)', () => {
  it('labels a 2026-08-10 point as Aug 10, not Aug 9', async () => {
    render(<PriceChart itemId="item-1" />)
    await act(async () => { await Promise.resolve() })

    const labels = await screen.findByTestId('chart-labels')
    expect(labels.textContent).toBe('Aug 10|Aug 11')
  })
})
