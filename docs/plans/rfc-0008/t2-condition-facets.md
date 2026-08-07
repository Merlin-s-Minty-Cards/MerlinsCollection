# T2 — `LP+` / `LP-` must reach the condition filter

**RFC:** 0008 §B (issue #1) · **Layer:** backend only · **Depends on:** nothing
**Files:** `backend/src/merlins_collection/routers/inventory.py`

## The bug

`GET /inventory/facets` builds its condition list from the bare tier only
(line ~357):

```python
if hasattr(item, "condition"):
    conditions.add(item.condition.value)   # NM/LP/MP/HP/DMG — modifier discarded
```

`condition_modifier` is a **separate stored field** (`ConditionModifier`: `"+"`,
`"-"`, `None`) and never gets combined in. So the endpoint structurally cannot
emit `LP+` or `LP-`, no matter what's in stock.

`FilterPanel.tsx:135-151` renders whatever `facets.conditions` contains — so the
frontend needs **no change** once the backend emits the combined strings. It
deliberately does *not* read the `CONDITION_OPTIONS` constant, because the facet
list is supposed to reflect actual stock.

## The fix

Two backend changes.

### 1. Facets emit the combined display string

Combine tier + modifier into the display form (`LP+`, `LP`, `LP-`) using the same
convention as `normalize_condition` / the frontend's `formatCondition`.

Emit a value **only when at least one available item actually has that grade** —
that's the whole point of a facet. Do not pad the list out to all seven options;
that's what `CONDITION_OPTIONS` is for and it belongs to the admin editor.

**Sort order matters.** `sorted()` gives you `LP, LP+, LP-` — alphabetical, and
wrong. The owner-facing vocabulary order is best-to-worst:

```
NM, LP+, LP, LP-, MP, HP, DMG
```

Sort by an explicit rank list matching `frontend/lib/constants.ts` `CONDITION_OPTIONS`.
A value not in the rank list (shouldn't happen) sorts last rather than crashing.

### 2. `/inventory/search?condition=` accepts the combined form

Today the param is typed `Condition | None` — a bare-tier enum, documented as
"the whole tier including LP+/LP-" (line ~204). That semantic stays as the default,
but the param must now also accept `LP+` and narrow to exactly that grade.

- Change the param type from `Condition` to `str` and parse it yourself, mirroring
  the admin's `_parse_condition_query` (`routers/admin/inventory.py:863-876`) —
  **read that function and match its behaviour**, don't invent a second dialect.
- Bare tier (`LP`) → matches `LP`, `LP+`, and `LP-` (unchanged, don't regress this).
- Combined (`LP+`) → matches only tier `LP` with modifier `+`.
- Unparseable input → **422**, not a silent empty result.

**Do not** add a combined `"LP+"` member to the `Condition` enum. Storage is always
two fields. That exact mistake was the Round 1 bug (see CLAUDE.md).

## RED — write these first, confirm they fail, then stop

1. Inventory contains one `LP`+`+` item → `/inventory/facets` `conditions` includes
   `"LP+"`. Fails today.
2. Inventory contains `LP`+`+`, `LP`+`None`, `LP`+`-` → all three of `LP+`, `LP`,
   `LP-` appear as distinct options. Fails today.
3. Facet ordering is `NM, LP+, LP, LP-, MP, HP, DMG` (subset of, in that order) —
   **not** alphabetical. Fails today.
4. No `LP+` item in stock → `"LP+"` is absent from facets. Passes today; guards
   against "just return all seven".
5. `/inventory/search?condition=LP%2B` returns only the `LP+` item, not the plain
   `LP` one. Fails today.
6. `/inventory/search?condition=LP` still returns all of `LP+`, `LP`, `LP-`.
   Passes today — regression guard, the important one.
7. `/inventory/search?condition=ZZ` → 422.
8. Graded items are still excluded whenever `condition` is set (existing rule).

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "facet or condition"
ruff check backend/src
```

## Done when

- All eight green, existing condition tests still green.
- No frontend file was modified. If you found yourself editing `FilterPanel.tsx`,
  the backend fix is incomplete — the panel already renders whatever it's given.
