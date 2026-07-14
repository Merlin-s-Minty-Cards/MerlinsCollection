import CardTile from './CardTile'
import { itemKey, type InventoryItem } from '@/lib/inventory'

/** Responsive grid of inventory result tiles. */
export default function CardGrid({ items }: { items: InventoryItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {items.map((item) => (
        // card_id alone repeats across finishes/conditions/slabs of one card
        <CardTile key={itemKey(item)} item={item} />
      ))}
    </div>
  )
}
