import { describe, it, expect } from 'vitest'
import { sortVaultItems } from '../vault-sort'

describe('sortVaultItems', () => {
  it('sorts numeric string values ascending ("9.50" before "10.00")', () => {
    const items = [
      { item_id: 'a', cost_basis: '10.00' },
      { item_id: 'b', cost_basis: '9.50' },
    ]
    const sorted = sortVaultItems(items, 'cost_basis', 'asc')
    expect(sorted.map((i) => i.item_id)).toEqual(['b', 'a'])
  })

  it('sorts numeric string values descending', () => {
    const items = [
      { item_id: 'a', cost_basis: '10.00' },
      { item_id: 'b', cost_basis: '9.50' },
    ]
    const sorted = sortVaultItems(items, 'cost_basis', 'desc')
    expect(sorted.map((i) => i.item_id)).toEqual(['a', 'b'])
  })

  it('sorts null/NaN values last in ascending order', () => {
    const items = [
      { item_id: 'a', percent_net: null },
      { item_id: 'b', percent_net: '40.0' },
      { item_id: 'c', percent_net: '-10.0' },
    ]
    const sorted = sortVaultItems(items, 'percent_net', 'asc')
    expect(sorted.map((i) => i.item_id)).toEqual(['c', 'b', 'a'])
  })

  it('sorts null/NaN values last in descending order too (never jumps to the top)', () => {
    const items = [
      { item_id: 'a', percent_net: null },
      { item_id: 'b', percent_net: '40.0' },
      { item_id: 'c', percent_net: '-10.0' },
    ]
    const sorted = sortVaultItems(items, 'percent_net', 'desc')
    expect(sorted.map((i) => i.item_id)).toEqual(['b', 'c', 'a'])
  })

  it('orders NM before LP+ before LP by condition tier', () => {
    const items = [
      { item_id: 'a', condition: 'LP' },
      { item_id: 'b', condition: 'NM' },
      { item_id: 'c', condition: 'LP+' },
    ]
    const sorted = sortVaultItems(items, 'condition', 'asc')
    expect(sorted.map((i) => i.item_id)).toEqual(['b', 'c', 'a'])
  })

  it('handles two-field condition + condition_modifier storage', () => {
    const items = [
      { item_id: 'a', condition: 'LP', condition_modifier: null },
      { item_id: 'b', condition: 'NM', condition_modifier: null },
      { item_id: 'c', condition: 'LP', condition_modifier: '+' },
    ]
    const sorted = sortVaultItems(items, 'condition', 'asc')
    expect(sorted.map((i) => i.item_id)).toEqual(['b', 'c', 'a'])
  })

  it('reverses condition order for desc', () => {
    const items = [
      { item_id: 'a', condition: 'LP' },
      { item_id: 'b', condition: 'NM' },
      { item_id: 'c', condition: 'LP+' },
    ]
    const sorted = sortVaultItems(items, 'condition', 'desc')
    expect(sorted.map((i) => i.item_id)).toEqual(['a', 'c', 'b'])
  })

  it('sorts unrecognized condition values last regardless of direction', () => {
    const items = [
      { item_id: 'a', condition: 'UNKNOWN' },
      { item_id: 'b', condition: 'NM' },
    ]
    expect(sortVaultItems(items, 'condition', 'asc').map((i) => i.item_id)).toEqual(['b', 'a'])
    expect(sortVaultItems(items, 'condition', 'desc').map((i) => i.item_id)).toEqual(['b', 'a'])
  })

  it('falls back to localeCompare for non-numeric string columns', () => {
    const items = [
      { item_id: 'a', name: 'Pikachu' },
      { item_id: 'b', name: 'Charizard' },
    ]
    const sorted = sortVaultItems(items, 'name', 'asc')
    expect(sorted.map((i) => i.item_id)).toEqual(['b', 'a'])
  })

  it('does not mutate the original array', () => {
    const items = [
      { item_id: 'a', cost_basis: '10.00' },
      { item_id: 'b', cost_basis: '9.50' },
    ]
    const original = [...items]
    sortVaultItems(items, 'cost_basis', 'asc')
    expect(items).toEqual(original)
  })
})
