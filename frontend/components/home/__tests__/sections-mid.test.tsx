import { render, screen } from '@testing-library/react'

vi.mock('next/image', () => ({
  default: ({ src, alt, ...rest }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === 'string' ? src : ''} alt={alt} {...rest} />
  ),
}))

import TrustStrip from '@/components/home/TrustStrip'
import StoryTeaser from '@/components/home/StoryTeaser'
import BuySellTrade from '@/components/home/BuySellTrade'

describe('mid Home sections', () => {
  it('TrustStrip renders all four trust items', () => {
    render(<TrustStrip />)
    ;['Raw & graded', 'Fair prices', 'We collect too', 'At the shows'].forEach((t) =>
      expect(screen.getByText(t)).toBeInTheDocument(),
    )
  })

  it('StoryTeaser renders the heading and link to About', () => {
    render(<StoryTeaser />)
    expect(
      screen.getByRole('heading', { level: 2, name: 'Three friends, a lot of cards, and a cat.' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Find out more about Merlin' })).toHaveAttribute('href', '/about')
  })

  it('BuySellTrade renders the three offer cards', () => {
    render(<BuySellTrade />)
    expect(screen.getByText('Find your next card')).toBeInTheDocument()
    expect(screen.getByText('Cash in your collection')).toBeInTheDocument()
    expect(screen.getByText('Tired of your old cards?')).toBeInTheDocument()
  })

  it('TrustStrip staggers its four items into view', () => {
    const { container } = render(<TrustStrip />)
    expect(container.querySelectorAll('.reveal').length).toBeGreaterThanOrEqual(4)
  })
})
