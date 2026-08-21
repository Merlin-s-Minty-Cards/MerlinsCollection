# RFC 0012 Progress

| Task | Status | Notes |
|---|---|---|
| A — Layout width | Done | Review clean. Manual visual check not performed (no dev server); pre-existing `npx vitest run` breakage in this checkout noted (`npm test --workspace=frontend` works and was used). |
| B1 — trades.py backend | Done | Review clean after 1 fix round (normalized empty-string card_id to None). Implementer also investigated and ruled out a pre-existing `test_rate_limit.py` flake as unrelated. |
| B2 — IncomingCardForm/trade page frontend | Done | Review clean after 1 fix round (added a page-level Buy-mode graded regression test — the brief's own prescribed test wasn't discriminating). |
| C1 — CosignorPicker + useCosigners | Done | Review clean, no fix rounds needed. |
| C2 — Inventory filter by cosigner | Done | Review clean, no fix rounds. |
| C3 — CardDetailModal assign/unassign | Done | Review clean after 1 fix round (added RFC-mandated split_percent/minimum_price advanced overrides, dropped from the original brief). |
| C4 — Buy/Trade assign + trades.py item_ids fix | Done | Review clean, no fix rounds. |
| Bonus — CosignorPicker unmount-timeout leak | Done | Review clean. Found independently by C3 and C4, fixed centrally rather than left as duplicate per-consumer test workarounds. |
| D — Lesson capture | Done | Wrote a new CLAUDE.md lesson on stale gate-justification comments (escape hatch disabled for a reason later solved elsewhere in the same file, gate never revisited). Committed separately (`1b9dd10` model-selection lesson, `ccd79fd` escape-hatch lesson). |
| Final full-suite run | Done | Backend 1838/1838, frontend 951/951 (95 files) at HEAD `ccd79fd`. |
| Final whole-branch review | Done | 1 Critical + 5 Important findings (all traced to real code, none disputed); 6 Minor findings parked as tracked debt (reviewer's own call: none block merge). |
| Final-review fix wave | Done | Commits `5f7cac5`, `fb3d339`, `3e41641`, `b1def10`. All 6 Critical/Important findings fixed. Backend 1840/1840, frontend 962/962 after. |
| Scoped re-review of fix wave | Done | Clean — all 6 fixes verified PASS (tests genuinely discriminating, CLAUDE.md corrections fact-checked, no scope creep). No further round needed. |

Update this table as each task lands (subagent or executor should flip
"Not started" → "In progress" → "Done", with a one-line note on anything
that deviated from the task file, e.g. a helper function name that didn't
match what the plan guessed).
