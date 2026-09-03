/**
 * RFC 0023 T5 — the `finish_attributes` column's render + multiselect edit.
 *
 * Split from `admin-inventory-columns.test.ts` for the same reason as
 * `admin-inventory-columns-tcgplayer.test.tsx`: this needs a real render,
 * cheaper as a direct column-level test than mounting the whole page.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { INVENTORY_COLUMNS, type ColumnRenderContext, type InventoryItem } from '@/lib/admin-inventory-columns'

const col = INVENTORY_COLUMNS.find((c) => c.key === 'finish_attributes')!

function makeCtx(overrides: Partial<ColumnRenderContext> = {}): ColumnRenderContext {
  return {
    editingId: null,
    editField: null,
    editValue: '',
    setEditValue: () => {},
    startEdit: () => {},
    saveEdit: () => {},
    cancelEdit: () => {},
    locationOptions: [],
    getImageUrl: () => null,
    onRefresh: () => {},
    onDelete: () => {},
    consignorName: () => undefined,
    ...overrides,
  }
}

function item(overrides: Partial<InventoryItem>): InventoryItem {
  return { item_id: 'item-1', kind: 'raw', status: 'available', ...overrides }
}

describe('the finish_attributes column render', () => {
  it('shows an em dash when no attributes are set', () => {
    render(<>{col.render(item({ finish_attributes: [] }), makeCtx())}</>)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('joins multiple attributes for display', () => {
    render(<>{col.render(item({ finish_attributes: ['1st Edition', 'Shadowless'] }), makeCtx())}</>)
    expect(screen.getByText('1st Edition, Shadowless')).toBeInTheDocument()
  })
})

describe('the finish_attributes column edit spec', () => {
  it('reads the stored array via multiselectValue', () => {
    const spec = col.edit!(makeCtx())
    expect(spec.type).toBe('multiselect')
    expect(spec.multiselectValue?.(item({ finish_attributes: ['Signed'] }))).toEqual(['Signed'])
    expect(spec.multiselectValue?.(item({}))).toEqual([])
  })

  it('offers the suggested chip vocabulary as options', () => {
    const spec = col.edit!(makeCtx())
    const values = (spec.options ?? []).map((o) => o.value)
    expect(values).toContain('1st Edition')
    expect(values).toContain('Full Art')
  })

  it('accepts free text alongside the suggested chips', () => {
    const spec = col.edit!(makeCtx())
    expect(spec.allowCustom).toBe(true)
  })

  it('saves the FULL updated array through ctx.saveField, not a joined string', async () => {
    const saveField = vi.fn().mockResolvedValue(undefined)
    const spec = col.edit!(makeCtx({ saveField }))
    await spec.saveMultiselect?.(item({ finish_attributes: ['Signed'] }), ['Signed', '1st Edition'])
    expect(saveField).toHaveBeenCalledWith(
      item({ finish_attributes: ['Signed'] }),
      'finish_attributes',
      ['Signed', '1st Edition'],
    )
  })
})
