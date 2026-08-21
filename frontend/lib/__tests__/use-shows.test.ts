import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useShows } from '@/lib/use-shows'
import { useAdminApi } from '@/lib/admin-api'

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

describe('useShows', () => {
  beforeEach(() => {
    getMock.mockReset()
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
  })

  it('fetches /shows (including archived) and maps show_id/name to value/label', async () => {
    getMock.mockResolvedValueOnce([
      { show_id: 's1', name: 'Winter Show', date: '2026-01-01' },
    ])

    const { result } = renderHook(() => useShows())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([{ value: 's1', label: 'Winter Show' }])
    expect(getMock).toHaveBeenCalledWith('/shows', { include_archived: true })
  })

  // Same class of bug fixed on useCosigners/useLocations: a `[]`-deps fetch
  // effect that races NextAuth's client session hydration can permanently
  // strand this dropdown empty. See use-cosigners.test.ts for the full
  // mechanism.
  it('retries once the session finishes loading, instead of permanently caching an empty list', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<typeof useAdminApi>)

    const { result, rerender } = renderHook(() => useShows())

    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)
    expect(result.current.options).toEqual([])

    getMock.mockResolvedValueOnce([{ show_id: 's1', name: 'Winter Show', date: '2026-01-01' }])
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([{ value: 's1', label: 'Winter Show' }])
  })
})
