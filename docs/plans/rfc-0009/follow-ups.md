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

*(no rows yet)*

| Finding | Why deferred | Impact if ignored |
|---|---|---|
