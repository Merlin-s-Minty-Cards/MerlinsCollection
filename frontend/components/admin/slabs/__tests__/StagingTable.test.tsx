import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StagingTable from '../StagingTable'
import type { StagedSlab } from '../SlabEntryForm'

function row(over: Partial<StagedSlab> = {}): StagedSlab {
  return {
    key: 'k1', cert_number: '89787279', card_id: 'en:swsh8-271', name: 'Gengar VMAX',
    company: 'PSA', grade: '9.5', grade_label: 'MINT 9.5', buy_price: 900.5,
    location: 'toploader', ...over,
  }
}

describe('StagingTable', () => {
  it('renders one row per staged slab with cert, card, grade and cost', () => {
    render(<StagingTable rows={[row()]} onRemove={vi.fn()} />)
    expect(screen.getByText('89787279')).toBeInTheDocument()
    expect(screen.getByText('Gengar VMAX')).toBeInTheDocument()
    expect(screen.getByText(/9\.5/)).toBeInTheDocument()
    // Scoped to the row: with a single slab staged, the batch total carries the
    // same amount, so an unscoped query matches twice.
    expect(screen.getByRole('row', { name: /89787279/ })).toHaveTextContent('$900.50')
  })

  it('marks a row with no catalog link so the operator knows it lands in Triage', () => {
    render(<StagingTable rows={[row({ card_id: null })]} onRemove={vi.fn()} />)
    expect(screen.getByText(/no catalog link/i)).toBeInTheDocument()
  })

  it('removes a row by key', () => {
    const onRemove = vi.fn()
    render(<StagingTable rows={[row()]} onRemove={onRemove} />)
    fireEvent.click(screen.getByRole('button', { name: /remove/i }))
    expect(onRemove).toHaveBeenCalledWith('k1')
  })

  it('renders nothing but an empty note when there are no rows', () => {
    render(<StagingTable rows={[]} onRemove={vi.fn()} />)
    expect(screen.getByText(/nothing staged/i)).toBeInTheDocument()
  })

  // ---- RFC 0010 T0 ---------------------------------------------------------
  // The staging table used to render the raw typed string, so "1,300" displayed
  // as a perfectly correct-looking $1,300 while NaN was on its way to the
  // server. Rendering the PARSED number is what makes the batch inspectable,
  // and the total is the signal that would have exposed it before commit.

  it('renders the parsed amount, so a mistyped cost cannot look correct', () => {
    render(<StagingTable rows={[row({ buy_price: 1300 })]} onRemove={vi.fn()} />)
    expect(screen.getByRole('row', { name: /89787279/ })).toHaveTextContent('$1,300.00')
  })

  it('totals the batch', () => {
    render(
      <StagingTable
        rows={[
          row({ key: 'a', cert_number: '1', buy_price: 1300 }),
          row({ key: 'b', cert_number: '2', buy_price: 40.5 }),
        ]}
        onRemove={vi.fn()}
      />,
    )
    expect(screen.getByRole('row', { name: /batch total/i })).toHaveTextContent('$1,340.50')
  })

  // RFC 0010 T12 — the consequence, at the point of decision
  it('says an unlinked row will not be priced automatically, not just that it is unlinked', () => {
    render(<StagingTable rows={[row({ card_id: null })]} onRemove={() => {}} />)
    expect(screen.getByText(/will not be priced automatically/i)).toBeInTheDocument()
  })
})
