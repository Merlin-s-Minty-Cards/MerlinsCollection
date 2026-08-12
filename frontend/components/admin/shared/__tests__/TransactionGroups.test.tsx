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

beforeEach(() => {
  onVoid.mockReset()
  onRestore.mockReset()
  onVoid.mockResolvedValue(undefined)
  onRestore.mockResolvedValue(undefined)
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
