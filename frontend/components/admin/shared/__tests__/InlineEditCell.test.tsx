import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import InlineEditCell from '../InlineEditCell'

describe('InlineEditCell', () => {
  it('renders the display value and a pencil affordance when not editing', () => {
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={vi.fn()}
      />
    )
    expect(screen.getByText('$12.50')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('shows an input of the given type when clicked into edit mode', () => {
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton') as HTMLInputElement
    expect(input).toBeInTheDocument()
    expect(input.type).toBe('number')
    expect(input.step).toBe('0.01')
    expect(input.value).toBe('12.50')
  })

  it('renders a url input when type is url', () => {
    render(
      <InlineEditCell
        value="https://example.com"
        type="url"
        displayValue={<span>link</span>}
        onSave={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText('link'))
    const input = screen.getByDisplayValue('https://example.com') as HTMLInputElement
    expect(input.type).toBe('url')
  })

  it('saves the typed value on Enter', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '20.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('20.00')
  })

  it('saves the typed value on blur', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '20.00' } })
    await act(async () => {
      fireEvent.blur(input)
    })
    expect(onSave).toHaveBeenCalledWith('20.00')
  })

  it('cancels on Escape, restores original value, and does not also fire blur-save', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton') as HTMLInputElement
    fireEvent.change(input, { target: { value: '99.00' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    // Escape should exit edit mode back to display value without saving
    expect(screen.getByText('$12.50')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()

    // Re-enter edit mode to confirm the value was restored, not left as '99.00'
    fireEvent.click(screen.getByText('$12.50'))
    const reopenedInput = screen.getByRole('spinbutton') as HTMLInputElement
    expect(reopenedInput.value).toBe('12.50')
  })

  it('does not call onSave when the value is unchanged (dirty-check)', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton')
    // No change — just reading the value, then clicking/tabbing away.
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSave).not.toHaveBeenCalled()
    // Still exits edit mode back to the display value.
    expect(screen.getByText('$12.50')).toBeInTheDocument()
  })

  it('keeps the editor open and forwards the error to onError when onSave rejects', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('save failed'))
    const onError = vi.fn()
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
        onError={onError}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '20.00' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1))
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error)
    // Editor stays open with the rejected draft still visible — no silent revert.
    expect(screen.getByRole('spinbutton')).toBeInTheDocument()
    expect((screen.getByRole('spinbutton') as HTMLInputElement).value).toBe('20.00')
    expect(screen.queryByText('$12.50')).not.toBeInTheDocument()
  })

  it('exits edit mode once an async onSave resolves', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    const input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '20.00' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSave).toHaveBeenCalledWith('20.00')
    await waitFor(() => expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument())
  })

  it('renders a prefix adornment inside the input when provided', () => {
    render(
      <InlineEditCell
        value="12.50"
        type="number"
        displayValue={<span>$12.50</span>}
        onSave={vi.fn()}
        prefix="$"
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    expect(screen.getByText('$', { selector: 'span' })).toBeInTheDocument()
  })
})

// RFC 0010 T1. `type="money"` is the inline-edit counterpart of MoneyInput:
// a text input that accepts what a human types (`1,300`) and commits the
// parsed value, instead of a number input the comma never reaches.
describe('InlineEditCell type="money"', () => {
  const renderMoneyCell = (onSave = vi.fn(), onError?: (e: unknown) => void) => {
    render(
      <InlineEditCell
        value="12.50"
        type="money"
        displayValue={<span>$12.50</span>}
        onSave={onSave}
        onError={onError}
      />
    )
    fireEvent.click(screen.getByText('$12.50'))
    return { onSave, input: screen.getByRole('textbox') as HTMLInputElement }
  }

  it('edits through a text input carrying the decimal keypad hint, not a number input', () => {
    const { input } = renderMoneyCell()
    // type="number" is what makes `1,300` un-typeable; inputMode is the only
    // thing it was buying that matters, and it must survive the swap.
    expect(input.type).toBe('text')
    expect(input.inputMode).toBe('decimal')
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('commits a comma-grouped amount as its parsed value', async () => {
    const { onSave, input } = renderMoneyCell()
    fireEvent.change(input, { target: { value: '1,300' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('1300')
  })

  it('still commits a plain amount unchanged (regression gate)', async () => {
    const { onSave, input } = renderMoneyCell()
    fireEvent.change(input, { target: { value: '9.99' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('9.99')
  })

  it('never calls onSave with an unreadable amount, and keeps the editor open', async () => {
    const onSave = vi.fn()
    const onError = vi.fn()
    const { input } = renderMoneyCell(onSave, onError)
    fireEvent.change(input, { target: { value: '1,30' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledTimes(1)
    // The editor stays open with the offending text intact, exactly as it does
    // when onSave rejects — the admin fixes it rather than losing it.
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('1,30')
  })

  it('commits an empty value as empty, so clearing a price still works', async () => {
    const { onSave, input } = renderMoneyCell()
    fireEvent.change(input, { target: { value: '' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('')
  })

  it('commits a zero amount — a free card is a real thing at a buy table', async () => {
    const { onSave, input } = renderMoneyCell()
    fireEvent.change(input, { target: { value: '0' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('0')
  })
})
