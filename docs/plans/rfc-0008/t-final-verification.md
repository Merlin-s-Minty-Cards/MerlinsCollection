# T-FINAL — Full verification, docs, PR

**Run only once, after T1-T10 have all landed.** Per owner decision, the full
suite does not run inside individual task conversations.

## 1. Full test suite

Per CLAUDE.md, the shell tool times out around 10-15s — these **must** run as
background processes, then poll with `get_process_output`.

```
# Backend — ~10 min, 1050+ tests. Runs from workspace root.
python -m pytest backend/tests -q --tb=short 2>&1

# Frontend — ~25s, 41 test files. Needs the cmd /c wrapper; the cwd param is
# broken for subdirectories.
cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\frontend & npx vitest run --reporter=verbose" 2>&1

# MCP server — ~60s
cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\mcp-server & npx vitest run --reporter=verbose" 2>&1
```

Wait 30s+ before the first backend poll, 15s+ for the others.

> **Worktree gotcha** (from prior sessions): this checkout is a git worktree, and a
> global editable install makes Python import the **sibling** repo's backend. Always
> go through `pytest` or an explicit `PYTHONPATH=backend/src`. If results look
> impossible, verify with
> `python -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"`
> before debugging anything else.

## 2. Lint

```bash
ruff check backend/src
npm run lint --workspace=frontend
```

## 3. Cross-task regression checks

Things no single task's narrow test selection covers:

- **T1 + T2 both touched `routers/inventory.py`.** Confirm the price-bound reorder
  didn't disturb condition faceting and vice versa.
- **T4 + T7 both touched `AdminShell.tsx`** (height cap; new nav item). Confirm the
  sidebar still holds with the extra tab, and that the nav scrolls internally at a
  short viewport.
- **T6 + T8 both touched the admin inventory page** (column registry; set
  combobox). Confirm the set filter survived the registry refactor.
- **T5 + T11 both touched `CardDetailModal`** (widened fields; "Send to Triage"
  button). Confirm the modal still opens and saves from every page that uses it.
- **T7 + T11 both added a sidebar nav item.** Confirm the sidebar still holds with
  both, and that T11's count badge renders.
- **T10 + T11 both touched name resolution.** Confirm an override set via Triage
  actually changes what `/inventory` renders, with the JP badge intact.
- **T3's totals.** Chat-reported inventory totals will differ from before — that is
  the intended fix, not a regression. Confirm chat now **agrees with** the dashboard.
- **Customer-facing leak check.** T11 adds `review_reason`, an internal field.
  Hit `/inventory/search` on an item that has one and confirm it is **absent** from
  the response. `_CUSTOMER_ITEM_FIELDS` is an allowlist, so this should hold by
  construction — verify it anyway, because a leak here is admin notes reaching
  customers.
- **Triage queue drains and stays drained.** Clear an item, then re-run the
  importer or a sync over it, and confirm it is **not** re-flagged. This is the
  failure mode that makes review queues rot.

## 4. Manual smoke pass

The four §E surfaces, which the RFC warns is a four-surface outage if regressed:

- [ ] `/admin/buy` — catalog search returns results, fast, and shows a real error state on failure
- [ ] `/admin/trade` — incoming-card search likewise; no vendor-mode toggle present
- [ ] `/admin/market` — watchlist add finds a card
- [ ] `/admin/market` — catalog view lists cards

Plus:

- [ ] `/inventory` — price filter excludes a card priced above the max **as displayed**
- [ ] `/inventory` — condition dropdown offers `LP+` / `LP-` when such stock exists
- [ ] `/inventory` — a JP card with an override shows the English name; JP badge still there
- [ ] `/inventory` — a JP card **without** an override still shows its native name, not a guess
- [ ] `/admin/inventory` — columns toggle and persist across reload; filters follow visibility; "show all filters" works
- [ ] `/admin/shows` — create, edit, archive, unarchive
- [ ] Sidebar holds while scrolling, at desktop and 375px

Triage (T11):

- [ ] "Send to Triage" appears on **every** admin tab showing a card — walk them:
      Inventory, Vault, Sell, Buy, Trade, Show Prep, Prep Queue, History, card detail
- [ ] Flagging from a row action works, toasts, and Undo reverts it
- [ ] An already-flagged card reads "In Triage" rather than re-flagging
- [ ] Triage list shows reason chips; a card qualifying twice appears **once** with both
- [ ] Re-pointing a `card_id` shows before/after and warns on lineage and on a
      cross-language link
- [ ] Copying an English name sets the override and leaves `card_id` **unchanged**
- [ ] Clearing an item removes it from the list; sidebar badge decrements
- [ ] Empty state reads as success

## 5. Docs

Run the `sync-docs` skill. Specifically:

- **CLAUDE.md** — add `/admin/shows` **and `/admin/triage`** to the Admin Panel
  route table and the sidebar order list. Triage needs a short prose entry like the
  Prep Queue's: it is the `needs_review` queue, reachable from every tab, and the
  place automation errors get corrected.
- **CLAUDE.md** — the Prep Queue gotcha note has a sibling now: `needs_review` is no
  longer only an import artifact; admins set it deliberately. Say so.
- **CLAUDE.md Ops** — the catalog seed section says the live table has an empty
  catalog. **That is now false** — measured 31,603 catalog rows on 2026-08-05.
  Correct it, and record that the remaining catalog-search problem was the
  full-table scan (T9), not missing data. Leaving this stale will send the next
  reader down the same dead end this RFC started on.
- API endpoint docs for the new `/admin/shows`, `/admin/catalog/sets`, and
  `/admin/triage/counts` routes.
- Note the new model fields: `display_name_override`, `review_reason`,
  `reviewed_at`, `Show.archived`, and the new `catalog_set` entity. (There is no
  `name_en`/`dex_number` — that RFC design was dropped; make sure no stale doc
  claims otherwise.)

## 6. Release note

One line, per the RFC's §D risk item: **chat-reported inventory totals will change**,
because they were previously computed from stale nightly figures. Customers see this
number.

Specifics from T3, for whoever writes the line:

- The direction is **not** predictable. Chat now reports the live catalog price,
  which may be above or below the nightly `current_market_value` it used to read.
  In T3's parity fixture the old path came out $117 low on a $1,467 total (~8%).
- It is not only the total. `get_inventory_summary`, `calculate_inventory_value`,
  `search_inventory` and `flag_underpriced_cards` all reprice, so per-card figures
  quoted in chat move too, and `flag_underpriced_cards` may flag a different set.
- A card with no price from any source now reports `null` rather than `0`. It is
  still counted as held, is excluded from value totals and from "top valued
  cards", and is dropped by a min/max value filter.

## 7. PR

Run the `pr-description` skill against the branch diff.

## Done when

- All three suites green, both linters clean.
- Every manual checkbox ticked.
- Docs updated — especially the stale "catalog is empty" claim.
- PR description generated.
