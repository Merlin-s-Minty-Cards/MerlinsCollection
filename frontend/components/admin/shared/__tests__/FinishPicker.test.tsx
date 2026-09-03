import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FinishPicker from '../FinishPicker'

/**
 * RFC 0023 T6 — one priced finish (the join key into card.prices) plus a
 * chip multi-select for everything that is genuinely not mutually exclusive
 * with it. The chip vocabulary is SUGGESTED, not enforced — free text is
 * always accepted.
 */

describe('FinishPicker — the priced finish select', () => {
  it('offers the measured PRICED_FINISHES vocabulary', () => {
    render(
      <FinishPicker finish="normal" onFinishChange={vi.fn()} attributes={[]} onAttributesChange={vi.fn()} />
    )
    const select = screen.getByRole('combobox', { name: 'Finish' })
    expect(select).toHaveValue('normal')
    expect(screen.getByRole('option', { name: 'holofoil' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '1stEditionHolofoil' })).toBeInTheDocument()
    // The exact live bug this RFC exists to fix — the old dropdown offered
    // this spelling, which `_MARKET_FINISH_FALLBACK` has never heard of.
    expect(screen.queryByRole('option', { name: 'firstEditionHolofoil' })).not.toBeInTheDocument()
  })

  it('reports a change on the priced finish', async () => {
    const user = userEvent.setup({ delay: null })
    const onFinishChange = vi.fn()
    render(
      <FinishPicker finish="normal" onFinishChange={onFinishChange} attributes={[]} onAttributesChange={vi.fn()} />
    )
    await user.selectOptions(screen.getByRole('combobox', { name: 'Finish' }), 'holofoil')
    expect(onFinishChange).toHaveBeenCalledWith('holofoil')
  })
})

describe('FinishPicker — the attributes chip multi-select', () => {
  it('renders the suggested chip vocabulary', () => {
    render(
      <FinishPicker finish="normal" onFinishChange={vi.fn()} attributes={[]} onAttributesChange={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: '1st Edition' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Full Art' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Signed' })).toBeInTheDocument()
  })

  it('adds a chip to the attributes array when clicked', async () => {
    const user = userEvent.setup({ delay: null })
    const onAttributesChange = vi.fn()
    render(
      <FinishPicker finish="normal" onFinishChange={vi.fn()} attributes={[]} onAttributesChange={onAttributesChange} />
    )
    await user.click(screen.getByRole('button', { name: '1st Edition' }))
    expect(onAttributesChange).toHaveBeenCalledWith(['1st Edition'])
  })

  it('marks a selected chip as pressed', () => {
    render(
      <FinishPicker finish="normal" onFinishChange={vi.fn()} attributes={['1st Edition']} onAttributesChange={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: '1st Edition' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Signed' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('removes a chip from the attributes array when clicked again', async () => {
    const user = userEvent.setup({ delay: null })
    const onAttributesChange = vi.fn()
    render(
      <FinishPicker
        finish="normal"
        onFinishChange={vi.fn()}
        attributes={['1st Edition', 'Shadowless']}
        onAttributesChange={onAttributesChange}
      />
    )
    await user.click(screen.getByRole('button', { name: '1st Edition' }))
    expect(onAttributesChange).toHaveBeenCalledWith(['Shadowless'])
  })

  it('accepts free text via the add-custom input, alongside the suggested chips', async () => {
    const user = userEvent.setup({ delay: null })
    const onAttributesChange = vi.fn()
    render(
      <FinishPicker finish="normal" onFinishChange={vi.fn()} attributes={[]} onAttributesChange={onAttributesChange} />
    )
    await user.type(screen.getByLabelText('Add custom finish attribute'), 'Wonder Pick Foil{Enter}')
    expect(onAttributesChange).toHaveBeenCalledWith(['Wonder Pick Foil'])
  })

  it('does not add a duplicate or blank custom tag', async () => {
    const user = userEvent.setup({ delay: null })
    const onAttributesChange = vi.fn()
    render(
      <FinishPicker
        finish="normal" onFinishChange={vi.fn()}
        attributes={['Signed']} onAttributesChange={onAttributesChange}
      />
    )
    await user.type(screen.getByLabelText('Add custom finish attribute'), 'Signed{Enter}')
    await user.type(screen.getByLabelText('Add custom finish attribute'), '   {Enter}')
    expect(onAttributesChange).not.toHaveBeenCalled()
  })

  it('renders an already-selected custom tag as its own removable chip', () => {
    // A tag typed via the custom input must not vanish into the array with
    // no way to click it off again.
    render(
      <FinishPicker
        finish="normal" onFinishChange={vi.fn()}
        attributes={['Wonder Pick Foil']} onAttributesChange={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: 'Wonder Pick Foil' })).toHaveAttribute('aria-pressed', 'true')
  })
})
