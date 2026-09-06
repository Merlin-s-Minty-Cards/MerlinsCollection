import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useAdminDocs } from '@/lib/use-admin-docs'
import { useAdminApi } from '@/lib/admin-api'

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

describe('useAdminDocs', () => {
  beforeEach(() => {
    getMock.mockReset()
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<
      typeof useAdminApi
    >)
  })

  it('resolves categories and articles from the API on success', async () => {
    const payload = {
      categories: [{ id: 'money', label: 'Money & Calculations' }],
      articles: [
        {
          id: 'acquisition-ratio',
          category: 'money',
          title: 'The acquisition-ratio percentage',
          summary: 'How it is calculated.',
          body: 'Full body text.',
          keywords: ['ratio'],
          related_routes: ['/admin/trade'],
        },
      ],
    }
    getMock.mockResolvedValueOnce(payload)

    const { result } = renderHook(() => useAdminDocs())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.categories).toEqual(payload.categories)
    expect(result.current.articles).toEqual(payload.articles)
    expect(result.current.error).toBe(false)
    expect(getMock).toHaveBeenCalledWith('/docs')
  })

  it('reports an error and empty lists when the API call rejects', async () => {
    getMock.mockRejectedValueOnce(new Error('network down'))

    const { result } = renderHook(() => useAdminDocs())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBe(true)
    expect(result.current.categories).toEqual([])
    expect(result.current.articles).toEqual([])
  })

  // Same session-race shape use-locations.ts/use-cosigners.ts already guard
  // against: a `[]`-deps fetch effect can fire during NextAuth's client
  // session hydration window and never get a second chance to retry.
  it('retries once the session finishes loading, instead of permanently failing', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<
      typeof useAdminApi
    >)

    const { result, rerender } = renderHook(() => useAdminDocs())

    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)

    const payload = { categories: [], articles: [] }
    getMock.mockResolvedValueOnce(payload)
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<
      typeof useAdminApi
    >)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(getMock).toHaveBeenCalledWith('/docs')
    expect(result.current.error).toBe(false)
  })
})
