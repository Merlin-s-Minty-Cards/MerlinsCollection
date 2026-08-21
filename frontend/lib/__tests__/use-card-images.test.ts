import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCardImages } from '../use-card-images'

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

describe('useCardImages', () => {
  it('resolves ids into image urls', async () => {
    postMock.mockResolvedValue({ 'c-1': 'https://img/1.png' })

    const { result } = renderHook(() => useCardImages(['c-1']))

    await waitFor(() => expect(result.current.getImageUrl('c-1')).toBe('https://img/1.png'))
  })

  it('does not re-request an id it has already resolved', async () => {
    postMock.mockResolvedValue({ 'c-1': 'https://img/1.png' })

    const { result, rerender } = renderHook(() => useCardImages(['c-1']))
    await waitFor(() => expect(result.current.getImageUrl('c-1')).toBe('https://img/1.png'))

    const callsAfterResolve = postMock.mock.calls.length
    rerender()
    rerender()

    expect(postMock).toHaveBeenCalledTimes(callsAfterResolve)
  })

  it('does not re-request on every render after a failure', async () => {
    // Callers pass a freshly-mapped array, so `resolve` is a new identity each
    // render and the effect re-runs each render. If a failure puts the ids
    // straight back in the queue, a page that re-renders per keystroke (Trade
    // types into a search box) fires one POST per keystroke at an endpoint
    // that is already failing. Card art is decoration — it must not stampede.
    postMock.mockRejectedValue(new Error('boom'))

    const { rerender } = renderHook(() => useCardImages(['c-1']))

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))

    for (let i = 0; i < 5; i++) rerender()
    await new Promise((r) => setTimeout(r, 20))

    expect(postMock).toHaveBeenCalledTimes(1)
  })

  it('reports no image for an id whose lookup failed', async () => {
    postMock.mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCardImages(['c-1']))
    await waitFor(() => expect(postMock).toHaveBeenCalled())

    expect(result.current.getImageUrl('c-1')).toBeNull()
  })

  it('still fetches genuinely new ids after an earlier failure', async () => {
    // Suppressing the retry must not wedge the hook — a card that appears
    // later has never been attempted and deserves its own lookup.
    postMock.mockRejectedValueOnce(new Error('boom'))

    const { rerender } = renderHook(
      ({ ids }) => useCardImages(ids),
      { initialProps: { ids: ['c-1'] } },
    )
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))

    postMock.mockResolvedValue({ 'c-2': 'https://img/2.png' })
    rerender({ ids: ['c-1', 'c-2'] })

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2))
    expect(postMock.mock.calls[1][1].card_ids).toEqual(['c-2'])
  })
})
