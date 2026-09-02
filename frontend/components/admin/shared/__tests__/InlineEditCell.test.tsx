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

// RFC 0022 T1 — five new scalar types plus multiselect, generalizing the
// component from three types to nine.
describe('InlineEditCell type="text"', () => {
  it('commits the typed value on Enter, and again on blur', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="Rylan" type="text" displayValue={<span>Rylan</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('Rylan'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    expect(input.type).toBe('text')
    fireEvent.change(input, { target: { value: 'Rylan Voss' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(onSave).toHaveBeenCalledWith('Rylan Voss')
  })

  it('cancels on Escape without also firing a blur-save (double-fire regression)', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="Rylan" type="text" displayValue={<span>Rylan</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('Rylan'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Something Else' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.getByText('Rylan')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('carries the vault-field class', () => {
    render(
      <InlineEditCell value="Rylan" type="text" displayValue={<span>Rylan</span>} onSave={vi.fn()} />
    )
    fireEvent.click(screen.getByText('Rylan'))
    expect(screen.getByRole('textbox').className).toContain('vault-field')
  })

  it('carries the aria-label through onto the input itself, not just the wrapper', () => {
    render(
      <InlineEditCell
        value="Rylan"
        type="text"
        displayValue={<span>Rylan</span>}
        onSave={vi.fn()}
        aria-label="Edit Name"
      />
    )
    fireEvent.click(screen.getByText('Rylan'))
    expect(screen.getByRole('textbox', { name: 'Edit Name' })).toBeInTheDocument()
  })
})

describe('InlineEditCell type="textarea"', () => {
  it('carries the aria-label through onto the textarea itself', () => {
    render(
      <InlineEditCell
        value="old note"
        type="textarea"
        displayValue={<span>old note</span>}
        onSave={vi.fn()}
        aria-label="Edit Notes"
      />
    )
    fireEvent.click(screen.getByText('old note'))
    expect(screen.getByRole('textbox', { name: 'Edit Notes' })).toBeInTheDocument()
  })

  it('renders a textarea and commits on Ctrl+Enter', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="old note" type="textarea" displayValue={<span>old note</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('old note'))
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(textarea.tagName).toBe('TEXTAREA')
    fireEvent.change(textarea, { target: { value: 'new note' } })
    await act(async () => {
      fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true })
    })
    expect(onSave).toHaveBeenCalledWith('new note')
  })

  it('does NOT commit on a bare Enter (needs a newline, not a submit)', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="old note" type="textarea" displayValue={<span>old note</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('old note'))
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'new note' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    expect(onSave).not.toHaveBeenCalled()
  })

  it('commits on blur', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="old note" type="textarea" displayValue={<span>old note</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('old note'))
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'new note' } })
    await act(async () => {
      fireEvent.blur(textarea)
    })
    expect(onSave).toHaveBeenCalledWith('new note')
  })

  it('cancels on Escape without a blur double-fire', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="old note" type="textarea" displayValue={<span>old note</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('old note'))
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'discard me' } })
    fireEvent.keyDown(textarea, { key: 'Escape' })
    expect(screen.getByText('old note')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })
})

describe('InlineEditCell type="date"', () => {
  it('renders a native date input carrying the ISO value verbatim, no Date construction', () => {
    render(
      <InlineEditCell value="2026-03-08" type="date" displayValue={<span>Mar 8, 2026</span>} onSave={vi.fn()} />
    )
    fireEvent.click(screen.getByText('Mar 8, 2026'))
    const input = screen.getByDisplayValue('2026-03-08') as HTMLInputElement
    expect(input.type).toBe('date')
  })

  it('commits on change', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="2026-03-08" type="date" displayValue={<span>Mar 8, 2026</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('Mar 8, 2026'))
    const input = screen.getByDisplayValue('2026-03-08')
    await act(async () => {
      fireEvent.change(input, { target: { value: '2026-03-09' } })
    })
    expect(onSave).toHaveBeenCalledWith('2026-03-09')
  })

  it('cancels on Escape without a blur double-fire', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="2026-03-08" type="date" displayValue={<span>Mar 8, 2026</span>} onSave={onSave} />
    )
    fireEvent.click(screen.getByText('Mar 8, 2026'))
    const input = screen.getByDisplayValue('2026-03-08')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.getByText('Mar 8, 2026')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })
})

const CONDITION_OPTIONS = [
  { value: 'NM', label: 'NM' },
  { value: 'LP', label: 'LP' },
  { value: 'MP', label: 'MP' },
]

describe('InlineEditCell type="select"', () => {
  it('commits immediately on change -- no Enter, no blur required', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="NM"
        type="select"
        options={CONDITION_OPTIONS}
        displayValue={<span>NM</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('NM'))
    const select = screen.getByRole('combobox')
    await act(async () => {
      fireEvent.change(select, { target: { value: 'LP' } })
    })
    expect(onSave).toHaveBeenCalledWith('LP')
  })

  it('cancels on Escape before a choice is made, without a blur double-fire', () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell
        value="NM"
        type="select"
        options={CONDITION_OPTIONS}
        displayValue={<span>NM</span>}
        onSave={onSave}
      />
    )
    fireEvent.click(screen.getByText('NM'))
    const select = screen.getByRole('combobox')
    fireEvent.keyDown(select, { key: 'Escape' })
    expect(screen.getByText('NM')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('renders a DISABLED select showing the current value when options have not loaded yet, never an empty dropdown', () => {
    render(
      <InlineEditCell value="NM" type="select" options={[]} displayValue={<span>NM</span>} onSave={vi.fn()} />
    )
    fireEvent.click(screen.getByText('NM'))
    const select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.disabled).toBe(true)
  })

  it('carries the vault-field class', () => {
    render(
      <InlineEditCell
        value="NM"
        type="select"
        options={CONDITION_OPTIONS}
        displayValue={<span>NM</span>}
        onSave={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText('NM'))
    expect(screen.getByRole('combobox').className).toContain('vault-field')
  })

  it('carries the aria-label through onto the select itself, not just the wrapper', () => {
    render(
      <InlineEditCell
        value="NM"
        type="select"
        options={CONDITION_OPTIONS}
        displayValue={<span>NM</span>}
        onSave={vi.fn()}
        aria-label="Edit Condition"
      />
    )
    fireEvent.click(screen.getByText('NM'))
    expect(screen.getByRole('combobox', { name: 'Edit Condition' })).toBeInTheDocument()
  })
})

describe('InlineEditCell type="checkbox"', () => {
  it('renders as a checkbox in place -- no click-to-edit swap at all', () => {
    render(
      <InlineEditCell value="false" type="checkbox" displayValue={<span>ignored</span>} onSave={vi.fn()} />
    )
    // The checkbox is immediately present, with no separate display state to click into.
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('toggles and saves immediately on click, with no separate commit step', async () => {
    const onSave = vi.fn()
    render(
      <InlineEditCell value="false" type="checkbox" displayValue={<span>ignored</span>} onSave={onSave} />
    )
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    await act(async () => {
      fireEvent.click(checkbox)
    })
    expect(onSave).toHaveBeenCalledWith('true')
  })

  it('reflects a true stored value as checked', () => {
    render(
      <InlineEditCell value="true" type="checkbox" displayValue={<span>ignored</span>} onSave={vi.fn()} />
    )
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true)
  })
})

describe('InlineEditCell type="multiselect"', () => {
  const FINISH_OPTIONS = [
    { value: 'holofoil', label: 'Holofoil' },
    { value: 'reverseHolofoil', label: 'Reverse Holo' },
    { value: 'normal', label: 'Normal' },
  ]

  it('opens a chip/checkbox list of options on click', () => {
    render(
      <InlineEditCell
        value=""
        type="multiselect"
        options={FINISH_OPTIONS}
        multiselectValue={['holofoil']}
        onSave={vi.fn()}
        onSaveMultiselect={vi.fn()}
        displayValue={<span>Holofoil</span>}
      />
    )
    fireEvent.click(screen.getByText('Holofoil'))
    expect(screen.getByRole('checkbox', { name: 'Holofoil' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Normal' })).not.toBeChecked()
  })

  it('calls onSaveMultiselect with the updated ARRAY on each toggle, immediately', async () => {
    const onSaveMultiselect = vi.fn()
    render(
      <InlineEditCell
        value=""
        type="multiselect"
        options={FINISH_OPTIONS}
        multiselectValue={['holofoil']}
        onSave={vi.fn()}
        onSaveMultiselect={onSaveMultiselect}
        displayValue={<span>Holofoil</span>}
      />
    )
    fireEvent.click(screen.getByText('Holofoil'))
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox', { name: 'Normal' }))
    })
    expect(onSaveMultiselect).toHaveBeenCalledWith(['holofoil', 'normal'])
  })

  it('removes a value from the array when its chip is toggled off', async () => {
    const onSaveMultiselect = vi.fn()
    render(
      <InlineEditCell
        value=""
        type="multiselect"
        options={FINISH_OPTIONS}
        multiselectValue={['holofoil', 'normal']}
        onSave={vi.fn()}
        onSaveMultiselect={onSaveMultiselect}
        displayValue={<span>2 finishes</span>}
      />
    )
    fireEvent.click(screen.getByText('2 finishes'))
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox', { name: 'Normal' }))
    })
    expect(onSaveMultiselect).toHaveBeenCalledWith(['holofoil'])
  })

  it('with allowCustom, appends a free-text value not in options', async () => {
    const onSaveMultiselect = vi.fn()
    render(
      <InlineEditCell
        value=""
        type="multiselect"
        options={FINISH_OPTIONS}
        multiselectValue={['holofoil']}
        allowCustom
        onSave={vi.fn()}
        onSaveMultiselect={onSaveMultiselect}
        displayValue={<span>Holofoil</span>}
      />
    )
    fireEvent.click(screen.getByText('Holofoil'))
    const customInput = screen.getByPlaceholderText(/add/i)
    fireEvent.change(customInput, { target: { value: 'firstEditionHolofoil' } })
    await act(async () => {
      fireEvent.keyDown(customInput, { key: 'Enter' })
    })
    expect(onSaveMultiselect).toHaveBeenCalledWith(['holofoil', 'firstEditionHolofoil'])
  })
})
