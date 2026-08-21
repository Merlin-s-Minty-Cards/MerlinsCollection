import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CertInput from '../CertInput'

describe('CertInput', () => {
  it('accepts a wedge scanner burst and keeps the digits', () => {
    const onChange = vi.fn()
    render(<CertInput value="" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: '89787279' } })
    expect(onChange).toHaveBeenCalledWith('89787279')
  })

  it('strips a trailing carriage return and newline a scanner appends', () => {
    const onChange = vi.fn()
    render(<CertInput value="" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: '89787279\r\n' } })
    expect(onChange).toHaveBeenCalledWith('89787279')
  })

  it('calls onEnter when Enter is pressed, without needing a scanner', () => {
    const onEnter = vi.fn()
    render(<CertInput value="89787279" onChange={vi.fn()} onEnter={onEnter} />)
    fireEvent.keyDown(screen.getByLabelText(/cert/i), { key: 'Enter' })
    expect(onEnter).toHaveBeenCalledTimes(1)
  })

  it('accepts characters typed one at a time over a long span', () => {
    // The regression a speed-gated implementation introduces: a cert typed
    // slowly must be exactly as valid as one scanned in 40ms.
    const onChange = vi.fn()
    const { rerender } = render(<CertInput value="" onChange={onChange} />)
    const digits = '89787279'
    let acc = ''
    for (const d of digits) {
      acc += d
      fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: acc } })
      rerender(<CertInput value={acc} onChange={onChange} />)
    }
    expect(onChange).toHaveBeenLastCalledWith('89787279')
    expect(onChange).toHaveBeenCalledTimes(digits.length)
  })

  it('does not call onEnter on an empty value', () => {
    const onEnter = vi.fn()
    render(<CertInput value="  " onChange={vi.fn()} onEnter={onEnter} />)
    fireEvent.keyDown(screen.getByLabelText(/cert/i), { key: 'Enter' })
    expect(onEnter).not.toHaveBeenCalled()
  })

  it('fires onBlur so the form can run its duplicate check', () => {
    const onBlur = vi.fn()
    render(<CertInput value="89787279" onChange={vi.fn()} onBlur={onBlur} />)
    fireEvent.blur(screen.getByLabelText(/cert/i))
    expect(onBlur).toHaveBeenCalledTimes(1)
  })
})
