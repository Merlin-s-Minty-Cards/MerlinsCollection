# RFC 0021 — Task Index

**RFC:** [`docs/rfcs/0021-catalog-hygiene-and-scheduled-sync.md`](../../rfcs/0021-catalog-hygiene-and-scheduled-sync.md)
**Round guide:** [`docs/plans/round9/README.md`](../round9/README.md) — read it first.
**Progress:** [`progress.md`](progress.md) · **Follow-ups:** [`follow-ups.md`](follow-ups.md)

Backend + infra only. No frontend files change in this RFC.

| Task | Title | Depends on | Suite to run |
|---|---|---|---|
| T1 | TCGdex series client methods | — | backend |
| T2 | Ingest exclusion in both catalog entry points | T1 | backend |
| T3 | `scripts/purge_catalog_junk.py` | T1, T2 | backend |
| T4 | Live dry run + owner report | T3 | none (read-only, live) |
| T5 | `MerlinsSyncStack` + deploy/verify scripts | — | infra |
| T6 | Docs + full-suite verification | T1–T5 | all |

**T5 is independent of T1–T4** and can be done first or in a separate session if
context is tight. T4 is the only task that touches live AWS and it is read-only.

---

## T1 — TCGdex series client methods

**Files:** `backend/src/merlins_collection/services/tcgdex.py`,
`backend/tests/services/test_tcgdex.py`

Add `list_series(language)` and `get_series(language, series_id)` beside the
existing `list_sets`, using the same `self._get` helper and the same
`LANGUAGE_API_CODE` lookup. `get_series` returns `None` on 404 and re-raises on
anything else — copy `get_card`'s exact shape, it is the precedent.

Verified live 2026-09-02:
- `GET /v2/en/series` → 21 rows, one of which is `{"id":"tcgp","name":"Pokémon TCG Pocket",…}`
- `GET /v2/en/series/tcgp` → the series with a `sets` array of 15 entries
- `GET /v2/en/sets` → 218 rows shaped `{"id","name","cardCount"}` — **no `serie` field**
- `GET /v2/en/sets/A1` → full detail, carries `"serie": {"id":"tcgp","name":"…"}`

**RED first.** Tests: a stubbed transport returns the series list → `list_series`
returns it; a 404 → `get_series` returns `None`; a 500 → `get_series` raises
`TcgdexError`.

**Done when:** both methods exist, tested, `ruff` clean.

---

## T2 — Ingest exclusion in both catalog entry points

**Files:** `backend/src/merlins_collection/services/catalog_sync.py`,
`backend/scripts/seed_catalog.py`, tests for both.

Add `EXCLUDED_SERIES`, `TCG_POCKET_SET_IDS` and `excluded_set_ids(client, language)`
to `catalog_sync.py` exactly as the RFC specifies, then call it from:

1. `_sync_new_sets` — resolve once at the top of the run (not per set), then skip
   an excluded set **before** the `repo.list_cards_by_set` emptiness check, so its
   cards are never walked and it never appears in `new_sets`. Report the count as
   `sets_skipped_digital`.
2. `seed_catalog.seed_language` — same skip, same summary key.

Compare on the **raw TCGdex set id** (`"A1"`), which is what `list_sets` yields.

**RED first.** Five tests, all with a stub client:
- A TCG Pocket set in `list_sets` is never walked and writes zero cards.
- A physical set is still ingested (the exclusion is not a wildcard).
- `get_series` raising `TcgdexError` → the run completes, the set is still
  skipped via the literal, and a warning is logged.
- An unknown series id in `EXCLUDED_SERIES` → no effect, no crash.
- `excluded_set_ids` makes **one** HTTP call per language, not one per set —
  assert the stub's call count.

**Done when:** both entry points skip, the fallback works, summaries report it.

---

## T3 — `scripts/purge_catalog_junk.py`

**Files:** `backend/scripts/purge_catalog_junk.py`,
`backend/tests/scripts/test_purge_catalog_junk.py`, and whatever repository method
the partition delete needs in `services/dynamodb.py`.

Read `backend/scripts/reprice_catalog.py` first — it is the shape to copy for the
chunked progress loop, and `backend/scripts/seed_catalog.py` for the
`--execute --confirm-table` rail. Read `backend/tests/services/test_catalog_wipe.py`
for the "business master data is untouched" assertion set.

**The three cohorts, and they are not interchangeable:**

| Cohort | Predicate | Action |
|---|---|---|
| Digital-only | `parse_card_id` succeeds **and** the embedded set id is in `excluded_set_ids` for that language | delete |
| Legacy | `card_id` has **no `:` separator at all** | delete |
| Unknown language | `card_id` has a `:` but the prefix is not a known API code | **report only, never delete** |

Do **not** collapse the last two into `parse_card_id(...) is None`. RFC 0023 adds
16 language codes and will turn that into a data-destroying false positive.

**In-use guard:** build the set of `card_id`s referenced by any inventory item
(one `repo.list_inventory()` walk), skip any candidate in it, and report those
with their item ids under `in_use_skipped`.

**Delete the whole `CARD#<card_id>` partition**, not just the card row — query the
partition and batch-delete every SK, so `PRICE#RAW#…`, `PRICE#GRADED#…` and
`GRADEDPRICE#…` children go with it. Count children separately.

Also deregister the `catalog_set` rows for purged sets.

Print a one-line reminder at the end that the running Lambda's in-process catalog
cache holds the old rows until its TTL expires. Do not build a cache-bust endpoint.

**Progress output is not optional.** This walks 31,603+ rows. Print
`chunk N/M: done/total, ETA` after every chunk. CLAUDE.md records a 90-minute
silent script that was indistinguishable from a hang.

**RED first.** Tests listed in the RFC's §2 — all eight, against moto.

**Done when:** dry run writes nothing (assert the table is unchanged),
`--execute` without `--confirm-table` refuses, and every cohort behaves as the
table says.

---

## T4 — Live dry run + owner report

**No code.** Run the dry run against the live table and report to the owner:

```bash
cd backend
.venv/bin/python scripts/purge_catalog_junk.py            # DRY RUN, default
```

Report: the summary JSON, plus **10 sample rows per cohort** (card_id, name,
set_name) so the owner can eyeball that nothing real is in the list, plus the
full `in_use_skipped` list if it is non-empty.

**Then stop and wait.** The owner approves before any `--execute`. This is an
owner-reserved decision and is not covered by "decide and record".

---

## T5 — `MerlinsSyncStack` + deploy/verify scripts

**Files:** `infra/lib/sync-stack.ts`, `infra/bin/infra.ts`,
`infra/test/sync-stack.test.ts`, `scripts/deploy-sync.sh`, `scripts/verify-sync.sh`

Build it exactly as the RFC's §3 specifies. The three things most likely to be got
wrong, in order:

1. **`target: 'runtime'` on the image asset, NOT `'lambda'`.** This is an ECS
   task. Put the explaining comment in both the stack and the test.
2. **No `Fn::ImportValue` anywhere.** The table name is a plain string prop from
   `infra/bin/infra.ts`. An import would drag `MerlinsBackendStack` into every
   deploy of this stack, which is the second route to the secret wipe CLAUDE.md
   documents.
3. **`dynamodb:Scan` on the task role.** The catalog cache path needs it;
   CLAUDE.md records a live HTTP 500 from exactly this grant being absent.

`Vpc.fromLookup({ isDefault: true })` needs real credentials on the first
`cdk synth` (it writes `cdk.context.json`). **Check the account actually has a
default VPC before writing the stack** — `aws ec2 describe-vpcs --filters
Name=isDefault,Values=true`. If it does not, take an explicit `vpcId` prop
instead and say so in `progress.md`.

**Do not deploy.** Produce `cdk synth -o /tmp/sync-synth` and `cdk diff
MerlinsSyncStack --exclusively`, read the emitted template to confirm the
`target` and the two cron expressions really made it through (CLAUDE.md's rule:
verify the synthesized template, never the source), and hand the owner the
commands.

**Done when:** `npm test --workspace=infra` is green, `cdk synth` succeeds, and
the emitted JSON has been read and matches.

---

## T6 — Docs + full-suite verification

- `CLAUDE.md`: the Ops section currently implies the sync runs. Add the sync stack
  and its two schedules; note the TCG Pocket exclusion beside the existing
  `sync_new_sets` paragraph (which warns that restoring its early-out "will look
  like an optimization and is the bug" — the new exclusion is a *different*
  filter and must not be confused with it).
- `docs/aws-setup.md`: the new stack, its deploy script, and the
  `POKEMONPRICETRACKER_API_KEY` hazard.
- `deploy/backend-task-role-permissions.json`: note that the sync stack's inline
  policy mirrors it and both must change together.
- Run every suite listed in the round guide.
