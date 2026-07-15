import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, beforeEach } from 'vitest'

const mockUseSession = vi.fn()
const mockSignIn = vi.fn()
vi.mock('next-auth/react', () => ({
  useSession: () => mockUseSession(),
  signIn: (...args: unknown[]) => mockSignIn(...args),
}))

import Navbar from '@/components/layout/Navbar'

beforeEach(() => {
  vi.clearAllMocks()
  // Default to signed-in so link-focused tests see the Inventory CTAs.
  mockUseSession.mockReturnValue({ data: { user: {} }, status: 'authenticated' })
})

describe('Navbar', () => {
  it('renders the primary nav links with correct hrefs', () => {
    render(<Navbar />)
    expect(screen.getByRole('link', { name: 'Shows' })).toHaveAttribute('href', '/shows')
    expect(screen.getByRole('link', { name: 'About' })).toHaveAttribute('href', '/about')
    expect(screen.getByRole('link', { name: 'Dictionary' })).toHaveAttribute('href', '/dictionary')
    expect(screen.getByRole('link', { name: 'Articles' })).toHaveAttribute('href', '/articles')
  })

  it('renders Inventory CTAs pointing to /inventory when signed in', () => {
    render(<Navbar />)
    // One CTA lives in the desktop bar, one inside the mobile dropdown menu.
    const inventoryLinks = screen.getAllByRole('link', { name: 'Inventory' })
    expect(inventoryLinks.length).toBeGreaterThan(0)
    inventoryLinks.forEach((link) => expect(link).toHaveAttribute('href', '/inventory'))
  })

  it('replaces the Inventory CTA with a Sign in control that starts Cognito login when signed out', async () => {
    mockUseSession.mockReturnValue({ data: null, status: 'unauthenticated' })
    render(<Navbar />)

    // No Inventory link is exposed to a signed-out visitor.
    expect(screen.queryByRole('link', { name: 'Inventory' })).toBeNull()

    const signIns = screen.getAllByRole('button', { name: 'Sign in' })
    expect(signIns.length).toBeGreaterThan(0)
    await userEvent.click(signIns[0])
    expect(mockSignIn).toHaveBeenCalledWith('cognito', { callbackUrl: '/inventory' })
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
