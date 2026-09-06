'use client'

import { useEffect, useState } from 'react'
import { useShows } from '@/lib/use-shows'
import { formatMoneyInput, parseMoney } from '@/lib/money'
import MoneyInput from './MoneyInput'
import ConfirmDialog from './ConfirmDialog'
import type { ArchiveTransaction } from './TransactionGroups'

/**
 * The per-leg Edit dialog (RFC 0024 T3/T4) — a typo correction, distinct from
 * void. `PATCH /admin/transactions/{txn_id}` accepts any subset of these six
 * fields; this dialog always sends every field that actually changed from the
 * leg's current value, never the whole form, so an untouched field cannot be
 * accidentally "corrected" back to its own displayed value on every save.
 *
 * Deliberately a DIALOG, not an RFC 0022 inline cell: an amount edit here has
 * a side effect on another entity (`cost_basis`), can move the row between
 * DynamoDB month partitions, and marks a report stale — that needs a surface
 * that can show `cost_basis_skipped_reason` on the way back, which a one-line
 * cell cannot.
 */

export interface TransactionEditPatch {
  amount?: number
  date?: string
  payment_method?: string
  fee?: number
  show_id?: string | null
  notes?: string | null
}

export interface TransactionEditResult {
  cost_basis_updated: boolean
  cost_basis_skipped_reason: string | null
}

function moneyField(value: unknown): string {
  const parsed = parseMoney(String(value ?? '0'))
  return formatMoneyInput(parsed ?? 0)
}

export default function TransactionEditDialog({
  open,
  txn,
  loading = false,
  error,
  costBasisSkippedReason,
  onSave,
  onClose,
}: {
  open: boolean
  /** The leg being edited — its CURRENT values seed the form. `null` while closed. */
  txn: ArchiveTransaction | null
  loading?: boolean
  error?: string | null
  /**
   * Set by the caller after a successful save that skipped the `cost_basis`
   * follow. Rendered as plain information, never an error banner — RFC 0022
   * made this the COMMON outcome once `cost_basis` is inline-editable
   * everywhere, not a rare failure.
   */
  costBasisSkippedReason?: string | null
  /** Only the fields that actually changed. */
  onSave: (patch: TransactionEditPatch) => void
  onClose: () => void
}) {
  const { options: showOptions } = useShows()
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState('')
  const [paymentMethod, setPaymentMethod] = useState('')
  const [fee, setFee] = useState('')
  const [showId, setShowId] = useState('')
  const [notes, setNotes] = useState('')

  // Each opening reseeds from the leg's current values — never carries a
  // previous edit's half-typed state into a different leg.
  useEffect(() => {
    if (!open || !txn) return
    setAmount(moneyField(txn.amount))
    setDate(txn.date)
    setPaymentMethod(txn.payment_method)
    setFee(moneyField(txn.fee))
    setShowId(txn.show_id ?? '')
    setNotes(txn.notes ?? '')
  }, [open, txn])

  if (!txn) return null

  const parsedAmount = parseMoney(amount)
  const parsedFee = parseMoney(fee)
  // `=== null`, never falsiness — a $0 fee or a $0 amount (a throw-in) is a
  // real, valid value, not a missing one.
  const invalid = parsedAmount === null || parsedFee === null

  const submit = () => {
    if (invalid) return
    const patch: TransactionEditPatch = {}
    if (parsedAmount !== (parseMoney(moneyField(txn.amount)) ?? null)) {
      patch.amount = parsedAmount!
    }
    if (date !== txn.date) patch.date = date
    if (paymentMethod !== txn.payment_method) patch.payment_method = paymentMethod
    if (parsedFee !== (parseMoney(moneyField(txn.fee)) ?? null)) {
      patch.fee = parsedFee!
    }
    if (showId !== (txn.show_id ?? '')) patch.show_id = showId || null
    if (notes !== (txn.notes ?? '')) patch.notes = notes || null
    if (Object.keys(patch).length === 0) {
      onClose()
      return
    }
    onSave(patch)
  }

  return (
    <ConfirmDialog
      open={open}
      title="Edit transaction"
      description="Corrects a typo in the ledger. This is not a void — the original date, batch grouping and timeline continuity are preserved."
      confirmLabel="Save"
      loading={loading}
      confirmDisabled={invalid}
      onConfirm={submit}
      onCancel={onClose}
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wider text-pine-400">Amount</span>
            <MoneyInput label="Amount" value={amount} onChange={setAmount} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wider text-pine-400">Fee</span>
            <MoneyInput label="Fee" value={fee} onChange={setFee} />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wider text-pine-400">Date</span>
            {/* A plain ISO string, bound directly — never routed through
                `new Date()` on a date-only string (CLAUDE.md's dates rule). */}
            <input
              type="date"
              aria-label="Date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wider text-pine-400">Payment method</span>
            <input
              aria-label="Payment method"
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
            />
          </label>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-pine-400">Show</span>
          <select
            aria-label="Show"
            value={showId}
            onChange={(e) => setShowId(e.target.value)}
            className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
          >
            <option value="">No show</option>
            {showOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-pine-400">Notes</span>
          <textarea
            aria-label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="vault-field w-full rounded-lg px-2.5 py-2 text-xs"
          />
        </label>

        {costBasisSkippedReason && (
          <p role="status" className="text-xs text-amber-300">
            The item&apos;s cost basis was not updated: {costBasisSkippedReason}.
          </p>
        )}
        {error && (
          <p role="alert" className="text-xs text-red-400">{error}</p>
        )}
      </div>
    </ConfirmDialog>
  )
}
