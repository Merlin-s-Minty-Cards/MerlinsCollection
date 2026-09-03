/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { buildIncomingLegBody, buildIncomingLeg, type IncomingLegDraft } from '../trade-incoming-form'

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

// RFC 0010 T1 — the leg's amounts are typed by a human, so parseFloat is banned
// here: parseFloat('1,300') is 1 and never NaN, so a $1,299 loss passes every
// isNaN guard downstream.
describe('buildIncomingLegBody money parsing', () => {
  it('parses a comma-grouped agreed value', () => {
    const body = buildIncomingLegBody(
      { name: 'Charizard', card_number: '', set_name: '', market_value: '', value: '1,300' },
      null,
    )
    expect(body.agreed_value).toBe(1300)
  })

  it('parses a comma-grouped market value', () => {
    const body = buildIncomingLegBody(
      { name: 'Charizard', card_number: '', set_name: '', market_value: '2,500.50', value: '1300' },
      null,
    )
    expect(body.market_value).toBe(2500.5)
  })

  it('omits an unreadable market value rather than sending a truncated one', () => {
    const body = buildIncomingLegBody(
      { name: 'Charizard', card_number: '', set_name: '', market_value: '1,30', value: '1300' },
      null,
    )
    expect(body.market_value).toBeUndefined()
  })
})

// final-review Important 7 — market_value and image_url were collected on
// the picker but never reached `POST /admin/trades/{id}/incoming`, which
// reads both. buildIncomingLeg is what the live form actually calls.
describe('buildIncomingLeg market_value/image_url (Important 7)', () => {
  const baseDraft: IncomingLegDraft = {
    card_id: 'en:base1-4',
    name: 'Charizard',
    agreed_value: 400,
    kind: 'raw',
    set_name: '',
    card_number: '',
    condition: 'NM',
    finish: 'normal',
    company: 'PSA',
    grade: '',
    cert_number: '',
    grade_label: '',
    language: 'EN',
    location: 'glass',
  }

  it('carries market_value and image_url through when the draft has them', () => {
    const leg = buildIncomingLeg({ ...baseDraft, market_value: 350, image_url: 'https://i/1.png' })
    expect(leg.market_value).toBe(350)
    expect(leg.image_url).toBe('https://i/1.png')
  })

  it('omits market_value and image_url when the draft is a manual entry with neither', () => {
    const leg = buildIncomingLeg({ ...baseDraft, card_id: null, market_value: null, image_url: undefined })
    expect(leg).not.toHaveProperty('market_value')
    expect(leg).not.toHaveProperty('image_url')
  })

  it('a zero market_value is sent, not treated as absent', () => {
    const leg = buildIncomingLeg({ ...baseDraft, market_value: 0 })
    expect(leg.market_value).toBe(0)
  })
})

// RFC 0023 T6 — finish_attributes threaded through the incoming-leg builder,
// same shape as set_name/card_number/image_url: sent only when non-empty.
describe('buildIncomingLeg finish_attributes (RFC 0023 T6)', () => {
  const baseDraft: IncomingLegDraft = {
    card_id: 'en:base1-4',
    name: 'Charizard',
    agreed_value: 400,
    kind: 'raw',
    set_name: '',
    card_number: '',
    condition: 'NM',
    finish: 'holofoil',
    company: 'PSA',
    grade: '',
    cert_number: '',
    grade_label: '',
    language: 'EN',
    location: 'glass',
  }

  it('carries finish_attributes through for a raw leg', () => {
    const leg = buildIncomingLeg({ ...baseDraft, finish_attributes: ['1st Edition', 'Shadowless'] })
    expect(leg.finish_attributes).toEqual(['1st Edition', 'Shadowless'])
  })

  it('omits finish_attributes when the draft has none', () => {
    const leg = buildIncomingLeg({ ...baseDraft, finish_attributes: [] })
    expect(leg).not.toHaveProperty('finish_attributes')
  })

  it('omits finish_attributes when the draft does not set it at all', () => {
    const leg = buildIncomingLeg(baseDraft)
    expect(leg).not.toHaveProperty('finish_attributes')
  })

  it('never appears on a graded leg — attributes are a raw-only concept', () => {
    const leg = buildIncomingLeg({
      ...baseDraft, kind: 'graded', finish_attributes: ['1st Edition'],
    })
    expect(leg).not.toHaveProperty('finish_attributes')
  })
})
