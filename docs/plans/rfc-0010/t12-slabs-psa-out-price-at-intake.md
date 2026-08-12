# T12 — Slabs: PSA out, scanner affordance out, a price at intake

**RFC:** 0010 §H + §I · **Layer:** full-stack · **Depends on: T0** · **Blocks: T14**
**Owner ask, 2026-08-10:** *"I just found out that the PSA API is now a paid feature, so we will
not be using it anymore. Now, the slab tab flow should be: enter a cert number, match to a
catalog card, manual entry if no catalog card to match, then send to the pricing API to get a
market price. I think we can just hide the scanner functionality because it seems to me like all
the scanner does is essentially type the number when it scans so it could just be used in the
normal input box anyway."*

Three of those four steps already exist. The fourth — pricing at intake — is new, and it is a
small change if you resist writing a second pricing path.

## Part 1 — PSA is dropped, not deferred

Until now the position was "403 at the account, remedied by an approval email" (re-confirmed
2026-08-10 against PSA's Swagger with both bearer spellings). **A paid API the owner has declined
changes that from deferred to withdrawn** — the same call already made about PriceCharting on
2026-08-07.

**Remove:**

- the two disabled buttons — **Camera scan** and **Auto-fill from cert** — and the
  `#psa-blocked` note (`frontend/app/(admin)/admin/slabs/page.tsx:145-171`), plus the now-unused
  `Camera` / `Wand2` imports;
- RFC 0009 **T2** and **T5** move `DEFERRED` → **WON'T DO** in
  `docs/plans/rfc-0009/progress.md`, with the paid-API reason and the date. **Do not delete
  those docs** — a decision recorded beats a gap nobody can explain.

They were rendered disabled *on purpose*, so the gap read as known rather than forgotten. With the
gap now permanent, a disabled button implies a roadmap that does not exist.

The `.env.example` / CLAUDE.md / RFC 0009 documentation sweep is **T14**, not here. Keep this task
to code.

## Part 2 — Hide the scanner affordance, keep the scanner working

The owner's reasoning is exactly right, and it is why `CertInput` was built with **no scanner
detection and deliberately no timing logic** in the first place.

**Remove:** the **Scan cert** button, the `scanArmed` state, the "waiting for scan" affordance,
and `armScan` (`slabs/page.tsx:26-34, 134-141`), plus the `armed` prop on `SlabEntryForm`.

> ### ⚠️ Do NOT remove these from `CertInput`
>
> - **`onEnter` — Enter *advances* focus, it never submits.** A wedge scanner ends its burst with
>   Enter. If that submitted, the form would fire before card, grade and cost were filled.
> - **Trailing `\r` / `\n` stripping.** Without it an invisible character rides into a URL path on
>   the duplicate-cert check.
>
> Both are what make wedge scanning work **in the ordinary field**, which is the owner's whole
> point. Removing them breaks scanning while hand-typing keeps working — an invisible failure
> nobody finds until someone is standing at a table with a scanner.
>
> The existing regression test — *characters typed one at a time over a long span are exactly as
> valid as a burst* — **stays**, and so do the other five `CertInput` tests.

`focusToken` stays: the commit path still uses it to return focus to the cert field
(`slabs/page.tsx:94`), which is the ergonomic fix that closed an RFC 0009 follow-up.

Keep the **Manual entry** disclosure exactly as it is. It is the form's only toggle now, and the
form staying open across adds is deliberate — intake is a batch workflow.

## Part 3 — Price a slab at intake

Today `attach_price` runs only from the nightly `run_daily_sync` and from
`POST /admin/slabs/refresh-prices` (`routers/admin/slabs.py:313`), so a freshly-committed slab has
no value until the next night.

**Reuse the existing refresh. Do not write a second pricing path.**
`refresh_graded_prices` (`services/catalog_sync.py:226`) already walks owned slabs
**never-priced-first**, so a slab committed a second ago is already at the head of its queue.
What is missing is scope:

- `refresh_graded_prices` gains `only_item_ids: set[str] | None = None`, applied when selecting
  candidates — **before** any pricing call, so a filtered-out slab costs nothing;
- `POST /admin/slabs/refresh-prices` accepts optional `item_ids: list[str]` and passes it through;
- after a **successful** commit, `/admin/slabs` fires that scoped refresh and polls
  `/refresh-prices/status`. The Market page's polling UI is the precedent to copy rather than a
  second pattern to learn.

Without the scope filter a 3-slab batch spends the day's whole 50-lookup budget re-checking the
shelf.

> ### Pricing runs AFTER the commit, never inside its loop
>
> The commit finishes, the batch clears, **then** pricing runs. T0 exists because a money write
> blew up mid-loop; putting a metered third-party HTTP call inside the same loop rebuilds that
> failure with a worse trigger. A vendor 500, a spent quota, or a **409 "a refresh is already
> running"** must degrade to *"committed, not yet priced"* — a state the product already models,
> at `/admin/slabs?priced=false`.
>
> Concretely: the commit's success message lands first and unconditionally. The pricing result is a
> second, separate status line.

### An unmatched slab stays unpriced — owner decision

The verified-join rule is unchanged: a price attaches only when the vendor's
`externalCatalogId`, read as `en:<id>`, equals the item's own `card_id`
(`services/slab/pricing.py:451-500`, `_verify_join`).

So the manual-entry fallback the owner asked for is, **by construction, unpriceable** — no
`card_id`, no join, no price. Offered three options, the owner chose to keep the rule: the
vendor's name search was measured wrong roughly **one time in three**, and a wrong price looks
exactly like a right one. Japanese slabs carry no `externalCatalogId` at all and are unpriceable
for the same reason.

**The UI must say so at the point of decision**, not leave the operator wondering. `StagingTable`
already marks a row with no `card_id` as *"no catalog link"*; extend that to name the consequence
— *"no catalog link — will not be priced automatically"*. Neither case is Triage-flagged (owner
decision 2026-08-09, and consistent with T3's ruling on what Triage is for); both surface at
`/admin/slabs?priced=false`.

### Quota, stated plainly

The free tier is **100 credits per UTC day** and a graded lookup costs **2**, so **50 lookups a
day, total, shared with the nightly job**. A 30-slab intake day consumes 60% of it. The scoped
refresh is what keeps that honest; the run summary already reports credits remaining, and the
result line should show it so the spend is visible.

*Open question in `progress.md`:* fire automatically after every commit, or leave a "Price this
batch" button? Automatic matches the owner's flow description. **Recommend automatic, with the
credit cost in the result line.**

## Files

- **Modify:** `frontend/app/(admin)/admin/slabs/page.tsx`
- **Modify:** `frontend/components/admin/slabs/SlabEntryForm.tsx` — drop the `armed` prop
- **Modify:** `frontend/components/admin/slabs/StagingTable.tsx` — the consequence wording
- **Modify:** `backend/src/merlins_collection/services/catalog_sync.py` — `only_item_ids`
- **Modify:** `backend/src/merlins_collection/routers/admin/slabs.py` — `item_ids` on the trigger
- **Modify:** `docs/plans/rfc-0009/progress.md` — T2/T5 → WON'T DO
- **Tests:** `frontend/components/admin/slabs/__tests__/*`,
  `frontend/app/(admin)/admin/slabs/__tests__/page.test.tsx`,
  `backend/tests/test_catalog_sync.py` (or wherever `refresh_graded_prices` is covered),
  `backend/tests/test_slabs.py`

## RED — write these first, show the failing output, wait for confirmation

**Backend (5):**
1. `refresh_graded_prices(only_item_ids={...})` prices only those slabs;
2. filtered-out slabs cost **zero** provider calls (assert on a recording fake's call count);
3. `POST /admin/slabs/refresh-prices` with `item_ids` passes them through;
4. without `item_ids` it behaves exactly as today — the regression gate;
5. an unknown item id in `item_ids` is ignored, not a 500.

**Frontend (7):**
6. the **Camera scan** and **Auto-fill from cert** buttons are **gone**;
7. the **Scan cert** button is **gone**;
8. **`CertInput` still advances on Enter and still strips `\r\n`** — the guardrail test, and it
   must be named so nobody deletes it;
9. a successful commit fires `refresh-prices` scoped to the created item ids;
10. **a failed refresh does NOT undo or obscure the commit success message**;
11. a **409** from the refresh reads as "committed, not yet priced", not as an error;
12. a staged row with no `card_id` says it will not be priced automatically.

Note the existing test trap: the form renders both `Grade` **and** `Grade label`, so grade queries
must stay anchored `/^grade$/i`.

**Commands corrected as executed.** The frontend half was the broken `npx vitest` form;
the backend `-k` expression works but is slow and imprecise (it also collects
`test_slabs.py`'s neighbours by module name). Real paths — note `routers/admin/` and
`services/`, and that `confirm` now returns `item_ids` so `test_purchases.py` is in scope:

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_slabs.py backend/tests/routers/admin/test_purchases.py backend/tests/services/test_catalog_sync.py -q --tb=short
npm test --workspace=frontend -- --run "app/(admin)/admin/slabs" "components/admin/slabs"
```

## GREEN — done when

The above pass, all 20+ pre-existing slab frontend tests pass, the pre-existing
`refresh_graded_prices` tests pass, `ruff check backend/src` is clean, and
`npm run lint --workspace=frontend` is clean.

**Run `npm run build --workspace=frontend`.** This page is where RFC 0009's
`?params=[object Object]` bug shipped — `api.get`'s second argument **is** the params record, not
a `{ params }` wrapper — and vitest does not typecheck.

## Manual check

Intake one slab with a catalog match: confirm it commits, then gets a price within a few seconds.
Intake one with free text only: confirm it commits, says it will not be auto-priced, and appears
under `/admin/slabs?priced=false`. Then **scan a cert with the wedge scanner into the plain cert
field** and confirm the digits land intact and focus advances — that is the behaviour Part 2 is
betting on, and it cannot be verified any other way.

## Do not

- Do not remove `CertInput`'s Enter handling or `\r\n` stripping.
- Do not delete RFC 0009's T2/T5 docs — mark them WON'T DO.
- Do not write a second pricing path. Scope the existing one.
- Do not call the pricing provider inside the commit loop.
- Do not let a pricing failure fail, obscure, or roll back a commit.
- Do not price an unmatched slab off a name search. Owner decision.
- Do not make the cert number optional. Without one it is not a slab
  (`GradedInventoryItem.cert_number` is `str`, not `str | None`).
- Do not remove the `CERT#` duplicate-cert warning. It never depended on PSA.
- Do not touch `.env.example` or CLAUDE.md — that is T14.

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

**T13 — Sixteen flat tabs become three groups**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t13-grouped-navigation.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
