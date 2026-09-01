import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DealSummary, { type DealSummaryProps } from '../DealSummary'

/**
 * RFC 0011 T15, final-review Important 4 — a cash-component amount input
 * that re-derives its value from the parsed number every render loses a
 * decimal point or comma mid-keystroke, because the parent immediately
 * reflows the field back to the last successfully parsed integer.
 */

function props(over: Partial<DealSummaryProps> = {}): DealSummaryProps {
  return {
    mode: 'trade',
    showProfit: true,
    customerView: false,
    cashComponents: [{ direction: 'they_pay', amount: 0, payment_method: 'cash' }],
    onCashComponentsChange: vi.fn(),
    balance: 0,
    profit: 0,
    date: '2026-08-14',
    onDateChange: vi.fn(),
    counterparty: '',
    onCounterpartyChange: vi.fn(),
    onConfirm: vi.fn(),
    confirmDisabled: false,
    ...over,
  }
}

describe('DealSummary cash amount input', () => {
  it('keeps a typed decimal point across keystrokes instead of reflowing to an integer', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealSummary {...props()} />)

    const input = screen.getByLabelText(/cash amount 1/i)
    await user.clear(input)
    await user.type(input, '1.50')

    expect(input).toHaveValue('1.50')
  })

  it('keeps a typed comma across keystrokes instead of blanking the field', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealSummary {...props()} />)

    const input = screen.getByLabelText(/cash amount 1/i)
    await user.clear(input)
    await user.type(input, '1,300')

    expect(input).toHaveValue('1,300')
  })

  it('commits the parsed amount to onCashComponentsChange as the draft resolves', async () => {
    const user = userEvent.setup({ delay: null })
    const onCashComponentsChange = vi.fn()
    render(<DealSummary {...props({ onCashComponentsChange })} />)

    const input = screen.getByLabelText(/cash amount 1/i)
    await user.clear(input)
    await user.type(input, '1300')

    expect(onCashComponentsChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ amount: 1300 }),
    ])
  })
})

describe('DealSummary cost basis mode', () => {
  it('never renders a cost basis mode picker, in any mode', () => {
    render(<DealSummary {...props({ mode: 'trade' })} />)
    expect(screen.queryByText(/cost basis mode/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^transfer$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^split$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^manual$/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/total cost basis/i)).not.toBeInTheDocument()
  })
})

describe('DealSummary payment method visibility', () => {
  // Exact label, not a regex: a staged cash component also carries its own
  // "Payment method N" select (the rail that ONE cash leg settles on), which
  // is a different control from the single deal-wide select this describes.
  it('shows the payment method select for buy and sell', () => {
    render(<DealSummary {...props({ mode: 'buy', onPaymentMethodChange: vi.fn() })} />)
    expect(screen.getByLabelText('Payment method')).toBeInTheDocument()
  })

  it('hides the payment method select for trade — it uses cash components instead', () => {
    render(<DealSummary {...props({ mode: 'trade', onPaymentMethodChange: vi.fn() })} />)
    expect(screen.queryByLabelText('Payment method')).not.toBeInTheDocument()
  })
})
