import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, beforeEach } from 'vitest'

const mockUseSession = vi.fn()
const mockSignOut = vi.fn()
vi.mock('next-auth/react', () => ({
  useSession: () => mockUseSession(),
  signOut: (...args: unknown[]) => mockSignOut(...args),
}))

import Footer from '@/components/layout/Footer'

beforeEach(() => {
  vi.clearAllMocks()
  mockUseSession.mockReturnValue({ data: { user: {} }, status: 'authenticated' })
})

describe('Footer', () => {
  it('renders the three column headings', () => {
    render(<Footer />)
    expect(screen.getByText('Explore')).toBeInTheDocument()
    expect(screen.getByText('Collect')).toBeInTheDocument()
    expect(screen.getByText('Follow')).toBeInTheDocument()
  })

  it('renders an external Instagram link', () => {
    render(<Footer />)
    const ig = screen.getByRole('link', { name: 'Instagram' })
    expect(ig).toHaveAttribute('href', expect.stringContaining('instagram.com'))
  })

  it('renders the copyright line', () => {
    render(<Footer />)
    expect(screen.getByText(/Merlin's Minty Cards LLC/)).toBeInTheDocument()
  })

  it('renders a low-visibility Sign out control in the Collect column when signed in', async () => {
    render(<Footer />)
    const signOutBtn = screen.getByRole('button', { name: 'Sign out' })
    expect(signOutBtn).toBeInTheDocument()
    await userEvent.click(signOutBtn)
    expect(mockSignOut).toHaveBeenCalledWith({ callbackUrl: '/' })
  })

  it('renders a Sign in link to /inventory instead when signed out', () => {
    mockUseSession.mockReturnValue({ data: null, status: 'unauthenticated' })
    render(<Footer />)
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/inventory')
  })

  it('treats a session whose token refresh failed as signed out', () => {
    mockUseSession.mockReturnValue({
      data: { user: {}, error: 'RefreshAccessTokenError' },
      status: 'authenticated',
    })
    render(<Footer />)
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/inventory')
  })
})
