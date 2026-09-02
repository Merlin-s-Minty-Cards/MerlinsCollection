# RFC 0021 — Follow-ups

Out-of-scope findings. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **CloudWatch alarm + SNS notification on the sync DLQ.** | The DLQ itself is the durable failure record and `verify-sync.sh` is the check. An alarm is a real improvement but not a launch requirement, and the first draft's alarm+topic+subscription was cut as bloat by the adversarial pass. |
| 2 | **A cache-bust endpoint so a purge takes effect immediately.** | `catalog_cache` is process-local; a one-time script cannot reach the running Lambda's copy. Building an admin endpoint for a script that runs once is cost without benefit — the TTL expires on its own. |
| 3 | **Excluding other non-physical TCGdex series.** | `tcgp` is the one the owner reported. `EXCLUDED_SERIES` is a frozenset precisely so adding another is a one-line change when one is identified. |
| 4 | **Backfilling `catalog_set` counts after the purge.** | `backfill_catalog_sets.py` already exists and is a harmless upsert. Run it manually after the purge rather than coupling the two scripts. |
| 5 | **Alerting when the sync's structured JSON reports partial failure** (e.g. graded pricing skipped for a missing key while every other step succeeded). | Needs a decision about what "unhealthy" means for a six-step job, which is a bigger question than this RFC. |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| | | |
