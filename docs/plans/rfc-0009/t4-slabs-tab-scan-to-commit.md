# T4 — The Slabs tab: scan → stage → commit

> # ⛔ SUPERSEDED 2026-08-08 — DO NOT EXECUTE THIS DOCUMENT
>
> This describes a **scan → PSA-lookup → stage → commit** pipeline. **It cannot be
> built.** PSA's cert API returns 403 at the account level, so the
> `/admin/slabs/lookup/{cert}` endpoint every flag and badge below depends on does
> not exist and is not being built.
>
> **Build this instead:**
> [`docs/superpowers/plans/2026-08-08-slab-manual-entry.md`](../../superpowers/plans/2026-08-08-slab-manual-entry.md)
> — Tasks 3–6. An entry form with catalog autocomplete and a free-text fallback,
> feeding the same staging table and the same three-call commit.
>
> **What changed:** T4 now **depends on T3 only**, not T2. There is no `/lookup`
> call, no `degraded_reason` badge table, and no quota polling. The commit section
> below is still accurate and is carried forward. The manual-typing requirements
> below are still binding — they are now the *primary* path rather than the fallback.
>
> Kept unedited as the record of what was originally specified.

**RFC:** 0009 §8 · **Layer:** frontend · ~~**Depends on:** T2, T3~~ →
**Depends on: T3** · **Blocks:** T6

**This is the milestone.** When T4 lands, the feature is usable end to end: a stack
of slabs becomes real, costed inventory. Everything after this adds pricing and
polish to a working product.

## Files

- **Create:** `frontend/app/(admin)/admin/slabs/page.tsx`
- **Create:** `frontend/components/admin/slabs/ScanInput.tsx`
- **Create:** `frontend/components/admin/slabs/StagingTable.tsx`
- **Modify:** `frontend/components/admin/AdminShell.tsx` — `navItems`, line 29-45
- **Test:** `frontend/components/admin/slabs/__tests__/ScanInput.test.tsx`,
  `.../StagingTable.test.tsx`,
  `frontend/app/(admin)/admin/slabs/__tests__/page.test.tsx`

## Sidebar

Insert **after Buy** in `navItems` (it is an acquisition flow):

```tsx
{ href: '/admin/buy', label: 'Buy', icon: ShoppingBag },
{ href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
{ href: '/admin/trade', label: 'Trade', icon: ArrowRightLeft },
```

`ScanLine` is a lucide-react icon, the library already in use there.

## Three input methods, one pipeline

**All three produce a cert number and feed the identical `onScan` callback.** There
is exactly one downstream path — lookup, stage, commit. Do not build a separate flow
for any of them.

| Method | Task | Notes |
|---|---|---|
| Keyboard-wedge scanner | T4 | Primary; fastest for a stack |
| **Typing the cert number by hand** | **T4** | **First-class, always available** |
| Device camera | T5 | Optional convenience, droppable |

### Manual typing is a first-class path, not a fallback

Owner requirement, 2026-08-07. It must work **at all times**, with no mode switch, no
toggle, and no dependence on a scanner being connected or a camera being permitted.
The operator can always key a cert number and press Enter — or click an explicit
**Add** button next to the input, because a keyboard-only flow should not require
knowing that Enter is the trigger.

Concretely, the same input accepts both:

- A wedge scanner's burst of characters ending in Enter.
- A person typing eight digits over several seconds, then Enter **or** the Add button.

**Never gate submission on typing speed.** Timing may only decide whether to
*auto*-submit; it must never decide whether a submission is *allowed*. A cert typed
slowly is exactly as valid as one scanned in 40 ms, and a scuffed or unreadable
barcode makes hand entry the only way in.

Manual entry also has to survive every degraded state in the table below. When PSA
is unreachable or the quota is spent, typing a cert still stages a row — the operator
then fills in card and grade by hand. That path is the reason the feature keeps
working on a bad day.

### `ScanInput` requirements

- A single text input that **refocuses itself** after every submission, so the
  operator never has to click between slabs. This is the difference between a tool
  that gets used and one that gets abandoned.
- Visible **Add** button beside it, equivalent to pressing Enter.
- Guard against the same cert firing twice from one physical scan — but **do not**
  block a deliberate re-entry of the same cert; the operator may be correcting a row
  they just removed.
- Trim whitespace; some scanners append a carriage return **and** a newline.
- Basic shape validation with a **non-blocking** warning: if the entry does not look
  like a cert number, say so and still let it through. The operator can see the slab;
  the validator cannot.
- Show the last submission's status inline so the operator's eyes never leave the
  input.

**Do not block the input while a lookup is in flight.** The operator will scan or type
the next slab immediately; queue lookups rather than dropping them. A dropped entry is
a slab that silently never entered inventory — the worst possible failure here.

## The staging table

One row per scan. Rows are **client state only** until commit — nothing is persisted
before then, matching T2's read-only `/lookup`.

Per row:

| Column | Source |
|---|---|
| Cert | the scan |
| Card | `cert.subject` + `brand`, or an editable text field when unresolved |
| Grade | `cert.grade` + `grade_label`, editable |
| Company | defaults `PSA`, editable (a CGC slab is typed by hand) |
| Cost | **empty, required, admin-entered.** Nothing may guess this |
| Flags | duplicate / degraded / unmatched badges |
| Remove | drop the row |

**Flag rendering — be honest, per `degraded_reason` from T2:**

| `degraded_reason` | Row shows |
|---|---|
| `null`, `found: true` | "PSA verified" |
| `null`, `found: false` | "Not found at PSA — check the number" |
| `no_key` | "PSA lookup unavailable — enter details manually" |
| `quota_exhausted` | "Daily PSA limit reached — manual entry until UTC midnight" |
| `provider_error` | "PSA unreachable — enter details manually" |
| `not_psa` | "Non-PSA slab — enter details manually" |
| `already_owned` present | "Already in inventory (status X)" — **warning, not a block** |

A duplicate must be overridable: re-buying a slab you sold is legitimate (RFC §9).

Commit is disabled while any row is missing a cost, and the button says why.

**Quota warning.** Poll `GET /admin/slabs/quota` (T2) when the page loads and show
remaining PSA calls once they drop low. Hitting the cap mid-stack is survivable —
rows still stage manually — but knowing before you start is better than finding out
on slab 40.

## Commit

One action, three calls, in order. **The buy-session router's prefix is
`/purchases`, not `/buys`** — the session id is called `buy_id` but the route is not:

1. `POST /admin/purchases` → `buy_id`
2. `POST /admin/purchases/{buy_id}/items` per row, with `kind: "graded"` and the slab
   fields from T3
3. `POST /admin/purchases/{buy_id}/confirm`

**Send `buy_price` and `grade` as JSON numbers** — that is what the backend must
handle and what T3 tested (CLAUDE.md's float landmine). Do not stringify them here
to dodge it.

**Partial-failure handling is required.** If step 2 fails on row 4 of 10, do **not**
silently confirm 3 slabs. Stop, keep the staged rows on screen, tell the operator
which row failed, and leave the draft session uncommitted — a draft that is never
confirmed creates no inventory, so the safe state is "do nothing". Offer retry.

On success: a toast with count and total, clear the staging table, return focus to
the scan input.

## Frontend conventions — follow, do not reinvent

- Read `frontend/app/(admin)/admin/buy/page.tsx` first and copy its structure,
  loading states and error handling.
- Use the existing admin API hook (`useAdminApi`) as `AdminShell` does; do not hand-
  roll `fetch` with auth headers.
- Item names: call `adminItemName` (`frontend/lib/admin-item-name.ts`). **Never**
  inline `display_name || product_name` (CLAUDE.md).
- Locations: `useLocations()`. Never hardcode a location list.
- Conditions do not apply to slabs — do not render a condition control.

## RED — write these first, confirm they fail, then STOP

```bash
cd frontend && npx vitest run components/admin/slabs app/\(admin\)/admin/slabs --reporter=verbose
```

**ScanInput — scanner path**

1. Rapid keystrokes ending in Enter emit one `onScan` with the cert number.
2. One physical scan emits exactly one `onScan`, never two.
3. Trailing `\r` / `\n` / spaces are stripped.
4. The input refocuses after a submission.
5. Submitting while a lookup is in flight still emits — nothing is dropped.
6. Empty input + Enter emits nothing.

**ScanInput — manual typing path (owner requirement; these are not optional)**

7. Characters typed **slowly**, one at a time over a simulated multi-second span,
   then Enter, emit `onScan` with the full value. Assert the timing explicitly —
   this is the regression that a speed-gated implementation would introduce.
8. Clicking the **Add** button submits the typed value without any Enter key.
9. Manual typing works with **no scanner and no camera present** — nothing in the
   component may depend on either being available.
10. The same cert can be entered again after its row is removed — the duplicate
    guard must not permanently blacklist a value.
11. An entry that fails shape validation still emits `onScan`, and renders a
    non-blocking warning. Assert both: emitted **and** warned.
12. Manual entry works while the backend reports `degraded_reason: "no_key"` — the
    row still stages, editable by hand.

**StagingTable**

13. A resolved row renders card name, grade and a "PSA verified" indicator.
14. Each `degraded_reason` renders its specific message from the table above —
    assert the text, since a generic "error" is the thing this design rejects.
15. `already_owned` renders a duplicate warning **and the row stays committable**.
16. A row with no cost blocks commit and the button explains why.
17. Filling every cost enables commit.
18. Removing a row drops it and re-enables commit if it was the blocker.
19. An unresolved row's card/grade/company fields are editable — this is the manual
    path's landing zone and must be fully usable with the keyboard alone.

**Page**

20. A submission calls `/admin/slabs/lookup/{cert}` and appends a staged row.
21. Commit posts create → items → confirm, in that order, with `kind: "graded"`.
22. `buy_price` is sent as a JSON **number**, not a string.
23. A failure on the second item stops the flow, does **not** call confirm, and
    leaves all staged rows on screen.
24. Success clears the table and shows count + total.
25. **End-to-end manual path:** with the PSA lookup returning `no_key`, a typed cert
    plus hand-entered card, grade and cost commits a valid graded item. This is the
    proof the feature works with no scanner, no camera and no API.

If the file needs no DOM, add `// @vitest-environment node` — but these are all
component tests, so they need jsdom. Leave the default.

## GREEN

Only after the owner confirms failure.

## Manual check before you call it done

Run the app and scan (or type) a real cert. A test suite cannot tell you whether the
refocus behavior feels right with an actual scanner in hand, and that is the one
thing this task lives or dies on.

## Commit

```bash
git add frontend/app/\(admin\)/admin/slabs frontend/components/admin/slabs \
        frontend/components/admin/AdminShell.tsx
git commit -m "feat(slabs): scan-to-inventory intake tab"
```

Update [`progress.md`](progress.md) — mark the milestone reached.

## Definition of done — all four, every time

This task is not finished until **all four** are true. The fourth is what keeps the
chain moving: a task that stops at "tests pass" strands the next conversation.

1. **The narrow test selection named above passes.** Not the full suite — that runs
   once, at T-FINAL.
2. **The work is committed**, using the commit command above.
3. **[`progress.md`](progress.md) is updated** — status, commit sha, and anything a
   later task needs in the Notes cell. Out-of-scope findings go to
   [`follow-ups.md`](follow-ups.md), not here.
4. **Your final message ends with a copy-pasteable prompt for a FRESH conversation
   to execute the NEXT task.** It must be self-contained, and it must contain:
   - which files to read first (always `progress.md`, plus that task's doc);
   - the task id, and "execute that task only";
   - the RED gate — write the failing tests, show the owner the failing output,
     **wait for confirmation**, and only then implement (CLAUDE.md, binding);
   - the constraints that actually bite for that task (`./.venv/Scripts/python.exe`
     never bare `python`; do not run the full suite; any landmine this task
     uncovered);
   - **this same four-part definition of done**, with the task numbers advanced.

The next task order is in [`README.md`](README.md) and [`progress.md`](progress.md).

**Nothing carries between conversations except what you commit and what that prompt
says.** Write it for someone with no memory of this one.
