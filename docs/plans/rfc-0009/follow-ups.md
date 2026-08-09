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

Recorded 2026-08-07, **revised 2026-08-08 once the keys and certs arrived.** T0 now
has a **split verdict** — pricing PROCEED, PSA STOP (the account is not approved for
PSA's public API, a 403 no code change can fix). See
[spike-findings.md](spike-findings.md). Rows below that a live call has since
confirmed or overturned are marked in place; struck-through text is what the earlier
keyless evidence had suggested.

| Finding | Why deferred | Impact if ignored |
|---|---|---|
| **CONFIRMED LIVE 2026-08-08.** RFC §5.2 and T7's rotation math assume **1 credit per slab**. The API's own response says `"costPerCard": 2`, and **billing is on `limit`, not on hits** — a `limit=2` search matching *zero* cards was still charged 4 credits. Free tier = **50 lookups/day at `limit=1`**; `ceil(N/50)` days for a sweep ([rfcs/0009…md:88-96](../../rfcs/0009-slab-intake-and-graded-pricing.md#L88-L96)) | No longer a doc claim — measured. Correcting the RFC and the T7 doc together is T8's job, not a side edit here | T7 sizes its rotation off a doubled budget and refreshes half as often as promised; worse, any `limit>1` multiplies the cost silently, so a "let's fetch 5 candidates" change quietly cuts the daily budget to 10 slabs |
| RFC §5.1 says PSA returns **no rate-limit headers**. It returns no `X-RateLimit-*`, but a 429 **does** carry `Retry-After`, observed counting **833 → 797 s** — a ~13-minute rolling window, not a wait until UTC midnight, despite the body saying "per Day" ([spike-findings.md §1](spike-findings.md)) | Observed on an **anonymous** (keyless) request. **Still unverified for an authenticated caller** — the approved-account 403 (below) means no successful authenticated PSA call has ever been made from this codebase. T2 must re-measure once the account is approved | T2 builds a calendar-day counter resetting at 00:00 UTC. If the real window is rolling, the guard both blocks intake that would have succeeded and fails to predict the ones that won't |
| ~~PSA returns the **same 429 body for a bad token as for a spent quota**~~ — **CORRECTED 2026-08-08 with the real key.** An *unrecognized* credential falls into the anonymous 429 bucket, but a *recognized but unentitled* token returns a distinguishable **`403 {"Message":"Access to this API is limited to approved customers."}`**. RFC §9's failure list has no 403 case at all ([spike-findings.md §1.2-1.3](spike-findings.md)) | T2 owns PSA error handling and `/admin/slabs/quota`, and cannot be written until the account is approved anyway | An admin sees "cert lookup failed" and waits for a quota that was never the problem. The fix for a 403 is a support email to PSA, not a retry and not waiting for midnight — the UI must be able to say so |
| ~~Nothing in `backend/src` stores a TCGplayer product id … first contact must be a fuzzy name search~~ — **LARGELY SUPERSEDED 2026-08-08.** The pricing response carries **`externalCatalogId` in TCGdex shape**, and `en:<externalCatalogId>` point-reads straight to our own `card_id` (verified on 4 cards; **13 of 19** joined). It also returns `tcgPlayerId`, which `price_source_id` should store so later refreshes are exact ([spike-findings.md §3.1](spike-findings.md)) | The residual gap is real and is the row below (JP cards carry no `externalCatalogId`). Capturing `tcgPlayerId` at catalog-sync time is still out of scope | Kept for the record: T6 should try the deterministic join **before** any fuzzy path, and never invent a name-matching step where an id join is available |
| **The vendor's name search returns the wrong card roughly a third of the time**, and a wrong answer is indistinguishable from a right one — same 200, same populated price block. `Umbreon Gold Star` → 0 hits; `Umbreon Star` → Umbreon **VMAX**; `M Latias EX` → **Latios** EX; `Muk & Alolan Muk GX` → **Alolan Muk GX**; `Pikachu` → 1 of 592 ([spike-findings.md §3.3](spike-findings.md)) | This is a T6 **design constraint**, not a defect to fix here, and the mitigation (auto-attach only on a verified `externalCatalogId` join) is T6's to implement | T6 confidently prices a third of the shelf off the wrong comps. Mispricing that lands in the business's favour is the exact class of bug the condition-pricing correction already cost this codebase once |
| **Japanese cards carry no `externalCatalogId`** — all 3 JP cards in the sample returned `null`, so the deterministic catalog join is English-only and JP slabs fall back to fuzzy matching against `ja:`-keyed rows ([spike-findings.md §3.2](spike-findings.md)) | Nothing to fix on our side — it is missing vendor data. RFC §9 already routes an unmatched card to Triage as `missing_card_id`, so it degrades correctly | **JP slabs land in Triage as the norm rather than the exception.** Not a bug, but the owner should hear it before they meet it, and it makes the JP half of intake meaningfully more hands-on |
| **Two Trainer Gallery cards are missing from our catalog**: `en:swsh9-TG23` and `en:swsh12-TG29` both come back `None` from `get_catalog_card`, though the vendor knows them. TCGdex appears to file TG subsets under a different set id | A catalog-completeness gap, entirely outside RFC 0009 — it predates this work and affects raw cards too, not just slabs | Any Trainer Gallery card, slab or raw, cannot be linked to a catalog row, so it gets no market price and no card art, and it lands in Triage with no way for an admin to resolve it |
| **The provider returns ~23 grade buckets, not the 3 the RFC names** — `psa1`–`psa10` **including half grades** (`psa8_5`), plus `bgs*`, `cgc*`, `sgc*`, `ace*`, `tag*` and `ungraded` ([spike-findings.md §2.2](spike-findings.md)) | Storage already fits (`GRADEDPRICE#<company>#<grade>`, `PricePoint.grade` is a `Decimal`), so nothing is blocked. Deciding *which* buckets to store and show is a T6/owner call | An opportunity missed rather than a bug: the CGC/BGS/SGC manual-entry path (RFC §9) could be given real market values from data we are already paying a credit for |
| `tests/fixtures/psa/cert_not_found.json` will hold a **labelled stub**, not a real body: PSA's not-found is expected to be an empty 204, which cannot be written as valid JSON. Real status lives in the `.headers.json` sidecar | A recording decision made while writing the runner, not a defect. Flagged so T2 does not read the stub as a provider response shape | T2 writes a mapper that expects `{"_spike_note": …}` from PSA, or a test asserts against a placeholder as if it were real data |
| **The secret-leak checks in T8 and T-FINAL match their own text.** `grep -l "pokeprice_\|^PSA_API_KEY=."` hits [t8-docs-and-ops.md:56](t8-docs-and-ops.md) and [t-final-verification.md:72](t-final-verification.md) — the two docs that quote the pattern. Both say to expect **no output** and to **stop** if anything matches | Editing another task's doc from outside it is exactly the side errand this ledger forbids; T8 and T-FINAL own their own commands | The check cries wolf on a clean tree. Either someone burns time proving a false positive is a false positive, or — much worse — learns to wave the check through, which is how a real key ships. Fix: exclude `docs/plans/` or grep for a value pattern rather than the bare key name |

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

## T4 — Slabs tab (manual entry → commit)

Recorded 2026-08-08 at the end of Task 6 of the
[manual-entry plan](../../superpowers/plans/2026-08-08-slab-manual-entry.md), with
the owner's explicit decision to defer rather than widen Task 6. The first two are
**spec requirements the plan does not implement**, raised before implementing and
deferred deliberately — they are not oversights.

| Finding | Why deferred | Impact if ignored |
|---|---|---|
| **The spec's per-row commit gating is unimplemented and currently unreachable.** The design doc (*Staging table and commit*) requires "commit is disabled while any row lacks a cost or a grade, and the button says which". It is in neither `StagingTable` (presentational by owner constraint, Task 5) nor the page — [`slabs/page.tsx`](../../../frontend/app/(admin)/admin/slabs/page.tsx) gates only on `busy \|\| rows.length === 0` | **The gate cannot fire today.** `SlabEntryForm.submit` refuses to emit a row with a blank grade or cost ([SlabEntryForm.tsx:111-114](../../../frontend/components/admin/slabs/SlabEntryForm.tsx#L111-L114)), and `StagingTable` is read-only, so no staged row can lack either field. Implementing a branch no input can reach is untestable-by-construction bloat | **None until per-row editing lands** — and that is exactly when it bites. The File Structure table in the plan and the design doc both promise "per-row edit" on `StagingTable`; whoever builds it must add this gating in the same change, or an edited-to-blank row reaches `add_buy_item` and 422s mid-batch |
| **"Refocus the cert field" on success is not implemented.** The design doc requires "On success: toast with count and total, clear the table, refocus the cert field". The page does the toast and the clear; nothing returns focus. `CertInput`'s `autoFocus` fires only on mount, and the form is never remounted after a commit | Needs a prop or imperative handle on `SlabEntryForm`, which is outside Task 6's declared file list (`page.tsx`, `AdminShell.tsx`, its test). No test covers it either. Owner deferred it 2026-08-08 | **The one ergonomic gap in the flow.** After each committed batch the operator must click back up to the cert field before typing the next slab — with a stack of slabs in hand, that is the interaction the feature lives on. Cheap to fix, worth doing before the tab sees real use |
| Nothing prevents staging the **same cert twice in one batch**. Both rows commit; the second `CERT#` pointer write overwrites the first, so the pointer resolves to only one of the two items | The duplicate check is a per-field, on-blur call against *persisted* inventory (`GET /admin/slabs/certs/{cert}`); it knows nothing about the client-side batch. A batch-local check is new behaviour, not a fix to existing behaviour, and RFC §9 makes duplicate detection a warning with override anyway | Two real inventory items exist and are both correct; only the advisory pointer is single-valued. Same class as the T1 false-negative row above, and the same eventual fix (a GSI or a list-valued pointer) resolves both |
| `Number(r.buy_price)` is unvalidated at the page boundary: a cost typed as `1,200` yields `NaN`, which `JSON.stringify` sends as `null` | `SlabEntryForm` requires the field to be non-blank but not numeric, so the validation gap is the form's, not the page's. It fails safely as-is | `add_buy_item` rejects the null with a 422, the page shows its `role="alert"` and **keeps the whole batch on screen** — the correct stop-don't-half-commit behaviour. The operator sees a backend error message rather than a field-level one, which is worse UX but not a wrong write |
