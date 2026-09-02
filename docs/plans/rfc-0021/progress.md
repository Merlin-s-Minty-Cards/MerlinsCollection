# RFC 0021 — Catalog Hygiene & Scheduled Price Sync: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.** That one is
gitignored, local-only, and rolling; nothing tracked may cite it.

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0021-catalog-hygiene-and-scheduled-sync.md`](../../rfcs/0021-catalog-hygiene-and-scheduled-sync.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 TCGdex series client methods | NOT STARTED |
| T2 Ingest exclusion | NOT STARTED |
| T3 Purge script | NOT STARTED |
| T4 Live dry run + owner report | NOT STARTED — **owner gate** |
| T5 `MerlinsSyncStack` | NOT STARTED |
| T6 Docs + verification | NOT STARTED |

## Next: T1

Nothing blocks it. T5 is equally unblocked and can run first if a session wants
the infra work while it has a clean context.

## Facts established during planning (do not re-derive these)

Verified live against `api.tcgdex.net/v2` on 2026-09-02:

- **TCG Pocket is series `tcgp`.** `GET /v2/en/series/tcgp` returns all 15 sets in
  one call: `P-A, A1, A1a, A2, A2a, A2b, A3, A3a, A3b, A4, A4a, B1, B1a, B2, B2a`.
- **The brief `/{lang}/sets` listing has NO `serie` field** — only
  `{id, name, cardCount}`. You cannot filter by series at listing time; you must
  fetch the series (one call) or the individual set.
- **TCGdex speaks 18 language codes**, enumerated by the API's own 404 validation
  body: `en, fr, es, es-mx, it, pt, pt-br, pt-pt, de, nl, pl, ru, ja, ko, zh-tw,
  id, th, zh-cn`. The docs site says 14 and is stale; trust the API.
  (RFC 0023 consumes this. Recorded here because this session measured it.)
- **"Deluxe Pack ex" is NOT a top-level `tcgp` set id** in the live `en` response,
  despite being a real TCG Pocket product. Unconfirmed whether it exists under
  another id. Immaterial — the code resolves the list live and only falls back to
  the literal on failure.

Verified in this repo on 2026-09-02:

- **`grep -rln "ecs\|Fargate" infra/lib/` returns nothing**, and
  `infra/bin/infra.ts` instantiates exactly three stacks. There is no schedule
  construct anywhere in `infra/`. This is the whole cause of the dark sync.
- **`scripts/scheduled_sync.py` is intact and correct** — it just has no caller.
  Its `--job prices|catalog` interface is what the new schedules target.
- **`parse_card_id` already names the legacy cohort** in its docstring and returns
  `None` for it. It returns `None` for unknown-language ids too, which is why T3
  must split the two.

## Decisions made autonomously (with the rejected alternative)

- **The exclusion is by series id, not by set-id prefix.** `A*`/`B*` prefixes are
  not reserved and a future physical set could collide. Rejected the cheaper
  prefix filter.
- **A series-lookup failure falls back to a hardcoded list rather than failing the
  run.** Rejected propagating the error: a TCGdex blip on a cosmetic filter would
  take the whole nightly price refresh down, and the stale-literal failure mode is
  a handful of junk rows the purge script already removes.
- **The purge deletes the whole `CARD#` partition.** Rejected deleting only the
  card row, which orphans price history nothing can ever read again.
- **The sync stack is a fourth independent stack with no `Fn::ImportValue`.**
  Rejected folding it into `MerlinsBackendStack`, which would put schedule changes
  on the same deploy path as the backend Lambda's environment map.
- **No CloudWatch alarm / SNS topic in v1.** The DLQ is the durable failure record
  and `verify-sync.sh` is the check. Listed in follow-ups.

## Owner gates on this RFC

1. **T4 → T3 `--execute`.** The owner reviews the dry-run report and approves
   before anything is deleted from the live table.
2. **All deploys.** Claude produces `cdk diff` / `cdk synth` and the commands;
   the owner runs them.
