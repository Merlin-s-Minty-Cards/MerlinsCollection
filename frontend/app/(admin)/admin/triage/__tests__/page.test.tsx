import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import AdminTriagePage from '../page'

/**
 * T11 — Triage: one place for everything that might be wrong.
 * docs/plans/rfc-0008/t11-triage-tab.md
 *
 * The list is the UNION of one stored reason and two derived ones, served by
 * `GET /admin/inventory/search?triage=true` (not a parallel list endpoint —
 * see the backend RED tests in backend/tests/routers/admin/test_triage.py):
 *
 *   flagged              stored `needs_review` — cleared explicitly by an admin
 *   missing_card_id      no catalog link — self-healing, fixed by re-pointing
 *   missing_english_name JP item with no override — self-healing, fixed by naming
 *
 * The two repair tools are deliberately separate, and the separation is the
 * owner's core requirement: assigning a name must NEVER change `card_id`.
 */

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()

// One STABLE object, not a fresh literal per call. The real `useAdminApi`
// memoizes its return value, and this page's `fetchItems` is a `useCallback`
// keyed on it — a mock that returns a new identity every render turns the
// fetch effect into an infinite loop that hangs the run.
const mockApi = {
  get: getMock,
  post: postMock,
  put: putMock,
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

// --- fixtures -------------------------------------------------------------

const flaggedItem = {
  item_id: 'flagged-1',
  kind: 'raw',
  card_id: 'en:sv1-25',
  language: 'EN',
  display_name: 'Pikachu #25',
  display_name_override: null,
  needs_review: true,
  review_reason: 'back looks trimmed',
  card: { card_id: 'en:sv1-25', name: 'Pikachu', set_name: 'Scarlet & Violet', number: '025' },
}

const unlinkedItem = {
  item_id: 'unlinked-1',
  kind: 'raw',
  card_id: null,
  language: 'EN',
  display_name: 'Charizard #4',
  display_name_override: null,
  needs_review: false,
  review_reason: null,
  card: null,
}

const jpItem = {
  item_id: 'jp-1',
  kind: 'raw',
  card_id: 'ja:M4-084',
  language: 'JP',
  display_name: 'ハリマロン #84',
  display_name_override: null,
  needs_review: false,
  review_reason: null,
  card: { card_id: 'ja:M4-084', name: 'ハリマロン', set_name: 'Mega Brave', number: '084' },
}

/** Qualifies under BOTH `flagged` and `missing_card_id`. */
const twoReasonItem = {
  item_id: 'both-1',
  kind: 'raw',
  card_id: null,
  language: 'EN',
  display_name: 'Blastoise #9',
  display_name_override: null,
  needs_review: true,
  review_reason: 'manual_entry',
  card: null,
}

function mockList(items: unknown[]) {
  getMock.mockImplementation((path: string) => {
    if (path === '/inventory/search') return Promise.resolve({ items, total: items.length })
    if (path === '/market/search') return Promise.resolve({ items: [], total: 0 })
    if (path === '/locations') return Promise.resolve([])
    return Promise.resolve({})
  })
}

/**
 * The `<tr>` containing the given card name.
 *
 * Found via the cell text rather than `getByRole('row', { name })`: the row
 * must be awaited (the list arrives asynchronously), and a `<tr>`'s accessible
 * name is not reliably computed from its contents.
 */
async function findRow(name: string | RegExp) {
  const cell = await screen.findByText(name)
  const tr = cell.closest('tr')
  if (!tr) throw new Error(`No <tr> contains ${name}`)
  return tr
}

/** Every rendered row whose text mentions the given card. */
function rowsMentioning(pattern: RegExp) {
  return screen.getAllByRole('row').filter((r) => pattern.test(r.textContent ?? ''))
}

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  putMock.mockReset()
  postMock.mockResolvedValue({})
  putMock.mockResolvedValue({})
  mockList([])
})

// ===========================================================================
// 16-18 — one list, reason chips, reason filter
// ===========================================================================

describe('Triage list', () => {
  it('requests the union of every triage reason, not one filter at a time', async () => {
    mockList([flaggedItem])
    render(<AdminTriagePage />)

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ triage: 'true' }),
      ),
    )
  })

  it('labels each row with why it is here — stored and derived reasons alike', async () => {
    mockList([flaggedItem, unlinkedItem, jpItem])
    render(<AdminTriagePage />)

    // Stored: the admin's own note, not just the bare fact of the flag. A queue
    // of cards with no stated problem is not a worklist.
    expect(within(await findRow(/Pikachu/)).getByText(/back looks trimmed/i)).toBeInTheDocument()
    // Derived: computed, no flag to clear, leaves on its own once fixed.
    expect(within(await findRow(/Charizard/)).getByText(/no catalog link/i)).toBeInTheDocument()
    expect(within(await findRow(/ハリマロン/)).getByText(/needs english name/i)).toBeInTheDocument()
  })

  it('lists a card qualifying under two reasons once, carrying both chips', async () => {
    // Parallel queues would show this card twice and it would get "fixed" twice.
    mockList([twoReasonItem])
    render(<AdminTriagePage />)

    const tr = await findRow(/Blastoise/)
    expect(rowsMentioning(/Blastoise/)).toHaveLength(1)
    expect(within(tr).getByText(/manual_entry/i)).toBeInTheDocument()
    expect(within(tr).getByText(/no catalog link/i)).toBeInTheDocument()
  })

  it('narrows the list to one reason when the admin filters by it', async () => {
    mockList([flaggedItem, unlinkedItem, jpItem])
    render(<AdminTriagePage />)
    await screen.findByText(/Pikachu/)

    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'missing_card_id' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ triage: 'true', missing_card_id: 'true' }),
      ),
    )
  })

  it('shows the effective name — the override outranks the catalog name', async () => {
    // What the admin sees must be what the customer sees, or they are editing
    // blind against the one field that actually wins (T10's precedence).
    mockList([{ ...jpItem, display_name_override: 'Chespin' }])
    render(<AdminTriagePage />)

    expect(await screen.findByText('Chespin')).toBeInTheDocument()
  })

  it('reads as success, not emptiness, when nothing needs review', async () => {
    mockList([])
    render(<AdminTriagePage />)

    expect(await screen.findByText(/nothing needs review/i)).toBeInTheDocument()
  })
})

// ===========================================================================
// 19-21 — repair tool 1: re-point a mismatched card (the dangerous write)
// ===========================================================================

describe('Triage — re-pointing a mismatched card', () => {
  const replacement = {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_name: 'Base Set',
    number: '004',
    images: { small: 'https://example.com/base1-4.webp' },
  }

  function mockRepoint(item: unknown, candidate: unknown = replacement) {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') return Promise.resolve({ items: [item], total: 1 })
      if (path === '/market/search') return Promise.resolve({ items: [candidate], total: 1 })
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })
  }

  async function pickReplacement(candidateName = 'Charizard') {
    fireEvent.click(await screen.findByRole('button', { name: /re-point/i }))
    fireEvent.change(await screen.findByLabelText(/search the catalog/i), {
      target: { value: candidateName },
    })
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(candidateName) }))
  }

  it('shows a before/after comparison and writes nothing until it is confirmed', async () => {
    // `card_id` drives pricing, images, set and rarity. The admin has to see
    // what they are changing TO before it lands.
    mockRepoint(flaggedItem)
    render(<AdminTriagePage />)

    await pickReplacement()

    const confirm = await screen.findByRole('dialog', { name: /confirm re-point/i })
    expect(within(confirm).getByText(/Pikachu/)).toBeInTheDocument()
    expect(within(confirm).getByText(/Charizard/)).toBeInTheDocument()
    expect(putMock).not.toHaveBeenCalled()

    fireEvent.click(within(confirm).getByRole('button', { name: /confirm/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/flagged-1', { card_id: 'en:base1-4' }),
    )
  })

  it('says plainly that the price is stale until the next sync', async () => {
    // Otherwise the admin re-points and is left staring at the OLD card's price,
    // with nothing on screen explaining why.
    mockRepoint(flaggedItem)
    render(<AdminTriagePage />)

    await pickReplacement()

    const confirm = await screen.findByRole('dialog', { name: /confirm re-point/i })
    expect(within(confirm).getByText(/price/i)).toBeInTheDocument()
  })

  it('warns when the item carries trade lineage, without blocking the fix', async () => {
    // Re-pointing rewrites what a historical record appears to refer to. Fixing
    // a genuine old error is legitimate, so this warns rather than blocks.
    mockRepoint({ ...flaggedItem, lineage_id: 'lin-9', predecessor_item_id: 'item-0' })
    render(<AdminTriagePage />)

    await pickReplacement()

    const confirm = await screen.findByRole('dialog', { name: /confirm re-point/i })
    expect(within(confirm).getByText(/lineage|trade history/i)).toBeInTheDocument()
    expect(within(confirm).getByRole('button', { name: /confirm/i })).toBeEnabled()
  })

  it('warns loudly when the new card is in a different language from the item', async () => {
    // models/inventory.py:38-53 — a JP item resolves to a JP catalog row BY
    // DESIGN, so an EN target is nearly always a mistake.
    mockRepoint(jpItem, replacement) // JP item -> "en:base1-4"
    render(<AdminTriagePage />)

    await pickReplacement()

    const confirm = await screen.findByRole('dialog', { name: /confirm re-point/i })
    expect(within(confirm).getByText(/different language|cross-language/i)).toBeInTheDocument()
  })
})

// ===========================================================================
// 22-24 — repair tool 2: assign an English display name
// ===========================================================================

describe('Triage — assigning an English display name', () => {
  const englishEquivalent = {
    card_id: 'en:sv1-9',
    name: 'Chespin',
    set_name: 'Scarlet & Violet',
    number: '009',
  }

  function mockNaming(item: unknown = jpItem) {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') return Promise.resolve({ items: [item], total: 1 })
      if (path === '/market/search') {
        return Promise.resolve({ items: [englishEquivalent], total: 1 })
      }
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })
  }

  it('copies a name off an English card WITHOUT re-linking the item', async () => {
    // *** The single most important assertion in T11. ***
    // The admin is choosing a NAME, not a card. `card_id` must not appear in
    // the request body at all — not unchanged, not echoed, absent. Designing
    // out this exact confusion is the owner's stated requirement.
    mockNaming()
    render(<AdminTriagePage />)

    fireEvent.click(await screen.findByRole('button', { name: /assign english name/i }))
    fireEvent.change(await screen.findByLabelText(/search the catalog/i), {
      target: { value: 'Chespin' },
    })
    fireEvent.click(await screen.findByRole('button', { name: /use this name/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/jp-1', {
        display_name_override: 'Chespin',
      }),
    )
    expect(putMock.mock.calls[0][1]).not.toHaveProperty('card_id')
  })

  it('makes it unmistakable in the UI that the catalog link is untouched', async () => {
    mockNaming()
    render(<AdminTriagePage />)

    fireEvent.click(await screen.findByRole('button', { name: /assign english name/i }))

    expect(
      await screen.findByText(/does not change (which card|the card|the catalog link)/i),
    ).toBeInTheDocument()
  })

  it('accepts a typed name for a JP-exclusive print with no English equivalent', async () => {
    // T10's research: a large and permanent share of the Japanese catalog has
    // no English print at all, so the search path alone cannot cover this.
    mockNaming()
    render(<AdminTriagePage />)

    fireEvent.click(await screen.findByRole('button', { name: /assign english name/i }))
    fireEvent.change(await screen.findByLabelText(/type a name/i), {
      target: { value: 'Chespin (Mega Brave promo)' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^save name$/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/jp-1', {
        display_name_override: 'Chespin (Mega Brave promo)',
      }),
    )
  })

  it('clears the override back to the catalog name', async () => {
    // Sends null, not "": the backend normalizes blank to None, but an empty
    // string on the wire is a value the admin did not choose.
    mockNaming({ ...jpItem, display_name_override: 'Chespin' })
    render(<AdminTriagePage />)

    fireEvent.click(await screen.findByRole('button', { name: /assign english name/i }))
    fireEvent.click(await screen.findByRole('button', { name: /clear name/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/jp-1', {
        display_name_override: null,
      }),
    )
  })
})

// ===========================================================================
// 25 — the list drains
// ===========================================================================

describe('Triage — a fixed item leaves the list', () => {
  it('removes a cleared row immediately, with no full refetch', async () => {
    // Matches the Prep Queue's "Priced -> removed" pattern (CLAUDE.md). A
    // refetch round-trip here makes every fix feel like it hung.
    mockList([flaggedItem])
    render(<AdminTriagePage />)

    await screen.findByText(/Pikachu/)
    const searchCalls = getMock.mock.calls.filter(([p]) => p === '/inventory/search').length

    fireEvent.click(screen.getByRole('button', { name: /clear review/i }))

    await waitFor(() => expect(screen.queryByText(/Pikachu/)).not.toBeInTheDocument())
    expect(putMock).toHaveBeenCalledWith('/inventory/flagged-1', {
      needs_review: false,
      review_reason: null,
    })
    expect(getMock.mock.calls.filter(([p]) => p === '/inventory/search')).toHaveLength(
      searchCalls,
    )
  })
})
