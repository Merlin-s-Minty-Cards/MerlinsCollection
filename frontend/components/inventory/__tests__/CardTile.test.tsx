import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import CardTile from '@/components/inventory/CardTile'
import type { InventoryItem } from '@/lib/inventory'

// T10 (docs/plans/rfc-0008/t10-jp-english-names.md): a Japanese card whose
// catalog row is in Japanese script gets an admin-authored English name. The
// name changing must NOT cost the customer the JP disclosure — a JP print is a
// different card at a different price, so "Chespin" without the badge would be
// actively misleading. Rendering the override and rendering the badge are two
// independent things and this pins them together.

const jpChespin: InventoryItem = {
  kind: 'raw',
  item_id: '01JRAWCHESPINJP000000000001',
  card_id: 'ja:M4-084',
  listed_price: '4.00',
  current_market_value: null,
  acquired_at: '2026-04-01',
  language: 'JP',
  finish: 'normal',
  condition: 'NM',
  condition_modifier: null,
  factory_sealed: false,
  display_name: 'Chespin #84',
  display_name_override: 'Chespin',
  card: {
    card_id: 'ja:M4-084',
    name: 'ハリマロン',
    set_id: 'ja:M4',
    set_name: 'メガシンカ',
    number: '84',
    rarity: 'Common',
    image_small: null,
    market_price: null,
  },
}

describe('CardTile', () => {
  it('shows the admin override instead of the Japanese catalog name', () => {
    render(<CardTile item={jpChespin} />)
    expect(screen.getByRole('heading', { name: 'Chespin' })).toBeInTheDocument()
    expect(screen.queryByText('ハリマロン')).toBeNull()
  })

  it('still marks the card as a Japanese print when an override is displayed', () => {
    render(<CardTile item={jpChespin} />)
    expect(screen.getByText('JP')).toBeInTheDocument()
  })

  it('uses the override as the placeholder image accessible name', () => {
    render(<CardTile item={jpChespin} />)
    expect(screen.getByRole('img', { name: 'Chespin' })).toBeInTheDocument()
  })

  it('leaves an English card with no override on its catalog name', () => {
    const enCharizard: InventoryItem = {
      ...jpChespin,
      item_id: '01JRAWCHARIZARDNM0000000001',
      language: 'EN',
      display_name: 'Charizard first #4',
      display_name_override: null,
      card: { ...jpChespin.card!, card_id: 'base1-4', name: 'Charizard' },
    }
    render(<CardTile item={enCharizard} />)
    expect(screen.getByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
    expect(screen.queryByText('JP')).toBeNull()
  })
})
