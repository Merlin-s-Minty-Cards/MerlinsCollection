import { render, screen } from '@testing-library/react'

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
