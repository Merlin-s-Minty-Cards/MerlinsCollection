// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { sortRows } from '../client-table-sort'

interface Row {
  id: string
  amount: number | null
  label: string | null
}

const fields = {
  amount: (r: Row) => r.amount,
  label: (r: Row) => r.label,
}

function row(id: string, amount: number | null, label: string | null = null): Row {
  return { id, amount, label }
}

describe('sortRows', () => {
  it('sorts numerically ascending', () => {
    const result = sortRows(
      [row('a', 10), row('b', 1)],
      fields,
      'amount',
      'asc',
    )
    expect(result.map((r) => r.id)).toEqual(['b', 'a'])
  })

  it('sorts numerically descending', () => {
    const result = sortRows(
      [row('a', 1), row('b', 10)],
      fields,
      'amount',
      'desc',
    )
    expect(result.map((r) => r.id)).toEqual(['b', 'a'])
  })

  it('sorts text via localeCompare', () => {
    const result = sortRows(
      [row('a', null, 'zebra'), row('b', null, 'apple')],
      fields,
      'label',
      'asc',
    )
    expect(result.map((r) => r.id)).toEqual(['b', 'a'])
  })

  it('sorts missing values LAST ascending', () => {
    const result = sortRows(
      [row('none', null), row('has', 5)],
      fields,
      'amount',
      'asc',
    )
    expect(result.map((r) => r.id)).toEqual(['has', 'none'])
  })

  it('sorts missing values LAST descending too', () => {
    const result = sortRows(
      [row('none', null), row('has', 5)],
      fields,
      'amount',
      'desc',
    )
    expect(result.map((r) => r.id)).toEqual(['has', 'none'])
  })

  it('returns rows untouched when key is null', () => {
    const rows = [row('b', 1), row('a', 2)]
    expect(sortRows(rows, fields, null, 'asc')).toEqual(rows)
  })

  it('returns rows untouched when key has no extractor', () => {
    const rows = [row('b', 1), row('a', 2)]
    expect(sortRows(rows, fields, 'bogus', 'asc')).toEqual(rows)
  })

  it('does not mutate the input array', () => {
    const rows = [row('b', 10), row('a', 1)]
    const original = [...rows]
    sortRows(rows, fields, 'amount', 'asc')
    expect(rows).toEqual(original)
  })
})
