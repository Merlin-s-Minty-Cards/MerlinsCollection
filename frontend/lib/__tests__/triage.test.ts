// @vitest-environment node
import { describe, it, expect } from 'vitest'
import {
  MACHINE_REASON_LABELS,
  parkBody,
  reasonsFor,
  reviewReasonLabel,
  unlinkBody,
  REASON_LABELS,
} from '@/lib/triage'

/**
 * RFC 0010 T3 — a machine key is not a sentence.
 *
 * `review_reason` is ONE column carrying two different things: a key from
 * `MACHINE_REVIEW_REASONS` written by automation, and free text an admin typed.
 * The chip rendered the column raw, so an imported row read `low_match_confidence`
 * — which tells the person holding the card nothing about what to do with it.
 *
 * Set membership is what separates the two, and it has to be exact: the bulk
 * clear keys off the same distinction on the server.
 */

describe('reviewReasonLabel', () => {
  it('turns every machine key into a sentence a person can act on', () => {
    for (const [key, label] of Object.entries(MACHINE_REASON_LABELS)) {
      expect(reviewReasonLabel(key)).toBe(label)
      // The label must actually be a label, not the key wearing a hat.
      expect(reviewReasonLabel(key)).not.toBe(key)
    }
  })

  it('covers every machine reason the backend can write', () => {
    // Mirrors MACHINE_REVIEW_REASONS (models/inventory.py). A key with no label
    // falls through to the raw-text branch and renders as a snake_case token,
    // which is the defect this map exists to remove.
    expect(Object.keys(MACHINE_REASON_LABELS).sort()).toEqual([
      'blank_condition',
      'cert_lookup_failed',
      'low_match_confidence',
      'manual_entry',
      'no_catalog_link',
    ])
  })

  it("passes an admin's own note through verbatim", () => {
    // The whole point of the free-text column. Rewriting or truncating what a
    // human deliberately recorded is worse than showing a machine key.
    expect(reviewReasonLabel('back looks trimmed')).toBe('back looks trimmed')
    expect(reviewReasonLabel('Wront Set should be 150a')).toBe('Wront Set should be 150a')
  })

  it('says nothing when there is no reason, rather than inventing one', () => {
    // 8 of the 27 live triage rows carry a bare flag with no reason at all —
    // written before the column existed and not backfillable. The chip falls
    // back to its generic label; it must not read "undefined".
    expect(reviewReasonLabel(null)).toBeNull()
    expect(reviewReasonLabel(undefined)).toBeNull()
    expect(reviewReasonLabel('   ')).toBeNull()
    expect(REASON_LABELS.flagged).toBe('Flagged for review')
  })
})


// ===========================================================================
// RFC 0011 T6 — unlink-and-park, and the park button
// ===========================================================================

describe('parkBody / unlinkBody', () => {
  it('park sends only the flag', () => {
    // `card_id` is deliberately absent: there is nothing to unlink on a row that
    // already has none, and sending `card_id: null` would be a meaningless write
    // on the one field that drives pricing, images and set membership.
    expect(parkBody()).toEqual({ no_catalog_match: true })
  })

  it('unlink clears the inherited promo price', () => {
    // The whole complaint: the card was pointed at a close-but-wrong promo, so
    // the figure it inherited is that promo's price and no sync will ever fix it
    // once the link is gone. A leftover wrong number on a customer-facing
    // surface is worse than no number.
    expect(unlinkBody()).toEqual({
      card_id: null, no_catalog_match: true, current_market_value: null,
    })
  })

  it('never sends a client-side timestamp', () => {
    // The server stamps no_catalog_match_at. A client clock is not ours to trust
    // — and T5's handler pops the key anyway, so sending it is dead weight that
    // reads like it works.
    expect(unlinkBody()).not.toHaveProperty('no_catalog_match_at')
    expect(parkBody()).not.toHaveProperty('no_catalog_match_at')
  })
})

describe('reasonsFor mirrors the server suppression', () => {
  it('drops missing_card_id once the item is parked', () => {
    expect(reasonsFor({
      item_id: 'x', kind: 'raw', card_id: null, no_catalog_match: true,
    })).toEqual([])
  })

  it('keeps a flag that is a real error', () => {
    // Parking answers ONE question. A human's flag is a different, real problem.
    expect(reasonsFor({
      item_id: 'x', kind: 'raw', card_id: null,
      no_catalog_match: true, needs_review: true,
    })).toEqual(['flagged'])
  })

  it('keeps missing_english_name on a parked JP card', () => {
    expect(reasonsFor({
      item_id: 'x', kind: 'raw', card_id: null, no_catalog_match: true,
      language: 'JP', display_name_override: null,
    })).toEqual(['missing_english_name'])
  })

  it('still reports missing_card_id on an unparked unlinked item', () => {
    expect(reasonsFor({ item_id: 'x', kind: 'raw', card_id: null }))
      .toEqual(['missing_card_id'])
  })
})
