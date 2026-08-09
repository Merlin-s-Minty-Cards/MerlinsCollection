# RFC 0009 — Slab intake + graded pricing: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never
appear in `git status` or reach anyone else. It now carries a pointer block sending
readers here. Record all RFC 0009 status **in this file**.

**Last updated:** 2026-08-08 (**T3 and T4 DONE** — the manual-entry plan's 7 tasks are
complete and **the T4 milestone is met: intake works end to end**, no scanner, no
camera, no PSA. T0 DONE with a split verdict — pricing PROCEED, PSA STOP on an
account-entitlement 403. T1 DONE — `0b21de2`. **T6 is the next task**)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](../../rfcs/0009-slab-intake-and-graded-pricing.md)
**Task index:** [`README.md`](README.md)

## ⚠️ THE PLAN CHANGED ON 2026-08-08 — READ THIS BEFORE PICKING UP A TASK

**STATUS 2026-08-08: the re-plan is COMPLETE.** All 7 of its tasks are done and
committed, T3 and T4 are `DONE` in the table below, and **intake works end to end
with no scanner, no camera and no PSA.** Read on for what changed and why; nothing
below is a pending instruction any more, except that `t3-*.md` / `t4-*.md` are still
not the authority.

PSA's cert API is **blocked at the account** (403, not fixable in code), so intake
was re-planned as **manual-first**. The authority for T3 and T4 is now:

- **Design:** [`docs/superpowers/specs/2026-08-08-slab-manual-entry-design.md`](../../superpowers/specs/2026-08-08-slab-manual-entry-design.md)
- **Task-by-task plan:** [`docs/superpowers/plans/2026-08-08-slab-manual-entry.md`](../../superpowers/plans/2026-08-08-slab-manual-entry.md)
  — **7 numbered tasks, executed in order, one per conversation.** Its checkboxes
  are the live record of what is done.

**`t3-buy-session-graded.md` and `t4-slabs-tab-scan-to-commit.md` are superseded**
and carry banners saying so. Do not execute them as written: T4's doc describes a
scan→PSA-lookup pipeline that cannot be built, and T3's doc contains a review-flagging
rule the owner has since reversed.

**T4 no longer depends on T2.** The dependency was the whole point of the re-plan,
and **both tasks are now finished** — see their rows below for shas.

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | Provider spike | **DONE (split verdict)** | `cd59ebc` | **Pricing = PROCEED, PSA = STOP.** All 19 cards priced, **including 3/3 Japanese** — coverage is better than feared. But PSA returns `403 "limited to approved customers"` on every call: the key is valid, **the account is not entitled**, and no code change fixes it. **T6 unblocked; T2 still blocked, now on PSA account approval rather than on this spike.** Also: auto-pricing off a name search picks the **wrong card ~1/3 of the time** — T6 must gate attachment on a verified match. Full evidence: [`spike-findings.md`](spike-findings.md) |
| T1 | Slab model + cert index | **DONE** | `0b21de2` | **Stale-pointer strategy: READER-SIDE verification** (`get_item_id_by_cert` re-reads the item and confirms it still claims the cert) — so T4 can trust `owned: true` **completely**; the residual risk is a rare false *negative*, first row of [`follow-ups.md`](follow-ups.md) T1. Endpoint is `GET /admin/slabs/certs/{cert}?company=PSA`, `200` either way |
| T2 | PSA lookup + quota guard | **DEFERRED (owner action)** | — | **Deferred WHOLE, not stubbed, and it no longer blocks anything in flight.** T4 was decoupled from it in the 2026-08-08 re-plan — the manual flow needs no new endpoint. Blocked on PSA approving the account: every call is `403 "limited to approved customers"`; the token and `Authorization: Bearer` format are both confirmed correct. Nothing about PSA's response shape is known, so the mapper cannot be written honestly. RFC §9 **now carries the 403 case** (added by Task 7) |
| T3 | Buy session → graded | **DONE** | `b9a9798`, `170eb09` | Executed as **Tasks 1–2 of the [manual-entry plan](../../superpowers/plans/2026-08-08-slab-manual-entry.md)**, not `t3-*.md`. `add_buy_item` validates `kind: "graded"` (`company`/`grade`/`cert_number` required, 422 at **add** time so a bad item cannot lose the staged batch); `confirm_buy_session` branches on `kind` and writes a `GradedInventoryItem` + an `ItemCategory.GRADED` transaction + the `CERT#` pointer. **31 passed** in `test_purchases.py`; the raw path was kept byte-identical and its pre-existing tests are the regression gate. Two confirmed traps: `BuySessionItem` is dead code (validation went in `add_buy_item`), and the `cert_verified_at → cert_lookup_failed` rule was **not** added (reversed — see Decisions). **The float landmine did not bite:** `_serialize` recurses into lists, so a JSON `grade: 9.5` lands as `Decimal("9.5")` — no `_serialize` change was needed |
| T4 | Slabs tab (manual entry → commit) | **DONE** | `c5b5a00`, `164d3b0`, `cb0b59f`, `ec56727` | **MILESTONE MET — intake is a usable product.** Executed as Tasks 3–6 of the manual-entry plan: `CertInput` (one path for wedge scanner and keyboard; Enter *advances*, never submits), `SlabEntryForm` (catalog autocomplete + free-text fallback, cert required, duplicate check on blur), `StagingTable` (presentational), and `/admin/slabs` + the sidebar entry. **20 frontend tests pass** across `components/admin/slabs` and `app/(admin)/admin/slabs`; `npm run lint` clean. Commit is the three-call sequence create → items → confirm, with `buy_price`/`grade` as JSON **numbers** and `manual_entry` deliberately **never** sent. **Four follow-ups**, two of them spec requirements the owner deferred — see [`follow-ups.md`](follow-ups.md) T4 |
| T5 | Camera scan fallback | **DEFERRED** | — | Behind T2, not T4: a camera yields a cert number, which without PSA resolves to nothing. Droppable |
| T6 | Pricing provider + slab list | NOT STARTED | — | **FULLY UNBLOCKED — this is the next task.** T0 cleared the provider (shape recorded as 19 fixtures, quota is self-reported, coverage proven) and **T4 is now done**, so its last dependency is satisfied and there are real graded items to price. Three binding notes: store `smartMarketPrice.price` **with its `confidence`**, pin `limit=1` (**cost is 2 x limit, billed even on zero hits**), and **auto-attach a price only on a verified `externalCatalogId` join** — a bare name search is wrong ~1/3 of the time. The owner nod on that last rule is still open, in Blocked below |
| T7 | Nightly sync + refresh fix | NOT STARTED | — | blocked on T6 |
| T8 | Docs + ops | NOT STARTED | — | blocked on T7 |
| T-FINAL | Verification + PR | NOT STARTED | — | blocked on all |

Statuses: `NOT STARTED` → `RED (awaiting owner confirmation)` → `IN PROGRESS` → `DONE`,
plus `BLOCKED` for a task that was started and cannot finish without the owner, and
`DEFERRED` for one deliberately taken out of the critical path — **`DEFERRED` is not
`BLOCKED`**: nothing in flight is waiting on T2 or T5, and neither is startable until
PSA approves the account.

## How to update this file

At the **end** of your task conversation, and only then:

1. Set your row's status to `DONE` and paste the commit sha.
2. Add one line to the Notes column if a later task needs to know something.
3. Add anything surprising to the **Decisions made during execution** table below.
4. Append out-of-scope findings to [`follow-ups.md`](follow-ups.md) — not here.

Do **not** mark a task `DONE` without the narrow test selection passing. Evidence
before assertions.

## Blocked / needs the owner

**Resolved 2026-08-08:** both keys are now in `backend/.env` and the owner supplied 19
certs, which unblocked T0. One new blocker replaced them, and it is external.

| Item | Needed from owner | Blocks |
|---|---|---|
| **Get PSA to approve this account for the public API — email them** | `403 {"Message":"Access to this API is limited to approved customers."}` on **every** call. Tried and ruled out: four auth header formats (§1.2 of spike-findings — `Authorization: Bearer` is correct), the EULA page at **https://www.psacard.com/publicapi/accepteula**, and **a key the owner updated on 2026-08-08 at 13:08**, which still 403s. It is **not endpoint-specific** — `GetByCertNumber` and `GetImagesByCertNumber` both 403 — so it is the **account**, not the call. **Stop retrying; each attempt spends quota and cannot succeed.** The remaining action is to email `collectors-apis@collectors.com` (the address PSA's own error body gives) and ask for public-API approval for the account. Key fingerprint at the last failed attempt, so a future "I updated it" is verifiable: `sha256[:12] = e4e50f8717d2` | **T2**, and the PSA half of T0 |
| Decide whether **T6 proceeds ahead of PSA** | Pricing is verified and unblocked, but without cert-verified identities an automatic price attach is wrong ~1/3 of the time. The proposed rule — auto-attach only on a verified `externalCatalogId` join, otherwise stage or Triage — needs an owner nod | T6 |
| *(optional)* more **Japanese** cert numbers | JP coverage measured 3/3, but on only 3 cards; T0 asked for at least 5 | confidence in T6 |
| Rotate both keys | Both were pasted into a chat transcript on 2026-08-07. Rotate once the integration is confirmed working | T8 |
| ~~`PSA_API_KEY` / `POKEMONPRICETRACKER_API_KEY` in `backend/.env`~~ | ~~Owner has the keys~~ — **done 2026-08-08** | — |
| ~~~20 real cert numbers off the shelf~~ | ~~Needed to measure coverage~~ — **19 supplied 2026-08-08** | — |

**When PSA approval lands, re-run the PSA half first** — it is the whole of
[`spike-findings.md`](spike-findings.md) §1.5 and costs 21 of the 100 daily calls:

```bash
cd backend
../.venv/Scripts/python.exe <scratchpad>/spike_slabs.py psa --certs <scratchpad>/certs.txt --execute
```

**The script and `certs.txt` live in a session scratchpad**, so a later session must
check they still exist and rebuild them from `spike-findings.md` (Appendix) if not.
The 19 cert numbers themselves are recorded in that doc's §4 coverage table.

## Decisions made during execution

| Date | Task | Decision | Why |
|---|---|---|---|
| 2026-08-07 | T0 | **Stopped rather than substituting invented certs or a mocked provider.** No authenticated call was made and no fixture was written | T0's prerequisites say to stop. A fixture recorded from a guessed shape is worse than none — T2 and T6 are mappers, and a plausible wrong shape looks like it works |
| 2026-08-07 | T0 | Ran **four unauthenticated probes** against both endpoints (no key sent, nothing charged) and recorded them | They cost no quota and settled real questions: PSA cannot distinguish a bad key from a spent quota, and it returns `Retry-After` on 429. See follow-ups.md |
| 2026-08-07 | T0 | Fixtures will be **body-only in `cert_<n>.json`, with status and headers in a `cert_<n>.headers.json` sidecar** | T0 requires the body be recorded unmodified, but the findings also need status codes and headers. A sidecar keeps both without editing the body |
| 2026-08-07 | T0 | `card_id` matching will **reuse `build_catalog_index` + `_match_card`**, not a new matcher | `card_text.py`'s docstring records what two matchers that normalize differently already cost this codebase. `_match_card` returning `None` is also already the correct route into Triage's `missing_card_id` |
| 2026-08-08 | T1 | **Stale cert pointers are handled on the READ side**, not by sweeping on write. `get_item_id_by_cert` re-reads the item and confirms it still claims that cert/company before returning it | The write-path sweep (mirroring `put_show`) would need the item's OLD cert, so it puts an extra `get_item` on **every** inventory write including the bulk import loop — and it still would not cover `delete_inventory_item`, which knows nothing about pointers. Reader verification costs one point read on a low-frequency admin path and makes an orphan harmless by construction. **T4 can trust `owned: true` fully** — a stale pointer can produce a false *negative* (see follow-ups) but never a false positive |
| 2026-08-08 | T0 | **Split the gate rather than failing it whole.** PSA is STOP, pricing is PROCEED, and T6 is unblocked while T2 is not | The two providers are independent, and the pricing question — the one that justified the spike — was fully answerable from the owner's own card names. Blocking T6 on PSA's entitlement problem would have stalled work that the evidence supports |
| 2026-08-08 | T0 | Drove the pricing sweep from the **owner's card names** (`--names-from`) instead of PSA identities, and recorded the query separately from the owner's label | PSA's 403 left no verified identities. The findings must not claim cert-verified coverage — a hit proves the vendor covers the CARD, not that PSA would resolve the cert to it, and the two claims are kept apart in §4 |
| 2026-08-08 | T0 | Pinned `limit=1` on every pricing query | Billing is `2 x limit` **and is charged even when the search matches nothing** — measured: a `limit=2` search with 0 hits cost 4 credits. `limit` is the cost dial, not a free breadth knob |
| 2026-08-08 | T0 | The one PSA fixture is named **`psa_403_not_approved.json`**, not `cert_<n>.json` | It holds an error body, not a cert response. Under the cert name, a later task would eventually write a mapper against it |
| 2026-08-08 | re-plan | **Intake becomes MANUAL-FIRST and T4 is decoupled from T2.** Owner-approved; design + 7-task plan under `docs/superpowers/` | PSA is blocked at the account with no code-side fix. Manual entry was already required to work in every degraded state (RFC §8) and for CGC/BGS/SGC (§9), so promoting it to the primary path makes the fallback the path everyone uses — it cannot rot. Nothing is discarded: PSA returns as a pre-fill |
| 2026-08-08 | re-plan | **T2 deferred WHOLE rather than stubbed PSA-free** | Without PSA a cert number identifies nothing, so a PSA-free `/lookup/{cert}` would return an empty shell on every call — code written only to be rewritten, and a false signal to callers that a lookup happened. The manual flow needs no new endpoint: catalog search and T1's duplicate check both already exist |
| 2026-08-08 | re-plan | **REVERSED T3's rule that `cert_verified_at is None` flags `cert_lookup_failed`.** Flag only on a missing `card_id` | With manual entry primary, that rule would flag every slab and turn Triage into noise. `cert_lookup_failed` means *automation tried and failed*; a human typing a slab in is the opposite. `_review_reason_for_buy` already returns `no_catalog_link`, so this removes work rather than adding it. **The frontend must therefore never send `manual_entry`** |
| 2026-08-08 | T8 (early, at the owner's request) | **`backend/.env.example` now carries blank `PSA_API_KEY=` and `POKEMONPRICETRACKER_API_KEY=`.** Deliberately **without** the `PSA_DAILY_QUOTA` / `PRICING_DAILY_QUOTA` lines T8 §2 also lists, and the comments diverge from T8's draft text on two points: a graded lookup is budgeted at **2 credits, not 1**, and PSA's "no rate-limit headers" is qualified (a 429 does carry `Retry-After`, and is also what a bad token returns) | The two quota knobs are not fields on `Settings` yet — T2 and T6 add them — and `model_config` uses `extra="ignore"`, so documenting them now would advertise settings that silently do nothing. T8 still owns the rest of §2 (CLAUDE.md, ECS secrets, README); only the two key placeholders are done |
| 2026-08-08 | T3 (Task 1) | Graded validation is enforced at **add-item time** (422 from `POST /{buy_id}/items`), not at confirm, and the check is `in (None, "")` rather than falsiness | A session that swallows a bad item and explodes on commit loses the whole staged batch — the exact failure the batch design exists to prevent. The `(None, "")` form rejects blanks without rejecting a numeric `0`, which is not a real grade but is also not the case the check is for |
| 2026-08-08 | T3 (Task 2) | `grade` is routed through `str()` before pydantic sees it, and **no `_serialize` change was needed** | The frontend sends `9.5` as a JSON number; `str()` gives pydantic an exact `Decimal("9.5")` instead of a binary float. The CLAUDE.md float landmine was checked rather than assumed: `_serialize` **recurses into lists**, so the number inside the session's item list is already coerced on write. **The rule that hand-entered slabs are not review-flagged is now shipped and test-covered** (`test_catalog_matched_slab_is_not_flagged_for_review`) |
| 2026-08-08 | T4 (Task 5) | `StagingTable` was built **presentational-only** — `rows` + `onRemove`, no state, no api, no validity gating | Owner constraint. The consequence is recorded rather than hidden: the design doc's per-row commit gating landed in neither component, and is now the first row of [`follow-ups.md`](follow-ups.md) T4 |
| 2026-08-08 | T4 (Task 6) | **Two design-doc requirements were raised with the owner and DEFERRED, not dropped** — per-row commit gating, and "refocus the cert field" on success | Deferring beat widening Task 6. The gating is **unreachable by construction today** (`SlabEntryForm` will not emit a row with a blank grade or cost, and `StagingTable` has no edit path), so implementing it would be untestable bloat — **it becomes real the moment per-row editing is added**, which both the plan and the design doc still promise. The refocus needs a prop or imperative handle outside Task 6's file list. Both in [`follow-ups.md`](follow-ups.md) T4 |
| 2026-08-08 | T7 | The **RFC was corrected in place** (§1/§5.1/§5.2/§5.3/§9) rather than superseded wholesale, and the T0 numbers were sourced from [`spike-findings.md`](spike-findings.md) rather than paraphrased | The RFC's §3 "what already exists" and §6 data model are still correct and still the best reference in the repo; superseding the whole document would have thrown those away to fix four sections. §7's `/lookup` endpoint and §8's scan bar are the parts left describing the unbuilt PSA flow, and the amendment banner now says exactly that |
| 2026-08-08 | T1 | `put_inventory_item` writes the **item first, then the pointer**, and lets a pointer failure propagate rather than swallowing it | The reverse order lets an advisory index write block a real inventory write. This way a crash between them leaves a *missing* pointer (a missed warning, which the RFC already allows an admin to override) rather than a wrong one, and the retry is an idempotent upsert of both |

## Baseline at planning time (2026-08-07)

Measured, not assumed — so a later task can tell a regression from a pre-existing
failure:

- Backend suite: **1369 tests / 52 files, ~2 min**. Two pre-existing `test_auth.py`
  failures are known and are **not** yours to fix.
  - **Re-measured at the end of T1 (2026-08-08): 1407 passed, 0 failed, 2m21s.**
    That is 1369 + T1's 38 new tests, and the two `test_auth.py` failures **did
    not reproduce** — nothing in T1 touches auth, so treat the "two known
    failures" line above as stale rather than as something T1 fixed. A later task
    seeing an auth failure should not assume it is pre-existing.
- Frontend: **545 tests / 73 files, ~31 s**.
- MCP: **98 tests / 7 files, ~1 s**.
- Lint: ruff on `backend/src` and `npm run lint --workspace=frontend` both have
  known pre-existing findings. Compare counts; do not chase them to zero.

Use `./.venv/Scripts/python.exe`, never bare `python` — the bare form resolves to an
unrelated venv with no pytest. If results look impossible, this checkout is a git
worktree and a global editable install can shadow it with the sibling repo's
backend; verify which package loaded before debugging anything else (CLAUDE.md).
