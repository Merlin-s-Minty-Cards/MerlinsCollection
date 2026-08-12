import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SlabsPage from '../page'
import { AdminApiError } from '@/lib/admin-api'

const mockApi = { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})
// NOTE: useLocations returns `options`, NOT `locations` (lib/use-locations.ts:13).
vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({ options: [{ value: 'toploader', label: 'Toploader' }], loading: false }),
}))

// The entry form is behind a disclosure now (2026-08-10), matching the other
// admin tabs. Every staging helper has to open it first.
function openManualEntry() {
  fireEvent.click(screen.getByRole('button', { name: /manual entry/i }))
}

function stageOne() {
  openManualEntry()
  fireEvent.change(screen.getByLabelText(/cert number/i), { target: { value: '89787279' } })
  fireEvent.change(screen.getByLabelText(/card name/i), { target: { value: 'Gengar VMAX' } })
  // ANCHORED — /grade/i matches both "Grade" and "Grade label" and throws
  // "Found multiple elements". Corrected during Task 4; see its DONE note.
  fireEvent.change(screen.getByLabelText(/^grade$/i), { target: { value: '9.5' } })
  fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '900.50' } })
  fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
}

describe('Slabs page', () => {
  beforeEach(() => {
    mockApi.get.mockReset(); mockApi.post.mockReset()
    mockApi.get.mockResolvedValue({ items: [], total: 0 })
    mockApi.post.mockResolvedValue({ buy_id: 'BUY1' })
  })

  it('commits create -> items -> confirm in that order with kind graded', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    const paths = mockApi.post.mock.calls.map((c) => c[0])
    expect(paths).toEqual(['/purchases', '/purchases/BUY1/items', '/purchases/BUY1/confirm'])
    expect(mockApi.post.mock.calls[1][1]).toMatchObject({ kind: 'graded', cert_number: '89787279' })
  })

  it('sends buy_price and grade as JSON numbers, not strings', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    const body = mockApi.post.mock.calls[1][1]
    expect(typeof body.buy_price).toBe('number')
    expect(body.buy_price).toBe(900.5)
    expect(typeof body.grade).toBe('number')
  })

  it('never sends manual_entry — every slab is hand-typed and must not flood Triage', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    expect(mockApi.post.mock.calls[1][1]).not.toHaveProperty('manual_entry')
  })

  it('stops without confirming when an item post fails, keeping the rows', async () => {
    mockApi.post
      .mockResolvedValueOnce({ buy_id: 'BUY1' })
      .mockRejectedValueOnce(new Error('boom'))
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    const paths = mockApi.post.mock.calls.map((c) => c[0])
    expect(paths).not.toContain('/purchases/BUY1/confirm')
    expect(screen.getByText('89787279')).toBeInTheDocument()
  })

  it('clears the batch and reports the total on success', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
    await waitFor(() => expect(screen.getByText(/nothing staged/i)).toBeInTheDocument())
    expect(screen.getByText(/900\.50/)).toBeInTheDocument()
  })

  // T-FINAL (2026-08-09). `useAdminApi.get(path, params?)` takes the params
  // RECORD as its second positional argument (lib/admin-api.ts:84-88) — it is
  // not a FetchOptions wrapper. Passing `{ params: { priced } }` makes the
  // request builder iterate the OUTER object, so it emits
  // `?params=%5Bobject+Object%5D` and never sends `priced` at all: the unpriced
  // worklist silently returns every slab. Only `next build` caught this; vitest
  // does not typecheck, so all 573 tests stayed green.
  it('sends priced as a query param the backend can read, not a nested object', async () => {
    render(<SlabsPage />)
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled())
    mockApi.get.mockClear()

    fireEvent.change(screen.getByLabelText(/filter slabs by pricing/i), {
      target: { value: 'false' },
    })

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled())
    expect(mockApi.get).toHaveBeenLastCalledWith('/slabs', { priced: 'false' })
  })

  it('omits the params argument entirely when the filter is "all"', async () => {
    render(<SlabsPage />)
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled())
    expect(mockApi.get).toHaveBeenLastCalledWith('/slabs', undefined)
  })

  // ---- RFC 0010 T0: a comma-typed cost survives the whole path -------------

  it('sends buy_price as a JSON number when the cost was typed as 1,300', async () => {
    render(<SlabsPage />)
    openManualEntry()
    fireEvent.change(screen.getByLabelText(/cert number/i), { target: { value: '89787279' } })
    fireEvent.change(screen.getByLabelText(/card name/i), { target: { value: 'Gengar VMAX' } })
    fireEvent.change(screen.getByLabelText(/^grade$/i), { target: { value: '9.5' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    const body = mockApi.post.mock.calls[1][1]
    expect(typeof body.buy_price).toBe('number')
    expect(body.buy_price).toBe(1300)
  })

  it('reports a committed total that matches the total shown while staged', async () => {
    render(<SlabsPage />)
    openManualEntry()
    fireEvent.change(screen.getByLabelText(/cert number/i), { target: { value: '89787279' } })
    fireEvent.change(screen.getByLabelText(/card name/i), { target: { value: 'Gengar VMAX' } })
    fireEvent.change(screen.getByLabelText(/^grade$/i), { target: { value: '9.5' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    // The staged total is the pre-commit signal the old table lacked entirely.
    const staged = await screen.findByRole('row', { name: /batch total/i })
    expect(staged).toHaveTextContent('$1,300.00')

    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
    await waitFor(() => expect(screen.getByText(/nothing staged/i)).toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('$1,300.00')
  })

  // ---- Intake affordances (2026-08-10) -------------------------------------
  // The page previously dumped the whole entry form on screen with no way to
  // put it away. The disclosure below is what remains of that work.
  //
  // THREE TESTS WERE DELETED HERE by RFC 0010 T12, deliberately: the "arms the
  // cert field for a scan" test and the two "disabled, naming PSA approval"
  // tests. Their subjects no longer exist — PSA's cert API became a paid
  // feature the owner declined, so camera capture and cert auto-fill are
  // WITHDRAWN rather than deferred, and the scan button was redundant with the
  // plain cert field a wedge scanner already types into. The replacement
  // assertions are in the "Slabs intake after PSA was dropped" block below,
  // which pins their ABSENCE, and `CertInput.test.tsx` still pins the wedge
  // behaviour that makes removing the button safe.

  describe('intake affordances', () => {
    it('keeps the manual entry form put away until it is asked for', () => {
      render(<SlabsPage />)
      expect(screen.queryByLabelText(/cert number/i)).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: /manual entry/i })).toHaveAttribute(
        'aria-expanded',
        'false',
      )
    })

    it('reveals the entry form when Manual entry is pressed, and puts it away again', () => {
      render(<SlabsPage />)
      const toggle = screen.getByRole('button', { name: /manual entry/i })

      fireEvent.click(toggle)
      expect(screen.getByLabelText(/cert number/i)).toBeInTheDocument()
      expect(toggle).toHaveAttribute('aria-expanded', 'true')

      fireEvent.click(toggle)
      expect(screen.queryByLabelText(/cert number/i)).not.toBeInTheDocument()
    })

  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T12 — PSA is out, the scanner affordance is out, a price at intake
// ---------------------------------------------------------------------------

describe('Slabs intake after PSA was dropped (RFC 0010 T12)', () => {
  beforeEach(() => {
    mockApi.get.mockReset(); mockApi.post.mockReset()
    mockApi.get.mockResolvedValue({ items: [], total: 0 })
    mockApi.post.mockResolvedValue({ buy_id: 'BUY1' })
  })

  it('no longer offers Camera scan — the API is paid and declined, so the gap is permanent', () => {
    render(<SlabsPage />)
    expect(screen.queryByRole('button', { name: /camera/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/PSA API approval/i)).not.toBeInTheDocument()
  })

  it('no longer offers Auto-fill from cert', () => {
    render(<SlabsPage />)
    expect(screen.queryByRole('button', { name: /auto-fill/i })).not.toBeInTheDocument()
  })

  it('no longer offers a Scan cert button — the plain cert field IS the scanner target', () => {
    render(<SlabsPage />)
    expect(screen.queryByRole('button', { name: /scan cert/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/waiting for scan/i)).not.toBeInTheDocument()
  })

  it('keeps Manual entry as the one intake toggle', () => {
    render(<SlabsPage />)
    expect(screen.getByRole('button', { name: /manual entry/i })).toBeInTheDocument()
  })
})

describe('Slabs price-at-intake (RFC 0010 T12)', () => {
  function mockCommit(overrides: {
    refresh?: () => Promise<unknown>
    status?: Record<string, unknown>
  } = {}) {
    mockApi.get.mockReset(); mockApi.post.mockReset()
    mockApi.get.mockImplementation((path: string) => {
      if (path === '/slabs/refresh-prices/status') {
        return Promise.resolve(overrides.status ?? {
          state: 'completed', priced: 1, candidates: 1, failures: 0,
          credits_remaining: 96, error: null,
        })
      }
      return Promise.resolve({ items: [], total: 0 })
    })
    mockApi.post.mockImplementation((path: string) => {
      if (path === '/purchases') return Promise.resolve({ buy_id: 'BUY1' })
      if (path === '/purchases/BUY1/items') return Promise.resolve({})
      if (path === '/purchases/BUY1/confirm') {
        return Promise.resolve({ items_created: 1, item_ids: ['ITEM1'] })
      }
      if (path === '/slabs/refresh-prices') {
        return overrides.refresh ? overrides.refresh() : Promise.resolve({ state: 'started' })
      }
      return Promise.resolve({})
    })
  }

  async function commitOne() {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
  }

  it('prices the batch AFTER the commit, scoped to the ids it created', async () => {
    mockCommit()
    await commitOne()

    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalledWith(
        '/slabs/refresh-prices', { item_ids: ['ITEM1'] },
      )
    })
    // Order is the requirement: the money write finishes first.
    const paths = mockApi.post.mock.calls.map((c) => c[0])
    expect(paths.indexOf('/purchases/BUY1/confirm')).toBeLessThan(
      paths.indexOf('/slabs/refresh-prices'),
    )
  })

  it('lands the commit success message first and unconditionally, even when pricing fails', async () => {
    mockCommit({ refresh: () => Promise.reject(new Error('vendor 500')) })
    await commitOne()

    // Hardened: without the second assertion this passes against code that
    // never prices at all, which proves nothing.
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith(
        '/slabs/refresh-prices', { item_ids: ['ITEM1'] },
      ),
    )
    expect(await screen.findByText(/Committed 1 slab/i)).toBeInTheDocument()
    expect(screen.queryByText(/Commit failed/i)).not.toBeInTheDocument()
  })

  it('reads a 409 as "committed, not yet priced", not as an error', async () => {
    const conflict = new AdminApiError(409, 'A slab price refresh is already running')
    mockCommit({ refresh: () => Promise.reject(conflict) })
    await commitOne()

    expect(await screen.findByText(/Committed 1 slab/i)).toBeInTheDocument()
    expect(await screen.findByText(/not yet priced/i)).toBeInTheDocument()
  })

  it('reports the credits the run spent, so the 50-a-day ceiling is visible', async () => {
    mockCommit()
    await commitOne()
    expect(await screen.findByText(/96 credits left/i)).toBeInTheDocument()
  })
})
