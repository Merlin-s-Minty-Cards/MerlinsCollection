import { describe, it, expect } from 'vitest'
import { buildIncomingLegBody } from '../trade-incoming-form'

describe('buildIncomingLegBody', () => {
  const baseForm = {
    name: 'Charizard',
    card_number: '4/102',
    set_name: 'Base Set',
    market_value: '150.00',
    value: '120.00',
  }

  it('omits card_id and image_url when no catalog card is selected', () => {
    const body = buildIncomingLegBody(baseForm, null)
    expect(body.card_id).toBeNull()
    expect(body.image_url).toBeUndefined()
  })

  it('attaches card_id and image_url from the selected catalog card', () => {
    const selectedCard = { card_id: 'base1-4', images: { small: 'https://example.com/small.webp' } }
    const body = buildIncomingLegBody(baseForm, selectedCard)
    expect(body.card_id).toBe('base1-4')
    expect(body.image_url).toBe('https://example.com/small.webp')
  })

  it('omits image_url when the selected card has no small image', () => {
    const selectedCard = { card_id: 'base1-4' }
    const body = buildIncomingLegBody(baseForm, selectedCard)
    expect(body.image_url).toBeUndefined()
  })

  it('trims name and passes through card_number, set_name, market_value, agreed_value', () => {
    const body = buildIncomingLegBody({ ...baseForm, name: '  Charizard  ' }, null)
    expect(body.name).toBe('Charizard')
    expect(body.card_number).toBe('4/102')
    expect(body.set_name).toBe('Base Set')
    expect(body.market_value).toBe(150)
    expect(body.agreed_value).toBe(120)
  })

  it('omits card_number, set_name, and market_value when blank', () => {
    const body = buildIncomingLegBody(
      { name: 'Mystery Card', card_number: '', set_name: '', market_value: '', value: '5.00' },
      null,
    )
    expect(body.card_number).toBeUndefined()
    expect(body.set_name).toBeUndefined()
    expect(body.market_value).toBeUndefined()
    expect(body.agreed_value).toBe(5)
  })
})
