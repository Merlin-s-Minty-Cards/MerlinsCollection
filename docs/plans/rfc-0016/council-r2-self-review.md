# Council r2 — self-review (not an independent pass)

Written 2026-08-24, by the same session that implemented GREEN. This is a
systematic walkthrough of `council-r1-verdict.md`'s checklist against the
actual diff, done as part of the TDD skill's required post-change
adversarial-review step. **It is not a substitute for an independent
re-review** — see `progress.md`'s open Council r2 item. Recorded here so a
later independent review has a concrete self-assessment to check (and
disagree with) rather than starting from nothing.

## Checklist items, verified one by one

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | FATAL: MCP `item_id` | DONE (prior commit, this session) | `mcp-server/src/__tests__/item-id-field.test.ts` (real MCP client/server, not mocked); `test_search_result_item_id_hydrates_in_display_card` traces producer→consumer |
| 2 | Shared visibility predicate | DONE | `services/customer_visibility.py::is_customer_visible`, called by both `routers/inventory.py::customer_visible_items` and `bedrock.py::_hydrate_item`; `test_display_ownership.py` (7 tests) |
| 3 | Price derivation via `_display_price`'s logic | DONE (mirrored, not imported — circular-import constraint, documented in `_hydrate_item`'s docstring) | `test_display_price_derivation.py` (4 tests) |
| 4 | Error isolation | DONE (`_hydrate_item` never raises) | `test_display_error_isolation.py` (4 tests) |
| 5 | `cert_image_url` dropped | DONE (backend model + frontend type) | `test_display_hydration.py`, `test_display_security.py` |
| 6 | `json.dumps`, not f-strings | DONE (all tool-result paths) | `test_display_tool_json.py` (6 tests), `test_display_security.py`'s JSON pair |
| 7 | Tri-state `open` write-only | **Dissolved** by decision 23 — no incremental panel state exists to desynchronize | `test_display_panel_has_no_open_field` |
| 8 | close-then-add invisible card | **Dissolved** by decision 23 — no `add_to_panel` exists | N/A |
| 9 | Panel contents told to model (reduced) | DONE — context injection at request start + `set_display` echo | `test_display_panel_context_injection.py` (3), `test_display_panel_visibility.py` (3), `test_set_display_composes_remove_operation` |
| 10 | 12-turn ceiling vs 30s timeout | **Resolved** by decision 23's turn collapse, not per-call budgeting; `_MAX_TOOL_TURNS` reverted to 5 | `test_max_tool_turns_stays_at_5`, `test_display_sequences_stay_at_five_tool_turn_budget` |
| 11 | No work ceiling | DONE — dedupe+cap before I/O (restore and `set_display`), per-request hydration-block ceiling, artifacts capped | `test_display_work_ceiling.py` (5 tests) |
| — | `set_display` collapse itself (decision 23) | DONE — 7-tool surface, `set_panel` replaces 5 methods | `test_set_display_state_machine.py` (11 tests), `shared/tool-contract.json` (verified pre-existing) |
| — | Frontend: no `open` prop, empty-cards gating, `cert_image_url` removed | DONE | Full frontend suite (1020/1020) including `DisplayPanel.test.tsx`, `ChatPanel.test.tsx` |

## Four-lens sweep across the full diff (logic / security / chaos / bloat)

Judged the delta against the pre-GREEN state, not against a hypothetical
ideal — per `adversarial-review`'s own rule.

**Logic.** Traced every branch `_hydrate_item` can take (raw+catalog,
raw+no-catalog, graded+catalog, graded+no-catalog, missing item, wrong
visibility, exception mid-hydration) against the test suite; all covered.
`_run_set_display`'s truncation-flag threading (dedupe+cap before hydrating,
but still report truncation to the ALREADY-capped `set_panel` call via an
explicit `input_truncated` override) was the one genuinely subtle piece —
verified against `test_set_display_truncates_at_50_and_returns_notice`
directly rather than trusting the design on paper.

**Security.** `is_customer_visible`'s logic is unchanged (byte-for-byte
transplant, not a rewrite) — verified by re-running every existing consumer
of `customer_visible_items` (routers/inventory.py's search, dashboard
summary; routers/public.py's featured endpoint) via the full 2087-test
backend suite, not just the new display-hydration tests. `_hydrate_item`'s
broad exception catch (`ClientError, ValidationError, AttributeError,
TypeError, KeyError`) is a deliberate trust-boundary choice, logged not
silent, matching existing precedent elsewhere in this codebase
(`catalog_sync.py`, `spreadsheet_import.py`).

**Chaos.** `_DisplayState` is constructed fresh per `chat()` call (no shared
mutable state across concurrent requests); `BedrockChatService` itself is
already per-request (`dependencies.py::get_bedrock_service` is not cached).
No new I/O loops beyond what item 11 explicitly bounds.

**Bloat.** The new `services/customer_visibility.py` module is the minimum
viable extraction given the circular-import constraint — one function, two
constants, same shape as the existing `services/condition_pricing.py`. Grepped
the whole repo for leftover references to the five deleted tools/methods
(`add_to_panel`, `remove_from_panel`, `reorder_panel`, `open_panel`,
`close_panel`, `_DISPLAY_ITEM_TOOLS`) — zero hits.

## Findings surfaced (not silently fixed)

1. **`DisplayedCard.kind` still admits `'sealed'`/`'bulk'`** on both sides of
   the wire — unchanged carry-forward from `council-r1-verdict.md`'s own
   note; still needs a ruling, not a silent removal or a silent leave-as-is.

2. **New: frontend price-precedence is now backwards.** `DisplayPanel.tsx`
   and `ChatPanel.tsx` both compute displayed price as
   `card.current_market_value ?? card.listed_price`. Before this session,
   that was defensible (neither field was condition-adjusted, so either
   order was "a market figure or a fallback"). After item 3, `listed_price`
   is the RESOLVED, condition-adjusted display price (mirroring
   `_display_price`) and `current_market_value` is a separate, potentially
   stale, unadjusted pass-through of the item's stored figure — so the
   frontend now prefers the wrong one whenever both are present. Not fixed
   in this session because no currently-passing test pins the correct
   precedence (fixing it means changing an assertion in
   `DisplayPanel.test.tsx` that predates this remediation, which is a real
   design call — "should the frontend even still read
   `current_market_value` at all" — for the owner or an independent review
   to make, not something to change unilaterally while making RED green).
