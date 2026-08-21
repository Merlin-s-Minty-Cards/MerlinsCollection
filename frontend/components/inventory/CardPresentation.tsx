import Image from 'next/image'
import { formatPrice } from '@/lib/inventory'

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
