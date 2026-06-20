import { render, screen } from '@testing-library/react'

vi.mock('next/image', () => ({
  default: ({ src, alt, ...rest }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === 'string' ? src : ''} alt={alt} {...rest} />
  ),
}))

import HomePage from '@/app/(public)/page'

describe('Home page', () => {
  it('renders the hero headline', () => {
    render(<HomePage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('handled with care')
  })

  it('renders every major section heading', () => {
    render(<HomePage />)
    ;[
      'It started with one binder.',
      'Three ways to work with us.',
      'A peek at the collection.',
      'Catch us at a card show.',
      'Start with the basics.',
      "Let's find your card.",
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
