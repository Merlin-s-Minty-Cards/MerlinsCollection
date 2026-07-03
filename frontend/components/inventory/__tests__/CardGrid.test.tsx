import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'

import CardGrid from '@/components/inventory/CardGrid'
import type { InventoryItem } from '@/lib/inventory'

// Wire-format fixtures: Decimal fields are strings, catalog data under `card`.
const charizardNM: InventoryItem = {
  kind: 'raw',
  card_id: 'base1-4',
  quantity: 2,
  listed_price: '250.42',
  current_market_value: '300.00',
  acquired_at: '2026-04-01',
  finish: 'holofoil',
  condition: 'NM',
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
  card_id: 'base1-4',
  quantity: 1,
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
  card_id: 'sv1-orphan',
  quantity: 1,
  listed_price: '5.00',
  current_market_value: null,
  acquired_at: '2026-04-01',
  finish: 'normal',
  condition: 'LP',
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

  it('shows the quantity when more than one copy is in stock', () => {
    render(<CardGrid items={[charizardNM]} />)
    expect(screen.getByText(/×\s*2/)).toBeInTheDocument()
  })

  it('uses the card name for the image (or placeholder) accessible name', () => {
    render(<CardGrid items={[charizardNM]} />)
    expect(screen.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
  })
})
