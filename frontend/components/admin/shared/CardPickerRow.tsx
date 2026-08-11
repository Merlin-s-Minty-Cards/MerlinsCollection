'use client'

import CardImage, { TABLE_THUMB_SIZE } from './CardImage'
import PriceDisplay from './PriceDisplay'

/**
 * One candidate row in a card picker: name, image AND price.
 *
 * This is CLAUDE.md's standing rule ("A CARD IS NEVER IDENTIFIED BY NAME
 * ALONE") expressed as a component, so it cannot rot back out. Pokemon names
 * collide relentlessly across sets, printings, finishes and languages, so a
 * list of names is a list of things the operator cannot tell apart — and they
 * are standing at a table holding the physical card. The image answers "is
 * this the card?"; the price answers "what do I do about it?".
 *
 * There is ONE definition and five callers (Buy, Trade, Triage's two repair
 * dialogs, Slabs, Market). It is a component rather than a documented pattern
 * because three of those five were built FROM Buy's row and dropped the image
 * on the way.
 *
 * Both fields arrive in `GET /admin/market/search` already — `images.small`
 * inline and `display_price`/`display_finish` computed server-side by the one
 * shared finish-aware lookup. Do not add a second request, and do not resolve
 * art through `useCardImages` (that hook is for inventory items by `card_id`).
 */

export interface PickerCard {
  card_id: string
  name: string
  set_id?: string
  set_name?: string
  number?: string
  rarity?: string
  // `small?: string | null` rather than an optional whole object, so a card
  // shape declared here stays assignable to the narrower ones already in
  // `lib/` (e.g. trade-incoming-form's `IncomingCatalogCard`).
  images?: { small?: string | null; large?: string | null }
  /** Chosen SERVER-side by `_market_price(card, "normal")`. Never recomputed here. */
  display_price?: string | number | null
  display_finish?: string | null
  /** `brief` = never fetched. `full` with no price = no provider covers it. */
  detail?: string | null
  last_synced_at?: string | null
}

/**
 * Past this, a figure is shown with its age. A price from six days ago is
 * fine; a three-month-old one is a different claim and must not look identical.
 * Eight days clears the weekly re-price cycle (RFC 0010 T17) with a day of slack.
 */
const STALE_DAYS = 8

function ageInDays(iso?: string | null): number | null {
  if (!iso) return null
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return null
  return Math.floor((Date.now() - then) / 86_400_000)
}

/**
 * The price column's contents.
 *
 * The ABSENT cases are the main cases, not the edges: most of the 31,603
 * catalog rows carry no price until T17's weekly cycle reaches them. An absent
 * price is never `$0.00` and never a blank cell — `FinishPrice` bands are
 * written only when a provider actually published a figure, so absent means
 * absent. And "we never fetched one" is a different fact from "no provider
 * covers this card": only the second one means waiting will not help, which is
 * the whole reason `detail` exists.
 */
function PriceColumn({ card }: { card: PickerCard }) {
  const price = card.display_price
  if (price === null || price === undefined || price === '') {
    // A missing `detail` is treated as `brief`, matching the model's own default.
    const covered = card.detail === 'full'
    return (
      <span className="text-[10px] text-pine-500">
        {covered ? 'not priced' : 'no price yet'}
      </span>
    )
  }

  const age = ageInDays(card.last_synced_at)
  return (
    <>
      <PriceDisplay value={price} className="text-xs text-spriggatito-400" />
      {/* A holofoil figure quoted against a normal card is the kind of
          mismatch that costs money, so the finish is named whenever it is not
          the default one the lookup asked for. */}
      {card.display_finish && card.display_finish !== 'normal' && (
        <span className="block text-[9px] text-pine-500">{card.display_finish}</span>
      )}
      {age !== null && age >= STALE_DAYS && (
        <span className="block text-[9px] text-amber-400/80">{age}d ago</span>
      )}
    </>
  )
}

// Generic in the card type so `onSelect` hands each caller back its OWN card
// shape. Every page carries a slightly wider `CatalogCard` (Buy reads `prices`
// off it, Market keeps an index signature), and without this they would all
// have to cast the callback argument back to the type they just passed in.
export default function CardPickerRow<T extends PickerCard>({
  card,
  onSelect,
  action,
  nameBadge,
  selected,
}: {
  card: T
  /** Clicking the row picks the card. Omit when `action` is the only affordance. */
  onSelect?: (card: T) => void
  /**
   * A caller-supplied control rendered at the end of the row. Triage's name
   * dialog ("Use this name") and Market's watchlist star need a DIFFERENT
   * action from a row click on the same row shape — and Market needs both,
   * which is why they are siblings rather than one nested inside the other.
   */
  action?: React.ReactNode
  /** Rendered inline after the name. Market's name-match confidence chip. */
  nameBadge?: React.ReactNode
  selected?: boolean
}) {
  const meta = [
    card.set_name || card.set_id,
    card.number && `#${card.number}`,
    card.rarity,
  ].filter(Boolean).join(' · ')

  const body = (
    <>
      {/* Never a hand-picked size, and never a bare <img>. A card-less or
          failed id renders the placeholder at the SAME size — rows that change
          height as art loads make the list jump under the cursor mid-click,
          which on a picker means selecting the wrong card. */}
      <CardImage imageUrl={card.images?.small} alt={card.name} size={TABLE_THUMB_SIZE} />
      <div data-testid="card-picker-text" className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-xs text-pine-100">{card.name}</span>
          {nameBadge}
        </div>
        <div className="truncate text-[10px] text-pine-400">{meta}</div>
        {/* Tertiary, but present: it is how a re-point is verified. */}
        <div className="truncate font-mono text-[10px] text-pine-500">{card.card_id}</div>
      </div>
      {/* The price column NEVER shrinks and never truncates — a truncated
          price is worse than no price. Right-aligned in its own column
          because that is what the eye scans down a list of candidates. */}
      <div data-testid="card-picker-price" className="flex-shrink-0 text-right">
        <PriceColumn card={card} />
      </div>
    </>
  )

  return (
    <div
      data-testid="card-picker-row"
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 ${
        selected ? 'bg-pine-800/60' : ''
      }`}
    >
      {onSelect ? (
        <button
          type="button"
          onClick={() => onSelect(card)}
          className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md py-1 text-left transition-colors hover:bg-pine-800/60"
        >
          {body}
        </button>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2.5">{body}</div>
      )}
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  )
}
