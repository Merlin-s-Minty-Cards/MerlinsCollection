import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import SetCombobox from '@/components/shared/SetCombobox'

/**
 * T8 — the type-to-narrow set picker, extracted from the public `FilterPanel`
 * so the admin inventory page can mount the same control.
 *
 * The two call sites hand it differently-shaped data — the public panel passes
 * `facets.sets` (`{id, name}`, scoped to customer-visible stock), the admin page
 * passes catalog-set registry rows carrying an owned count and a language — so
 * the component's contract is deliberately the intersection: `{id, name}` plus
 * an optional `annotation` string it renders alongside the name. Forking it into
 * two comboboxes is what these tests exist to prevent.
 */

const SETS = [
  { id: 'en:base1', name: 'Base Set' },
  { id: 'en:base2', name: 'Jungle' },
  { id: 'en:sv1', name: 'Scarlet & Violet' },
]

describe('SetCombobox', () => {
  it('narrows the options to what was typed', async () => {
    render(<SetCombobox sets={SETS} value="" onChange={vi.fn()} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    await userEvent.type(input, 'Jun')

    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names).toContain('Jungle')
    expect(names).not.toContain('Base Set')
    expect(names).not.toContain('Scarlet & Violet')
  })

  it('reports the selected set by id, not by name', async () => {
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="" onChange={onChange} ariaLabel="Set" />)

    await userEvent.click(screen.getByRole('combobox', { name: 'Set' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Base Set' }))

    expect(onChange).toHaveBeenCalledWith('en:base1')
  })

  it('renders the current value as its set name', () => {
    render(<SetCombobox sets={SETS} value="en:sv1" onChange={vi.fn()} ariaLabel="Set" />)

    expect(screen.getByRole('combobox', { name: 'Set' })).toHaveValue('Scarlet & Violet')
  })

  it('offers a clear option that reports the empty selection', async () => {
    const onChange = vi.fn()
    render(
      <SetCombobox sets={SETS} value="en:sv1" onChange={onChange} ariaLabel="Set"
                   emptyLabel="Any set" />,
    )

    await userEvent.click(screen.getByRole('combobox', { name: 'Set' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Any set' }))

    expect(onChange).toHaveBeenCalledWith('')
  })

  it('shows each option annotation without matching it while typing', async () => {
    /**
     * The annotation is what lets the admin see "0 owned" and tell an EN set
     * from its identically-named JA twin. It must NOT be part of the search
     * text: typing "EN" would otherwise match every English set at once and the
     * narrowing would stop meaning anything.
     */
    render(
      <SetCombobox
        sets={[
          { id: 'en:base1', name: 'Base Set', annotation: 'EN · 2 owned' },
          { id: 'ja:base1', name: 'Base Set', annotation: 'JP · 0 owned' },
          { id: 'en:sv1', name: 'Scarlet & Violet', annotation: 'EN · 0 owned' },
        ]}
        value=""
        onChange={vi.fn()}
        ariaLabel="Set"
      />,
    )

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    expect(screen.getByText('JP · 0 owned')).toBeInTheDocument()

    await userEvent.clear(input)
    await userEvent.type(input, 'EN')
    expect(screen.queryByRole('option', { name: /Scarlet/ })).not.toBeInTheDocument()
  })

  it('keeps two identically-named sets selectable as distinct options', async () => {
    const onChange = vi.fn()
    render(
      <SetCombobox
        sets={[
          { id: 'en:base1', name: 'Base Set', annotation: 'EN · 2 owned' },
          { id: 'ja:base1', name: 'Base Set', annotation: 'JP · 0 owned' },
        ]}
        value=""
        onChange={onChange}
        ariaLabel="Set"
      />,
    )

    await userEvent.click(screen.getByRole('combobox', { name: 'Set' }))
    const options = screen.getAllByRole('option').filter((o) =>
      o.textContent?.includes('Base Set'),
    )
    expect(options).toHaveLength(2)

    await userEvent.click(options[1])
    expect(onChange).toHaveBeenCalledWith('ja:base1')
  })
})

/**
 * Keyboard operation (RFC 0008 follow-up, T8 row 1).
 *
 * Options used to be chosen with `onMouseDown` only, with no arrow keys, no
 * Enter and no `aria-activedescendant` — so a keyboard-only admin could narrow
 * the list by typing and then had no way to pick anything out of it. This is a
 * heavily keyboard-driven admin surface, so that gap cost more here than it did
 * on the customer filter panel it was inherited from.
 */
describe('SetCombobox keyboard navigation', () => {
  it('selects a set with ArrowDown then Enter', async () => {
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="" onChange={onChange} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    // Index 0 is the "Any set" empty row, so the first real set is two downs in.
    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    await userEvent.keyboard('{Enter}')

    expect(onChange).toHaveBeenCalledWith('en:base1')
  })

  it('selects the empty row with a single ArrowDown then Enter', async () => {
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="en:base1" onChange={onChange} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    await userEvent.keyboard('{ArrowDown}{Enter}')

    expect(onChange).toHaveBeenCalledWith('')
  })

  it('navigates within the NARROWED list, not the full one', async () => {
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="" onChange={onChange} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    await userEvent.type(input, 'jun')
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    expect(onChange).toHaveBeenCalledWith('en:base2')
  })

  it('ArrowUp from nothing-highlighted wraps to the last option', async () => {
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="" onChange={onChange} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    await userEvent.keyboard('{ArrowUp}{Enter}')

    expect(onChange).toHaveBeenCalledWith('en:sv1')
  })

  it('does not select anything on a bare Enter', async () => {
    // Nothing is highlighted until the user arrows, so Enter must not silently
    // pick whatever happens to be first.
    const onChange = vi.fn()
    render(<SetCombobox sets={SETS} value="" onChange={onChange} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    await userEvent.keyboard('{Enter}')

    expect(onChange).not.toHaveBeenCalled()
  })

  it('points aria-activedescendant at the highlighted option', async () => {
    render(<SetCombobox sets={SETS} value="" onChange={vi.fn()} ariaLabel="Set" />)

    const input = screen.getByRole('combobox', { name: 'Set' })
    await userEvent.click(input)
    expect(input).not.toHaveAttribute('aria-activedescendant')

    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    const active = input.getAttribute('aria-activedescendant')
    expect(active).toBeTruthy()
    expect(document.getElementById(active!)).toHaveTextContent('Base Set')
  })
})
