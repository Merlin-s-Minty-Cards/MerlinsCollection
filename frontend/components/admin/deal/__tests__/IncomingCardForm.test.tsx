import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import IncomingCardForm from '../IncomingCardForm'
import type { PickerCard } from '@/components/admin/shared/CardPickerRow'

/**
 * RFC 0011 T14 — catalog pick first, then kind. Decision 15: condition and
 * grade are alternatives and are never both on screen.
 */

const getMock = vi.fn()

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => ({
      get: getMock,
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
      isAuthenticated: true,
      isLoading: false,
    }),
  }
})

vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({
    options: [
      { value: 'glass', label: 'Glass' },
      { value: 'toploader', label: 'Toploader' },
    ],
    loading: false,
  }),
}))

function card(over: Partial<PickerCard> = {}): PickerCard {
  return {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_name: 'Base Set',
    number: '4',
    rarity: 'Rare Holo',
    images: { small: 'https://i/1.png' },
    display_price: '120.00',
    detail: 'full',
    ...over,
  }
}

function mockCertOwned(cert: string) {
  getMock.mockImplementation(async (path: string) =>
    path.includes(cert) ? { owned: true, item_id: 'i1', status: 'sold', name: 'Charizard' } : { owned: false },
  )
}

beforeEach(() => {
  getMock.mockReset()
  getMock.mockResolvedValue({ owned: false })
})

describe('IncomingCardForm', () => {
  it('never shows condition and grade at the same time', async () => {
    const user = userEvent.setup({ delay: null })
    render(<IncomingCardForm card={card()} onAdd={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByLabelText(/condition/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^grade$/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /graded/i }))

    expect(screen.queryByLabelText(/condition/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^grade$/i)).toBeInTheDocument()
  })

  it('shows the picked card identity with image, name and price', () => {
    render(<IncomingCardForm card={card()} onAdd={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('$120.00')).toBeInTheDocument()
  })

  it('emits a raw leg by default', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)

    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'raw', card_id: 'en:base1-4', name: 'Charizard', condition: 'NM' }),
    )
    expect(onAdd.mock.calls[0][0]).not.toHaveProperty('grade')
  })

  it('emits the backend language enum casing, not the display casing', async () => {
    // `Language` on InventoryItem is a case-sensitive StrEnum: EN/JP only.
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)

    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))

    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ language: 'EN' }))
  })

  it('emits a graded leg with the cert fields', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card({ card_id: 'en:base1-4' })} onAdd={onAdd} onCancel={vi.fn()} />)

    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.selectOptions(screen.getByLabelText(/company/i), 'PSA')
    await user.type(screen.getByLabelText(/^grade$/i), '10')
    await user.type(screen.getByLabelText(/cert/i), '12345678')
    await user.type(screen.getByLabelText(/value/i), '400')
    await user.click(screen.getByRole('button', { name: /^add$/i }))

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'graded',
        company: 'PSA',
        grade: 10,
        cert_number: '12345678',
        card_id: 'en:base1-4',
      }),
    )
  })

  it('accepts a value typed with a comma', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), '1,300')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ agreed_value: 1300 }))
  })

  it('accepts a free card', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), '0')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ agreed_value: 0 }))
  })

  it('refuses an unreadable value rather than sending a guess', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), 'abc')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('warns on an already-owned cert without blocking the add', async () => {
    const user = userEvent.setup({ delay: null })
    mockCertOwned('12345678')
    render(<IncomingCardForm card={card()} onAdd={vi.fn()} onCancel={vi.fn()} />)
    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.type(screen.getByLabelText(/cert/i), '12345678')

    expect(await screen.findByText(/already own/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^add$/i })).toBeEnabled()
  })

  it('forces manual entry to raw, and says why', () => {
    render(<IncomingCardForm card={null} onAdd={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /graded/i })).toBeDisabled()
    expect(screen.getByText(/needs a catalog card/i)).toBeInTheDocument()
  })

  it('emits a manual leg with a null card_id', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={null} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/card name/i), 'Japanese promo')
    await user.type(screen.getByLabelText(/value/i), '25')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ card_id: null, name: 'Japanese promo', kind: 'raw' }),
    )
  })

  it('disables Graded and says why when gradedAllowed is false (Buy mode, Critical 1 regression)', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} gradedAllowed={false} />)

    expect(screen.getByRole('radio', { name: /graded/i })).toBeDisabled()
    expect(screen.getByText(/graded intake isn't available from buy/i)).toBeInTheDocument()

    // Even if `kind` state were somehow 'graded', submit must still emit raw
    // — the toggle disable is not the only line of defense.
    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ kind: 'raw' }))
  })

  it('cancels without emitting', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    const onCancel = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={onCancel} />)
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
    expect(onAdd).not.toHaveBeenCalled()
  })
})
