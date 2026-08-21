# T6 — Configurable columns, and filters that follow them

**RFC:** 0008 §F5 (issue #10) · **Layer:** frontend · **Depends on:** nothing
**File:** `frontend/app/(admin)/admin/inventory/page.tsx` (+ a new registry module)

Largest frontend task in RFC 0008. Give it its own conversation.

## The gap

Line 201 builds a hardcoded `columns: Column<InventoryItem>[]` array (Image, Name,
Status, Kind, Cond, Location, Price Paid, Market, Sticker, …). No visibility
control, no persistence. Separately, the filter panel offers fields
(`card_number`, `artist`, `set_name`, …) with no relationship to what's displayed.

## Owner decision on filters (RFC Q9 — settled, build exactly this)

> Filters follow the visible columns — **plus** a "show all filters" escape hatch.

So: by default the filter panel shows only filters whose column is currently
visible. A **"Show all filters"** toggle reveals every filterable field regardless
of column visibility. This is the literal reading the owner asked for, without
trapping them into adding a column just to filter on something.

Two details that make this behave sanely:

- When "show all filters" is on and the owner sets a filter on a **hidden** column,
  the result set changes for a reason they can't see. Mark that filter visibly
  (e.g. "filtering on a hidden column") and offer a one-click "show this column".
  Silent invisible filtering is the failure mode to avoid here.
- Turning a column off must **not** silently clear an active filter on it. Keep the
  filter applied and surface it per the above. Dropping a user's filter because
  they hid a column is data loss from their point of view.

## Build

### 1. A column registry module

New file, e.g. `frontend/lib/admin-inventory-columns.tsx`. Not inline in the page —
the page is already large and this is reusable.

Each entry:

```ts
{
  key: string              // stable; persisted — never rename without a version bump
  label: string
  defaultVisible: boolean
  filterable?: boolean     // does this field get a filter control
  render: (item: InventoryItem) => ReactNode
}
```

Cover the **superset** of fields across every item kind (raw / graded / sealed /
bulk — the union in `models/inventory.py:170-247`), not just what's hardcoded
today. That's the point: fields that exist but were never displayable become
available.

### 2. Column picker

A checkbox list / multi-select filtering which registry entries reach `DataTable`.
Keep registry order stable so columns don't jump around as they're toggled.

### 3. Persistence

`localStorage`, keyed `admin-inventory-columns-v1`.

- **Versioned key** — bumping it retires a stale saved list rather than
  resurrecting a broken shape after a registry change.
- **Validate on read.** A saved key that's no longer in the registry is dropped,
  not rendered. A corrupt/unparseable value falls back to defaults rather than
  throwing — this runs on mount and an exception here blanks the page.
- No backend schema, no cross-device sync (owner accepted; RFC alternatives).

### 4. Wire filters to visibility

Per the owner decision above.

## Watch for

- The existing **Image column** is already conditional on a separate `showImages`
  toggle (line 203). Fold it into the registry rather than leaving two competing
  mechanisms — but keep the existing toggle working, or migrate it deliberately.
- Inline editing: the Location column renders an inline `<select>` when
  `editingId === item.item_id` (line 255+). That editing behaviour must survive the
  move into the registry.
- Sorting: entries currently carry `sortable: true`. Preserve per-column.
- Ownership column exists per CLAUDE.md — don't lose it.
- SSR: `localStorage` doesn't exist on the server. Read it in an effect (or guard
  `typeof window`) or Next will throw on hydration.

## RED — write these first, confirm they fail, then stop

1. Default render shows exactly the `defaultVisible` registry columns.
2. Unchecking a column removes it from the table. Fails today.
3. Choice persists across remount via `localStorage`. Fails today.
4. A saved key not in the registry is ignored, and the table still renders.
5. Corrupt `localStorage` value → falls back to defaults, no throw.
6. Filter panel shows only filters for visible columns by default. Fails today.
7. "Show all filters" reveals filters for hidden columns. Fails today.
8. A filter on a hidden column stays applied and is flagged as such. Fails today.
9. Hiding a column with an active filter does not clear the filter.
10. Inline location editing still works after the registry move. Regression guard.
11. Column order is stable regardless of toggle sequence.

## Verify (narrow)

```bash
cd frontend && npx vitest run inventory columns
npm run lint --workspace=frontend
```

Then drive `/admin/inventory`: toggle columns, reload, confirm they stick.

## Done when

- All 11 green, columns persist, filters follow visibility with a working escape hatch.
- No hardcoded column array remains in `page.tsx`.
