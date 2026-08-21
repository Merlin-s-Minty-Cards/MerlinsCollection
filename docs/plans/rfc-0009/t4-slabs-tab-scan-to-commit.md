# T4 — The Slabs tab: enter → stage → commit

> # ⚠️ REWRITTEN 2026-08-08 — this doc now describes the feature AS BUILT
>
> **What this file used to say cannot be built.** It described a
> **scan → PSA-lookup → stage → commit** pipeline resting on
> `GET /admin/slabs/lookup/{cert}`. PSA's cert API returns **403 at the account
> level**, so that endpoint does not exist and is not being built, and every flag,
> badge and quota poll that hung off it went with it.
>
> **The authority is, and remains:**
> [`docs/superpowers/plans/2026-08-08-slab-manual-entry.md`](../../superpowers/plans/2026-08-08-slab-manual-entry.md)
> — Tasks 3–6, backed by
> [the design spec](../../superpowers/specs/2026-08-08-slab-manual-entry-design.md).
> **Those tasks are COMPLETE** (`c5b5a00`, `164d3b0`, `cb0b59f`, `ec56727`). This
> document is now a *description of what shipped*, not an instruction to build it —
> if you are implementing, read the plan; if you are trying to understand the tab,
> read this.
>
> **What changed from the original:** T4 **depends on T3 only**, not T2. There is no
> `/lookup` call, no `degraded_reason` badge table and no quota polling. The commit
> section survived the re-plan unaltered and is carried forward below. The
> manual-typing requirements survived too — they are now the *primary* path rather
> than the fallback.
>
> The superseded scan-and-lookup text is not reproduced here; it is in this file's
> git history, and in RFC §7/§8 which still describe the unbuilt PSA flow.

**RFC:** 0009 §8 · **Layer:** frontend · **Depends on: T3** (~~T2, T3~~) ·
**Blocks:** T6 · **Status: DONE 2026-08-08**

**This was the milestone, and it is met.** A stack of slabs becomes real, costed
inventory with **no scanner, no camera and no PSA**. Everything after this adds
pricing and polish to a working product.

## Files as built

- **Created:** `frontend/app/(admin)/admin/slabs/page.tsx` — batch state, the
  three-call commit
- **Created:** `frontend/components/admin/slabs/CertInput.tsx` — the cert field
- **Created:** `frontend/components/admin/slabs/SlabEntryForm.tsx` — the form; emits
  one staged row via `onAdd`
- **Created:** `frontend/components/admin/slabs/StagingTable.tsx` — the batch
- **Modified:** `frontend/components/admin/AdminShell.tsx` — `navItems`
- **Tests:** `frontend/components/admin/slabs/__tests__/{CertInput,SlabEntryForm,StagingTable}.test.tsx`
  and `frontend/app/(admin)/admin/slabs/__tests__/page.test.tsx` — **20 passing**

Note the component named `ScanInput` in the original plan **does not exist**. It is
`CertInput`, and the rename is meaningful: the field is named for what it holds, not
for one of the two ways of filling it.

## Sidebar

Inserted **after Buy** in `navItems` (it is an acquisition flow):

```tsx
{ href: '/admin/buy', label: 'Buy', icon: ShoppingBag },
{ href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
{ href: '/admin/trade', label: 'Trade', icon: ArrowRightLeft },
```

`ScanLine` is a lucide-react icon, the library already in use there.

## The form

The operator is the source of identity, grade and cost. There is no lookup.

| Field | Behaviour |
|---|---|
| Cert number | Typed, or scanned into the same field. **Required — see below.** Duplicate check on blur |
| Card | Catalog autocomplete, 300 ms debounce, `api.get('/market/search', { name })` → `GET /admin/market/search`. Selecting a suggestion sets `card_id` |
| *(fallback)* Card name | The same input, free text. Typing after a selection clears `card_id` back to `null` |
| Company | Defaults `PSA`, editable — this is what makes CGC/BGS/SGC ordinary rather than special |
| Grade | Numeric, half grades allowed (`9.5`). Required |
| Grade label | Optional free text, e.g. `GEM MT 10` |
| Cost | Required. **Never guessed** |
| Location | `useLocations()`. Never a hardcoded list |

**No condition control.** Conditions are meaningless for a slab, and the customer
surface already skips the condition multiplier for graded items.

### The cert number is required, and that is a definition rather than a constraint

Owner decision, 2026-08-08: **without a cert number it is not a slab, it is just a
normal card.** The cert is what a graded item *is* — a third party's identified,
encapsulated judgement — so an entry lacking one does not belong in this flow.

Two mechanical facts agree, which is how we know the rule is sound rather than merely
convenient: `GradedInventoryItem.cert_number` is `str`, not `str | None`
(`models/inventory.py:307`), and the cert is the key of T1's `CERT#` pointer row, so
there is nowhere to file a slab without one.

**So the form offers no "no cert" escape**, and the empty-cert message points the
operator at the Buy page, which creates raw items. Silently accepting a graded item
with a blank cert would produce a row that is neither a working slab nor a correct
raw card.

This raises the stakes on hand entry: for a slab whose label is scuffed or whose
barcode will not read, typing the cert is the difference between entering that slab
and not entering it at all.

### `CertInput` — one path for scanner and keyboard

A wedge scanner is a keyboard that types fast and ends with Enter. So there is **no
scanner detection and deliberately no timing logic**: submission is never gated on
typing speed. A cert typed slowly over ten seconds is exactly as valid as one scanned
in 40 ms.

**Enter *advances*, it does not submit.** The scanner's trailing Enter arrives long
before card, grade and cost are filled, so `onEnter` moves focus to the Card field
and the batch row is added by the explicit **Add to batch** button. Trailing `\r` and
`\n` are stripped on the way in, so the value never carries invisible characters into
a URL path.

### Duplicate check

On cert blur, `GET /admin/slabs/certs/{cert}?company=`. T1's contract: **`owned:
false` is a 200**, not a 404. A hit renders a warning naming the item and its status,
and **never blocks** — re-buying a slab you sold is legitimate (RFC §9). A check that
*threw* sets the warning back to `null` rather than showing an error: a failed check
is not evidence the cert is unowned, and it must never block the add.

## The staging table

Rows are **client state only** until commit; nothing is persisted before then.
`StagingTable` is **presentational** — `rows` and `onRemove`, no state, no api calls
(owner constraint, Task 5). It renders cert, card, company, grade and cost, marks a
row with no `card_id` as **"no catalog link"** so the operator knows up front that it
lands in Triage with no automatic price, and offers a per-row Remove.

**Two things the design doc specifies are NOT implemented**, deferred by explicit
owner decision on 2026-08-08 and recorded in [`follow-ups.md`](follow-ups.md) T4.
Do not read this section as claiming them:

1. **Per-row commit gating.** The spec's "commit is disabled while any row lacks a
   cost or a grade, and the button says which" is in neither `StagingTable` nor the
   page — the page gates only on `busy || rows.length === 0`. It is **unreachable by
   construction today**: `SlabEntryForm` refuses to emit a row with a blank grade or
   cost, and the table has no edit path. **It becomes real the moment per-row editing
   is added**, and whoever builds that must add the gating in the same change.
2. **Per-row edit.** The original spec promised it; it was not built.

## Commit

One action, three calls, in order. **The buy-session router's prefix is
`/purchases`, not `/buys`** — the session id is called `buy_id` but the route is not:

1. `POST /admin/purchases` → `buy_id`
2. `POST /admin/purchases/{buy_id}/items` per row, with `kind: "graded"` and the slab
   fields from T3
3. `POST /admin/purchases/{buy_id}/confirm`

**`buy_price` and `grade` go as JSON numbers**, not strings — that is what the backend
handles and what T3 tested (CLAUDE.md's float landmine). Do not stringify them here
to dodge it.

**`manual_entry` is deliberately never sent.** Every slab on this tab is typed by
hand, so sending it would flag the entire shelf into Triage — see the review-flagging
amendment in `t3-buy-session-graded.md` and RFC §9.

**Partial failure does not half-commit.** If step 2 fails on row 4 of 10, the flow
stops, every staged row stays on screen, the error names what failed, and the draft
session is left unconfirmed — a session that is never confirmed creates no inventory,
so the safe state is "do nothing".

On success: a `role="status"` line with count and total, and the table clears.
**Focus is not returned to the cert field** — the design doc requires it and it was
deferred (follow-ups T4, second row). It is the one ergonomic gap in the flow, and
cheap to close before the tab sees real use.

## Tests as built

```bash
cd frontend && npx vitest run components/admin/slabs "app/(admin)/admin/slabs" --reporter=verbose
```

20 passing. The CLI filter's parentheses are matched literally as a path substring,
not as a regex group, so no escaping is needed beyond the shell quotes.

**`CertInput` (6)** — a scanner burst keeps its digits; trailing `\r\n` is stripped;
Enter fires `onEnter`; characters typed one at a time over a long span are exactly as
valid as a burst (**this is the regression a speed-gated implementation
introduces**); Enter on a blank value does nothing; blur fires `onBlur` for the
duplicate check.

**`SlabEntryForm` (5)** — a blank cert blocks the add and the message points at the
Buy page; a hand-typed card adds a row with `card_id: null`; choosing a catalog
suggestion sets `card_id`; an already-owned cert warns **and still allows the add**;
company defaults to PSA and accepts CGC.

**`StagingTable` (4)** — a row renders cert, card, grade and cost; a row with no
`card_id` renders "no catalog link"; Remove passes the row key; an empty batch
renders the "nothing staged" note.

**Page (5)** — commit posts create → items → confirm in that order with
`kind: "graded"`; `buy_price` and `grade` are JSON **numbers**; `manual_entry` is
**never** sent; a failure on the item post does **not** call confirm and leaves the
rows on screen; success clears the batch and reports the total.

> **A test trap worth keeping.** The form renders both `Grade` and `Grade label`, so
> an unanchored `getByLabelText(/grade/i)` matches two elements and throws
> `Found multiple elements` — dedupe only collapses one element reached twice. Every
> grade query is anchored **`/^grade$/i`**. The label is correct; the regex was the
> defect. If a `grade_label` column is ever added to `StagingTable`, its `/9\.5/`
> text query becomes ambiguous with `"MINT 9.5"` in the same way.

## Frontend conventions — followed, do not reinvent

- `frontend/app/(admin)/admin/buy/page.tsx` is the model for catalog autocomplete,
  in particular its `searchSeqRef` **sequence guard**, which stops a slow search from
  overwriting a newer one's results. That guard is mirrored here.
- **The Buy page's `!api.isAuthenticated` guard is deliberately NOT mirrored** — a
  test's mock api has no such field, so copying it makes every catalog search return
  early and the autocomplete fail for a reason unrelated to the form.
- `useAdminApi` as `AdminShell` does; never a hand-rolled `fetch` with auth headers.
  It exposes `get(path, params)` with params as a bare second argument.
- Item names: `adminItemName` (`frontend/lib/admin-item-name.ts`). **Never** inline
  `display_name || product_name` (CLAUDE.md).
- Locations: `useLocations()` — which returns **`options`**, not `locations`.
- Conditions do not apply to slabs — no condition control.

## Manual check before calling it done

Run the app and type a real slab in end to end. A test suite cannot tell you whether
the field order feels right with a stack of slabs in hand, and that is the one thing
this feature lives or dies on.

## Commit

Landed across four commits, one per plan task:

```
c5b5a00  feat(slabs): cert input serving scanner and keyboard equally
164d3b0  feat(slabs): slab entry form with catalog autocomplete and manual fallback
cb0b59f  feat(slabs): staging table for a slab intake batch
ec56727  feat(slabs): manual slab intake tab, scan to committed inventory
```

[`progress.md`](progress.md) records T4 `DONE` with those shas, and the four
out-of-scope findings are in [`follow-ups.md`](follow-ups.md) T4.
