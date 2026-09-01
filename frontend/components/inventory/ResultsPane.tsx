import { X } from 'lucide-react'
import { CARD_GRID_CLASS, CardPresentation } from './CardPresentation'
import type { PresentedCard } from '@/lib/inventory'

export interface ResultsView {
  /** e.g. "12 results" (filter mode) or "Display (3)" (chat mode). */
  headerLabel: string
  cards: PresentedCard[]
  status: 'idle' | 'loading' | 'error' | 'success'
  /** Shown when `cards` is empty — each mode supplies its own copy. */
  emptyMessage: string
  /** Shown above the grid when the caller truncated the result set. */
  truncatedNotice?: string
  /**
   * Chat mode only: clears the set of cards currently "pinned" for
   * conversation context (what round-trips as `panel_item_ids` on the next
   * turn) without resetting the conversation itself. Filter mode has no
   * equivalent concept — omitting this renders no control, since filter
   * results are already replaced by the next search.
   */
  onClear?: () => void
}

/**
 * The one persistent results grid shared by filter and chat mode (RFC 0019).
 * Purely presentational — driven entirely by props, no fetch logic of its
 * own, so either mode can push its own view into it without this component
 * knowing which mode produced it.
 */
export default function ResultsPane({
  headerLabel,
  cards,
  status,
  emptyMessage,
  truncatedNotice,
  onClear,
}: ResultsView) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-2xl vault-panel">
      {headerLabel && (
        <header className="flex items-center justify-between gap-4 border-b border-pine-700 p-4">
          <h2 className="font-serif text-lg font-semibold text-pine-100">{headerLabel}</h2>
          {onClear && (
            <button
              type="button"
              onClick={onClear}
              aria-label="Clear display"
              className="shrink-0 rounded-md p-2 text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
            >
              <X size={16} aria-hidden />
            </button>
          )}
        </header>
      )}

      {truncatedNotice && (
        <p className="border-b border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          {truncatedNotice}
        </p>
      )}

      <div className="vault-scroll min-h-0 flex-1 overflow-y-auto p-4">
        {status === 'loading' ? (
          <p className="py-10 text-center font-mono text-sm text-mint">Searching the vault…</p>
        ) : status === 'error' ? (
          <p className="py-10 text-center text-sm text-red-300">
            Something went wrong. Check your connection and try again.
          </p>
        ) : cards.length === 0 ? (
          <p className="py-10 text-center text-sm text-pine-300">{emptyMessage}</p>
        ) : (
          <div className={CARD_GRID_CLASS}>
            {cards.map((card) => (
              <CardPresentation
                key={card.key}
                title={card.title}
                imageUrl={card.imageUrl}
                setName={card.setName}
                number={card.number}
                conditionLabel={card.conditionLabel}
                price={card.price}
                isJapanese={card.isJapanese}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
