# RFC 0009 — Task Plan Index

Execution plan for [RFC 0009](../../rfcs/0009-slab-intake-and-graded-pricing.md).
Each task below is a **self-contained document** — hand exactly one to a fresh
conversation and it has everything it needs without re-reading the RFC.

**Branch:** all tasks land on `Polishing-For-Deployment` (one branch, many commits).

**Progress:** update [`progress.md`](progress.md) at the end of every task. That
file is the first thing a new conversation should read.

**Test discipline (owner decision, carried over from RFC 0008):** do NOT run the
full suite per task. Each task doc names the *narrow* test selection to run while
working. The full suite runs once, at the end, via T-FINAL.

**TDD gate (CLAUDE.md, binding):** each doc has an explicit RED section. Write those
tests, show the owner the failing output, **wait for confirmation**, then go GREEN.
Never combine phases.

**Out-of-scope findings:** append to [`follow-ups.md`](follow-ups.md). Do not fix
them as a side errand.

## How to start a task conversation

Paste this, filling in the task id:

> Read `docs/plans/rfc-0009/progress.md` and `docs/plans/rfc-0009/<task-file>.md`.
> Execute that task only, following the RED gate. Do not start any other task.

## Vertical slicing

Tasks are sliced so that **T4 is a usable product**: after T0–T4 you can scan a
stack of slabs and have them become real, costed inventory. Everything after T4
adds pricing and polish to a working feature rather than completing a half-built one.

If you run out of appetite, the natural cut lines are **after T4** (intake works,
prices are manual) or **after T7** (intake + automated pricing; only docs remain).

## Tasks

| # | Doc | Scope | Layer | Depends on |
|---|---|---|---|---|
| T0 | [t0-provider-spike.md](t0-provider-spike.md) | Verify both APIs against real data; record fixtures; **coverage gate** | spike | — |
| T1 | [t1-slab-model-and-cert-index.md](t1-slab-model-and-cert-index.md) | Slab fields + `CERT#` pointer row + duplicate-check endpoint | backend | — |
| T2 | [t2-psa-lookup-and-quota.md](t2-psa-lookup-and-quota.md) | PSA client behind a Protocol, outbound quota guard, `/lookup/{cert}` | backend | T0, T1 |
| T3 | [t3-buy-session-graded.md](t3-buy-session-graded.md) | Buy session creates graded items — fixes the `kind: "raw"` hardcode | backend | T1 |
| T4 | [t4-slabs-tab-scan-to-commit.md](t4-slabs-tab-scan-to-commit.md) | **The tab.** Wedge scanner **and hand-typed certs** → staging table → commit. End-to-end usable | frontend | T2, T3 |
| T5 | [t5-camera-scan.md](t5-camera-scan.md) | Camera barcode fallback — a third input into the same pipeline | frontend | T4 |
| T6 | [t6-pricing-provider-and-slab-list.md](t6-pricing-provider-and-slab-list.md) | Pricing client + `graded_price` writes + slab list with values | full-stack | T0, T4 |
| T7 | [t7-nightly-sync-and-refresh-fix.md](t7-nightly-sync-and-refresh-fix.md) | Nightly refresh with stalest-first rotation; fixes the graded-skip bug | backend | T6 |
| T8 | [t8-docs-and-ops.md](t8-docs-and-ops.md) | CLAUDE.md corrections, `.env.example`, ECS secrets, README | docs/ops | T7 |
| T-FINAL | [t-final-verification.md](t-final-verification.md) | Full suite, lint, build, PR | verification | all |

## Owner decisions locked in during planning (2026-08-07)

| Question | Decision |
|---|---|
| Cert entry | **Three co-equal methods** — keyboard-wedge scanner and **hand-typed cert numbers** both in T4, camera in T5. One shared pipeline |
| What a scan creates | **A staged intake batch**, committed as a unit |
| Commit path | **Through the existing buy session** — accepted consequence: every scanned slab appears in purchase history and show analytics as a buy |
| Tab scope | **Intake + slab list + pricing controls** |
| Refresh cadence | **Nightly**, joined to `daily_sync.py` |
| Pricing vendor | **PokemonPriceTracker free tier.** PriceCharting rejected — owner declined to pay for what is only an estimate |
| Population data | **Dropped.** Not a preference — PSA's public API always returns `null` for it |

## The two facts that shape everything

1. **The slab price storage layer already exists and is unused.**
   `CARD#<id>` / `GRADEDPRICE#<company>#<grade>` rows, with getters, setters and a
   nightly history snapshot, all currently fed by hand. **No pricing schema change
   is needed** — T6/T7 fill existing rows from an API.

2. **`confirm_buy_session` hardcodes `"kind": "raw"`**
   (`routers/admin/purchases.py:243`). Until T3, no code path in this application
   can create a graded inventory item.

## Do not

- Do not run `npm test` or the full pytest suite inside a task conversation.
- Do not combine RED and GREEN phases (CLAUDE.md).
- Do not use bare `python` — always `./.venv/Scripts/python.exe` (CLAUDE.md).
- Do not commit either API key, or any file containing one. `.env` only.
- Do not add a `population` field. PSA's public API always returns `null` for it.
- Do not build a parallel slab-intake router that duplicates purchase transactions.
  Extend the buy session (T3).
- Do not write a grade-multiplier price estimate off the raw catalog price. It was
  explicitly rejected; see RFC §11.
- Do not put a scan on a request path. Duplicate cert checks go through the `CERT#`
  pointer row (T1).
- Do not write a bare `float` to DynamoDB — `_serialize` coerces, but only where it
  is applied. Prices arrive from the frontend as JSON **numbers** (CLAUDE.md Ops).
- Do not hand-pick a card-art size. Use `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN`.
- Do not let the pricing provider write `card_id`, `display_name_override`, or any
  identity field. It supplies **values only**.
- Do not make PSA calls from the nightly sync. There is nothing to refresh.
- Do not let a provider failure return a 5xx to the admin UI. Degrade to manual.
