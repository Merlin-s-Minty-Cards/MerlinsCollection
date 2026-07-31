# RFC 0005: Admin Panel Frontend

- **Status:** Draft
- **Author:** design-doc agent
- **Date:** 2025-01-27

## Summary

A full admin panel built into the Next.js frontend, served under `/admin/*`, gated behind `session.isAdmin`. Replaces the Retool dependency with a first-party interface for managing inventory, executing sales/purchases/trades, and prepping for shows — all calling the `/admin/*` API endpoints built in RFC 0004.

## Motivation

The business operates at physical card shows where speed matters. A dedicated admin panel built into the existing app means:
1. No third-party dependency (Retool) or separate login
2. Matches the existing brand aesthetics and feels cohesive
3. Works on tablets at shows (responsive)
4. Admin-only gating uses the same Cognito session that's already in place

## Design Principles

### Visual Identity

The admin panel uses the existing **dark "vault" theme** (pine/forest color system) but adapted for a denser, operational UI:
- Background: `pine-950` (#06150b) with the existing `vault-scope` styles
- Panels/cards: `vault-panel` gradient (pine-800 → pine-900) with pine-700 borders
- Text: `pine-100` primary, `pine-300` secondary, `mint` for accents/labels
- Interactive: mint/spriggatito-400 for primary actions, forest-mid for hover states
- Destructive: `red-500` for delete/cancel actions, amber for warnings

### Layout Philosophy

- **Sidebar navigation** (collapsible on mobile) with icon + label nav items
- **Dense but readable** — 8px base spacing, tight table rows, minimal padding
- **Laptop-first** — designed for laptop screens at card shows (1280px+), scales down to tablet/phone
- **Action-oriented** — primary CTA always visible, status indicators prominent

### UX Patterns

- **Session-based workflows** — sell/buy/trade are multi-step drafts (match the API's session model)
- **Inline editing** — inventory fields editable in-place, no modal forms
- **Optimistic UI** — show changes immediately, revert on error
- **Persistent state** — current sell/buy/trade session survives page navigation (stored in URL or context)

## Route Structure

```
frontend/app/(admin)/
├── layout.tsx              # Admin shell (sidebar + content area), admin gate
├── admin/
│   ├── page.tsx            # Dashboard: quick stats, recent activity
│   ├── inventory/
│   │   └── page.tsx        # Full inventory table with inline CRUD
│   ├── sell/
│   │   └── page.tsx        # Active sell session builder
│   ├── buy/
│   │   └── page.tsx        # Active buy session builder
│   ├── trade/
│   │   └── page.tsx        # Trade calculator with customer view
│   ├── market/
│   │   └── page.tsx        # Catalog search + watchlist
│   └── show-prep/
│       └── page.tsx        # Mispriced cards, bulk moves, location overview
```

## Component Architecture

```
frontend/components/admin/
├── AdminShell.tsx           # Sidebar + top bar + content slot
├── AdminSidebar.tsx         # Navigation with icons, collapsible
├── AdminHeader.tsx          # Page title + breadcrumbs + quick actions
├── inventory/
│   ├── InventoryTable.tsx   # Data table with sort, filter, inline edit
│   ├── InventoryFilters.tsx # Status/location/condition filter bar
│   ├── ItemDetailPanel.tsx  # Slide-out detail view
│   └── CreateItemForm.tsx   # New item creation form
├── sell/
│   ├── SellSessionBuilder.tsx  # Main sell interface
│   ├── SellItemRow.tsx         # One item in the sell cart
│   └── SellConfirmModal.tsx    # Confirmation summary
├── buy/
│   ├── BuySessionBuilder.tsx   # Main buy interface
│   ├── BuyItemForm.tsx         # Add new item to buy session
│   └── BuyConfirmModal.tsx     # Confirmation summary
├── trade/
│   ├── TradeCalculator.tsx     # Two-column trade builder
│   ├── TradeLegList.tsx        # Outgoing or incoming legs
│   ├── TradeBalance.tsx        # Live balance + margin display
│   └── CustomerView.tsx        # Sanitized view (safe to show customer)
├── market/
│   ├── CatalogSearch.tsx       # Search the synced catalog
│   ├── PriceTrend.tsx          # Price history chart
│   └── Watchlist.tsx           # Watchlist management
├── show-prep/
│   ├── MispricedTable.tsx      # Cards needing repricing
│   ├── BulkMovePanel.tsx       # Multi-select + move
│   └── LocationSummary.tsx     # Counts by location
└── shared/
    ├── DataTable.tsx           # Reusable sortable/filterable table
    ├── SearchInput.tsx         # Debounced search with icon
    ├── StatusBadge.tsx         # Colored status indicator
    ├── PriceDisplay.tsx        # Formatted currency display
    ├── ConfirmDialog.tsx       # Reusable confirmation modal
    └── useAdminApi.ts          # Hook: fetches with auth token
```

## API Integration

### `useAdminApi` Hook

All admin API calls go through a shared hook that:
1. Reads the Cognito access token from the NextAuth session
2. Sends it as `Authorization: Bearer <token>`
3. Handles 401 (redirect to login) and 403 (redirect to home)
4. Provides loading/error states

```typescript
// Simplified interface
function useAdminApi() {
  return {
    get: (path: string) => Promise<T>,
    post: (path: string, body: any) => Promise<T>,
    put: (path: string, body: any) => Promise<T>,
    patch: (path: string, body: any) => Promise<T>,
    del: (path: string) => Promise<T>,
  }
}
```

### Backend URL

Uses `NEXT_PUBLIC_API_URL` environment variable (already configured for the inventory page's existing API calls).

## Key Pages

### 1. Dashboard (`/admin`)

Quick overview:
- Inventory count (available / total)
- Today's sales / purchases count
- Cards needing repricing
- Quick-action buttons: "New Sale", "New Buy", "New Trade"

### 2. Inventory (`/admin/inventory`)

Full-featured data table:
- All items across all statuses (not just available)
- All fields visible (cost_basis, location, notes)
- Column sort (click headers)
- Filter bar: status, location, condition, kind
- Search by name (debounced text input)
- Inline edit: click a cell to edit, blur to save
- Row actions: view history, delete (soft/hard)
- "Add Item" button → form/modal

### 3. Sell (`/admin/sell`)

Session-based interface:
- Left panel: search available inventory
- Right panel: current sell cart (items + agreed prices)
- Bottom bar: total, payment method selector, confirm button
- On confirm: all items flip to SOLD

### 4. Buy (`/admin/buy`)

Session-based interface:
- Form to add cards being purchased (name, condition, price, market value)
- Running total + average buy percentage
- Confirm creates all items in inventory

### 5. Trade (`/admin/trade`)

Two-column layout:
- Left: "Going Out" (our items) — search + add from inventory
- Right: "Coming In" (their items) — manual entry form
- Bottom: cash component + live balance bar
- Toggle: "Show Customer" mode (strips internal data, safe for their screen)
- Margin indicator visible only in admin mode

### 6. Market (`/admin/market`)

Research tool:
- Catalog search (name, set)
- Click a card → price history chart + current prices
- "Add to Watchlist" button
- Watchlist tab with target prices

### 7. Show Prep (`/admin/show-prep`)

Pre-show checklist:
- Mispriced cards table (threshold slider)
- Multi-select → "Move to glass case" bulk action
- Location breakdown (pie chart or bar)

## Responsive Behavior

| Breakpoint | Layout |
|-----------|--------|
| < 768px (phone) | Sidebar collapses to bottom tab bar, single-column content |
| 768px–1024px (tablet) | Sidebar collapsed (icons only), content fills remaining width |
| > 1024px (desktop/laptop) | Full sidebar with labels + content — PRIMARY use case (shows) |

## Authentication Flow

1. User navigates to `/admin/*`
2. Server-side `(admin)/layout.tsx` checks `session.isAdmin`
3. Non-admin → redirect to `/`
4. No session → redirect to Cognito sign-in with `callbackUrl=/admin`
5. Authenticated admin → render the admin shell

## Dependencies

No new packages required. Uses:
- `next-auth` (existing) for session/token
- `lucide-react` (existing) for icons
- Tailwind CSS (existing) for styling
- `fetch` for API calls (no axios/swr needed — the admin panel is write-heavy, not cache-heavy)

Optional future additions:
- `@tanstack/react-table` for advanced table features (sorting, virtualization)
- `recharts` or `chart.js` for price trend visualization

## Implementation Phases

### Phase A: Shell & Infrastructure
- Admin layout with sidebar navigation
- `useAdminApi` hook
- Route protection (layout gate)
- Admin link in Navbar (visible only to admins)

### Phase B: Inventory Management
- Full data table with filters and sort
- Inline editing
- Create/delete items
- Item history panel

### Phase C: Sell & Buy Flows
- Sell session builder
- Buy session builder
- Confirm flows with summary

### Phase D: Trade Calculator
- Two-column trade builder
- Balance + margin display
- Customer view toggle

### Phase E: Market & Show Prep
- Catalog search
- Price trend display
- Watchlist
- Mispriced cards + bulk move

## Open Questions

1. **Chart library** — Use a lightweight chart for price trends? Or just a table of price points for v1?
2. **Mobile trade UX** — Two-column layout doesn't work on phone. Tabs? Or require tablet minimum for trades?
3. **Offline support** — Card shows sometimes have poor connectivity. Cache the full inventory on page load? (Deferred to v2)
4. **Sound/haptic feedback** — Audible confirmation on sale/trade confirm? (Nice-to-have, deferred)
