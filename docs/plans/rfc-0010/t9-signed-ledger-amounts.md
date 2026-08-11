# T9 — A sale reads `+$40`, a purchase reads `−$200`

**RFC:** 0010 §F.1 · **Layer:** frontend · **Depends on: T8** (same file) · **Blocks:** T10
**Owner report:** plan doc item 9 — *"In Show analytics, there needs to be a +/- for sales and
buys. i.e., sold is +$ and buying a card is -$."*

## Confirmed state

`Transaction.amount` is stored **unsigned**, with direction carried by `type`
(`backend/src/merlins_collection/models/business.py:36-48`, `TransactionType` = `SALE` /
`PURCHASE`). The analytics table renders it through `PriceDisplay value={t.amount}` with no sign
and no direction cue (`frontend/app/(admin)/admin/analytics/page.tsx:120-127`), so a $200
purchase and a $200 sale are visually identical in a column headed "Amount".

## This is a presentation change only

**Do not invert signs in storage.** Every existing aggregate (`summarize_transactions`,
`sell_through_rate`, the show snapshot generator, the dashboard) reads `amount` as a magnitude
and applies direction itself. Making some rows negative would silently change every one of those
numbers, including snapshots already written.

Worth knowing, and recorded in [`follow-ups.md`](follow-ups.md): `Expense.amount` **is** already
signed, negative meaning money came in, matching the source spreadsheet
(`models/business.py:62-66`). So the ledger carries two conventions. T9 makes transactions *look*
like expenses without *being* stored like them; unifying that is a migration, not this task.

## Files

- **Create:** `frontend/components/admin/shared/SignedAmount.tsx`
- **Modify:** `frontend/app/(admin)/admin/analytics/page.tsx` — the transaction table
- **Modify:** `frontend/app/(admin)/admin/history/page.tsx` — the same treatment where it renders
  transaction amounts
- **Tests:** `frontend/components/admin/shared/__tests__/SignedAmount.test.tsx`, plus the
  analytics and history page tests

## Design

`<SignedAmount value={t.amount} type={t.type} />`:

| type | renders | colour |
|---|---|---|
| `sale` | `+$40.00` | mint |
| `purchase` | `−$200.00` | red/amber |
| anything else | `$40.00` | neutral |

**The sign is text, not colour.** Colour alone is not an accessible carrier of meaning, and the
owner reads these on a phone in show lighting. Use the true minus sign `−` (U+2212) rather than a
hyphen for the rendered value — it aligns in a monospace column, which is how this table is set.

**Reuse `PriceDisplay` for the number itself** rather than reimplementing currency formatting;
`SignedAmount` composes the sign and colour around it. Two money formatters is one too many.

**Unknown types fall through to neutral, not to `+`.** The archive is deliberately raw and may
carry a type this component has not been taught; guessing a direction on a money figure is worse
than showing none.

**Trade cash legs.** `is_trade_cash_leg` already exists (`routers/admin/analytics.py`, used at
line 366) and the daily dashboard already excludes them from sell-through. The **archive shows
them by design** — "nothing is filtered out … because the point is to see what was actually
written" — so their sign follows their `type` like any other row. Do not add a special case; if a
cash leg's `type` says purchase, it renders negative, and that is correct.

**Summary tiles.** `Total Sold`, `Total Bought` and `Net Sales`
(`analytics/page.tsx:548-551`) are labelled tiles, not a signed column, so `Total Bought` stays a
positive figure under its own label. **`Net Sales` is the one that should be signed**, because it
genuinely can go either way on a buying-heavy day — and today it renders a bare figure that reads
as profit whichever direction it went.

## RED — write these first, show the failing output, wait for confirmation

**`SignedAmount` (6):**
1. a sale renders a leading `+`;
2. a purchase renders a leading `−`;
3. an unknown type renders neither sign;
4. the sign is present in the **text content**, not only in a class;
5. a sale and a purchase carry different colour classes;
6. `0` renders without a misleading sign.

**Analytics page (3):**
7. a purchase row shows `−$200.00`;
8. a sale row shows `+$40.00`;
9. a negative `Net Sales` renders signed.

**History page (1):**
10. transaction amounts there are signed the same way — one component, both surfaces, so they
    cannot drift.

```bash
cd frontend && npx vitest run components/admin/shared/__tests__/SignedAmount "app/(admin)/admin/analytics" "app/(admin)/admin/history" --reporter=verbose
```

## GREEN — done when

The above pass, pre-existing analytics and history tests pass, and
`npm run lint --workspace=frontend` is clean.

## Manual check

Open a day with both a sale and a purchase. The two must be distinguishable **at a glance and in
greyscale** — screenshot it and desaturate if you are unsure. That is the test the colour-only
version fails.

## Do not

- Do not change stored signs.
- Do not invent a direction for an unknown transaction type.
- Do not carry meaning in colour alone.
- Do not write a second currency formatter — compose `PriceDisplay`.
- Do not special-case trade cash legs. The archive shows what was written.
- Do not sign `Total Bought`; its label already carries the direction.

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

**T10 — One real transaction renders as one line**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t10-transaction-batch-id.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
