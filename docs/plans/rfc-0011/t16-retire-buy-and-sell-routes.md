# T16 — Retire `/admin/buy` and `/admin/sell`

**RFC:** 0011 §I, decisions 10 & 11 · **Layer:** frontend · **Depends on:** T15 · **Blocks:** —

The last step, and deliberately separate: T15 builds the merged page while the old routes
still work, so it can be reviewed on its own. This task removes them and repoints
everything that referred to them.

**This is the one task in RFC 0011 that deletes working, reachable pages.** Do it in one
commit, so a bisect never lands on a state where the sidebar points at a route that no
longer exists.

## Owner decision, and the precedent it departs from

Decision 10: **`/admin/buy` and `/admin/sell` are removed, not redirected.** `/admin/trade`
survives as the single route.

CLAUDE.md records the opposite instinct for `/admin/outgoing` — *"grouping is a sidebar
concern and renaming would break every bookmark to fix a URL nobody types."* That
precedent still holds **for renaming a page that still exists**. Here the two pages
genuinely stop existing, so there is no URL to preserve the meaning of. Record the
distinction in CLAUDE.md (T12) rather than leaving a future reader to think the rule was
forgotten.

## Files

- **Delete:** `frontend/app/(admin)/admin/buy/` (page + `__tests__`)
- **Delete:** `frontend/app/(admin)/admin/sell/` (page + `__tests__`)
- **Modify:** `frontend/components/admin/AdminShell.tsx` — `navGroups` (line 56-60),
  `mobileItems` (line 95-101)
- **Modify:** `frontend/app/(admin)/admin/page.tsx` — the three quick actions (line 116-123)
- **Modify:** `frontend/components/admin/__tests__/AdminShell.test.tsx`,
  `frontend/app/(admin)/admin/__tests__/page.test.tsx`
- **Sweep:** every remaining reference — `grep -rn "admin/buy\|admin/sell" frontend/`

## Design

### The sidebar

"At the show" drops from five entries to three:

```ts
{
  id: 'at-the-show',
  label: 'At the show',
  items: [
    { href: '/admin/inventory', label: 'Inventory', icon: Package },
    { href: '/admin/trade', label: 'Buy / Sell / Trade', icon: ArrowRightLeft },
    { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
  ],
}
```

Decision 11: the label spells out all three modes, so nothing has to be learned from a
one-word name.

### `mobileItems` — an explicit list, never a slice

CLAUDE.md is emphatic, and it is emphatic because flattening the groups and taking five
once yielded *Trade* where Slabs should have been. The list loses two entries and gains
one:

```ts
const mobileItems = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/inventory', label: 'Inventory', icon: Package },
  { href: '/admin/trade', label: 'Deal', icon: ArrowRightLeft },
  { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
]
```

**"Deal" here, "Buy / Sell / Trade" in the sidebar** — the mobile bar is four icons across
a phone and the long label does not fit. That is a deliberate divergence; note it in the
code so the next reader does not "fix" it into consistency.

### The dashboard keeps three quick actions

They are the fastest path into each mode and there is no reason to lose them — the mode
lives in the query string precisely so one route can serve three entry points:

```tsx
<QuickAction href="/admin/trade?mode=sell" label="New Sale"  hint="Start selling" ... />
<QuickAction href="/admin/trade?mode=buy"  label="New Buy"   hint="Purchase cards" ... />
<QuickAction href="/admin/trade"           label="New Trade" hint="Trade calculator" ... />
```

Leave the fourth (Vault) alone.

## RED — write these first, show the failing output, then STOP

In `AdminShell.test.tsx`:

```tsx
it('offers one Buy / Sell / Trade entry, not three', () => {
  render(<AdminShell><div /></AdminShell>)
  const group = screen.getByRole('group', { name: 'At the show' })
  const labels = within(group).getAllByRole('link').map((l) => l.textContent?.trim())
  expect(labels).toEqual(['Inventory', 'Buy / Sell / Trade', 'Slabs'])
})

it('points the mobile bar at the merged route', () => {
  // An explicit list, never a .slice() of the groups.
  render(<AdminShell><div /></AdminShell>)
  const bar = screen.getByRole('navigation', { name: /mobile/i })
  expect(within(bar).getByRole('link', { name: /deal/i }))
    .toHaveAttribute('href', '/admin/trade')
  expect(within(bar).queryByRole('link', { name: /^buy$/i })).not.toBeInTheDocument()
})

it('marks the group active for the merged route', () => {
  // The group holding the active route is forced open regardless of what was saved.
  mockPathname('/admin/trade')
  render(<AdminShell><div /></AdminShell>)
  expect(screen.getByRole('group', { name: 'At the show' })).toBeVisible()
})
```

In the dashboard test:

```tsx
it('sends each quick action to the merged page with its mode', async () => {
  render(<AdminDashboardPage />)
  const actions = within(await screen.findByTestId('quick-actions'))
  expect(actions.getByRole('link', { name: /new sale/i }))
    .toHaveAttribute('href', '/admin/trade?mode=sell')
  expect(actions.getByRole('link', { name: /new buy/i }))
    .toHaveAttribute('href', '/admin/trade?mode=buy')
  expect(actions.getByRole('link', { name: /new trade/i }))
    .toHaveAttribute('href', '/admin/trade')
})
```

And one repo-level guard, in `AdminShell.test.tsx`:

```tsx
it('has no link anywhere to a retired route', () => {
  // A nav entry pointing at a deleted page is a 404 the owner finds mid-show.
  render(<AdminShell><div /></AdminShell>)
  for (const link of screen.getAllByRole('link')) {
    const href = link.getAttribute('href') ?? ''
    expect(href.startsWith('/admin/buy')).toBe(false)
    expect(href.startsWith('/admin/sell')).toBe(false)
  }
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run components/admin/__tests__/AdminShell.test.tsx "app/(admin)/admin/__tests__/page.test.tsx"
```

## GREEN, then sweep

After the tests pass, delete the two route directories and sweep for stragglers:

```bash
grep -rn "admin/buy\|admin/sell" frontend/ --include=*.tsx --include=*.ts
```

Expect hits in: the two deleted test files (gone with them), possibly `CardDetailModal`
or a link in Prep Queue. **Every hit is either updated or explained in `progress.md`** —
a `grep` that still returns something after this task is the failure mode.

`npm run build` is the real check: Next.js resolves `<Link href>` at build time, so a link
to a deleted route surfaces there rather than at runtime. **Run it in this task** even
though the full verification is T12.

## Watch for

- **The three-groups sidebar contract still holds** — groups default open, the active
  group is forced open, and the Triage badge rolls onto its group header only while that
  group is shut. This task changes one group's contents, not the mechanism.
- **`NAV_GROUPS_KEY` is versioned** (`admin-nav-groups-v1`). Group *ids* are unchanged
  here, so a saved open/shut map stays valid — do not bump it.
- **Do not add a redirect.** Decision 10 is removal. A redirect from a URL nobody can
  reach any more is dead code that reads like a supported path.
- **`/admin/trade` with no `mode` must still work** — it is the plain Trade entry and the
  dashboard's third quick action.

## Done means

1. both test files pass, output shown;
2. `grep -rn "admin/buy\|admin/sell" frontend/` returns nothing unexplained;
3. `cd frontend && npm run build` exits 0;
4. `npm run lint --workspace=frontend` clean;
5. by hand: every sidebar and dashboard route resolves, on desktop and at mobile width;
6. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
