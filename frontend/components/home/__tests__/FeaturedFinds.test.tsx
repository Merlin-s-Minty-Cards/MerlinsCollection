import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Keep the real isSafeImageUrl (FeaturedFinds filters through it); mock only the fetch.
vi.mock('@/lib/public', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/public')>()),
  getFeaturedCards: vi.fn(),
}))

import FeaturedFinds from '@/components/home/FeaturedFinds'
import { getFeaturedCards } from '@/lib/public'

const mockedGetFeaturedCards = vi.mocked(getFeaturedCards)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FeaturedFinds', () => {
  it('renders API cards when the endpoint returns some', async () => {
    mockedGetFeaturedCards.mockResolvedValue({
      cards: [
        { name: 'Lugia', image_url: 'https://images.pokemontcg.io/neo3/9.png' },
        { name: 'Charizard', image_url: 'https://images.pokemontcg.io/base1/4.png' },
      ],
    })

    render(await FeaturedFinds())

    expect(screen.getByAltText('Lugia')).toHaveAttribute(
      'src',
      'https://images.pokemontcg.io/neo3/9.png',
    )
    expect(screen.getByAltText('Charizard')).toBeInTheDocument()
    // 1–4 real cards -> render exactly those, no static padding.
    expect(screen.getAllByRole('img')).toHaveLength(2)
  })

  it('renders fewer than five tiles without static padding when 1–4 cards return', async () => {
    mockedGetFeaturedCards.mockResolvedValue({
      cards: [{ name: 'Lugia', image_url: 'https://images.pokemontcg.io/neo3/9.png' }],
    })

    render(await FeaturedFinds())

    const imgs = screen.getAllByRole('img')
    expect(imgs).toHaveLength(1)
    expect(imgs[0]).toHaveAttribute('src', 'https://images.pokemontcg.io/neo3/9.png')
  })

  it('falls back to the static images when the endpoint returns zero cards', async () => {
    mockedGetFeaturedCards.mockResolvedValue({ cards: [] })

    render(await FeaturedFinds())

    const imgs = screen.getAllByRole('img')
    expect(imgs).toHaveLength(5)
    imgs.forEach((img) => expect(img.getAttribute('src')).toContain('/images/cards/'))
  })

  it('falls back to the static images when the fetch throws', async () => {
    mockedGetFeaturedCards.mockRejectedValue(new Error('endpoint down'))

    render(await FeaturedFinds())

    const imgs = screen.getAllByRole('img')
    expect(imgs).toHaveLength(5)
    imgs.forEach((img) => expect(img.getAttribute('src')).toContain('/images/cards/'))
  })

  it('drops cards with an unsafe image URL rather than 500-ing the page', async () => {
    // A malformed / non-allowlisted URL would throw inside next/image at SSR.
    // The component must exclude it; if nothing safe remains it shows the static set.
    mockedGetFeaturedCards.mockResolvedValue({
      cards: [
        { name: 'Evil', image_url: 'https://evil.example.com/x.png' },
        { name: 'Broken', image_url: 'not a url' },
      ],
    })

    render(await FeaturedFinds())

    expect(screen.queryByAltText('Evil')).not.toBeInTheDocument()
    const imgs = screen.getAllByRole('img')
    expect(imgs).toHaveLength(5)
    imgs.forEach((img) => expect(img.getAttribute('src')).toContain('/images/cards/'))
  })

  it('keeps only the safe cards when the payload mixes safe and unsafe URLs', async () => {
    mockedGetFeaturedCards.mockResolvedValue({
      cards: [
        { name: 'Lugia', image_url: 'https://images.pokemontcg.io/neo3/9.png' },
        { name: 'Evil', image_url: 'https://evil.example.com/x.png' },
      ],
    })

    render(await FeaturedFinds())

    expect(screen.getByAltText('Lugia')).toBeInTheDocument()
    expect(screen.queryByAltText('Evil')).not.toBeInTheDocument()
    expect(screen.getAllByRole('img')).toHaveLength(1)
  })

  it('keeps the section heading and inventory link', async () => {
    mockedGetFeaturedCards.mockResolvedValue({ cards: [] })

    render(await FeaturedFinds())

    expect(
      screen.getByRole('heading', { level: 2, name: 'A peek at the collection.' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Explore the inventory/ })).toHaveAttribute(
      'href',
      '/inventory',
    )
  })
})
