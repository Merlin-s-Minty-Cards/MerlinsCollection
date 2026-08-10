import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SlabsPage from '../page'

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

  // ---- Intake affordances (2026-08-10) -------------------------------------
  // The page previously dumped the whole entry form on screen with no way to
  // put it away, and offered no visible route in other than typing. These
  // cover the disclosure, the (real) scan path, and the two placeholders whose
  // blocker is PSA account approval — re-confirmed 403 on 2026-08-10.

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

    // The wedge scanner is just a fast keyboard, so "arm the field" IS the
    // whole feature — there is nothing to defer here.
    it('arms the cert field for a scan, opening the form if it was closed', async () => {
      render(<SlabsPage />)
      fireEvent.click(screen.getByRole('button', { name: /scan cert/i }))

      const cert = screen.getByLabelText(/cert number/i)
      expect(cert).toBeInTheDocument()
      await waitFor(() => expect(cert).toHaveFocus())
      expect(screen.getByText(/waiting for scan/i)).toBeInTheDocument()
    })

    it('offers a camera button but disables it, naming PSA approval as the blocker', () => {
      render(<SlabsPage />)
      const camera = screen.getByRole('button', { name: /camera/i })
      expect(camera).toBeDisabled()
      expect(camera).toHaveAccessibleDescription(/psa api approval/i)
    })

    it('offers cert auto-fill but disables it, naming the same blocker', () => {
      render(<SlabsPage />)
      const autofill = screen.getByRole('button', { name: /auto-fill/i })
      expect(autofill).toBeDisabled()
      expect(autofill).toHaveAccessibleDescription(/psa api approval/i)
    })
  })
})
