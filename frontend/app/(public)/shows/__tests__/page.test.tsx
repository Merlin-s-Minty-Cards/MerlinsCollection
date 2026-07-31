import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/public', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/public')>()),
  getPublicShows: vi.fn(),
}))

import ShowsPage, { revalidate } from '@/app/(public)/shows/page'
import { getPublicShows } from '@/lib/public'

const mockedGetShows = vi.mocked(getPublicShows)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Shows page', () => {
  it('re-fetches on a schedule so new shows appear without a rebuild (ISR)', () => {
    expect(revalidate).toBe(300)
  })

  it('renders the page heading', async () => {
    mockedGetShows.mockResolvedValue({ upcoming: [], past: [] })
    render(await ShowsPage())
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/show/i)
  })

  it('splits into Upcoming and Past sections from the API payload', async () => {
    mockedGetShows.mockResolvedValue({
      upcoming: [
        { name: 'Seattle Trading Card Con', date: '2026-08-14', venue: 'Convention Center', city: 'Seattle, WA' },
      ],
      past: [{ name: 'Lloyd Center Show', date: '2026-07-18', venue: 'Lloyd Center', city: 'Portland, OR' }],
    })

    render(await ShowsPage())

    expect(screen.getByRole('heading', { name: /upcoming shows/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /past shows/i })).toBeInTheDocument()
    expect(screen.getByText('Seattle Trading Card Con')).toBeInTheDocument()
    expect(screen.getByText('Lloyd Center Show')).toBeInTheDocument()
    expect(screen.getByText('Seattle, WA')).toBeInTheDocument()
  })

  it('derives the date badge and label from the show date', async () => {
    mockedGetShows.mockResolvedValue({
      upcoming: [{ name: 'Seattle Trading Card Con', date: '2026-08-14', venue: null, city: null }],
      past: [],
    })

    render(await ShowsPage())

    expect(screen.getByText('AUG')).toBeInTheDocument()
    expect(screen.getByText('Aug 14, 2026')).toBeInTheDocument()
  })

  it('omits venue/city lines when a show is missing those details', async () => {
    mockedGetShows.mockResolvedValue({
      upcoming: [{ name: 'Bare Show', date: '2026-08-14', venue: null, city: null }],
      past: [],
    })

    render(await ShowsPage())

    expect(screen.getByText('Bare Show')).toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })

  it('shows the empty-state copy when both lists are empty', async () => {
    mockedGetShows.mockResolvedValue({ upcoming: [], past: [] })
    render(await ShowsPage())
    expect(screen.getByText(/no shows on the calendar/i)).toBeInTheDocument()
  })

  it('links to the contact section for bookings', async () => {
    mockedGetShows.mockResolvedValue({ upcoming: [], past: [] })
    render(await ShowsPage())
    expect(screen.getByRole('link', { name: /get in touch/i })).toHaveAttribute(
      'href',
      '/about#contact',
    )
  })
})
