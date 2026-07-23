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
  it('renders a tile per item with name, set, condition label and listed price', () => {
    render(<CardGrid items={[charizardNM, charizardPsa9]} />)
    expect(screen.getAllByText('Charizard')).toHaveLength(2)
    expect(screen.getAllByText('Base').length).toBeGreaterThan(0)
    expect(screen.getByText('NM')).toBeInTheDocument()
    expect(screen.getByText('PSA 9')).toBeInTheDocument()
    expect(screen.getByText('$250.42')).toBeInTheDocument()
    expect(screen.getByText('$900.00')).toBeInTheDocument()
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
})
