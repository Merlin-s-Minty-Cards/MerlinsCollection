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

// `triage_reasons` is on every fixture because RFC 0010 T3 makes the SERVER the
// authority on why a row is here — the page renders that array rather than
// recomputing the rules in TypeScript. A fixture without it is a response shape
// the endpoint no longer produces.
const flaggedItem = {
  item_id: 'flagged-1',
  kind: 'raw',
  card_id: 'en:sv1-25',
  language: 'EN',
  display_name: 'Pikachu #25',
  display_name_override: null,
  condition: 'NM',
  condition_modifier: null,
  needs_review: true,
  review_reason: 'back looks trimmed',
  triage_reasons: ['flagged'],
  card: { card_id: 'en:sv1-25', name: 'Pikachu', set_name: 'Scarlet & Violet', number: '025' },
}

const unlinkedItem = {
  item_id: 'unlinked-1',
  kind: 'raw',
  card_id: null,
  language: 'EN',
  display_name: 'Charizard #4',
  display_name_override: null,
  condition: 'LP',
  condition_modifier: null,
  needs_review: false,
  review_reason: null,
  triage_reasons: ['missing_card_id'],
  card: null,
}

const jpItem = {
  item_id: 'jp-1',
  kind: 'raw',
  card_id: 'ja:M4-084',
  language: 'JP',
  display_name: 'ハリマロン #84',
  display_name_override: null,
  condition: 'NM',
  condition_modifier: null,
  needs_review: false,
  review_reason: null,
  triage_reasons: ['missing_english_name'],
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
  condition: 'NM',
  condition_modifier: null,
  needs_review: true,
  review_reason: 'manual_entry',
  triage_reasons: ['flagged', 'missing_card_id'],
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
    // T3: the machine key renders as a sentence, not as `manual_entry`.
    expect(within(tr).getByText(/entered by hand/i)).toBeInTheDocument()
    expect(within(tr).getByText(/no catalog link/i)).toBeInTheDocument()
  })

  it('narrows the list with ONE reason parameter and nothing else', async () => {
    // T3: was three separate params (`needs_review`, `missing_card_id`,
    // `missing_english_name`), which meant `flagged` narrowed by the stored
    // boolean rather than by the predicate that produced the chip — and a new
    // reason had no param at all.
    mockList([flaggedItem, unlinkedItem, jpItem])
    render(<AdminTriagePage />)
    await screen.findByText(/Pikachu/)

    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'missing_card_id' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ triage: 'true', triage_reason: 'missing_card_id' }),
      ),
    )
    const [, params] = getMock.mock.calls.filter(([p]) => p === '/inventory/search').at(-1)!
    expect(params).not.toHaveProperty('missing_card_id')
    expect(params).not.toHaveProperty('needs_review')
    expect(params).not.toHaveProperty('missing_english_name')
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
// RFC 0010 T3 — the server says why, one filter narrows, the queue can drain
// ===========================================================================

describe('Triage — the server is the authority on why a row is here', () => {
  it('renders the chips the server sent, not a local recompute', async () => {
    // The fixture is deliberately one the LOCAL rules would score as clean: it
    // is linked, English and unflagged, so `reasonsFor()` returns []. If the
    // page still recomputes, this row shows no chip — which is the owner's
    // report ("the WHY column reads empty") reproduced in a test.
    mockList([
      {
        ...flaggedItem,
        needs_review: false,
        review_reason: null,
        card_id: 'en:sv1-25',
        language: 'EN',
        triage_reasons: ['missing_english_name'],
      },
    ])
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    expect(within(row).getByText(/needs english name/i)).toBeInTheDocument()
  })

  it('renders a machine reason as a sentence instead of a snake_case key', async () => {
    mockList([{ ...flaggedItem, review_reason: 'low_match_confidence' }])
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    expect(within(row).getByText(/matcher wasn't sure/i)).toBeInTheDocument()
    expect(within(row).queryByText('low_match_confidence')).not.toBeInTheDocument()
  })

  it('leaves sold and closed cards out until the admin asks for them', async () => {
    // A sold card's data quality is not a worklist item — it sat in this queue
    // forever with nothing that could ever remove it.
    mockList([flaggedItem])
    render(<AdminTriagePage />)
    await screen.findByText(/Pikachu/)

    fireEvent.click(screen.getByLabelText(/include sold/i))

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ triage: 'true', include_terminal: 'true' }),
      ),
    )
  })
})

describe('Triage — clearing machine flags in bulk', () => {
  const machineFlagged = {
    ...flaggedItem,
    item_id: 'machine-1',
    review_reason: 'manual_entry',
    bulk_clearable: true,
    card: { ...flaggedItem.card, name: 'Machop' },
  }

  it('names the exact number it is about to clear, never "clear all"', async () => {
    mockList([
      machineFlagged,
      {
        ...machineFlagged,
        item_id: 'machine-2',
        card: { ...flaggedItem.card, name: 'Squirtle' },
      },
      // Human note: not clearable, and must not be counted.
      { ...flaggedItem, bulk_clearable: false },
    ])
    render(<AdminTriagePage />)
    await screen.findByText(/Machop/)

    fireEvent.click(screen.getByRole('button', { name: /clear machine flags/i }))

    const confirm = await screen.findByRole('dialog', { name: /clear machine flags/i })
    expect(within(confirm).getByText(/\b2\b/)).toBeInTheDocument()
    // Scoped to the bulk route: `useCardImages` POSTs on every render, so a
    // bare "post was never called" would fail for an unrelated reason.
    expect(
      postMock.mock.calls.filter(([p]) => p === '/inventory/bulk-clear-review'),
    ).toHaveLength(0)
  })

  it('sends the filter it is looking at, and refetches once it lands', async () => {
    mockList([machineFlagged])
    postMock.mockResolvedValue({ cleared: 1 })
    render(<AdminTriagePage />)
    await screen.findByText(/Machop/)

    fireEvent.click(screen.getByRole('button', { name: /clear machine flags/i }))
    const confirm = await screen.findByRole('dialog', { name: /clear machine flags/i })
    fireEvent.click(within(confirm).getByRole('button', { name: /^clear \d+/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/inventory/bulk-clear-review',
        expect.objectContaining({ include_terminal: false }),
      ),
    )
  })

  it('offers nothing to clear when no row carries a machine flag', async () => {
    // Measured against the live table 2026-08-11: this is the CURRENT state —
    // 27 rows, none of them bulk-clearable. A button promising to clear zero
    // things is worse than no button.
    //
    // NOTE: passes before the change, because no such button exists yet. It is
    // the pin that keeps the new button from rendering unconditionally.
    mockList([flaggedItem, unlinkedItem])
    render(<AdminTriagePage />)
    await screen.findByText(/Pikachu/)

    expect(screen.queryByRole('button', { name: /clear machine flags/i })).toBeNull()
  })
})

describe('Triage — setting the condition on a card in hand', () => {
  it('sends the tier and the modifier as SEPARATE fields', async () => {
    // Never a combined "LP+" — storage is always two fields, and sending the
    // combined form is the Round 1 enum-validation bug (CLAUDE.md).
    mockList([flaggedItem])
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    fireEvent.change(within(row).getByLabelText(/condition/i), { target: { value: 'LP+' } })

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/flagged-1', {
        condition: 'LP',
        condition_modifier: '+',
      }),
    )
  })

  it('offers every condition an admin can grade a card as', async () => {
    mockList([flaggedItem])
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    const select = within(row).getByLabelText(/condition/i)
    expect(
      Array.from(select.querySelectorAll('option')).map((o) => o.textContent),
    ).toEqual(['NM', 'LP+', 'LP', 'LP-', 'MP', 'HP', 'DMG'])
  })

  it('updates the row in place, without refetching the whole queue', async () => {
    // Same reason as "Priced -> removed" on the Prep Queue: a round-trip here
    // makes every fix feel like it hung.
    mockList([flaggedItem])
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    const searchCalls = getMock.mock.calls.filter(([p]) => p === '/inventory/search').length

    fireEvent.change(within(row).getByLabelText(/condition/i), { target: { value: 'MP' } })

    await waitFor(() => expect(putMock).toHaveBeenCalled())
    const select = within(await findRow(/Pikachu/)).getByLabelText(
      /condition/i,
    ) as HTMLSelectElement
    expect(select.value).toBe('MP')
    expect(getMock.mock.calls.filter(([p]) => p === '/inventory/search')).toHaveLength(
      searchCalls,
    )
  })

  it('says so when the condition does not save, instead of showing the new value', async () => {
    // A silent failure here is a price left wrong on the customer site.
    mockList([flaggedItem])
    putMock.mockRejectedValue(new Error('nope'))
    render(<AdminTriagePage />)

    const row = await findRow(/Pikachu/)
    fireEvent.change(within(row).getByLabelText(/condition/i), { target: { value: 'MP' } })

    expect(await screen.findByText(/could not update that condition/i)).toBeInTheDocument()
    const select = within(await findRow(/Pikachu/)).getByLabelText(
      /condition/i,
    ) as HTMLSelectElement
    expect(select.value).toBe('NM')
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

// ===========================================================================
// Card art in the queue
// ===========================================================================

describe('AdminTriagePage card art', () => {
  // Triage is where an admin decides what a card actually IS, and for the
  // `missing_english_name` case the name on the row is the one thing they
  // cannot read. The art is the identifying detail, so it belongs in the
  // identity cell next to the name rather than in a column of its own.
  it('shows the card art beside the name once images resolve', async () => {
    mockList([jpItem])
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/card-images') {
        return Promise.resolve({ 'ja:M4-084': 'https://img.example/harimaron.png' })
      }
      return Promise.resolve({})
    })

    render(<AdminTriagePage />)

    const img = await screen.findByRole('img')
    expect(img).toHaveAttribute('src', 'https://img.example/harimaron.png')
    // Same identity cell as the name, not a detached column.
    expect(within(await findRow(/ハリマロン/)).getByRole('img')).toBe(img)
  })

  it('requests art only for items that have a catalog link', async () => {
    // `missing_card_id` items have nothing to look up. Asking for them anyway
    // would put null keys in the batch and make the placeholder look like a
    // failed fetch rather than the expected state for an unlinked item.
    mockList([jpItem, unlinkedItem])
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/card-images') return Promise.resolve({})
      return Promise.resolve({})
    })

    render(<AdminTriagePage />)
    await screen.findByText(/Charizard/)

    await waitFor(() => {
      const call = postMock.mock.calls.find(([p]) => p === '/inventory/card-images')
      expect(call).toBeDefined()
      expect(call![1].card_ids).toEqual(['ja:M4-084'])
    })
  })

  it('holds the row height with a placeholder when a card has no art', async () => {
    // An unlinked item still needs the same-size box, or the rows jog sideways
    // as the reader scans down the queue.
    mockList([unlinkedItem])
    render(<AdminTriagePage />)

    const row = await findRow(/Charizard/)
    expect(within(row).getByLabelText(/no image/i)).toBeInTheDocument()
  })
})

// ===========================================================================
// RFC 0010 T15 — the catalog picker shows the card, not just its name
// ===========================================================================

describe('AdminTriagePage catalog picker (RFC 0010 T15)', () => {
  // The report that produced the standing CLAUDE.md rule came from THIS page:
  // on the `missing_english_name` queue the item's name is in Japanese, so a
  // name-only candidate list asks the admin to choose between rows they
  // literally cannot read.
  const priced = {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_name: 'Base Set',
    number: '004',
    rarity: 'Rare Holo',
    images: { small: 'https://img.example/zard.png' },
    display_price: '189.99',
    display_finish: 'holofoil',
    detail: 'full',
    last_synced_at: new Date().toISOString(),
  }

  function mockPicker(item: unknown) {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') return Promise.resolve({ items: [item], total: 1 })
      if (path === '/market/search') return Promise.resolve({ items: [priced], total: 1 })
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })
  }

  async function openPicker(button: RegExp) {
    fireEvent.click(await screen.findByRole('button', { name: button }))
    fireEvent.change(await screen.findByLabelText(/search the catalog/i), {
      target: { value: 'Charizard' },
    })
    return screen.findByTestId('card-picker-row')
  }

  it('shows the art and the price in the re-point dialog', async () => {
    mockPicker(flaggedItem)
    render(<AdminTriagePage />)

    const row = await openPicker(/re-point/i)
    expect(within(row).getByAltText('Charizard')).toHaveAttribute('src', 'https://img.example/zard.png')
    expect(within(row).getByTestId('card-picker-price').textContent).toContain('$189.99')
  })

  it('shows the art and the price in the name dialog', async () => {
    mockPicker(jpItem)
    render(<AdminTriagePage />)

    const row = await openPicker(/assign english name/i)
    expect(within(row).getByAltText('Charizard')).toHaveAttribute('src', 'https://img.example/zard.png')
    expect(within(row).getByTestId('card-picker-price').textContent).toContain('$189.99')
  })

  it('still reaches the two-stage confirm when a re-point candidate is picked', async () => {
    mockPicker(flaggedItem)
    render(<AdminTriagePage />)

    const row = await openPicker(/re-point/i)
    fireEvent.click(within(row).getByRole('button', { name: /Charizard/ }))

    const confirm = await screen.findByRole('dialog', { name: /confirm re-point/i })
    expect(putMock).not.toHaveBeenCalled()
    fireEvent.click(within(confirm).getByRole('button', { name: /confirm/i }))
    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/flagged-1', { card_id: 'en:base1-4' }),
    )
  })

  it('still writes ONLY display_name_override from the name dialog', async () => {
    // The one rule in this feature that must not break. A row that now carries
    // a `card_id`, art and a price is exactly the row a reader would assume
    // re-links the item — it must not.
    mockPicker(jpItem)
    render(<AdminTriagePage />)

    const row = await openPicker(/assign english name/i)
    fireEvent.click(within(row).getByRole('button', { name: /use this name/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/jp-1', {
        display_name_override: 'Charizard',
      }),
    )
    expect(putMock.mock.calls[0][1]).not.toHaveProperty('card_id')
  })
})
