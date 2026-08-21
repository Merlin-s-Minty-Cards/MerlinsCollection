/**
 * RFC 0010 T9 — a sale reads +$40, a purchase reads −$200.
 *
 * Owner report: *"In Show analytics, there needs to be a +/- for sales and buys.
 * i.e., sold is +$ and buying a card is -$."* `Transaction.amount` is stored
 * UNSIGNED with direction carried by `type`, so a $200 purchase and a $200 sale
 * were visually identical in a column headed "Amount".
 *
 * This is a presentation change only. Nothing here inverts a stored sign.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SignedAmount from '../SignedAmount'

describe('SignedAmount', () => {
  it('renders a sale with a leading +', () => {
    render(<SignedAmount value="40.00" type="sale" />)
    expect(screen.getByTestId('signed-amount')).toHaveTextContent('+$40.00')
  })

  it('renders a purchase with a leading minus', () => {
    render(<SignedAmount value="200.00" type="purchase" />)
    // U+2212, not a hyphen — it aligns in the monospace column this table sets.
    expect(screen.getByTestId('signed-amount')).toHaveTextContent('−$200.00')
  })

  it('renders an unknown type with no sign at all', () => {
    // The archive is deliberately raw and may carry a type this component has
    // not been taught. Guessing a direction on a money figure is worse than
    // showing none.
    render(<SignedAmount value="40.00" type="adjustment" />)
    const el = screen.getByTestId('signed-amount')
    expect(el).toHaveTextContent('$40.00')
    expect(el.textContent).not.toMatch(/[+−-]/)
  })

  it('puts the sign in the TEXT, not only in a class', () => {
    // Colour alone is not an accessible carrier of meaning, and the owner reads
    // these on a phone in show lighting.
    const { container } = render(<SignedAmount value="200.00" type="purchase" />)
    expect(container.textContent).toBe('−$200.00')
  })

  it('gives a sale and a purchase different colour classes', () => {
    const { unmount } = render(<SignedAmount value="40.00" type="sale" />)
    const saleClass = screen.getByTestId('signed-amount').className
    unmount()
    render(<SignedAmount value="40.00" type="purchase" />)
    const purchaseClass = screen.getByTestId('signed-amount').className
    expect(saleClass).not.toBe(purchaseClass)
  })

  it('renders zero without a misleading sign', () => {
    render(<SignedAmount value="0.00" type="sale" />)
    const el = screen.getByTestId('signed-amount')
    expect(el).toHaveTextContent('$0.00')
    expect(el.textContent).not.toMatch(/[+−-]/)
  })

  it('renders an absent amount as the usual em-dash, unsigned', () => {
    render(<SignedAmount value={null} type="purchase" />)
    expect(screen.getByTestId('signed-amount')).toHaveTextContent('—')
    expect(screen.getByTestId('signed-amount').textContent).not.toContain('−$')
  })

  it('takes the direction from the number itself when told to (a net total)', () => {
    // `Net Sales` is a genuinely signed figure and can go either way on a
    // buying-heavy day. It has no transaction type to key on.
    render(<SignedAmount value="-160.00" fromValue />)
    expect(screen.getByTestId('signed-amount')).toHaveTextContent('−$160.00')
  })

  it('renders a positive net total with a + and no double sign', () => {
    render(<SignedAmount value="160.00" fromValue />)
    expect(screen.getByTestId('signed-amount').textContent).toBe('+$160.00')
  })
})
