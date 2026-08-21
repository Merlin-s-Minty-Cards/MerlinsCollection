# Task C4: Assign a Cosigner While Adding an Incoming Card (Buy/Trade)

**Files:**
- Modify: `backend/src/merlins_collection/routers/admin/trades.py` (add
  `item_ids` to the confirm response — see correction below)
- Test: `backend/tests/routers/admin/test_trades.py`
- Modify: `frontend/lib/trade-incoming-form.ts` (`IncomingLeg` gains an
  optional client-side-only `consignor_id`)
- Modify: `frontend/components/admin/deal/IncomingCardForm.tsx` (add a
  collapsed "Consignor" section)
- Modify: `frontend/app/(admin)/admin/trade/page.tsx` (stage the consignor
  per leg; after confirm, fire link calls for staged legs that had one)
- Test: `frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx`
- Test: `frontend/app/(admin)/admin/trade/__tests__/page.test.tsx`

**Interfaces:**
- Consumes: `CosignorPicker` from
  `frontend/components/admin/shared/CosignorPicker.tsx` (Task C1) — cannot
  start until C1 exists. Also touches `IncomingCardForm.tsx`, which Task B2
  also modifies (different sections — B2 changes the graded-gate logic
  around lines 129/232-254; this task adds a new section below the existing
  fields). Read the file post-B2 before starting this task to avoid
  reintroducing the deleted gate logic by accident.
- Produces: nothing consumed by other tasks.

## Correction to RFC 0012

The RFC assumed `POST /admin/trades/{trade_id}/confirm`'s response already
includes `item_ids` (citing `deal-session.ts:39-43`'s `ConfirmResult` type
comment, "Trade's commit path — what T13's graded-price verification reads
back"). **This is not actually true today** — grepping
`trades.py` for `item_ids` finds nothing; the confirm response currently
returns `{trade_id, status, outgoing_count, incoming_count, total_out_value,
total_in_value, transactions_created, items_created, items_sold}` with no
item id list. The RFC's "open question" about `purchases.py` was
answered correctly (it already returns `item_ids` at
`purchases.py:438`) but the same check was not actually run against
`trades.py`. This task adds it.

## Context

Neither `purchases.py`'s item-add endpoint nor `trades.py`'s incoming-leg
endpoint accepts `consignment` at creation time, and per RFC 0012 that's
not changing (it would duplicate `cosigners.py:221`'s default-split-percent
logic). Instead: the operator picks a consignor per incoming card in the
form; the choice is staged client-side only; after the deal commits, the
page fires `POST /admin/cosigners/{id}/link` once per item that had a
consignor staged, un-awaited, matching the existing "commit succeeds and is
reported first, a secondary call happens after" pattern already used for
slab price refresh.

`trades.py`'s incoming legs and the resulting inventory items are created in
strict positional order — `for index, leg in enumerate(incoming):` at
`trades.py:824` builds one item per leg in the same order the legs were
added — so the created `item_ids` list, once added, is index-aligned with
the trade session's `incoming_legs` list, which is index-aligned with the
frontend's own `incoming` staged-array state
(`app/(admin)/admin/trade/page.tsx:154`, appended in `handleAddIncoming` in
the same order `addIncoming` was called). `purchases.py`'s items follow the
same one-POST-per-card, append-in-order shape. This positional correlation
is what lets the frontend pair a staged consignor choice back to the item
id that resulted from it, without either backend endpoint needing to accept
`consignment` directly.

---

## Part 1 — Backend: add `item_ids` to the trade confirm response

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/routers/admin/test_trades.py`, in the class containing
`test_confirm_full_trade`:

```python
    def test_confirm_returns_item_ids_for_incoming_legs_in_order(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual", "manual_basis": "20.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Card A", "agreed_value": "30.00", "condition": "NM",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Card B", "agreed_value": "45.00", "condition": "NM",
        }, headers=_auth(token))
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "25.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "item_ids" in data
        assert len(data["item_ids"]) == 2

        all_items = {i.item_id: i for i in repo.list_inventory()}
        first = all_items[data["item_ids"][0]]
        second = all_items[data["item_ids"][1]]
        assert first.display_name == "Card A"
        assert second.display_name == "Card B"
```

Adjust the cash amount if it doesn't balance under this file's confirm-balance
rule — copy `test_confirm_full_trade`'s existing balancing approach (same
file, ~line 296) rather than guessing.

- [ ] **Step 2: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary"
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_trades.py -k item_ids_for_incoming -v
```
Expected: FAIL — `KeyError` or `assert "item_ids" in data` fails, since the
key doesn't exist yet.

- [ ] **Step 3: Collect and return `item_ids`**

In `backend/src/merlins_collection/routers/admin/trades.py`, find the
incoming-legs loop (around line 823-824):

```python
    # Process incoming legs (their cards becoming our inventory)
    for index, leg in enumerate(incoming):
        new_item_id = new_ulid()
```

Add a list before the loop and append inside it:

```python
    # Process incoming legs (their cards becoming our inventory)
    created_item_ids: list[str] = []
    for index, leg in enumerate(incoming):
        new_item_id = new_ulid()
        created_item_ids.append(new_item_id)
```

Then find the confirm response dict (around line 963-973):

```python
    return {
        "trade_id": trade_id,
        "status": "confirmed",
        "outgoing_count": items_sold,
        "incoming_count": items_created,
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "transactions_created": txns_created,
        "items_created": items_created,
        "items_sold": items_sold,
    }
```

Add `item_ids`:

```python
    return {
        "trade_id": trade_id,
        "status": "confirmed",
        "outgoing_count": items_sold,
        "incoming_count": items_created,
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "transactions_created": txns_created,
        "items_created": items_created,
        "items_sold": items_sold,
        # RFC 0012: index-aligned with the incoming legs that were sent, so a
        # caller that staged per-leg metadata (e.g. a consignor to assign)
        # can pair it back to the item id that resulted, after the fact.
        "item_ids": created_item_ids,
    }
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_trades.py -v`
Expected: PASS, full file.

- [ ] **Step 5: Run the full backend suite**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/merlins_collection/routers/admin/trades.py backend/tests/routers/admin/test_trades.py
git commit -m "feat(rfc-0012): trade confirm returns item_ids for incoming legs"
```

---

## Part 2 — Frontend: stage a consignor per incoming card, link after confirm

- [ ] **Step 7: Write the failing `IncomingCardForm` test**

Add to `frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx`
(mock `@/lib/use-cosigners` alongside the existing `@/lib/use-locations`
mock):

```tsx
vi.mock('@/lib/use-cosigners', () => ({
  useCosigners: () => ({ options: [{ value: 'cos-1', label: 'Alex' }], loading: false }),
}))
```

```tsx
  it('lets the operator stage a consignor for the card being added', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /consignor/i })) // opens the collapsed section
    await user.click(screen.getByRole('combobox', { name: /consignor/i }))
    await user.click(screen.getByText('Alex'))
    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ consignor_id: 'cos-1' }))
  })

  it('omits consignor_id entirely when none was staged', async () => {
    const user = userEvent.setup({ delay: null })
    const onAdd = vi.fn()
    render(<IncomingCardForm card={card()} onAdd={onAdd} onCancel={vi.fn()} />)
    await user.type(screen.getByLabelText(/value/i), '40')
    await user.click(screen.getByRole('button', { name: /^add$/i }))
    const leg = onAdd.mock.calls[0][0]
    expect(leg.consignor_id).toBeUndefined()
  })
```

- [ ] **Step 8: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run components/admin/deal/__tests__/IncomingCardForm.test.tsx --reporter=verbose
```
Expected: FAIL — no "Consignor" disclosure button exists yet, `onAdd` never
receives a `consignor_id`.

- [ ] **Step 9: Add the collapsed Consignor section to `IncomingCardForm`**

In `frontend/components/admin/deal/IncomingCardForm.tsx`, add the import:

```tsx
import CosignorPicker from '@/components/admin/shared/CosignorPicker'
```

Add state (near the other `useState` calls, around line 86-88):

```tsx
  const [consignorPanel, setConsignorPanel] = useState(false)
  const [consignorId, setConsignorId] = useState<string | null>(null)
```

In `buildIncomingLeg(...)`'s call inside `submit` (around line 148-171), add
the field conditionally so it's never sent as `null` (matching this file's
existing convention for optional fields, e.g. how `market_value`/`image_url`
are only included when present — see `trade-incoming-form.ts`'s
`buildIncomingLeg`, Step 11 below, for where the field actually needs
declaring on the type):

```tsx
    onAdd({
      ...buildIncomingLeg({
        card_id: card?.card_id ?? null,
        name,
        agreed_value: parsed,
        kind: gradedSelectable ? kind : 'raw',
        set_name: setName_,
        card_number: number,
        condition,
        finish,
        company,
        grade,
        cert_number: cert,
        grade_label: gradeLabel,
        language,
        location,
        market_value: card ? parseMoney(String(card.display_price ?? '')) : null,
        image_url: card?.images?.small ?? null,
      }),
      ...(consignorId ? { consignor_id: consignorId } : {}),
    })
```

Add the collapsed section to the JSX, after the Value/Language/Location grid
and before the error block (around line 385-386):

```tsx
      <div className="flex flex-col gap-2">
        {consignorPanel ? (
          <CosignorPicker value={consignorId} onChange={setConsignorId} />
        ) : (
          <button
            type="button"
            onClick={() => setConsignorPanel(true)}
            className="self-start text-[11px] text-mint hover:text-mint/80"
          >
            + Consignor
          </button>
        )}
      </div>
```

- [ ] **Step 10: Run it to verify it passes**

Run: `npx vitest run components/admin/deal/__tests__/IncomingCardForm.test.tsx --reporter=verbose`
Expected: PASS.

- [ ] **Step 11: Add `consignor_id` to the `IncomingLeg` type**

In `frontend/lib/trade-incoming-form.ts`, add to the `IncomingLeg` interface
(near the other optional fields, e.g. after `image_url` around line 88):

```typescript
  /**
   * Client-side only — never sent to POST /trades/{id}/incoming or
   * POST /purchases/{id}/items (neither accepts consignment at create time,
   * RFC 0012). The page reads this off the leg to stage a post-confirm
   * POST /cosigners/{id}/link, keyed by position against the confirm
   * response's item_ids.
   */
  consignor_id?: string
```

`buildIncomingLeg` itself does not need to change — `IncomingCardForm`
spreads `consignor_id` onto the object `buildIncomingLeg` returns (Step 9),
so the field rides along without the builder needing to know about it. Any
`deal-session.ts` `addIncoming` implementation that forwards the whole `leg`
object to the backend as-is (the trade path, `deal-session.ts:194-197`,
`await api.post(`/trades/${id}/incoming`, leg)`) would leak an unknown
`consignor_id` key to that endpoint — confirm this is harmless (an unknown
key in a `dict[str, Any]` body that only reads named keys off it, as
`add_incoming_leg` does, is silently ignored, not rejected) or, if you'd
rather not send it at all, strip it in `tradeApi.addIncoming` before the
POST. Prefer stripping it explicitly — it's one line and avoids relying on
the backend's default `Any`-body leniency:

```typescript
    async addIncoming(id, leg) {
      const { consignor_id: _consignor_id, ...body } = leg
      await api.post(`/trades/${id}/incoming`, body)
    },
```

Apply the same strip in `buyApi(api).addIncoming` (`deal-session.ts:93-116`)
— it already builds an explicit object rather than forwarding `leg` as-is,
so there `consignor_id` is simply never referenced; no change needed there
beyond confirming it isn't accidentally spread in.

- [ ] **Step 12: Write the failing `trade/page.tsx` test**

Check `frontend/app/(admin)/admin/trade/__tests__/page.test.tsx`'s existing
setup for how it mocks `sessionApiFor`/`AdminApi` and stages an incoming card
(the file comment at line 108, "Stages one incoming card via the catalog
pick -> IncomingCardForm path," points at the helper to reuse). Add:

```tsx
  it('links a staged consignor to its resulting item after confirm', async () => {
    // Reuse this file's existing stage-one-incoming-card helper, then have
    // the mocked session.confirm resolve with item_ids so the page can
    // correlate the staged consignor_id back to a real item id.
    confirmMock.mockResolvedValue({ item_ids: ['new-item-1'] })
    // ...render the page, stage one incoming card with a consignor selected
    // (drive IncomingCardForm's own consignor picker, same as its own test),
    // then trigger Confirm...
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/cosigners/cos-1/link', { item_ids: ['new-item-1'] }),
    )
  })
```

Fill in the render/staging steps by copying this file's existing pattern for
staging one incoming card (the helper at line ~108) rather than rewriting
it — match its exact mock variable names (`confirmMock`, `postMock` or
whatever this file already calls them; grep the file for `mockResolvedValue`
near its `session.confirm` mock to find the right names before writing this
test for real).

- [ ] **Step 13: Run it to verify it fails**

Run:
```bash
npx vitest run "app/(admin)/admin/trade/__tests__/page.test.tsx" --reporter=verbose
```
Expected: FAIL — no post-confirm link call happens yet.

- [ ] **Step 14: Stage the consignor and link after confirm in `trade/page.tsx`**

In `handleAddIncoming` (`frontend/app/(admin)/admin/trade/page.tsx:150-166`),
carry the staged consignor into the local `incoming` array:

```tsx
  const handleAddIncoming = async (leg: IncomingLeg) => {
    if (!sessionId) return
    try {
      await session.addIncoming(sessionId, leg)
      setIncoming((prev) => [...prev, {
        name: leg.name,
        card_id: leg.card_id,
        meta: [leg.set_name, leg.card_number && `#${leg.card_number}`].filter(Boolean).join(' · ') || undefined,
        price: leg.agreed_value,
        priceLabel: 'value',
        agreedValue: leg.agreed_value,
        consignorId: leg.consignor_id ?? null,
      }])
      setFormCard(undefined)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add card')
    }
  }
```

Add `consignorId: string | null` to the `StagedIncoming` type (find its
definition — likely in this file or a shared `deal` type module imported
here; grep `interface StagedIncoming` to locate it).

In `handleConfirm` (`frontend/app/(admin)/admin/trade/page.tsx:256-281`),
after a successful `session.confirm(...)`, fire the link calls:

```tsx
  const handleConfirm = async () => {
    if (!sessionId) return
    setConfirming(true)
    try {
      const result = await session.confirm(sessionId, {
        counterparty: counterparty || null,
        date,
        payment_method: session.supports.costBasisMode ? undefined : paymentMethod,
        basis_mode: session.supports.costBasisMode ? basisMode : undefined,
        manual_basis:
          session.supports.costBasisMode && basisMode === 'manual'
            ? String(parseMoney(manualBasis) ?? 0)
            : undefined,
      })
      setConfirmed(true)
      setShowConfirm(false)

      // RFC 0012: neither /purchases/{id}/items nor /trades/{id}/incoming
      // accepts consignment at create time (by design — see cosigners.py's
      // default-split logic, which would otherwise need duplicating
      // frontend-side). A staged consignor is linked here instead, after
      // the deal has already committed — un-awaited and on its own,
      // matching the existing "commit succeeds and is reported first, a
      // secondary call happens after" shape already used for slab price
      // refresh. item_ids is index-aligned with the incoming legs that were
      // sent (trades.py's enumerate loop, purchases.py's append-in-order
      // items list), which is the same order `incoming` was built in above.
      const itemIds = result.item_ids ?? []
      incoming.forEach((leg, i) => {
        const itemId = itemIds[i]
        if (leg.consignorId && itemId) {
          adminApi.post(`/cosigners/${leg.consignorId}/link`, { item_ids: [itemId] }).catch(() => {
            // A link failure here must not read back as "the deal failed" —
            // it already committed. Recoverable after the fact from
            // CardDetailModal (Task C3).
          })
        }
      })
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to confirm')
    } finally {
      setConfirming(false)
    }
  }
```

Check the exact name this file uses for its `useAdminApi()` instance (it may
already be called `api` rather than `adminApi` — `session` here is the
`DealSessionApi` returned by `sessionApiFor`, a different object from the
raw API client; find wherever `useAdminApi()` is actually called in this
file and use that binding's name instead of inventing `adminApi`).

Confirm `sessionApi`'s `confirm(...)` return type (`ConfirmResult`) is
already typed with `item_ids?: string[]` (`deal-session.ts:39-43`) — no type
change needed there, only the `trades.py`/`purchases.py` runtime shapes
mattered (Part 1 fixed the trade side; the purchase side already had it).

- [ ] **Step 15: Run it to verify it passes**

Run: `npx vitest run "app/(admin)/admin/trade/__tests__/page.test.tsx" --reporter=verbose`
Expected: PASS.

- [ ] **Step 16: Run the full frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS.

- [ ] **Step 17: Commit**

```bash
git add frontend/lib/trade-incoming-form.ts frontend/lib/deal-session.ts frontend/components/admin/deal/IncomingCardForm.tsx "frontend/app/(admin)/admin/trade/page.tsx" frontend/components/admin/deal/__tests__/IncomingCardForm.test.tsx "frontend/app/(admin)/admin/trade/__tests__/page.test.tsx"
git commit -m "feat(rfc-0012): stage and link a consignor when adding an incoming card"
```
