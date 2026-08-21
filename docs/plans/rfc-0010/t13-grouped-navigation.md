# T13 — Sixteen flat tabs become three groups

**RFC:** 0010 §K · **Layer:** frontend · **Depends on:** — · **Blocks:** —
**Owner report:** plan doc item 12 — *"Create Larger tabs to hold sub tabs for this. Ex. 'Show'
would hold our inventory, buy, sell, trade, slabs tabs"*

## The grouping — owner's choice, 2026-08-10

Offered three groupings, the owner picked **At the show / Back office / Data**:

| Group | Tabs |
|---|---|
| *(top level)* | Dashboard |
| **At the show** | Inventory · Sell · Buy · Trade · Slabs |
| **Back office** | Prep Queue · Show Prep · Shows · Triage · Market · Vault |
| **Data** | Show Analytics · History · Cosigners · Locations |

Grouped by **when you use them**, which is why Inventory sits with the transaction tabs rather
than with Vault. Keep the within-group order above — it is the current `navItems` order preserved
wherever possible, so muscle memory survives.

## Files

- **Modify:** `frontend/components/admin/AdminShell.tsx`
- **Tests:** `frontend/components/admin/__tests__/AdminShell.test.tsx`

## Constraints — each of these is a way to get this wrong

**1. Every route path is unchanged.** No renames, no redirects, no nested routes. Grouping is a
sidebar concern; nesting the URLs would break every bookmark and doc reference to fix a URL nobody
types. **`/admin/outgoing` keeps its misleading path** even though it is labelled *Prep Queue* —
CLAUDE.md already documents that gotcha, and relabelling the URL is a separate decision.

**2. The Triage badge keeps working, including when its group is collapsed.** It lives in
**Back office**. A count nobody can see is the exact failure the badge was built to avoid — the
comment at `AdminShell.tsx:55-60` says so. When a group is collapsed, its header carries the
rolled-up badge.

*(Open question in `progress.md`: roll the badge onto the header when the group is **expanded**
too, or only when collapsed? Only-when-collapsed is less noisy. Pick one and record it.)*

**3. The collapsed sidebar still has to work.** At 60px the sidebar is icon-only
(`AdminShell.tsx:88`). Group *headers* have no icon, so in that state they become thin dividers,
or a `title`-tooltip label — **not** truncated text. Do not let collapse+groups produce a column
of unreadable stubs.

**4. The group containing the active route starts expanded.** `isActive` is a
`pathname.startsWith` test (`AdminShell.tsx:70-73`); reuse it to decide the initial open group.
Landing on a page whose group is collapsed, with no visible indication of where you are, is worse
than the flat list.

**5. Expansion state persists.** `localStorage`, under a **versioned** key
(`admin-nav-groups-v1`), so a later grouping change cannot silently resurrect a saved shape that no
longer matches. Same discipline as the column-visibility key from RFC 0008.

**6. The mobile nav becomes an explicit array.** It currently takes `navItems.slice(0, 5)`
(`AdminShell.tsx:166`). Flattening a nested structure and slicing it silently changes what a phone
shows, and nobody would notice. Declare the five explicitly — recommend Dashboard, Inventory,
Sell, Buy, Slabs (the show-floor five), which is what the current slice happens to produce minus
Trade.

## Design

Restructure `navItems` into groups while keeping each item's existing shape
(`{ href, label, icon, badge? }`) so the link rendering is untouched:

```ts
const navGroups = [
  { id: 'show',   label: 'At the show', items: [...] },
  { id: 'office', label: 'Back office', items: [...] },
  { id: 'data',   label: 'Data',        items: [...] },
]
const topLevel = [{ href: '/admin', label: 'Dashboard', icon: LayoutDashboard }]
```

Accessibility, and it is cheap here: the group header is a `<button>` with `aria-expanded`
controlling a region — not a `<div>` with an `onClick`. The sidebar is keyboard-navigated by
anyone using it one-handed at a show table.

Keep the group headers visually quiet — this is chrome, not content. The existing
`font-mono text-[11px] uppercase tracking-[0.18em] text-mint` treatment used for the "Admin"
header (line 94) is the vocabulary already in the file; reuse it rather than inventing a heading
style.

**Multiple groups may be open at once.** An accordion that closes one group to open another turns
every cross-group jump into two clicks, which is worse than the flat list it replaces.

## RED — write these first, show the failing output, wait for confirmation

1. all sixteen destinations are still reachable, at their **existing hrefs** — enumerate them and
   assert each one, since a dropped tab in a restructure is silent;
2. the three group headers render;
3. clicking a header toggles `aria-expanded` and shows/hides its items;
4. **the group containing the current route starts expanded** (render at `/admin/triage`, assert
   Back office is open);
5. the Triage badge renders when `total > 0`, and **is visible on the group header when the group
   is collapsed**;
6. no badge renders when `total == 0` — the pre-existing rule;
7. expansion state round-trips through `localStorage`;
8. the collapsed (60px) sidebar renders without truncated group labels;
9. **the mobile nav renders exactly five explicit entries**, not a slice.

**Command corrected as executed** — the `npx vitest` form is broken in this repo:

```bash
npm test --workspace=frontend -- --run components/admin/__tests__/AdminShell
```

## GREEN — done when

The above pass, every pre-existing `AdminShell` test passes, and
`npm run lint --workspace=frontend` is clean. Also `grep` the codebase for `navItems` — if
anything outside this file imports it, that consumer needs updating and is not covered by these
tests.

## Manual check

Click through all sixteen tabs. Collapse the sidebar and confirm it is still navigable and the
Triage count is still visible. Reload and confirm your expansion state survived. Then check a
phone-width viewport.

## Do not

- Do not rename or redirect any route.
- Do not nest the URLs.
- Do not lose a tab. Count them: sixteen destinations, fifteen in groups plus Dashboard.
- Do not hide the Triage count behind a collapsed group.
- Do not make the groups an accordion.
- Do not leave the mobile nav as a `.slice()`.
- Do not use an unversioned `localStorage` key.

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

**T14 — Docs stop describing a PSA integration that will never exist**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t14-docs-and-ops.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
