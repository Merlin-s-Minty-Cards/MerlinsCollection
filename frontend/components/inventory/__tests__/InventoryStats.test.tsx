import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/inventory', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/inventory')>()),
  getInventorySummary: vi.fn(),
}))

// Mutable session so a test can simulate the pre-hydration (no token) state.
const { sessionRef } = vi.hoisted(() => ({
  sessionRef: {
    current: {
      data: { accessToken: 'test-token' as string | undefined } as { accessToken?: string } | null,
      status: 'authenticated' as string,
    },
  },
}))

vi.mock('next-auth/react', () => ({
  useSession: () => sessionRef.current,
}))

import InventoryStats from '@/components/inventory/InventoryStats'
import { getInventorySummary } from '@/lib/inventory'

const mockedGetSummary = vi.mocked(getInventorySummary)

beforeEach(() => {
  vi.clearAllMocks()
  sessionRef.current = {
    data: { accessToken: 'test-token' },
    status: 'authenticated',
  }
})

describe('InventoryStats', () => {
  // RFC 0025 T5 — the owner asked for the Est. value tile removed, not
  // relabeled. Two tiles now, never three.
  it('renders the two summary values with the existing labels', async () => {
    mockedGetSummary.mockResolvedValue({
      cards_in_vault: 312,
      sets_tracked: 27,
    })

    render(<InventoryStats />)

    expect(await screen.findByText('312')).toBeInTheDocument()
    expect(screen.getByText('27')).toBeInTheDocument()
    for (const label of ['Cards in vault', 'Sets tracked']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.queryByText('Est. value')).not.toBeInTheDocument()
  })

  it('renders "—" placeholders while loading (never the old fake numbers)', () => {
    mockedGetSummary.mockReturnValue(new Promise(() => {})) // never resolves

    render(<InventoryStats />)

    expect(screen.getAllByText('—')).toHaveLength(2)
    expect(screen.queryByText('4,820')).not.toBeInTheDocument()
  })

  it('does not fetch before the session token has hydrated (avoids a guaranteed 401)', () => {
    sessionRef.current = { data: null, status: 'loading' }
    mockedGetSummary.mockResolvedValue({ cards_in_vault: 1, sets_tracked: 1 })

    render(<InventoryStats />)

    expect(mockedGetSummary).not.toHaveBeenCalled()
    expect(screen.getAllByText('—')).toHaveLength(2)
  })

  it('renders "—" on error, never a crash or the old fake numbers', async () => {
    mockedGetSummary.mockRejectedValue(new Error('401'))

    render(<InventoryStats />)

    await waitFor(() => expect(screen.getAllByText('—')).toHaveLength(2))
    expect(screen.queryByText('$612k')).not.toBeInTheDocument()
    // labels remain even in the error state
    expect(screen.getByText('Cards in vault')).toBeInTheDocument()
  })
})
