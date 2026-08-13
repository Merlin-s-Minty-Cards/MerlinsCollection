# T12 — Docs, CLAUDE.md, and full-suite verification

**RFC:** 0011 (all) · **Layer:** both · **Depends on:** every task · **Blocks:** —

This is the only task that runs the full suite. Everything before it ran a narrow
selection on purpose.

## Part 1 — Documentation

### CLAUDE.md

Six edits. Each one is a rule a future reader will otherwise re-derive or break.

**1. The Admin Panel table** gains a row in the **Back office** group, between Triage and
Market:

```
| | `/admin/unmatched` | Unmatched | Cards TCGdex does not carry — parked from Triage, paired when the catalog catches up. See "Unmatched" below |
```

**2. A new section after "Triage"**, carrying the rules that are expensive to rediscover:

> **Unmatched** (`/admin/unmatched`) — the queue for cards the catalog does not have.
> RFC 0011. It exists because **`missing_card_id` is a DERIVED triage reason**, so before
> this an unmatchable card sat in Triage forever and the queue that is meant to reach zero
> had a floor it could never get under.
>
> **`no_catalog_match` is the stored fact, and `services/triage.is_missing_card_id` is the
> only place that reads it.** The list and the sidebar badge both route through that one
> function; adding the check anywhere else is how they start disagreeing.
>
> **The invariant: `no_catalog_match=True` implies `card_id is None`**, enforced by a model
> validator. Setting it on a linked item is a 422; assigning a `card_id` clears it
> automatically, because requiring a second write to leave a queue is how rows get
> stranded in one.
>
> **Nothing was backfilled and nothing auto-migrates** — owner requirement, 2026-08-13:
> *"all cards that go there should only be moved under admin supervision."* There is a
> permanent test asserting the queue is empty on an untouched table. Do not write a
> migration for this later.
>
> **Unlinking clears `current_market_value`.** The card was pointed at a close-but-wrong
> promo, so the figure it inherited is that promo's price and no sync will ever correct it
> once the link is gone. A parked card is hand-valued and carries `HandValuedBadge`.
>
> A parked item that is **also** flagged or unnamed stays in Triage with its remaining
> chips. Parking answers one question; those are different, real errors.

**3. Under the inventory table**, the sort and filter rules:

> **Every inventory column is sortable and every column has its own filter** (RFC 0011).
> Both are registry-driven: `SORT_FIELDS` (`services/inventory_sort.py`) and
> `FILTERABLE_FIELDS` (`services/inventory_filters.py`) on the backend,
> `INVENTORY_COLUMNS` / `INVENTORY_FILTERS` on the frontend. Totality is enforced by
> tests on both sides, so a new model field fails a test rather than silently arriving
> without a sort or a filter.
>
> **Missing values sort LAST in both directions**, for every type — not just money. A
> column where the blanks bunch at whichever end you are not looking at is a column
> people stop clicking.
>
> **Condition sorts by rank, not alphabetically:** NM > LP+ > LP > LP- > MP > HP > DMG.
> Alphabetical sorting made `LP+` and `LP-` identical, which is the exact distinction
> RFC 0008 T2 stored in two fields.
>
> **An unknown `sort` field or `filter` triple is a 422, never a silent no-op** — same
> rule as `triage_reason`. Two spellings of a filter exist (the legacy named params and
> the generic `filter=`), but **one evaluator**: the named params build the same
> `FieldFilter` objects. Four of them stay hand-written because they do more than a field
> comparison — `name` searches notes, `condition` splits `LP+`, `min_price` falls back to
> cost, and the catalog filters join the catalog.

**4. Under "Third-Party APIs" / Ops**, the catalog freshness rules:

> **`CatalogCard.first_seen_at` answers "when did this row appear"; `last_synced_at` does
> not** — it is bumped by any write, so a price refresh re-stamps a 2024 row. `None` means
> **predates the field**, not "new", and every reader counts only non-null values. It is
> written with a conditional `attribute_not_exists` update, **never in the item body**,
> because a full reseed whole-item `put_item`s every row and would otherwise reset all
> 31,603 of them.
>
> **`sync_new_sets` now always walks the brief card list** for both languages, instead of
> only when a set is entirely absent. That early-out is why a promo catalogued into a set
> we already hold was invisible. The extra walk is the accepted cost; **restoring the
> early-out will look like an optimization and is the bug.**

**5. Under the card-picker rule (§L's descendant)**, one paragraph:

> **`CardSearchPanel` is the one card search** — name + card number + set combobox,
> adopted by Buy, Trade, Slabs, Triage re-point, Market and Unmatched. `GET
> /admin/market/search` always accepted all three fields; the pickers just never sent
> them. **Manual entry is a permanent control**, not something that appears after a failed
> search — the owner's report was finding a card that exists whose catalog row is the
> wrong printing, at which point a gated button is unreachable. It is offered only where
> creating an off-catalog item is meaningful: Buy, Trade, Slabs.

**6. Correct anything now stale.** Search CLAUDE.md for claims this RFC invalidates — in
particular any text implying Triage is the only place unmatched cards live, or that the
inventory table's sortable columns are a fixed short list.

### Other docs

- `docs/plans/rfc-0011/progress.md` — final state, every task DONE with its sha
- `docs/plans/rfc-0011/follow-ups.md` — anything found and deliberately not fixed
- Grep `docs/` for statements this RFC makes false. RFC 0010's follow-ups list a
  "no per-tab send-to-triage" gap; check whether the Unmatched work changes its wording.

## Part 2 — Verification

Run all four, from the repo root, and **paste the real output** into `progress.md`. Do not
summarize a run you did not do.

```bash
# Backend — ~2 minutes, 1600+ tests
./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short

# Frontend — ~30 seconds
npm test --workspace=frontend

# MCP server — ~1 second
npm test --workspace=mcp-server

# Production build — catches type errors vitest does not
cd frontend && npm run build

# Linters
./.venv/Scripts/python.exe -m ruff check backend/src
npm run lint --workspace=frontend
```

**Before debugging anything that looks impossible**, confirm which package actually
loaded. This checkout is a git worktree and a global editable install can shadow it with
the sibling repo's backend:

```bash
./.venv/Scripts/python.exe -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"
```

### Known, not yours

`ChatPanel.test.tsx` has a documented history of load-dependent flakiness. It was fixed on
2026-08-11 (`mockReset` plus `userEvent.setup({ delay: null })`, 3317ms → 994ms). If it
fails, re-run it **in isolation** first — a failure that passes alone is the known
pattern, and the tell is that the failure *count* changes between runs. Note it; do not
chase it.

## Part 3 — Manual checks only the owner can do

List these in `progress.md` as outstanding. They need a browser and real data:

1. **`/admin/inventory`** — turn on Notes, Grade and Acquired. Confirm each header sorts
   both ways with blanks staying at the bottom, and that each filter narrows the list and
   disappears when its column is turned off.
2. **Triage → Unmatched** — park a card that already has no link; unlink a wrongly-matched
   one and read the confirm copy, checking it names the price it is about to clear.
3. **`/admin/unmatched`** — pair a card from a suggestion; confirm it leaves the queue and
   that its value becomes sync-maintained. Send another back to Triage.
4. **Dashboard** — the "Ready to pair" card shows the right count and links through.
5. **`/admin/buy`** — manual entry is clickable before typing anything; search by card
   number alone finds a card.
6. **Run "check for new sets"** on `/admin/market` once, so `first_seen_at` starts being
   populated. Until it runs, the dashboard's new-card count is legitimately `0`.

## Done means

1. all four suites and the build pass, with **real output pasted** into `progress.md`;
2. both linters clean;
3. CLAUDE.md carries all six edits;
4. `progress.md` records the final state, the verification sha, and the six manual checks
   as outstanding;
5. **not merged, not pushed** — that is the owner's call.
