# RFC 0021: Catalog Hygiene & Scheduled Price Sync

**Status:** Draft — written 2026-09-02, adversarially reviewed the same day
(see "Adversarial review findings"). No code written yet.
**Author:** Claude (planning session), owner-directed
**Round:** 9 — see [`docs/plans/round9/README.md`](../plans/round9/README.md)
**Owner tasks covered:** "PokemonTCG Player cards showing up in the catalog need
to be removed"; "daily price refreshes are not happening (both catalog and
inventory) — I think they need to be deployed on AWS to keep them running."

## Summary

Two problems with one root theme: **the catalog data pipeline is not doing its
job.** Junk rows got in and nothing takes them out, and the nightly job that
keeps prices current has not run since the serverless migration because the
infrastructure that invoked it was deleted along with ECS.

This RFC does three things:

1. **Stops the junk at the door.** TCGdex now carries Pokémon TCG Pocket — a
   digital-only game — under series `tcgp`. `seed_catalog` and `sync_new_sets`
   both enumerate `/{lang}/sets` with no series filter, so all 15 TCG Pocket sets
   were ingested as if they were physical cards. Both entry points gain a shared
   exclusion.
2. **Takes the junk out.** A new `scripts/purge_catalog_junk.py` removes TCG
   Pocket rows and legacy pokemontcg.io-era rows, on the repo's standard dry-run
   rail, with the chunked-progress shape a 31,000-row walk requires.
3. **Puts the sync back on a schedule.** A new, deliberately independent
   `MerlinsSyncStack` runs the *existing* `scripts/scheduled_sync.py` on
   EventBridge Scheduler → ECS Fargate RunTask.

Nothing in this RFC touches the frontend.

## Motivation

### The junk

`_sync_new_sets` and `seed_catalog.seed_language` both call
`client.list_sets(language)` → `GET /{lang}/sets` and walk every set they get
back. That endpoint returns **218 sets for `en`** and its rows look like
`{"id": "A1", "name": "Genetic Apex", "cardCount": {...}}` — there is **no
`serie` field on the brief listing at all** (verified live 2026-09-02). So there
has never been anything for the walk to filter on, and when TCGdex added the
`tcgp` series the sets simply appeared in the list and got seeded.

TCG Pocket cards are digital game assets. They are not physical inventory, they
have no TCGplayer or Cardmarket pricing, and they pollute every catalog
autocomplete an operator uses at a buy table — which is the surface where a wrong
pick costs money.

The owner also reports **legacy rows** in the catalog. `parse_card_id`
(`services/tcgdex.py`) already names this exact cohort in its own docstring: a
"dead pokemontcg.io-era row (`"xy7-54"`)" — an id with no `<api_lang>:` prefix.
The repo has known about these for long enough to document them; nothing has ever
removed them.

### The sync

`backend/scripts/scheduled_sync.py` exists, is tested, and is correct. Its module
docstring says:

> Scheduled sync dispatcher: EventBridge Scheduler → ECS RunTask entry point.
> **Architecture decision (ECS over Lambda):** these jobs run inside the existing
> backend container image … A new-set catalog sync can exceed Lambda's hard
> 15-minute timeout.

**RFC 0014 migrated the backend off ECS to a Lambda Function URL and deleted the
ECS constructs.** Measured 2026-09-02: `grep -rln "ecs\|Fargate" infra/lib/`
returns **nothing**, and `infra/bin/infra.ts` instantiates exactly three stacks —
`MerlinsBackendStack`, `MerlinsFrontendStack`, `MerlinsCognitoBrandingStack`.
There is no schedule construct, no cluster, no task definition, and no rule
anywhere in `infra/`.

So the dispatcher has had no caller since that migration. Prices are stale
because nothing invokes the job, not because the job is broken. The whole of
`run_daily_sync`'s six steps — held-price depth pass, graded pricing, two history
snapshots, the inventory denormalization, and the weekly catalog cycle — has been
dark.

This also explains a symptom the owner did not connect to it: `CLAUDE.md` states
the weekly `refresh_catalog_prices` cycle is what fills catalog prices, "which is
why the rules above lead with the absent cases." Those absent cases have been
permanent since the migration.

## Owner decisions (recorded 2026-09-02)

1. **What to purge:** "I want to get rid of the Digital-Only Pokemon TCG Pocket
   sets as well as any legacy rows although there shouldn't even be any in the
   first place."
2. **How the purge is run:** Claude runs the **dry run** against live and reports
   counts plus sample rows. The owner approves before any `--execute`.
3. **Sync hosting:** EventBridge Scheduler → Fargate task, no idle cluster cost.
   Rejected: Step Functions + chunked Lambdas (restructures working sync code to
   fit a 15-minute ceiling that Fargate simply does not have); split
   nightly-Lambda/weekly-Fargate (two deployment paths to save pennies).
4. **Deploys:** Claude does not deploy. `cdk diff` / `cdk synth` and the exact
   commands are handed to the owner.

## Detailed Design

### 1. TCGdex series exclusion (`services/tcgdex.py`, `services/catalog_sync.py`)

**Two new client methods**, mirroring the existing `list_sets` shape:

```python
def list_series(self, language: Language) -> list[dict]:
    """All series for a language (bare array of ``{id, name, logo}``)."""
    return self._get(f"/{LANGUAGE_API_CODE[language]}/series") or []

def get_series(self, language: Language, series_id: str) -> dict | None:
    """One series in full, including its ``sets`` array; ``None`` on 404."""
```

`GET /{lang}/series/tcgp` returns the whole set list for the series in **one
call** — verified live, 15 sets for `en`. That is the cheap filter, and it is the
only cheap one available, because the brief `/sets` listing carries no series
field.

**One shared exclusion helper** in `services/catalog_sync.py`, called by both
ingest paths so the rule cannot drift:

```python
# Digital-only games TCGdex carries alongside the physical TCG. These are not
# inventory: they have no TCGplayer/Cardmarket pricing and no physical card
# exists to buy, sell or grade. Excluded at INGEST, so a purge never has to run
# twice.
EXCLUDED_SERIES = frozenset({"tcgp"})

# Fallback used only when the series endpoint is unreachable for a language.
# Verified against api.tcgdex.net/v2/en/series/tcgp on 2026-09-02.
TCG_POCKET_SET_IDS = frozenset({
    "P-A", "A1", "A1a", "A2", "A2a", "A2b", "A3", "A3a", "A3b",
    "A4", "A4a", "B1", "B1a", "B2", "B2a",
})

def excluded_set_ids(client, language) -> frozenset[str]:
    """TCGdex set ids that must never be ingested, for one language.

    Resolved once per language per run and cached by the caller — this is one
    HTTP call, not one per set.

    A failure here NEVER fails the sync and NEVER silently lets the sets
    through: it logs a warning and falls back to ``TCG_POCKET_SET_IDS``. The
    literal can go stale as new TCG Pocket sets release, which is precisely why
    the live call is preferred; a stale literal ingests a handful of new junk
    rows the purge script can remove, whereas propagating the error would take
    the whole nightly catalog job down over a cosmetic filter.
    """
```

**Call sites**, both of which currently walk every set returned by `list_sets`:

- `catalog_sync._sync_new_sets` — skip an excluded set before the
  `repo.list_cards_by_set` emptiness check, so an excluded set is never walked
  and never counted in `new_sets`.
- `scripts/seed_catalog.seed_language` — same skip, and report the count as
  `sets_skipped_digital` in the summary rather than silently.

**The comparison is on the raw TCGdex set id** (`"A1"`), not the composite
`"en:A1"`. `excluded_set_ids` returns raw ids because that is what
`client.list_sets` yields; converting at the boundary once is clearer than
converting inside the helper.

**Tests** (`backend/tests/services/test_catalog_sync.py`,
`backend/tests/scripts/test_seed_catalog.py`):

- A stub client whose `list_sets` includes `A1` and whose `get_series("tcgp")`
  returns it: `sync_new_sets` writes **zero** cards for that set and never calls
  `iter_brief_cards` for it.
- A stub whose `get_series` raises `TcgdexError`: the run still completes, `A1`
  is still skipped (via the literal), and a warning is logged.
- A stub returning a series id the code does not know: no effect, no crash.
- **A regression test that a physical set is still ingested** — the exclusion
  must not become a wildcard.

### 2. `scripts/purge_catalog_junk.py`

Standard rails, matching `seed_catalog.py` (the closest sibling — a destructive
full-table walk, not the additive `backfill_catalog_sets.py` rail):

- **Dry run by default.** `--execute --confirm-table merlins-cards` to write.
- **Chunked progress printed between chunks** — mandatory. CLAUDE.md records
  `backfill_price_history_ttl.py` running 90 minutes in silence against ~70,000
  rows and being indistinguishable from a hang. This script walks 31,603+ catalog
  rows and their price children. Copy `reprice_catalog.py`'s shape:
  `chunk N/M: done/total, ETA`.
- Uses `backend/.venv/bin/python`, no shebang (repo convention).

**Two predicates, evaluated per catalog row:**

| Kind | Predicate | Why it is safe |
|---|---|---|
| Digital-only | `parse_card_id(card_id)` yields `(lang, tcgdex_id)` **and** the set id embedded in `tcgdex_id` is in the language's `excluded_set_ids` | Same authority the ingest filter uses. One code path, two callers. |
| Legacy | `parse_card_id(card_id) is None` | Already the repo's own definition of a dead row: "a dead pokemontcg.io-era row (`"xy7-54"`), or a language code this build does not speak." |

**The legacy predicate has a live-fire hazard and the script must handle it.**
`parse_card_id` returns `None` for *two* different reasons, and only one of them
is junk. The second — "a language code this build does not speak" — will start
matching real rows the moment RFC 0023 adds 16 new languages, and would match
them *right now* if anyone had seeded a `ko:` row by hand. So the script splits
the two:

```
no ":" separator at all            -> LEGACY, purgeable
":" present, language unknown      -> REPORTED, never purged, listed by language code
```

**In-use guard, and it is the important one.** A catalog row an inventory item
points at must never be deleted: `card_id` is the join key for pricing, images
and identity, and removing the row silently unprices a card the business owns and
strands it with a dangling reference. The script therefore:

1. Builds the set of `card_id`s referenced by **any** inventory item (one
   `repo.list_inventory()` walk, held in memory — the inventory is thousands of
   rows, not millions).
2. Any purge candidate in that set is **skipped and reported** under
   `in_use_skipped`, with its item ids, as a manual triage list for the owner.
3. Everything else is deleted.

**What a delete removes.** A catalog card is a `CARD#<card_id>` partition with
child rows: the card itself, `PRICE#RAW#…` / `PRICE#GRADED#…` history points, and
`GRADEDPRICE#…` bands. Deleting only the card row leaves orphaned price history
that nothing can ever read. So a purge deletes **the whole `CARD#<card_id>`
partition** — query the partition, batch-delete every SK. The script reports
`cards_deleted` and `child_rows_deleted` separately.

`catalog_set` registry rows are deleted too, so the Set filter on
`/admin/inventory` stops offering "Genetic Apex" — but **only for a set whose
cards were ALL actually deleted.**

> If even one card in a set was held back by the in-use guard, that set still has
> catalog rows, and deregistering it would leave a set with cards and no registry
> entry — invisible to the Set filter while still matching search. Deregistration
> is therefore conditional on `deleted == candidates` for that set, and a set with
> survivors is listed under `sets_kept_partial` in the summary so the owner knows
> the purge is not finished for it.

`backfill_catalog_sets.py` is the re-derivation if a count ever looks wrong.

**Cache invalidation.** `services/catalog_cache.invalidate()` is process-local and
the script is a separate process, so it does nothing for the running Lambda. The
script prints a one-line reminder that the live catalog cache holds the old rows
until its TTL expires. Do not add a cache-busting endpoint for this — it is a
one-time script.

**Summary JSON**, printed at the end and on `--execute`:

```
{"scanned": N, "digital_candidates": N, "legacy_candidates": N,
 "unknown_language_reported": N, "in_use_skipped": N,
 "cards_deleted": N, "child_rows_deleted": N,
 "sets_deregistered": N, "sets_kept_partial": [...],
 "dry_run": true}
```

**Tests** (`backend/tests/scripts/test_purge_catalog_junk.py`), all against moto:

- A TCG Pocket card is a candidate; a physical card is not.
- A `"xy7-54"` row is a legacy candidate; an `"en:base1-4"` row is not.
- A `"ko:xy7-54"`-shaped row with an unknown language is **reported, not deleted**.
- A candidate referenced by an inventory item is skipped and reported.
- Dry run writes nothing at all (assert the table is byte-identical after).
- `--execute` without `--confirm-table` refuses.
- The whole `CARD#` partition goes, price children included.
- **A set with one in-use survivor is NOT deregistered** and appears in
  `sets_kept_partial`; a set purged completely IS deregistered.
- Business master data (shows, consignors, transactions, inventory) is untouched —
  reuse `test_catalog_wipe.py`'s existing assertions as the model.

### 3. `MerlinsSyncStack` (`infra/lib/sync-stack.ts`)

**A fourth, deliberately independent stack.** Same reasoning CLAUDE.md already
records for `MerlinsCognitoBrandingStack`: this stack shares no resource with
`MerlinsFrontendStack` or `MerlinsBackendStack`, so a scheduling change is
structurally incapable of touching either Lambda's environment map and cannot
trigger the partial-env-export secret wipe.

It does **not** import anything from the backend stack. The DynamoDB table name
arrives as a plain string prop from `infra/bin/infra.ts`, exactly as the other
stacks receive theirs — importing a backend export would pull
`MerlinsBackendStack` into every `cdk deploy MerlinsSyncStack`, which is the
second, independent route to the same wipe that CLAUDE.md documents.

**Resources:**

| Resource | Notes |
|---|---|
| `ec2.Vpc.fromLookup({ isDefault: true })` | No new VPC, no NAT gateway. |
| `ecs.Cluster` | No capacity providers, no EC2. A Fargate-only cluster costs **nothing** when idle. |
| `ecs.FargateTaskDefinition` | 1 vCPU / 2048 MiB. The catalog walk is network-bound, not CPU-bound. |
| `ecs.ContainerImage.fromAsset('..', { file: 'backend/Dockerfile', target: 'runtime' })` | **`runtime`, NOT `lambda`.** See the warning below. |
| `logs.LogGroup` | `retention: ONE_MONTH`. The job's only output is one structured JSON line per run and that is the whole observability story. |
| `scheduler.CfnSchedule` ×2 | `prices` and `catalog`. |
| `sqs.Queue` | Dead-letter target for both schedules. |
| Task role policy | `dynamodb:Query`, `GetItem`, `PutItem`, `UpdateItem`, `BatchWriteItem`, **`Scan`** on `table/merlins-cards`. |

> **The `--target lambda` trap runs in reverse here, and it is easy to get
> wrong.** CLAUDE.md warns that a manual `docker build` of the backend image
> silently lands on `runtime` when `lambda` was wanted. **This stack wants the
> opposite.** These are ECS Fargate tasks with no Lambda runtime API to talk to;
> the `lambda` stage's Web Adapter extension is dead weight at best. `target:
> 'runtime'` is correct here and `infra/test/sync-stack.test.ts` pins it, with a
> comment saying why, so nobody "fixes" it to match `backend-stack.ts`.

**`dynamodb:Scan` is required and is not an oversight.** The catalog cache and
`_scan_catalog` are on the sync path (CLAUDE.md records a live HTTP 500 from
exactly this grant being missing on the ECS task role). `deploy/backend-task-role-permissions.json`
is the existing source of truth for the shape; this stack's inline policy mirrors
it. Any new action the sync needs goes in **both** places or they drift.

**Networking:** `assignPublicIp: true` in public subnets. The job must reach
`api.tcgdex.net` and `pokemonpricetracker.com` over the internet, and a NAT
gateway costs ~$32/month to avoid a public IP on a task that runs twice a month.

**Schedules** (`scheduler.CfnSchedule`, `EcsRunTask` target, `flexibleTimeWindow:
OFF`):

| Schedule | Expression | Job | Why |
|---|---|---|---|
| `merlins-sync-prices` | `cron(0 9 * * ? *)` — 09:00 UTC = 01:00/02:00 Pacific | `--job prices` | `run_daily_sync`. Overnight in the business's own timezone; the weekly catalog cycle inside it is the long tail. |
| `merlins-sync-catalog` | `cron(0 15 2 * ? *)` — 15:00 UTC on the 2nd | `--job catalog` | `sync_new_sets`. New sets release monthly at most; CLAUDE.md already describes this as "a button or a monthly schedule". **A different day and hour from the nightly job on purpose** — the nightly `prices` job carries the ~24-minute weekly catalog cycle, and two concurrent catalog writers is not a state either job was designed for. A lock would be the general fix; six hours of separation on a job that runs twice a month is the proportionate one. |

The container command is
`["python", "-m", "scripts.scheduled_sync", "--job", "prices"]` — overridden per
schedule via the target's `containerOverrides`. The task definition itself carries
no command, so neither schedule inherits the other's job by accident.

**Environment variables on the task definition:**
`DYNAMODB_TABLE_NAME`, `AWS_REGION`, `POKEMONPRICETRACKER_API_KEY`,
`PRICING_DAILY_QUOTA`.

> **This stack has its own environment map and therefore its own partial-export
> hazard.** `POKEMONPRICETRACKER_API_KEY` is read from the deployer's shell at
> synth time, the same way every other secret in this repo is. A `cdk deploy
> MerlinsSyncStack` without it exported writes an **empty** key, and
> `build_pricing_provider()` returns `None`, and the nightly job silently stops
> pricing slabs while reporting success on every other step. The deploy script
> below closes that mechanically; do not deploy this stack by hand.
> **Always pass `--exclusively`.**

**`scripts/deploy-sync.sh`**, modelled on `scripts/deploy-frontend.sh`:

1. Read the current live `POKEMONPRICETRACKER_API_KEY` off the deployed backend
   Lambda via command substitution (never printed) and re-export it, so a deploy
   can only preserve what already exists. An explicit export in the operator's
   own shell still wins, so rotating the key works normally.
2. Refuse to run if the resolved key would be empty.
3. `cdk diff MerlinsSyncStack --exclusively`, then
   `cdk deploy MerlinsSyncStack --exclusively`.
4. Afterwards, print the two schedule ARNs and the command to trigger a manual
   run.

**`infra/test/sync-stack.test.ts`** pins, via `Template.fromStack`:

- The image asset's `target` is `runtime` (the comment explains why it differs
  from `backend-stack.ts`).
- Both `AWS::Scheduler::Schedule` resources exist with the exact cron expressions.
- Each schedule's `containerOverrides` command ends with the right `--job` value,
  and the two differ.
- The task role policy contains `dynamodb:Scan`.
- The environment map contains all four keys.
- The stack has **no** `Fn::ImportValue` — proving it is genuinely independent and
  cannot drag another stack into a deploy.

### 4. Verifying the sync actually runs

A green `cdk deploy` proves nothing (CLAUDE.md's standing rule, learned the hard
way on the trailing-slash outage). `scripts/verify-sync.sh`:

- `aws scheduler list-schedules` — both schedules exist and are `ENABLED`.
- `aws ecs list-tasks` / `describe-tasks` for the most recent run.
- `aws logs tail` the log group for the last structured JSON summary line and
  assert it parses and reports `"status": "ok"`.
- One-shot manual invocation command printed for the operator, so the first run
  does not have to wait for 09:00 UTC.

## API Contracts

None. No HTTP surface changes in this RFC.

## Alternatives Considered

**Filter TCG Pocket by set-id prefix (`A*`, `B*`, `P-A`) instead of by series.**
Cheaper — no extra HTTP call — and wrong: `A`/`B` prefixes are not reserved, and a
future physical set could collide. The series id is the actual fact; the id list
is kept only as an offline fallback.

**Purge by re-seeding the catalog from scratch.** `seed_catalog.py` with the new
exclusion would eventually produce a clean catalog, but it does not *delete*
anything — the junk rows would simply survive as unrefreshed rows, and a full
reseed whole-item `put_item`s 31,603 rows for a problem affecting a few hundred.

**Step Functions + chunked Lambdas.** Rejected by the owner. It would require
restructuring `refresh_catalog_prices`'s ~24-minute walk into resumable chunks
purely to fit a ceiling Fargate does not have, on code that is currently correct
and tested.

**Reviving the ECS constructs inside `MerlinsBackendStack`.** Rejected: it would
put a schedule change on the same deploy path as the backend Lambda's environment
map, which is exactly the blast radius `MerlinsCognitoBrandingStack` exists to
demonstrate avoiding.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **The purge deletes a catalog row an item needs.** | The in-use guard skips and reports rather than deletes. Dry run is the default and the owner approves the execute. |
| **The legacy predicate widens after RFC 0023 adds 16 languages.** | The script splits "no separator" (purge) from "unknown language" (report only). RFC 0023 is scheduled after this one, and the split makes the order not matter. |
| **`Vpc.fromLookup` needs a bootstrapped, account-specific context.** | It writes to `cdk.context.json`; the first `cdk synth` must run with real credentials. Documented in the task doc. If the account has no default VPC, the fallback is an explicit VPC id prop — flagged as the first thing to check. |
| **The nightly job fails silently forever.** | DLQ on both schedules, plus `verify-sync.sh`. A CloudWatch alarm on the DLQ depth is listed in follow-ups rather than built now — the DLQ itself is the durable record. |
| **The scheduled task uses the wrong Docker stage.** | Pinned by `sync-stack.test.ts` with an explanatory comment. |
| **A Fargate task's cold pull of a large image makes the job slow.** | Accepted. The job runs twice a month at 01:00 local; a two-minute image pull is invisible. |

## Adversarial review findings (2026-09-02)

Run inline before any implementation, per the owner's request. Findings folded
into the design above rather than tracked separately:

1. **Logic — the in-use guard was missing from the first draft.** Deleting a
   catalog row that inventory references would silently unprice owned stock and
   leave a dangling `card_id`, which no existing test would catch. Added as a
   hard requirement with its own test.
2. **Logic — `parse_card_id` returning `None` conflates two cohorts.** "No colon"
   is junk; "unknown language code" becomes a false positive the moment RFC 0023
   lands and is a false positive *today* for any hand-seeded row. Split into
   purge vs report.
3. **Chaos — the series lookup is a new network dependency on the nightly job's
   critical path.** A TCGdex outage on `/series/tcgp` must not take the whole
   price refresh down for a cosmetic filter. Resolved with the hardcoded fallback
   plus a warning log; the stale-literal failure mode is a few extra junk rows,
   which is strictly cheaper than a dark night.
4. **Security — the new stack re-introduces the partial-env-export wipe on a
   fourth surface.** `POKEMONPRICETRACKER_API_KEY` lives in this stack's
   environment map, and a hand-run `cdk deploy` without it exported empties it,
   degrading silently (`build_pricing_provider()` returns `None` and every other
   step still reports success). Resolved with `scripts/deploy-sync.sh` reading the
   live value, plus `--exclusively`, plus a refusal on empty.
5. **Bloat — the first draft added a CloudWatch alarm, an SNS topic and an email
   subscription.** Cut. The DLQ is the durable failure record and
   `verify-sync.sh` is the check; an alarm is a follow-up, not a launch
   requirement.
6. **Correctness — deleting only the `CARD#<id>` row orphans its `PRICE#` and
   `GRADEDPRICE#` children.** The purge deletes the whole partition.
7. **Logic — deregistering a `catalog_set` whose cards were not all deleted.**
   The in-use guard can hold a card back, leaving a set with surviving rows and no
   registry entry: invisible to the Set filter while still matching search.
   Deregistration is now conditional on a complete purge, with `sets_kept_partial`
   reported.
8. **Chaos — the two schedules can overlap on the 1st of the month.** The nightly
   `prices` job (09:00 UTC) carries the ~24-minute weekly catalog cycle, and the
   monthly `catalog` job fired at 11:00 UTC the same morning; both write catalog
   rows. Moved the catalog schedule to the **2nd at 15:00 UTC**, six hours clear of
   any plausible overrun. Cheaper than building a lock for a job that runs twice a
   month.

## Open Questions

None blocking. The dry-run report answers the only real unknown — how many rows
each predicate actually matches on the live table — and the owner sees it before
anything is deleted.
