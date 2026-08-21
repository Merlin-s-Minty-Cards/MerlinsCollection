import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCosigners } from '@/lib/use-cosigners'
import { useAdminApi } from '@/lib/admin-api'

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: vi.fn(),
}))

const mockedUseAdminApi = vi.mocked(useAdminApi)
const getMock = vi.fn()

describe('useCosigners', () => {
  beforeEach(() => {
    getMock.mockReset()
    // The common case for every pre-existing test below: session already
    // resolved by the time this hook mounts.
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
  })

  it('fetches /cosigners and maps consignor_id/name to value/label', async () => {
    getMock.mockResolvedValueOnce([
      { consignor_id: 'c1', name: 'Alex' },
      { consignor_id: 'c2', name: 'Bailey' },
    ])

    const { result } = renderHook(() => useCosigners())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([
      { value: 'c1', label: 'Alex' },
      { value: 'c2', label: 'Bailey' },
    ])
    expect(getMock).toHaveBeenCalledWith('/cosigners')
  })

  it('falls back to an empty list on a fetch failure, never throws', async () => {
    getMock.mockRejectedValueOnce(new Error('network'))

    const { result } = renderHook(() => useCosigners())

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([])
  })

  // The bug this pins: NextAuth's client SessionProvider is mounted with no
  // initial `session` prop (see components/providers/SessionProvider.tsx), so
  // on every fresh page load `useSession()` genuinely starts at
  // `status: 'loading'` and only resolves asynchronously — even on a route
  // the SERVER already gated behind a valid admin session
  // (app/(admin)/layout.tsx calls `auth()` server-side, which tells you
  // nothing about the CLIENT SessionProvider's own timing). A hook whose
  // fetch effect runs once on mount with `[]` deps can lose that race: it
  // fires before `isAuthenticated` is true, the request 401s, and the effect
  // never runs again to retry — permanently caching an empty list for the
  // life of the page, even though `/admin/cosigners` genuinely has rows.
  //
  // `/admin/cosigners` (the page) never shows this: its own fetch effect
  // depends on `api`, which is a NEW object once `isAuthenticated` flips
  // true, so it naturally retries. `useCardImages` already gets this right
  // the same way (lib/use-card-images.ts). This hook did not.
  it('retries once the session finishes loading, instead of permanently caching an empty list from a request made before auth was ready', async () => {
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: false } as ReturnType<typeof useAdminApi>)

    const { result, rerender } = renderHook(() => useCosigners())

    // Still waiting on auth: no request attempted, and the hook must not
    // falsely report itself "done" with an empty list — it hasn't tried yet.
    expect(getMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)
    expect(result.current.options).toEqual([])

    // Session finishes loading — a real consignor exists to fetch now.
    getMock.mockResolvedValueOnce([{ consignor_id: 'c1', name: 'Alex' }])
    mockedUseAdminApi.mockReturnValue({ get: getMock, isAuthenticated: true } as ReturnType<typeof useAdminApi>)
    rerender()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).toEqual([{ value: 'c1', label: 'Alex' }])
  })
})
