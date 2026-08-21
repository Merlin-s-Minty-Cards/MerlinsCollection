import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PriceDisplay from '../PriceDisplay'

/**
 * Follow-up #7 (RFC 0011) — `parseFloat` reads "1,300.00" as `1`, not `NaN`,
 * so a comma-grouped string used to render as "$1.00" instead of failing
 * loudly. `parseMoney` is the required parser for anything money-shaped
 * (CLAUDE.md: "Never use parseFloat on money").
 */
describe('PriceDisplay', () => {
  it('formats a plain numeric string', () => {
    render(<PriceDisplay value="120.00" />)
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('formats a number value', () => {
    render(<PriceDisplay value={120} />)
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('does not misread a comma-grouped string as $1.00', () => {
    // parseFloat("1,300.00") is 1, not NaN — it would have rendered "$1.00"
    // silently instead of the correct $1300.00 or a dash.
    render(<PriceDisplay value="1,300.00" />)
    expect(screen.getByText('$1300.00')).toBeInTheDocument()
    expect(screen.queryByText('$1.00')).not.toBeInTheDocument()
  })

  it('shows a dash for an unreadable string rather than a wrong number', () => {
    render(<PriceDisplay value="not a price" />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows a dash for null', () => {
    render(<PriceDisplay value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows a dash for undefined', () => {
    render(<PriceDisplay value={undefined} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('compacts a comma-grouped string over 1000 correctly', () => {
    render(<PriceDisplay value="1,300.00" compact />)
    expect(screen.getByText('$1.3k')).toBeInTheDocument()
  })
})
