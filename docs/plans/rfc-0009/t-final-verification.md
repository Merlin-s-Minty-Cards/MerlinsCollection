# T-FINAL — Full verification and PR

**Depends on:** every other task · **Blocks:** nothing

The only task permitted to run the full suites. Everything before this ran a narrow
selection, so this is the first time the whole system is exercised together.

## 1. Compare against the recorded baseline

The baseline is in [`progress.md`](progress.md), measured 2026-08-07 **before** any
RFC 0009 work. Your job is to find regressions, not to reach zero failures — some
failures pre-date this branch and are explicitly not yours.

| Suite | Baseline |
|---|---|
| Backend | 1369 tests / 52 files, ~2 min. **Two known `test_auth.py` failures** |
| Frontend | 545 tests / 73 files, ~31 s |
| MCP | 98 tests / 7 files, ~1 s |

Plus whatever each task added.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short
npm test --workspace=frontend
npm test --workspace=mcp-server
```

Use `./.venv/Scripts/python.exe`, never bare `python`. If the backend suite takes
far longer than ~2 minutes, someone reintroduced a per-test `mock_aws()` — CLAUDE.md
explains why that costs 507 ms per test versus 15 ms, and it is a regression worth
reporting.

**In Kiro/Cursor the shell tool times out around 10-15 s.** Start these as background
processes and poll; do not run them in the foreground and conclude they hung.

## 2. Lint

```bash
./.venv/Scripts/python.exe -m ruff check backend/src
npm run lint --workspace=frontend
```

Both had pre-existing findings at baseline. **Compare counts.** Do not chase them to
zero and do not "fix" unrelated files — that inflates the diff and buries the real
change.

## 3. Next build

```bash
cd frontend && npm run build
```

Round 4 found a real regression that only the build caught, which every test suite
had missed. Do not skip this step.

## 4. Boot with empty keys

Production will run with unset keys until the ECS secrets land, and every degraded
path in T2/T6 exists for exactly that state.

```bash
cd backend && ../.venv/Scripts/python.exe -c "from merlins_collection.main import app; print('ok')"
```

Then, with the app running and **no** keys set, confirm `/admin/slabs` still loads,
a typed cert still stages a row, and it still commits. **The feature must be fully
usable with no scanner, no camera, and no API access.**

## 5. Secret sweep

**`docs/plans/` is excluded from every command below**, because three docs in it
QUOTE these patterns — this file, [`t8-docs-and-ops.md`](t8-docs-and-ops.md) and
[`follow-ups.md`](follow-ups.md). Without the exclusion the sweep reports *itself*,
and a check that always cries wolf is one you learn to wave through — which is how a
real key eventually ships. (T8 fixed its own copy on 2026-08-09 and left this one,
since each doc owns its own commands; T-FINAL fixed this copy on 2026-08-09.)

Working tree — name-shaped, then a value-shaped scan no prose can trip:

```bash
git ls-files | grep -v "^docs/plans/" | xargs grep -l "pokeprice_\|^PSA_API_KEY=." 2>/dev/null

git ls-files | grep -v "^docs/plans/" \
  | xargs grep -nE "(PSA_API_KEY|POKEMONPRICETRACKER_API_KEY)[=:][\"' ]*[A-Za-z0-9_-]{8,}" 2>/dev/null

git check-ignore -v backend/.env   # must print a .gitignore hit
```

Branch history — a key committed anywhere in this branch's history, not just at the
tip, means rewriting history before the PR:

```bash
git log -p origin/main..HEAD -- . ':(exclude)docs/plans/' \
  | grep -nE "(PSA_API_KEY|POKEMONPRICETRACKER_API_KEY)[=:][\"' ]*[A-Za-z0-9_-]{8,}"

git log -p origin/main..HEAD -- . ':(exclude)docs/plans/' | grep -n "pokeprice_"
```

Expect no output from any grep, and a `.gitignore` hit for `backend/.env`. **All
clean on 2026-08-09** across the branch's 190 commits; the only matches for the
unfiltered form were the three docs named above. Do not conclude a key leaked
without a *value* match — none has.

## 6. Manual smoke test

An agent must **not** do this. `backend/.env` points at the **same live DynamoDB
table** as production, so an agent-run smoke test writes real inventory. The Round 4
plan deferred this step for the same reason.

Hand the owner a checklist. **Corrected 2026-08-09 (T-FINAL):** the original list
assumed PSA cert verification and a camera. Neither was built — PSA is blocked at the
account (403) so T2 and T5 are deferred, and intake is manual-first by design. There
is no "PSA-verified identity" to observe and no camera to scan with; those rows are
replaced below rather than left to fail on contact.

- [ ] Wedge-scan a real slab's cert barcode → the cert field fills and focus
      *advances*; the form does not submit on the scanner's trailing Enter
- [ ] Type a cert number by hand → same result, same path
- [ ] Identify the card via catalog autocomplete → row stages with the catalog name
- [ ] Identify a card the catalog does not have via the **free-text fallback** →
      row still stages and commits
- [ ] Enter a cert already owned → duplicate **warning** appears on blur and the
      **override** works (it is a warning, never a gate — a re-bought slab is legitimate)
- [ ] Commit a batch → items appear in Inventory, a purchase transaction appears in
      History, and the total is right
- [ ] A committed slab shows a price on the Slabs tab, or an honest "not priced"
- [ ] Trigger a price refresh → values update, quota is respected

## 7. Follow-ups

Read [`follow-ups.md`](follow-ups.md) end to end and summarize it for the owner in
your report. It is a decision list, not a backlog, and it is worthless if nobody
reads it once the work is done.

## 8. PR

Use the `pr-description` skill. The PR body should lead with the two facts a reviewer
most needs:

- `confirm_buy_session` could not create graded items at all before this branch.
- The slab pricing storage layer already existed and was unused; this fills it from
  an API rather than adding a schema.

And it must state that **both API keys need rotating** after merge (RFC §10).

## Commit

```bash
git add docs/plans/rfc-0009/
git commit -m "test(slabs): full-suite verification sweep for RFC 0009"
```

Set every row in [`progress.md`](progress.md) to `DONE` and record the final suite
numbers next to the baseline so the next person inherits a fresh measurement.

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
