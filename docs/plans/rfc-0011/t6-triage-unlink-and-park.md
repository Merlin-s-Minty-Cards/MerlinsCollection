# T6 — Unlink-and-park, and the park button

**RFC:** 0011 §D · **Layer:** frontend · **Depends on:** T5 · **Blocks:** T8
**Owner report:** *"there should be a new button in triage to repoint a card to null.
There are cards that are close to the right card but are actually a promo so the price is
completely wrong."*
**Owner decision, 2026-08-13:** *"Repointing to null should automatically move it to the
new tab, but cards that already don't have a matching should also have a button to move
them to the new tab."*

## Two entry points, and they are not the same action

| | on a row that **has** a wrong `card_id` | on a row that **already has none** |
|---|---|---|
| where | inside `RepointDialog` | a row-level button |
| writes | `card_id: null`, `no_catalog_match: true`, `current_market_value: null` | `no_catalog_match: true` |
| then | offers the hand-value tool | nothing — there is no inherited price |

The first lives **inside the re-point dialog**, not as a bare row button. That dialog is
already the codebase's most carefully guarded write — it shows a before/after diff and
warns about trade lineage, because `card_id` drives pricing, images and set membership
(`triage/page.tsx:597-604`). Unlinking is the same write with a null target and belongs
behind the same confirmation.

## Files

- **Modify:** `frontend/app/(admin)/admin/triage/page.tsx` — `RepointDialog` (line 605),
  the `_tools` column (line 276-329), `OpenTool` (line 46)
- **Modify:** `frontend/lib/triage.ts` — `TriageItem` gains the two fields; add
  `parkBody()` and `unlinkBody()`
- **Test:** `frontend/lib/__tests__/triage.test.ts`,
  `frontend/app/(admin)/admin/triage/__tests__/page.test.tsx`

## Interfaces

**Consumes** from T5: `PUT /admin/inventory/{item_id}` accepting `no_catalog_match`, and
the automatic unpark on `card_id` assignment.

**Produces** (T8 reuses the field names; the two bodies are Triage-local):

```ts
// frontend/lib/triage.ts
export interface TriageItem {
  no_catalog_match?: boolean
  no_catalog_match_at?: string | null
  // …existing fields
}
/** Park a row that already has no catalog link. */
export function parkBody(): Record<string, unknown>
/** Unlink a wrongly-matched card AND park it, clearing the inherited price. */
export function unlinkBody(): Record<string, unknown>
```

## Design

### The two bodies, in `lib/triage.ts` beside `clearTriageBody`

```ts
/**
 * Park a row that already has no catalog link.
 *
 * One field. `card_id` is not in this body and must never be — there is nothing to
 * unlink, and sending `card_id: null` on a row that already has none would be a
 * meaningless write on the one field that drives pricing.
 */
export function parkBody() {
  return { no_catalog_match: true }
}

/**
 * Unlink a wrongly-matched card and park it, in ONE write.
 *
 * `current_market_value: null` is not tidiness — it is the whole complaint. The card is
 * pointed at a close-but-wrong promo, so the figure it inherited is that promo's price,
 * and no sync will ever correct it once the link is gone. A leftover wrong number on a
 * customer-facing surface is worse than no number, so it goes, and the hand-value tool
 * opens immediately afterwards.
 *
 * `no_catalog_match_at` is NOT here. The server stamps it (T5); a client-supplied
 * timestamp is a clock we do not control.
 */
export function unlinkBody() {
  return { card_id: null, no_catalog_match: true, current_market_value: null }
}
```

### `RepointDialog` gains a second, destructive action

The dialog currently has one confirm path, gated on a `candidate` being picked
(`triage/page.tsx:643, 700-710`). Add an **"No match in TCGdex"** action that is available
*without* a candidate, styled as the secondary/destructive choice rather than the primary
one — picking the right card is still the main job of this dialog.

It needs its own confirmation copy, because it is doing three things at once:

```tsx
{/* Available with no candidate selected — this is the answer when the catalog has
    nothing to point at. Distinct copy because it does three things, and the admin
    should see all three before clicking. */}
<button
  type="button"
  onClick={() => setConfirmingUnlink(true)}
  className="px-2 py-1 rounded-md text-[11px] text-pine-300 border border-pine-700/60
             hover:text-amber-300 hover:border-amber-400/40 transition-colors"
>
  No match in TCGdex
</button>
```

and the confirm body states each consequence plainly:

> **Move to Unmatched?**
> This card will be unlinked from `en:swshp-SWSH039`, its market value of `$42.00` will
> be cleared, and it will move to the Unmatched queue until the catalog carries it.
> You can set a value by hand next, and pair it later from that queue.

Do not skip this dialog. The parallel is `ConfirmDialog` on `/admin/shows`, whose wording
CLAUDE.md points at as the pattern to mirror for anything that moves a row out of sight.

On success: call `onRepointed(null)` — widen its type to
`(cardId: string | null) => void` — and let the page drop the row. Then open the value
tool:

```tsx
setOpenTool({ item, tool: 'value' })
```

### The row button, gated on the SERVER's reason

```tsx
{/* Only where there is nothing to unlink. Gated on the SERVER's reason, not a local
    `!item.card_id` — T3 of RFC 0010 made `services/triage.reasons_for` the authority
    and this is not the place to open a second one. */}
{(item.triage_reasons ?? []).includes('missing_card_id') && (
  <button
    type="button"
    onClick={() => park(item)}
    className="px-2 py-1 rounded-md text-[11px] text-pine-300 border border-pine-700/60
               hover:text-amber-300 hover:border-amber-400/40 transition-colors"
  >
    No TCGdex match
  </button>
)}
```

`park` follows the page's existing error discipline exactly — `setError` on failure and
leave the row, because a silent failure here looks identical to success:

```tsx
const park = async (item: TriageItem) => {
  setError(null)
  try {
    await api.put(`/inventory/${item.item_id}`, parkBody())
  } catch {
    setError('Could not move that card to Unmatched. It is still in the queue.')
    return
  }
  // Drop it only if `missing_card_id` was its ONLY reason — a flagged or unnamed row
  // keeps that problem and stays put, carrying its remaining chips. `reasonsFor` is a
  // PREDICTION here, not the authority; the row is gone either way.
  const remaining = reasonsFor({ ...item, no_catalog_match: true })
  if (remaining.length === 0) dropRow(item.item_id)
  else setItems((rows) => rows.map((r) =>
    r.item_id === item.item_id
      ? { ...r, no_catalog_match: true, triage_reasons: remaining }
      : r))
}
```

**`frontend/lib/triage.ts`'s `reasonsFor` must mirror T5's suppression** — it is the
prediction used for optimistic updates, and its docstring already says so. Add
`if (item.no_catalog_match) return false` to its `missing_card_id` branch.

## RED — write these first, show the failing output, then STOP

In `frontend/lib/__tests__/triage.test.ts`:

```ts
describe('parkBody / unlinkBody', () => {
  it('park sends only the flag', () => {
    expect(parkBody()).toEqual({ no_catalog_match: true })
  })

  it('unlink clears the inherited promo price', () => {
    // The whole complaint: the card was pointed at a close-but-wrong promo, so the
    // figure it inherited is that promo's price and no sync will ever fix it.
    expect(unlinkBody()).toEqual({
      card_id: null, no_catalog_match: true, current_market_value: null,
    })
  })

  it('never sends a client-side timestamp', () => {
    // The server stamps no_catalog_match_at. A client clock is not ours to trust.
    expect(unlinkBody()).not.toHaveProperty('no_catalog_match_at')
    expect(parkBody()).not.toHaveProperty('no_catalog_match_at')
  })
})

describe('reasonsFor mirrors the server suppression', () => {
  it('drops missing_card_id once the item is parked', () => {
    expect(reasonsFor({ item_id: 'x', kind: 'raw', card_id: null,
                        no_catalog_match: true })).toEqual([])
  })

  it('keeps a flag that is a real error', () => {
    expect(reasonsFor({ item_id: 'x', kind: 'raw', card_id: null,
                        no_catalog_match: true, needs_review: true })).toEqual(['flagged'])
  })
})
```

In the Triage page test:

```tsx
it('offers "No TCGdex match" only on rows that have no catalog link', async () => {
  // Gated on the SERVER's reason, never a local !item.card_id.
  mockSearch([
    { item_id: 'unlinked', kind: 'raw', card_id: null,
      triage_reasons: ['missing_card_id'] },
    { item_id: 'flagged', kind: 'raw', card_id: 'en:base1-4', needs_review: true,
      triage_reasons: ['flagged'] },
  ])
  render(<AdminTriagePage />)

  expect(await screen.findAllByRole('button', { name: 'No TCGdex match' })).toHaveLength(1)
})

it('parks a card and drops it from the queue', async () => {
  const user = userEvent.setup({ delay: null })
  mockSearch([{ item_id: 'x', kind: 'raw', card_id: null,
                triage_reasons: ['missing_card_id'] }])
  render(<AdminTriagePage />)

  await user.click(await screen.findByRole('button', { name: 'No TCGdex match' }))

  expect(apiPut).toHaveBeenCalledWith('/inventory/x', { no_catalog_match: true })
  await waitFor(() => expect(screen.queryByText(/x/)).not.toBeInTheDocument())
})

it('keeps a parked row that is also flagged', async () => {
  const user = userEvent.setup({ delay: null })
  mockSearch([{ item_id: 'x', kind: 'raw', card_id: null, needs_review: true,
                triage_reasons: ['flagged', 'missing_card_id'] }])
  render(<AdminTriagePage />)

  await user.click(await screen.findByRole('button', { name: 'No TCGdex match' }))

  // Parking answers ONE question. The human's flag is a different, real problem.
  expect(await screen.findByText('Flagged for review')).toBeInTheDocument()
})

it('says so when parking fails, and leaves the row', async () => {
  const user = userEvent.setup({ delay: null })
  apiPut.mockRejectedValueOnce(new Error('nope'))
  mockSearch([{ item_id: 'x', kind: 'raw', card_id: null,
                triage_reasons: ['missing_card_id'] }])
  render(<AdminTriagePage />)

  await user.click(await screen.findByRole('button', { name: 'No TCGdex match' }))

  // A silent failure here looks identical to success.
  expect(await screen.findByText(/still in the queue/i)).toBeInTheDocument()
})

it('unlinking a wrong match clears its price and parks it', async () => {
  const user = userEvent.setup({ delay: null })
  mockSearch([{ item_id: 'x', kind: 'raw', card_id: 'en:swshp-SWSH039',
                current_market_value: '42.00', triage_reasons: ['flagged'] }])
  render(<AdminTriagePage />)

  await user.click(await screen.findByRole('button', { name: 'Re-point' }))
  await user.click(await screen.findByRole('button', { name: 'No match in TCGdex' }))
  await user.click(await screen.findByRole('button', { name: /move to unmatched/i }))

  expect(apiPut).toHaveBeenCalledWith('/inventory/x', {
    card_id: null, no_catalog_match: true, current_market_value: null,
  })
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run lib/__tests__/triage.test.ts "app/(admin)/admin/triage/__tests__/page.test.tsx"
```

## Watch for

- **`mockReset()` in `beforeEach`, never `clearAllMocks()`.** This file queues
  `mockResolvedValueOnce` replies heavily.
- **`userEvent.setup({ delay: null })`** in every test above.
- **Do not add the unlink action to `CardDetailModal`.** It reaches six pages, and an
  irreversible-looking price-clearing write does not belong on a general detail modal
  without the diff and the warnings the re-point dialog provides.
- **`onRepointed`'s type widens to `string | null`.** Check the call site at
  `triage/page.tsx:479-489` — its optimistic `reasonsFor` prediction needs the parked
  flag too, or the row briefly re-renders with a `missing_card_id` chip before dropping.
- **The confirm dialog must name the price it is about to clear.** A dialog that says
  "this will be unlinked" and silently wipes `$42.00` is the kind of surprise this
  codebase writes confirmation copy to prevent.

## Done means

1. both test files pass, output shown;
2. `npm run lint --workspace=frontend` clean;
3. by hand on `/admin/triage`: park an unlinked card and watch it leave; unlink a matched
   one, read the confirm copy, confirm the value tool opens afterwards;
4. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
