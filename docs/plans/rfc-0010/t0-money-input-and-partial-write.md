# T0 — Money inputs accept what a human types, and a batch never half-commits

**RFC:** 0010 §G · **Layer:** full-stack · **Depends on:** — · **Blocks:** T1, T12, and
**the RFC 0009 merge**

## Why this is first

RFC 0009's T-FINAL is re-opened and blocked on this exact defect. Today, a five-slab batch
with `1,300` typed in row 3 leaves **rows 1–2 as real inventory with real purchase
transactions**, the session stuck in `draft`, and the UI reporting *"Nothing was created;
the batch is intact"* — which is false. The operator's natural next move is to press Commit
again, which duplicates rows 1–2.

The owner reported the operator-facing half independently on 2026-08-10: *"typing 1,300 for
cost will break the commit, but typing 1300 is accepted. Both should work."*

## The failure chain, end to end

1. `SlabEntryForm`'s Cost field is free text — `<input aria-label="Cost" inputMode="decimal">`
   (`frontend/components/admin/slabs/SlabEntryForm.tsx:257-263`). `inputMode` hints the
   mobile keyboard; it constrains nothing.
2. Validation is `!cost.trim()` (line 130), so `1,300` and `$40` both pass.
3. `StagingTable` renders the raw string, so `1,300` displays as a correct-looking
   **`$1,300`**. There is no total row. **Zero signal before commit.**
4. `Number("1,300")` → `NaN` → `JSON.stringify` → **`buy_price: null`**
   (`frontend/app/(admin)/admin/slabs/page.tsx:82`).
5. `add_buy_item` only checks `"buy_price" not in body`, so `null` is accepted with a
   **200**. `_GRADED_REQUIRED_FIELDS` covers company/grade/cert_number — a bad *grade* is
   correctly 422'd, a bad *cost* is not.
6. Inside `confirm_buy_session` the per-item loop does `Decimal(str(None))` →
   `InvalidOperation` → **unhandled 500**. The loop has already called
   `put_inventory_item` + `put_transaction` + `put_timeline_event` for every earlier row.
   There is no rollback, and `status` is set to `confirmed` only *after* the loop.

Worst input is the most likely one: four-figure costs are normal for graded slabs.

## Two things rule out the obvious fixes

**`type="number" step="0.01"` is REJECTED.** It was the recommendation on file in RFC
0009's progress table. A native number input does not accept a comma, so `1,300` becomes
un-typeable rather than correct — it satisfies the machine and fails the person who asked.

**`parseFloat` is BANNED for money.** Measured 2026-08-10:

| input | `Number(v)` | `parseFloat(v)` |
|---|---|---|
| `1300` | `1300` | `1300` |
| `1,300` | `NaN` | **`1`** |
| `1,300.50` | `NaN` | **`1`** |
| `$40` | `NaN` | `NaN` |
| `1.2.3` | `NaN` | `1.2` |
| `""` | `0` | `NaN` |

`parseFloat` stops at the separator and returns `1`, and **`1` is not `NaN`**, so it passes
every `isNaN` guard already in this codebase (`outgoing/page.tsx:140`,
`show-prep/page.tsx:133`). Swapping `Number` for `parseFloat` would turn a loud 500 into a
silent $1,299 loss. **That is a worse bug than the one being fixed.**

## Scope

**In:** the shared parser and input component, the slab Cost field, the `add_buy_item`
guard, and `confirm_buy_session` batch pre-validation.

**Out:** every other money field in the admin. They are all `type="number"` today, so none
of them can receive a comma, and rolling `MoneyInput` out to them is **T1**. Do not widen.

## Files

- **Create:** `frontend/lib/money.ts` — `parseMoney`, `formatMoneyInput`
- **Create:** `frontend/components/admin/shared/MoneyInput.tsx`
- **Create:** `frontend/lib/__tests__/money.test.ts`,
  `frontend/components/admin/shared/__tests__/MoneyInput.test.tsx`
- **Modify:** `frontend/components/admin/slabs/SlabEntryForm.tsx` — the Cost field
- **Modify:** `frontend/app/(admin)/admin/slabs/page.tsx` — send the parsed number
- **Modify:** `frontend/components/admin/slabs/StagingTable.tsx` — render the parsed value
  and add a batch total
- **Modify:** `backend/src/merlins_collection/routers/admin/purchases.py` — `add_buy_item`
  guard, `confirm_buy_session` pre-validation
- **Tests:** `backend/tests/test_purchases.py`,
  `frontend/components/admin/slabs/__tests__/SlabEntryForm.test.tsx`,
  `frontend/app/(admin)/admin/slabs/__tests__/page.test.tsx`

## Design

### `parseMoney(raw: string): number | null`

Accepts what a human types; returns **`null`, never a guess**, for anything ambiguous.

| input | result | why |
|---|---|---|
| `1300`, `1300.50`, `.5` | the number | plain |
| `1,300`, `1,300.50`, `12,345,678` | the number | thousands separators stripped |
| `$40`, `$ 1,300`, ` 40 ` | the number | currency symbol and whitespace stripped |
| `40.`, `40.0` | `40` | trailing point is unambiguous |
| `1,30` | **`null`** | not a valid grouping — 3 digits required after a separator |
| `1.2.3`, `1,2,3` | **`null`** | ambiguous |
| `-5` | **`null`** | a cost is not negative. Reject at the parser, not at each caller |
| `abc`, `""`, `"$"` | **`null`** | not a number |
| `1e3` | **`null`** | nobody types this in a price field, and accepting it invites surprises |

Rejecting ambiguity is the whole point: `1,30` must **not** resolve to a plausible wrong
number. Implement by normalising to a canonical string and validating it against a strict
regex, then `Number()` on the result. **Do not call `parseFloat` anywhere in this file.**

`formatMoneyInput(n)` returns the canonical display string (`1300.5` → `"1300.50"`) for the
blur normalisation.

### `MoneyInput`

- A **text** input with `inputMode="decimal"` — never `type="number"`.
- `onChange` gives the caller the raw string *and* `parseMoney`'s result, so the parent can
  disable its action on `null`.
- **Normalises on blur:** `1,300` becomes `1300.00` in the field, so the operator sees what
  will be sent before they commit. This is the signal step 3 of the failure chain lacks.
- Renders an inline, `role="alert"` message when the value is non-empty and unparseable
  ("That isn't an amount I can read — try 1300 or 1,300"), and sets `aria-invalid`.
- Keeps the caller's `aria-label` so existing test queries (`getByLabelText('Cost')`) still
  resolve.

### The frontend call sites

- `SlabEntryForm`: Cost becomes a `MoneyInput`. `submit()` refuses when
  `parseMoney(cost) === null`, with the same messaging shape the blank-cert path already
  uses. The staged row carries the **parsed number**, not the raw string.
- `StagingTable`: renders the parsed value through the shared money formatter and gains a
  **batch total row**. A total is what would have exposed a `NaN` before commit.
- `slabs/page.tsx`: sends `buy_price: r.buy_price` where that is already a number. Keep it a
  **JSON number** — the backend coerces through `str()` to an exact `Decimal`, and sending
  strings is what let the float landmine hide (CLAUDE.md Ops).

### The backend guards

**`add_buy_item` — 422 at add time.** Validation happens at add, not confirm, matching the
RFC 0009 T3 decision (2026-08-08): *a session that swallows a bad item and explodes on
commit loses the whole staged batch.* Reject when `buy_price` is absent, `None`, or not
finite. Accept a JSON number **or** a numeric string — MCP and curl are real clients and
the backend is the last line, not a mirror of one form's habits.

**`confirm_buy_session` — validate every row before writing any.** Walk the staged items,
coerce every money and numeric field, collect failures, and **422 with the offending row
index** before the first `put_inventory_item`. This is the only change that fixes
*partial write* as a class rather than this one trigger, and it is hard to justify deferring
while T11 is being built precisely because the ledger had no correction path.

The raw (non-graded) path must stay byte-identical in behaviour: **a batch that commits
today must still commit.** Its existing tests are the regression gate.

## RED — write these first, show the failing output, wait for confirmation

**`parseMoney` (frontend, ~14 cases):** every row of the table above. Include an explicit
test named for the trap — *`parseMoney` does not use parseFloat: "1,300" is 1300, never 1* —
asserting `parseMoney('1,300') === 1300`. That test is the one a future reader needs.

**`MoneyInput` (frontend, 5):**
1. typing `1,300` and blurring leaves `1300.00` in the field;
2. an unparseable value renders the alert and sets `aria-invalid`;
3. an unparseable value reports `null` to the parent;
4. a valid value reports the number;
5. the caller's `aria-label` reaches the input.

**`SlabEntryForm` (frontend, 3):**
1. **`1,300` produces a staged row with `buy_price: 1300`** — the owner's report, as a test;
2. `$40` produces `40`;
3. `1,30` blocks the add and says why. *(Existing grade-query tests are anchored `/^grade$/i`
   because the form renders both `Grade` and `Grade label` — keep that anchoring.)*

**`StagingTable` (frontend, 2):** a row renders `$1,300.00` for a parsed 1300; the batch
total sums the rows.

**Slabs page (frontend, 2):** commit posts `buy_price` as a JSON **number**; a batch whose
total is shown matches the committed total in the success line.

**`add_buy_item` (backend, 4):**
1. `buy_price: null` → **422**, and no item is added to the session;
2. `buy_price` absent → 422;
3. `buy_price: "1300"` (string) → accepted;
4. `buy_price: 1300` (number) → accepted.

**`confirm_buy_session` (backend, 3):**
1. **a five-item batch with a bad `buy_price` on item 3 creates ZERO inventory items and
   ZERO transactions, and returns 422 naming the row** — this is the partial-write test and
   it is the most important one in the task;
2. the session stays `draft` and its items are intact, so a corrected retry works;
3. a fully valid five-item batch still commits all five (the regression gate).

Run:

```bash
# frontend
cd frontend && npx vitest run lib/__tests__/money components/admin/shared/__tests__/MoneyInput components/admin/slabs "app/(admin)/admin/slabs" --reporter=verbose
# backend
./.venv/Scripts/python.exe -m pytest backend/tests/test_purchases.py -q --tb=short
```

## GREEN — done when

- All of the above pass, plus the pre-existing `test_purchases.py` suite (31 tests at RFC
  0009 T3) is still green.
- `./.venv/Scripts/python.exe -m ruff check backend/src` is clean.
- `npm run lint --workspace=frontend` is clean.

## Manual check before calling it done

Stage three slabs typing the cost as `1300`, `1,300` and `$1,300.50`. Confirm the staging
table shows `$1,300.00`, `$1,300.00`, `$1,300.50` and a correct total, then commit and
confirm three items land with the right costs. Then stage three more with `1,30` in the
middle and confirm the add is refused at the form — the batch never reaches the server.

## Do not

- Do not use `parseFloat`. Anywhere. See the table.
- Do not use `type="number"` on a money field.
- Do not widen to the other money surfaces — that is T1.
- Do not make the parser guess at `1,30`. A silent wrong number is the failure mode.
- Do not send `buy_price` as a string from the slabs page.
- Do not add rollback to `confirm_buy_session`. Validating before the first write is
  simpler and stronger than compensating after a partial one.

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

**T1 — `MoneyInput` everywhere, and the `parseFloat` sites go**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t1-money-input-rollout.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
