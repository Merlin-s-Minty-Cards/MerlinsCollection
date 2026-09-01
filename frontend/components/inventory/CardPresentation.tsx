import Image from 'next/image'
import { formatPrice } from '@/lib/inventory'

// Shared by DisplayPanel (both docked and fullscreen) and ChatPanel's inline
// artifact grid, so a card is the same size everywhere it renders — fixed
// 2026-08-25 after both surfaces shipped cards roughly 2x this size (a
// single inline chat card spanned most of the chat pane; the docked sidebar
// was a one-per-row vertical stack, not a grid at all). `auto-fill` +
// `minmax` rather than fixed `grid-cols-N` breakpoints: it's what makes the
// sidebar's card count respond automatically to its own resizable width
// instead of needing separate width-keyed breakpoints.
export const CARD_GRID_CLASS =
  'grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] items-start gap-3'

export interface CardPresentationProps {
  title: string
  imageUrl?: string
  setName: string
  number?: string
  conditionLabel: string
  price: number | string
  isJapanese?: boolean
}

function displayPrice(price: number | string): string {
  if (typeof price === 'number') return formatPrice(price)
  return price.trim() !== '' && Number.isFinite(Number(price)) ? formatPrice(price) : price
}

/** Shared inventory-card presentation used by filter and chat display surfaces. */
export function CardPresentation({
  title,
  imageUrl,
  setName,
  number,
  conditionLabel,
  price,
  isJapanese = false,
}: CardPresentationProps) {
  return (
    <article className="group overflow-hidden rounded-xl vault-panel transition-colors hover:border-mint/50">
      <div className="relative aspect-[245/342] bg-pine-950">
        {isJapanese && (
          <span
            className="absolute left-2 top-2 z-10 rounded-full bg-mint px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-pine-950"
            title="Japanese print"
          >
            JP
          </span>
        )}
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt={title}
            width={245}
            height={342}
            sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 220px"
            className="h-full w-full object-contain"
          />
        ) : (
          <div
            role="img"
            aria-label={title}
            className="flex h-full w-full items-center justify-center px-3 text-center text-xs font-semibold text-pine-400"
          >
            {title}
          </div>
        )}
      </div>

      <div className="space-y-2 p-3">
        <h3 className="truncate font-semibold text-pine-100" title={title}>
          {title}
        </h3>
        <div className="flex items-center justify-between gap-2 font-mono text-[12px] text-pine-300">
          <span className="truncate">{setName}</span>
          {number && <span className="shrink-0">#{number}</span>}
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <span className="truncate rounded-full border border-pine-600 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-pine-200">
            {conditionLabel}
          </span>
          <span className="shrink-0 font-mono text-sm font-semibold text-mint">
            {displayPrice(price)}
          </span>
        </div>
      </div>
    </article>
  )
}
