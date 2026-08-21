import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import SlabEntryForm from '../SlabEntryForm'

const mockApi = { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})
// NOTE: useLocations returns `options`, NOT `locations` (lib/use-locations.ts:13).
vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({ options: [{ value: 'toploader', label: 'Toploader' }], loading: false }),
}))

// The grade field is filled via the ANCHORED /^grade$/i, never /grade/i: the
// form renders both "Grade" and "Grade label", and an unanchored regex matches
// both, so `getByLabelText` throws "Found multiple elements". Anchoring here
// rather than renaming the field keeps the operator-facing label accurate.
function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('SlabEntryForm', () => {
  beforeEach(() => {
    mockApi.get.mockReset()
    mockApi.get.mockResolvedValue({ items: [], total: 0 })
  })

  it('offers manual entry before the admin has searched for anything', async () => {
    render(<SlabEntryForm onAdd={vi.fn()} />)
    expect(await screen.findByRole('button', { name: /manual/i })).toBeInTheDocument()
  })

  it('blocks the add when the cert is blank and points at the Buy page', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/card name/i, 'Gengar VMAX')
    fill(/^grade$/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    expect(onAdd).not.toHaveBeenCalled()
    expect(screen.getByText(/without a cert number.*not a slab/i)).toBeInTheDocument()
    expect(screen.getByText(/buy page/i)).toBeInTheDocument()
  })

  it('adds a row with card_id null when the card was typed by hand', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fill(/card name/i, 'Some JP Card')
    fill(/^grade$/i, '10')
    fill(/cost/i, '40')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      cert_number: '89787279', card_id: null, name: 'Some JP Card',
      // A staged row carries the PARSED number, not the typed text (T0).
      company: 'PSA', grade: '10', buy_price: 40,
    })
  })

  it('sets card_id when a catalog suggestion is chosen', async () => {
    mockApi.get.mockResolvedValue({
      items: [{ card_id: 'en:swsh8-271', name: 'Gengar VMAX', set_name: 'Fusion Strike', number: '271' }],
      total: 1,
    })
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fill(/card name/i, 'Gengar')

    const suggestion = await screen.findByRole('button', { name: /Gengar VMAX/ })
    fireEvent.click(suggestion)
    fill(/^grade$/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalled())
    expect(onAdd.mock.calls[0][0].card_id).toBe('en:swsh8-271')
  })

  it('warns but still allows the add when the cert is already owned', async () => {
    mockApi.get.mockImplementation((path: string) =>
      path.startsWith('/slabs/certs/')
        ? Promise.resolve({ owned: true, item_id: '01ABC', status: 'available', name: 'Gengar VMAX' })
        : Promise.resolve({ items: [], total: 0 })
    )
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fireEvent.blur(screen.getByLabelText(/cert number/i))

    expect(await screen.findByText(/already in inventory/i)).toBeInTheDocument()

    fill(/card name/i, 'Gengar VMAX')
    fill(/^grade$/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
  })

  // ---- RFC 0010 T0: the cost field accepts what a human types --------------
  // The owner's report, 2026-08-10: "typing 1,300 for cost will break the
  // commit, but typing 1300 is accepted. Both should work."

  it('stages 1,300 as the number 1300 — the owner-reported input', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fill(/card name/i, 'Gengar VMAX')
    fill(/^grade$/i, '9.5')
    fill(/cost/i, '1,300')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
    expect(onAdd.mock.calls[0][0].buy_price).toBe(1300)
  })

  it('stages $40 as the number 40', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '11111111')
    fill(/card name/i, 'Pikachu')
    fill(/^grade$/i, '10')
    fill(/cost/i, '$40')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
    expect(onAdd.mock.calls[0][0].buy_price).toBe(40)
  })

  it('blocks the add on an unreadable cost and says why, rather than guessing', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '22222222')
    fill(/card name/i, 'Charizard')
    fill(/^grade$/i, '9')
    fill(/cost/i, '1,30')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    expect(onAdd).not.toHaveBeenCalled()
    // MoneyInput raises its own inline alert too, so assert across all of them
    // rather than pinning which one carries the message.
    const alerts = screen.getAllByRole('alert').map((el) => el.textContent ?? '')
    expect(alerts.join(' ')).toMatch(/cost/i)
  })

  it('defaults company to PSA and allows CGC', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    expect((screen.getByLabelText(/company/i) as HTMLSelectElement).value).toBe('PSA')
    fireEvent.change(screen.getByLabelText(/company/i), { target: { value: 'CGC' } })
    fill(/cert number/i, '1234')
    fill(/card name/i, 'Charizard')
    fill(/^grade$/i, '9')
    fill(/cost/i, '10')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
    await waitFor(() => expect(onAdd.mock.calls[0][0].company).toBe('CGC'))
  })

  // ---- RFC 0010 T15: the picker shows name, image AND price ----------------

  describe('catalog picker', () => {
    const priced = {
      card_id: 'en:swsh8-271',
      name: 'Gengar VMAX',
      set_id: 'swsh8',
      set_name: 'Fusion Strike',
      number: '271',
      rarity: 'Secret Rare',
      images: { small: 'https://img.example/gengar.png' },
      display_price: '189.99',
      display_finish: 'holofoil',
      detail: 'full',
      last_synced_at: new Date().toISOString(),
    }

    async function searchFor(term: string) {
      mockApi.get.mockResolvedValue({ items: [priced], total: 1 })
      render(<SlabEntryForm onAdd={vi.fn()} />)
      fill(/card name/i, term)
      return screen.findByTestId('card-picker-row')
    }

    it('renders both the art and the price on every candidate', async () => {
      const row = await searchFor('Gengar')
      expect(within(row).getByAltText('Gengar VMAX')).toHaveAttribute(
        'src', 'https://img.example/gengar.png',
      )
      expect(within(row).getByTestId('card-picker-price').textContent).toContain('$189.99')
    })

    it('still links the staged row to the catalog when a candidate is chosen', async () => {
      mockApi.get.mockResolvedValue({ items: [priced], total: 1 })
      const onAdd = vi.fn()
      render(<SlabEntryForm onAdd={onAdd} />)
      fill(/cert number/i, '89787279')
      fill(/card name/i, 'Gengar')

      const row = await screen.findByTestId('card-picker-row')
      fireEvent.click(within(row).getByRole('button', { name: /Gengar VMAX/ }))
      fill(/^grade$/i, '9.5')
      fill(/cost/i, '900.50')
      fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

      await waitFor(() => expect(onAdd).toHaveBeenCalled())
      expect(onAdd.mock.calls[0][0].card_id).toBe('en:swsh8-271')
    })
  })
})
