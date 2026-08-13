# T8 — `/admin/unmatched`, the queue page

**RFC:** 0011 §E · **Layer:** frontend · **Depends on:** T5, T6, T7 · **Blocks:** T10
**Owner ask:** *"there should be a new tab that is just for cards that do not have a
match in TCGdex… this tab would let us move cards out of triage, so triage is
specifically for cards that actually have errors."*

## Files

- **Create:** `frontend/app/(admin)/admin/unmatched/page.tsx`
- **Create:** `frontend/app/(admin)/admin/unmatched/__tests__/page.test.tsx`
- **Modify:** `frontend/components/admin/AdminShell.tsx` — one nav entry (line 65-75)
- **Modify:** `frontend/components/admin/__tests__/AdminShell.test.tsx`

## Interfaces

**Consumes:**

- T5: `GET /admin/inventory/search?no_catalog_match=true`; `PUT /admin/inventory/{id}`
  with `{card_id}` (auto-unparks) or `{no_catalog_match: false}`
- T6: `TriageItem` with `no_catalog_match` / `no_catalog_match_at`
- T7: `GET /admin/unmatched/suggestions?limit=3` → `{ items: [{item_id, candidates}],
  items_with_candidates }`, each candidate carrying `card_id, name, set_name, number,
  image_small, market_price, score, why`

## Design

### Sidebar placement

**Back office group, directly after Triage** (`AdminShell.tsx:70`). Label **Unmatched**,
icon `Unlink` from lucide.

Three rules from CLAUDE.md apply and each has a test in `AdminShell.test.tsx`:

- groups default **open**, and the group holding the active route is forced open;
- the Triage badge stays Triage's — **do not add a second badge here.** Two amber counts
  in one group trains the eye to stop reading both. The count lives in the page header
  and on the dashboard widget (T10);
- **`mobileItems` is an explicit list, never a `.slice()` of the groups.** Do not add
  Unmatched to it — the mobile bar is five items and Unmatched is not one of the five you
  use standing at a table.

### The page

Follow `/admin/triage`'s shape — it is the same kind of work — with the vault design
system throughout. **Every control gets `vault-field`**; CLAUDE.md's rule, and the Slabs
page is the cautionary tale.

Header copy matters, because this queue is *not* meant to reach zero the way Triage is:

> **Unmatched**
> **Waiting on the catalog** (12)
> Cards TCGdex does not carry yet. They are priced by hand and will stay here until the
> catalog catches up — this list is not meant to reach zero.

**Art is always on, no toggle.** The list is short by construction and recognising the
card *is* the task — same reasoning as Triage, History and Trade.

| Column | Contents |
|---|---|
| Card | `CardImage size={TABLE_THUMB_SIZE}` + effective name via `adminItemName` + the item's own set/number text |
| Parked | `formatISODate(item.no_catalog_match_at)` — **never `new Date()` on a date-only string** |
| Value | Inline `MoneyInput` writing `current_market_value`; `HandValuedBadge` beside it |
| Suggestions | Up to three `CardPickerRow`s, each with a **Pair** action, plus the score's `why` as secondary text |
| *(actions)* | **Search catalog** · **Back to Triage** |

### Suggestions render through `CardPickerRow`, and the full search is always there

**Owner constraint, verbatim:** *"you must also have the option for the user to search the
whole catalog if none of those candidates match."*

So every row carries a **Search catalog** action — including rows that already have three
strong candidates. Ranked suggestions are a shortcut, never the only door.

**T8 and T11 are independent, so whichever lands SECOND does this wiring:**

- if **T11 has already landed**, open its `CardSearchPanel` (name + number + set) in a
  dialog here, with `onManualEntry` omitted — a parked card is being *paired*, so there is
  nothing to create;
- if **T11 has not landed**, reuse the Triage page's existing `CatalogPicker`, and add a
  row to `follow-ups.md` saying this page still needs the swap. T11's own "Done means"
  checks for that row.

Each candidate row must show **name, image and price** (the absolute owner rule). Two
honesty rules carry over from T7 and must survive into the UI:

- **an absent price renders `—`, never `$0.00` and never a guess.** `FinishPrice` bands
  exist only when a provider published a figure;
- **a catalog price is a NEAR MINT figure and is not condition-adjusted.** Label it
  `Market (NM)`, so nobody reads it as this DMG card's sale price.

### Sorting: candidates first

```tsx
// "Which card can now be paired" is the question this page answers, so rows that
// became actionable float to the top. Within each group, oldest first — a card
// parked in March has waited longer than one parked yesterday.
const ordered = [...items].sort((a, b) => {
  const byCandidates = candidateCount(b) - candidateCount(a)
  if (byCandidates !== 0) return byCandidates
  return (a.no_catalog_match_at ?? '').localeCompare(b.no_catalog_match_at ?? '')
})
```

### Pairing

Confirmed with a before/after diff — the same discipline as `RepointDialog`, because it
is the same write on the same load-bearing field:

> **Pair with Charizard #4 (Base Set)?**
> This card will be linked to `en:base1-4` and will leave the Unmatched queue. Its value
> will be maintained by the nightly sync from then on, replacing the `$40.00` you set by
> hand.

On success: `PUT /inventory/{id}` with `{ card_id }` — **nothing else.** T5 clears
`no_catalog_match` server-side, and sending it here would be a second client-side copy of
a server rule. Then drop the row with no refetch, matching the Prep Queue / Triage
"fixed → removed" pattern.

### Back to Triage

`PUT /inventory/{id}` with `{ no_catalog_match: false }`. Drop the row. This is the
`unarchive` of this feature — parking that cannot be undone is just a slower delete.

### Empty state

The queue **ships empty** and that is correct, so the empty state must not read as
breakage:

> Nothing is waiting on the catalog. Cards get here from Triage, when you confirm TCGdex
> does not carry them.

## RED — write these first, show the failing output, then STOP

`frontend/app/(admin)/admin/unmatched/__tests__/page.test.tsx`:

```tsx
// Dates render here, so pin a negative-offset TZ. `toFake: ['Date']` only —
// full fake timers deadlock waitFor.
import '@/lib/__tests__/_timezone'

describe('AdminUnmatchedPage', () => {
  beforeEach(() => {
    // reset, NOT clearAllMocks — clearAllMocks does not drain a mockResolvedValueOnce
    // queue, and leftovers cascade into the next test.
    apiGet.mockReset()
    apiPut.mockReset()
  })

  it('fetches only the parked cohort', async () => {
    render(<AdminUnmatchedPage />)
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith(
      '/inventory/search', expect.objectContaining({ no_catalog_match: 'true' }),
    ))
  })

  it('says the list is empty without implying something is broken', async () => {
    mockItems([])
    render(<AdminUnmatchedPage />)
    expect(await screen.findByText(/nothing is waiting on the catalog/i)).toBeInTheDocument()
  })

  it('floats rows with candidates to the top', async () => {
    mockItems([
      { item_id: 'none', display_name: 'Zzz', no_catalog_match_at: '2026-01-01T00:00:00Z' },
      { item_id: 'has', display_name: 'Aaa', no_catalog_match_at: '2026-06-01T00:00:00Z' },
    ])
    mockSuggestions({ items: [{ item_id: 'has', candidates: [candidate()] }],
                      items_with_candidates: 1 })
    render(<AdminUnmatchedPage />)

    const rows = await screen.findAllByRole('row')
    expect(rows[1]).toHaveTextContent('Aaa')
  })

  it('shows name, image and price on every candidate', async () => {
    // Owner rule, absolute: a card is never identified by name alone.
    mockItems([{ item_id: 'x', display_name: 'Charizard' }])
    mockSuggestions({ items: [{ item_id: 'x', candidates: [
      candidate({ name: 'Charizard', image_small: 'https://img/1.png',
                  market_price: '100.00' }),
    ] }], items_with_candidates: 1 })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
  })

  it('renders an absent price as a dash, never as zero', async () => {
    // A missing band means no provider published a figure. $0.00 is a lie.
    mockItems([{ item_id: 'x', display_name: 'Charizard' }])
    mockSuggestions({ items: [{ item_id: 'x', candidates: [
      candidate({ market_price: null }) ] }], items_with_candidates: 1 })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('offers a full catalog search even on a row that has candidates', async () => {
    // Owner constraint: ranked suggestions must never be the only door.
    mockItems([{ item_id: 'x', display_name: 'Charizard' }])
    mockSuggestions({ items: [{ item_id: 'x', candidates: [candidate()] }],
                      items_with_candidates: 1 })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByRole('button', { name: /search catalog/i })).toBeInTheDocument()
  })

  it('pairs a card by sending only card_id', async () => {
    const user = userEvent.setup({ delay: null })
    mockItems([{ item_id: 'x', display_name: 'Charizard' }])
    mockSuggestions({ items: [{ item_id: 'x', candidates: [
      candidate({ card_id: 'en:base1-4' }) ] }], items_with_candidates: 1 })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /^pair$/i }))
    await user.click(await screen.findByRole('button', { name: /pair with/i }))

    // The server clears no_catalog_match (T5). Sending it here would be a second
    // client-side copy of a server rule.
    expect(apiPut).toHaveBeenCalledWith('/inventory/x', { card_id: 'en:base1-4' })
  })

  it('sends a card back to triage', async () => {
    const user = userEvent.setup({ delay: null })
    mockItems([{ item_id: 'x', display_name: 'Charizard' }])
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /back to triage/i }))

    expect(apiPut).toHaveBeenCalledWith('/inventory/x', { no_catalog_match: false })
  })

  it('renders the parked date in local time', async () => {
    // new Date('2026-06-01') is UTC midnight and renders as May 31 in every US zone.
    mockItems([{ item_id: 'x', no_catalog_match_at: '2026-06-01T12:00:00Z' }])
    render(<AdminUnmatchedPage />)
    expect(await screen.findByText(/Jun 1, 2026/)).toBeInTheDocument()
  })
})
```

In `AdminShell.test.tsx`:

```tsx
it('puts Unmatched in Back office, after Triage', () => {
  render(<AdminShell><div /></AdminShell>)
  const group = screen.getByRole('group', { name: 'Back office' })
  const labels = within(group).getAllByRole('link').map((l) => l.textContent)
  expect(labels.indexOf('Unmatched')).toBe(labels.indexOf('Triage') + 1)
})

it('does not give Unmatched a second badge', () => {
  // Two amber counts in one group trains the eye to stop reading both.
  render(<AdminShell><div /></AdminShell>)
  const link = screen.getByRole('link', { name: /unmatched/i })
  expect(within(link).queryByTestId('nav-badge')).not.toBeInTheDocument()
})

it('keeps the mobile bar at its explicit five', () => {
  // Never a .slice() of the groups — flattening yields the wrong five.
  render(<AdminShell><div /></AdminShell>)
  const bar = screen.getByRole('navigation', { name: /mobile/i })
  expect(within(bar).queryByText('Unmatched')).not.toBeInTheDocument()
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run "app/(admin)/admin/unmatched" "components/admin/__tests__/AdminShell.test.tsx"
```

## Watch for

- **Do not build a parallel list endpoint.** The list is
  `GET /admin/inventory/search?no_catalog_match=true`. Triage's router docstring explains
  the rule; the same applies here.
- **Do not add a sidebar badge.** See above.
- **`MoneyInput`, never `type="number"`, never `parseFloat`.** The Value column is a money
  field and the owner types `1,300`.
- **`formatISODate` / `parseISODateLocal`** from `lib/dates.ts` for the Parked column.
- **`useCardImages` is not needed for candidates** — T7 returns `image_small` directly.
  Use it only if you render art for the *parked item itself*, which has no `card_id` and
  will therefore always render the placeholder. Prefer showing the placeholder to firing
  a lookup that cannot succeed.

## Done means

1. both test files pass, output shown;
2. `npm run lint --workspace=frontend` clean;
3. by hand: park a card from Triage (T6), see it land here, pair it from a suggestion,
   watch it leave; send another back to Triage;
4. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
