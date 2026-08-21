import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useLocations } from '@/lib/use-locations'
import { useAdminApi } from '@/lib/admin-api'
import { LOCATION_OPTIONS } from '@/lib/constants'

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

describe('useLocations', () => {
  beforeEach(() => {
    getMock.mockReset()
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
  })

  it('resolves options from the API on success', async () => {
    const apiOptions = [{ value: 'foo', label: 'Foo' }]
    getMock.mockResolvedValueOnce(apiOptions)

    const { result } = renderHook(() => useLocations())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual(apiOptions)
    expect(getMock).toHaveBeenCalledWith('/locations')
  })

  it('falls back to LOCATION_OPTIONS when the API call rejects', async () => {
    getMock.mockRejectedValueOnce(new Error('network down'))

    const { result } = renderHook(() => useLocations())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual(LOCATION_OPTIONS)
  })

  // Same bug as useCosigners (see that test file's comment for the full
  // mechanism): a `[]`-deps fetch effect that races NextAuth's client
  // session hydration can permanently strand this dropdown on its
  // hardcoded LOCATION_OPTIONS fallback even though `/admin/locations` has
  // real, admin-managed rows to offer.
  it('retries once the session finishes loading, instead of permanently falling back', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<typeof useAdminApi>)

    const { result, rerender } = renderHook(() => useLocations())

    // Still waiting on auth: no request attempted, and the hook must not
    // falsely report itself "done" with only the hardcoded fallback — it
    // hasn't tried the real list yet.
    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)
    expect(result.current.options).toEqual(LOCATION_OPTIONS)

    getMock.mockResolvedValueOnce([{ value: 'custom_shelf', label: 'Custom Shelf' }])
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([{ value: 'custom_shelf', label: 'Custom Shelf' }])
  })
})
