import Image from 'next/image'
import {
  formatPrice,
  itemTitle,
  conditionLabel,
  type InventoryItem,
} from '@/lib/inventory'

/** A single inventory result in the steel results grid. */
export default function CardTile({ item }: { item: InventoryItem }) {
  const title = itemTitle(item)
  const image = item.card?.image_small

  return (
    <article className="group overflow-hidden rounded-xl vault-panel transition-colors hover:border-mint/50">
      <div className="relative aspect-[245/342] bg-pine-950">
        {image ? (
          <Image
            src={image}
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
          <span className="truncate">{item.card?.set_name ?? 'Unknown set'}</span>
          {item.card && <span className="shrink-0">#{item.card.number}</span>}
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <span className="rounded-full border border-pine-600 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-pine-200">
            {conditionLabel(item)}
          </span>
          <span className="flex items-baseline gap-2">
            {item.quantity > 1 && (
              <span className="font-mono text-[11px] text-pine-300">×{item.quantity}</span>
            )}
            <span className="font-mono text-sm font-semibold text-mint">
              {formatPrice(item.listed_price)}
            </span>
          </span>
        </div>
      </div>
    </article>
  )
}
