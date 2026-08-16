import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCatalogSets } from '@/lib/use-catalog-sets'
import { useAdminApi } from '@/lib/admin-api'

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

const SET = { set_id: 'sv1', set_name: 'Scarlet & Violet', language: 'EN', card_count: 258, owned_count: 12 }

describe('useCatalogSets', () => {
  beforeEach(() => {
    getMock.mockReset()
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
  })

  it('fetches /catalog/sets on success', async () => {
    getMock.mockResolvedValueOnce([SET])

    const { result } = renderHook(() => useCatalogSets())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.sets).toEqual([SET])
    expect(getMock).toHaveBeenCalledWith('/catalog/sets')
  })

  // Same class of bug fixed on useCosigners/useLocations/useShows: a
  // `[]`-deps fetch effect that races NextAuth's client session hydration
  // can permanently strand this dropdown empty. See use-cosigners.test.ts
  // for the full mechanism.
  it('retries once the session finishes loading, instead of permanently caching an empty list', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<typeof useAdminApi>)

    const { result, rerender } = renderHook(() => useCatalogSets())

    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)
    expect(result.current.sets).toEqual([])

    getMock.mockResolvedValueOnce([SET])
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.sets).toEqual([SET])
  })
})
