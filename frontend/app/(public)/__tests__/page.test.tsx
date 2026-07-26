import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

// FeaturedFinds is an async server component (it server-fetches featured cards);
// the client test renderer can't render it inline inside the sync HomePage, so
// stub it with a sync equivalent that keeps the heading + inventory link this
// composition test asserts on. FeaturedFinds' own behavior has dedicated tests.
vi.mock('@/components/home/FeaturedFinds', () => ({
  default: () => (
    <section>
      <h2>A peek at the collection.</h2>
      <a href="/inventory">Explore the inventory →</a>
    </section>
  ),
}))

import HomePage from '@/app/(public)/page'

describe('Home page', () => {
  it('renders the hero headline', () => {
    render(<HomePage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('and a cat named Merlin')
  })

  it('renders every major section heading', () => {
    render(<HomePage />)
    ;[
      'Three friends, a lot of cards, and a cat.',
      'Three reasons to stop by our table.',
      'A peek at the collection.',
      'Catch us at a card show.',
      'Let us help you',
      'We have an answer!',
    ].forEach((t) =>
      expect(screen.getByRole('heading', { level: 2, name: t })).toBeInTheDocument(),
    )
  })

  it('routes its primary CTAs correctly', () => {
    render(<HomePage />)
    expect(screen.getByRole('link', { name: 'Read our story' })).toHaveAttribute('href', '/about')
    expect(screen.getByRole('link', { name: /Explore the inventory/ })).toHaveAttribute('href', '/inventory')
    expect(screen.getByRole('link', { name: /Articles & guides/ })).toHaveAttribute('href', '/articles')
    expect(screen.getByRole('link', { name: /Collectors Dictionary/ })).toHaveAttribute('href', '/dictionary')
  })
})
