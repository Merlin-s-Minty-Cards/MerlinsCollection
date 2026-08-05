import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, within, waitFor } from '@testing-library/react'
import AdminInventoryPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()
const mockApi = {
  get: getMock, post: postMock, put: putMock, patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

describe('AdminInventoryPage location pickers use the live location list', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    postMock.mockResolvedValue({ item_id: 'new-1' })
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([{ value: 'custom_shelf', label: 'Custom Shelf' }])
      }
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{ item_id: 'item-1', display_name: 'Pikachu', location: 'custom_shelf', status: 'available' }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })
  })

  it('create-form location select uses live options, not the static LOCATION_OPTIONS list', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    // Real accessible name confirmed by reading inventory/page.tsx's header
    // button: it reads "Add Item" (with a Plus icon), not "New Item".
    fireEvent.click(screen.getByRole('button', { name: /add item/i }))

    // Scope to the create-form dialog itself, not the whole document. The
    // filter-bar location <select> (page.tsx, already wired to useLocations()
    // before this task) also renders a "Custom Shelf" <option> once its own
    // useLocations() call resolves, so an unscoped screen.findByRole('option',
    // { name: 'Custom Shelf' }) can pass on the filter bar's option alone —
    // proving nothing about CreateItemModal's own select. Scoping via
    // within(dialog) makes both the positive and negative assertions actually
    // exercise CreateItemModal's dropdown.
    const dialog = await screen.findByRole('dialog', { name: /add new item/i })

    expect(await within(dialog).findByRole('option', { name: 'Custom Shelf' })).toBeInTheDocument()
    // "Glass Case" is not an actual LOCATION_OPTIONS label (the static list has
    // "Glass" and "Display Case" as separate entries), so it would never appear
    // either way — that assertion wouldn't catch a regression. "Toploader" is a
    // real static-list label, so its absence actually proves the dropdown is no
    // longer sourced from the static list (mirrors the negative check used in
    // CardDetailModal.test.tsx).
    expect(within(dialog).queryByRole('option', { name: /Toploader/i })).not.toBeInTheDocument()
  })

  it('filters by needs_review via the Needs Review select', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByLabelText(/needs review/i), { target: { value: 'true' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ needs_review: 'true' }),
      )
    )
  })

  it('create-form defaults location to the first live option, not a hardcoded "toploader" (finding 2)', async () => {
    // "toploader" is deletable via DELETE /admin/locations/{value} once no
    // item uses it (Task 7's whole point) — a hardcoded default that
    // survives its deletion 422s "Unknown location" on submit unless the
    // admin happens to touch the dropdown themselves.
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /add item/i }))
    const dialog = await screen.findByRole('dialog', { name: /add new item/i })

    fireEvent.change(within(dialog).getByLabelText(/^name$/i), { target: { value: 'Pikachu' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^create$/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/inventory',
        expect.objectContaining({ location: 'custom_shelf' }),
      )
    )
  })
})

describe('AdminInventoryPage inline location edit no-op guard', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      }
      if (path === '/inventory/search') {
        // A null-location item — Buy/Trade can leave location unset by
        // design, and the inline editor no longer has a "— None —" option
        // to explicitly re-select once location became required (finding 6).
        return Promise.resolve({
          items: [{ item_id: 'item-1', display_name: 'Pikachu', location: null, status: 'available' }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })
  })

  it('does not PUT when the location editor is opened and blurred without a change', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByTitle('Click to edit'))
    const select = screen.getByRole('combobox', { name: /edit location/i })
    fireEvent.blur(select)

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
  })
})
