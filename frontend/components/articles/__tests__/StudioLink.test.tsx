import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSession } from 'next-auth/react'
import StudioLink from '@/components/articles/StudioLink'

vi.mock('next-auth/react', () => ({ useSession: vi.fn() }))

const useSessionMock = vi.mocked(useSession)

const mockSession = (data: unknown, status = 'authenticated') =>
  useSessionMock.mockReturnValue({ data, status } as never)

beforeEach(() => {
  useSessionMock.mockReset()
})

describe('StudioLink', () => {
  it('offers an admin the way in to the Studio', () => {
    mockSession({ isAdmin: true, expires: '2099-01-01' })

    render(<StudioLink />)

    expect(screen.getByRole('link', { name: /studio/i })).toHaveAttribute('href', '/studio')
  })

  it('renders nothing for a signed-in customer who is not an admin', () => {
    mockSession({ isAdmin: false, expires: '2099-01-01' })

    const { container } = render(<StudioLink />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing for an anonymous visitor', () => {
    mockSession(null, 'unauthenticated')

    const { container } = render(<StudioLink />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing while the session is still loading', () => {
    // /articles is ISR-cached and shared across visitors. Rendering *nothing*
    // until the session resolves is what keeps admin markup out of the cached
    // HTML — hiding it with CSS would bake it into every visitor's page.
    mockSession(undefined, 'loading')

    const { container } = render(<StudioLink />)

    expect(container).toBeEmptyDOMElement()
  })
})
