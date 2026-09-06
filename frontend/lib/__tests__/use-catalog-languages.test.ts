import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCatalogLanguages } from '@/lib/use-catalog-languages'
import { useAdminApi } from '@/lib/admin-api'

/**
 * RFC 0023 T3 — mirrors `useCatalogSets` (lib/use-catalog-sets.ts) exactly:
 * same fetch-once-on-mount shape, same `isAuthenticated`-gated retry (CLAUDE.md
 * documents four hooks that shipped permanently empty from missing exactly
 * this gate), same empty-array-on-failure default so one broken filter never
 * blanks the rest of the admin panel.
 */

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

const LANGUAGE = { code: 'EN', label: 'English', sets: 218 }

describe('useCatalogLanguages', () => {
  beforeEach(() => {
    getMock.mockReset()
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
  })

  it('fetches /catalog/languages on success', async () => {
    getMock.mockResolvedValueOnce([LANGUAGE])

    const { result } = renderHook(() => useCatalogLanguages())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.languages).toEqual([LANGUAGE])
    expect(getMock).toHaveBeenCalledWith('/catalog/languages')
  })

  it('defaults to an empty list on a failed fetch, not a thrown error', async () => {
    getMock.mockRejectedValueOnce(new Error('boom'))

    const { result } = renderHook(() => useCatalogLanguages())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.languages).toEqual([])
  })

  it('defaults to an empty list when the response is not an array', async () => {
    getMock.mockResolvedValueOnce({ error: 'unexpected shape' })

    const { result } = renderHook(() => useCatalogLanguages())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.languages).toEqual([])
  })

  it('retries once the session finishes loading, instead of permanently caching an empty list', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<typeof useAdminApi>)

    const { result, rerender } = renderHook(() => useCatalogLanguages())

    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)
    expect(result.current.languages).toEqual([])

    getMock.mockResolvedValueOnce([LANGUAGE])
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.languages).toEqual([LANGUAGE])
  })
})
