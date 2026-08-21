# Task B2: Unblock Graded Manual Entry in `IncomingCardForm` (Trade + Buy)

**Files:**
- Modify: `frontend/components/admin/deal/IncomingCardForm.tsx`
- Modify: `frontend/app/(admin)/admin/trade/page.tsx:380`
- Modify: `frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx`
- Test: same test file (RED then GREEN)

**Interfaces:**
- Consumes: nothing new. `IncomingCardForm`'s existing props
  (`card: PickerCard | null`, `onAdd`, `onCancel`, `gradedAllowed?: boolean`)
  are unchanged in shape — only the internal gating logic changes.
- Produces: nothing new consumed by other tasks. C4 (buy/trade consignor
  assignment) also touches this file later — different sections (C4 adds a
  new "Consignor" block; this task only changes the `gradedSelectable`
  derivation and two explanatory `<span>`s). Do this task first or in
  parallel; C4 should read the post-B2 version of the file before starting.

## Context

Two independent gates currently keep a graded incoming leg from being
submitted as graded: `!manual` (blocks any manual/no-catalog-match entry)
and `!gradedAllowed` (blocks Buy mode entirely, regardless of catalog
match). Both are lifted per RFC 0012 section B — the backend rule they were
guarding (B1) is already gone, and the cert-ownership warning UI they were
"pending" (`IncomingCardForm.tsx:101-123`, the debounced `GET
/slabs/certs/{cert}` check) already exists and is gated only on `kind ===
'graded'`, not on `manual` or the mode — it becomes reachable the moment
these two gates are removed, with no code changes of its own needed.

- [ ] **Step 1: Write the failing tests — replace the two regression tests that assert the old (now-wrong) behavior**

In `frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx`,
find and replace this test (around line 173-177):

```tsx
  it('forces manual entry to raw, and says why', () => {
    render(<IncomingCardForm card={null} onAdd={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /graded/i })).toBeDisabled()
    expect(screen.getByText(/needs a catalog card/i)).toBeInTheDocument()
  })
```

with:

```tsx
  it('allows Graded to be selected on a manual (no catalog match) entry', () => {
    render(<IncomingCardForm card={null} onAdd={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /graded/i })).toBeEnabled()
    expect(screen.queryByText(/needs a catalog card/i)).not.toBeInTheDocument()
  })

  it('emits a manual GRADED leg with a null card_id when Graded is picked', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={null} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.type(screen.getByLabelText(/card name/i), 'Mystery Charizard')
    await user.type(screen.getByLabelText(/^grade$/i), '10')
    await user.type(screen.getByLabelText(/cert number/i), '99')
    await user.type(screen.getByLabelText(/value/i), '400')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ card_id: null, kind: 'graded', company: 'PSA', grade: 10 }),
    )
  })

  it('runs the cert-owned check for a manual graded entry (it was already wired, just unreachable)', async () => {
    const user = userEvent.setup({ delay: null })
    mockCertOwned('99')
    render(<IncomingCardForm card={null} onAdd={vi.fn()} onCancel={vi.fn()} />)
    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.type(screen.getByLabelText(/cert number/i), '99')
    expect(await screen.findByText(/you already own cert/i)).toBeInTheDocument()
  })
```

Find and replace this test (around line 191-204):

```tsx
  it('disables Graded and says why when gradedAllowed is false (Buy mode, Critical 1 regression)', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} gradedAllowed={false} />)

    expect(screen.getByRole('radio', { name: /graded/i })).toBeDisabled()
    expect(screen.getByText(/graded intake isn't available from buy/i)).toBeInTheDocument()

    // Even if `kind` state were somehow 'graded', submit must still emit raw
    // — the toggle disable is not the only line of defense.
    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ kind: 'raw' }))
  })
```

with:

```tsx
  it('allows Graded to be selected in Buy mode too (RFC 0012 reverses the prior Buy-mode block)', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} gradedAllowed={true} />)

    expect(screen.getByRole('radio', { name: /graded/i })).toBeEnabled()
    expect(screen.queryByText(/graded intake isn't available from buy/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /graded/i }))
    await user.type(screen.getByLabelText(/^grade$/i), '9')
    await user.type(screen.getByLabelText(/cert number/i), '55')
    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ kind: 'graded' }))
  })
```

Note `gradedAllowed={true}` is passed explicitly above even though it's
already the prop's default — this documents the call site's intent
alongside the deleted-test's shape, and keeps the test meaningful even if a
future change flips the default.

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run components/admin/deal/__tests__/IncomingCardForm.test.tsx --reporter=verbose
```
Expected: the four new/changed tests FAIL (the radio is still disabled; the
old explanatory text is still present).

- [ ] **Step 3: Remove the manual gate and the two explanatory spans**

In `frontend/components/admin/deal/IncomingCardForm.tsx`, change line 129:

```tsx
  const gradedSelectable = !manual && gradedAllowed
```

to:

```tsx
  // RFC 0012: manual entry (no catalog match) can be graded — Slabs intake
  // never gated this, and the Trade-specific backend rule that used to
  // require a card_id for a graded leg (Decision 14) is gone (see
  // routers/admin/trades.py). gradedAllowed itself now only reflects
  // whatever a specific caller still wants to withhold, if anything.
  const gradedSelectable = gradedAllowed
```

Delete the manual-only explanatory span (around lines 243-249):

```tsx
        {manual && (
          // A disabled control with no explanation is the thing this codebase
          // deletes. One line, right next to it.
          <span className="text-[11px] text-pine-400">
            Graded needs a catalog card — its price joins on the card id.
          </span>
        )}
```

Delete the Buy-mode explanatory span (around lines 250-254):

```tsx
        {!manual && !gradedAllowed && (
          <span className="text-[11px] text-pine-400">
            Graded intake isn&apos;t available from Buy yet — use Slabs.
          </span>
        )}
```

Update the radio's `disabled` condition comment (around line 232-236) since
the `!manual` half of the reasoning it describes no longer applies:

```tsx
              // T13 422s a raw leg carrying graded fields, but a graded leg no
              // longer needs a card_id (RFC 0012) — `gradedSelectable` now
              // just mirrors `gradedAllowed`, which defaults to true and is
              // only false if a future caller explicitly withholds graded.
              disabled={k === 'graded' && !gradedSelectable}
```

Update the file's top doc comment (lines 13-25) — it currently states
"Decision 14: 'regardless you should be picking a card from the catalog...'"
as settled fact. Replace the paragraph starting "Decision 14 is..." with:

```tsx
 * RFC 0012 reverses Decision 14: a graded leg no longer requires a catalog
 * pick. Manual entry (no catalog match) can now be graded, matching how
 * `/admin/slabs` intake has always worked — an unmatched graded item lands
 * unpriced and self-routes to Triage (services/triage.py's
 * is_missing_card_id), the same state a JP slab is already in.
 *
```

Update the `card` prop's doc comment (line 49, `/** `null` == manual entry.
A manual entry can only ever be RAW. */`) to drop the now-false second
sentence:

```tsx
  /** `null` == manual entry (no catalog match). */
```

Update the `gradedAllowed` prop's doc comment (lines 53-64) to drop the
stale "this stays off until that lands" reasoning — replace with:

```tsx
  /**
   * Presentational gate only — which controls the form shows. Defaults to
   * `true`. RFC 0012 removed the Buy-mode-specific block this used to carry
   * (the cert-ownership warning it was "pending" already existed and is
   * gated on `kind === 'graded'` alone, at lines ~101-123 below — it just
   * wasn't reachable while this defaulted to `false` for Buy). Kept as a
   * prop, not deleted, in case a future caller needs to withhold graded for
   * a reason unrelated to this one.
   */
```

- [ ] **Step 4: Update the call site**

In `frontend/app/(admin)/admin/trade/page.tsx:380`, change:

```tsx
              gradedAllowed={mode !== 'buy'}
```

to:

```tsx
              gradedAllowed={true}
```

Grep first for any other consumer of `IncomingCardForm`'s `gradedAllowed`
prop before this step:

```bash
grep -rn "gradedAllowed" frontend/app frontend/components
```

If `trade/page.tsx` is the only non-test call site (expected, per RFC 0012's
investigation), leave the prop itself in place with its `true` default
rather than deleting it — removing a prop that tests still reference for
documentation purposes is unnecessary churn for this task; note in the
commit message that the prop is now vestigial-but-harmless if no caller ever
passes `false`.

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run components/admin/deal/__tests__/IncomingCardForm.test.tsx frontend/app/\(admin\)/admin/trade/__tests__/page.test.tsx --reporter=verbose
```
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/admin/deal/IncomingCardForm.tsx frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx "frontend/app/(admin)/admin/trade/page.tsx"
git commit -m "fix(rfc-0012): allow graded manual entry in Trade and Buy mode"
```
