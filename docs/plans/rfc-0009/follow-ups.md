# RFC 0009 — Follow-up ledger

Things found while executing RFC 0009 that were **deliberately not fixed in the
task that found them**, collected so the owner can triage them in one pass once
T0–T8 and T-FINAL are done.

This is not a bug tracker and not a backlog. It is the "we noticed this, it was out
of scope, someone should decide" list.

## For agents adding to this file

Append to the table for your task, creating the section if it does not exist. One
row per finding. Keep it to what a reader needs to decide:

- **Finding** — what is wrong, in one line, with a `file:line` link.
- **Why deferred** — the actual reason (out of scope / needs an owner decision /
  needs infra access / risky to change blind). "No time" is not a reason.
- **Impact if ignored** — be honest, including "probably none".

Rules:

- **Do not fix items in this file as a side errand.** They are here precisely
  because they were judged out of scope. If one blocks your task, say so in your
  report and ask.
- **Do not delete rows.** Mark a resolved row `~~struck through~~` with the task
  that handled it, so the owner can see it was dealt with rather than lost.

## Known before execution started

Recorded during planning so no task rediscovers them and treats them as its own bug.

| Finding | Why deferred | Impact if ignored |
|---|---|---|
| CLAUDE.md's "Third-Party APIs (Planned)" says the PSA API supplies **population** data. It does not — `TotalPopulation`/`PopulationHigher` are always `null` on the public API | Doc correction, assigned to T8 rather than done piecemeal | A future reader plans a feature around data that cannot be fetched |
| CLAUDE.md points at "claude-progress.txt Phase 4" for the third-party API plan. That file was replaced by the admin-enhancements rounds and has no Phase 4 | Same — T8 | Dangling cross-reference sends a reader on a dead hunt |
| CLAUDE.md's third-party section still names **PriceCharting** as the pricing source | Superseded by the owner's 2026-08-07 decision; T8 corrects it | A future task integrates a vendor the owner declined to pay for |
| `tcg_url` accepts a `javascript:` URI with no scheme validation (pre-existing, RFC 0008 era) | Pre-existing and out of scope, but RFC 0009 adds a second provider-supplied URL (`cert_image_url`) with the same shape — T1 validates the new field only | Admin-only self-XSS on the old field remains |
| Buy session persists **raw request JSON**, where prices arrive as JSON floats; `_serialize` is the only float→Decimal coercion | Known landmine, documented in CLAUDE.md Ops. T3 must send a JSON **number** in at least one test, since the existing tests all send strings and missed this in production | A money path 500s in production and tests stay green |

## T0 — Provider spike

Recorded 2026-08-07. T0 itself is **incomplete and blocked** on the owner (keys +
cert numbers); see [spike-findings.md](spike-findings.md). These rows are the
findings that are already settled and that belong to *other* tasks.

| Finding | Why deferred | Impact if ignored |
|---|---|---|
| RFC §5.2 and T7's rotation math assume **1 credit per slab**. PokemonPriceTracker's docs price graded data at **2 credits** (1 card + 1 `includeEbay`), so the free tier covers **50 slabs/day, not 100** — `ceil(N/50)` days for a full sweep, not `ceil(N/100)` ([rfcs/0009…md:88-96](../../rfcs/0009-slab-intake-and-graded-pricing.md#L88-L96)) | Vendor-doc claim, not yet confirmed against an authenticated call — confirming it is the blocked half of T0. Correcting the RFC and the T7 doc together is T8's job, not a side edit here | T7 sizes its nightly rotation off a doubled budget, so a shelf of 60+ slabs silently refreshes half as often as the docs promise, and the 429 arrives mid-sweep |
| RFC §5.1 says PSA returns **no rate-limit headers**. It returns no `X-RateLimit-*`, but a 429 **does** carry `Retry-After`, observed counting **833 → 797 s** — a ~13-minute rolling window, not a wait until UTC midnight, despite the body saying "per Day" ([spike-findings.md §1.1(b)](spike-findings.md)) | Observed on an **anonymous** (keyless) request, which may be a different bucket from an authenticated one. T2 owns the quota guard and must re-measure with a real key before designing around it | T2 builds a calendar-day counter resetting at 00:00 UTC. If the real window is rolling, the guard both blocks intake that would have succeeded and fails to predict the ones that won't |
| PSA returns the **same 429 body for a bad token as for a spent quota** — there is no 401 and no way to tell the two apart by status code ([spike-findings.md §1.1(a)](spike-findings.md)) | T2 owns PSA error handling and `/admin/slabs/quota`. RFC §9 already degrades all of these to manual entry, so nothing is broken — but the honest-reporting decision is T2's to make | `/admin/slabs/quota` reports "quota exhausted" when the real problem is a wrong or expired key, and an admin waits for midnight instead of fixing the key. Repeats the class of dishonest-failure bug the admin panel was already corrected for once |
| Nothing in `backend/src` stores a **TCGplayer product id** — not `CatalogCard`, not the TCGdex mapper, which keeps TCGplayer prices and discards the id. The pricing provider addresses cards by `tcgPlayerId` or free-text `search`, so first contact must be a **fuzzy name search** ([spike-findings.md §1.2](spike-findings.md)) | Capturing `tcgPlayerId` during catalog sync would touch the catalog schema and the sync path — well outside T0, and outside T6's brief too. `price_source_id` already absorbs the result, so the RFC design stands | Every slab's first price lookup is a fuzzy text match against a third-party database. Wrong-card matches price a slab off the wrong comps, and unlike our own matcher there is no `sets_agree` guard on their side |
| `tests/fixtures/psa/cert_not_found.json` will hold a **labelled stub**, not a real body: PSA's not-found is expected to be an empty 204, which cannot be written as valid JSON. Real status lives in the `.headers.json` sidecar | A recording decision made while writing the runner, not a defect. Flagged so T2 does not read the stub as a provider response shape | T2 writes a mapper that expects `{"_spike_note": …}` from PSA, or a test asserts against a placeholder as if it were real data |

## T1 — Slab fields + cert pointer

Recorded 2026-08-08. All four are consequences of the pointer-row design the RFC
chose (§6), found while writing T1 — not defects in it. The first is the only one
with a user-visible effect.

| Finding | Why deferred | Impact if ignored |
|---|---|---|
| **A cert pointer holds ONE item id, so duplicate detection can produce a false negative.** Sell a slab, re-buy it (two live items share cert `X`, pointer → the newer one), then correct the newer item's cert to `Y`. Reader verification correctly rejects the now-stale `X` pointer, but the older item still holding `X` is invisible — `/admin/slabs/certs/X` answers `owned: false` on a slab we own (`services/dynamodb.py`, `get_item_id_by_cert`) | A true fix is a GSI on `cert_number` (or a pointer holding a *list*), which is a table-level change well outside T1 and needs an owner call on the added index cost. The RFC explicitly specifies a single-pointer row, and RFC §9 already makes duplicate detection a **warning with override**, so nothing is blocked | An admin re-buys a slab already on the shelf without a warning. Requires a specific sell → re-buy → cert-correction sequence, so rare — but it fails **silently and in the direction of a wrong purchase**, which is the expensive direction |
| Cert pointer rows carry **no import generation** and are in neither scan's `entity_scope`, so `sweep_generation` and the catalog wipe never touch them (`services/dynamodb.py:462-470`, `:655-665`) | Deliberate, not an oversight: a generation-scoped pointer that no sweep knows about would be *worse* than an unscoped one. Reader verification means an orphan resolves to `None`, so correctness never depends on cleanup. Adding them to a sweep scope changes import semantics and belongs with whoever owns that path | Orphaned `CERT#` rows accumulate after imports and deletes. ~100 bytes each, costing one wasted point read on a lookup that was going to answer "not owned" anyway. Storage only; no wrong answers |
| `delete_inventory_item` leaves the item's cert pointer behind (`services/dynamodb.py:940-944`) | Same reasoning — the reader verifies, so the orphan is harmless, and deleting it would need the item's cert, i.e. a read before every delete. Covered by `test_deleted_item_stops_resolving_by_cert` | None beyond the storage note above |
| `cert_number` on `GradedInventoryItem` is an **unvalidated, unbounded `str`** — no length bound and no trim, unlike the bounded admin-text fields beside it. T1 guards the *read* path (a `max_length` on the endpoint's path param, and a `.strip()` when building the pointer key) but leaves the model field as found | Changing the model field is a write-path change touching the import and buy paths, not the read path T1 owns, and every existing row would have to satisfy the new bound. T3 extends the buy session to write slabs and is the natural place to decide it | A cert pasted at >2048 bytes reaches `put_inventory_item`, and the pointer write fails with a DynamoDB `ValidationException` **after** the item row is already written — a 500 on intake with the item saved and no pointer. The T1 endpoint is already guarded; this is the write side |
