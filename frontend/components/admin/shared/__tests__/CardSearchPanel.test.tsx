import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CardSearchPanel from '../CardSearchPanel'

/**
 * RFC 0011 T11 — one shared card search (name + number + set) with a
 * permanent, always-visible manual-entry escape hatch.
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

vi.mock('@/lib/use-catalog-sets', () => ({
  useCatalogSets: () => ({
    sets: [
      { set_id: 'en:base1', set_name: 'Base Set', language: 'en', card_count: 102, owned_count: 3 },
    ],
    loading: false,
  }),
  toComboboxSets: (sets: { set_id: string; set_name: string }[]) =>
    sets.map((s) => ({ id: s.set_id, name: s.set_name })),
}))

vi.mock('@/lib/use-catalog-languages', () => ({
  useCatalogLanguages: () => ({
    languages: [
      { code: 'EN', label: 'English', sets: 218 },
      { code: 'JP', label: 'Japanese', sets: 177 },
    ],
    loading: false,
  }),
}))

function mockResults(items: unknown[]) {
  getMock.mockResolvedValue({ items, total: items.length })
}

function card(over: Record<string, unknown> = {}) {
  return {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_id: 'en:base1',
    set_name: 'Base Set',
    number: '4',
    rarity: 'Rare Holo',
    images: { small: 'https://img/1.png' },
    display_price: '100.00',
    detail: 'full',
    ...over,
  }
}

beforeEach(() => {
  getMock.mockReset()
  mockResults([])
})

describe('CardSearchPanel', () => {
  it('sends name and number together', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')
    await user.type(screen.getByLabelText('Card number'), '4')

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ name: 'Charizard', number: '4' })))
  })

  it('defaults the language filter to EN and sends it (RFC 0023 T3)', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ name: 'Charizard', language: 'EN' })))
  })

  it('offers only languages that actually have catalog rows, from useCatalogLanguages', async () => {
    render(<CardSearchPanel onSelect={vi.fn()} />)

    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Japanese' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Korean' })).not.toBeInTheDocument()
  })

  it('sends the chosen language once one is picked', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.selectOptions(screen.getByRole('combobox', { name: 'Language' }), 'JP')
    await user.type(screen.getByLabelText('Card name'), 'Charizard')

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ name: 'Charizard', language: 'JP' })))
  })

  it('includes the chosen set once one is picked', async () => {
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.click(screen.getByRole('combobox', { name: 'Set' }))
    await user.click(await screen.findByRole('option', { name: 'Base Set' }))
    await user.type(screen.getByLabelText('Card name'), 'Charizard')

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ name: 'Charizard', set_id: 'en:base1' })))
  })

  it('searches on the number alone', async () => {
    // Set + number with no name is how you find a card whose name you cannot read.
    const user = userEvent.setup({ delay: null })
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card number'), '182')

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/market/search',
      expect.objectContaining({ number: '182' })))
  })

  it('does not request the whole catalog when every field is empty', async () => {
    render(<CardSearchPanel onSelect={vi.fn()} />)
    await new Promise((r) => setTimeout(r, 400)) // past the 300ms debounce
    expect(getMock).not.toHaveBeenCalled()
  })

  it('shows manual entry before any search has run', async () => {
    // The owner's actual complaint: it only appeared after a failed search.
    render(<CardSearchPanel onSelect={vi.fn()} onManualEntry={vi.fn()} />)
    expect(screen.getByRole('button', { name: /enter manually/i })).toBeInTheDocument()
  })

  it('still shows manual entry while results are on screen', async () => {
    const user = userEvent.setup({ delay: null })
    mockResults([card({ name: 'Charizard' })])
    render(<CardSearchPanel onSelect={vi.fn()} onManualEntry={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')
    await screen.findByText('Charizard')

    expect(screen.getByRole('button', { name: /enter manually/i })).toBeInTheDocument()
  })

  it('omits manual entry where it is meaningless', () => {
    render(<CardSearchPanel onSelect={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /enter manually/i })).not.toBeInTheDocument()
  })

  it('shows name, image and price on every result', async () => {
    const user = userEvent.setup({ delay: null })
    mockResults([card({ name: 'Charizard', images: { small: 'https://img/1.png' },
      display_price: '100.00' })])
    render(<CardSearchPanel onSelect={vi.fn()} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')

    expect(await screen.findByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
  })

  it('calls onSelect with the picked card', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup({ delay: null })
    mockResults([card({ name: 'Charizard' })])
    render(<CardSearchPanel onSelect={onSelect} />)

    await user.type(screen.getByLabelText('Card name'), 'Charizard')
    await user.click(await screen.findByText('Charizard'))

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ card_id: 'en:base1-4' }))
  })
})
