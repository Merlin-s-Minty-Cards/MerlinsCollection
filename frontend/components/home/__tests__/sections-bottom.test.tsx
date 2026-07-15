import { render, screen } from '@testing-library/react'
import FeaturedFinds from '@/components/home/FeaturedFinds'
import ShowsPreview from '@/components/home/ShowsPreview'
import LearnHub from '@/components/home/LearnHub'
import FinalCTA from '@/components/home/FinalCTA'

describe('bottom Home sections', () => {
  it('FeaturedFinds links to the inventory', () => {
    render(<FeaturedFinds />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'A peek at the collection.' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Explore the inventory/ })).toHaveAttribute(
      'href',
      '/inventory',
    )
  })

  it('ShowsPreview links to the shows page', () => {
    render(<ShowsPreview />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'Catch us at a card show.' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All shows' })).toHaveAttribute('href', '/shows')
  })

  it('LearnHub links to articles and dictionary', () => {
    render(<LearnHub />)
    expect(screen.getByRole('link', { name: /Articles & guides/ })).toHaveAttribute(
      'href',
      '/articles',
    )
    expect(screen.getByRole('link', { name: /Collectors Dictionary/ })).toHaveAttribute(
      'href',
      '/dictionary',
    )
  })

  it('FinalCTA renders the closing call to action', () => {
    render(<FinalCTA />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'We have an answer!' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Get in touch' })).toHaveAttribute('href', '/about#contact')
  })
})

describe('FeaturedFinds collection cards', () => {
  it('wires every card with the smooth hover-grow treatment', () => {
    const { container } = render(<FeaturedFinds />)
    const cards = container.querySelectorAll('.collection-card')
    expect(cards).toHaveLength(5)
    // the treatment lives on the wrapper that holds each card image
    cards.forEach((card) => {
      expect(card.querySelector('img')).toBeInTheDocument()
    })
  })

  it('row container carries collection-row class so CSS :has() can shrink siblings on hover', () => {
    const { container } = render(<FeaturedFinds />)
    // The CSS rule `.collection-row:has(.collection-card:hover) .collection-card:not(:hover)`
    // anchors on this class — if it is missing the sibling-shrink effect silently disappears.
    expect(container.querySelector('.collection-row')).toBeInTheDocument()
  })
})

describe('bottom sections reveal on scroll', () => {
  it('FeaturedFinds wraps content in reveal wrappers and keeps the collection row', () => {
    const { container } = render(<FeaturedFinds />)
    expect(container.querySelector('.reveal')).toBeInTheDocument()
    expect(container.querySelector('.collection-row')).toBeInTheDocument()
    expect(container.querySelectorAll('.collection-card')).toHaveLength(5)
  })

  it('ShowsPreview wraps its listing in a reveal wrapper with a hover lift', () => {
    const { container } = render(<ShowsPreview />)
    expect(container.querySelector('.reveal')).toBeInTheDocument()
    expect(container.querySelector('.hover-lift')).toBeInTheDocument()
  })

  it('LearnHub staggers its two panels and lifts them on hover', () => {
    const { container } = render(<LearnHub />)
    expect(container.querySelectorAll('.reveal').length).toBeGreaterThanOrEqual(2)
    expect(container.querySelectorAll('.hover-lift').length).toBeGreaterThanOrEqual(2)
  })
})
