# RFC 0006: Admin Panel UX — Round 4 Enhancements

**Status:** Draft  
**Author:** Kiro (orchestrator)  
**Date:** 2025-07-21  

## Summary

13 enhancements across the admin panel: trade calculator data entry improvements, profit display upgrades, vault image bug fix, inventory image toggle, show-prep mass sticker update + sort by delta + TCGplayer links, card detail cleanup (remove listed_price, rename cost_basis), location dropdown, delete-after-loss with confirmation, date fields on sell/trade, and sticker notes.

## Motivation

The admin panel is used live at card shows. Faster data entry, clearer profit visibility, and fewer manual text-entry fields directly improve show-day throughput. Several of these are bug fixes or UX debt from previous rounds.

---

## Detailed Design

### Stream 1: Trade Page Enhancements (trade/page.tsx)

**1A. Incoming card form expansion**

Current incoming form has: `name`, `value`.  
New field order with labels: `Card Name`, `Number`, `Set`, `Market`, `Value`, `%`.

- `name` — card name (text, existing)
- `number` — card number in set (text, new)
- `set` — set name (text, new)
- `market` — market value reference (number, new, informational only — not sent to backend)
- `value` — agreed trade-in value (number, existing field `agreed_value`)
- `percentage` — auto-calculated: `(value / market * 100)`. Editable — typing % recalculates value.

UI: Labels above each input. `Value` and `%` labels get a highlight (e.g., mint/amber bg pill or underline) to draw the eye.

The `number` and `set` fields are stored in the incoming leg's `name` composite or as metadata. Backend trade incoming legs currently only store `name` + `agreed_value`. Two options:
- **Option A (frontend-only):** Concatenate into name display: `"{name} #{number} — {set}"`. No backend change.
- **Option B (backend extension):** Add `card_number` and `set_name` optional fields to trade incoming legs.

**Recommendation:** Option B — the backend already accepts `set_name` and `market_value` on incoming legs. Add `card_number` to the accepted fields. Frontend sends all fields separately; they're stored in the trade session and flow through to the inventory item on confirm.

Backend change: Add `"card_number": body.get("card_number")` to the incoming leg dict in `POST /trades/{id}/incoming`. One-line addition.

**1B. Profit display (rename "Our Margin" → "Our Profit")**

Current: Shows `margin_pct` only as a percentage.  
New: Show both `% gain` AND `$ profit` amount. Label: "Our Profit".

The dollar profit = `total_in_value + cash_delta - total_cost_basis` (what we receive minus what our cards cost us). The backend `TradeBalance` already returns `total_cost_basis` and the other values needed. Calculate on frontend:
```
dollarProfit = parseFloat(balance.total_in_value) + parseFloat(balance.cash_delta) - parseFloat(balance.total_cost_basis)
```

Display: `$X.XX (Y.Y%)` — both in the same block.

**1C. Date field on trade page**

Add a date input auto-filled with today's date but editable. Sent to backend on confirm as `trade_date`. Backend already has `created_at` on sessions but this allows backdating.

Backend change: Add optional `trade_date: date | None` to trade confirm/patch endpoint. If provided, override the transaction `created_at` timestamp.

---

### Stream 2: Show-Prep Enhancements (show-prep/page.tsx)

**2A. Move image toggle to top**

Currently `<ImageToggle>` is below the DataTable. Move it to the header row next to the threshold controls (same row as the `%/$` toggle and slider).

**2B. Sort by Delta**

Make the `delta_pct` column sortable in the DataTable. Frontend sort (data is already fully loaded). Add `sortable: true` to the delta column definition and implement a local sort comparator using the numeric delta value.

**2C. TCGplayer link column**

Add a column to the right of Delta showing a TCGplayer link icon. Two states:
- If item has `tcg_url` field populated → clickable link icon (opens in new tab)
- If no `tcg_url` → show a small "add link" button that reveals an inline input for pasting a URL

On blur/enter of the inline input, PATCH the item's `tcg_url` via `/admin/inventory/{id}` (already supports arbitrary field updates).

The `tcg_url` field already exists on the inventory model. No backend change needed.

**2D. Mass sticker update via text box**

Add a bulk action: when items are selected (checkboxes), show a "Update Stickers" input alongside the existing "Move to location" input. User types a price, clicks "Apply" → PATCHes `sticker_price` on all selected items.

Implementation: Loop selected IDs, call `PUT /admin/inventory/{id}` with `{ sticker_price: value }` for each. Show progress/result count.

---

### Stream 3: Inventory & Card Detail Enhancements

**3A. Vault pictures not loading (bug fix)**

The vault page passes `cardIds` to `useCardImages` only when `showImages` is true. However, looking at the vault code: `const cardIds = (data?.items ?? []).map((i) => i.card_id)` — this maps correctly. The issue is likely that vault items have `card_id` stored but the batch image resolution endpoint `/admin/inventory/card-images` may not be resolving them.

Investigation needed: The most likely cause is that vault items (status=`on_hold`) are not being found by the card-images endpoint, OR their `card_id` values don't match what TCGdex expects. Debug by checking:
1. Whether vault items have valid `card_id` values
2. Whether the `/admin/inventory/card-images` endpoint filters by status

**3B. Inventory page: add toggleable picture option**

The inventory page ALREADY has `<ImageToggle>` wired up (line ~184 in the filters section). If images aren't showing, it's the same underlying bug as 3A. Verify this is actually working — the code looks correct. If user means they want the toggle moved to a more prominent position, move it to the top alongside filters (it's already in `ml-auto` position in the filter row).

**3C. Remove "Listed Price" from CardDetailModal**

Remove `{ key: 'listed_price', label: 'Listed Price', type: 'number' }` from `EDITABLE_FIELDS` array. The field is a relic — `listed_price` was from the spreadsheet import and is null on all items by owner decision. `sticker_price` replaced it functionally.

**3D. Rename "Cost Basis" → "Price Paid"**

In `EDITABLE_FIELDS`: change `{ key: 'cost_basis', label: 'Cost Basis', type: 'number' }` to `{ key: 'cost_basis', label: 'Price Paid', type: 'number' }`.

Also rename in the inventory table column header and anywhere else it's displayed as a label (sell cart, show-prep, vault). The backend field name stays `cost_basis` — only the UI label changes.

**3E. Location dropdown (fixed options)**

Replace the free-text location input in CardDetailModal and the inventory table's inline edit with a `<select>` dropdown. Fixed options based on actual business locations:

Options: `glass`, `toploader`, `binder`, `storage`

These are the four physical locations currently in the data. Status (on_hold, lost, out_for_grading) and factory_sealed are separate fields already handled by the status system.

This applies to:
- CardDetailModal location field
- Inventory page inline location editor
- CreateItemModal location field
- Show-prep bulk move target (keep as text — bulk move target might be any location)

**3F. Delete option after loss conversion + confirmation popup**

Current delete does soft-delete (marks as lost). Enhancement: if an item is ALREADY in `lost` status, show a "Permanently Delete" option with a danger confirmation popup ("This cannot be undone. Permanently delete this record?"). Calls `DELETE /admin/inventory/{id}?hard=true` (backend already supports hard delete via query param).

---

### Stream 4: Cross-Page Features (sell + trade)

**4A. Date field on sell page**

Add a date input to the sell session info panel (alongside Customer and Payment). Auto-filled with today (`new Date().toISOString().split('T')[0]`), editable. Sent on confirm as `sale_date`.

Backend change: Add optional `sale_date: date | None` to sell session patch/confirm. If provided, use as transaction date instead of `utcnow()`.

**4B. Date field on trade page**

(Covered in 1C above — same pattern.)

**4C. Sticker notes**

Add a `sticker_notes` field near the sticker price display. This is a small free-text input for internal notes about why a sticker was set to a particular price (e.g., "Damaged corner — priced low" or "Show special").

Backend change: Add `sticker_notes: str | None = None` to `_ItemBase` in `models/inventory.py`. It flows through DynamoDB CRUD automatically like `sticker_price` did.

Frontend: Show a small text input or expandable note icon next to sticker price in:
- Inventory table (inline, expandable on hover/click)
- CardDetailModal (as an editable field)
- Show-prep table (read-only display, tooltip on hover)

---

## Data Schema Changes

### `_ItemBase` (backend/src/merlins_collection/models/inventory.py)

```python
# New field — add after sticker_price
sticker_notes: str | None = None
```

### Trade/Sell session patches

```python
# In sell session PATCH body (routers/admin/sell.py)
sale_date: date | None = None  # Optional override for transaction date

# In trade session PATCH body (routers/admin/trade.py)  
trade_date: date | None = None  # Optional override for transaction date
```

No new DynamoDB indexes needed — these are scalar attributes on existing items/sessions.

---

## API Contract Changes

### Modified: `PATCH /admin/sales/{sell_id}`
New optional body field:
```json
{ "sale_date": "2025-07-20" }
```

### Modified: `PATCH /admin/trades/{trade_id}`
New optional body field:
```json
{ "trade_date": "2025-07-20" }
```

### No new endpoints needed
- Sticker update uses existing `PUT /admin/inventory/{id}`
- TCG URL update uses existing `PUT /admin/inventory/{id}`
- Card images uses existing `POST /admin/inventory/card-images`
- Hard delete uses existing `DELETE /admin/inventory/{id}?hard=true`

---

## Concurrency Plan (4 Streams)

These streams have NO file overlap and can be dispatched to `code-writer` in parallel:

| Stream | Files Touched | Dependencies |
|--------|--------------|--------------|
| **1: Trade** | `frontend/app/(admin)/admin/trade/page.tsx`, backend trade router | None |
| **2: Show-Prep** | `frontend/app/(admin)/admin/show-prep/page.tsx` | None |
| **3: Inventory/Detail** | `CardDetailModal.tsx`, `inventory/page.tsx`, `vault/page.tsx`, `models/inventory.py` | None (vault bug may need backend investigation) |
| **4: Cross-Page (sell date, sticker notes)** | `sell/page.tsx`, backend sell router, `models/inventory.py` | Stream 3 adds `sticker_notes` to model — **sequence Stream 4 model change AFTER Stream 3** or merge carefully |

**Conflict note:** Streams 3 and 4 both touch `models/inventory.py` (Stream 3 for location dropdown validation potentially, Stream 4 for `sticker_notes`). Resolution: Stream 4 handles the model addition; Stream 3 is frontend-only for its changes. Stream 4's backend piece (model + sell date) goes first or in parallel if the model edit is a simple append.

---

## Alternatives Considered

1. **~~Backend fields for trade incoming (number, set):~~** Decision: store separately. Backend already supports `set_name` and `market_value`; adding `card_number`. Data flows through to inventory item on trade confirm.

2. **Keeping listed_price visible:** Rejected — it's null on every item and replaced by sticker_price. Removing reduces confusion.

3. **Dynamic location list from DB:** Considered fetching distinct locations from DynamoDB. Rejected because the list is small and fixed by business process (glass, toploader, binder, storage). A hardcoded dropdown is faster and prevents typos.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Vault image bug has a backend cause | Stream 3 investigator checks the card-images endpoint before frontend changes |
| Date override on sales/trades could cause accounting confusion | Date is optional, defaults to today — only used for backdating forgotten entries |
| Hard delete is destructive | Double confirmation popup with "cannot be undone" warning + only available on already-lost items |

---

## Open Questions

1. ~~Location list~~ — Confirmed: `glass`, `toploader`, `binder`, `storage`.
2. ~~Trade incoming fields~~ — Storing separately. Backend already accepts `set_name`/`market_value`; adding `card_number`.
3. ~~Sticker notes max length~~ — Confirmed: 200 chars.

