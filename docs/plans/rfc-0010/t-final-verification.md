# T-FINAL — Full verification and the PR

**RFC:** 0010 (all) · **Layer:** verification · **Depends on: every task** · **Blocks:** merge

This is the first time RFC 0010's changes are exercised together. Per-task runs were **narrow by
design** (owner decision, carried from RFC 0008 and 0009), so nothing before this point has proven
the whole system green.

## Read this first — the lesson that cost RFC 0009 a stale sign-off

RFC 0009's T-FINAL certified commit `6486773`, then `80deb9c` landed 479 lines of UI on top of it.
The verification had run against a tree that no longer existed, and the recorded "575 passed" turned
out to be a **pass count read off a red run** — the fail count was never carried across.

Two rules follow, and they are not optional:

1. **Verify at the exact HEAD you are signing off.** Record the sha. If anything lands after, this
   task re-opens.
2. **A pass count is not a suite result.** Record passed **and** failed, always, for every suite.

## Known pre-existing failure — not yours

`frontend/components/inventory/__tests__/ChatPanel.test.tsx` fails **6–7 tests under full-suite
parallel load** and passes **12/12 in isolation**. That file and its component are untouched by this
branch. Confirm both facts still hold (`git log main..HEAD -- <paths>` is empty; run the file
alone), then **report it as pre-existing with both counts.** Do not chase it, and do not let it
block the PR — but do not paper over it either.

## The checklist

### 1. Full suites, all three layers

```bash
./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short
npm test --workspace=frontend
npm test --workspace=mcp-server
```

Record **passed / failed / files / wall time** for each, against the baseline in
[`progress.md`](progress.md):

| Suite | Baseline | This run | Delta |
|---|---|---|---|
| Backend | 1502 passed / 0 failed / 2m13s | | |
| Frontend | 580 tests, 6–7 failing | | |
| MCP | 98 passed / 7 files / 1.0s | | |

- **Backend wall time is a canary.** ~2m means the session-scoped `mock_aws()` is intact; **~10
  minutes means a per-test `mock_aws()` regression** was reintroduced (CLAUDE.md — 93% of the
  suite's time used to go to fixture setup).
- MCP should be **unchanged at 98**. No task in RFC 0010 touches `mcp-server`. If that number
  moved, find out why before signing anything.
- Use the documented `npm test --workspace=…` form. Both vitest suites fail spuriously under
  `npx vitest` ("Vitest failed to find the runner") — the failure is the invocation, not the code.

If backend results look impossible, this checkout is a git worktree and a global editable install
can shadow it with the sibling repo's backend. Check which package loaded **before** debugging
anything else:

```bash
./.venv/Scripts/python.exe -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"
```

### 2. Lint

```bash
./.venv/Scripts/python.exe -m ruff check backend/src
npm run lint --workspace=frontend
```

Both were clean at the RFC 0009 sign-off, so **clean is the bar, not "no new findings."**
`backend/scripts` and `backend/tests` carry pre-existing `I001`/`E501` findings and are **not** in
the named path — do not chase them to zero.

### 3. `next build` — NOT OPTIONAL

```bash
npm run build --workspace=frontend
```

**Vitest does not typecheck.** This is the only gate that catches that class, and in RFC 0009 it
caught a real bug all 573 frontend tests missed: `/admin/slabs` passed `{ params: {…} }` to
`api.get`, whose second argument **is** the params record, so the request emitted
`?params=[object Object]` and the unpriced worklist silently returned every slab.

RFC 0010 has three places with the same exposure:

- **T5** changed `onUpdated`'s signature across six call sites;
- **T10** added a model field consumed by a new frontend grouping;
- **T12** edited the same `/admin/slabs` page that shipped the original bug.

**Never skip this step.**

### 4. Secret-leak sweep

Use RFC 0009 T-FINAL's corrected form — it excludes `docs/plans/` (so the command does not match
its own text) and greps for the **value shape** as well as the variable name. Sweep every commit on
the branch, not just the tip.

T14 *removes* key references, which is the safe direction, but the pricing key is still live and
**still un-rotated** (RFC 0009 T8, owner action outstanding).

### 5. Boot with keys forced empty

```bash
cd backend && POKEMONPRICETRACKER_API_KEY= ../.venv/Scripts/python.exe -c "
from merlins_collection.services.slab.pricing import *
from merlins_collection.config import settings
print('pricing key set:', bool(settings.pokemonpricetracker_api_key))
"
```

The app must boot and `build_pricing_provider()` must return `None`, the nightly job must skip
graded pricing while every other step runs, and **T12's intake-time refresh must degrade to
"committed, not yet priced"** rather than failing a commit. An unset key is a supported state.

### 6. Manual smoke checklist — hand this to the owner

Each line maps to a task. **Every one of these is a thing the owner reported and could not do.**

| # | Check | Task |
|---|---|---|
| 1 | Type `1,300` as a slab cost. It stages as `$1,300.00`, commits, and the item's cost is 1300 | T0 |
| 2 | Type `1,30` as a slab cost. The add is refused at the form; nothing reaches the server | T0 |
| 3 | Type `1,300` in a Buy price and a Prep Queue sticker. Both commit as 1300 | T1 |
| 4 | Edit an import-created consignor's payout %. **One** row, updated | T2 |
| 5 | Create a second consignor with an existing name. Refused, with a useful message | T2 |
| 6 | Archive a consignor. It **disappears** from the list; "View archived" shows it marked **Archived**, never "Sold"; Unarchive brings it back | T2 |
| 7 | The Harry the owner already soft-deleted renders as **Archived**, not active and not "Sold" | T2 |
| 8 | Open Triage. **Every visible row has at least one WHY chip** | T3 |
| 9 | Filter by each reason. The count changes each time | T3 |
| 10 | Filter to `blank_condition`, set a real condition on a card in hand, and confirm the **customer-facing** price on `/inventory` moves. Record the queue's size — that is the remediation job | T3 |
| 10b | Bulk-clear machine flags. **`blank_condition` rows survive it** | T3 |
| 11 | Search a card name in Triage. A no-match search does **not** say "Nothing needs review" | T4 |
| 12 | Scroll well down Inventory, open a card, edit its location. The value updates at once **and you stay where you were** | T5 |
| 13 | At **150% and 200% zoom** on Triage, Show Prep and Inventory: open a card and type in the **Finish** field. The characters go into Finish, and the box is readable | T6 |
| 14 | A card with **no** art lays the modal out the same way | T6 |
| 15 | Filter Prep Queue to the glass case, price two cards. Count drops by two, list does not jump, only glass items remain | T7 |
| 16 | Show Analytics on 2026-08-10 reads **Aug 10** everywhere, agreeing with the date picker | T8 |
| 16b | **After 5pm Pacific** (or with the clock set there), open Buy. The default date is **today**, not tomorrow | T8 |
| 17 | A sale reads `+$`, a purchase reads `−$` — **and they are distinguishable in greyscale** | T9 |
| 18 | Buy three cards in one session. Show Analytics shows **one** purchase line, expandable to three | T10 |
| 19 | A pre-existing (pre-`batch_id`) day still lists its rows correctly | T10 |
| 20 | Sell a card, then void the sale with a reason. Card returns to `available`, the day's total drops, History shows it struck through with the reason, the timeline shows **both** the sale and the void | T11 |
| 21 | Restore that void. Everything goes back | T11 |
| 22 | Regenerate the show snapshot after a void. The number moved | T11 |
| 23 | No **Camera scan**, **Auto-fill from cert** or **Scan cert** button on `/admin/slabs` | T12 |
| 24 | **Wedge-scan a cert into the plain cert field.** Digits land intact, focus advances to Card | T12 |
| 25 | Intake a slab with a catalog match. It gets a price within seconds of commit | T12 |
| 26 | Intake a free-text slab. It commits, says it will not be auto-priced, appears under `?priced=false` | T12 |
| 27 | All sixteen sidebar destinations reachable; Triage count visible with its group collapsed; expansion survives a reload | T13 |
| 28 | Phone-width viewport shows five nav entries | T13 |
| 29 | Search `Charizard` in **all five** catalog pickers — Triage (both dialogs), Slabs, Market, Buy, Trade. Every candidate shows its **image and its price**, and the name is still readable at 100% and 150% zoom | T15 |
| 29b | An unpriced card reads **"no price yet"**, never `$0.00` or a blank cell | T15 |
| 29c | Run the nightly job with `CATALOG_REFRESH_CARDS_PER_NIGHT=50`. Fifty `brief` rows come back `full` with prices, the lock is released, and the coverage panel's `brief` count drops by 50. **Do not run an uncapped pass by hand** — it is 2 h 18 min against a free volunteer-run API | T17 |
| 29d | `/admin/market` coverage reports **0** `full` rows older than 8 days once a cycle has completed — this is the auditable form of "by Friday" | T17 |
| 30 | On Triage's `missing_english_name` queue, search a Japanese card. **The art is what lets you pick it** | T15 |
| 31 | Hand-value a card that is not in the catalog from Triage. It prices on `/inventory`, sells through `/admin/sell`, takes a sticker from Prep Queue — **and the value survives `POST /admin/market/sync`** | T16 |
| 32 | Archived consignors and archived shows behave **identically**: hidden by default, one toggle reveals them, both badges read `Archived` | T2 |

**Row 24 cannot be verified any other way.** T12 removes the scanner UI on the premise that a wedge
scanner is just a fast keyboard. If that premise is wrong, hand-typing still works and the failure is
invisible — a scanner in hand is the only test.

**Row 13 is T6's actual acceptance criterion**, not its test suite. A jsdom test asserts classes; only
a person can confirm a field is typeable.

### 7. The PR

Use the `pr-description` skill. The body must state:

- the twelve owner-reported items and which task closed each;
- **that T0 closes the RFC 0009 merge blocker**, since that is why this branch could not ship;
- the three owner decisions that reversed a written request or a prior plan — no Triage sticker
  reason, PSA withdrawn, `type="number"` rejected for money;
- the final suite numbers, **passed and failed**, with the `ChatPanel` flakiness named as
  pre-existing;
- the schema additions (`Transaction.batch_id`, the three void fields) and that **nothing is
  backfilled**;
- the three owner actions still outstanding: **rotate the pricing API key**, run
  `reconcile_consignors.py` against production if T2's fork exists there, and **work the
  `blank_condition` Triage queue** — those cards are listed to customers as NM until someone
  checks them, so state the count.

## Sign-off is not merge

Do not merge. Record in [`progress.md`](progress.md): the verified sha, all suite numbers, the
smoke-checklist result, and anything the owner still has to do. Then hand it over.

## Do not

- Do not sign off against a sha that is no longer HEAD.
- Do not record a pass count without its fail count.
- Do not skip `next build`.
- Do not chase the `ChatPanel` flakiness — report it.
- Do not chase `backend/scripts` / `backend/tests` lint findings.
- Do not call this done off the automated checks alone. The smoke checklist is where twelve of the
  twelve reported bugs actually get confirmed fixed.

---

## Done means: committed, recorded, and the next prompt emitted

This task is finished when **all five** of these are true. Four is not done.

1. **The narrow test selection above passes**, and you have shown the output. Not "should pass".
2. **[`progress.md`](progress.md) is updated** — this row set to `DONE` with the commit sha, a
   Notes line if a later task needs to know something, and anything surprising added to the
   Decisions table.
3. **Out-of-scope findings are appended to [`follow-ups.md`](follow-ups.md)** — not fixed as a
   side errand, and not left only in the conversation.
4. **The work is committed.** One focused commit, or a small series, in this branch's
   conventional-commit style (`feat(scope):` / `fix(scope):` / `docs(scope):`). Do not merge, do
   not push unless asked.
5. **Your final output is the ready-to-paste prompt below**, so a fresh conversation can pick up
   the next task without the owner reconstructing anything.

### Next in the chain

**Nothing — this is the last task.** Instead of a next-task prompt, end with the sign-off summary
T-FINAL asks for: the verified sha, every suite's passed AND failed counts, the smoke-checklist
result, and the owner actions still outstanding. **Do not merge.**
