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

## ⚠️ Re-planned 2026-08-08 — manual-first intake

**The re-plan is COMPLETE: all 7 of its tasks are done, and T3 and T4 are `DONE`.**
Intake works end to end with no scanner, no camera and no PSA. **T6 is next.**

PSA's cert API is blocked at the account (403, no code-side fix), so T3 and T4 were
re-planned. **Their authority is now
[`docs/superpowers/plans/2026-08-08-slab-manual-entry.md`](../../superpowers/plans/2026-08-08-slab-manual-entry.md)**
(7 numbered tasks, one per conversation; its checkboxes are the live record), backed by
[the design spec](../../superpowers/specs/2026-08-08-slab-manual-entry-design.md).

`t3-*.md` and `t4-*.md` are **superseded and carry banners**. T4 no longer depends
on T2.

## How to start a task conversation

**For T3/T4 work**, use the numbered tasks in the manual-entry plan above — each
conversation ends by committing and emitting the prompt for the next one.

**For every other task**, paste this, filling in the task id:

> Read `docs/plans/rfc-0009/progress.md` and `docs/plans/rfc-0009/<task-file>.md`.
> Execute that task only, following the RED gate. Do not start any other task.

## Vertical slicing

Tasks are sliced so that **T4 is a usable product**: after T0–T4 you can take a
stack of slabs — typing each cert, or scanning it into the same field — and have
them become real, costed inventory. Everything after T4 adds pricing and polish to a
working feature rather than completing a half-built one. **This line is now past
tense: T4 landed 2026-08-08.**

If you run out of appetite, the natural cut lines are **after T4** (intake works,
prices are manual) or **after T7** (intake + automated pricing; only docs remain).

## Tasks

| # | Doc | Scope | Layer | Depends on |
|---|---|---|---|---|
| T0 | [t0-provider-spike.md](t0-provider-spike.md) | Verify both APIs against real data; record fixtures; **coverage gate** | spike | — |
| T1 | [t1-slab-model-and-cert-index.md](t1-slab-model-and-cert-index.md) | Slab fields + `CERT#` pointer row + duplicate-check endpoint | backend | — |
| T2 | [t2-psa-lookup-and-quota.md](t2-psa-lookup-and-quota.md) | **WON'T DO (2026-08-10)** — PSA's cert API became a **paid** feature and the owner declined it. Previously `DEFERRED` pending free-tier approval; **that approval is no longer being sought.** See RFC 0010 §H | backend | — (withdrawn) |
| T3 | ~~[t3-buy-session-graded.md](t3-buy-session-graded.md)~~ → **[manual-entry plan](../../superpowers/plans/2026-08-08-slab-manual-entry.md) Tasks 1–2** | **DONE** (`b9a9798`, `170eb09`) — buy session creates graded items; the `kind: "raw"` hardcode is gone | backend | T1 |
| T4 | ~~[t4-slabs-tab-scan-to-commit.md](t4-slabs-tab-scan-to-commit.md)~~ → **[manual-entry plan](../../superpowers/plans/2026-08-08-slab-manual-entry.md) Tasks 3–6** | **DONE** (`c5b5a00`, `164d3b0`, `cb0b59f`, `ec56727`) — **the milestone.** Manual entry with catalog autocomplete → staging table → commit | frontend | **T3 only** |
| T5 | [t5-camera-scan.md](t5-camera-scan.md) | **WON'T DO (2026-08-10)** — follows T2: a camera yields a cert number, and without PSA a cert number resolves to nothing. RFC 0010 T12 **removed** the disabled "Camera scan" button | frontend | — (withdrawn) |
| T6 | [t6-pricing-provider-and-slab-list.md](t6-pricing-provider-and-slab-list.md) | Pricing client + `graded_price` writes + slab list with values. **← the next task; both dependencies are now met** | full-stack | T0, T4 |
| T7 | [t7-nightly-sync-and-refresh-fix.md](t7-nightly-sync-and-refresh-fix.md) | Nightly refresh with stalest-first rotation; fixes the graded-skip bug | backend | T6 |
| T8 | [t8-docs-and-ops.md](t8-docs-and-ops.md) | CLAUDE.md corrections, `.env.example`, ECS secrets, README | docs/ops | T7 |
| T-FINAL | [t-final-verification.md](t-final-verification.md) | Full suite, lint, build, PR | verification | all |

## Owner decisions locked in during planning (2026-08-07)

| Question | Decision |
|---|---|
| Cert entry | ~~Three co-equal methods~~ → **TWO, and they are the same field** (2026-08-10). Keyboard-wedge scanner and hand-typed cert numbers, both in T4, through one `CertInput`; **the camera is WON'T DO** with T5. RFC 0010 T12 also removed the "Scan cert" button — a wedge scanner is a fast keyboard, so the ordinary field is the scan target |
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
- **Do not build anything on PSA, do not retry the cert endpoint, and do not email
  `collectors-apis@collectors.com`.** T2 and T5 are **WON'T DO** as of 2026-08-10 —
  the API is paid and the owner declined it. Do not add a `psa_api_key` setting.
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
