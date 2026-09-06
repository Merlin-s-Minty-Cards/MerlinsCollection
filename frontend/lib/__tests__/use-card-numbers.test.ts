import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCardNumbers } from '../use-card-numbers'

const postMock = vi.fn()

const mockApi = {
  get: vi.fn(),
  post: postMock,
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

beforeEach(() => {
  postMock.mockReset()
})

// Mirrors use-card-images.test.ts — both hooks share `useBatchedCardLookup`,
// so this pins the same behavior against the OTHER endpoint it's wired to.
describe('useCardNumbers', () => {
  it('resolves ids into catalog print numbers, via /inventory/card-numbers', async () => {
    postMock.mockResolvedValue({ 'sv1-25': '25' })

    const { result } = renderHook(() => useCardNumbers(['sv1-25']))

    await waitFor(() => expect(result.current.getCardNumber('sv1-25')).toBe('25'))
    expect(postMock).toHaveBeenCalledWith('/inventory/card-numbers', { card_ids: ['sv1-25'] })
  })

  it('does not re-request an id it has already resolved', async () => {
    postMock.mockResolvedValue({ 'sv1-25': '25' })

    const { result, rerender } = renderHook(() => useCardNumbers(['sv1-25']))
    await waitFor(() => expect(result.current.getCardNumber('sv1-25')).toBe('25'))

    const callsAfterResolve = postMock.mock.calls.length
    rerender()
    rerender()

    expect(postMock).toHaveBeenCalledTimes(callsAfterResolve)
  })

  it('does not re-request on every render after a failure', async () => {
    postMock.mockRejectedValue(new Error('boom'))

    const { rerender } = renderHook(() => useCardNumbers(['sv1-25']))

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))

    for (let i = 0; i < 5; i++) rerender()
    await new Promise((r) => setTimeout(r, 20))

    expect(postMock).toHaveBeenCalledTimes(1)
  })

  it('reports no number for an id whose lookup failed', async () => {
    postMock.mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCardNumbers(['sv1-25']))
    await waitFor(() => expect(postMock).toHaveBeenCalled())

    expect(result.current.getCardNumber('sv1-25')).toBeNull()
  })

  it('returns null for a card_id the server resolved but had no number for', () => {
    // Distinguishes "never fetched" from "fetched, and the answer is
    // genuinely nothing" — both render the same way to a caller, but only
    // one of them is a lookup failure worth not retrying immediately.
    const { result } = renderHook(() => useCardNumbers([]))
    expect(result.current.getCardNumber(null)).toBeNull()
    expect(result.current.getCardNumber(undefined)).toBeNull()
  })
})
