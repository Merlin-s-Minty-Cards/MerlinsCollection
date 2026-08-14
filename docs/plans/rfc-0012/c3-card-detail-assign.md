# Task C3: Assign/Unassign a Cosigner from `CardDetailModal`

**Files:**
- Modify: `frontend/components/admin/shared/CardDetailModal.tsx`
- Test: `frontend/components/admin/shared/__tests__/CardDetailModal.test.tsx`

**Interfaces:**
- Consumes: `CosignorPicker` (default export) from
  `frontend/components/admin/shared/CosignorPicker.tsx` (Task C1) — cannot
  start until C1 exists.
- Produces: nothing consumed by other tasks.

## Context

`CardDetailModal.tsx` already renders a **read-only** Consignment section
(around lines 758-800) with a comment explaining why it's read-only: routing
an edit through the modal's generic single-field editor
(`payload = { [editingField]: value }` against `PUT /admin/inventory/{id}`)
would require the frontend to reinvent `POST /admin/cosigners/{id}/link`'s
default-split-percent logic (`cosigners.py:221`,
`(100 - consignor.payout_percent) / 100`), risking silently dropping
`paid_out` or mis-setting `split_percent`. This task adds real assign/unassign
controls that call the existing, tested cosigner endpoints directly instead
— **no backend changes**, both endpoints already exist:

- Assign: `POST /admin/cosigners/{consignor_id}/link` with
  `{ "item_ids": [item_id] }` (optional `split_percent`/`minimum_price`
  overrides; the endpoint fills sensible defaults if omitted).
- Unassign: `DELETE /admin/cosigners/{consignor_id}/assets/{item_id}`.

Neither endpoint returns the full updated item (they return
`{linked, consignor_id, failed_item_ids}` and `{status, item_id}`
respectively), so this task calls `onUpdated()` with **no** argument after a
successful assign/unassign — the modal's own docstring
(`CardDetailModal.tsx:22-31`) already documents this as the correct shape
for "something changed, but I cannot tell you what," which is exactly this
case (a refetch is the parent's job, same as it already is for the existing
triage-clear flow at `writeTriage`, which does return a full item and calls
`setCurrent` directly — this task's assign/unassign do not have that luxury,
so they use the `onUpdated()`-with-no-args path instead).

- [ ] **Step 1: Write the failing test**

Check `frontend/components/admin/shared/__tests__/CardDetailModal.test.tsx`'s
existing mock setup (it already mocks `useAdminApi`, per the earlier grep
finding `useLocations: () => ({...})` around line 27 — find the matching
`useAdminApi` mock nearby) and match its shape. Add a mock for
`@/lib/use-cosigners` alongside the existing `useLocations` mock:

```tsx
vi.mock('@/lib/use-cosigners', () => ({
  useCosigners: () => ({
    options: [{ value: 'cos-1', label: 'Alex' }],
    loading: false,
  }),
}))
```

Add these tests to the file's `describe` block:

```tsx
  it('shows an "Assign consignor" control when the item has no consignment', () => {
    render(<CardDetailModal item={{ item_id: 'i1', name: 'Charizard' }} onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: /assign consignor/i })).toBeInTheDocument()
  })

  it('links the item to a cosigner and refetches', async () => {
    const user = userEvent.setup({ delay: null })
    const postMock = vi.fn().mockResolvedValue({ linked: 1, consignor_id: 'cos-1', failed_item_ids: [] })
    mockApi.post = postMock // match however this file's existing tests reach the mocked api.post
    const onUpdated = vi.fn()
    render(<CardDetailModal item={{ item_id: 'i1', name: 'Charizard' }} onClose={vi.fn()} onUpdated={onUpdated} />)

    await user.click(screen.getByRole('button', { name: /assign consignor/i }))
    await user.click(screen.getByRole('combobox', { name: /consignor/i }))
    await user.click(screen.getByText('Alex'))
    await user.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/cosigners/cos-1/link', { item_ids: ['i1'] }))
    expect(onUpdated).toHaveBeenCalledWith()
  })

  it('shows an "Unassign" control and unlinks a consigned item', async () => {
    const user = userEvent.setup({ delay: null })
    const delMock = vi.fn().mockResolvedValue({ status: 'unlinked', item_id: 'i1' })
    mockApi.del = delMock
    const onUpdated = vi.fn()
    render(
      <CardDetailModal
        item={{ item_id: 'i1', name: 'Charizard', consignment: { consignor_id: 'cos-1', split_percent: '0.5' } }}
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    )

    await user.click(screen.getByRole('button', { name: /unassign consignor/i }))

    await waitFor(() => expect(delMock).toHaveBeenCalledWith('/cosigners/cos-1/assets/i1'))
    expect(onUpdated).toHaveBeenCalledWith()
  })
```

Read the actual existing mock variable names in this test file first (it
may call its mocked `useAdminApi()` return value something other than
`mockApi` — match whatever pattern the file's other `api.put` assertions
already use, e.g. `putMock`/`postMock` module-level `vi.fn()`s like
`IncomingCardForm.test.tsx`'s `getMock`, rather than the `mockApi.post = ...`
shorthand sketched above if the file's real convention differs).

- [ ] **Step 2: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run components/admin/shared/__tests__/CardDetailModal.test.tsx --reporter=verbose
```
Expected: FAIL — no "Assign consignor" / "Unassign consignor" buttons exist yet.

- [ ] **Step 3: Implement the assign/unassign controls**

In `frontend/components/admin/shared/CardDetailModal.tsx`, add the import:

```tsx
import CosignorPicker from './CosignorPicker'
```

Add state near the other panel-toggle state (alongside `triagePanel` around
line 167-169):

```tsx
  const [consignorPanel, setConsignorPanel] = useState(false)
  const [pendingConsignorId, setPendingConsignorId] = useState<string | null>(null)
  const [consignorSaving, setConsignorSaving] = useState(false)
  const [consignorError, setConsignorError] = useState<string | null>(null)
```

Add handlers near `writeTriage` (same `useCallback` pattern, reading `item`
from the same closure the existing handlers use):

```tsx
  const assignConsignor = useCallback(async () => {
    if (!item || !pendingConsignorId) return
    setConsignorSaving(true)
    setConsignorError(null)
    try {
      await api.post(`/cosigners/${pendingConsignorId}/link`, { item_ids: [item.item_id] })
      setConsignorPanel(false)
      setPendingConsignorId(null)
      onUpdated?.()
    } catch (e) {
      setConsignorError(e instanceof AdminApiError ? e.message : 'Could not assign consignor.')
    } finally {
      setConsignorSaving(false)
    }
  }, [api, item, pendingConsignorId, onUpdated])

  const unassignConsignor = useCallback(async () => {
    if (!item || !consignment) return
    setConsignorSaving(true)
    setConsignorError(null)
    try {
      await api.del(`/cosigners/${String(consignment.consignor_id)}/assets/${item.item_id}`)
      onUpdated?.()
    } catch (e) {
      setConsignorError(e instanceof AdminApiError ? e.message : 'Could not unassign consignor.')
    } finally {
      setConsignorSaving(false)
    }
  }, [api, item, consignment, onUpdated])
```

Check the exact name of the `item` variable available in this scope — the
existing `writeTriage` callback closes over `item` directly (the prop), per
`CardDetailModal.tsx:267-278`; `consignment` (the derived read-only object,
`CardDetailModal.tsx:319-322`) is defined further down the render body, so if
`assignConsignor`/`unassignConsignor` are declared before that line, either
move them below it or read `shown.consignment` directly instead of the
`consignment` local — match whichever the surrounding code makes easiest
without reordering unrelated hooks.

Extend the Consignment section (around lines 758-800) — currently only
rendered `{consignment && (...)}`. Change the wrapping condition so the
section (or an assign prompt) always renders, and add the controls:

```tsx
          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
              Consignment
            </h3>
            {consignment ? (
              <>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(min(17rem,100%),1fr))] gap-2">
                  {/* ...existing four read-only rows, unchanged... */}
                </div>
                <button
                  type="button"
                  disabled={consignorSaving}
                  onClick={unassignConsignor}
                  className="mt-2 text-[11px] text-red-400 hover:text-red-300 disabled:opacity-50"
                >
                  Unassign consignor
                </button>
              </>
            ) : consignorPanel ? (
              <div className="flex flex-col gap-2">
                <CosignorPicker value={pendingConsignorId} onChange={setPendingConsignorId} />
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={consignorSaving || !pendingConsignorId}
                    onClick={assignConsignor}
                    className="rounded-lg border border-mint/30 bg-mint/15 px-3 py-1.5 text-xs font-medium text-mint disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConsignorPanel(false)
                      setPendingConsignorId(null)
                      setConsignorError(null)
                    }}
                    className="text-[11px] text-pine-400 hover:text-pine-100"
                  >
                    Cancel
                  </button>
                </div>
                {consignorError && <p role="status" className="text-xs text-red-300">{consignorError}</p>}
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConsignorPanel(true)}
                className="text-[11px] text-mint hover:text-mint/80"
              >
                Assign consignor
              </button>
            )}
          </section>
```

- [ ] **Step 4: Run it to verify it passes**

Run:
```bash
npx vitest run components/admin/shared/__tests__/CardDetailModal.test.tsx --reporter=verbose
```
Expected: PASS.

- [ ] **Step 5: Run the full frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/admin/shared/CardDetailModal.tsx frontend/components/admin/shared/__tests__/CardDetailModal.test.tsx
git commit -m "feat(rfc-0012): assign/unassign a consignor from CardDetailModal"
```
