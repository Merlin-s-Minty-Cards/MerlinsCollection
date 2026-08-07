# T4 — Sidebar stays put · Vendor mode deleted

**RFC:** 0008 §F2 (issue #7) + §F3 (issue #8) · **Layer:** frontend · **Depends on:** nothing

Two small, unrelated fixes bundled because both are frontend-only and neither is
big enough for its own conversation.

---

## Part A — §F2: the admin sidebar scrolls away

**File:** `frontend/components/admin/AdminShell.tsx`

### Root cause

Line 52: the outer wrapper is `min-h-screen ... flex`. `<main>` (line 143) already
carries `overflow-y-auto`, but **`overflow-y-auto` only bounds scrolling when the
element's height is capped**. `min-h-screen` is a *minimum*, not a cap, so with
default `align-items: stretch` both `<aside>` and `<main>` grow to content height
and the **document** scrolls instead. `<aside>` has no sticky/fixed positioning, so
it scrolls away exactly as reported.

The nav's own `overflow-y-auto` (line 79) is already correctly placed for the
"too many tabs" case — it just never engages, because the aside is never bounded.

### Fix

Change the outer wrapper from `min-h-screen` to `h-screen overflow-hidden`. That
caps the parent, so `<main>`'s existing `overflow-y-auto` activates and `<aside>`
becomes viewport-bounded via flex stretch. The nav then scrolls independently when
the tab list overflows, with no further change.

Do **not** reach for `position: sticky` — rejected in the RFC's alternatives, it
doesn't stop the page scrolling past a short sidebar.

### Watch for

- **Mobile.** The mobile bottom nav (line 123) is `fixed`, and `<main>` has
  `pb-20 md:pb-0` to clear it. Verify `h-screen overflow-hidden` doesn't clip
  content behind the bottom nav on a narrow viewport. Check at 375px width.
- **Nested scroll containers.** Admin pages with their own scrolling tables
  (Vault, Inventory) now sit inside a bounded `<main>`. Confirm they don't
  double-scroll or lose their sticky table headers.
- `vault-scroll` is the project's scrollbar-styling class — keep it wherever it is.

---

## Part B — §F3: delete vendor mode

**File:** `frontend/app/(admin)/admin/trade/page.tsx`

### Confirmed dead — verified by grep, and the owner has confirmed removal

`mode: "customer"|"vendor"` gated a percent-based margin-split formula from
RFC 0007 §A1. That formula was retired by the Round 3 OWNER RULING 2026-08-04 and
replaced by the unconditional `basis_mode` (transfer/split/manual) selector.

Nothing in `admin/trades.py` branches on `"vendor"` — every `mode ==` check in
that file is against `basis_mode`, a different field. `vendorMode` today does
exactly three cosmetic things:

| Line | What |
|---|---|
| 87 | `useState(false)` |
| 367 | reset to `false` |
| 406-413 | toggle button + badge label swap |
| 828 | appends `" (vendor mode)"` to the confirm dialog text |

### Fix

Delete all four. Remove the toggle button entirely.

**On the stored `mode` field:** the trade session still writes
`"mode": body.get("mode", "customer")` (`admin/trades.py:176`) and merges it on
update (line 271). Nothing reads it back for any calculation.

- Stop sending `mode` from the frontend payload.
- **Leave the backend's default-write in place** for now. It costs nothing, it
  keeps historical rows shape-consistent, and dropping a written field is a
  separate decision from removing dead UI. Do not delete the backend field in
  this task.
- Historical trade sessions are unaffected either way.

### Do not

Do not touch the `basis_mode` selector (transfer/split/manual). It is the live,
correct control and renders unconditionally by design.

---

## RED — write these first, confirm they fail, then stop

1. `AdminShell` renders its outer wrapper with a **capped** height class
   (`h-screen`), not `min-h-screen`. Fails today.
2. Trade page renders **no** "Vendor Mode" / "Customer Mode" toggle. Fails today.
3. Trade page confirm dialog text contains no `"vendor mode"` suffix. Fails today.
4. Trade page still renders the basis-mode selector with all three options.
   Passes today — regression guard, the important one.

## Verify (narrow)

```bash
cd frontend && npx vitest run AdminShell trade
npm run lint --workspace=frontend
```

Then **look at it**: load `/admin/inventory`, scroll the table, confirm the sidebar
holds. Repeat at 375px width for the mobile nav check.

## Done when

- Sidebar fixed at desktop and mobile widths, nav scrolls internally if tabs overflow.
- `grep -rn "vendorMode\|vendor mode" frontend/` returns nothing.
