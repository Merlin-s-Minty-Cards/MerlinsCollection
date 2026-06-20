import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// next/image needs no Next runtime in tests — render a plain img
vi.mock('next/image', () => ({
  default: ({ src, alt, ...rest }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={typeof src === 'string' ? src : ''} alt={alt} {...rest} />
  ),
}))

import Navbar from '@/components/layout/Navbar'

describe('Navbar', () => {
  it('renders the primary nav links with correct hrefs', () => {
    render(<Navbar />)
    expect(screen.getByRole('link', { name: 'Shows' })).toHaveAttribute('href', '/shows')
    expect(screen.getByRole('link', { name: 'About' })).toHaveAttribute('href', '/about')
    expect(screen.getByRole('link', { name: 'Dictionary' })).toHaveAttribute('href', '/dictionary')
    expect(screen.getByRole('link', { name: 'Articles' })).toHaveAttribute('href', '/articles')
  })

  it('renders the Inventory CTA pointing to /inventory', () => {
    render(<Navbar />)
    expect(screen.getByRole('link', { name: 'Inventory' })).toHaveAttribute('href', '/inventory')
  })

  it('toggles the mobile menu open and closed', async () => {
    const user = userEvent.setup()
    render(<Navbar />)
    const btn = screen.getByRole('button', { name: 'Menu' })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    await user.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
  })
})
