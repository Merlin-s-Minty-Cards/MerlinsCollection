# T1 — `MoneyInput` everywhere, and the `parseFloat` sites go

**RFC:** 0010 §G ("Rollout") · **Layer:** frontend · **Depends on: T0** · **Blocks:** —

## Why

T0 makes the slab Cost field accept `1,300`. That leaves the admin **inconsistent in the
other direction**: Slabs would be the one money field that takes a comma while every other
one silently swallows the keystroke. The owner types money on Buy, Sell, Trade, Prep Queue
and Show Prep too, and "both should work" was not scoped to slabs.

## The current state, measured

Every other money input is a native number input, which is why the comma has never bitten
there — the browser refuses the character:

| Surface | Line | Field |
|---|---|---|
| Buy | `buy/page.tsx:563, 569, 577` | market value, buy price, buy % |
| Sell | `sell/page.tsx:488, 517` | agreed price, discount |
| Prep Queue | `outgoing/page.tsx:275, 439` | bulk sticker, inline sticker |
| Show Prep | `show-prep/page.tsx:279, 423, 509` | bulk sticker, inline sticker |
| Market | `market/page.tsx:309` | target buy price |
| Cosigners | `cosigners/page.tsx:601, 679, 691` | payout %, split %, min price |
| shared | `InlineEditCell.tsx:135` | `type: 'number' \| 'url'` |

## Two real defects to fix in the same sweep

**1. Parse one value, send another.** Prep Queue and Show Prep guard on the parsed number
and then send the **raw string**:

```ts
const price = parseFloat(bulkStickerValue)
if (isNaN(price) || price < 0) return
// ...
await api.put(`/inventory/${id}`, { sticker_price: bulkStickerValue })  // ← the STRING
```

(`outgoing/page.tsx:140-150`, `show-prep/page.tsx:133-138`.) Harmless *only* because
`type="number"` keeps the string numeric-clean. **The moment this task changes the input, it
becomes a live bug** — `1,300` would pass the guard as `1` (see T0's table) and then send the
literal `"1,300"` to a `Decimal` field. Fix both to send the parsed value.

**2. Every `parseFloat` on money goes.** The call sites are listed above plus the display-side
ones (`buy/page.tsx:148-186, 277-278, 324-352`, `sell/page.tsx:109-184, 453-471`,
`cosigners/page.tsx:175, 228`). Display-side `parseFloat` on a **server-sent** decimal string
is safe — the server never emits `1,300` — so those may stay, but **anything reading a value a
human typed** must go through `parseMoney`.

Be explicit about the distinction in the code comments, or the next person deletes the safe
ones and reintroduces the unsafe ones.

## Percent fields are money-shaped but not money

`payout_percent`, `split_percent` and `buy_pct` are bounded 0–100 (or 0–1 on the wire) and
have no thousands separators. Use `MoneyInput`'s parsing discipline via a thin
`percent` variant, or leave them as `type="number"` with a `min`/`max`. **Do not** let
`parseMoney`'s currency-symbol stripping run on a percent field — `$50%` should not parse.
Recommend: leave percent fields alone this task, and say so in the commit message, since no
report mentions them.

## `InlineEditCell` — decide, do not drift

`InlineEditCell` (`components/admin/shared/InlineEditCell.tsx`) takes
`type: 'number' | 'url'` and backs every inline price edit. Two options:

- **(a)** add a `'money'` type that renders `MoneyInput` internally — one change, every
  inline price editor inherits it, and the component keeps owning its own commit/Enter/blur
  behaviour;
- **(b)** replace `InlineEditCell` with `MoneyInput` at money call sites — more churn, and
  it duplicates the Enter/blur/cancel logic `InlineEditCell` already has right.

**Recommend (a).** Record the choice in `progress.md`.

## Files

- **Modify:** `frontend/components/admin/shared/InlineEditCell.tsx` (a `'money'` type)
- **Modify:** the five page files above, at their **human-typed** money inputs only
- **Modify:** `frontend/lib/money.ts` if a display formatter is wanted alongside
  `PriceDisplay` — check first; `PriceDisplay` may already cover it
- **Tests:** the existing `__tests__` beside each page, plus `InlineEditCell.test.tsx`

## RED — write these first, show the failing output, wait for confirmation

Per-surface, the same three assertions (7 surfaces × 3, trim duplicates where a page has two
money fields of the same kind):

1. typing `1,300` and committing sends **`1300`** to the API — not `NaN`, not `1`, not
   `"1,300"`;
2. an unparseable value blocks the action and shows the inline message;
3. the existing happy path (`1300`) still works — the regression gate.

Plus, specifically:

- **Prep Queue bulk sticker sends the parsed number, not the raw string** — assert on the
  `api.put` body. Same for Show Prep. These are the two rows from "defects to fix" and they
  need their own named tests.
- `InlineEditCell` with `type="money"` parses `1,300` and commits `1300`.

Run:

```bash
cd frontend && npx vitest run "app/(admin)/admin/buy" "app/(admin)/admin/sell" "app/(admin)/admin/outgoing" "app/(admin)/admin/show-prep" "app/(admin)/admin/market" "app/(admin)/admin/cosigners" components/admin/shared/__tests__/InlineEditCell --reporter=verbose
```

## GREEN — done when

- The above pass, and every pre-existing test in those files still passes.
- `npm run lint --workspace=frontend` clean.
- `grep -rn "parseFloat" frontend/app/\(admin\) frontend/components/admin` returns **only**
  display-side reads of server-sent decimal strings, each with a comment saying so.

## Manual check

On each surface, type `1,300` and confirm the committed value. Then confirm on a phone-width
viewport that the numeric keypad still appears — `inputMode="decimal"` is what preserves
that once `type="number"` is gone, and losing it would be a real regression for show-floor
use.

## Do not

- Do not use `parseFloat` on a human-typed value.
- Do not touch percent fields unless you have decided to, deliberately, and recorded it.
- Do not drop `inputMode="decimal"`. The mobile keypad is the only thing `type="number"` was
  buying that matters.
- Do not change any API contract. This task sends the same fields with correct values.

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

**T15 — Every card picker shows the card: name, image AND price**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t15-card-picker-images.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
