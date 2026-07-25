# RFC 0001: Inventory ↔ Catalog Relink and Display-Name Fallback

- **Status:** Implemented (passed Council review on revision 3; BE 541 / FE 158 / MCP 71 green, lints clean)
- **Author:** design-doc agent (for Ethan Harter)
- **Date:** 2026-07-24
- **Branch:** `Polishing-For-Deployment`
- **Supersedes/implements:** `claude-progress.txt` PART 3 "ACTIVE BUGS"

> **As-built note:** section C below was written against a read-time,
> notes-parsing design. During implementation the Council flagged that design as
> a data-leak risk (a dropped-empty identity segment could promote
> cost/consignor/location free-text onto the wire), so the shipped design instead
> **materializes `display_name` once, at import time**, from the item's
> structured `Name`/`Card #` columns — never from `notes`. Section C is updated
> below to describe what shipped; see C.6/Follow-ups for what this retires.

---

## Owner decisions (final)

The owner has ruled on all three questions from section E. These are binding:

1. **Relink strategy — Option C (review toolchain).** DECIDED as recommended
   (section D). Relink existing NULL-`card_id` rows via `build_review.py` →
   `apply_review_decisions.py`; no destructive re-import.
2. **Sealed items — HIDE (cards-only customer surface).** DECIDED, and this
   **overrides** the RFC's original recommendation to keep sealed visible. `sealed`
   is removed from the customer-visible kinds on **every** customer-facing read path
   (backend `/inventory/search` and the MCP chat tools). See revised section E1.
3. **Sold ratio (~80%) — trust as genuine, DEFER.** No investigation now. See
   revised section E2.

---

## Summary

The `/inventory` filter page and `/chat` tools look broken because the spreadsheet
import linked almost no inventory rows to the catalog: `card_id = NULL` on ~93% of
AVAILABLE items. The catalog itself is healthy and the FE↔BE contract is correct.
The single defect is that `spreadsheet_import._match_card` and the catalog index it
looks against **compare raw, un-normalized name and number strings**, so an Excel
float artifact (`"181.0"` vs catalog `"181"`), a slash form (`"182/167"`), or minor
name punctuation defeats every lookup. This RFC designs (B) a normalized,
conservative matcher fix; (C) a display-name fallback, materialized once at
import time from structured identity (not parsed from notes at read time — see
the as-built note above), so unmatched stock reads as a card name instead of a
ULID; and (D) a recommendation to relink existing production rows via the
read-only review toolchain rather than a destructive re-import. It defines RED
unit tests to author first per the project's TDD rule.

---

## Motivation

Owner report: *"filter page shows transactions and booster packs instead of just
cards; filters return no results like they're not formatted right; chat returns only
the card ID without the name."* All three symptoms trace to one cause (unmatched
inventory) plus one cosmetic amplifier (the ULID fallback title). The app is live;
this is the whole remaining launch-blocking job. Fixing it makes the customer-facing
search usable without touching deployment.

---

## A. Verification note — diagnosis CONFIRMED (with one important nuance)

I read the real code at every location the diagnosis names. The root-cause claim is
**correct**. Concretely:

**The matcher never normalizes.** `spreadsheet_import.py`:

- Index build (line 1048):
  `catalog_index.setdefault((card.name.lower(), card.number), []).append(card)`
  — keys on the **raw** catalog `name.lower()` and **raw** `number`.
- Lookup (`_match_card`, line 262):
  `hits = ctx.catalog_index.get((name.strip().lower(), str(number).strip()), [])`
  — looks up the **raw** sheet name/number.

Neither side calls the normalizers that already exist in `card_text.py`
(`normalize_name`, `normalize_number`/`strip_float_artifact`). So:

- `Card #` cell `"181.0"` (Excel float export) → key `"181.0"` ≠ catalog `"181"` → miss.
- `"182/167"` (sheet writes the full collector string) ≠ catalog `"182"` → miss.
- Name punctuation/spacing drift (`"Moltres & Zapdos-GX"` vs `"Moltres & Zapdos GX"`)
  → miss.

This fully explains the "<10% matched" observation. The price-noise example from the
diagnosis (`notes="Dragonair #181.0 — 30-32"`) is worth clarifying: the `"— 30-32"`
is the **Notes column**, appended as a separate ` — `-delimited notes segment — it is
NOT inside the `Card #` cell. The `Card #` cell itself is just `"181.0"`. So the
matcher only has to survive the float artifact, not embedded price text; the price
text is a *display* concern handled in section C.

**Symptom 1 (filters return nothing).** Confirmed. `routers/inventory.py:114-137`
applies `set_id`, `name`, and `rarity` by joining through `catalog.get(card_id)`.
With `card_id=NULL` on nearly every available item, those filters exclude almost
everything. `language`, `condition`, and price filters are in-item and unaffected.

**Symptom 2 ("transactions / booster packs").** Confirmed as *not* real Transaction
entities. It is (a) the ULID title fallback in `frontend/lib/inventory.ts:181-184`
(`item.card?.name ?? item.card_id ?? item.item_id` → renders a ULID that reads like a
junk id) and (b) the 2 legitimate `kind=sealed` items, which are customer-visible by
design (`_CUSTOMER_KINDS` at `inventory.py:35`). See owner-decision E1.

**Symptom 3 (chat shows the id, no name).** Confirmed. `mcp-server/src/
dynamodb-repository.ts` `toCard` (lines 150-157): `name = meta ? meta.name :
(cardId ?? item_id)`. With `card_id=NULL` the name becomes the ULID.

**Nuance / partial correction — set the expectation correctly:** even a *perfect*
normalizer cannot uniquely auto-link many singles. The Singles tab has **no Set
column**, and a `(name, number)` pair routinely matches the same card printed in
several sets. Those rows are genuinely ambiguous; the correct outcome is
`card_id=None, needs_review=True`, and they must flow to the **human review
toolchain** (section D), not be force-linked to `hits[0]`. So the matcher fix raises
the auto-link rate on *unambiguous* rows and shrinks the review queue — it does not,
and must not, drive NULLs to zero by guessing. This distinction drives both the
matcher design (conservative, no fuzzy auto-link) and the relink recommendation.

---

## B. Matcher fix design (`_match_card` + the index it reads)

### B.1 Where each piece lives

- `backend/src/merlins_collection/services/spreadsheet_import.py`
  - `_match_card(...)` — the lookup.
  - `run_import(...)` line 1046-1048 — the catalog index build (must change in lockstep).
- `backend/src/merlins_collection/services/card_text.py` — shared normalization home.
  Already exports `normalize_name`, `normalize_number`, `strip_float_artifact`,
  `parse_language`. This RFC proposes **moving three helpers here** so the importer
  and the review page share one implementation (they currently disagree, which is the
  exact failure class `card_text.py`'s own docstring was written to prevent):
  - `core_name(text)` (drop finish/variant words) — today in `scripts/build_review.py`.
  - `number_keys(number)` (slash + zero-strip forms) — today `_number_keys` in `build_review.py`.
  - `sets_agree(a, b)` (token-containment set match) — today `_sets_agree` in `build_review.py`.

  `build_review.py` then imports them from `card_text.py` instead of defining its own,
  so producer (importer) and consumer (review page) normalize identically.

### B.2 Shared index builder (new, single source of truth)

Add a pure function `build_catalog_index(cards) -> CatalogIndex` (or a plain dict
keyed structure) in `card_text.py` or `spreadsheet_import.py`, and have **both**
`run_import` and any test build the index through it. It keys catalog cards on:

```
by_name_number[(normalize_name(card.name), num_key)]  -> [CatalogCard]   for num_key in number_keys(card.number)
by_core_number[(core_name(card.name), num_key)]       -> [CatalogCard]
```

This is deliberately the same shape `CatalogIndex.build` in `build_review.py` already
uses — the review page's matcher is the "good" one; the importer should share its
normalization, just apply a stricter (auto-link-only) decision rule.

`ImportContext.catalog_index`'s type/comment changes from
`(name_lower, number) -> [CatalogCard]` to the normalized structure above. All current
`_match_card` callers pass through `ImportContext`, so no call-site churn beyond the
two importers already calling it.

### B.3 `_match_card` algorithm (exact-then-narrow, conservative)

Inputs: `ctx`, `name`, `number`, `*`, `language=EN`, and a new optional
`set_text: str = ""` (slabs have a Set column; singles pass `""`).

```
1. Language gate (UNCHANGED): if language is not EN -> return None.
   (The English-only catalog gate stays first; all existing JP tests must stay green.)

2. Normalize:
     n_full = normalize_name(name)
     n_core = core_name(name)
     keys   = number_keys(normalize_number(number))   # e.g. "181.0" -> ["181"], "182/167" -> ["182/167","182"]
   If n_full is "" (fully non-ASCII) -> return None.   # "no evidence", never a match

3. Exact tier — full name + number:
     for k in keys: hits = by_name_number[(n_full, k)]; stop at first non-empty.
     if len(hits) == 1 -> return hits[0].card_id            # unambiguous: AUTO-LINK
     if len(hits) > 1  -> go to step 5 (set narrowing)

4. Core tier — variant-stripped name + number (only if step 3 found nothing):
     for k in keys: hits = by_core_number[(n_core, k)]; stop at first non-empty.
     if len(hits) == 1 -> return hits[0].card_id
     if len(hits) > 1  -> go to step 5

5. Set narrowing (only reached when hits are multi-set AND we have set evidence):
     candidates = set_text or trailing tokens of the name (for singles that wrote the
                  set into the name, e.g. "Mew Gold Celebrations").
     narrowed = [c for c in hits if sets_agree(candidate_set, c.set_name)]
     if len(narrowed) == 1 -> return narrowed[0].card_id
     otherwise             -> return None

6. Anything else -> return None   # ambiguous or unfound -> needs_review -> review toolchain
```

**Match order:** exact full-name+number → variant-stripped name+number → set-narrowed.
**Threshold / tie-breaking:** auto-link **only** on a *unique* survivor
(`len == 1`). A multi-hit that set-narrowing cannot reduce to one returns `None`. There
is **no fuzzy matching in the importer** — fuzzy (`difflib`) and confidence bands stay
in the human review page (`build_review.predict_card`), which is where an uncertain
guess belongs. `hits[0]`-on-a-tie (the "pick the first of many" behavior) is explicitly
forbidden; it is how a card would silently get the wrong set's price.

**As-built addendum — qualifier/variant guard (added during Council review, both
match branches):** a core-tier match (step 4) reaches the catalog only by
dropping a variant word from the sheet name. Dropping a FINISH word (holo/
reverse) costs no confidence, but dropping a QUALIFIER (alt art/gold/1st
edition/etc., `_QUALIFIER_TOKENS` in `card_text.py`) means the sheet describes a
materially different, differently-priced print than the card the core tier
landed on. `_dropped_qualifier(sheet_name, card_name)` checks for exactly that
and forces `None` (→ `needs_review`) rather than auto-linking — on **both** the
single-hit branch (step 3/4) and the set-narrowed branch (step 5), since
narrowing to one set does not restore a qualifier the core tier already dropped.
Without this guard a variant (e.g. an alt-art print) could be silently linked to
its base card's price.

**Caller changes:**
- `import_singles` (line 309): pass `set_text=""` (no Set column). It may optionally
  pass the trailing-name-token heuristic; keep it minimal — trailing-token set
  inference can be deferred to the review page if it complicates the first cut.
- `import_slabs` (line 364): pass `set_text=set_name` (the parsed Set cell), so a slab
  whose name+number hits several sets is narrowed by its Set text.

**What does NOT change:** the language gate and its ordering; the JP "keep the sheet's
own money" behavior; `needs_review = card_id is None or blank_condition`; the notes
string the importer preserves (identity is still recoverable by `parse_source_text`).

### B.4 Consequence for existing rows

The matcher fix changes only **future** imports. It does not rewrite the live table.
Existing NULL rows are relinked by section D.

---

## C. Display fallback design — AS BUILT: materialize at import, not read-time notes-parsing

**Goal:** when `card_id` is NULL, show a human name derived from the item's identity
instead of a ULID — in the frontend tile *and* the MCP `toCard`.

**This section documents the shipped design**, which differs from the RFC's original
proposal (parse `notes` at read time, in both languages, on every request). The
Council flagged that approach as fragile and leak-prone: a dropped-empty identity
segment in the notes-parsing path could silently promote a later segment (cost,
consignor, location) onto the wire, and the parsing rule would have to be kept in
sync, forever, in two languages. The shipped design instead computes the name
**once, at import time**, from data that was never at risk of containing free-text
in the first place, and stores it.

### C.1 Hard constraint (unchanged from the original design)

`notes` is **internal-only** and deliberately excluded from the customer wire. The
backend `/inventory/search` response uses an **allowlist** (`_CUSTOMER_ITEM_FIELDS`,
`inventory.py:51`) that omits `notes`, `cost_basis`, `location`, `tcg_url`, etc. The
raw `notes` string can contain a cost/price range (`"— 30-32"`), a location
(`"For David"`), and free-text. **Exposing raw `notes` to the client (or deriving a
customer-facing field from it) would risk leaking internal business data.**

### C.2 Materialization rule — `format_display_name` (`services/card_text.py`)

`display_name = format_display_name(name, number)` composes `"<name> #<number>"`
(or just `<name>` when the number isn't a well-formed card number) from the
**structured** `Name` / `Card #` sheet columns — never from `notes` — and:

- whitespace-collapses the name, returns `None` when there is no name at all;
- appends the number only when it survives `normalize_number` and matches the
  card-number shape (so a stray non-numeric artifact isn't glued on);
- length-bounds the result (`_DISPLAY_NAME_MAX = 80` chars).

It is called **once**, at import time, by every importer that creates a row
(`import_singles`, `import_slabs`, `import_consignments` in
`spreadsheet_import.py`) and by the relink toolchain
(`apply_review_decisions.DecisionApplier._write_card`, using the review decision's
confirmed name/number). The result is stored on the item row as `display_name`.
There is no read-time derivation anywhere — nothing parses `notes` to produce it.

Example: sheet `Name="Dragonair"`, `Card #="181.0"` → `display_name = "Dragonair #181"`.

### C.3 Backend: read the stored `display_name` verbatim

- `models/inventory.py`: `display_name: str | None = None` lives on
  `RawInventoryItem` and `GradedInventoryItem` (and their `Enriched*` subclasses),
  set once at import/relink time.
- `routers/inventory.py`, `_enrich`: when `card is None`, the response carries the
  item's stored `display_name` as-is (`data.get("display_name")`); when `card is
  not None` it is forced to `None` because the catalog `card.name` is authoritative.
  No parsing happens here — it is a straight passthrough of a field that was
  already sanitized at write time.
- `"display_name"` is in `_CUSTOMER_ITEM_FIELDS` (`inventory.py:64`). It carries
  only name+number and no cost/location/free-text, so it is safe to expose.

### C.4 Frontend precedence (`frontend/lib/inventory.ts`) — unchanged from the original design

`ItemBase` carries `display_name?: string | null`. `itemTitle`:

```
sealed        -> item.product_name
otherwise     -> item.card?.name ?? item.display_name ?? item.card_id ?? item.item_id
```

`display_name` ranks above `card_id` (more human) and above the `item_id` ULID (the
original bug). The ULID is the last resort only when nothing else exists. The
frontend does no parsing at all — it only ever reads the field the backend sent.

### C.5 MCP `toCard`: reads the SAME stored field, not a local re-derivation

The original proposal had MCP parse `row.notes` locally with a second,
TS-language copy of the parsing rule — accepted at the time as an existing class
of cross-language duplication (mirroring `card_text.py` ↔
`dynamodb-repository.ts` for normalization and shard count). **That duplication,
and the risk it carried, is retired by the shipped design.** MCP reads DynamoDB
rows directly, so it sees the same `display_name` attribute the backend
materialized at import; `toCard` uses it verbatim:

```
name = meta ? meta.name : (row.display_name ?? cardId ?? String(row.item_id))
```

MCP never touches `row.notes` for naming purposes. Both customer surfaces
(backend `_enrich`, MCP `toCard`) now read **one** stored field instead of each
maintaining its own parser — the "accepted cross-language duplication" risk this
RFC originally flagged for C.5 no longer applies to display-name derivation (the
normalization/shard-count duplication elsewhere is unrelated and still stands).

### C.6 Housekeeping — done

`dynamodb-repository.ts`'s header comment documented the pre-Database-Redesign
`SK=CARD#<id>#RAW#...`/`SK=CARD#<id>#GRADED#...` schema; the real inventory SK is
`ITEM#<item_id>` (confirmed against `dynamodb.py`'s `put_inventory_item`). The
comment has been corrected (comment-only) to describe the current PK/SK layout and
the fact that `toCard` reads a stored `display_name` (C.5 above).

---

## D. Relink strategy recommendation — **Option C (review toolchain), not re-import**

Two candidates from the diagnosis:

**Option C — relink existing NULL rows via `build_review.py` →
`apply_review_decisions.py`.** Read-only `Scan` builds an HTML triage page; the human
accepts/sets/rejects; the applier writes **only** `card_id` / `needs_review` / GSI1
keys via `update_item`, dry-run by default, fail-closed per row, with a language gate
and a table-binding guard. It already targets exactly the `needs_review=True` /
NULL-card_id queue, and its predictor (`CatalogIndex` + `predict_card`) is the strong
matcher (normalized name+number, core-name, set inference, fuzzy, confidence bands).

**Option E — full idempotent re-import** (`run_import(..., force_replace=True)`;
single-flight lock + load-then-swap generation replace in `services/dynamodb.py`).

**Recommendation: Option C.** Rationale:

1. **Non-destructive.** `run_import` refuses on existing business data and, with
   `force_replace=True`, **replaces every import-owned record** — discarding anything
   written or corrected since the first import (its own `ExistingBusinessDataError`
   docstring says so). Row-based records also get **fresh ULIDs** each run, so every
   `item_id` changes — breaking any stored reference. The frozen balance-sheet baseline
   and any manual fixes would be at risk. Option C touches one attribute per item.
2. **Purpose-built.** The review/apply/backfill toolchain and its tests
   (`backend/tests/scripts/test_build_review.py`, `test_apply_review_decisions.py`,
   `test_backfill_language.py`, `test_language_recall.py`) exist precisely for this.
3. **Already has the good matcher.** Relinking benefits from `predict_card`'s fuzzy +
   set inference and a human confirm — safer than the importer's conservative
   auto-linker for the genuinely ambiguous rows.
4. **Small volume.** ~300 available items, most already predicted HIGH/MEDIUM; a
   bounded, one-sitting triage.

Use **Option B (matcher fix)** to make *future* imports link correctly and to shrink
the review queue; use **Option E only** if the owner deliberately wants to rebuild
from a corrected sheet and accepts the wholesale replace. Sequence: land B → run
`build_review` against the live table → triage → `apply_review_decisions --apply`.
(`backfill_language.py` is a separate, already-run concern; only relevant if new JP
rows appear.)

---

## E. Owner-decision questions (each with options + recommendation)

**E1. Should sealed items (`kind=sealed`, e.g. booster packs) be customer-visible?**
> **DECIDED (binding): HIDE sealed — cards-only surface.** The owner overrode the
> recommendation this section originally made (quoted below for rationale only).
> **Shipped:** `"sealed"` is removed from `_CUSTOMER_KINDS` (backend
> `inventory.py:37`) and from `PUBLIC_KINDS` (MCP `dynamodb-repository.ts:39`).
> RED tests assert a `kind=sealed` item is excluded from customer results on
> both paths (`test_search_excludes_sealed_items_from_customer_results` in
> `backend/tests/routers/test_inventory.py`; `"excludes sealed products from
> the customer-facing projection (cards-only surface, RFC 0001)"` in
> `mcp-server/src/__tests__/dynamodb-repository.test.ts`), and both are green.

Before the decision, `_CUSTOMER_KINDS` included `sealed` in both backend
(`inventory.py`) and MCP (`PUBLIC_KINDS`, `dynamodb-repository.ts`). Sealed items
already rendered by their `product_name`, so they were not themselves the ULID
"junk" the owner saw — that was unmatched singles (fixed by section C).
- (a) Keep sealed visible — they are real sellable product.
- (b) Hide sealed from customer search (remove `"sealed"` from both sets).
- **Original recommendation: (a) keep them** — the "booster packs instead of
  cards" complaint is resolved by the display fix (C) removing the ULID noise.
  **The owner instead chose (b):** the search surface is cards-only regardless
  of whether sealed product renders cleanly. `toCard` in
  `dynamodb-repository.ts` still has a `kind === "sealed"` branch (dead code on
  the customer path now that `PUBLIC_KINDS` excludes it upstream); left in
  place as harmless and reusable if an admin-only surface needs it later.

**E2. Is the ~80% sold ratio genuine history or importer over-flip?**
The importer flips an item to sold only when **both** `Sold` and `Date Sold` are
present (`import_singles` line 337-345). Per shard: 120 sold / 30 available.
- (a) Genuine — the sheet really records mostly-sold history.
- (b) Over-flip — the importer misreads a "Sold" column (e.g. a lingering value).
- **Recommendation: investigate before acting.** Spot-check a shard's sold rows
  against the actual spreadsheet's `Sold`/`Date Sold` columns. If the sheet is truly
  mostly historical sales, it is genuine and no code changes — available stock is just
  small (~300), which independently makes pages look sparse. Do not re-import to "fix"
  this without owner confirmation, since re-import re-applies the same sheet logic.

**E3. Relink vs re-import for production.**
- **Recommendation: relink (Option C)**, per section D — non-destructive, surgical,
  preserves corrections and item_ids. Reserve re-import for a deliberate rebuild from a
  corrected sheet with `force_replace=True`, fully understanding the wholesale replace.

---

## F. Test plan — AS BUILT (RED first, per CLAUDE.md TDD)

The original test list below was written against the read-time notes-parsing
design (section C's original text) before implementation. It is replaced here with
the test plan as it actually shipped, across three Council revisions; all listed
tests exist and are green (BE 541 / FE 158 / MCP 71 total, including these).

### F.1 Backend matcher & display-name materialization — `backend/tests/services/test_spreadsheet_import.py`, `backend/tests/services/test_card_text.py`

Catalog index built through the production `build_catalog_index` (no test may pass
by hand-normalizing a key the real code doesn't).

Matcher normalization and conservative-linking tests:
`test_match_card_links_number_with_float_artifact`,
`test_match_card_links_slash_form_number`,
`test_match_card_normalizes_name_punctuation`,
`test_match_card_ambiguous_multiset_stays_unlinked`,
`test_match_card_slab_set_inference_links_unique`,
`test_import_singles_links_float_artifact_row`,
`test_build_catalog_index_keys_are_normalized`,
`test_match_card_single_hit_rejected_when_set_text_contradicts`,
`test_match_card_single_hit_links_when_set_text_agrees`.

Qualifier/variant guard (as-built addendum, B.3) — added on both match branches so
a variant is never silently linked to its base card's price:
`test_match_card_variant_qualifier_not_autolinked_to_base`,
`test_match_card_finish_only_normalization_still_links` (finish-only drop still
links — only a qualifier drop blocks),
`test_match_card_variant_qualifier_not_autolinked_via_narrowed_branch`,
`test_match_card_finish_only_narrowed_branch_still_links`.

Display-name materialization (section C, as-built):
`test_import_singles_materializes_display_name_from_structured_identity`,
`test_import_singles_stores_no_display_name_when_name_is_blank`,
`test_import_singles_matched_row_still_stores_structured_display_name`,
`test_import_slabs_materializes_display_name_from_structured_identity`,
`test_import_consignments_materializes_display_name`, and in
`test_card_text.py`: `test_format_display_name_composes_name_and_number`,
`test_format_display_name_returns_none_without_a_structured_name`,
`test_format_display_name_keeps_the_name_when_the_number_is_absent_or_junk`,
`test_format_display_name_bounds_the_composed_length`.

Regressions that stayed green throughout (JP English-only gate untouched):
`test_english_single_still_matches_the_catalog_exactly_as_before`,
`test_match_card_itself_refuses_a_non_english_language`,
`test_japanese_single_is_never_matched_to_an_english_catalog_card`,
`test_japanese_slab_marked_only_in_the_set_column_is_still_gated`,
`test_daily_sync_never_writes_an_english_price_onto_a_japanese_item`.

### F.2 Backend router — `backend/tests/routers/test_inventory.py`

- `test_search_result_exposes_materialized_display_name_when_unmatched` — an
  available raw item with `card_id=None` and a stored `display_name` (from import)
  → the response item carries that `display_name` verbatim.
- `test_search_result_does_not_leak_notes_cost_or_location` — the response item has
  **no** `notes`, `cost_basis`, `location`, `tcg_url` keys (allowlist guard).
- `test_search_result_display_name_is_none_when_item_stored_none` — no stored
  `display_name` (e.g. a genuinely nameless row) → response field is `None`, not
  fabricated from anything else.
- `test_matched_item_prefers_catalog_name_over_display_name` — when `card` is
  present, `_enrich` forces `display_name` to `None` and the catalog name drives
  display.
- `test_search_excludes_sealed_items_from_customer_results` — E1: a `kind=sealed`
  item is excluded from `/inventory/search` results entirely.

### F.3 Frontend — `frontend/lib/__tests__/inventory.test.ts` (`describe('itemTitle')`)

- `falls back to display_name when card and card_id are null` — asserts the
  `card?.name ?? display_name ?? card_id ?? item_id` precedence.
- `prefers display_name over the item_id ULID`.
- `still prefers the catalog name over a present display_name`.
- The pre-existing "falls back to the item_id" test is retained, updated for the
  new precedence (no `display_name` present → still `item_id`).

### F.4 MCP — `mcp-server/src/__tests__/dynamodb-repository.test.ts` (`describe('listCards')`)

- `uses the stored display_name when the catalog is missing and card_id is null`.
- `uses the stored display_name for a graded slab too`.
- `falls back to the item_id when there is no display_name, never parsing notes`.
- `ignores notes entirely even when they look like an identity segment` — the key
  privacy-guard test: a row whose `notes` reads like an identity string but has no
  stored `display_name` must NOT have that identity derived from notes at read time.
- `prefers the catalog name over a stored display_name for a matched item`.
- `excludes sealed products from the customer-facing projection (cards-only
  surface, RFC 0001)` — E1.
- The prior "reads the stored JP language for a sealed product" test was removed;
  a sealed item never reaches `listCards`'s customer projection at all now (see
  the removal note left in place in the test file, just above the sealed-exclusion
  test).

### F.5 Non-test cleanup (verified by lint/existing tests, no new test)

- `core_name` / `number_keys` / `sets_agree` moved into `card_text.py`;
  `build_review.py` imports them instead of defining its own. Existing
  `test_build_review.py` stayed green.
- `apply_review_decisions.DecisionApplier._write_card` writes `display_name`
  alongside `card_id`/`needs_review`/GSI1 keys on relink, covered by
  `test_card_accept_materializes_display_name_from_the_decision`
  (`backend/tests/scripts/test_apply_review_decisions.py`).
- `dynamodb-repository.ts` stale header comment fixed (C.6) — comment-only, this
  documentation pass.

---

## Risks & Mitigations

- **Over-linking to the wrong set.** Mitigated by the unique-survivor rule (B.3),
  the qualifier/variant guard on both match branches, and the F.1 matcher tests;
  ambiguous or variant-dropped rows stay NULL and route to human review.
- **Leaking internal data via display name.** Mitigated structurally, not just by a
  parsing rule: `display_name` is computed once at import time from structured
  `Name`/`Card #` columns only (`format_display_name`), never from `notes`, so
  there is no read-time parser that could ever promote a later notes segment
  (cost/consignor/location) onto the wire. Covered by F.2's leak test and F.4's
  "ignores notes entirely" test.
- **Regressing the JP English-only gate.** Mitigated by keeping the language gate first
  and untouched, and by the F.1 regression set.
- **Relink writing bad ids.** `apply_review_decisions.py` is dry-run by default,
  validates each id against both the catalog and the item's own preserved text, gates
  language, and binds the block to the table — all pre-existing.
- **Cross-language duplication (Python parse vs TS parse).** For *display-name
  derivation* specifically, this risk is **retired** by the as-built design (C.5):
  both surfaces read one stored field, so there is nothing left to keep in sync.
  Duplication elsewhere (name/number normalization, `INVENTORY_SHARD_COUNT`)
  between `card_text.py` and `dynamodb-repository.ts` is unrelated to this RFC and
  still stands, unchanged.

## Open Questions

- Should `import_singles` attempt trailing-name-token set inference in the importer, or
  leave all multi-set singles to the review page? (Leaning: leave to review page for a
  minimal first cut; revisit if the queue is too large.) — **TBD**, unchanged by
  this RFC's implementation.
- E1 (sealed visibility) and E3 (relink vs re-import) are resolved by the owner
  decisions at the top of this document and are shipped. E2 (sold ratio) is
  deferred per the owner's decision, not investigated as part of this RFC.

---

## Follow-ups (non-blocking, tracked here for a future cleanup pass)

The Council passed this RFC's implementation with the following **cosmetic,
non-blocking** residuals — none affect correctness or security, and none were
made "must-fix" by any advisor, but they're recorded here so they aren't lost:

- `format_display_name` (`card_text.py`) does not explicitly strip control or
  bidi-override characters from the composed name before truncating/returning it.
- `EnrichedRawInventoryItem` and `EnrichedGradedInventoryItem`
  (`models/inventory.py`) each redeclare `display_name: str | None = None`, which
  is already inherited from `RawInventoryItem`/`GradedInventoryItem` — redundant,
  not incorrect.
- `_DISPLAY_NAME_MAX` (80-char) truncation can land mid-token and leave a
  dangling `#` with no digits after it if the cut falls right after the
  separator.
- Promo-set / qualifier-token matching in `_dropped_qualifier` /
  `sets_agree` casefolds but doesn't otherwise normalize promo-set naming
  variants beyond what `normalize_name` already does.

None of these were fixed here — this is a documentation pass, not a code change —
and they belong to a future `code-writer` cleanup pass, not this RFC.

---

## Appendix — key code references (as-built, this branch)

- `backend/src/merlins_collection/services/spreadsheet_import.py` — `_match_card`
  (line ~270), `_dropped_qualifier` (~334), `import_singles` (~391), `import_slabs`
  (~443), catalog index build via `build_catalog_index` in `run_import` (~1135).
- `backend/src/merlins_collection/services/card_text.py` — `normalize_name`,
  `normalize_number`, `strip_float_artifact`, `parse_source_text`, `SourceText`,
  `build_catalog_index`, `core_name`, `number_keys`, `sets_agree`, and
  `format_display_name` (~370) — the single source of the materialized
  `display_name`.
- `backend/src/merlins_collection/models/inventory.py` — `display_name` field on
  `RawInventoryItem`/`GradedInventoryItem` and their `Enriched*` counterparts
  (~line 152, 164, 229+).
- `backend/src/merlins_collection/routers/inventory.py` — `_CUSTOMER_KINDS`
  (line 37), `_CUSTOMER_ITEM_FIELDS` (line 51), catalog-join filters, `_enrich`
  (line ~185, reads stored `display_name` verbatim).
- `backend/scripts/apply_review_decisions.py` — `DecisionApplier._write_card`
  (~561) writes `display_name` on relink via `format_display_name`.
- `frontend/lib/inventory.ts` — `itemTitle`, `ItemBase` (unchanged precedence
  from the original design: `card?.name ?? display_name ?? card_id ?? item_id`).
- `mcp-server/src/dynamodb-repository.ts` — header comment (top of file, fixed
  this pass), `PUBLIC_KINDS` (line 39, `sealed` removed), `toCard` (reads
  `row.display_name` verbatim, no notes parsing).
- Toolchain: `backend/scripts/build_review.py` (`CatalogIndex`, `predict_card`),
  `apply_review_decisions.py` (`DecisionApplier`), `backfill_language.py`.
