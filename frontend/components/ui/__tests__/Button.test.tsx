import { render, screen } from '@testing-library/react'
import Button from '@/components/ui/Button'

describe('Button', () => {
  it('still renders a primary link with its href, label, and variant', () => {
    render(<Button href="/about">Read our story</Button>)
    const link = screen.getByRole('link', { name: 'Read our story' })
    expect(link).toHaveAttribute('href', '/about')
    expect(link).toHaveAttribute('data-variant', 'primary')
  })

  it('gives the primary variant a hover lift', () => {
    render(<Button href="/x">Go</Button>)
    expect(screen.getByRole('link', { name: 'Go' }).className).toMatch(/hover:-translate-y/)
  })

  it('gives the ghost variant a hover fill', () => {
    render(
      <Button href="/x" variant="ghost">
        Go
      </Button>,
    )
    expect(screen.getByRole('link', { name: 'Go' }).className).toMatch(/hover:bg-forest/)
  })

  it('renders a button element when no href is given', () => {
    render(<Button>Submit</Button>)
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
  })

  it('exposes the ghost variant via data-variant', () => {
    render(
      <Button href="/x" variant="ghost">
        Ghost
      </Button>,
    )
    expect(screen.getByRole('link', { name: 'Ghost' })).toHaveAttribute('data-variant', 'ghost')
  })
})
