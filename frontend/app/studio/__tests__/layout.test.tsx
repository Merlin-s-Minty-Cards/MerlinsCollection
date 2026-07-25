import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/auth', () => ({ auth: vi.fn() }))

vi.mock('next/navigation', () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`)
  }),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND')
  }),
}))

import StudioLayout from '@/app/studio/layout'
import { auth } from '@/lib/auth'

const authMock = vi.mocked(auth as unknown as () => Promise<unknown>)

beforeEach(() => {
  authMock.mockReset()
})

describe('Studio route protection', () => {
  it('sends an anonymous visitor to sign in', async () => {
    authMock.mockResolvedValue(null)

    await expect(StudioLayout({ children: null })).rejects.toThrow(/REDIRECT:.*signin/)
  })

  it('hides the Studio from a signed-in customer who is not an admin', async () => {
    // 404 rather than 403: a non-admin has no business knowing the route exists.
    authMock.mockResolvedValue({ isAdmin: false, expires: '2099-01-01' })

    await expect(StudioLayout({ children: null })).rejects.toThrow('NEXT_NOT_FOUND')
  })

  it('lets an admin through', async () => {
    authMock.mockResolvedValue({ isAdmin: true, expires: '2099-01-01' })

    await expect(StudioLayout({ children: 'studio' })).resolves.toBe('studio')
  })
})
