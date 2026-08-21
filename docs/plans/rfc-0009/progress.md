# RFC 0009 — Slab intake + graded pricing: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never
appear in `git status` or reach anyone else. It now carries a pointer block sending
readers here. Record all RFC 0009 status **in this file**.

**Last updated:** 2026-08-09 (**T-FINAL DONE — RFC 0009 IS COMPLETE.** All three
suites green together for the first time: **1502 backend / 575 frontend / 98 MCP**,
lint clean, leak sweep clean, `next build` green. The build caught **one real bug**
the entire suite missed — the `/admin/slabs` priced filter never reached the backend
— fixed under the RED gate with owner confirmation. T0/T1/T3/T4/T6/T7/T8 DONE; T2 and
T5 are **WON'T DO** — the PSA cert API became a paid feature and the owner declined it on 2026-08-10, so the gap is permanent rather than pending (RFC 0010 T12). They block nothing. **There is no next
task.** **ONE** owner action is still outstanding and it is not a code task:
**rotate the PokemonPriceTracker key.** The former second action — emailing
`collectors-apis@collectors.com` for PSA approval — is **WITHDRAWN**, and the PSA
key needs no rotation because no code reads it)
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
| T2 | PSA lookup + quota guard | **WON'T DO (2026-08-12)** | — | **WITHDRAWN, not deferred. The PSA cert API is now a PAID feature and the owner declined it on 2026-08-10** (RFC 0010 §H, T12). The gap is permanent, so there is nothing to wait for and nothing to build: `PSA_API_KEY` stays inert, `test_config.py::test_there_is_still_no_psa_setting_to_configure` stays as the tripwire, and this doc stays in the repo because a decision recorded beats a gap nobody can explain. Prior status: **Deferred WHOLE, not stubbed, and it no longer blocks anything in flight.** T4 was decoupled from it in the 2026-08-08 re-plan — the manual flow needs no new endpoint. Blocked on PSA approving the account: every call is `403 "limited to approved customers"`; the token and `Authorization: Bearer` format are both confirmed correct. Nothing about PSA's response shape is known, so the mapper cannot be written honestly. RFC §9 **now carries the 403 case** (added by Task 7) |
| T3 | Buy session → graded | **DONE** | `b9a9798`, `170eb09` | Executed as **Tasks 1–2 of the [manual-entry plan](../../superpowers/plans/2026-08-08-slab-manual-entry.md)**, not `t3-*.md`. `add_buy_item` validates `kind: "graded"` (`company`/`grade`/`cert_number` required, 422 at **add** time so a bad item cannot lose the staged batch); `confirm_buy_session` branches on `kind` and writes a `GradedInventoryItem` + an `ItemCategory.GRADED` transaction + the `CERT#` pointer. **31 passed** in `test_purchases.py`; the raw path was kept byte-identical and its pre-existing tests are the regression gate. Two confirmed traps: `BuySessionItem` is dead code (validation went in `add_buy_item`), and the `cert_verified_at → cert_lookup_failed` rule was **not** added (reversed — see Decisions). **The float landmine did not bite:** `_serialize` recurses into lists, so a JSON `grade: 9.5` lands as `Decimal("9.5")` — no `_serialize` change was needed |
| T4 | Slabs tab (manual entry → commit) | **DONE** | `c5b5a00`, `164d3b0`, `cb0b59f`, `ec56727` | **MILESTONE MET — intake is a usable product.** Executed as Tasks 3–6 of the manual-entry plan: `CertInput` (one path for wedge scanner and keyboard; Enter *advances*, never submits), `SlabEntryForm` (catalog autocomplete + free-text fallback, cert required, duplicate check on blur), `StagingTable` (presentational), and `/admin/slabs` + the sidebar entry. **20 frontend tests pass** across `components/admin/slabs` and `app/(admin)/admin/slabs`; `npm run lint` clean. Commit is the three-call sequence create → items → confirm, with `buy_price`/`grade` as JSON **numbers** and `manual_entry` deliberately **never** sent. **Four follow-ups**, two of them spec requirements the owner deferred — see [`follow-ups.md`](follow-ups.md) T4 |
| T5 | Camera scan fallback | **WON'T DO (2026-08-12)** | — | Follows T2: a camera yields a cert number, and without PSA a cert number resolves to nothing. The disabled "Camera scan" button was removed from `/admin/slabs` by RFC 0010 T12 — a disabled button implies a roadmap, and there is none |
| T6 | Pricing provider + slab list | **DONE** | `65ecece` | **53 backend + 8 frontend tests pass**; ruff and `next lint` clean. **The owner approved the verified-join rule** (see Decisions) — `attach_price` refuses unless `en:<externalCatalogId>` equals the item's own `card_id`, and an unpriced slab is **NOT** Triage-flagged, it surfaces at `/admin/slabs?priced=false`. **"No coverage" is an ABSENT KEY, confirmed against all 19 fixtures — not one contains a `0`** (T7 depends on this: a missing grade key means "no comps", and must never become `Decimal("0")`). Also: **nothing calls `attach_price` yet — that is T7's job.** `prices(id)` is the exact, non-fuzzy call T7 should use; `resolve()` is the fuzzy one and runs once per card ever. `services/slab/quota.py` was created HERE, not in T2 |
| T7 | Nightly sync + refresh fix | **DONE** | `fbf1553` | **138 tests pass** in the three named files, **218 more** across the blast radius (`test_dynamodb`, `test_pricing`, `test_catalog_wipe`, the three `scripts/` files); ruff clean. `refresh_graded_prices` walks owned slabs stalest-first (never-priced first), capped at **50 lookups**, deduped by `(card_id, company, grade)`, and a per-run memo means one card is ONE call whatever grades of it we hold — so `resolve()` runs at most once per card per night. **TWO OWNER DECISIONS, 2026-08-09** (see Decisions): the job DOES do first contact, and a hand-typed price is overwritten unless **pinned**. `POST /admin/slabs/refresh-prices` + `PUT /admin/slabs/{id}/price/pin` are new; the Market button now prices slabs too. **T8 must know:** the pin has NO frontend control yet, so nothing is pinned in practice and the provider currently always wins — [`follow-ups.md`](follow-ups.md) T7 row 3 |
| T8 | Docs + ops | **DONE** | `9afb79d` | **5 tests pass** in `test_config.py` (2 pre-existing + 3 new doc guards); the app boots with both keys **forced empty**; ruff clean on `backend/src`; leak check clean outside `docs/plans/`. **The T8 doc was itself wrong in FIVE places and now carries a correction banner** — the biggest being that it describes a PSA-per-slab flow and a camera that do not exist. **`PSA_API_KEY` is read by NO code** (no `psa_api_key` field on `Settings`; `extra="ignore"` swallows it), so it is documented as inert and `PSA_DAILY_QUOTA` was not added at all — only `PRICING_DAILY_QUOTA` exists. **The slab quota counters touch no DynamoDB table**, so the task role needs nothing new, but the ECS **execution** role needs `secretsmanager:GetSecretValue`. **KEY ROTATION IS STILL NOT DONE** — owner action in two vendor portals, procedure now written in `docs/aws-setup.md` Phase 8 |
| T-FINAL | Verification + PR | **DONE — but see the merge blocker** | `6486773`, `80deb9c` | **DO NOT MERGE until the slab cost input is fixed.** Found 2026-08-10: a non-numeric cost (`1,200`) posts as `null`, is accepted with a 200, and raises mid-loop in `confirm_buy_session` **after earlier rows are already written** as real inventory — a partial write the UI reports as "Nothing was created". Verified in the code, not inferred; the follow-ups row that called this "fails safely" was wrong and is corrected. Behavioural change on a money path, so it is RED-gated and left for the owner to confirm. Everything below still holds | **RFC 0009 IS COMPLETE.** Full suite, all three layers, measured 2026-08-09: **backend 1502 passed / 0 failed / 2m13s**, **frontend 575 passed / 78 files / 28s**, **MCP 98 passed / 7 files / 1.0s**. `ruff check backend/src` clean; `next lint` clean; leak sweep clean across all 190 branch commits; app boots with both keys forced empty and `build_pricing_provider()` returns `None`. **`next build` caught a REAL BUG the whole suite missed** — `/admin/slabs` passed `{ params: {…} }` to `api.get`, whose second arg IS the params record, so the request emitted `?params=[object Object]` and **the unpriced worklist filter silently returned every slab**. Fixed under the RED gate with 2 new tests (owner confirmed GREEN). **Vitest does not typecheck — `next build` is the only gate that catches this class; never skip it.** Also fixed this doc's self-matching leak command and its stale PSA/camera smoke checklist |

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
| ~~**Get PSA to approve this account for the public API — email them**~~ | **CLOSED / WITHDRAWN 2026-08-10. Do not do this.** PSA's cert API became a **paid** feature and the owner declined it, so approval is no longer being sought and **T2/T5 are WON'T DO** (RFC 0010 §H). **Stop retrying the endpoint and do not email `collectors-apis@collectors.com`** — every attempt costs quota and cannot succeed. The evidence below is kept as the record of why this was investigated properly rather than abandoned on a guess. *(Original entry follows.)* **RE-TESTED 2026-08-10 at the owner's request — STILL 403, nothing has changed.** Checked against PSA's own Swagger this time (`https://api.psacard.com/publicapi/swagger.json`, which confirms `basePath: /publicapi`, the route `/cert/GetByCertNumber/{certNumber}`, and `securityDefinitions: {Bearer: {type: apiKey, name: Authorization, in: header}}`). **The bearer format is now positively CONFIRMED CORRECT by differential**: `Authorization: bearer <token>` and `Authorization: Bearer <token>` both return the entitlement **403**, while the raw token with no scheme falls into the anonymous **429** bucket — i.e. a recognized credential 403s and an unrecognized one does not, so the token IS authenticating and the account is what is refused. Key fingerprint `sha256[:12] = e4e50f8717d2`, **identical to 2026-08-08**, so the key was never rotated either. Original evidence follows. `403 {"Message":"Access to this API is limited to approved customers."}` on **every** call. Tried and ruled out: four auth header formats (§1.2 of spike-findings — `Authorization: Bearer` is correct), the EULA page at **https://www.psacard.com/publicapi/accepteula**, and **a key the owner updated on 2026-08-08 at 13:08**, which still 403s. It is **not endpoint-specific** — `GetByCertNumber` and `GetImagesByCertNumber` both 403 — so it is the **account**, not the call. **Stop retrying; each attempt spends quota and cannot succeed.** The remaining action is to email `collectors-apis@collectors.com` (the address PSA's own error body gives) and ask for public-API approval for the account. Key fingerprint at the last failed attempt, so a future "I updated it" is verifiable: `sha256[:12] = e4e50f8717d2` | **T2**, and the PSA half of T0 |
| ~~Decide whether **T6 proceeds ahead of PSA**~~ | **ANSWERED 2026-08-09.** Owner approved **verified-join-only** attachment, and chose **"list only, no Triage flag"** for the slabs that fail it. Both are implemented and test-covered in `65ecece` | — |
| *(optional)* more **Japanese** cert numbers | JP coverage measured 3/3, but on only 3 cards; T0 asked for at least 5 | confidence in T6 |
| **Rotate both keys — STILL OUTSTANDING after T8, and T8 could not do it** | Both were pasted into a chat transcript on 2026-08-07. This is an owner action in **two external vendor portals**; no AWS command performs it. Procedure, now written down in `docs/aws-setup.md` Phase 8: issue a new key in the vendor portal → update `backend/.env` → update the Secrets Manager secret → **force a new ECS deployment** (secrets resolve at task start, unlike task-role permissions which are read per request). The pricing key is the one that matters — the PSA key is read by no code at all | nothing in code; **flagged, not done** |
| ~~`PSA_API_KEY` / `POKEMONPRICETRACKER_API_KEY` in `backend/.env`~~ | ~~Owner has the keys~~ — **done 2026-08-08** | — |
| ~~~20 real cert numbers off the shelf~~ | ~~Needed to measure coverage~~ — **19 supplied 2026-08-08** | — |

~~**When PSA approval lands, re-run the PSA half first**~~ — **WITHDRAWN
2026-08-10: approval is not coming, because it is no longer being sought.** The
API is paid and the owner declined it (RFC 0010 §H). **Do not run the `psa`
probe.** The command is retained only so the record shows what was tried:

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
| 2026-08-09 | T6 | **OWNER DECISION: attach a price only on a verified `externalCatalogId` join, and do NOT Triage-flag the slabs that fail it.** Both options were presented with their measured costs; the owner took the recommended pair | The join is self-verifying — our own catalog row confirms the vendor's answer — and it caught all three wrong matches in T0's sample. Not flagging keeps Triage usable: every JP slab fails the join *by construction* (no `externalCatalogId` exists for them, ever), so flagging would have made Triage a list of cards nobody can fix, which is the exact noise problem that got a T3 rule reversed a week earlier. `/admin/slabs?priced=false` is the worklist instead |
| 2026-08-09 | T6 | `GradedPrices.prices` is keyed by the **vendor's own grade key** (`"psa10"`, `"bgs9_5"`, `"ungraded"`), not the T6 doc's illustrative bare `{"10": …}` | A bare grade loses the COMPANY, and our storage is keyed by both. A typical card returns ~23 buckets spanning PSA/BGS/CGC/SGC/ACE/TAG — real data, not hypothetical, and exactly what the CGC/BGS/SGC manual path (RFC §9) will want later. `grade_key(company, grade)` is the one converter |
| 2026-08-09 | T6 | `resolve()` returns a **`ResolvedCard`, not the doc's `str \| None`**, and carries the prices from the same response | The verified-join rule needs `external_catalog_id` back from the resolve in order to check it — a bare `price_source_id` string makes the owner-approved rule unimplementable. Carrying the prices costs nothing: `includeEbay=true` already paid for them, so a first-time lookup is ONE call, not two. `prices(id)` stays separate because T7 refreshes by id and never searches |
| 2026-08-09 | T6 | **Currency: absent → USD with `currency_assumed: True`; a STATED non-USD → refuse, never convert** | Spike §2.2 measured that there is no currency field anywhere in the response. USD is the right reading (eBay-US comps) but it must not be a *silent* one. Not converting is deliberate: the codebase's one conversion precedent (`eur_usd_rate`) records its rate in `value_note`, and a second quieter conversion path is how a wrong number becomes invisible |
| 2026-08-09 | T6 | Two files outside the T6 doc's list were touched: **`services/dynamodb.py`** (a `source`/`confidence` keyword on `set_graded_market_value`, plus a new `get_graded_price_row`) and **`services/slab/quota.py`** (created here rather than reused from the deferred T2) | The doc says "no schema change is needed" and that is still true — the ROW shape is unchanged. But the setter hardcoded `source: "manual"` and the getter returned only the bare figure, so "priced by a provider, 3 days ago" was unreadable, and the doc's own `GET /admin/slabs` contract requires exactly that. Both changes are additive and keyword-only; all 136 existing tests over those modules still pass |
| 2026-08-09 | T6 | `_search_name` prefers the **CATALOG** name over the admin's own label when the item is linked | Not a slight on the admin — it is what T0 measured. The vendor's search is literal, so "Mega Latias EX" finds Latios and "Umbreon Gold Star" finds nothing at all, while the catalog name is the vocabulary the vendor's catalog was built from. A nameless unlinked slab is now refused **before** the call rather than searched for with an empty query, which would be billed the full 2 credits and could only return an arbitrary card |
| 2026-08-09 | T7 | **OWNER DECISION: the nightly job DOES do first contact** — it runs the fuzzy `resolve()` for a slab that has a `card_id` but no cached `price_source_id`, gated by T6's verified join. This REVERSES the T7 doc's RED item 5 ("a slab with no `price_source_id` is skipped") | That line predates T6. Nothing anywhere sets `price_source_id` — PSA intake was going to, and PSA is dead — so a job that skipped those slabs would price **nothing, ever**, and `attach_price`'s entire resolve branch would be dead code. The owner's question ("I thought you just need the cert number?") is worth recording as the answer too: the cert identifies the slab **to PSA**, and the pricing vendor has never heard of cert numbers — it prices cards. Even with PSA working, the vendor still has to be searched. The accepted cost is that an unjoinable slab re-burns 2 credits nightly; counted in the run summary and filed as [`follow-ups.md`](follow-ups.md) T7 row 2 |
| 2026-08-09 | T7 | **OWNER DECISION: a hand-typed price is NOT protected from the provider unless it is explicitly PINNED.** Both "manual always wins" and "provider always wins" were offered with their costs and both were declined. `pinned` is a boolean on the `GRADEDPRICE#` row; `PUT /admin/slabs/{item_id}/price/pin` sets it; `GET /admin/slabs` reports it per row | The T7 doc names this a real business decision and says to ask. "Manual always wins" would freeze every slab the owner had ever touched out of automatic pricing permanently — and `/admin/slabs?priced=false` would not surface them either, because they DO have a value, so the freeze would be invisible. The owner also chose pinning as a **separate deliberate action** rather than an automatic consequence of typing a price. **The consequence is live and is in follow-ups T7 row 3: there is no frontend toggle yet, so nothing is pinned and the provider currently always wins** |
| 2026-08-09 | T7 | **The quota counter STAYS per-process and in-memory.** T6 row 2 assigned this call to T7; T7 made it rather than deferring it again | The nightly job is one scheduled process, the counter self-corrects from `x-ratelimit-daily-remaining` on every successful call, and the failure mode of an overshoot is a 429 the loop already stops cleanly on. A DynamoDB counter costs a table decision plus a write per lookup to prevent a bounded, self-healing delay. The specific trigger to revisit is recorded in follow-ups T7 row 1 rather than pre-built |
| 2026-08-09 | T7 | `set_graded_market_value` gained `pinned: bool \| None = None`, where `None` **preserves the stored flag at the cost of a read**, rather than defaulting to `False` | The method is a whole-row `put_item`. A default of `False` means an admin re-typing a value silently clears a pin someone set on purpose — and they would find out only when the provider replaced the figure they were protecting. One point read per price write is the cheaper mistake |
| 2026-08-09 | T7 | A per-run `_ProviderMemo` wraps the provider, so ONE card is ONE call whatever grades of it we hold | Not primarily a cost fix. One vendor response carries every grade (~23 buckets), so a card held in PSA 9 and PSA 10 would otherwise cost two lookups **and two fuzzy searches** — and the fuzzy search is where T0 measured the wrong-card answers coming from. Halving how often we ask is a correctness win. Scoped to one run: last night's figure is what tonight exists to replace |
| 2026-08-09 | T7 | The loop aborts after **5 consecutive failures**, against the depth pass's 25 | The unit of waste is different. Every failed pricing call is still BILLED — the client debits as soon as the vendor answers, whatever it answered — so a vendor 500ing at everything would spend the entire day's budget producing nothing. A TCGdex failure costs only time |
| 2026-08-09 | T7 | `build_pricing_provider()` returns **`None`** on a missing key rather than raising, and the two callers treat that absence oppositely: `run_daily_sync` degrades quietly, `POST /admin/slabs/refresh-prices` reports `state: "failed"` | Nobody is watching the nightly job, and letting an unset graded key take down the depth pass and both snapshots would be a strictly worse trade — T8's checklist includes rotating both keys, so "no key right now" is a state this job will really meet. A human pressed the button, though, and telling them "completed" when nothing could have been fetched is a lie they cannot see through |
| 2026-08-09 | T7 | RED item 9 ("assert against a PSA fake that records calls") was implemented as a **socket block** — `httpx.Client.send`/`request` raise for the duration of the run — rather than a PSA spy | There is no PSA client to spy on: T2 is deferred whole. Inventing a seam purely to assert against it would test the seam. Blocking the socket is strictly stronger: it catches a PSA call, a second pricing client, or anything else that constructs its own transport behind the caller's back |
| 2026-08-09 | T8 | **Documented `PSA_API_KEY` as INERT rather than adding the `Settings` field to make the doc true.** Confirmed by grep: zero hits for `psa_api_key` in `backend/src` and `backend/tests`, so `extra="ignore"` swallows the env var entirely. `PSA_DAILY_QUOTA` was not added either | The field belongs with the client that reads it (T2). Adding it now ships config with no reader — the same "advertises a setting that silently does nothing" trap the owner's 2026-08-08 note warned about, just pointed the other way. Labelling it costs three sentences in three files and is honest today; `test_config.py::test_there_is_still_no_psa_setting_to_configure` is the tripwire that fails the moment T2 adds the field, so the labels cannot outlive their truth |
| 2026-08-09 | T8 | **Corrected the T8 doc IN PLACE with a five-item banner instead of executing it as written.** Its §1 described a PSA-per-slab flow and a camera that were never built, §2 had the credit math wrong twice and named two non-existent settings, §3 claimed the quota counters use `merlins-rate-limits` | The RFC precedent from T7: correct in place, keep the good parts. A task doc that survives execution unamended teaches the next reader the wrong thing — and §3's wrong *reason* for "no new IAM" was the dangerous one, since it would send someone hunting for counter rows in a table that never gets written. §3's conclusion survived; its reasoning did not |
| 2026-08-09 | T8 | **No RED phase, stated rather than faked.** T8 changes prose, comments and a `.env` template — no behaviour — so nothing could fail first. The three tests added to `test_config.py` are **documentation guards for behaviour that already shipped** in T6/T7 and passed on their first run, by design | CLAUDE.md's gate binds behavioural change. Inventing a failing test for a docstring would have produced a fake RED and a test that asserts prose. The guards earn their place differently: four separate docs now print "100 credits = 50 lookups", so a default changed in code without them makes all four quietly wrong |
| 2026-08-09 | T8 | `deploy/backend-container.json` was left **without** a `secrets` block; the block to paste lives in `docs/aws-setup.md` Phase 8 instead | A placeholder ARN in a file that gets applied verbatim makes the ECS task **fail to start** until the secret exists — a worse failure than the one it prevents, and a docs task has no access to mint the real ARN. The tradeoff is recorded as a follow-up: regenerating the task def from that file silently drops the key, and the run still exits `0` |
| 2026-08-09 | T-FINAL | **Fixed the `/admin/slabs` priced-filter bug rather than logging it**, under a full RED gate: two failing tests written first, the failing output shown to the owner, GREEN only after explicit confirmation. The owner chose the **call-site** fix over widening `useAdminApi.get`'s signature | It is a real user-visible defect on a documented worklist, and it **broke `next build`**, so the branch could not deploy with it — logging it would have handed over a branch that does not build. The call-site fix is isolated: `/admin/slabs` was the only wrapper-form caller in the codebase, so changing the shared helper would have put every admin page in the blast radius to fix one line. The deeper trap (the helper accepts the wrong shape silently) is [`follow-ups.md`](follow-ups.md) T-FINAL row 1 |
| 2026-08-09 | T-FINAL | **Corrected two things in `t-final-verification.md` itself** — its self-matching secret-leak command (now excludes `docs/plans/` and adds T8's value-shaped grep) and its §6 smoke checklist, which still told the owner to look for "PSA-verified identity" and to "scan with the camera" | Same precedent as T7's RFC amendment and T8's banner: a task doc that survives execution unamended teaches the next reader the wrong thing. The leak fix was explicitly assigned to T-FINAL by [`follow-ups.md`](follow-ups.md) T0 (each doc owns its own commands). The checklist mattered more: it is the one artifact handed to a human, and three of its rows described a flow that does not exist, so the owner would have "failed" a smoke test of features nobody built |
| 2026-08-09 | T7 | Three test files got a `monkeypatch.setattr(settings, "pokemonpricetracker_api_key", "")` guard | `Settings.model_config` uses `env_file=".env"`, which resolves against the **CWD** — so the same test run from `backend/` rather than the repo root would load the REAL key, and the "unconfigured key" tests would make live, billed vendor calls. Forced empty, not assumed empty |


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

## FINAL measurement (T-FINAL, 2026-08-09) — the number to regress against

The whole system exercised together for the first time. **Everything below is
green.** A later reader comparing against this can tell a regression from a
pre-existing failure:

| Suite | Baseline (2026-08-07) | **Final (2026-08-09)** | Delta |
|---|---|---|---|
| Backend | 1369 → 1407 after T1, ~2m21s | **1502 passed, 0 failed, 2m13s** | +95 from T6/T7/T8 |
| Frontend | 545 / 73 files, ~31s | **575 passed, 78 files, 28s** | +30 = T4's 20, T6's 8, T-FINAL's 2 |
| MCP | 98 / 7 files, ~1s | **98 passed, 7 files, 1.0s** | unchanged |
| `ruff check backend/src` | pre-existing findings | **All checks passed** | clean |
| `npm run lint --workspace=frontend` | pre-existing findings | **clean, exit 0** | clean |
| `npm run build --workspace=frontend` | not previously run | **exit 0** | see below |

- **The two `test_auth.py` failures did not reproduce**, consistent with T1's
  re-measurement. Treat the original "two known failures" line as stale.
- Backend runtime **2m13s**, so the session-scoped `mock_aws()` is intact — a
  per-test `mock_aws()` regression would show as ~10 minutes.
- **`next build` earned its place in the checklist.** It caught a type error that
  all 573 frontend tests missed, because **vitest does not typecheck**. The
  `/admin/slabs` page passed `{ params: {…} }` to `api.get`, whose second argument
  IS the params record, so the query came out as `?params=[object Object]` and the
  unpriced worklist silently returned every slab. Fixed under the RED gate.
  **Never skip step 3.**
- Lint outside the named paths is unchanged and NOT ours: `backend/scripts` and
  `backend/tests` still carry pre-existing `I001`/`E501` findings, including
  `scripts/daily_sync.py`'s `I001`. The named path is `backend/src`, which is clean.
- Both vitest suites fail spuriously if invoked as `npx vitest` ("Vitest failed to
  find the runner", or vitest 4.1.9 resolving over the workspace's 3.2.6). **Use the
  documented `npm test --workspace=…` form**; the failure is the invocation, not the
  code.

Use `./.venv/Scripts/python.exe`, never bare `python` — the bare form resolves to an
unrelated venv with no pytest. If results look impossible, this checkout is a git
worktree and a global editable install can shadow it with the sibling repo's
backend; verify which package loaded before debugging anything else (CLAUDE.md).
