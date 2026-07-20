import { describe, it, expect, vi, beforeEach } from 'vitest'

// Replace the auth module wholesale — importing the real one pulls in NextAuth's
// Node-only server internals, which don't resolve under vitest.
vi.mock('@/lib/auth', () => ({ auth: vi.fn() }))
vi.mock('next/navigation', () => ({ redirect: vi.fn() }))
// Navbar (imported by the layout) reads the session.
vi.mock('next-auth/react', () => ({ useSession: vi.fn(), signIn: vi.fn() }))

import { auth } from '@/lib/auth'
import { redirect } from 'next/navigation'
import AuthLayout from '@/app/(auth)/layout'

const mockedAuth = vi.mocked(auth)
const mockedRedirect = vi.mocked(redirect)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('auth layout gate', () => {
  it('redirects an unauthenticated visitor to sign in', async () => {
    mockedAuth.mockResolvedValue(null)
    await AuthLayout({ children: null })
    expect(mockedRedirect).toHaveBeenCalledWith(expect.stringContaining('/api/auth/signin'))
  })

  it('lets an authenticated visitor through without redirecting', async () => {
    mockedAuth.mockResolvedValue({ user: {}, expires: '2026-01-01' } as never)
    await AuthLayout({ children: 'page' })
    expect(mockedRedirect).not.toHaveBeenCalled()
  })

  it('redirects when the session token refresh has failed', async () => {
    // Session cookie exists, but the embedded Cognito token could not be
    // refreshed — the visitor is effectively signed out and must not load the
    // protected page.
    mockedAuth.mockResolvedValue({
      user: {},
      expires: '2026-01-01',
      error: 'RefreshAccessTokenError',
    } as never)
    await AuthLayout({ children: 'page' })
    expect(mockedRedirect).toHaveBeenCalledWith(expect.stringContaining('/api/auth/signin'))
  })
})
