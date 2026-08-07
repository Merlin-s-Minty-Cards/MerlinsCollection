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
import { adminItemName } from '../admin-item-name'

describe('adminItemName', () => {
  it('lets the admin override beat the import-materialized display_name', () => {
    // The bug this exists for: an admin assigns "Chespin" to a Japanese card in
    // Triage and the admin panel keeps showing the Japanese name, which reads as
    // an edit that did not save.
    expect(
      adminItemName({ display_name_override: 'Chespin', display_name: 'ハリマロン #84' }),
    ).toBe('Chespin')
  })

  it('beats a sealed product_name too', () => {
    // Correcting what is written on a row is the whole point of the override;
    // no field outranks it.
    expect(
      adminItemName({ display_name_override: 'Japanese Booster Box', product_name: '拡張パック' }),
    ).toBe('Japanese Booster Box')
  })

  it('ignores a whitespace-only override rather than rendering a blank row', () => {
    expect(adminItemName({ display_name_override: '   ', display_name: 'Pikachu' })).toBe(
      'Pikachu',
    )
  })

  it('ignores an empty-string override', () => {
    // Clearing the box in the UI can send '' before the backend normalizes it.
    expect(adminItemName({ display_name_override: '', display_name: 'Pikachu' })).toBe('Pikachu')
  })

  it('falls back through display_name, product_name, name, then card_id', () => {
    expect(adminItemName({ display_name: 'A' })).toBe('A')
    expect(adminItemName({ product_name: 'B' })).toBe('B')
    expect(adminItemName({ name: 'C' })).toBe('C')
    expect(adminItemName({ card_id: 'sv1-4' })).toBe('sv1-4')
  })

  it('uses the fallback when the item has no name at all', () => {
    expect(adminItemName({})).toBe('(unnamed)')
    expect(adminItemName({}, 'this item')).toBe('this item')
  })

  it('tolerates a null or undefined item', () => {
    // Call sites pass optional state (`deleteTarget?`, `selectedItem?`) directly.
    expect(adminItemName(null)).toBe('(unnamed)')
    expect(adminItemName(undefined, 'this item')).toBe('this item')
  })
})
