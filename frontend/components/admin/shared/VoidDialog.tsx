'use client'

import { useEffect, useState } from 'react'
import ConfirmDialog from './ConfirmDialog'

/**
 * The confirm for withdrawing a transaction (RFC 0010 T11).
 *
 * A void, never a delete — so the REASON is not decoration, it is the thing
 * that makes a void better than a delete. The confirm cannot fire without one,
 * and the dialog stays open on failure with the server's message, because a
 * void that silently did not happen is the worst of the three outcomes.
 *
 * Shared by the transaction archive and the item timeline so the two cannot
 * drift into asking for different things.
 */
export default function VoidDialog({
  open,
  title,
  description,
  loading = false,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  description?: string
  loading?: boolean
  error?: string | null
  onConfirm: (reason: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')

  // Each opening starts from an empty box: carrying the previous reason over
  // is how the wrong explanation gets attached to the right correction.
  useEffect(() => {
    if (open) setReason('')
  }, [open])

  return (
    <ConfirmDialog
      open={open}
      title={title}
      description={description}
      confirmLabel="Void"
      variant="danger"
      loading={loading}
      confirmDisabled={!reason.trim()}
      onConfirm={() => onConfirm(reason.trim())}
      onCancel={onCancel}
    >
      <label className="block">
        <span className="text-[10px] uppercase tracking-wider text-pine-400">
          Reason (required)
        </span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder="Rang up the wrong card"
          className="vault-field mt-1 w-full rounded-lg px-2.5 py-2 text-xs"
        />
      </label>
      {error && (
        <p className="mt-2 text-xs text-red-400" role="alert">
          {error}
        </p>
      )}
    </ConfirmDialog>
  )
}
