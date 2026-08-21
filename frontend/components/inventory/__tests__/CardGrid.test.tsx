import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'

import CardGrid from '@/components/inventory/CardGrid'
import type { InventoryItem } from '@/lib/inventory'

// Wire-format fixtures (post Database-Redesign): each item has an `item_id`,
// `card_id` is optional, there is NO `quantity`, catalog data lives under `card`.
const charizardNM: InventoryItem = {
  kind: 'raw',
  item_id: '01JRAWCHARIZARDNM0000000001',
  card_id: 'base1-4',
  listed_price: '250.42',
  current_market_value: '300.00',
  acquired_at: '2026-04-01',
  finish: 'holofoil',
  condition: 'NM',
  condition_modifier: null,
  factory_sealed: false,
  card: {
    card_id: 'base1-4',
    name: 'Charizard',
    set_id: 'base1',
    set_name: 'Base',
    number: '4',
    rarity: 'Rare Holo',
    image_small: 'https://img/charizard.png',
    market_price: '260.00',
  },
}

const charizardPsa9: InventoryItem = {
  kind: 'graded',
  item_id: '01JGRADEDCHARIZARDPSA000001',
  card_id: 'base1-4',
  listed_price: '900.00',
  current_market_value: null,
  acquired_at: '2026-04-01',
  company: 'PSA',
  grade: '9',
  cert_number: '12345678',
  card: {
    card_id: 'base1-4',
    name: 'Charizard',
    set_id: 'base1',
    set_name: 'Base',
    number: '4',
    rarity: 'Rare Holo',
    image_small: 'https://img/charizard.png',
    // Graded slab: the catalog's ungraded market price must NOT be shown; the
    // tile keeps the slab's own listed price.
    market_price: '199.99',
  },
}

const orphan: InventoryItem = {
  kind: 'raw',
  item_id: '01JRAWORPHAN00000000000001',
  card_id: 'sv1-orphan',
  listed_price: '5.00',
  current_market_value: null,
  acquired_at: '2026-04-01',
  finish: 'normal',
  condition: 'LP',
  condition_modifier: null,
  factory_sealed: false,
  card: null,
}

const boosterBox: InventoryItem = {
  kind: 'sealed',
  item_id: '01JSEALEDBOOSTERBOX00000001',
  listed_price: '120.00',
  current_market_value: '140.00',
  acquired_at: '2026-04-01',
  product_name: 'Scarlet & Violet Booster Box',
  product_type: 'booster_box',
  card: null,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CardGrid', () => {
  it('shows market price for a raw card and keeps the listed price for a graded slab', () => {
    render(<CardGrid items={[charizardNM, charizardPsa9]} />)
    expect(screen.getAllByText('Charizard')).toHaveLength(2)
    expect(screen.getAllByText('Base').length).toBeGreaterThan(0)
    expect(screen.getByText('NM')).toBeInTheDocument()
    expect(screen.getByText('PSA 9')).toBeInTheDocument()
    // Raw single: pokemontcg.io market price replaces the sheet sticker ($250.42).
    expect(screen.getByText('$260.00')).toBeInTheDocument()
    expect(screen.queryByText('$250.42')).toBeNull()
    // Graded slab: the ungraded market figure is ignored; its own price stands.
    expect(screen.getByText('$900.00')).toBeInTheDocument()
    expect(screen.queryByText('$199.99')).toBeNull()
  })

  it('falls back to the sheet listed price when a raw card has no market price', () => {
    const noMarket: InventoryItem = {
      ...charizardNM,
      item_id: 'no-market-1',
      card: { ...charizardNM.card!, market_price: null },
    }
    render(<CardGrid items={[noMarket]} />)
    expect(screen.getByText('$250.42')).toBeInTheDocument()
  })

  it('keys duplicate card_ids uniquely (no React duplicate-key warning)', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<CardGrid items={[charizardNM, charizardPsa9]} />)

    const keyWarnings = consoleError.mock.calls.filter((args) =>
      String(args[0]).includes('same key'),
    )
    expect(keyWarnings).toHaveLength(0)
  })

  it('falls back to the card_id as title when there is no catalog data', () => {
    render(<CardGrid items={[orphan]} />)
    expect(screen.getByRole('heading', { name: 'sv1-orphan' })).toBeInTheDocument()
  })

  it('renders a sealed product with its product name, type badge and price', () => {
    render(<CardGrid items={[boosterBox]} />)
    expect(
      screen.getByRole('heading', { name: 'Scarlet & Violet Booster Box' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Booster Box')).toBeInTheDocument()
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('uses the card name for the image (or placeholder) accessible name', () => {
    render(<CardGrid items={[charizardNM]} />)
    expect(screen.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
  })

  it('marks a Japanese print with a JP indicator so it is distinguishable from its EN twin', () => {
    const jpCharizard: InventoryItem = { ...charizardNM, item_id: 'jp-1', language: 'JP' }
    render(<CardGrid items={[jpCharizard]} />)
    expect(screen.getByText('JP')).toBeInTheDocument()
  })

  it('does not show a JP indicator on an English (or unstamped) card', () => {
    // charizardNM carries no language field → treated as EN.
    render(<CardGrid items={[charizardNM]} />)
    expect(screen.queryByText('JP')).toBeNull()
  })
})
