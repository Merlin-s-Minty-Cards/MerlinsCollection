import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import DealStagedColumn from '../DealStagedColumn'
import type { DealRowCard } from '../DealCardRow'

/**
 * RFC 0024 T2 — `customerView` threaded into the staged columns, the same
 * prop and name `DealSearchPanel` and `DealCardRow` already carry. A staged
 * row keeps its REAL `marketValue`/`pricePaid` in state regardless of the
 * toggle (the operator can flip Customer View after cards are already
 * staged); the suppression happens here, at render time.
 */

function row(over: Partial<DealRowCard> = {}): DealRowCard {
  return {
    card_id: 'en:base1-4',
    name: 'Charizard',
    meta: 'Base Set · #4',
    imageUrl: 'https://i/1.png',
    price: '32.00',
    priceLabel: 'value',
    marketValue: '100.00',
    pricePaid: '32.00',
    ...over,
  }
}

describe('DealStagedColumn', () => {
  it('renders market and paid on a staged row by default', () => {
    render(
      <DealStagedColumn
        title="Coming In"
        testId="coming-in"
        accentClassName="text-mint"
        rows={[row()]}
        onRemove={vi.fn()}
        total={32}
        emptyLabel="empty"
      />,
    )
    expect(screen.getByText(/market\s*\$100\.00/i)).toBeInTheDocument()
    expect(screen.getByText(/paid\s*\$32\.00/i)).toBeInTheDocument()
    expect(screen.getByText('313%')).toBeInTheDocument()
  })

  it('hides paid and the ratio under customer view, keeps market', () => {
    render(
      <DealStagedColumn
        title="Coming In"
        testId="coming-in"
        accentClassName="text-mint"
        rows={[row()]}
        onRemove={vi.fn()}
        total={32}
        emptyLabel="empty"
        customerView
      />,
    )
    expect(screen.getByText(/market\s*\$100\.00/i)).toBeInTheDocument()
    expect(screen.queryByText(/paid/i)).not.toBeInTheDocument()
    expect(screen.queryByText('313%')).not.toBeInTheDocument()
  })

  it('still forces the headline price to null when a row is editable, customer view or not', () => {
    render(
      <DealStagedColumn
        title="Going Out"
        testId="going-out"
        accentClassName="text-red-400"
        rows={[row({ price: '32.00' })]}
        onRemove={vi.fn()}
        onEditValue={vi.fn()}
        total={32}
        emptyLabel="empty"
      />,
    )
    // The headline price is replaced by the trailing MoneyInput, so the
    // static price text is a dash — unrelated to the market/paid/ratio line.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
