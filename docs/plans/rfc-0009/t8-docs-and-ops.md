# T8 — Documentation corrections and production wiring

**RFC:** 0009 §10 · **Layer:** docs/ops · **Depends on:** T7 · **Blocks:** T-FINAL

Small task, but it carries the two things that make the feature real in production
and it corrects documentation that is **actively wrong** today.

> **THIS DOC WAS ITSELF WRONG IN FIVE PLACES. Corrected in place while executing
> it, 2026-08-09 — the notes below are the authority over the prose under them.**
>
> 1. **§1: "PSA is called once per slab, ever" and "three co-equal input methods
>    including a camera" describe a flow that DOES NOT EXIST.** PSA has never been
>    called successfully (403, account not entitled); T2 is deferred whole and T5's
>    camera was never built. What shipped is manual-first intake — wedge scanner or
>    keyboard into one cert field — with pricing from PokemonPriceTracker under a
>    verified-join rule. §1's "the 100/day quota binds only on same-day intake" is
>    therefore about a quota nothing spends.
> 2. **§2: "1 credit per card" is wrong and so is the 100-lookup implication.** A
>    lookup costs **2 credits** (`costPerCard: 2`, measured live), so the free tier
>    is **FIFTY** lookups a day — and you are billed on `limit` even when the
>    search matches **zero** cards.
> 3. **§2: `PSA_DAILY_QUOTA` is not a `Settings` field, and neither is
>    `PSA_API_KEY`.** `model_config` uses `extra="ignore"`, so documenting either as
>    a working knob advertises a setting that silently does nothing. Only
>    `PRICING_DAILY_QUOTA` exists. `PSA_API_KEY` stays in `.env.example` as an
>    explicitly-labelled inert placeholder (owner's request, 2026-08-08).
> 4. **§2: PSA does not return "NO rate-limit headers" full stop.** No
>    `X-RateLimit-*`, but a 429 **does** carry `Retry-After` (observed 833 → 797 s,
>    a ~13-minute rolling window despite the body saying "per Day"), and a 429 is
>    also what an unrecognized token returns. `backend/.env.example` already
>    carried a corrected version of this comment before T8 ran — read what is there
>    before overwriting it.
> 5. **§3: the quota counters do NOT reuse `merlins-rate-limits`.** They are purely
>    in-process and in-memory (`services/slab/quota.py`) and touch no table at all.
>    §3's *conclusion* is still right — the **task role** needs nothing new — but
>    for a different reason, and the **execution role** does need
>    `secretsmanager:GetSecretValue` to inject the key. See `docs/aws-setup.md`
>    Phase 8.
>
> Also corrected: §2's leak grep matches its own text (see the last row of
> [`follow-ups.md`](follow-ups.md) T0). The command below now excludes
> `docs/plans/`. **T-FINAL's copy of the same command is still uncorrected** — that
> doc owns its own commands.

## 1. Correct CLAUDE.md

The "Third-Party APIs (Planned)" section contains three errors, all recorded in
[`follow-ups.md`](follow-ups.md):

| Wrong today | Correct to |
|---|---|
| The PSA cert API supplies **population** data | It does not. `TotalPopulation` and `PopulationHigher` are **always `null`** on the public API. Population is website-only |
| **PriceCharting** is the graded price source | Owner declined a paid subscription on 2026-08-07. The source is **PokemonPriceTracker's free tier** (100 credits/day, PSA 8/9/10 from eBay sold listings) |
| "see claude-progress.md Phase 4, PAUSED" | That file was replaced by the admin-enhancements rounds and has no Phase 4. Point at `docs/rfcs/0009-...` instead |

Rewrite the section to describe what was **built**, not what was planned — the
feature exists now. It should state:

- PSA is called **once per slab, ever** (identity is immutable), so the nightly sync
  makes zero PSA calls and the 100/day quota binds only on same-day intake.
- Slab prices live in the **pre-existing** `GRADEDPRICE#<company>#<grade>` rows —
  no new pricing schema.
- **Non-PSA slabs (CGC/BGS/SGC) remain manual by design.** Keep this; it is still
  true and still deliberate.
- Cert entry has **three co-equal input methods** (wedge scanner, hand-typed, camera).

Also add `/admin/slabs` to the **Admin Panel** route table and note its position in
the sidebar (after Buy).

## 2. `.env.example`

Add **blank** placeholders with a comment naming the quota, matching the existing
commenting style in that file (it explains *why*, not just *what*):

```bash
# --- Slab intake (RFC 0009) ---
# PSA cert verification. Free tier: 100 calls/day, HTTP 429 over it, and the API
# returns NO rate-limit headers — services/slab/quota.py counts our own calls.
# Called once per slab ever (a cert's identity is immutable), so the nightly sync
# spends none of this. Bearer token; does not expire.
PSA_API_KEY=
PSA_DAILY_QUOTA=100
# Per-grade slab values (PSA 8/9/10, from eBay sold listings).
# Free tier: 100 credits/day, 60 req/min, 1 credit per card.
POKEMONPRICETRACKER_API_KEY=
PRICING_DAILY_QUOTA=100
```

**Verify `backend/.env` is gitignored and that no key appears anywhere in the repo**
before committing:

```bash
# `docs/plans/` is excluded because three docs in it QUOTE this pattern — this
# doc, t-final-verification.md and follow-ups.md. Without the exclusion the
# check reports itself and trains you to wave it through.
git ls-files | grep -v "^docs/plans/" | xargs grep -l "pokeprice_\|^PSA_API_KEY=." 2>/dev/null

# Value-shaped scan, which no doc's prose can trip: an actual token after the `=`.
git ls-files | grep -v "^docs/plans/" \
  | xargs grep -nE "(PSA_API_KEY|POKEMONPRICETRACKER_API_KEY)[=:][\"' ]*[A-Za-z0-9_-]{8,}" 2>/dev/null

git check-ignore -v backend/.env   # must print a .gitignore hit
```

Expect no output from the two greps. If anything matches, stop and fix it before
committing. **Both were clean on 2026-08-09**; the only matches for the
unfiltered form were the three docs listed above.

## 3. Production secrets

The backend runs on ECS. Both keys must be injected as **secrets**, not environment
literals in a task definition.

- Add both to the deployment docs alongside the existing configuration.
- Note in `docs/aws-setup.md` that these are the first **outbound** third-party
  credentials the service holds — the ECS task role work in CLAUDE.md's Ops section
  concerns AWS permissions and is unrelated; no IAM change is needed for these.
- **No new IAM permissions are required by this RFC.** The quota counters reuse the
  existing `merlins-rate-limits` table, which the task role can already write.
  If a task claims otherwise, re-check before granting anything.

## 4. Rotate the keys

Both keys were pasted into a chat transcript on 2026-08-07 during planning. Once the
integration is confirmed working end to end, **rotate both** in their respective
portals and update `.env` and the ECS secrets.

Flag this to the owner explicitly in your report. It is the kind of item that is easy
to nod at and never do.

## 5. Backend README

`backend/README.md` documents endpoints. Add the `/admin/slabs` routes from
T1/T2/T6/T7, matching the existing format.

## Verification

No new tests — this task changes docs and config only. But:

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -q --tb=short
```

`test_config.py` exists and asserts settings behavior; a new setting with a default
should not break it, and if the file asserts an exhaustive field list, it needs
updating.

Then confirm the app still boots with **empty** keys — the degraded path from T2 is
what production looks like until the secrets land:

```bash
cd backend && ../.venv/Scripts/python.exe -c "from merlins_collection.main import app; print('ok')"
```

## Commit

```bash
git add CLAUDE.md backend/.env.example backend/README.md docs/aws-setup.md docs/plans/rfc-0009/
git commit -m "docs(slabs): correct the third-party API section and wire production config"
```

Update [`progress.md`](progress.md).

## Definition of done — all four, every time

This task is not finished until **all four** are true. The fourth is what keeps the
chain moving: a task that stops at "tests pass" strands the next conversation.

1. **The narrow test selection named above passes.** Not the full suite — that runs
   once, at T-FINAL.
2. **The work is committed**, using the commit command above.
3. **[`progress.md`](progress.md) is updated** — status, commit sha, and anything a
   later task needs in the Notes cell. Out-of-scope findings go to
   [`follow-ups.md`](follow-ups.md), not here.
4. **Your final message ends with a copy-pasteable prompt for a FRESH conversation
   to execute the NEXT task.** It must be self-contained, and it must contain:
   - which files to read first (always `progress.md`, plus that task's doc);
   - the task id, and "execute that task only";
   - the RED gate — write the failing tests, show the owner the failing output,
     **wait for confirmation**, and only then implement (CLAUDE.md, binding);
   - the constraints that actually bite for that task (`./.venv/Scripts/python.exe`
     never bare `python`; do not run the full suite; any landmine this task
     uncovered);
   - **this same four-part definition of done**, with the task numbers advanced.

The next task order is in [`README.md`](README.md) and [`progress.md`](progress.md).

**Nothing carries between conversations except what you commit and what that prompt
says.** Write it for someone with no memory of this one.
