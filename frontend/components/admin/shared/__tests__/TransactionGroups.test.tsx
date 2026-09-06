/**
 * RFC 0010 T11 — an accidental sale can be undone, from the archive.
 *
 * Owner report: *"No way to manually change past sales in this history; should
 * be able to edit/delete/undo from that menu for accidental transactions."*
 *
 * The archive is where a transaction actually has a row, so this is where the
 * action lives. It is BATCH-AWARE because T10 made a five-card sale read as one
 * line — voiding five sales when you meant one is exactly the mistake this
 * feature exists to fix, so the count is in the confirm text.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import TransactionGroups, { type ArchiveTransaction } from '../TransactionGroups'

const onVoid = vi.fn()
const onRestore = vi.fn()
const onEdit = vi.fn()
const postMock = vi.fn()

vi.mock('@/lib/use-shows', () => ({
  useShows: () => ({ options: [], loading: false }),
}))

// Owner report: sale rows in the archive showed only a raw item_id ULID —
// no image, no name — behind a chevron that just repeated the same row.
// SaleDetailModal resolves each leg's name/card_id through POST
// /inventory/items-brief (backend/routers/admin/inventory.py); mocked here
// the same way every other admin-api-dependent component's test file does.
const mockApi = { get: vi.fn(), post: postMock, put: vi.fn(), del: vi.fn(), isAuthenticated: true }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

beforeEach(() => {
  onVoid.mockReset()
  onRestore.mockReset()
  onEdit.mockReset()
  onVoid.mockResolvedValue(undefined)
  onRestore.mockResolvedValue(undefined)
  onEdit.mockResolvedValue({ cost_basis_updated: false, cost_basis_skipped_reason: null })
  postMock.mockReset()
  postMock.mockImplementation((path: string) => {
    if (path === '/inventory/items-brief') return Promise.resolve({})
    if (path === '/inventory/card-images') return Promise.resolve({})
    return Promise.resolve({})
  })
})

function leg(over: Partial<ArchiveTransaction> = {}): ArchiveTransaction {
  return {
    txn_id: 'txn-1',
    type: 'sale',
    item_id: 'item-1',
    date: '2026-08-10',
    amount: '40.00',
    payment_method: 'cash',
    ...over,
  }
}

const BATCH: ArchiveTransaction[] = [
  leg({ txn_id: 'txn-1', item_id: 'item-1', batch_id: 'sell-1' }),
  leg({ txn_id: 'txn-2', item_id: 'item-2', batch_id: 'sell-1', amount: '10.00' }),
  leg({ txn_id: 'txn-3', item_id: 'item-3', batch_id: 'sell-1', amount: '25.00' }),
]

const VOIDED = leg({
  txn_id: 'txn-9',
  item_id: 'item-9',
  voided_at: '2026-08-11T18:30:00Z',
  voided_by: 'merlin',
  void_reason: 'Rang up the wrong card',
})

function renderGroups(transactions: ArchiveTransaction[]) {
  return render(
    <TransactionGroups
      transactions={transactions}
      onVoid={onVoid}
      onRestore={onRestore}
      onEdit={onEdit}
    />,
  )
}

function openVoidDialog() {
  fireEvent.click(screen.getByRole('button', { name: /void this transaction/i }))
}

describe('voiding from the transaction archive', () => {
  it('will not void without a reason', async () => {
    renderGroups([leg()])
    openVoidDialog()

    const confirm = screen.getByRole('button', { name: /^void$/i })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: 'Rang up the wrong card' },
    })
    expect(confirm).not.toBeDisabled()

    fireEvent.click(confirm)
    await waitFor(() => expect(onVoid).toHaveBeenCalledTimes(1))
    expect(onVoid.mock.calls[0][1]).toBe('Rang up the wrong card')
  })

  it('names the card count when the whole transaction is being voided', () => {
    renderGroups(BATCH)
    openVoidDialog()

    expect(
      screen.getByText(/void this whole transaction \(3 cards\)/i),
    ).toBeInTheDocument()
    expect(onVoid).not.toHaveBeenCalled()
  })

  it('targets the batch, not one leg, when the group has a batch_id', async () => {
    renderGroups(BATCH)
    openVoidDialog()
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'oops' } })
    fireEvent.click(screen.getByRole('button', { name: /^void$/i }))

    await waitFor(() => expect(onVoid).toHaveBeenCalled())
    expect(onVoid.mock.calls[0][0]).toMatchObject({
      scope: 'batch',
      id: 'sell-1',
      count: 3,
    })
  })

  it('renders a voided row struck through, with its reason and who voided it', () => {
    renderGroups([VOIDED])

    const row = screen.getByTestId('txn-group')
    expect(row.className).toMatch(/line-through/)
    const note = within(row).getByTestId('voided-note')
    expect(note).toHaveTextContent(/Rang up the wrong card/)
    expect(note).toHaveTextContent(/merlin/)
    // formatTimestamp, in the viewer's zone — not a raw ISO string.
    expect(note.textContent ?? '').not.toMatch(/2026-08-11T18:30:00Z/)
  })

  it('offers Restore on a voided row and never Void', () => {
    renderGroups([VOIDED])
    expect(screen.getByRole('button', { name: /restore/i })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /void this transaction/i }),
    ).not.toBeInTheDocument()
  })

  it('offers Void on a live row and never Restore', () => {
    renderGroups([leg()])
    expect(
      screen.getByRole('button', { name: /void this transaction/i }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /restore/i })).not.toBeInTheDocument()
  })

  it('surfaces a failed void and leaves the row unchanged', async () => {
    onVoid.mockRejectedValue(new Error('Item item-1 is lost, not sold'))
    renderGroups([leg()])
    openVoidDialog()
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'oops' } })
    fireEvent.click(screen.getByRole('button', { name: /^void$/i }))

    expect(await screen.findByText(/is lost, not sold/i)).toBeInTheDocument()
    const row = screen.getByTestId('txn-group')
    expect(row.className).not.toMatch(/line-through/)
  })

  it('excludes a voided leg from the group total', () => {
    renderGroups([
      leg({ txn_id: 'a', item_id: 'i-a', batch_id: 'b1', amount: '40.00' }),
      leg({
        txn_id: 'b', item_id: 'i-b', batch_id: 'b1', amount: '10.00',
        voided_at: '2026-08-11T18:30:00Z', void_reason: 'oops',
      }),
    ])
    const row = screen.getByTestId('txn-group')
    expect(within(row).getByText(/\$40\.00/)).toBeInTheDocument()
    expect(within(row).queryByText(/\$50\.00/)).not.toBeInTheDocument()
  })
})

describe('group sort control (RFC 0013 T4f)', () => {
  // Each fixture below is ordered so the DEFAULT (endpoint/insertion) order
  // would give a DIFFERENT result than the sort under test — a click that
  // merely reproduced the default order would prove nothing.

  function dateOrder(rows: HTMLElement[]) {
    return rows.map((r) => within(r).getByText(/Aug \d+, 2026/).textContent)
  }

  it('does not reorder groups until a sort is clicked (groupTransactions default preserved)', () => {
    renderGroups([
      leg({ txn_id: 'old', item_id: 'i-old', date: '2026-08-01' }),
      leg({ txn_id: 'new', item_id: 'i-new', date: '2026-08-20' }),
    ])
    const rows = screen.getAllByTestId('txn-group')
    expect(dateOrder(rows)).toEqual(['Aug 1, 2026', 'Aug 20, 2026'])
  })

  it('sorts groups by DATE, newest first, on the first click', () => {
    renderGroups([
      leg({ txn_id: 'old', item_id: 'i-old', date: '2026-08-01' }),
      leg({ txn_id: 'new', item_id: 'i-new', date: '2026-08-20' }),
    ])
    fireEvent.click(screen.getByRole('button', { name: /^date/i }))
    const rows = screen.getAllByTestId('txn-group')
    expect(dateOrder(rows)).toEqual(['Aug 20, 2026', 'Aug 1, 2026'])
  })

  it('reverses direction on a second click of the same sort', () => {
    renderGroups([
      leg({ txn_id: 'old', item_id: 'i-old', date: '2026-08-01' }),
      leg({ txn_id: 'new', item_id: 'i-new', date: '2026-08-20' }),
    ])
    const dateBtn = screen.getByRole('button', { name: /^date/i })
    fireEvent.click(dateBtn)
    fireEvent.click(dateBtn)
    const rows = screen.getAllByTestId('txn-group')
    expect(dateOrder(rows)).toEqual(['Aug 1, 2026', 'Aug 20, 2026'])
  })

  it('sorts groups by TOTAL, highest first, on the first click', () => {
    renderGroups([
      leg({ txn_id: 'small', item_id: 'i-small', date: '2026-08-05', amount: '5.00' }),
      leg({ txn_id: 'big', item_id: 'i-big', date: '2026-08-05', amount: '100.00' }),
    ])
    fireEvent.click(screen.getByRole('button', { name: /^total/i }))
    const rows = screen.getAllByTestId('txn-group')
    // Both groups share a date, so this can only pass if TOTAL drove the order.
    expect(within(rows[0]).getByText('$100.00')).toBeInTheDocument()
    expect(within(rows[1]).getByText('$5.00')).toBeInTheDocument()
  })

  it('Clear returns to the default, unsorted order', () => {
    renderGroups([
      leg({ txn_id: 'old', item_id: 'i-old', date: '2026-08-01' }),
      leg({ txn_id: 'new', item_id: 'i-new', date: '2026-08-20' }),
    ])
    fireEvent.click(screen.getByRole('button', { name: /^date/i }))
    expect(dateOrder(screen.getAllByTestId('txn-group'))).toEqual(['Aug 20, 2026', 'Aug 1, 2026'])

    fireEvent.click(screen.getByRole('button', { name: /clear/i }))
    expect(dateOrder(screen.getAllByTestId('txn-group'))).toEqual(['Aug 1, 2026', 'Aug 20, 2026'])
  })

  it('does not show the sort control when there are no groups', () => {
    renderGroups([])
    expect(screen.queryByText(/sort by:/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Sale detail modal — owner report: "listed sales should have details of the
// cards sold including image, name, and price... instead of an arrow to
// reveal the individual sales, [let] users click on the bundled sale to view
// the individual components... in a popup similar to how you would click on
// an inventory item." Replaces the old inline chevron-expand (no pinned test
// covered that behaviour in this file — TransactionGroups.test.tsx never
// asserted on `txn-leg` rows; the page-level assertions live in
// app/(admin)/admin/analytics/__tests__/page.test.tsx and are updated there
// to match).
// ---------------------------------------------------------------------------

describe('sale detail modal', () => {
  it('opens when the cards cell is clicked, even for a single-card group', async () => {
    renderGroups([leg({ item_id: 'item-1' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('opens for a multi-card group and requests every leg\'s brief in one call', async () => {
    renderGroups(BATCH)
    fireEvent.click(screen.getByRole('button', { name: /view the 3 cards/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/inventory/items-brief', {
        item_ids: ['item-1', 'item-2', 'item-3'],
      }),
    )
  })

  it('shows each leg\'s resolved name and its price inside the modal', async () => {
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/items-brief') {
        return Promise.resolve({
          'item-1': { name: 'Charizard EX', card_id: 'sv1-1' },
          'item-2': { name: 'Pikachu VMAX', card_id: 'sv1-2' },
          'item-3': { name: 'Gengar EX', card_id: 'sv1-3' },
        })
      }
      return Promise.resolve({})
    })
    renderGroups(BATCH)
    fireEvent.click(screen.getByRole('button', { name: /view the 3 cards/i }))

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Charizard EX')).toBeInTheDocument()
    expect(within(dialog).getByText('Pikachu VMAX')).toBeInTheDocument()
    expect(within(dialog).getByText('Gengar EX')).toBeInTheDocument()
    // The three legs' amounts from the BATCH fixture (40, 10, 25).
    expect(within(dialog).getByText('$40.00')).toBeInTheDocument()
    expect(within(dialog).getByText('$10.00')).toBeInTheDocument()
    expect(within(dialog).getByText('$25.00')).toBeInTheDocument()
  })

  it('shows leg profit (amount - cost_basis) for a sale, RFC 0024 T5', async () => {
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/items-brief') {
        return Promise.resolve({
          'item-1': { name: 'Charizard EX', card_id: 'sv1-1', cost_basis: '10.00' },
        })
      }
      return Promise.resolve({})
    })
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', type: 'sale', amount: '40.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    const dialog = await screen.findByRole('dialog', { name: /sale details/i })
    expect(await within(dialog).findByText('+$30.00')).toBeInTheDocument()
  })

  it('warns when the profit may be overstated by a $0 cost basis (consigned item)', async () => {
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/items-brief') {
        return Promise.resolve({
          'item-1': { name: 'Charizard EX', card_id: 'sv1-1', cost_basis: '0.00' },
        })
      }
      return Promise.resolve({})
    })
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', type: 'sale', amount: '40.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    const dialog = await screen.findByRole('dialog', { name: /sale details/i })
    expect(await within(dialog).findByText('+$40.00')).toBeInTheDocument()
    expect(within(dialog).getByTitle(/overstated/i)).toBeInTheDocument()
  })

  it('never shows a profit figure on a purchase leg', async () => {
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/items-brief') {
        return Promise.resolve({
          'item-1': { name: 'Charizard EX', card_id: 'sv1-1', cost_basis: '10.00' },
        })
      }
      return Promise.resolve({})
    })
    // amount(40) - cost_basis(10) = 30 — a value that appears NOWHERE else on
    // this leg's row, so its absence is unambiguous evidence no profit badge
    // rendered (as opposed to a regex that could accidentally match
    // `SignedAmount`'s own signed rendering of the leg's amount).
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', type: 'purchase', amount: '40.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    const dialog = await screen.findByRole('dialog', { name: /sale details/i })
    await within(dialog).findByText('Charizard EX')
    expect(within(dialog).queryByText('+$30.00')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('-$30.00')).not.toBeInTheDocument()
  })

  it('falls back to the item_id when a leg has no resolvable name', async () => {
    renderGroups([leg({ item_id: 'item-1' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('item-1')).toBeInTheDocument()
  })

  it('closes on request', async () => {
    renderGroups([leg({ item_id: 'item-1' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('lets a live leg be voided from inside the modal', async () => {
    renderGroups(BATCH)
    fireEvent.click(screen.getByRole('button', { name: /view the 3 cards/i }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.click(within(dialog).getAllByRole('button', { name: /^void this card$/i })[0])
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'Rang up wrong card' } })
    fireEvent.click(screen.getByRole('button', { name: /^void$/i }))

    await waitFor(() => expect(onVoid).toHaveBeenCalledTimes(1))
    expect(onVoid.mock.calls[0][0]).toMatchObject({ scope: 'row', id: 'txn-1', count: 1 })
  })

  it('lets a voided leg be restored from inside the modal', async () => {
    renderGroups([
      leg({ txn_id: 'a', item_id: 'i-a', batch_id: 'b1', amount: '40.00' }),
      leg({
        txn_id: 'b', item_id: 'i-b', batch_id: 'b1', amount: '10.00',
        voided_at: '2026-08-11T18:30:00Z', void_reason: 'oops',
      }),
    ])
    fireEvent.click(screen.getByRole('button', { name: /view the 2 cards/i }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.click(within(dialog).getByRole('button', { name: /^restore this card$/i }))
    await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1))
    expect(onRestore.mock.calls[0][0]).toMatchObject({ scope: 'row', id: 'b', count: 1 })
  })

  it('reflects a fresh transactions prop while the modal is still open, instead of freezing on a stale snapshot', async () => {
    // Guards the adversarial-review fix: the modal used to capture the whole
    // TransactionGroup OBJECT at click time. handleVoid/handleRestore in the
    // parent page call refetchDay() after a void, which rebuilds `groups`
    // with new objects — a captured object would keep showing the leg as
    // live until the modal was closed and reopened. Keying on `group.key`
    // and re-deriving from the current `groups` on every render is what
    // fixes it; this simulates that refetch via `rerender`.
    const { rerender } = renderGroups([
      leg({ txn_id: 'a', item_id: 'i-a', batch_id: 'b1', amount: '40.00' }),
      leg({ txn_id: 'b', item_id: 'i-b', batch_id: 'b1', amount: '10.00' }),
    ])
    fireEvent.click(screen.getByRole('button', { name: /view the 2 cards/i }))
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).queryByRole('button', { name: /^restore this card$/i }),
    ).not.toBeInTheDocument()

    // The parent's post-void refetch: leg 'b' now comes back voided.
    rerender(
      <TransactionGroups
        transactions={[
          leg({ txn_id: 'a', item_id: 'i-a', batch_id: 'b1', amount: '40.00' }),
          leg({
            txn_id: 'b', item_id: 'i-b', batch_id: 'b1', amount: '10.00',
            voided_at: '2026-08-11T18:30:00Z', void_reason: 'oops',
          }),
        ]}
        onVoid={onVoid}
        onRestore={onRestore}
      />,
    )

    expect(
      await within(screen.getByRole('dialog')).findByRole('button', { name: /^restore this card$/i }),
    ).toBeInTheDocument()
  })

  it('no longer renders legs inline in the table — the modal is the only place to see them', async () => {
    renderGroups(BATCH)
    expect(screen.queryAllByTestId('txn-leg')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: /view the 3 cards/i }))
    await screen.findByRole('dialog')
    expect(screen.queryAllByTestId('txn-leg')).toHaveLength(0)
  })
})

// ---------------------------------------------------------------------------
// Transaction edit (RFC 0024 T3/T4) — a typo correction path distinct from
// void, reached from the SAME per-leg row the void/restore actions live on.
// ---------------------------------------------------------------------------

describe('editing a leg from inside the modal', () => {
  it('opens the edit dialog seeded with the leg\'s own values', async () => {
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', amount: '150.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })

    fireEvent.click(screen.getByRole('button', { name: /^edit this card$/i }))
    expect(screen.getByLabelText('Amount')).toHaveValue('150.00')
  })

  it('submits only the changed field to onEdit, keyed by txn_id', async () => {
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', amount: '150.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })
    fireEvent.click(screen.getByRole('button', { name: /^edit this card$/i }))

    const amountField = screen.getByLabelText('Amount')
    fireEvent.change(amountField, { target: { value: '105' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(onEdit).toHaveBeenCalledWith('txn-1', { amount: 105 }))
  })

  it('refetches the archive after a successful edit, closing the dialog', async () => {
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', amount: '150.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })
    fireEvent.click(screen.getByRole('button', { name: /^edit this card$/i }))
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '105' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(onEdit).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.queryByLabelText('Amount')).not.toBeInTheDocument(),
    )
  })

  it('keeps the dialog open and shows the cost_basis_skipped_reason plainly, not as an error', async () => {
    onEdit.mockResolvedValue({
      cost_basis_updated: false,
      cost_basis_skipped_reason: 'cost basis was changed manually since',
    })
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', type: 'purchase', amount: '32.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })
    fireEvent.click(screen.getByRole('button', { name: /^edit this card$/i }))
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '40' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    expect(await screen.findByText(/cost basis was changed manually since/i))
      .toBeInTheDocument()
    // Still open, still editable — not swapped for an error state.
    expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  })

  it('surfaces a failed edit and leaves the row unchanged', async () => {
    onEdit.mockRejectedValue(new Error('Transaction is voided'))
    renderGroups([leg({ txn_id: 'txn-1', item_id: 'item-1', amount: '150.00' })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })
    fireEvent.click(screen.getByRole('button', { name: /^edit this card$/i }))
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '105' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    expect(await screen.findByText(/transaction is voided/i)).toBeInTheDocument()
  })

  it('does not offer Edit on a voided leg', async () => {
    renderGroups([leg({
      txn_id: 'txn-1', item_id: 'item-1',
      voided_at: '2026-08-11T18:30:00Z', void_reason: 'oops',
    })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    await screen.findByRole('dialog', { name: /sale details/i })
    expect(screen.queryByRole('button', { name: /^edit this card$/i })).not.toBeInTheDocument()
  })

  it('renders an edit note on the leg, the way the void reason already renders', async () => {
    renderGroups([leg({
      txn_id: 'txn-1', item_id: 'item-1',
      edited_at: '2026-08-12T10:00:00Z', edited_by: 'merlin',
      edit_history: [{
        at: '2026-08-12T10:00:00Z', by: 'merlin',
        changes: [{ field: 'amount', old: '150.00', new: '105.00' }],
      }],
    })])
    fireEvent.click(screen.getByRole('button', { name: /view the 1 card/i }))
    const dialog = await screen.findByRole('dialog', { name: /sale details/i })
    expect(within(dialog).getByTestId('edited-note')).toHaveTextContent(/merlin/i)
  })
})
