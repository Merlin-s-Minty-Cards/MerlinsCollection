# T10 — One real transaction renders as one line

**RFC:** 0010 §F.2 · **Layer:** backend + frontend · **Depends on: T9** · **Blocks: T11**
**Owner report:** plan doc item 10 — *"single transactions can be grouped together with details
regarding the transaction. For example one line on that could say purchase -$200 and contain
multiple cards which were purchased in a singular transaction."*

## Confirmed root cause: there is no key to group by

`Transaction` (`backend/src/merlins_collection/models/business.py:36-48`) carries `trade_id` — so
**trade legs can already be grouped** — but nothing equivalent for a sale or a buy. And the
confirm paths write one row per item:

| path | line |
|---|---|
| `confirm_buy_session` → `repo.put_transaction(txn)` per item | `routers/admin/purchases.py:328` |
| `confirm_sale_session` → `repo.record_sale(txn)` per item | `routers/admin/sales.py:292` |
| trade confirm → `record_sale` / `put_transaction` | `routers/admin/trades.py:762, 820, 864, 887` |

So a five-card purchase is five independent rows sharing only a `date` and a `payment_method`.
There is nothing to group by until this task adds it.

**T11 depends on this.** Voiding one leg of a five-card sale the operator thinks of as *one*
transaction is a trap; "void the whole transaction" needs a transaction to point at.

## Files

- **Modify:** `backend/src/merlins_collection/models/business.py` — `batch_id`
- **Modify:** `backend/src/merlins_collection/routers/admin/purchases.py`,
  `.../sales.py`, `.../trades.py` — write it
- **Modify:** `frontend/app/(admin)/admin/analytics/page.tsx` — group the table
- **Tests:** `backend/tests/test_purchases.py`, `test_sales.py`, `test_trades.py`,
  `frontend/app/(admin)/admin/analytics/__tests__/page.test.tsx`

## Design

### The field

```python
class Transaction(BaseModel):
    ...
    trade_id: str | None = None
    # The session that produced this row: buy_id, sell_id or trade_id. Lets a
    # five-card purchase render as ONE line instead of five unrelated ones.
    # None on every row written before this field existed, and deliberately NOT
    # backfilled — see the task doc for why a (date, payment_method) heuristic
    # is refused.
    batch_id: str | None = None
```

Optional with a `None` default, so **every existing row validates unchanged**. No key layout
change: it rides on the existing `TXN#<YYYY-MM>` rows, and `_txn_keys` is untouched.

### Writing it

Each confirm path stamps the session id it already holds — `buy_id`, `sell_id`, `trade_id`. For
trades, `batch_id = trade_id`: the trade *is* the transaction, and stamping both means the
grouping works without the frontend needing to know that trades are special.

Check `_serialize` handles it (it will — it is a plain string) and confirm the field survives the
round trip in the test, since these routers persist **raw request JSON** in places and that is
where the float landmine lived (CLAUDE.md Ops).

### Grouping — on the client

`GET /admin/transactions` keeps returning rows exactly as today. It is deliberately a raw
archive: *"nothing is filtered out, trade cash legs included, because the point is to see what
was actually written"* (`routers/admin/analytics.py`). Nesting it server-side would break that
contract for every other reader to serve one view's layout — see the RFC's Alternatives.

The analytics transaction table groups by `batch_id`:

```
▸ PURCHASE   Aug 10   −$200.00   5 cards   cash
▾ PURCHASE   Aug 10   −$200.00   5 cards   cash
     Charizard GX #sm211        −$60.00
     Hydreigon ex #240          −$29.00
     …
```

- The summary row shows type, date, **signed** total (T9's `SignedAmount`), item count and
  payment method.
- Collapsed by default. A day's activity as five lines is the point of the report.
- Expanding shows the legs. Reuse the existing per-row rendering rather than a second layout.
- **A row with `batch_id = null` renders as a single-item group** and expands to itself — no
  special-case branch in the render path, which keeps legacy and new rows on one code path.
- A group of one renders without a disclosure triangle. A twisty that reveals the same row is
  noise.
- **Sort by date descending on the group**, matching what the endpoint already returns
  (`txns.sort(key=lambda t: (t.date, t.txn_id), reverse=True)`), so grouping does not reorder the
  archive.
- Card names: `adminItemName` (`frontend/lib/admin-item-name.ts`). **Never** inline
  `display_name || product_name` (CLAUDE.md). The archive rows carry `item_id`, so a name lookup
  may be needed — check what `GET /admin/transactions` actually returns before designing the leg
  row, and if it carries only ids, either accept ids in the legs for this task or batch a name
  lookup the way `useCardImages` batches images. **Do not** fire one request per leg.

### No backfill, and this is deliberate

Historical rows keep `batch_id = null`. A `(date, payment_method, type)` heuristic is **refused**:
two separate cash sales on one show day are indistinguishable from one two-card sale under that
rule, so it would fabricate transactions that never happened, in the one view where being wrong
costs money.

The UI should not pretend otherwise. Legacy rows simply appear as single-line groups; there is no
"ungrouped" banner needed, because a one-item group is a truthful rendering of what is known.

## RED — write these first, show the failing output, wait for confirmation

**Backend (7):**
1. `confirm_buy_session` stamps every transaction in the batch with the same `batch_id`, equal to
   the `buy_id`;
2. `confirm_sale_session` does the same with the `sell_id`;
3. a trade stamps `batch_id == trade_id` on its legs;
4. two separate sessions produce **different** `batch_id`s;
5. `batch_id` survives the DynamoDB round trip (write then `list_transactions`);
6. a `Transaction` dict with **no** `batch_id` still validates, with `batch_id is None` — the
   backward-compatibility gate;
7. `GET /admin/transactions` includes `batch_id` in each row.

**Frontend (6):**
8. five rows sharing a `batch_id` render as **one** summary row;
9. the summary total is the sum of the legs, signed;
10. the summary shows the item count;
11. expanding reveals all five legs;
12. **a row with `batch_id: null` renders as its own single group** and has no disclosure control;
13. groups are ordered by date descending, unchanged from the endpoint's order.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_purchases.py backend/tests/test_sales.py backend/tests/test_trades.py -q --tb=short
cd frontend && npx vitest run "app/(admin)/admin/analytics" --reporter=verbose
```

## GREEN — done when

The above pass, the pre-existing purchase/sale/trade suites are still green (they are the
regression gate on three live money paths), `ruff check backend/src` is clean, and
`npm run lint --workspace=frontend` is clean.

## Manual check

Buy three cards in one session, then open Show Analytics for that day. It must read as **one**
purchase line with a total, expandable to three cards — not three lines. Then confirm a day with
pre-existing (pre-`batch_id`) rows still lists them individually and correctly.

## Do not

- Do not backfill `batch_id`, by heuristic or otherwise.
- Do not group server-side or change `GET /admin/transactions`'s shape beyond adding the field.
- Do not filter trade cash legs out of the archive.
- Do not make `batch_id` required — every historical row would fail validation.
- Do not fire a request per leg to resolve card names.
- Do not reorder the archive as a side effect of grouping.
- Do not inline `display_name || product_name`.

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

**T11 — An accidental sale can be undone**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t11-transaction-void.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
