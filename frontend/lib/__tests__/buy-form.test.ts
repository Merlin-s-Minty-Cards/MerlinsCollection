import { describe, it, expect } from 'vitest'
import { buyFormMode, buildBuyItemBody } from '../buy-form'

describe('buyFormMode', () => {
  it('returns "search" when no card is selected and manualMode is false', () => {
    expect(buyFormMode(null, false)).toBe('search')
  })

  it('returns "search" when selectedCard is undefined and manualMode is false', () => {
    expect(buyFormMode(undefined, false)).toBe('search')
  })

  it('returns "catalog" when a card object is selected', () => {
    const card = { card_id: 'abc-123', name: 'Pikachu' }
    expect(buyFormMode(card, false)).toBe('catalog')
  })

  it('returns "catalog" when a card is selected even if manualMode is true', () => {
    // catalog selection takes precedence over manual flag
    const card = { card_id: 'abc-123', name: 'Pikachu' }
    expect(buyFormMode(card, true)).toBe('catalog')
  })

  it('returns "manual" when manualMode is true and no card is selected', () => {
    expect(buyFormMode(null, true)).toBe('manual')
  })
})

describe('buildBuyItemBody', () => {
  const baseForm: Record<string, unknown> = {
    name: 'Charizard',
    condition: 'NM',
    buy_price: '42.00',
    market_value: '60.00',
    set_name: 'Base Set',
    location: 'toploader',
    card_number: '4/102',
    buy_pct: '70',
  }

  it('includes card_id from the selected card and manual_entry: false', () => {
    const selectedCard = { card_id: 'card-xyz' }
    const body = buildBuyItemBody(baseForm, selectedCard, false)
    expect(body.card_id).toBe('card-xyz')
    expect(body.manual_entry).toBe(false)
  })

  it('sets card_id: null and manual_entry: true in manual mode without a card', () => {
    const body = buildBuyItemBody(baseForm, null, true)
    expect(body.card_id).toBeNull()
    expect(body.manual_entry).toBe(true)
  })

  it('sets manual_entry: false when a catalog card is chosen even if manualMode is true', () => {
    const selectedCard = { card_id: 'card-xyz' }
    const body = buildBuyItemBody(baseForm, selectedCard, true)
    expect(body.card_id).toBe('card-xyz')
    expect(body.manual_entry).toBe(false)
  })

  it('sets card_id: null and manual_entry: false when no card and not manual', () => {
    const body = buildBuyItemBody(baseForm, null, false)
    expect(body.card_id).toBeNull()
    expect(body.manual_entry).toBe(false)
  })

  it('passes through form fields in the body', () => {
    const selectedCard = { card_id: 'card-xyz' }
    const body = buildBuyItemBody(baseForm, selectedCard, false)
    expect(body.name).toBe('Charizard')
    expect(body.condition).toBe('NM')
    expect(body.buy_price).toBe('42.00')
    expect(body.market_value).toBe('60.00')
    expect(body.set_name).toBe('Base Set')
    expect(body.location).toBe('toploader')
    expect(body.card_number).toBe('4/102')
  })
})
