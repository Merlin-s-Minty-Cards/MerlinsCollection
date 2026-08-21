# T7 — Nightly slab pricing, and the graded-skip bug

**RFC:** 0009 §5.2 · **Layer:** backend · **Depends on:** T6 · **Blocks:** T8

## Two things

**1. Wire pricing into the nightly sync.** `snapshot_graded_prices`
(`services/catalog_sync.py:58-85`) already walks owned slabs, dedupes by
`(card_id, company, grade)` and writes a history point per day — but only for values
someone typed by hand (`source="manual"`). Add a fetch step ahead of the snapshot so
the values are the provider's.

**2. Fix a known open bug.** The Market page's refresh-prices button is raw-only
while the nightly sync does refresh graded items — a scope mismatch recorded in
`claude-progress.txt:157` and still open. Same area, fix it here.

## Files

- **Modify:** `backend/src/merlins_collection/services/catalog_sync.py` —
  `snapshot_graded_prices` (line 58-85), and the refresh-prices entry point
- **Modify:** `backend/src/merlins_collection/routers/admin/slabs.py` —
  `POST /admin/slabs/refresh-prices`
- **Test:** `backend/tests/services/test_catalog_sync.py` (extend),
  `backend/tests/routers/admin/test_slabs.py` (extend)

## Zero PSA calls

The nightly job must **never** call PSA. A cert's identity is immutable, and
population — the only mutable field — is `null` on the public API anyway (RFC §5.1).
There is nothing to refresh. Add a test that asserts it (see #9).

## Stalest-first rotation

> **CORRECTED BY T8 (2026-08-09), and the as-built behaviour follows the
> correction, not the original text below-the-fold.** Two things in this section
> were wrong when it was written:
>
> 1. **The budget is credits, not lookups.** The free tier is 100 **credits** a
>    day and a graded lookup costs **2** (`costPerCard: 2`, measured live — 1 for
>    the card, 1 for `includeEbay`), so the real ceiling is **50 lookups a
>    night**, not 100. You are billed on `limit` even when the search matches
>    **zero** cards. `refresh_graded_prices` divides by 2 (`_CREDITS_PER_LOOKUP`)
>    and sizes itself off `PRICING_DAILY_QUOTA`, so the shipped code is correct;
>    only this prose was not.
> 2. **"A slab with no `price_source_id` … skip it" was REVERSED by the owner on
>    2026-08-09.** The job DOES do first contact — it runs the fuzzy `resolve()`
>    for a slab that has a `card_id` but no cached id, gated by T6's verified
>    join. Nothing anywhere sets `price_source_id` (PSA intake was going to), so
>    the original rule would have priced nothing, ever. **No `card_id`** is still
>    a free skip.

The pricing free tier is **100 credits/day = 50 lookups/day**. Under 50 slabs,
everything refreshes nightly. Above it, refresh the 50 stalest and let the rest
wait.

- Order candidates by the age of their stored value; **null/never-priced first** —
  a slab with no value at all is more urgent than one priced yesterday.
- Cap the run at the configured quota, not at a hardcoded number.
- **Respect the 60/min ceiling.** A long sequential run will trip it otherwise.
- Dedupe by `(card_id, company, grade)` before spending credits — the existing
  function already does this and the reason is now money, not just tidiness.
- A slab with no `card_id` cannot be priced. Skip it without spending a credit and
  without logging an error — it is a normal state that Triage already surfaces.
  (**A missing `price_source_id` is NOT a skip** — see the correction above.)

Log a summary: candidates, refreshed, skipped, quota remaining. This is the only
visibility into a job that runs while nobody is watching.

## Failure isolation

One card's failure must not abort the run. Catch per item, count failures, continue.
A provider hiccup on slab 3 of 80 must not cost you the other 77.

If the quota is exhausted mid-run, **stop cleanly** and report it. Do not spin
through the remainder collecting 429s.

## The snapshot still runs

After fetching, the existing history-point write continues, so slabs get a price
chart like raw cards. Set `source` to the provider rather than `"manual"` on
provider-sourced points, so a chart can tell a hand-typed value from a fetched one.

**A manual value must not be silently overwritten by a provider value.** The owner
may have deliberately priced a slab. Decide the precedence, implement it, and write
the test — the honest default is that the provider wins only where no manual value
was set, or the manual value carries a flag marking it as pinned. **Ask the owner if
this is not obvious from the code**; it is a real business decision, not a
refactoring detail.

## `POST /admin/slabs/refresh-prices`

Background trigger, mirroring the existing `POST /admin/market/sync` pattern —
read that first and copy its status-reporting shape rather than inventing one. The
Market page's polling UI is the precedent for how the frontend watches it.

## RED — write these first, confirm they fail, then STOP

```bash
./.venv/Scripts/python.exe -m pytest \
  backend/tests/services/test_catalog_sync.py backend/tests/routers/admin/test_slabs.py -q --tb=short
```

1. A run fetches provider prices for owned slabs and writes `graded_price` rows.
2. The history snapshot still writes one point per `(card_id, company, grade)` per
   day, and provider-sourced points carry the provider as `source`.
3. Two slabs with the same card/company/grade cost **one** credit, not two.
4. A slab with no `card_id` is skipped and spends no credit.
5. A slab with no `price_source_id` is skipped and spends no credit.
6. With 150 candidates and a quota of 100, exactly 100 are refreshed.
7. Those 100 are the **stalest**; never-priced slabs come first.
8. A provider error on one item does not abort the run — the others still refresh
   and the summary counts the failure.
9. **The run makes zero PSA calls.** Assert against a PSA fake that records calls.
10. Quota exhausted mid-run stops cleanly and reports partial completion.
11. Whatever manual-value precedence you implemented, assert it explicitly.
12. `POST /admin/slabs/refresh-prices` returns immediately and reports status like
    the market sync does.

**Refresh-prices bug**

13. The Market refresh path now includes graded items — a graded slab's
    `current_market_value` updates where previously it was skipped.
14. Raw refresh behavior is unchanged (regression).

## GREEN

Only after the owner confirms failure.

## Commit

```bash
git add backend/src/merlins_collection/services/catalog_sync.py \
        backend/src/merlins_collection/routers/admin/slabs.py backend/tests/
git commit -m "feat(slabs): nightly graded pricing with quota-aware rotation; fix graded refresh skip"
```

Update [`progress.md`](progress.md), and strike the graded-refresh row in
`claude-progress.txt`'s known-issues section — it has been open since Round 2 and
should not be listed as open once this lands.

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
