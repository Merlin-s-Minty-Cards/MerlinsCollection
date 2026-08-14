import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCosigners } from '@/lib/use-cosigners'

const getMock = vi.fn()

vi.mock('@/lib/admin-api', () => ({
  useAdminApi: () => ({ get: getMock }),
}))

describe('useCosigners', () => {
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
})
