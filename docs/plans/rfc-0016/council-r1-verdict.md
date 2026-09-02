# Council Verdict — RFC-0016, Revision 1: FAIL

> Migrated verbatim 2026-08-24 from Kiro's
> `.kiro/plans/0001-chat-experience/council/r1/verdict.md` (gitignored,
> tool-local — see `../README.md`'s "Where this came from"). Kiro's process
> convened four separate advisor subagents (contrarian, architect, chaos,
> security) plus a judge; this project's own equivalent is the
> `adversarial-review` skill's four inline lenses. The content below is the
> closed record of that round-1 review and is unchanged from the original —
> do not edit it to reflect progress; track remediation status in
> `progress.md` instead.

## Per-seat summary

- **Contrarian:** OBJECTION — 1 FATAL (F1: no MCP surface ever emits an inventory `item_id`, so display tools fail on every catalogued item) + 4 MAJOR (tri-state `open` not round-tripped; close-then-add produces an invisible/late-reappearing card; panel contents never surfaced to the model, breaking cross-turn remove/reorder; unhandled repository errors 500 a fail-closed route).
- **Architect:** OBJECTION — 3 STRUCTURAL (S1 = Contrarian F1, same root cause; S2: `_hydrate_item` is a third, loosest customer-visibility gate; S3: a fourth price derivation that already disagrees with the other three) + 6 MAJOR the seat itself scoped as non-blocking follow-ups, plus a cross-cutting `set_display` recommendation that is an owner call, not a defect.
- **Chaos:** OBJECTION — 3 blocking MAJOR (the 12-turn ceiling does not fit the deployed 30s Lambda timeout; hydration/restore failures are not isolated from the rest of the request; admitted requests have no ceiling on internal hydration work) + 2 non-blocking MINOR.
- **Security:** OBJECTION — 1 FATAL (`_hydrate_item` checks status only, omitting the kind/location gate both existing customer-visibility boundaries enforce, so any authenticated user can render withheld inventory via `panel_item_ids` or a relayed tool call) + 2 MAJOR the seat itself scoped as non-blocking standalone but required in the same pass + 5 MINOR, several explicitly checked-and-clean.

Four independent gating defects, on four different lanes, converging on the same handful of functions (`_hydrate_item`, `_DisplayState`, and the display-tool dispatch). This is not a close call.

## Master Checklist (FAIL only)

Ordered so prerequisite fixes land first. Items 1-6 all touch `_hydrate_item` / `_DisplayState.__init__` / `_run_display_tool` and should be delivered as one rewrite; items 7-9 are the panel state machine; items 10-11 are the cost/resilience ceiling.

1. **No MCP surface emits an inventory `item_id`; display tools cannot hydrate any catalogued item.** (Contrarian FATAL F1 = Architect STRUCTURAL S1) `CardResult.id` from `search_inventory` is the catalog `card_id`, not the inventory `item_id` the display tools require — `_hydrate_item` point-reads a SK that doesn't exist and every catalog-linked card fails to display. Fix must add a distinct `item_id` to `Card`/`CardResult` (a real, acknowledged MCP change) rather than widening display tools to accept `card_id`, since one `card_id` maps to multiple physical units. Acceptance: an integration test that composes a real `search_inventory` result into a `display_card`/`add_to_display` call and asserts successful hydration — RED for this fix, per Contrarian.

2. **`_hydrate_item` is a third, loosest definition of customer-visible inventory — an authenticated user can render withheld stock.** (Architect STRUCTURAL S2 = Security FATAL-1) Gates on `status == AVAILABLE` alone; both existing boundaries (`customer_visible_items`, MCP `isPublicInventory`) additionally require kind ∈ {raw, graded} and location ∈ {glass, toploader} or `factory_sealed`. Reachable via client-supplied `panel_item_ids` independent of item 1. Fix: extract the per-item predicate from `customer_visible_items` into something both `_hydrate_item` and the router call — a deletion, not new logic. The pinning test (`test_display_ownership.py::test_any_available_shared_inventory_item_can_be_hydrated`) must change with the fix, not be preserved.

3. **A fourth price derivation, already diverging from the other three.** (Architect STRUCTURAL S3) Display renders `current_market_value` (nightly-denormalized) where filter mode renders the live, condition-adjusted `_display_price`; `_hydrate_item` also never applies `apply_condition_adjustment`, so a DMG card's chat price would ship the NM figure once anything reads `CardSummary.market_price`. Fix: hydrate through `CardSummary.from_catalog` + `apply_condition_adjustment` + `_display_price` instead of a local re-derivation.

4. **Unhandled repository/validation errors during hydration crash a route documented as fail-closed.** (Contrarian MAJOR M5 = Chaos MAJOR "restore failure isolation") `_hydrate_item` and the initial `panel_item_ids` restore loop catch neither `ClientError` nor `ValidationError`; both escape as an untyped 500 on a route whose contract is 503-on-overload. A throttle on card 37 of 50 aborts a request that already paid for earlier reads and, if mid-conversation, earlier `converse()` calls. Fix: bound and isolate restore failures — catch repository errors per item, report partial restoration rather than failing the whole request.

5. **Provider-controlled `cert_image_url` is shipped on the customer-facing `/chat` wire.** (Security MAJOR-1) Documented at the model level as admin-only and provider-supplied (scheme-validated, not content-validated). Same projection code as items 1-3 — drop the field until a customer-facing render need exists.

6. **Unescaped string interpolation builds hand-rolled "JSON" tool results from model/client-influenced text.** (Security MAJOR-2) `_run_display_tool`'s error path and `remove_from_panel` both f-string `item_id` into a literal that re-enters the model's context framed as JSON; an `item_id` containing a quote produces malformed structured input inside the "trust this as data" frame the system prompt relies on. Fix: `json.dumps`, not string interpolation, at both call sites.

7. **Tri-state `open` is write-only — explicit close and empty-but-open cannot survive one round trip.** (Contrarian MAJOR M2) The client never sends `open`; the backend re-derives it purely from whether any card survived hydration, so `False` and empty-`True` both degrade to `None` on the next request. An open-but-empty panel or a user's own X-button close is silently discarded by the next unrelated message or the next `add_to_display`. Fix requires a contract change (`open`/`panel_closed` in `ChatRequest`), not a tweak.

8. **`close_display_panel` + `add_to_display` in one request yields an invisible card that reopens a turn late.** (Contrarian MAJOR M3) `add_to_panel`'s auto-open guard checks `panel_open is None`, which is false after an explicit close, so a card added in the same request as a close is appended but not shown — then auto-opens on the *next*, unrelated message. Fix in the same state-machine pass as item 7: `close_panel` must not leave `add_to_panel` able to add contents to a still-closed panel silently.

9. **The model is never told the panel's current contents, so cross-turn `remove_from_display`/`reorder_display` are unreachable.** (Contrarian MAJOR M4) No tool result, system text, or read tool surfaces `panel_cards` back to the model after `__init__` hydrates it; `buildHistory` on the client replays only text bubbles. `reorder_display`'s exact-set-match requirement makes a superset from re-searching insufficient. Fix: inject the panel's current IDs into context at request start (system/tool message) or add a read tool.

10. **The 12-turn ceiling does not fit the deployed 30-second Lambda timeout.** (Chaos MAJOR, escalating the ceiling flagged as "Unresolved" in progress.md decision 6) Twelve executed tool turns is thirteen `converse()` calls; at a plausible ~2.5s/call that alone exceeds 30s, before restore reads, MCP calls, or rate-limit writes — and `BUFFERED` response mode means a timeout after most of the work delivers nothing, while billing for all of it. This is the specific ceiling decision 6 deferred to this Council pass — it must be resolved here, either by lowering the ceiling with per-call budgeting, or by another mechanism that makes the deployed timeout and the turn ceiling compatible.

11. **Admitted requests have no ceiling on internal hydration work.** (Chaos MAJOR + Contrarian's related MINOR note, escalated) `_DisplayState.__init__` does not dedupe `panel_item_ids` before issuing reads (though `add_to_panel` dedupes on the trusted path), and a full/duplicate check on `add_to_display` happens *after* hydration reads, not before — so a single admitted request can drive up to 100 restore reads plus up to 2 reads per tool-use block with no per-request cap. Fix: dedupe initial IDs before I/O, check full/duplicate before hydrating on add, and cap total display-tool blocks executed per request. Extend the cap to the `artifacts` array as well (currently unbounded, unlike `panel.cards`).

## Overruled Findings

- **Architect's `set_display(item_ids)` consolidation recommendation** (cross-cutting recommendation, tied to M1) — not counted as blocking. It contradicts two settled owner decisions (six-tool surface, model-driven `reorder_display`). Per the brief, this is an owner question, not a defect: raised again here as **owner question** — the tool-surface shrink would also dissolve the item-10 turn-ceiling question, so the owner may want to resolve both together, but the current six-tool surface stands unless the owner says otherwise.

  **Resolution (recorded in `progress.md` decision 23): the owner chose this consolidation.** Items 7, 8, and 10 above are dissolved/resolved as a consequence — see `progress.md`'s "Council r1 — summary" section. This verdict file is left unedited as the historical record of what was found; do not implement items 7, 8, or 10 as written above.

## Appendix: Minor Items (non-blocking, filed to `follow-ups.md`)

- Tool-contract classification (which 5 tools MCP registers vs. which 6 the backend owns) is restated in five places, two via positional array slicing that a semantically-empty reorder would break. (Architect M2)
- Four overlapping catalog projections (`models/chat.py::CardSummary` vs. `models/inventory.py::CardSummary`; frontend `DisplayCardSummary` vs. `CardSummary`) — the stated justification (nullable `image_small`, missing `image_large`) doesn't hold up; `image_large` has no reader anywhere. May shrink incidentally once item 3's fix reuses the existing projection. (Architect M3)
- `CardPresentation` extraction landed one level too low: `DisplayPanel.tsx` and `ChatPanel.tsx` each reimplement identical title/condition/price derivations. Two concrete regressions from this: the JP badge disappears for uncatalogued Japanese items in chat (present in filter mode) because `DisplayedCard` carries no `language` field; sealed items show a flat "Sealed" label instead of the mapped "Booster Box"/etc. because `DisplayedCard` carries no `product_type`. (Architect M4; JP badge independently flagged MINOR by Contrarian)
- Wire payload carries several fields nothing reads (`image_large`, `set_id`, `rarity`, unused `market_price`, `finish`) and has no enforceable byte ceiling if a model repeats `display_card` for a large row. Bound response size / trim unread fields. (Architect M5 remainder, Chaos MINOR "buffered response size", Security MINOR "no cap on distinct items hydrated")
- Dead production branch in `routers/chat.py` (`isinstance(result, str)`) shaped entirely by a test double; no real caller returns a string. Three-line deletion. (Architect M6)
- `truncated` is sticky within a request (doesn't clear when cards are later removed) and amnesiac across requests (resets to `False` on every new message even if the panel is still capped). (Contrarian MINOR)
- `reorder_panel([])` on an empty panel reports success — harmless, confirms a no-op. (Contrarian MINOR)
- `max_tokens`/`stop_sequence` stop reasons fall through to a generic 502; `reorder_display` on a 50-card panel is large enough to make truncation newly reachable. (Contrarian MINOR)
- Dead/unreachable branches: `DisplayPanel`'s internal `open !== true` guard (already gated by the parent), and the sealed/bulk hydration branches (unreachable since MCP's `PUBLIC_KINDS` excludes them from search results). (Contrarian MINOR / Architect cross-lane)
- Stale/sold IDs in a restored panel silently disappear with no restoration notice distinct from the 50-cap `truncated` flag. (Chaos MINOR)
- `panel_item_ids` has no shape validation beyond length — moot once item 2 lands, since visibility will gate regardless of input shape. (Security MINOR)

## Re-review scope

FAIL. All four seats must re-review revision 2: **Contrarian, Architect, Chaos, Security.** Every gating item above falls in one of their lanes (items 1-9 span logic/structure/security; items 10-11 are chaos/resilience), and the fixes touch shared code paths (`_hydrate_item`, the panel state machine, tool dispatch) that all four lanes examined.

Adjourned pending revision 2. **As of this migration (2026-08-24), revision 2 has not been implemented yet — RED is written and committed, GREEN is not started.** See `progress.md` for current status.
