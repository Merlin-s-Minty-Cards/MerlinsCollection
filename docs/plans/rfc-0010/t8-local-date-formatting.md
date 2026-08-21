# T8 — Dates stop rendering a day early

**RFC:** 0010 §E · **Layer:** frontend · **Depends on:** — · **Blocks:** T9 (same file)
**Owner report:** plan doc item 8 — *"Display date on show analytics is wrong by one date
backward, Aug 10 shows as Aug 9. However, the 'pick a date' option shows the correct date."*

The second sentence is the diagnosis. The date picker is right because it binds the ISO string
directly and never constructs a `Date`; everything else on the page goes through one that does.

## Confirmed root cause

`frontend/app/(admin)/admin/analytics/page.tsx:78-84`:

```ts
function formatDate(dateStr: string): string {
  const d = new Date(dateStr)                       // "2026-08-10" → 2026-08-10T00:00:00Z
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
```

ECMA-262 requires a bare `YYYY-MM-DD` to be parsed as **UTC**. `toLocaleDateString` then formats
in the **browser's** zone. At any negative UTC offset — every US timezone — UTC
`2026-08-10T00:00Z` is the evening of **Aug 9** locally.

`formatDate` renders the transaction date (line 106), the selected show (line 376) and every show
in the archive list (line 685), so **every** date on Show Analytics is a day early.

The same construct is duplicated at:

| file | line | value |
|---|---|---|
| `app/(admin)/admin/analytics/page.tsx` | 80 | date-only — **broken** |
| `app/(admin)/admin/card/[id]/page.tsx` | 86 | date-only — **broken** |
| `components/admin/shared/PriceChart.tsx` | 90 | date-only — **broken** |
| `components/admin/slabs/SlabList.tsx` | 32 | full **timestamp** — correct, leave it |

`SlabList` is listed so nobody "fixes" it into a bug: a timestamp with a time and offset is
unambiguous, and `new Date()` is the right call there.

## A SECOND live bug, in scope: "today" is computed in UTC

**Owner, 2026-08-10:** *"use the local time if possible, but otherwise default to PST time as
that is where we are all located."*

Answering that surfaced a distinct defect. `new Date().toISOString().split('T')[0]` — the
default date on Buy (`buy/page.tsx:50, 274, 672`), Sell (`sell/page.tsx:62, 239`), Trade
(`trade/page.tsx:80`) and the dashboard (`page.tsx:69`) — returns the **UTC** date. Measured:

```
6:30pm Pacific, Aug 10  →  toISOString().split('T')[0]  =  2026-08-11   ← what it defaults to
                        →  local date in Pacific        =  2026-08-10
```

So **every transaction entered after 5pm Pacific defaults to tomorrow's date.** For a business
whose selling happens at evening card shows, that is most of them: the buy lands in the wrong
day's analytics, and potentially against the wrong show.

This is now **in scope for T8** — same root cause (a date derived through a UTC boundary), same
helper file, and fixing the display while leaving the input wrong would be worse than fixing
neither.

## Local first, Pacific as the fallback — and why the two barely interact

Worth being precise, because it changes how much work each part is:

- **Date-only values** (`"2026-08-10"`) have **no timezone at all.** Once you stop routing them
  through `new Date()`, they format as Aug 10 in every zone on earth. The Pacific fallback is
  irrelevant here — correct parsing is the whole fix.
- **Timestamps** (`voided_at`, a slab's `updated_at`) are real instants and *do* render
  differently per zone. Here "local if possible, else Pacific" applies: pass no `timeZone` so
  the browser uses its own, and only name a zone where there is no browser (SSR, a server-side
  render, a test).
- **"What is today"** must be computed in the **user's** zone, falling back to Pacific.

**Use the IANA zone `America/Los_Angeles`, never a fixed −8 offset.** Measured: Pacific is
**PDT (−7)** in August and **PST (−8)** in January, so a hardcoded −8 would be wrong from March
to November — about eight months a year, including every summer show.

## Files

- **Create:** `frontend/lib/dates.ts` — `formatISODate`, `parseISODateLocal`, `todayLocal`,
  `formatTimestamp`
- **Create:** `frontend/lib/__tests__/dates.test.ts`
- **Modify:** the three broken display call sites (delete their local `formatDate`)
- **Modify:** the four `toISOString().split('T')[0]` sites — buy, sell, trade, dashboard
- **Tests:** the existing analytics / card-detail / PriceChart / buy / sell / trade test files

## Design

```ts
/** The zone this business operates in. Used only when the runtime has none
 *  (SSR, tests). IANA, never a fixed offset: Pacific is PDT (-7) in August and
 *  PST (-8) in January, so a hardcoded -8 is wrong ~8 months a year. */
export const BUSINESS_TIME_ZONE = 'America/Los_Angeles'

/**
 * Format a DATE-ONLY string ("2026-08-10") for display.
 *
 * `new Date("2026-08-10")` is parsed as UTC midnight per ECMA-262 and then
 * rendered in the local zone, so in any negative-offset timezone it displays the
 * PREVIOUS day. That is why Show Analytics showed Aug 10 as Aug 9 while the
 * `<input type="date">` beside it was correct — the input never builds a Date.
 *
 * A date-only value carries no timezone, so this needs no zone at all: it splits
 * the string and formats the parts. NEVER pass a date-only string to `new Date()`.
 */
export function formatISODate(iso: string, opts?: Intl.DateTimeFormatOptions): string

/** Local-midnight Date for a date-only string, or null if it isn't one. */
export function parseISODateLocal(iso: string): Date | null

/**
 * Today's date as "YYYY-MM-DD" in the USER's zone, falling back to Pacific.
 *
 * NOT `new Date().toISOString().split('T')[0]`, which is the UTC date: measured,
 * 6:30pm Pacific on Aug 10 yields "2026-08-11", so every transaction entered
 * after 5pm Pacific defaulted to tomorrow.
 */
export function todayLocal(): string

/** A real instant, in the user's zone, falling back to Pacific. */
export function formatTimestamp(iso: string, opts?: Intl.DateTimeFormatOptions): string
```

`todayLocal` is cleanly expressed with `en-CA` (which formats as `YYYY-MM-DD`) or by reading
`Intl.DateTimeFormat().formatToParts`. Either is fine; do not hand-roll offset arithmetic.

For `formatTimestamp`, pass **no** `timeZone` when `Intl.DateTimeFormat().resolvedOptions()
.timeZone` is available — that is "use local" — and only name `BUSINESS_TIME_ZONE` when it is
not. Do not force Pacific on a browser that knows its own zone; the owner asked for local
first.

Split the string on `-` and construct `new Date(y, m - 1, d)` — a local-midnight date — or
format the parts directly with no `Date` at all. Either is fine; the local construction reuses
`toLocaleDateString` for the month names, which is worth keeping.

**Be defensive about the input.** These functions receive whatever the API sent. Return the raw
string unchanged for anything that is not `YYYY-MM-DD` (a full timestamp, an empty string, junk)
rather than rendering `Invalid Date` — that is what the existing `try/catch` was reaching for.
A full timestamp should either be delegated to normal `Date` parsing or returned as-is;
**decide and document it**, because the analytics transaction rows carry a `date` field whose
shape is worth confirming against the API before you assume.

Delete the three local `formatDate` helpers rather than leaving them beside the shared one.
Two implementations of the same fix is how one of them gets missed next time.

## RED — write these first, show the failing output, wait for confirmation

**The tests must pin a negative-offset timezone.** In UTC these all pass either way, so a UTC CI
box would go green while the bug is live in Portland. Set `process.env.TZ = 'America/Los_Angeles'`
before the date module loads (a `beforeAll`, a vitest `env` config, or a file-level
`// @vitest-environment node` + explicit TZ — whichever this repo already does; ~20 pure-logic
test files here already carry the node-environment pragma).

**Without that pin the test is theatre.** Say so in a comment above it.

1. **`formatISODate('2026-08-10')` renders "Aug 10, 2026" in `America/Los_Angeles`** — the
   owner's bug, as a test;
2. the same in `America/New_York`;
3. and in UTC (no regression for a UTC user);
4. `parseISODateLocal('2026-08-10')` yields local midnight, not UTC midnight;
5. a non-date-only input is handled per the documented rule, not as `Invalid Date`;
6. an empty string returns an empty string, not "Invalid Date".

**`todayLocal` (4) — the second bug:**
7. **at 6:30pm Pacific on Aug 10, `todayLocal()` returns `2026-08-10`, not `2026-08-11`.** Fake
   the clock (`vi.setSystemTime`) with the TZ pinned to Pacific. This is the test that matters;
   name it for the bug;
8. at 2am Pacific it returns that same calendar day;
9. it never returns the UTC date when they differ;
10. `BUSINESS_TIME_ZONE` is an IANA name, not an offset — assert the string, so nobody
    "simplifies" it to `-08:00`.

**Call sites (3):** the analytics transaction row, the selected-show header and the show archive
list each render the correct day under a pinned negative offset. One test per site — they are
three separate call sites and a shared helper does not prove all three were converted.

Plus `PriceChart` and `/admin/card/[id]` axis/label dates under the same pin.

**Default dates (4):** Buy, Sell, Trade and the dashboard each default to `todayLocal()`, and
under a faked 6:30pm-Pacific clock that default is **Aug 10**. Four separate call sites, four
tests — this is where the money-dating bug actually bites.

**Corrected as executed.** `npx vitest` fails here with *"Vitest failed to find
the runner"* (progress.md's baseline section records it; this is the ninth task
doc in the RFC to carry the broken form). The dashboard is a fifth default-date
call site and its test file was missing from the selection:

```bash
npm test --workspace=frontend -- --run "lib/__tests__/dates" "app/(admin)/admin/analytics" "app/(admin)/admin/card" "app/(admin)/admin/buy" "app/(admin)/admin/sell" "app/(admin)/admin/trade" "app/(admin)/admin/__tests__" components/admin/shared/__tests__/PriceChart
```

## GREEN — done when

The above pass, pre-existing tests in those files pass, `npm run lint --workspace=frontend` is
clean, and both greps are clear:

```bash
grep -rn "new Date(" frontend/app/\(admin\) frontend/components/admin    # no date-only args outside lib/dates.ts
grep -rn "toISOString().split\|toISOString().slice" frontend/             # no remaining "today" computations
```

**The second grep as written misses one.** The dashboard's "today" is
`toISOString().slice(0, 10)`, not `.split('T')[0]` — same defect, different
spelling. Grep for both.

## Manual check

Open Show Analytics on a day with activity. The heading date, the transaction rows and the show
list must all agree with the date picker. Today (2026-08-10) must read **Aug 10**.

Then, **after 5pm Pacific** (or with the machine clock set there), open Buy and check the default
date. It must be today, not tomorrow. That is the second bug, and it is only visible in the
evening — which is exactly when the business is selling.

## Do not

- Do not write the test without pinning a negative-offset TZ.
- **Do not use a fixed `-08:00` offset.** Pacific is PDT (−7) for eight months of the year.
- **Do not force Pacific on a browser that knows its own zone.** Local first; Pacific is the
  fallback.
- Do not leave `new Date().toISOString().split('T')[0]` anywhere as a "today" computation.
- Do not "fix" `SlabList` — its value is a timestamp, so `new Date()` is correct there.
- Do not leave the local `formatDate` helpers in place beside the shared one.
- Do not render `Invalid Date` for unexpected input.
- Do not change any API contract. The backend already sends correct ISO dates
  (`date.isoformat()`); both bugs are on the frontend.

---

## Done means: committed, recorded, and the next prompt emitted

This task is finished when **all five** of these are true. Four is not done.

1. **The narrow test selection above passes**, and you have shown the output. Not "should pass".
2. **[`progress.md`](progress.md) is updated** — this row set to `DONE` with the commit sha, a
   Notes line if a later task needs to know something, and anything surprising added to the
   Decisions table.
3. **Out-of-scope findings are appended to [`follow-ups.md`](follow-ups.md)** — not fixed as a
   side errand, and not left only in the conversation.
4. **The work is committed.** One focused commit, or a small series, in this branch's
   conventional-commit style (`feat(scope):` / `fix(scope):` / `docs(scope):`). Do not merge, do
   not push unless asked.
5. **Your final output is the ready-to-paste prompt below**, so a fresh conversation can pick up
   the next task without the owner reconstructing anything.

### Next in the chain

**T9 — A sale reads `+$40`, a purchase reads `−$200`**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t9-signed-ledger-amounts.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
