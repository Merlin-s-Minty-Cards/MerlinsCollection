import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, within } from '@testing-library/react'
import AdminInventoryPage from '../page'

const getMock = vi.fn()
const mockApi = {
  get: getMock, post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

describe('AdminInventoryPage location pickers use the live location list', () => {
  beforeEach(() => {
    getMock.mockReset()
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
})
