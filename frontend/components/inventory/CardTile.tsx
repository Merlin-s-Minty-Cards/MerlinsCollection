import { CardPresentation } from './CardPresentation'
import {
  itemTitle,
  conditionLabel,
  isJapanese,
  type InventoryItem,
} from '@/lib/inventory'

/** A single inventory result in the steel results grid. */
export default function CardTile({ item }: { item: InventoryItem }) {
  const title = itemTitle(item)
  const marketPrice = item.kind === 'raw' ? item.card?.market_price : null
  const price = marketPrice ?? item.listed_price ?? 'Price N/A'

  return (
    <CardPresentation
      title={title}
      imageUrl={item.card?.image_small ?? undefined}
      setName={item.card?.set_name ?? 'Unknown set'}
      number={item.card?.number}
      conditionLabel={conditionLabel(item)}
      price={price}
      isJapanese={isJapanese(item)}
    />
  )
}
