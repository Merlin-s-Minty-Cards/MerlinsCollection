'use client'

import { useState } from 'react'
import { Flag, FlagOff, Undo2 } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import {
  clearTriageBody,
  effectiveName,
  quickFlagBody,
  type TriageItem,
} from '@/lib/triage'

interface TriageRowActionProps {
  item: TriageItem
  /** Called after a write lands so the page can refresh its rows. */
  onChanged?: () => void
}

/**
 * One-click "this card is wrong" for a table row.
 *
 * Lives on the list-heavy pages (Inventory, Prep Queue) where spotting a bad
 * card mid-workflow is the actual use case — opening the detail modal per card
 * just to flag it defeats the point. The modal's slower path is where a note
 * gets typed; this one is deliberately note-less.
 *
 * Undo is not optional: a misclick on a row action is inevitable, and without
 * it the admin has to open the modal to fix a mistake the row made.
 */
export default function TriageRowAction({ item, onChanged }: TriageRowActionProps) {
  const api = useAdminApi()
  const [flagged, setFlagged] = useState(Boolean(item.needs_review))
  const [showUndo, setShowUndo] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const name = effectiveName(item)

  // The row itself is clickable (it opens the detail modal), so every handler
  // here has to stop the event before it reaches the row.
  //
  // `refetch` is deliberately FALSE on the flag path. The parent's refetch puts
  // its table into a loading state, which unmounts this row — and the undo
  // toast lives here, so refetching on flag makes the toast flash and vanish
  // before it can be clicked. The row already shows its own new state, so the
  // only cost of skipping the refetch is that a row filtered out by an active
  // `needs_review` filter lingers until the next natural fetch. A working undo
  // is worth more than a filter self-correcting one render sooner.
  const write = async (
    e: React.MouseEvent,
    body: Record<string, unknown>,
    nextFlagged: boolean,
    { undoable, refetch }: { undoable: boolean; refetch: boolean },
  ) => {
    e.stopPropagation()
    setBusy(true)
    setFailed(false)
    try {
      await api.put(`/inventory/${item.item_id}`, body)
      setFlagged(nextFlagged)
      setShowUndo(undoable)
      if (refetch) onChanged?.()
    } catch {
      // Without this a failed write is indistinguishable from a click that
      // never registered, and the admin moves on thinking the card is flagged.
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {flagged ? (
        <button
          type="button"
          disabled={busy}
          onClick={(e) => write(e, clearTriageBody(), false, { undoable: false, refetch: true })}
          aria-label={`Clear ${name} from Triage`}
          title="In Triage — click to clear"
          className="p-1 rounded text-amber-400 hover:text-amber-300 disabled:opacity-50"
        >
          <FlagOff size={13} />
        </button>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={(e) => write(e, quickFlagBody(), true, { undoable: true, refetch: false })}
          aria-label={`Send ${name} to Triage`}
          title="Send to Triage"
          className="p-1 rounded text-pine-600 hover:text-amber-400 disabled:opacity-50"
        >
          <Flag size={13} />
        </button>
      )}

      {failed && (
        <span role="alert" className="ml-1 text-[10px] text-red-400">
          Not saved
        </span>
      )}

      {showUndo && (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3
                     rounded-lg border border-amber-400/30 bg-pine-900/95 px-4 py-2
                     text-xs text-pine-100 shadow-xl"
        >
          <span>Sent to Triage</span>
          <button
            type="button"
            disabled={busy}
            onClick={(e) => write(e, clearTriageBody(), false, { undoable: false, refetch: true })}
            className="flex items-center gap-1 text-mint hover:text-mint/80 disabled:opacity-50"
          >
            <Undo2 size={12} /> Undo
          </button>
        </div>
      )}
    </>
  )
}
