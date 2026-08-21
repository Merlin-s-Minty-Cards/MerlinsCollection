'use client'

import { Plus } from 'lucide-react'
import CardImage, { TABLE_THUMB_SIZE } from '@/components/admin/shared/CardImage'
import { formatMoney } from '@/lib/money'

/**
 * The ONE row shape for a deal (RFC 0011 T14, §J).
 *
 * Search results, Coming In, Going Out and the confirm dialog all render this
 * component. That is the point: the owner's report was that identity is
 * inconsistent — an image behind a hover on `/admin/sell`, no image at all on
 * Trade's inventory picker, and nothing once a card was staged. Identity is
 * needed CONTINUOUSLY, not once at the moment of choosing: the operator builds
 * a five-card deal over several minutes and re-verifies every row against the
 * physical cards in their hand before confirming.
 *
 * **There is no hover behaviour of any kind carrying information.** Hover may
 * change a background colour. It may not reveal an image, a price, or a
 * control that is otherwise absent — a hover needs a mouse, shows exactly one
 * card when several are being compared, and shows nothing at all to someone
 * reading the list.
 */

export interface DealRowCard {
  /** `null` for a manual entry — it still gets a row, with the placeholder. */
  card_id?: string | null
  name: string
  /** `set · #number · rarity`, or an item's condition/location line. */
  meta?: string | null
  imageUrl?: string | null
  /**
   * A raw amount, NOT a formatted string. `null`/`undefined` means absent, and
   * absent renders as `—` — never `$0.00`, because a `FinishPrice` band is
   * written only when a provider actually published a figure.
   */
  price?: string | number | null
  /**
   * What the figure IS. A catalog price is a Near Mint market figure and is
   * not condition-adjusted, so it is labelled `market` and never presented as
   * a sale price.
   */
  priceLabel?: string
  /**
   * The staged consignor's display name, when this row is a staged incoming
   * leg with one attached (final-review Fix 5). `consignorId` alone used to
   * be carried on `StagedIncoming` with nothing rendered from it, so the
   * operator had no way to verify what they staged before Confirm.
   * `null`/`undefined` omits the line entirely rather than showing a blank one.
   */
  consignorLabel?: string | null
}

function priceText(value: DealRowCard['price']): string | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(n)) return null
  return formatMoney(n)
}

export default function DealCardRow({
  card,
  onAdd,
  actionIcon,
  actionVerb = 'Add',
  trailing,
}: {
  card: DealRowCard
  /** Omit on a read-only surface (the confirm dialog). No action, no button. */
  onAdd?: (card: DealRowCard) => void
  actionIcon?: React.ReactNode
  /** Leads the action's accessible name: "Add Charizard", never bare "Add". */
  actionVerb?: string
  /** A caller-supplied control at the end of the row (a remove button). */
  trailing?: React.ReactNode
}) {
  const money = priceText(card.price)

  return (
    <div
      data-testid="deal-card-row"
      className="flex w-full items-center gap-2.5 px-3 py-1.5 transition-colors hover:bg-pine-800/40"
    >
      {/* Imported, never re-picked: four admin pages each chose their own size
          and each rendered art wider than its own cell. A card-less or failed
          id renders the placeholder at the SAME height — a row that grows as
          art loads makes the list jump under the cursor mid-click. */}
      <CardImage
        imageUrl={card.imageUrl}
        alt={card.name}
        size={TABLE_THUMB_SIZE}
        placeholderTestId="card-image-placeholder"
      />

      {/* `min-w-0 flex-1` + `truncate`, so a long name shrinks instead of
          shoving the image out of its column. */}
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-pine-100">{card.name}</div>
        {card.meta && <div className="truncate text-[10px] text-pine-400">{card.meta}</div>}
        {card.consignorLabel && (
          <div className="truncate text-[10px] text-mint">Consignor: {card.consignorLabel}</div>
        )}
      </div>

      {/* Never shrinks and never truncates — a truncated price is worse than
          no price. Right-aligned: that is what the eye scans down a list. */}
      <div className="flex-shrink-0 text-right">
        {money === null ? (
          <span className="text-xs text-pine-500">—</span>
        ) : (
          <>
            <span className="block font-mono text-xs text-spriggatito-400">{money}</span>
            {card.priceLabel && (
              <span className="block text-[9px] uppercase tracking-wider text-pine-500">
                {card.priceLabel}
              </span>
            )}
          </>
        )}
      </div>

      {onAdd && (
        <button
          type="button"
          // Names the card, so a screen reader hears "Add Charizard".
          aria-label={`${actionVerb} ${card.name}`}
          onClick={() => onAdd(card)}
          className="flex-shrink-0 rounded-lg border border-mint/30 bg-mint/15 p-1.5 text-mint transition-colors hover:bg-mint/25"
        >
          {actionIcon ?? <Plus size={14} />}
        </button>
      )}
      {trailing && <div className="flex-shrink-0">{trailing}</div>}
    </div>
  )
}
