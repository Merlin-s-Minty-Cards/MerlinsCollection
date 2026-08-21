# T6 — The detail modal stays usable when you zoom

**RFC:** 0010 §D · **Layer:** frontend · **Depends on: T5** (same file) · **Blocks:** —
**Owner report:** plan doc items 5 **and** 7

## The report

Item 5:

> *"it forces the size of the image so when you zoom in our our it just keeps the same size of
> the image and shoves the text to the side … because the card art is so large the fields don't
> have room to show the data and when you click on one of them the text box is forced to be in
> the label over, in this example for hydreigon ex when i try to edit the finish field it puts
> characters into the factory sealed label and the box to add text is very small, i would
> scaling with resolution attempt to give the words on the right more room and just expand the
> popup"*

Item 7:

> *"When clicking on a card's image in Prepare for Shows, it doesn't allow room, and the picture
> is forced to be an even higher percentage of the screen"*

**Item 7 is the same component at a different zoom level, not a second bug.**
`/admin/show-prep` mounts `CardDetailModal` like the other five pages; there is no show-prep
modal. Both reports are fixed by one change and must be verified on both pages.

## Confirmed root cause — three compounding layout decisions

All in `frontend/components/admin/shared/CardDetailModal.tsx`:

1. **The shell is capped and does not grow.** `max-w-4xl h-[90vh]` (line 271) — 896px however
   large the display. Zooming in shrinks the *available* CSS pixels without the modal ever
   getting proportionally more room.
2. **The image column cannot yield.** `flex-shrink-0` (line 405) wrapping an `img` at
   `h-64 md:h-full w-auto object-contain` (line 410). At `h-full` inside a 90vh shell, a 5:7
   card claims ≈**0.71 × 90vh of width**, and `flex-shrink-0` means it never gives any of it
   back. The details column gets whatever remains — which is what "shoves the text to the side"
   describes.
3. **The field grid is viewport-driven, not container-driven.**
   `grid-cols-1 sm:grid-cols-2` (line 466) keys off the **viewport**, so it stays two-up no
   matter how narrow the *column* becomes, and each cell carries a fixed `w-24` label (line
   489). Once a cell is under ≈200px the label owns most of it and the input is compressed to
   near-zero width.

That is the "characters go into the factory sealed label" symptom exactly: the input has not
moved into the neighbouring cell — it has been squeezed until it renders beside the adjacent
label. `Finish` and `Factory Sealed` are consecutive fields in the same section
(`EDITABLE_FIELDS`, lines 78-79), which is why that pair is the one the owner hit.

## Files

- **Modify:** `frontend/components/admin/shared/CardDetailModal.tsx`
- **Tests:** `frontend/components/admin/shared/__tests__/CardDetailModal.test.tsx`

## Design

**Widen the shell and let it scale with the display:**

```
max-w-6xl xl:max-w-7xl h-[92vh]
```

**Cap the image and let it yield.** Replace `flex-shrink-0` with a bounded, shrinkable column:

```
md:max-w-[min(34%,20rem)] min-w-0        // on the image column
min-w-0                                  // on the details column (already present)
```

The `min()` is what makes it behave at both extremes: a percentage alone lets the image grow
without limit on a wide display, and a rem cap alone lets it dominate a narrow one. The details
column now has a floor.

**Make the field grid container-driven:**

```
[grid-template-columns:repeat(auto-fit,minmax(17rem,1fr))]
```

replacing `grid-cols-1 sm:grid-cols-2`. The grid collapses to one column whenever a cell would
be narrower than 17rem — **at any zoom, with no breakpoint to tune**. This is the change that
actually fixes the owner's report; the other two make it comfortable.

If Tailwind container queries (`@container` / `@lg:`) are available in this project's version,
they are a cleaner expression of the same idea — check `tailwind.config` before reaching for the
arbitrary-value form, and prefer whichever the codebase already uses elsewhere.

**Stack label over value in a narrow cell** rather than keeping a fixed `w-24` beside it. The
textarea rows already do exactly this (`flex-col items-stretch`, line 484), so follow that
pattern rather than inventing a second one.

**While you are in here** (all inside the reported symptom, none of it scope creep):

- the image already has `object-contain`; keep it, and add `max-h-full` so the cap cannot be
  defeated by a tall image;
- the no-image placeholder is a hardcoded `w-72 h-[25.75rem] flex-shrink-0` (line 419) — it must
  get the same treatment as the real image, or the layout is correct only for cards that *have*
  art.

## What a test can and cannot prove

A jsdom test can assert the class contract — the shell's max-width, the image column's cap, the
grid template, the absence of `flex-shrink-0`. It **cannot** tell you whether the finish field is
typeable at 175% zoom in Chrome. So the tests are a regression lock on the decisions, and the
**manual check below is the actual acceptance criterion.** Do not substitute one for the other.

## RED — write these first, show the failing output, wait for confirmation

1. the shell renders at `max-w-6xl` (not `max-w-4xl`);
2. the image column is **not** `flex-shrink-0` and carries a max-width cap;
3. the field grid uses the auto-fit template, **not** `sm:grid-cols-2`;
4. the no-image placeholder is shrinkable too (no `flex-shrink-0`, no fixed `w-72`);
5. every field row still renders its label and its value — the regression gate, since a layout
   change is exactly where a field quietly disappears;
6. the textarea fields still span the full row.

```bash
# `npx vitest` fails with "Vitest failed to find the runner" — use the workspace form.
npm test --workspace=frontend -- run components/admin/shared/__tests__/CardDetailModal --reporter=verbose
```

## GREEN — done when

The above pass, every pre-existing `CardDetailModal` test passes, and
`npm run lint --workspace=frontend` is clean.

## Manual check — this IS the acceptance criterion

Run the app. On **all three** of `/admin/triage`, `/admin/show-prep` and `/admin/inventory`,
open a card and at **100%, 150% and 200%** browser zoom confirm:

- the image never occupies more than about a third of the modal;
- **click the Finish field and type — the characters go into the Finish input**, and the input
  is wide enough to read (this is the owner's exact test case: Hydreigon ex #240);
- the fields collapse to a single column when the column is narrow, instead of staying two-up
  and squeezing;
- long values (`item_id`, `tcg_url`) truncate rather than forcing the column wider;
- a card with **no** art lays out the same way.

Check a `graded` item too — it renders three extra Identity fields (`company`, `grade`,
`cert_number`), so it is the densest section in the component.

## Do not

- Do not fix this with a viewport breakpoint. The report is about **zoom**, which changes the
  container without changing the breakpoint in the way you would expect.
- Do not remove fields to make room. Every one of them was added deliberately in RFC 0008 T5.
- Do not leave the no-image placeholder at a fixed size.
- Do not touch `/admin/card/[id]`, which duplicates this layout. Filed in
  [`follow-ups.md`](follow-ups.md) — the right fix there is to share a component, which is a
  refactor, not this bug fix.
- Do not claim this done off the test suite alone.

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

**T7 — Prep Queue sorts and filters by location**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t7-prep-queue-location.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
