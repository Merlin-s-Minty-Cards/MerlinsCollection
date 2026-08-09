# T6 — Graded pricing provider and the slab list

**RFC:** 0009 §5.2, §6, §7 · **Layer:** full-stack · **Depends on:** T0, T4 ·
**Blocks:** T7

## Prerequisite

T0's verdict is **PROCEED** and `backend/tests/fixtures/pricing/` holds real
recorded responses. `spike-findings.md` is the contract for every field name below —
this document deliberately does **not** guess them.

**If T0 said STOP, do not start this task.** The owner needs to pick a different
source first.

## The good news

**No schema change is needed.** `services/dynamodb.py` already stores slab values as
`CARD#<id>` / `GRADEDPRICE#<company>#<grade>` rows, with
`get_graded_market_value(card_id, company, grade)` and `put_graded_market_value(...)`
(around lines 971-991). That is exactly the granularity a per-grade provider returns.
This task fills those existing rows from an API instead of by hand.

## Files

- **Create:** `backend/src/merlins_collection/services/slab/pricing.py`
- **Modify:** `backend/src/merlins_collection/config.py` —
  `pokemonpricetracker_api_key`, `pricing_daily_quota: int = 100`
- **Modify:** `backend/src/merlins_collection/routers/admin/slabs.py` — `GET /admin/slabs`
- **Modify:** `frontend/app/(admin)/admin/slabs/page.tsx` — the list section
- **Create:** `frontend/components/admin/slabs/SlabList.tsx`
- **Test:** `backend/tests/services/slab/test_pricing.py`,
  `backend/tests/routers/admin/test_slabs.py` (extend),
  `frontend/components/admin/slabs/__tests__/SlabList.test.tsx`

## The interface

Mirror T2's shape — Protocol, real client, fixture-backed fake, injected by
dependency. No test makes a network call.

```python
class GradedPrices(BaseModel):
    price_source_id: str
    prices: dict[str, Decimal]   # grade key -> value, e.g. {"10": ..., "9": ...}
    currency: str
    as_of: datetime | None

class GradedPricing(Protocol):
    def resolve(self, *, name: str, set_name: str | None,
                number: str | None) -> str | None: ...
    def prices(self, price_source_id: str) -> GradedPrices | None: ...
```

`resolve` is called **once per card**, and the result is cached on the item as
`price_source_id` (added in T1). `prices` is what the nightly job calls. Splitting
them is what keeps T7's nightly cost at one credit per slab.

## The three traps

**1. `0` is not `null`.** T0 recorded what "no coverage" looks like. If the provider
returns `0` for an unpriced grade, **treat it as absent** and never write a
`graded_price` row. A slab silently valued at $0 is worse than an unpriced one: it
drags totals, misreports position, and looks authoritative.

**2. Currency.** If the response is not USD, convert it or refuse it. The codebase
already handles this for Cardmarket via `eur_usd_rate` and — importantly — records
the rate used in the figure's `value_note` so a converted number is never silently
wrong. Follow that precedent; do not invent a silent conversion.

**3. Resolution ambiguity.** "Charizard, Base Set, 4/102" can match several provider
listings. On a **first** resolve for a card, the ambiguity must reach the admin as a
choice, not be auto-picked. Once confirmed, `price_source_id` is stored and never
resolved again.

## What the pricing provider may write

**Values only.** It must never write `card_id`, `display_name`,
`display_name_override`, `company`, `grade`, or `cert_number`. Identity comes from
PSA and from the admin; pricing is a number hung off an identity that already exists.
CLAUDE.md's binding rule — a name edit never writes `card_id` — is the same principle.

## Quota

Reuse T2's `services/slab/quota.py` with a **separate** counter key for this
provider (`outbound:pricing:<epoch-day>`). 100 credits/day, 60/min. The per-minute
ceiling matters here in a way it did not for PSA, because T7 loops: respect it.

## `GET /admin/slabs`

Query params: `company`, `grade`, `status`, `priced` (`true`/`false`/omitted),
`limit`. Returns graded items joined with their `graded_price` value and its age.

Reuse the existing admin inventory search plumbing where you can rather than writing
a third search implementation — read `routers/admin/inventory.py` first. **No table
scan** (CLAUDE.md Ops).

Each row carries `market_value`, `value_as_of`, and `price_source` (`"provider"` or
`"manual"`), so the UI can be honest about where a number came from.

## Frontend `SlabList`

Columns: card art, card, cert, company, grade, value, value age, cost, status.

- Card art through `useCardImages` with `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN`
  (`components/admin/shared/CardImage.tsx`). Do **not** hand-pick a size — CLAUDE.md
  records exactly what that cost across four pages last time.
- `useCardImages` attempts each id **once**; pass a freshly-mapped array so the
  effect re-runs, and do not re-queue failed ids. Re-queueing caused one POST per
  keystroke on Trade.
- A manual value renders a "manual" badge. An unpriced slab renders "not priced",
  **not** `$0.00`.
- Value age renders as "priced 3 days ago" when stale. T7 rotates refreshes, so
  staleness is a normal state to display, not an error.

## RED — write these first, confirm they fail, then STOP

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/slab backend/tests/routers/admin/test_slabs.py -q --tb=short
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```

**Pricing client**

1. A recorded fixture maps to `GradedPrices` with correct per-grade values.
2. A grade the provider does not cover is **absent** from `prices`, not `0`.
3. A `0` in the response is treated as no coverage and does not appear in `prices`.
4. Unknown card → `None`, not an exception.
5. Provider 500 raises; it does not return `None`.
6. Non-USD currency is either converted with the rate recorded, or refused — assert
   whichever you implemented, and that it is never silently taken as USD.
7. The API key is not present in any log record emitted during a call.
8. Quota exhausted raises before any HTTP call is attempted.

**Storage**

9. A resolved price writes a `graded_price` row readable by
   `get_graded_market_value(card_id, company, grade)`.
10. Two grades of the same card write two independent rows.
11. Writing a provider price does **not** modify the item's `card_id`,
    `display_name` or `cert_number`.

**Endpoint**

12. `GET /admin/slabs` returns only graded items.
13. `?priced=false` returns only slabs with no value.
14. `?company=PSA&grade=10` filters correctly.
15. A slab with no `card_id` still appears in the list (it is real inventory) with a
    null value.

**Frontend**

16. An unpriced slab renders "not priced", never `$0.00`.
17. A manual value renders the manual badge.
18. A stale value renders its age.
19. Card art uses `TABLE_THUMB_SIZE`; a card-less row renders the placeholder.

## GREEN

Only after the owner confirms failure.

## Commit

```bash
git add backend/src/merlins_collection/services/slab backend/src/merlins_collection/config.py \
        backend/src/merlins_collection/routers/admin/slabs.py \
        frontend/components/admin/slabs frontend/app/\(admin\)/admin/slabs backend/tests/ frontend/
git commit -m "feat(slabs): per-grade pricing provider and slab list"
```

Update [`progress.md`](progress.md). Record in the Notes cell what "no coverage"
actually looked like — T7 depends on that distinction.

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
