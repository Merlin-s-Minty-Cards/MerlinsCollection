import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

  it('saves the typed value on Enter', () => {
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
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSave).toHaveBeenCalledWith('20.00')
  })

  it('saves the typed value on blur', () => {
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
    fireEvent.blur(input)
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

    // Simulate the blur that browsers fire as part of Escape's focus loss —
    // it must not trigger a save after cancel.
    fireEvent.keyDown(reopenedInput, { key: 'Escape' })
    fireEvent.blur(reopenedInput)
    expect(onSave).not.toHaveBeenCalled()
  })
})
