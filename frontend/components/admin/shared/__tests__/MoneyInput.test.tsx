import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import MoneyInput from '../MoneyInput'

/**
 * A controlled host, because the blur normalisation is only observable when the
 * parent actually accepts the value MoneyInput reports back. Rendering the
 * component uncontrolled would let a broken normalisation pass.
 */
function Host({ onChange, initial = '' }: { onChange?: (r: string, p: number | null) => void; initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <MoneyInput
      label="Cost"
      value={value}
      onChange={(raw, parsed) => {
        setValue(raw)
        onChange?.(raw, parsed)
      }}
    />
  )
}

describe('MoneyInput', () => {
  it('normalises on blur so the operator sees what will be sent', () => {
    render(<Host />)
    const input = screen.getByLabelText('Cost')
    fireEvent.change(input, { target: { value: '1,300' } })
    fireEvent.blur(input)
    expect((input as HTMLInputElement).value).toBe('1300.00')
  })

  it('flags an unreadable value inline and marks the field invalid', () => {
    render(<Host />)
    const input = screen.getByLabelText('Cost')
    fireEvent.change(input, { target: { value: '1,30' } })

    expect(screen.getByRole('alert')).toHaveTextContent(/isn't an amount i can read/i)
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('reports null to the parent for an unreadable value', () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Cost'), { target: { value: '1,30' } })
    expect(onChange).toHaveBeenLastCalledWith('1,30', null)
  })

  it('reports the parsed number to the parent for a readable value', () => {
    const onChange = vi.fn()
    render(<Host onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Cost'), { target: { value: '1,300' } })
    expect(onChange).toHaveBeenLastCalledWith('1,300', 1300)
  })

  it("keeps the caller's label on the input, and is text — never type=number", () => {
    render(<Host />)
    const input = screen.getByLabelText('Cost') as HTMLInputElement
    // type="number" cannot receive a comma at all, which is the fix that was
    // rejected: it satisfies the machine and fails the person.
    expect(input.type).toBe('text')
    expect(input).toHaveAttribute('inputMode', 'decimal')
  })

  it('says nothing while the field is empty — blank is not an error', () => {
    render(<Host />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Cost')).not.toHaveAttribute('aria-invalid', 'true')
  })
})
