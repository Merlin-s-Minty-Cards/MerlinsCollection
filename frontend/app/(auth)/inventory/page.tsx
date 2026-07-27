import type { Metadata } from 'next'
import Container from '@/components/ui/Container'
import InventoryWorkspace from '@/components/inventory/InventoryWorkspace'
import InventoryStats from '@/components/inventory/InventoryStats'

export const metadata: Metadata = { title: 'Inventory Search' }

export default function InventoryPage() {
  return (
    <div className="vault-scope min-h-screen font-sans text-pine-200">
      <Container className="py-[clamp(36px,6vw,64px)]">
        <header className="relative overflow-hidden rounded-3xl vault-panel px-6 py-8 sm:px-9 sm:py-10">
          <div className="relative">
            <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint">
              Inventory · The vault
            </span>
            <h1 className="mt-3 max-w-[18ch] font-serif text-[clamp(30px,5vw,46px)] font-semibold leading-[1.05] tracking-[-0.01em] text-pine-100">
              Search the inventory
            </h1>
            <p className="mt-3 max-w-[52ch] text-pine-300">
              Query Merlin&apos;s full collection by set, rarity, type, and price — or just ask in
              plain English. Live pricing from the market.
            </p>

            <InventoryStats />
          </div>
        </header>

        <div className="mt-8">
          <InventoryWorkspace />
        </div>
      </Container>
    </div>
  )
}
