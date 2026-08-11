# T11 — An accidental sale can be undone

**RFC:** 0010 §F.3 · **Layer:** backend + frontend · **Depends on: T10** · **Blocks:** —
**Owner report:** plan doc item 11 — *"No way to manually change past sales in this history;
should be able to edit/delete/undo from that menu for accidental transactions"*

> ## ⚠️ This is the largest risk in RFC 0010. Read the invariant before writing code.
>
> **A void honoured by some aggregates and not others produces two disagreeing sets of books,
> which is worse than having no void at all.** There is exactly ONE countability predicate and
> every reader calls it. No reader inlines its own check. The reader list below is exhaustive and
> each entry needs a test.

## Confirmed gap

Nothing can undo a transaction. `grep` over `routers/admin/` finds deletes only for session
line-items, locations, cosigners and inventory items — no `DELETE`, no void, no edit on any
transaction route. The History page is entirely read-only: `GET /admin/inventory/{id}/timeline`,
`/lineage` and `/inventory/search` (`frontend/app/(admin)/admin/history/page.tsx:123, 150, 163`).

And undoing a sale is **not** a row delete. `record_sale` (`services/dynamodb.py:1174-1207`)
writes the ledger row and flips the item to `sold` in **one** `transact_write_items`,
condition-guarded on the item not already being sold. Two things happened; two must be reversed,
together.

## Owner decision, 2026-08-10: void with an audit trail, not a hard delete

Three options were offered. The owner chose void. It matches the precedent already in this
codebase — Shows "delete" is an archive precisely so analytics can never dangle (CLAUDE.md, RFC
0008 Q6) — and a deleted sale would leave no trace it existed while silently disagreeing with
every snapshot already generated.

## Files

- **Modify:** `backend/src/merlins_collection/models/business.py` — the three void fields
- **Create:** `backend/src/merlins_collection/services/ledger.py` — the countability predicate
- **Modify:** `backend/src/merlins_collection/services/dynamodb.py` — an atomic
  `void_transaction` / `restore_transaction`
- **Modify:** `backend/src/merlins_collection/routers/admin/analytics.py` — the routes, plus
  every aggregate in the file
- **Modify:** every other aggregate reader (list below)
- **Modify:** `frontend/app/(admin)/admin/history/page.tsx`,
  `frontend/app/(admin)/admin/analytics/page.tsx`
- **Tests:** a new `backend/tests/test_transaction_void.py`, plus the existing analytics, sales
  and dynamodb suites

## Design

### The fields

```python
class Transaction(BaseModel):
    ...
    # A void, never a delete. Every aggregate MUST exclude a voided row through
    # services.ledger.is_countable — see that module's docstring.
    voided_at: datetime | None = None
    voided_by: str | None = None                              # SERVER-stamped
    void_reason: str | None = Field(default=None, max_length=500)
```

All optional; every existing row validates unchanged.

`voided_by` is **server-stamped from the authenticated principal**. A client's claim about who
voided a sale is not evidence, and this is the one field in the model whose whole purpose is
accountability. Bound `void_reason` at 500 like `review_reason`, for the same reason — it is free
text riding into a DynamoDB item with a 400 KB ceiling.

*(Open question in `progress.md`: Cognito `sub` or email. `sub` is stable and opaque; the email is
what an audit line wants to read. Pick one and document it — do not store both.)*

### The ONE predicate

```python
# backend/src/merlins_collection/services/ledger.py
def is_countable(txn: Transaction) -> bool:
    """True if this row counts toward any total.

    A voided transaction is a record that something was written and then
    withdrawn. It stays readable in the archive and on the item's timeline, and
    it counts toward NOTHING.

    Every aggregate calls this. A reader that inlines `txn.voided_at is None`
    instead is a second definition, and the failure mode is two sets of books
    that disagree by exactly one sale — which nobody notices until a month-end
    number is wrong.
    """
    return txn.voided_at is None
```

**Every reader, exhaustively** — this is the checklist, and each row needs a test:

| reader | where |
|---|---|
| `summarize_transactions` | `services/` analytics helpers |
| `sell_through_rate` | same |
| `starting_inventory` | same |
| `daily_analytics` | `routers/admin/analytics.py:351-382` |
| `list_analytics_dates` | `analytics.py:333-348` — a day whose only sale was voided should not be offered as a date with activity |
| the show snapshot generator | `POST /admin/shows/{id}/analytics/generate` |
| the dashboard (`/admin` quick stats) | wherever it sums today's activity |
| `GET /admin/transactions` | **does NOT filter** — it is the archive, and the void must be *visible* there |
| History page's timeline / lineage | shows the void; does not hide it |

Grep for `list_transactions(` and audit every call site. If a call site does not filter, it must
be because it is deliberately showing the archive — and it should say so in a comment.

### The routes

**`POST /admin/transactions/{txn_id}/void`**, body `{ reason }`.

Reverses **atomically**, mirroring `record_sale`'s `transact_write_items` shape so the two halves
can never disagree:

1. stamp `voided_at` / `voided_by` / `void_reason` on the ledger row;
2. restore the item's status.

Rules:

- A **sale** restores `sold → available`. Condition-guard the item update on it still being
  `sold`, exactly as `record_sale` guards on it not already being sold — if the item has moved on
  since (traded away, re-sold), the void must **fail loudly** rather than resurrect a card
  somebody else now owns.
- Voiding an already-voided transaction → **409**, not a silent success.
- A **purchase** is not symmetric — see the scope note below.
- Append a `voided` **timeline event** to the item. Do not delete the original sale event: the
  timeline is a history, and history includes the mistake.
- Mark any **show analytics snapshot** covering that date/show as stale (a `stale: true` flag on
  the snapshot, or clear it so the UI shows "not generated"). Snapshots are stored point-in-time
  records (`put_show_analytics`, `dynamodb.py:1277`), so a void leaves them wrong by
  construction. **Never silently rewrite one, and never silently serve a stale one.**

**`POST /admin/transactions/{txn_id}/restore`** — clears the three fields and re-applies the
original effect (a restored sale re-flips the item to `sold`, condition-guarded on it being
`available`). "Archiving that cannot be undone is just a slower delete" is already the phrasing
`unarchive_show` uses (`analytics.py:244-245`); the same logic applies here.

### Scope: purchases

**Raise this with the owner before implementing** (it is in `progress.md`'s Blocked table).
Voiding a sale returns an item to stock. Voiding a *purchase* should arguably **remove** an item
that should never have existed — and that item may since have been sold, traded, or re-priced.

**The honest small version: sales only in the first cut, with purchases returning a clear 400**
("A purchase cannot be voided yet — remove the item from inventory instead") rather than being
half-handled. A void that leaves a phantom item in stock is worse than no void.

### Frontend

On the **History** page, where the owner asked for it:

- each transaction row gets a **Void** action, behind `ConfirmDialog` (every destructive admin
  action already goes through it) with a **required reason** field. The reason is the whole point
  of choosing void over delete;
- a voided row renders struck through / dimmed, with `voided — <date> · "<reason>"`, and offers
  **Restore**;
- after T10, when a row belongs to a `batch_id` group the **primary** action is "Void this whole
  transaction (5 cards)", with per-leg void available for a partial correction. Present the count
  in the confirm text — voiding five sales when you meant one is exactly the mistake this feature
  exists to fix;
- the same rendering on the Show Analytics archive table, so a voided row is not invisible there.

## RED — write these first, show the failing output, wait for confirmation

**`is_countable` (2):** an ordinary transaction counts; a voided one does not.

**Void, backend (8):**
1. voiding a sale stamps all three fields **and** returns the item to `available`, in one write;
2. `voided_by` is the **authenticated principal**, not a client-supplied value (send a different
   one in the body and assert it is ignored);
3. voiding an already-voided transaction → **409**;
4. voiding a sale whose item is no longer `sold` **fails** and changes nothing;
5. a `voided` timeline event is appended and the original sale event **survives**;
6. an affected show snapshot is marked stale;
7. a purchase → **400** with the documented message (or, if the owner scoped purchases in, its
   own tests);
8. an unknown `txn_id` → 404.

**Restore, backend (3):** restores the three fields to null and re-flips the item to `sold`;
restoring a non-voided transaction → 409; restore fails if the item is no longer `available`.

**Aggregates, backend — one test per reader (8):** for each row of the reader table, a voided
transaction is excluded — and for `GET /admin/transactions` it is **included** and carries its
void fields. These eight tests are the point of the task; do not collapse them into one
parameterised case that a later refactor can silently narrow.

**Frontend (6):** the Void action requires a reason; a voided row renders struck through with its
reason; Restore is offered on a voided row only; the batch-aware confirm names the card count; a
failed void surfaces the error and leaves the row unchanged; voided rows show as voided on the
analytics archive too.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_transaction_void.py backend/tests/test_analytics.py backend/tests/test_sales.py backend/tests/test_dynamodb.py -q --tb=short
cd frontend && npx vitest run "app/(admin)/admin/history" "app/(admin)/admin/analytics" --reporter=verbose
```

## GREEN — done when

The above pass, the pre-existing analytics / sales / dynamodb suites are still green,
`ruff check backend/src` is clean, and `npm run lint --workspace=frontend` is clean.

## Manual check

Sell a card. Confirm it leaves inventory and appears in the day's total. Void the sale with a
reason. Confirm: the card is back in inventory as `available`, the day's total drops by that
amount, the History row shows struck-through with your reason, and the item's timeline shows both
the sale **and** the void. Then regenerate the show snapshot and confirm the number moved.

Finally, restore it, and confirm everything goes back.

## Do not

- **Do not inline a voided check in any aggregate.** One predicate.
- Do not hard-delete a transaction. The owner chose void.
- Do not trust a client-supplied `voided_by`.
- Do not delete the original timeline event.
- Do not silently rewrite a show snapshot, and do not silently serve a stale one.
- Do not resurrect an item whose status has moved on — fail loudly.
- Do not filter voided rows out of `GET /admin/transactions`. The archive shows what was written.
- Do not half-implement purchase voiding. Refuse it clearly, or scope it in properly.
- Do not skip the eight per-reader aggregate tests. They are the whole safety property.

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

**T12 — Slabs: PSA out, scanner affordance out, a price at intake**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t12-slabs-psa-out-price-at-intake.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
