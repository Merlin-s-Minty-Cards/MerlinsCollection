# T10 — "New from TCGdex" dashboard widget

**RFC:** 0011 §F.3 · **Layer:** frontend · **Depends on:** T7, T9 · **Blocks:** —
**Owner ask:** *"if there could be some kind of widget on the dashboard to show any new
cards from TCGdex, that would be great, and then we can look at the new tab to see which
card can now be paired."*

## Files

- **Modify:** `frontend/app/(admin)/admin/page.tsx` — one more `soft()` read in the
  existing `Promise.all` (line 59-72), one card in the *Needs attention* section
  (line 131-159)
- **Test:** `frontend/app/(admin)/admin/__tests__/page.test.tsx`

## Interfaces

**Consumes:**

- T9: `GET /admin/catalog/new-cards?since_days=30` → `{ count, since, cards[] }`
- T7: `GET /admin/unmatched/suggestions` → `{ items[], items_with_candidates }`

## Design

### Two numbers, and only one of them is a call to action

- **N** — catalog cards first seen in 30 days. Context: *the catalog moved.*
- **M** — parked cards that now have a candidate. **This is the number that changes what
  the admin does next**, so it leads.

The card belongs in **Needs attention**, next to Triage and Prep Queue, because that
section is defined as "the only section that changes what the admin does next"
(`page.tsx:129-130`). But it must not behave like the others in one respect:

> **`allClear` must not depend on it.** `allClear` (`page.tsx:96-98`) currently means
> "every queue is drained". New catalog cards are *news*, not work — a week where TCGdex
> published nothing is not an achievement, and folding N into `allClear` would make the
> "Nothing needs attention" panel vanish whenever the catalog happened to move. Add **M**
> — pairable cards, which genuinely is work — to `actionCounts`, and leave N out.

### Reuse `ActionCard`, do not invent a shape

`ActionCard` (`page.tsx:280-312`) already renders "label, hint, count, link, amber when
non-zero". Use it:

```tsx
<ActionCard
  testId="action-pairable"
  href="/admin/unmatched"
  label="Ready to pair"
  hint={
    newCards === null
      ? 'Unmatched cards with a match'
      : `${newCards} new catalog card${newCards === 1 ? '' : 's'} in 30 days`
  }
  icon={<Sparkles size={16} />}
  count={loading ? null : stats?.pairableCount ?? null}
/>
```

**The count is M, the hint carries N.** A card whose big number is "47 new catalog cards"
and whose link goes to a queue with nothing to do in it is a card that trains the eye to
ignore it.

### Soft-failed, like every other panel

```tsx
soft(api.get<NewCards>('/catalog/new-cards', { since_days: '30' })),
soft(api.get<Suggestions>('/unmatched/suggestions')),
```

`soft()` (`page.tsx:41-44`) resolves to `null` instead of throwing, so one dead endpoint
costs one card and not the dashboard. Both new reads join the existing `Promise.all`.

### Zero is honest, and it will be zero at first

**Every one of the 31,603 existing catalog rows has a null `first_seen_at`** (T9), so
until the next sync runs, N is genuinely `0`. That is correct. The copy must not imply
otherwise — no "no new cards yet, check back soon", which reads as a broken feature.
`ActionCard` already renders `0` in the calm grey style rather than the amber one, which
is exactly right.

## RED — write these first, show the failing output, then STOP

In `frontend/app/(admin)/admin/__tests__/page.test.tsx`:

```tsx
describe('New from TCGdex', () => {
  beforeEach(() => {
    apiGet.mockReset()   // never clearAllMocks — it does not drain the Once queue
  })

  it('counts pairable cards, not new catalog cards', async () => {
    // The number that changes what the admin does next is M, not N.
    mockDashboard({
      newCards: { count: 47, since: '2026-07-14', cards: [] },
      suggestions: { items: [], items_with_candidates: 3 },
    })
    render(<AdminDashboardPage />)

    const card = await screen.findByTestId('action-pairable')
    expect(within(card).getByText('3')).toBeInTheDocument()
    expect(within(card).getByText(/47 new catalog cards in 30 days/)).toBeInTheDocument()
  })

  it('links to the unmatched queue', async () => {
    mockDashboard({ suggestions: { items: [], items_with_candidates: 1 } })
    render(<AdminDashboardPage />)
    expect((await screen.findByTestId('action-pairable')).closest('a'))
      .toHaveAttribute('href', '/admin/unmatched')
  })

  it('survives a dead endpoint without blanking the dashboard', async () => {
    // soft(): one broken endpoint costs one panel, not the page.
    mockDashboard({ newCardsFails: true, suggestionsFails: true })
    render(<AdminDashboardPage />)

    expect(await screen.findByTestId('stat-on-hand')).toBeInTheDocument()
    expect(within(screen.getByTestId('action-pairable')).getByText('—')).toBeInTheDocument()
  })

  it('does not let new catalog cards suppress the all-clear panel', async () => {
    // News is not work. A week where TCGdex published is not a week with a chore.
    mockDashboard({
      triage: 0, prepQueue: 0, mispriced: 0,
      newCards: { count: 47, since: '2026-07-14', cards: [] },
      suggestions: { items: [], items_with_candidates: 0 },
    })
    render(<AdminDashboardPage />)

    expect(await screen.findByText(/every queue is clear/i)).toBeInTheDocument()
  })

  it('does suppress the all-clear when cards are pairable', async () => {
    mockDashboard({
      triage: 0, prepQueue: 0, mispriced: 0,
      suggestions: { items: [], items_with_candidates: 2 },
    })
    render(<AdminDashboardPage />)

    expect(screen.queryByText(/every queue is clear/i)).not.toBeInTheDocument()
  })

  it('shows a calm zero rather than implying the feature is broken', async () => {
    // Every pre-RFC-0011 catalog row has a null first_seen_at, so N is legitimately
    // 0 until the next sync. That is the honest answer, not an error state.
    mockDashboard({
      newCards: { count: 0, since: '2026-07-14', cards: [] },
      suggestions: { items: [], items_with_candidates: 0 },
    })
    render(<AdminDashboardPage />)

    const card = await screen.findByTestId('action-pairable')
    expect(within(card).getByText('0')).toBeInTheDocument()
    expect(within(card).queryByText(/check back/i)).not.toBeInTheDocument()
  })
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run "app/(admin)/admin/__tests__/page.test.tsx"
```

## Watch for

- **Do not add N to `actionCounts`.** The all-clear test above is the guard; read the
  reasoning in the Design section before "fixing" it.
- **Both reads go inside the existing `Promise.all`**, not in a second effect — the
  dashboard does six independent reads in one pass and a seventh belongs with them.
- **The effect's dependency array is `[api.isAuthenticated]` with an eslint-disable**
  (`page.tsx:90`). Leave it exactly as it is; changing it re-fetches the dashboard on
  every render.
- **`Sparkles` from lucide-react** — check it is imported; the file imports icons
  individually at line 5-19.

## Done means

1. the dashboard test file passes, output shown;
2. `npm run lint --workspace=frontend` clean;
3. by hand: with at least one parked card that has a candidate, the card shows a non-zero
   count and links through to `/admin/unmatched`;
4. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
