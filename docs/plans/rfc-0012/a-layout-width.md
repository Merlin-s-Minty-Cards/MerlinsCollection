# Task A: Admin Page Width Consistency

**Files:**
- Modify: `frontend/app/(admin)/admin/page.tsx:114`
- Modify: `frontend/app/(admin)/admin/locations/page.tsx:106`
- Modify: `frontend/app/(admin)/admin/analytics/page.tsx:324,425`
- Modify: `frontend/app/(admin)/admin/market/page.tsx:362`
- Modify: `frontend/app/(admin)/admin/history/page.tsx:342`
- Modify: `frontend/app/(admin)/admin/cosigners/page.tsx:441`
- Modify: `frontend/app/(admin)/admin/inventory/page.tsx:304`
- Modify: `frontend/app/(admin)/admin/shows/page.tsx:254`
- Modify: `frontend/app/(admin)/admin/card/[id]/page.tsx:161,169,186`
- Modify: `frontend/app/(admin)/admin/outgoing/page.tsx:473`
- Modify: `frontend/app/(admin)/admin/show-prep/page.tsx:364`
- Modify: `frontend/app/(admin)/admin/vault/page.tsx:241`
- Modify: `frontend/app/(admin)/admin/unmatched/page.tsx:378`
- Modify: `frontend/app/(admin)/admin/triage/page.tsx:382`
- Modify: `frontend/app/(admin)/admin/trade/page.tsx:290,317`
- Test: existing page test suites for the pages above (run as regression, no new test file)

**Interfaces:** None — pure CSS class removal, no new exports or props.

Line numbers above are as of the RFC 0012 investigation (2026-08-14) and may
have drifted by a line or two from unrelated edits since. If a line doesn't
match, grep the file for `max-w-` to relocate the wrapper.

- [ ] **Step 1: Confirm the current, inconsistent state (this IS the "red" for a mechanical task)**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary"
grep -n "p-6 lg:p-8 max-w-" frontend/app/\(admin\)/admin/**/*.tsx
```
Expected: every file above shows up with a `max-w-{3xl,5xl,6xl,7xl}` value.
`frontend/app/(admin)/admin/slabs/page.tsx` will NOT appear — it's already
uncapped, confirming the target end state.

- [ ] **Step 2: Remove the cap from each page wrapper**

For each file/line above, change the wrapper `div`'s className from e.g.

```tsx
<div className="p-6 lg:p-8 max-w-7xl">
```

to

```tsx
<div className="p-6 lg:p-8">
```

Apply this to every occurrence listed (note `analytics/page.tsx`,
`card/[id]/page.tsx`, and `trade/page.tsx` each have more than one — a
loading-state wrapper, an error-state wrapper, and/or a loaded-state
wrapper. All of them lose the cap, not just the "happy path" one).

**Do NOT touch** any of the following, which are dialogs/modals, not the
page itself, and are correctly capped:
- `cosigners/page.tsx:600,695` (`max-w-md`)
- `inventory/page.tsx:597` (`max-w-md`)
- `shows/page.tsx:297` (`max-w-md`)
- `unmatched/page.tsx:552`, `triage/page.tsx:1298` (`max-w-2xl`)
- `history/page.tsx:360,414,452` (`max-w-lg`, search dropdown panels)
- `outgoing/page.tsx:375`, `show-prep/page.tsx:495` (`max-w-28`/`max-w-48`,
  small inline field widths, unrelated to page layout)

- [ ] **Step 3: Verify no test asserts a specific max-width class**

Run:
```bash
cd frontend
npx vitest run --reporter=verbose 2>&1 | grep -i "max-w-7xl\|max-w-6xl\|max-w-5xl\|max-w-3xl"
```
Expected: no output (no test references these classes as an assertion
target). If a test IS found asserting one of these classes, update it in
this same step to assert the wrapper's absence instead, or drop the
assertion if it was only ever checking for the presence of `p-6 lg:p-8`
(keep that part, drop the `max-w-*` part).

- [ ] **Step 4: Run the frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS, same pass count as before this task (no regressions — this
change touches only layout classes, not component logic or test-visible
markup structure).

- [ ] **Step 5: Manual/visual check (frontend running)**

Start the dev server (`npm run dev --workspace=frontend`), sign in as an
admin, and open a page from the "Back office"/"Data" sidebar groups (e.g.
`/admin/cosigners`, `/admin/locations`) at a wide (>1600px) browser window.
Confirm the content now stretches to fill the viewport the same way
`/admin/slabs` already does, with no visible layout breakage (tables don't
overflow oddly, no giant empty gutters reappearing).

- [ ] **Step 6: Commit**

```bash
git add frontend/app/\(admin\)/admin
git commit -m "fix(rfc-0012): unify admin page width, drop inconsistent max-w caps"
```
