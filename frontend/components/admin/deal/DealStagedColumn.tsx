'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { formatMoney, formatMoneyInput, parseMoney } from '@/lib/money'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import DealCardRow, { type DealRowCard } from './DealCardRow'

/**
 * One staged column — Coming In or Going Out (RFC 0011 T15).
 *
 * Both columns render the SAME `DealCardRow` search results, staged legs and
 * the confirm dialog already use (T14, §J): identity is needed continuously,
 * not once at the moment of picking. A hidden column is not rendered here at
 * all — the page omits the whole component rather than passing it an empty
 * array, because an empty pane labelled "Going Out" in Buy mode reads as
 * broken (RFC 0011 §I).
 */

export interface DealStagedColumnProps {
  title: string
  /** `coming-in` / `going-out` — what the page's own tests key off of. */
  testId: string
  accentClassName: string
  rows: DealRowCard[]
  onRemove: (index: number) => void
  total: number
  emptyLabel: string
  /**
   * When provided, the price column becomes an editable `MoneyInput` instead
   * of static text — Going Out's default value is a picked item's market
   * price, and the operator negotiates from there. Coming In's value is
   * already set by `IncomingCardForm` before the row exists, so it stays
   * read-only.
   */
  onEditValue?: (index: number, raw: string, parsed: number | null) => void
}

export default function DealStagedColumn({
  title,
  testId,
  accentClassName,
  rows,
  onRemove,
  total,
  emptyLabel,
  onEditValue,
}: DealStagedColumnProps) {
  // The MoneyInput owns its text while typing, keyed by row index — a
  // half-typed "5" or "50." must not be discarded just because it does not
  // parse yet. The commit to `onEditValue` happens on blur, mirroring the old
  // trade page's `outDrafts` map.
  const [drafts, setDrafts] = useState<Record<number, string>>({})

  return (
    <div className="space-y-3" data-testid={testId}>
      <h3 className={`text-xs font-semibold uppercase tracking-wider ${accentClassName}`}>
        {title} ({rows.length})
      </h3>
      <div className="vault-panel rounded-xl overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-4 text-center text-xs text-pine-500">{emptyLabel}</div>
        ) : (
          <div className="divide-y divide-pine-700/25">
            {rows.map((row, idx) => (
              <DealCardRow
                key={idx}
                card={onEditValue ? { ...row, price: null } : row}
                trailing={
                  <div className="flex items-center gap-2">
                    {onEditValue && (
                      <MoneyInput
                        label={`Outgoing value for ${row.name}`}
                        value={
                          drafts[idx] ??
                          formatMoneyInput(
                            typeof row.price === 'number'
                              ? row.price
                              : parseMoney(String(row.price ?? '0')) ?? 0,
                          )
                        }
                        onChange={(raw) => setDrafts((d) => ({ ...d, [idx]: raw }))}
                        onBlur={() => {
                          const draft = drafts[idx]
                          if (draft === undefined) return
                          const parsed = parseMoney(draft)
                          if (parsed !== null) onEditValue(idx, draft, parsed)
                          setDrafts((d) => {
                            const next = { ...d }
                            delete next[idx]
                            return next
                          })
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        className="vault-field w-20 px-1.5 py-0.5 rounded text-xs text-right font-mono text-red-400"
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => onRemove(idx)}
                      aria-label={`Remove ${row.name}`}
                      className="p-1 text-pine-500 hover:text-red-400"
                    >
                      <X size={12} />
                    </button>
                  </div>
                }
              />
            ))}
          </div>
        )}
        <div className="px-3 py-2 border-t border-pine-700/30 text-right text-xs text-pine-400">
          Total: <span className={`font-mono ${accentClassName}`}>{formatMoney(total)}</span>
        </div>
      </div>
    </div>
  )
}
