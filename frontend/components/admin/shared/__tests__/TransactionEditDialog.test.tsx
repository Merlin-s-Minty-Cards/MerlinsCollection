import { afterAll, describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TransactionEditDialog from '../TransactionEditDialog'
import type { ArchiveTransaction } from '../TransactionGroups'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

/**
 * RFC 0024 T4 — the per-leg transaction edit dialog. A typo correction,
 * distinct from void: it sends only the fields that actually changed, uses
 * `MoneyInput` (never `type="number"`/`parseFloat`), and surfaces
 * `cost_basis_skipped_reason` as plain information rather than an error.
 */

vi.mock('@/lib/use-shows', () => ({
  useShows: () => ({
    options: [{ value: 'show-1', label: 'Portland' }],
    loading: false,
  }),
}))

const restoreTz = pinTimeZone(PACIFIC)
afterAll(() => restoreTz())

function txn(over: Partial<ArchiveTransaction> = {}): ArchiveTransaction {
  return {
    txn_id: 'txn-1',
    type: 'sale',
    item_id: 'item-1',
    date: '2026-03-01',
    amount: '150.00',
    payment_method: 'cash',
    fee: '0',
    show_id: null,
    notes: null,
    ...over,
  }
}

describe('TransactionEditDialog', () => {
  it('seeds the form from the leg being edited', () => {
    render(
      <TransactionEditDialog
        open
        txn={txn({ amount: '150.00', payment_method: 'venmo' })}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('Amount')).toHaveValue('150.00')
    expect(screen.getByLabelText('Payment method')).toHaveValue('venmo')
  })

  it('sends only the fields that actually changed', async () => {
    const user = userEvent.setup({ delay: null })
    const onSave = vi.fn()
    render(
      <TransactionEditDialog
        open
        txn={txn({ amount: '150.00' })}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    )
    const amountField = screen.getByLabelText('Amount')
    await user.clear(amountField)
    await user.type(amountField, '105')
    await user.click(screen.getByRole('button', { name: /^save$/i }))
    expect(onSave).toHaveBeenCalledWith({ amount: 105 })
  })

  it('closes without saving when nothing changed', async () => {
    const user = userEvent.setup({ delay: null })
    const onSave = vi.fn()
    const onClose = vi.fn()
    render(
      <TransactionEditDialog
        open
        txn={txn()}
        onSave={onSave}
        onClose={onClose}
      />,
    )
    await user.click(screen.getByRole('button', { name: /^save$/i }))
    expect(onSave).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('disables Save while the amount is unreadable, never silently coerced', async () => {
    const user = userEvent.setup({ delay: null })
    render(
      <TransactionEditDialog
        open
        txn={txn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    const amountField = screen.getByLabelText('Amount')
    await user.clear(amountField)
    await user.type(amountField, 'abc')
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()
  })

  it('surfaces cost_basis_skipped_reason as plain information, not an error', () => {
    render(
      <TransactionEditDialog
        open
        txn={txn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
        costBasisSkippedReason="cost basis was changed manually since"
      />,
    )
    const note = screen.getByRole('status')
    expect(note).toHaveTextContent(/cost basis was changed manually since/i)
  })

  it('renders a server error distinctly from the cost-basis note', () => {
    render(
      <TransactionEditDialog
        open
        txn={txn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
        error="Something went wrong"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong')
  })

  it('a $0 amount is accepted, never treated as invalid', async () => {
    const user = userEvent.setup({ delay: null })
    const onSave = vi.fn()
    render(
      <TransactionEditDialog
        open
        txn={txn({ amount: '150.00' })}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    )
    const amountField = screen.getByLabelText('Amount')
    await user.clear(amountField)
    await user.type(amountField, '0')
    expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled()
    await user.click(screen.getByRole('button', { name: /^save$/i }))
    expect(onSave).toHaveBeenCalledWith({ amount: 0 })
  })
})
