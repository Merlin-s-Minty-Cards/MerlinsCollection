# Round 9 — Execution Guide (RFCs 0021–0025)

**Read this before touching any Round 9 task.** It is the working agreement, the
ordering, and the context discipline for the whole batch. Every RFC in this round
points back here rather than repeating it.

**Branch:** `feat/round9-rfcs-0021-0025` (branched from `main` at `9215ca9`).
**All five RFCs land on this one branch.** Do not open a second branch per RFC.

## The owner's working agreement for this round

Stated 2026-09-02, verbatim intent:

- **Speed is the goal, and correctness is the constraint on it.** "The tasks are
  all carried out flawlessly, but excessive thinking and over-engineering is not
  what I want right now."
- **Group work so it tests together.** Fewer, larger verification passes beat one
  suite run per micro-change. Each RFC below is already a testable unit; run the
  suite at RFC boundaries, not after every file.
- **Do not escalate on uncertainty.** CLAUDE.md's rule is binding and it is the
  one most likely to be violated on a long autonomous run: before asking the
  owner anything, **name the specific fact the owner has that you do not.** If
  you cannot name one, decide, write the decision into the RFC's progress file
  with its rejected alternative, and keep going.
- **No code was written the night these plans were made.** Every RFC starts cold
  from `main`.

## Context discipline — this matters more here than usual

This round is five RFCs deep. A session that tries to carry all of it will run
out of window mid-change, which is the single worst outcome available.

CLAUDE.md's "Context usage" section is authoritative and binding. The Round 9
specific rules on top of it:

1. **One RFC per session, at most.** Several RFCs have tasks large enough to want
   their own session (0022's per-page adoption, 0023's language rollout). Prefer
   stopping early to stopping late.
2. **Record the first `<total_tokens>` marker of the session as the baseline.**
   Percent used is `1 - (remaining / baseline)`.
3. **At ~40%** — flag it in one line and offer the two options.
4. **At ~45–50%** — actively drive to a stopping point: land at green, tear down
   anything the session started, update the RFC's `progress.md`, and hand off.
5. **Choose the right handoff shape** (CLAUDE.md spells this out):
   - **Mid-task** — offer `/compact` with a resume prompt continuing the same task.
   - **Between tasks** — do **not** compact. Write the handoff into the RFC's
     `progress.md` and offer a short fresh-session prompt naming the next task and
     that file. The finished task's exploration has nothing to give the next one.
6. **`progress.md` in each `docs/plans/rfc-00NN/` directory is the handoff file** —
   it is tracked, unlike `claude-progress.md`, which is gitignored and rolling.
   **Never cite `claude-progress.md` from tracked source, tests or docs.**

## Execution order and why

| # | RFC | Tasks covered | Depends on |
|---|---|---|---|
| 1 | [0021 — Catalog Hygiene & Scheduled Price Sync](../../rfcs/0021-catalog-hygiene-and-scheduled-sync.md) | catalog junk removal, daily refresh deployment | nothing |
| 2 | [0022 — Universal Admin Inline Editing + Send to Vault](../../rfcs/0022-universal-inline-editing.md) | click-to-edit every table value, send-to-vault button | nothing |
| 3 | [0023 — Card Identity Vocabulary](../../rfcs/0023-card-identity-vocabulary.md) | 18 languages + manual override, finish rework, TCGplayer links per language | **0022** (the language/finish overrides are edit surfaces) |
| 4 | [0024 — Acquisition Economics & Transaction Editing](../../rfcs/0024-acquisition-economics-and-transaction-editing.md) | manual transaction edits + detail, market/percent on deal rows, price paid on selected items | nothing hard; easier after 0022 |
| 5 | [0025 — Customer Inventory Sticker Pricing](../../rfcs/0025-customer-sticker-pricing.md) | sticker price on the customer page, remove Est. value widget | nothing |

**0021 first** because it is backend + infra only and touches nothing the other
four touch — it can be verified and forgotten. **0022 before 0023** because
0023's whole point is that an admin can hand-correct a language or a finish, and
0022 builds the mechanism that makes that a one-click edit instead of four new
bespoke forms. **0025 last** because it is the smallest and because it changes what
customers see, so it should land on a branch that is otherwise already green.

If a session must reorder, 0021, 0024 and 0025 are independent of everything and
can move freely. Only 0022 → 0023 is a real ordering constraint.

## Cross-RFC seams — behaviours no single RFC fully describes

Found by the adversarial pass over the plan set, 2026-09-02. **Each of these is a
behaviour that emerges only when two RFCs are both in.** Whichever lands second
owns it; check this list before closing an RFC out.

| # | Seam | What the second RFC must do |
|---|---|---|
| 1 | **0022 × 0025 — a sticker cell becomes a customer-visibility switch.** 0022 makes `sticker_price` and `status` click-to-edit on six tables; 0025 makes "no sticker" and "not available" both mean *hidden from the storefront*. | The undo toast for a **cleared** sticker, and for a status leaving `available`, reads **"Removed from the customer site · Undo"** — not the generic field name. Prep Queue's existing "Sticker price cleared, row stays" message must say both things. |
| 2 | **0022 × 0023 — `finish_attributes` is a LIST.** 0022's totality test demands every column carry an `edit` spec or a reason; a list does not fit `select`. | 0022 ships a **`multiselect`** `EditSpec` type (with `allowCustom`) for exactly this. 0023's column uses it. Do not let 0023 bolt a second editing mechanism onto one column. |
| 3 | **0022 × 0024 — the `cost_basis` skip becomes the COMMON case.** Once `cost_basis` is inline-editable, an admin correcting the item directly breaks the equality guard on 0024's ledger→item sync. | `cost_basis_skipped_reason` is rendered as plain information ("changed by hand since; left alone"), never as an error. |
| 4 | **0021 × 0023 — the purge's "unknown language" cohort.** 0021 reports rather than deletes ids whose language prefix it does not recognise; 0023 teaches it 16 more. | Nothing, if 0021's split is built as specified. The split is what makes the two RFCs safe in either order — **do not "simplify" it back to `parse_card_id(...) is None`.** |
| 5 | **0023 × 0025 — an `OTHER`-language item has no catalog price.** 0025 makes the customer price the sticker, which a hand-valued `OTHER` item can perfectly well have. | Nothing. Noted because the natural assumption ("unpriceable ⇒ invisible") is wrong after 0025: an `OTHER` item with a sticker is a legitimate storefront card. |

## Standing rules that apply to every task in this round

Pulled forward because they are the ones this round is most likely to trip:

- **TDD, outside-in.** RED (failing test, stop, confirm) → GREEN (minimal) →
  REFACTOR. Never combine phases.
- **Money never goes through `parseFloat`, and a money input is never
  `type="number"`.** `parseMoney` / `MoneyInput` / `InlineEditCell type="money"`.
  `parseMoney('0')` is `0` — test `=== null`, never falsiness.
- **Dates go through `frontend/lib/dates.ts`.** Never `new Date()` on a date-only
  string; never `toISOString()` for "today".
- **A card is never identified by name alone** — image, name and price, in pickers
  *and* in already-selected rows. No hover may carry information.
- **Never write a bare `float` to DynamoDB.** When testing a money path, send a
  JSON **number**, which is what the frontend actually sends.
- **Every admin control gets `vault-field`** or it renders green-on-white.
- **Missing values sort LAST in both directions; an unknown sort field or filter
  is a 422, never a silent no-op.**
- **A fetch-once admin dropdown hook must gate on `api.isAuthenticated` and put it
  in the effect's dependency array.** A hook with `[]` ships permanently empty on a
  real fresh page load and no jsdom test can see it.
- **Verify the built artifact, not the source**, for anything about packaging,
  CDK tokens, or file resolution.

## Test commands (this clone is the WSL layout)

```bash
backend/.venv/bin/python -m pytest backend/tests -q --tb=short
npm test --workspace=frontend
npm test --workspace=mcp-server
npm test --workspace=infra
backend/.venv/bin/python -m ruff check backend/src
cd frontend && npm run lint
```

`bash scripts/run-tests.sh {all|backend|frontend|mcp}` encodes the interpreter
resolution and fails loudly rather than running zero tests.

## Closing the round out

After the last RFC lands: `sync-docs`, then `pr-description`. CLAUDE.md's admin
tables (the sidebar table, the Buy/Sell/Trade section, the customer-price
sections) all change in this round — `sync-docs` is not optional here.
