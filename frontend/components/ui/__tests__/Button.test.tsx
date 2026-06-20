import { render, screen } from '@testing-library/react'
import Button from '@/components/ui/Button'

describe('Button', () => {
  it('renders a link with the given href', () => {
    render(<Button href="/about">Read our story</Button>)
    expect(screen.getByRole('link', { name: 'Read our story' })).toHaveAttribute('href', '/about')
  })

  it('renders a button element when no href is given', () => {
    render(<Button>Submit</Button>)
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
  })

  it('exposes the variant via data-variant', () => {
    render(<Button href="/x" variant="ghost">Ghost</Button>)
    expect(screen.getByRole('link', { name: 'Ghost' })).toHaveAttribute('data-variant', 'ghost')
  })
})
