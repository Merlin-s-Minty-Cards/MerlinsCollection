'use client'

import { useEffect, useState } from 'react'
import { X, Undo2, RotateCcw } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import CardImage, { TABLE_THUMB_SIZE } from './CardImage'
import SignedAmount from './SignedAmount'
import type { ArchiveTransaction } from './TransactionGroups'

/**
 * The popup behind a bundled sale/purchase, showing what was actually bought
 * or sold. RFC/owner report: *"listed sales should have details of the cards
 * sold including image, name, and price... instead of an arrow to reveal the
 * individual sales, [let] users click on the bundled sale to view the
 * individual components... in a popup similar to how you would click on an
 * inventory item."*
 *
 * Replaces `TransactionGroups`' old inline chevron-expand, which rendered
 * only a raw `item_id` ULID per leg — no image, no name, in direct violation
 * of CLAUDE.md's "A CARD IS NEVER IDENTIFIED BY NAME ALONE" rule. The
 * transaction archive itself (`GET /admin/transactions`) never carried a
 * card_id or name — `Transaction` (models/business.py) has neither — so this
 * modal resolves both in ONE batched call to `POST /inventory/items-brief`
 * when it opens, keyed by the group's own `item_id`s (CLAUDE.md: "never fire
 * a request per row"). Price is NOT re-fetched: `leg.amount` is the
 * authoritative sold/bought figure the caller already has.
 */

interface ItemBrief {
  name: string | null
  card_id: string | null
}

export interface SaleDetailModalProps {
  /** The legs to show. `null` closes the modal. */
  rows: ArchiveTransaction[] | null
  onClose: () => void
  /** Per-leg void/restore — reuses the SAME confirm-dialog plumbing
   *  `TransactionGroups` already owns; this component only triggers it. */
  onVoidLeg?: (leg: ArchiveTransaction) => void
  onRestoreLeg?: (leg: ArchiveTransaction) => void
}

function isCountable(row: ArchiveTransaction): boolean {
  return row.voided_at == null
}

export default function SaleDetailModal({
  rows,
  onClose,
  onVoidLeg,
  onRestoreLeg,
}: SaleDetailModalProps) {
  const api = useAdminApi()
  const [briefs, setBriefs] = useState<Record<string, ItemBrief | null>>({})

  useEffect(() => {
    if (!rows || rows.length === 0) return
    let cancelled = false
    api
      .post<Record<string, ItemBrief | null>>('/inventory/items-brief', {
        item_ids: rows.map((r) => r.item_id),
      })
      .then((result) => {
        if (!cancelled) setBriefs(result ?? {})
      })
      .catch(() => {
        // Card identity is decoration on top of an already-informative row
        // (the item_id and amount still render) — a failed lookup falls
        // back to the raw id, the same "placeholder, never a crash" rule
        // useCardImages already follows.
        if (!cancelled) setBriefs({})
      })
    return () => {
      cancelled = true
    }
    // `rows` is a fresh array from the parent's group object every open —
    // comparing by reference is fine, it only changes when a different
    // group (or none) is selected.
  }, [rows, api])

  const cardIds = (rows ?? []).map((r) => briefs[r.item_id]?.card_id ?? null)
  const { getImageUrl } = useCardImages(cardIds)

  if (!rows) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Sale details"
    >
      <div
        className="relative w-full max-w-lg vault-panel rounded-2xl flex flex-col overflow-hidden border border-pine-700/50 shadow-2xl mx-4 max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-pine-700/40 bg-pine-900/95 backdrop-blur px-4 py-3">
          <h2 className="text-sm font-semibold text-pine-100">
            {rows.length} {rows.length === 1 ? 'card' : 'cards'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 rounded-md text-pine-400 hover:text-pine-200 hover:bg-pine-800 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <ul className="overflow-y-auto vault-scroll divide-y divide-pine-700/25">
          {rows.map((leg) => {
            const brief = briefs[leg.item_id]
            const voided = !isCountable(leg)
            return (
              <li
                key={leg.txn_id}
                className={`flex items-center gap-3 px-4 py-2.5 ${voided ? 'opacity-60' : ''}`}
              >
                <CardImage
                  imageUrl={brief ? getImageUrl(brief.card_id) : null}
                  alt={brief?.name || leg.item_id}
                  size={TABLE_THUMB_SIZE}
                />
                <div className="min-w-0 flex-1">
                  <p className={`truncate text-xs text-pine-100 ${voided ? 'line-through' : ''}`}>
                    {brief?.name || leg.item_id}
                  </p>
                  <SignedAmount value={leg.amount} type={leg.type} className="text-xs" />
                </div>
                {voided
                  ? onRestoreLeg && (
                    <button
                      type="button"
                      aria-label="Restore this card"
                      onClick={() => onRestoreLeg(leg)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-mint hover:bg-mint/10 transition-colors flex-shrink-0"
                    >
                      <RotateCcw size={11} /> Restore
                    </button>
                  )
                  : leg.type === 'sale' && onVoidLeg && (
                    <button
                      type="button"
                      aria-label="Void this card"
                      onClick={() => onVoidLeg(leg)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-red-400 hover:bg-red-500/10 transition-colors flex-shrink-0"
                    >
                      <Undo2 size={11} /> Void
                    </button>
                  )}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
