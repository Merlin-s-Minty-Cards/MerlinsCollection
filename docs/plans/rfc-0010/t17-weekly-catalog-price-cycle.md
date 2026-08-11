# T17 — Every catalog card is re-priced at least once a week, by Friday

**RFC:** 0010 §N · **Layer:** backend · **Depends on:** — · **Blocks:** nothing, but
**T15's price display has nothing to show until this runs**
**Owner ask, 2026-08-10:** *"it would be helpful when searching for catalog cards to see not
only the name and image, but also the price… I want to make it so that the entire catalog has
recorded/updated a new price by friday of each week. However the work is split up is up to
you."*

## The problem this solves

`refresh_held_prices` — the nightly TCGdex depth pass — is scoped to **cards the business
currently owns** (`_held_card_ids`, `services/catalog_sync.py:446-472`): ~300 cards. Every other
row in the catalog has **no price at all**, and `CatalogCard.detail` records that honestly as
`"brief"`.

That is exactly backwards for the Buy table. The cards you need a price for are the ones
somebody is trying to sell you — cards you do **not** own yet, by definition. RFC 0008 §C
already flagged this gap; this task closes it.

**31,603 catalog rows** (23,444 EN + 8,159 JA, measured 2026-07-28 —
`scripts/seed_catalog.py:81-101`), of which ~300 are already covered daily.

## Measured numbers — the design follows from these

| fact | value | source |
|---|---|---|
| TCGdex per-card latency, warm | **162 ms** | measured 2026-08-10, 5 cards, `/v2/en/cards/{id}` |
| courtesy delay between requests | **100 ms** | `refresh_held_prices(request_delay_seconds=0.1)` |
| **effective cost per card** | **~262 ms** | sum of the two |
| catalog lock TTL | **3600 s** | `_LOCK_TTL_SECONDS`, `services/dynamodb.py:326` |
| whole catalog, serial | **~2 h 18 min** | 31,603 × 0.262 s |

**A single full-catalog pass per night is not viable, and the reason is not time — it is the
lock.** `refresh_held_prices` holds the catalog lock for its whole run. A 2 h 18 min run
**outlives its own 1-hour TTL**, at which point the lock looks like a crashed holder and becomes
stealable. Its docstring states the consequence: *"A depth-pass write that lands after a reseed
has passed that card but before its finalize carries the superseded generation and is swept —
the card silently disappears from a live catalog."* Cards vanishing from a live catalog is a far
worse outcome than a stale price.

Cost is a non-issue either way: ~31,600 extra DynamoDB writes a night is roughly **$2.40/month**
on-demand, and TCGdex is free with no observed rate limit (`tcgdex.py:620` — the delay is
*"courtesy toward a free volunteer-run service"*). ECS RunTask has no Lambda-style timeout, and
the client's `total_deadline_seconds=300` is **per request** (reset at `tcgdex.py:703`), not per
job. Neither is a constraint.

## The design: a rolling weekly cycle, stalest-first

**~5,500 cards per night**, chosen stalest-first, as a new step in the existing nightly job.

- 31,300 unheld cards ÷ 5,500 = **5.7 nights**, so a cycle that starts Saturday completes
  Thursday and **Friday is slack** — which is what "by Friday" needs in order to survive a bad
  night rather than merely being true when nothing goes wrong.
- 5,500 × 0.262 s = **~24 min**, against a 3600 s lock TTL. **2.5× headroom**, no lock
  heartbeat needed, and that headroom is the whole reason for splitting the work.

**Degradation is graceful and bounded, which is the point of stalest-first over a cursor:**

| nights lost | Friday's backlog | Friday run time | verdict |
|---|---|---|---|
| 0 | ~0 | ~0 | normal |
| 1 | 5,500 | ~24 min | absorbed silently |
| 2 | 11,000 | ~48 min | absorbed, close to the TTL |
| 3+ | 16,500+ | **>60 min — would break the lock** | must not happen silently; see the guard |

A night that fails does not lose its cards: they stay stale, so tomorrow's stalest-first
selection picks them up automatically. **No cursor to corrupt, no cards to strand.**

### Ordering: never-priced first, then oldest

`CatalogCard` already carries everything needed — **no schema change**:

- `last_synced_at: datetime` (required field) — when *we* last wrote the row;
- `detail: Literal["brief", "full"]` — `brief` means the row came from the cheap list endpoint
  and **has never had a price fetched**.

So the ordering predicate is:

1. `detail == "brief"` — never priced, highest value, take these first;
2. then `detail == "full"` by `last_synced_at` **ascending**.

**This is the same shape `refresh_graded_prices` already uses** (never-priced first, then
stalest, capped at a nightly budget, RFC 0009 T7). Reuse the pattern deliberately; do not invent
a second one.

⚠️ **`last_synced_at` is bumped by ANY write, including the breadth pass.** A `brief` row written
by `sync_new_sets` yesterday looks *fresh* while having no price at all. That is precisely why
`detail` is checked **first** and not as a tiebreak — ordering on `last_synced_at` alone would
put brand-new, priceless cards at the back of the queue.

### Excluding held cards

Skip the `_held_card_ids` set. The daily depth pass already covers them, and fetching a card
twice in one night is pure waste. It also keeps the two passes' summaries readable: "held cards
refreshed" and "catalog cards refreshed" stay separate numbers.

### Where it runs

A new step inside `run_daily_sync`, **after** `refresh_held_prices` releases the catalog lock,
acquiring it again for its own run. No new EventBridge schedule, no new IAM: the existing
`merlins-price-sync` schedule (daily 09:00 UTC, `docs/aws-setup.md` Phase 8) already runs this
job.

Ordering within `run_daily_sync` matters and the existing docstring explains why: the depth pass
runs **first** because `refresh_inventory_market_values` denormalizes what it wrote. The new pass
prices cards we do **not** own, so it feeds no denormalizer and can go last — put it after
`refresh_inventory_market_values` so a 24-minute catalog walk can never delay the steps that
publish today's figures for stock we actually hold.

### Do not duplicate the per-card loop

`_refresh_held_prices`' per-card body is a carefully documented specification — priceless
successes go through `upsert_catalog_card_preserving_prices`, a 404 is `not_found` and neither
increments nor resets the failure counter, an existing price is never deleted or zeroed. **Extract
that body into a shared `_refresh_one_card(...)` helper** that both passes call, so there is one
copy of the delicate logic and each caller owns only its candidate selection and its budget.

The existing depth-pass tests are the regression gate on that extraction, and they are not
optional here.

### A guard the current code does not need but this one does

`max_consecutive_failures=25` aborts a run. At 300 cards that is a sensible tripwire; at 5,500 it
still is. But add a **hard runtime cap** as well — assert at start that
`cards_per_night × 0.262 s` sits under ~45 min, or bound the loop on elapsed time and stop
cleanly. A mis-set constant must not be able to blow the lock TTL, because that failure mode
loses catalog rows rather than prices.

Both the abort and the cap must be **reported in the summary** and reflected in the script's exit
code, or a week of half-runs looks like a week of clean ones — the exact failure
`scripts/daily_sync.py`'s exit-code protocol exists to prevent.

### Make the deadline auditable

"By Friday" needs a number that can be checked, not just a cadence that should produce it. Add to
`/admin/market`'s coverage panel:

- how many `full` catalog rows have `last_synced_at` **older than 8 days** — the healthy value is
  **0**, and any other value means the cycle is not keeping its promise;
- how many rows are still `brief` — the cycle's remaining first-pass work, which counts down to 0
  over the first ~6 nights and then stays there.

The first full cycle is the slow one: every one of ~31,300 rows is `brief`, so it takes ~6 nights
to get the initial coverage. Say so in the summary rather than letting it look like a stall.

## Deliverable 2: a one-time script that prices the WHOLE catalog in one run

**Owner ask, 2026-08-10:** *"I want to be able to run a script once so that the entire catalog has
it's price updated. This is something I can just leave going overnight."*

This is the **bootstrap** for the cycle above. Without it the first cycle takes ~6 nights to reach
initial coverage; with it, one overnight run prices everything and the nightly cycle only ever has
to keep it fresh. It also gives the owner a way to force a full re-price after a catalog reseed.

**It is a driver, not a second implementation.** `backend/scripts/reprice_catalog.py` calls the
same `refresh_catalog_prices` with a huge budget. Two implementations of "price a card" is the
divergence this repo has already paid for twice.

### The lock problem, and the answer

A 2 h 18 min run cannot hold the catalog lock — the TTL is 3600 s and a long holder looks like a
crashed one. **So the script works in bounded chunks, taking and releasing the lock per chunk:**
~2,000 cards (~9 min), release, re-acquire, continue. That reuses the existing lock semantics with
**no new primitive** — no heartbeat, no renew method, no raised TTL — and it means a reseed waiting
on the lock gets in between chunks instead of being starved for two hours.

If a chunk cannot acquire the lock (a reseed is running), the script **stops cleanly and says so**
rather than skipping ahead. Resume by re-running it.

### Resumability is free

Stalest-first ordering makes the script naturally resumable: kill it at 90 minutes, re-run it, and
it continues with whatever is still unpriced or oldest. **No checkpoint file, no `--resume` flag,
no state to corrupt** — the same property that makes the nightly cycle self-heal.

### Shape, following this repo's script conventions

Follow `scripts/backfill_catalog_sets.py` and `scripts/seed_catalog.py`:

```bash
cd backend
../.venv/Scripts/python.exe scripts/reprice_catalog.py                                  # DRY RUN — reports what it would do
../.venv/Scripts/python.exe scripts/reprice_catalog.py --execute --confirm-table merlins-cards
```

- **dry run by default**, printing the candidate count, the chunk plan and the **estimated
  runtime** (`count × 0.262 s`) so the owner knows what "overnight" means before starting;
- `--confirm-table` required to write, matching the seed script's rail;
- `--limit N` to prove it out on a small slice first;
- `--chunk-size` with a default of 2,000, bounded so it cannot exceed the lock TTL;
- **progress output every chunk** — done / total, failures, elapsed, ETA. This runs unattended for
  two hours; silence is indistinguishable from a hang;
- **Ctrl-C releases the lock and exits cleanly.** A `KeyboardInterrupt` that leaves the lock held
  blocks the next morning's nightly run for a full hour;
- the same failure posture as the nightly pass: a per-card error is counted and stepped over, an
  existing price is never deleted or zeroed, and consecutive failures abort.

**Note in the script's docstring that this is NOT a scheduled job** and not a seed — it neither
creates catalog rows (that is `seed_catalog.py`) nor prices only held cards (that is the nightly
depth pass). The three are easy to confuse; `_sync_new_sets`' docstring already had to spell out
the same distinction.

**Every script here needs the venv interpreter spelled out.** A bare `python` resolves to an
unrelated environment that cannot import `merlins_collection`, and these files have no shebang
(CLAUDE.md Ops).

## Files

- **Modify:** `backend/src/merlins_collection/services/catalog_sync.py` — extract
  `_refresh_one_card`; add `refresh_catalog_prices`; wire it into `run_daily_sync`
- **Create:** `backend/scripts/reprice_catalog.py` — the one-time overnight driver
- **Create/extend:** `backend/tests/test_reprice_catalog.py` — drive the script the way the owner
  would, the way `test_daily_sync.py` drives the nightly job
- **Modify:** `backend/src/merlins_collection/config.py` — `CATALOG_REFRESH_CARDS_PER_NIGHT`
  (default 5500) as a tunable, so the cadence is config and not a magic number
- **Modify:** `backend/scripts/daily_sync.py` — report the new step; extend the exit-code
  docstring
- **Modify:** `backend/src/merlins_collection/routers/admin/market.py` — the two coverage numbers
- **Tests:** `backend/tests/test_catalog_sync.py`, `backend/tests/test_daily_sync.py`,
  `backend/tests/test_market.py`

## RED — write these first, show the failing output, wait for confirmation

**Candidate selection (7):**
1. `brief` rows are selected **before** `full` rows, even when a `brief` row's `last_synced_at`
   is newer — the trap named above, and the test that proves `detail` is checked first;
2. within `full` rows, the oldest `last_synced_at` comes first;
3. the selection is capped at `cards_per_night`;
4. **held cards are excluded** (the daily pass covers them);
5. an aborted night's cards are picked up by the **next** run without any cursor state;
6. a night where every card is fresh selects the stalest ones anyway rather than nothing — the
   cycle keeps turning;
7. graded-only and sealed items contribute no candidates (they have no catalog card to price).

**The shared per-card helper (4) — the extraction's regression gate:**
8. a priceless success goes through `upsert_catalog_card_preserving_prices` and **does not delete
   the stored bands**;
9. a 404 counts as `not_found` and **neither increments nor resets** the consecutive-failure
   counter;
10. a per-card error is counted and the run continues;
11. **the existing held-pass behaviour is byte-identical after the extraction** — run the
    pre-existing depth-pass tests unchanged.

**Budget and safety (4):**
12. the run aborts after `max_consecutive_failures` and **reports it**;
13. the runtime cap stops the loop cleanly and reports it, rather than running past the lock TTL;
14. the lock is released even when the run raises (`finally`);
15. a lock held by someone else skips the pass without failing the whole job.

**Wiring (3):**
16. `run_daily_sync` runs the new step **after** `refresh_inventory_market_values`;
17. the summary carries the new step's counts as their own keys, not merged into the held pass's;
18. `daily_sync.py`'s exit code reflects a catalog-pass abort.

**Coverage reporting (2):**
19. the stale-over-8-days count is 0 for fresh rows and correct for old ones;
20. the `brief` count is reported separately from the stale count.

**The one-time script (7):**
21. **dry run writes nothing** and reports the candidate count, chunk plan and estimated runtime;
22. `--execute` without `--confirm-table` refuses;
23. it processes in chunks, **releasing the lock between them** (assert acquire/release pairs, not
    one long hold);
24. a chunk that cannot acquire the lock **stops cleanly** with a distinct exit code rather than
    skipping ahead;
25. **re-running after an interrupted run continues rather than restarting** — the resumability
    claim, asserted rather than assumed;
26. `--limit N` bounds the run;
27. `KeyboardInterrupt` releases the lock. This is the one that matters at 2 a.m.: a held lock
    blocks the next morning's nightly job for a full hour.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_catalog_sync.py backend/tests/test_daily_sync.py backend/tests/test_market.py -q --tb=short
```

**No test may touch the network.** The TCGdex client is injectable and every existing test in
`test_catalog_sync.py` fakes it; a real request in a suite that runs on every commit would spend
someone else's free service. Set `request_delay_seconds=0` in tests, as the existing ones do, or
the suite grows by 24 minutes of `sleep`.

## GREEN — done when

The above pass, **every pre-existing `test_catalog_sync.py` test passes unchanged** (that is what
proves the extraction was faithful), and `ruff check backend/src` is clean.

## Manual check

Run the job once against real data with a small cap (`CATALOG_REFRESH_CARDS_PER_NIGHT=50`) and
confirm: 50 previously-`brief` rows come back `full` with prices, the summary counts match, the
lock is released, and the coverage panel's `brief` count drops by 50. Then search one of those
cards on the Buy page and confirm a price now renders.

Then prove the script on a slice before the owner commits an evening to it:

```bash
cd backend
../.venv/Scripts/python.exe scripts/reprice_catalog.py --limit 200                       # dry run
../.venv/Scripts/python.exe scripts/reprice_catalog.py --limit 200 --execute --confirm-table merlins-cards
```

Confirm: 200 rows go `brief` → `full`, the progress output is readable, the ETA was roughly right,
and Ctrl-C during a run leaves the lock released (check it, do not assume).

**Do not run the full uncapped pass yourself to "see if it works."** It is 2 h 18 min of requests
against a volunteer-run free API, and it is the owner's overnight run to make.

## Do not

- Do not price the whole catalog in one nightly run. It outlives the catalog lock, and the
  failure mode is catalog rows silently disappearing.
- Do not raise `_LOCK_TTL_SECONDS` to make a long run fit. The chunking is the fix; a longer TTL
  just means a genuinely crashed holder blocks tomorrow's run for longer.
- Do not order on `last_synced_at` alone. A `brief` row can be newer than a priced one.
- Do not build a cycle cursor. Stalest-first self-heals; a cursor is state that can be wrong.
- Do not duplicate `_refresh_held_prices`' per-card body — extract it.
- Do not change `refresh_held_prices`' scope. Held cards keep their **daily** refresh; they are
  the stock being priced and sold today.
- Do not let a catalog-pass failure abort the held pass, the snapshots, or the denormalization.
  Degrade alone, exactly as the graded pricing step does.
- Do not make a real TCGdex request from a test.
- Do not report a `brief` row and a stale `full` row as the same number. They are different facts.
- **Do not give the one-time script its own copy of the pricing logic.** It is a driver over
  `refresh_catalog_prices`.
- **Do not let the script hold the lock for its whole run**, and do not add a heartbeat or raise the
  TTL to permit that. Chunk it.
- Do not add a checkpoint file or a `--resume` flag. Stalest-first already makes it resumable.
- Do not let `KeyboardInterrupt` leave the lock held.
- Do not run the full pass yourself. Prove it at `--limit 200` and hand the real run to the owner.

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

**T2 — Editing a consignor stops forking the row**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t2-consignor-row-fork.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
