'use client'

import { useEffect, useState } from 'react'
import { Maximize2, Minimize2, X } from 'lucide-react'
import { CardPresentation } from './CardPresentation'
import type { DisplayedCard } from '@/lib/inventory'

type PanelMode = 'docked' | 'fullscreen'

function cardTitle(card: DisplayedCard): string {
  return card.display_name || card.card?.name || 'Unknown card'
}

function cardCondition(card: DisplayedCard): string {
  if (card.condition) return card.condition
  if (card.kind === 'graded') {
    if (card.grade_label) return card.grade_label
    const slabGrade = [card.company, card.grade].filter(Boolean).join(' ')
    if (slabGrade) return slabGrade
  }
  // kind is narrowed to 'raw' | 'graded' (RFC-0016 Council r2): a 'sealed'
  // branch here was dead code, since a DisplayedCard can never carry that
  // kind (see DisplayedCard.kind's docstring in models/chat.py).
  return 'N/A'
}

export function DisplayPanel({
  cards,
  truncated,
  onClose,
}: {
  cards: DisplayedCard[]
  truncated: boolean
  onClose: () => void
}) {
  const [mode, setMode] = useState<PanelMode>('docked')

  // Decision 23: no `open` prop. Open/closed is inferred purely from whether
  // `cards` is non-empty — reset to docked whenever the panel closes (goes to
  // empty) so a later reopen doesn't inherit a stale fullscreen mode.
  useEffect(() => {
    if (cards.length === 0) setMode('docked')
  }, [cards.length])

  if (cards.length === 0) return null

  const containerClass =
    mode === 'fullscreen'
      ? 'fixed inset-0 z-50 overflow-hidden bg-pine-950'
      : 'fixed right-0 top-0 z-40 h-screen w-[400px] max-w-[40vw] overflow-hidden border-l border-pine-700 bg-pine-900 shadow-2xl'

  return (
    <aside
      aria-label="Card display panel"
      className={`hidden lg:block ${containerClass}`}
      data-panel-mode={mode}
    >
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-pine-700 p-4">
          <h2 className="font-serif text-lg font-semibold text-pine-100">
            Display ({cards.length}{truncated ? '+' : ''})
          </h2>
          <div className="flex shrink-0 gap-1">
            {mode === 'docked' ? (
              <button
                type="button"
                onClick={() => setMode('fullscreen')}
                className="rounded-md p-2 text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
                aria-label="Fullscreen"
              >
                <Maximize2 size={18} aria-hidden />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setMode('docked')}
                className="rounded-md p-2 text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
                aria-label="Dock"
              >
                <Minimize2 size={18} aria-hidden />
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-2 text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
              aria-label="Close"
            >
              <X size={18} aria-hidden />
            </button>
          </div>
        </header>

        {truncated && (
          <p className="border-b border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
            The panel is limited to 50 cards. Some results are not shown.
          </p>
        )}

        <div
          className={
            mode === 'fullscreen'
              ? 'vault-scroll grid min-h-0 flex-1 grid-cols-2 gap-4 overflow-y-auto p-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5'
              : 'vault-scroll min-h-0 flex-1 space-y-4 overflow-y-auto p-4'
          }
        >
          {cards.length === 0 ? (
            <p className="py-12 text-center text-sm text-pine-300">
              No cards in the display yet.
            </p>
          ) : (
            cards.map((card) => (
              <CardPresentation
                key={card.item_id}
                title={cardTitle(card)}
                imageUrl={card.card?.image_small || undefined}
                setName={card.card?.set_name ?? 'Unknown set'}
                number={card.card?.number}
                conditionLabel={cardCondition(card)}
                // listed_price is the RESOLVED, condition-adjusted price
                // (mirrors routers/inventory.py::_display_price); it must
                // win over current_market_value, a separate, potentially
                // stale pass-through (RFC-0016 Council r2 self-review).
                price={card.listed_price ?? card.current_market_value ?? 'Price N/A'}
                isJapanese={card.language === 'JP'}
              />
            ))
          )}
        </div>
      </div>
    </aside>
  )
}
