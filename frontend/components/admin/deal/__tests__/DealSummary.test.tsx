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
    supportsCostBasisMode: true,
    showProfit: true,
    customerView: false,
    cashComponents: [{ direction: 'they_pay', amount: 0, payment_method: 'cash' }],
    onCashComponentsChange: vi.fn(),
    balance: 0,
    profit: 0,
    basisMode: 'transfer',
    onBasisModeChange: vi.fn(),
    manualBasis: '',
    onManualBasisChange: vi.fn(),
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
