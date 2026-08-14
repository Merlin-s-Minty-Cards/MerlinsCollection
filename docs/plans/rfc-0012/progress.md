# RFC 0012 Progress

| Task | Status | Notes |
|---|---|---|
| A — Layout width | Done | Review clean. Manual visual check not performed (no dev server); pre-existing `npx vitest run` breakage in this checkout noted (`npm test --workspace=frontend` works and was used). |
| B1 — trades.py backend | Done | Review clean after 1 fix round (normalized empty-string card_id to None). Implementer also investigated and ruled out a pre-existing `test_rate_limit.py` flake as unrelated. |
| B2 — IncomingCardForm/trade page frontend | Done | Review clean after 1 fix round (added a page-level Buy-mode graded regression test — the brief's own prescribed test wasn't discriminating). |
| C1 — CosignorPicker + useCosigners | Not started | |
| C2 — Inventory filter by cosigner | Not started | blocked on C1 |
| C3 — CardDetailModal assign/unassign | Not started | blocked on C1 |
| C4 — Buy/Trade assign + trades.py item_ids fix | Not started | blocked on C1 |
| D — Lesson capture | Not started | blocked on A, B1, B2, C1-C4 |
| Final full-suite run | Not started | blocked on all above |

Update this table as each task lands (subagent or executor should flip
"Not started" → "In progress" → "Done", with a one-line note on anything
that deviated from the task file, e.g. a helper function name that didn't
match what the plan guessed).
