/**
 * RFC 0023 T7 — the `tcg_url` column's generated-search affordance.
 *
 * Split from `admin-inventory-columns.test.ts` (pure registry/persistence
 * logic, no rendering) because this behavior needs a real render: it's
 * about what `render()` actually produces for a given item, not the
 * registry's shape. A dedicated column-level render test is far cheaper
 * than mounting the whole `AdminInventoryPage` (which needs `/locations` and
 * `/inventory/search` mocks and a column-visibility dance just to make this
 * `defaultVisible: false` column appear) for behavior that belongs to the
 * column definition itself.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { INVENTORY_COLUMNS, type ColumnRenderContext, type InventoryItem } from '@/lib/admin-inventory-columns'
import { TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE } from '@/lib/tcgplayer'

const tcgColumn = INVENTORY_COLUMNS.find((c) => c.key === 'tcg_url')!

// Only `render` is exercised here; the stub context satisfies the type but
// none of its functions are expected to be called by this column.
const ctx: ColumnRenderContext = {
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
}

function item(overrides: Partial<InventoryItem>): InventoryItem {
  return { item_id: 'item-1', kind: 'raw', status: 'available', ...overrides }
}

describe('the tcg_url column', () => {
  it('offers a generated search link for an EN item with no stored tcg_url', () => {
    render(<>{tcgColumn.render(item({ language: 'EN', display_name: 'Charizard' }), ctx)}</>)
    const link = screen.getByRole('link', { name: /search tcgplayer/i })
    expect(link).toHaveAttribute('href', expect.stringContaining('tcgplayer.com/search/pokemon/product'))
  })

  it('offers the Japan-category link for a JP item', () => {
    render(<>{tcgColumn.render(item({ language: 'JP', display_name: 'Charizard' }), ctx)}</>)
    const link = screen.getByRole('link', { name: /search tcgplayer/i })
    expect(link).toHaveAttribute('href', expect.stringContaining('tcgplayer.com/search/pokemon-japan/product'))
  })

  it('shows the unsupported-language reason, not a link, for a language TCGplayer has no category for', () => {
    render(<>{tcgColumn.render(item({ language: 'KO', display_name: 'Some Card' }), ctx)}</>)
    expect(screen.queryByRole('link', { name: /search tcgplayer/i })).not.toBeInTheDocument()
    expect(screen.getByTitle(TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE)).toBeInTheDocument()
  })

  it('still shows the raw stored value as plain text, never as a clickable href (stored-XSS guard, unchanged)', () => {
    render(<>{tcgColumn.render(item({ language: 'EN', tcg_url: 'https://www.tcgplayer.com/product/12345' }), ctx)}</>)
    expect(screen.getByText('https://www.tcgplayer.com/product/12345')).toBeInTheDocument()
    // The raw value must not itself become the href of any link on this row —
    // only the generated (safe) search URL may.
    for (const link of screen.getAllByRole('link')) {
      expect(link).not.toHaveAttribute('href', 'https://www.tcgplayer.com/product/12345')
    }
  })
})
