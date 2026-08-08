# RFC 0009 — Slab intake + graded pricing: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never
appear in `git status` or reach anyone else. It now carries a pointer block sending
readers here. Record all RFC 0009 status **in this file**.

**Last updated:** 2026-08-08 (**T0 DONE, split verdict** — pricing PROCEED, PSA STOP on
an account-entitlement 403. **T1 DONE** — `0b21de2`)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](../../rfcs/0009-slab-intake-and-graded-pricing.md)
**Task index:** [`README.md`](README.md)

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | Provider spike | **DONE (split verdict)** | `cd59ebc` | **Pricing = PROCEED, PSA = STOP.** All 19 cards priced, **including 3/3 Japanese** — coverage is better than feared. But PSA returns `403 "limited to approved customers"` on every call: the key is valid, **the account is not entitled**, and no code change fixes it. **T6 unblocked; T2 still blocked, now on PSA account approval rather than on this spike.** Also: auto-pricing off a name search picks the **wrong card ~1/3 of the time** — T6 must gate attachment on a verified match. Full evidence: [`spike-findings.md`](spike-findings.md) |
| T1 | Slab model + cert index | **DONE** | `0b21de2` | **Stale-pointer strategy: READER-SIDE verification** (`get_item_id_by_cert` re-reads the item and confirms it still claims the cert) — so T4 can trust `owned: true` **completely**; the residual risk is a rare false *negative*, first row of [`follow-ups.md`](follow-ups.md) T1. Endpoint is `GET /admin/slabs/certs/{cert}?company=PSA`, `200` either way |
| T2 | PSA lookup + quota guard | **BLOCKED (owner action)** | — | **No longer blocked on T0 — blocked on PSA approving the account.** Every call is `403 "limited to approved customers"`; the token and `Authorization: Bearer` format are both confirmed correct. Nothing about PSA's response shape is known, so the mapper cannot be written honestly. Add a **403 case** to the failure handling — RFC §9 has none |
| T3 | Buy session → graded | NOT STARTED | — | **unblocked — T1 is done.** Note `cert_number` is still an unbounded `str` on the model; T1 guarded only the read path, see follow-ups |
| T4 | Slabs tab (scan → commit) | NOT STARTED | — | blocked on T2, T3. **Milestone: usable product** |
| T5 | Camera scan fallback | NOT STARTED | — | blocked on T4. Droppable |
| T6 | Pricing provider + slab list | NOT STARTED | — | **T0 cleared it** — shape recorded as 19 fixtures, quota is self-reported, coverage proven. Still needs T4. Three binding notes: store `smartMarketPrice.price` **with its `confidence`**, pin `limit=1` (**cost is 2 x limit, billed even on zero hits**), and **auto-attach a price only on a verified `externalCatalogId` join** — a bare name search is wrong ~1/3 of the time |
| T7 | Nightly sync + refresh fix | NOT STARTED | — | blocked on T6 |
| T8 | Docs + ops | NOT STARTED | — | blocked on T7 |
| T-FINAL | Verification + PR | NOT STARTED | — | blocked on all |

Statuses: `NOT STARTED` → `RED (awaiting owner confirmation)` → `IN PROGRESS` → `DONE`,
plus `BLOCKED` for a task that was started and cannot finish without the owner.

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
| **Accept the PSA public-API EULA, then RE-ISSUE the token** | Every call returns `403 {"Message":"Access to this API is limited to approved customers."}`. The key is valid and `Authorization: Bearer` is confirmed correct — **this is an entitlement, not a bug, and no code change can work around it.** Step 1: sign in to the PSA account that owns the token and accept the EULA at **https://www.psacard.com/publicapi/accepteula** (the page 403s to anonymous fetches, so it needs a logged-in session). Step 2: **generate a fresh token afterwards and replace `PSA_API_KEY` in `backend/.env`** — the current one was issued before acceptance, and re-checked after the EULA link was supplied it still 403s, so acceptance alone does not appear to retro-enable an existing token. Fallback if it still fails: `collectors-apis@collectors.com`, the address PSA's own error body gives | **T2**, and the PSA half of T0 |
| Decide whether **T6 proceeds ahead of PSA** | Pricing is verified and unblocked, but without cert-verified identities an automatic price attach is wrong ~1/3 of the time. The proposed rule — auto-attach only on a verified `externalCatalogId` join, otherwise stage or Triage — needs an owner nod | T6 |
| *(optional)* more **Japanese** cert numbers | JP coverage measured 3/3, but on only 3 cards; T0 asked for at least 5 | confidence in T6 |
| Rotate both keys | Both were pasted into a chat transcript on 2026-08-07. Rotate once the integration is confirmed working | T8 |
| ~~`PSA_API_KEY` / `POKEMONPRICETRACKER_API_KEY` in `backend/.env`~~ | ~~Owner has the keys~~ — **done 2026-08-08** | — |
| ~~~20 real cert numbers off the shelf~~ | ~~Needed to measure coverage~~ — **19 supplied 2026-08-08** | — |

**When PSA approval lands, re-run the PSA half first** — it is the whole of
[`spike-findings.md`](spike-findings.md) §1.4 and costs 21 of the 100 daily calls:

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
| 2026-08-08 | T8 (early, at the owner's request) | **`backend/.env.example` now carries blank `PSA_API_KEY=` and `POKEMONPRICETRACKER_API_KEY=`.** Deliberately **without** the `PSA_DAILY_QUOTA` / `PRICING_DAILY_QUOTA` lines T8 §2 also lists, and the comments diverge from T8's draft text on two points: a graded lookup is budgeted at **2 credits, not 1**, and PSA's "no rate-limit headers" is qualified (a 429 does carry `Retry-After`, and is also what a bad token returns) | The two quota knobs are not fields on `Settings` yet — T2 and T6 add them — and `model_config` uses `extra="ignore"`, so documenting them now would advertise settings that silently do nothing. T8 still owns the rest of §2 (CLAUDE.md, ECS secrets, README); only the two key placeholders are done |
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
