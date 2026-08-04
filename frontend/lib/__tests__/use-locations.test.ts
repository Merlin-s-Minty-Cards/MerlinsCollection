import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useLocations } from '@/lib/use-locations'
import { LOCATION_OPTIONS } from '@/lib/constants'

const getMock = vi.fn()

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: () => ({ get: getMock }),
}))

describe('useLocations', () => {
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
})
