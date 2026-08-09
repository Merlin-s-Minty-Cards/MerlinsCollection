# Manual-First Slab Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can type a stack of graded slabs into `/admin/slabs` and commit them as real, costed inventory with purchase transactions — with no PSA API, no scanner and no camera required.

**Architecture:** The buy session learns a second item `kind` (`"graded"`), so slabs get purchase transactions, timeline events, show attribution and cost basis from the same code path raw cards already use. The frontend adds one tab: an entry form (catalog autocomplete with a free-text fallback) feeding a client-side staging table, committed as one buy session.

**Tech Stack:** FastAPI + pydantic + DynamoDB (backend); Next.js 14 App Router + React + TypeScript + vitest/testing-library (frontend).

**Spec:** [`docs/superpowers/specs/2026-08-08-slab-manual-entry-design.md`](../specs/2026-08-08-slab-manual-entry-design.md)

## Definition of done — applies to EVERY task below

One task, one conversation. A task is finished only when **all four** are true, and
the fourth is what keeps the chain moving — a task that stops at "tests pass"
strands the next conversation.

1. **The narrow test selection the task names passes.** Never the full suite.
2. **The work is committed**, using the task's own commit command.
3. **That task's checkboxes in this file are ticked (`- [x]`) and committed.** These
   checkboxes are the live record of progress; a fresh conversation reads them to
   learn where things stand, so leaving them unticked makes the plan lie.
4. **Your final message ends with a copy-pasteable prompt for a FRESH conversation
   to execute the NEXT task.** Self-contained, containing: the files to read first
   (this plan, the spec, `docs/plans/rfc-0009/progress.md`), the task number and
   "execute that task only", the RED gate, the constraints that bite for that task,
   and **this same four-part definition of done** with the numbers advanced.

**Nothing carries between conversations except what you commit and what that prompt
says.** Write it for someone with no memory of this one.

## Global Constraints

- **TDD is a hard gate (CLAUDE.md).** RED → show the owner the failing output → **WAIT for confirmation** → GREEN. Never combine phases. Every task below marks the stop explicitly.
- **Use `./.venv/Scripts/python.exe`, never bare `python`** — the `python` on PATH resolves to an unrelated venv with no pytest.
- **Do not run the full suite inside a task.** Run only the narrow selection each task names. The full suite runs once, at T-FINAL.
- **Never write a bare `float` to DynamoDB.** `_serialize` (`services/dynamodb.py`) is the only float→Decimal coercion. Money and grades arrive from the browser as JSON **numbers**; existing tests all send strings and missed this in production.
- **Name resolution:** call `adminItemName` (`frontend/lib/admin-item-name.ts`). Never inline `display_name || product_name`.
- **Locations:** `useLocations()`. Never hardcode a location list.
- **Card art:** `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN` from `components/admin/shared/CardImage.tsx`. Never hand-pick a size.
- **Conditions do not apply to slabs.** Render no condition control.
- **`useAdminApi` prefixes `/admin`** (`lib/admin-api.ts:45`), so `api.get('/market/search')` hits `GET /admin/market/search`.

## Two traps discovered while planning

**1. `BuySessionItem` is dead code.** It is defined at `routers/admin/purchases.py:56` and referenced nowhere else — `add_buy_item` takes `body: dict[str, Any]` and hand-builds the item dict. The RFC task doc says to add slab fields to that model; **doing so would validate nothing.** Validation goes in `add_buy_item` (Task 1). Leave the model alone.

**2. Do not add a `cert_verified_at is None → cert_lookup_failed` rule.** The RFC task doc proposes it, but with manual entry as the primary path it would flag *every* slab and turn Triage into noise. `_review_reason_for_buy` (`purchases.py:28`) already returns `manual_entry` / `no_catalog_link`, which is exactly the behaviour the spec wants — **so the graded path reuses it unchanged, and the frontend must not send `manual_entry`.** This is a task that removes work rather than adding it.

## File Structure

| File | Responsibility |
|---|---|
| `backend/.../routers/admin/purchases.py` (modify) | `add_buy_item` validates graded items; `confirm_buy_session` branches on `kind` |
| `backend/tests/routers/admin/test_purchases.py` (modify) | graded coverage + raw regression |
| `frontend/components/admin/slabs/CertInput.tsx` (create) | one input serving scanner burst and hand typing |
| `frontend/components/admin/slabs/SlabEntryForm.tsx` (create) | the form; emits one staged row |
| `frontend/components/admin/slabs/StagingTable.tsx` (create) | the batch; per-row remove, cost/grade validity |
| `frontend/app/(admin)/admin/slabs/page.tsx` (create) | batch state + the three-call commit |
| `frontend/components/admin/AdminShell.tsx` (modify) | sidebar entry |
| `docs/…` (modify) | RFC + task docs + progress |

---

### Task 1: `add_buy_item` accepts and validates graded items

**Files:**
- Modify: `backend/src/merlins_collection/routers/admin/purchases.py:151-186`
- Test: `backend/tests/routers/admin/test_purchases.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `POST /admin/purchases/{buy_id}/items` accepts `kind: "graded"` plus `company: str`, `grade: number|str`, `cert_number: str`, and optional `grade_label`, `cert_verified_at`, `cert_image_url`, `price_source_id`. Persists them onto the session item dict under those exact keys. Task 2 reads them.

> **DONE 2026-08-08 — commit `b9a9798`.** 25 passed in
> `backend/tests/routers/admin/test_purchases.py` (22 pre-existing + 3 new).
> Both traps confirmed against real code before implementing: `BuySessionItem`
> is dead, and `_serialize` recurses into lists so the JSON float `grade: 9.5`
> becomes `Decimal("9.5")` on write — the float trap does not bite this path.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/routers/admin/test_purchases.py` inside `class TestBuySessionItems`:

```python
    def test_add_graded_item_persists_slab_fields(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900,
            "company": "PSA", "grade": 9.5, "cert_number": "89787279",
            "grade_label": "MINT 9.5", "card_id": "en:swsh8-271",
        }, headers=_auth(token))

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["kind"] == "graded"
        assert item["company"] == "PSA"
        assert item["cert_number"] == "89787279"
        assert item["grade_label"] == "MINT 9.5"

    def test_add_item_defaults_to_raw_when_kind_absent(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["items"][0]["kind"] == "raw"

    def test_graded_item_without_cert_is_rejected_and_session_survives(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900,
            "company": "PSA", "grade": 9.5,
        }, headers=_auth(token))

        assert resp.status_code == 422
        assert "cert_number" in resp.json()["detail"]
        # The previously-added item must survive a rejected sibling: losing the
        # staged batch is the failure the batch design exists to prevent.
        session = client.get(f"/admin/purchases/{buy_id}", headers=_auth(token)).json()
        assert len(session["items"]) == 1
```

- [x] **Step 2: Run the tests and confirm they FAIL, then STOP**

Run:
```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py -q --tb=short -k "graded or defaults_to_raw"
```
Expected: `test_add_graded_item_persists_slab_fields` fails on `KeyError: 'kind'`, `test_add_item_defaults_to_raw_when_kind_absent` fails the same way, and the rejection test fails because a 200 is returned instead of 422.

**Show the owner this output and WAIT for confirmation before Step 3.** (CLAUDE.md TDD gate.)

- [x] **Step 3: Implement**

In `purchases.py`, above `class BuySessionItem`, add:

```python
#: Fields a graded item cannot be staged without. Enforced HERE, at add time,
#: rather than at confirm: a session that swallows a bad item and explodes on
#: commit loses the whole staged batch, which is the failure the batch design
#: exists to prevent.
#:
#: `cert_number` is required because without one it is not a slab, it is just a
#: normal card (owner, 2026-08-08) -- and it is the key of the CERT# pointer
#: row, so there is nowhere to file the item without it.
_GRADED_REQUIRED_FIELDS = ("company", "grade", "cert_number")
```

In `add_buy_item`, after the existing `name`/`buy_price` check at line 164-165:

```python
    kind = body.get("kind", "raw")
    if kind == "graded":
        # `in (None, "")` rather than falsiness: a grade of 0 is not a real PSA
        # grade, but the check should reject blanks, not numeric edge cases.
        missing = [f for f in _GRADED_REQUIRED_FIELDS if body.get(f) in (None, "")]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"graded items require: {', '.join(missing)}",
            )
```

Then extend the `buy_item` dict (after `"manual_entry": ...`):

```python
        "kind": kind,
        "company": body.get("company"),
        "grade": body.get("grade"),
        "cert_number": body.get("cert_number"),
        "grade_label": body.get("grade_label"),
        "cert_verified_at": body.get("cert_verified_at"),
        "cert_image_url": body.get("cert_image_url"),
        "price_source_id": body.get("price_source_id"),
```

- [x] **Step 4: Run the tests and confirm they PASS**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py -q --tb=short
```
Expected: all pass, including the pre-existing raw tests.

- [x] **Step 5: Commit**

```bash
git add backend/src/merlins_collection/routers/admin/purchases.py backend/tests/routers/admin/test_purchases.py
git commit -m "feat(buy): stage graded items in a buy session"
```

- [x] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 1 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 2 — `confirm_buy_session` creates graded items**, following the four-part definition of
done at the top of this plan.

---

### Task 2: `confirm_buy_session` creates graded items

**Files:**
- Modify: `backend/src/merlins_collection/routers/admin/purchases.py:236-282`
- Test: `backend/tests/routers/admin/test_purchases.py`

**Interfaces:**
- Consumes: session item keys from Task 1 (`kind`, `company`, `grade`, `cert_number`, `grade_label`, `cert_verified_at`, `cert_image_url`, `price_source_id`).
- Produces: confirming a graded item writes a `GradedInventoryItem`, a `Transaction` with `category=ItemCategory.GRADED`, a timeline event, and (via `repo.put_inventory_item`, from T1) the `CERT#` pointer row.

> **DONE 2026-08-08 — commit `170eb09`.** 31 passed in
> `backend/tests/routers/admin/test_purchases.py` (25 pre-existing + 6 new).
> All plan identifiers (`repo.list_inventory`, `repo.list_transactions(start,
> end)`, `repo.get_item_id_by_cert`, `GradedInventoryItem`, `GradingCompany`,
> `ItemCategory`) verified against real code before writing tests — no
> near-misses this time. RED confirmed all 6 new tests failing for the
> expected reason (items always created with `kind == "raw"`) before any
> implementation touched the file.

- [x] **Step 1: Write the failing tests**

Append a new class to `backend/tests/routers/admin/test_purchases.py`:

```python
class TestConfirmGraded:
    def _graded_session(self, client, token, **overrides):
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        payload = {
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900.50,
            "company": "PSA", "grade": 9.5, "cert_number": "89787279",
            "card_id": "en:swsh8-271", "location": "toploader",
        }
        payload.update(overrides)
        client.post(f"/admin/purchases/{buy_id}/items", json=payload,
                    headers=_auth(token))
        return buy_id

    def test_confirm_creates_graded_inventory_item(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items_created"] == 1

        items = repo.list_inventory()
        item = next(i for i in items if getattr(i, "cert_number", None) == "89787279")
        assert item.kind == "graded"
        assert item.company.value == "PSA"
        assert item.grade == Decimal("9.5")
        # Money must survive a JSON float exactly -- not 900.4999999...
        assert item.cost_basis == Decimal("900.50")

    def test_graded_transaction_uses_graded_category(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        # `list_transactions` takes a date RANGE -- there is no no-arg form.
        today = date.today()
        txns = repo.list_transactions(today, today)
        assert txns[0].category == ItemCategory.GRADED

    def test_cert_pointer_row_exists_after_confirm(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert repo.get_item_id_by_cert(GradingCompany.PSA, "89787279") is not None

    def test_catalog_matched_slab_is_not_flagged_for_review(self, admin_client):
        """The core of the manual-first pivot: a hand-typed slab that resolved to
        a catalog card is NOT review-flagged. Flagging every slab would make
        Triage noise, and `cert_lookup_failed` means automation tried and failed
        -- a human typing a slab in is the opposite of that."""
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        item = next(i for i in repo.list_inventory()
                    if getattr(i, "cert_number", None) == "89787279")
        assert item.needs_review is False
        assert item.review_reason is None

    def test_slab_without_catalog_match_is_flagged_no_catalog_link(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token, card_id=None)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        item = next(i for i in repo.list_inventory()
                    if getattr(i, "cert_number", None) == "89787279")
        assert item.needs_review is True
        assert item.review_reason == "no_catalog_link"

    def test_raw_and_graded_in_one_session_both_confirm(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.json()["items_created"] == 2
        assert resp.json()["total_cost"] == "905.50"
        kinds = sorted(i.kind for i in repo.list_inventory())
        assert kinds == ["graded", "raw"]
```

Add to the file's imports if absent: `from datetime import date`, `from decimal import Decimal`, `from merlins_collection.models.business import ItemCategory`, `from merlins_collection.models.inventory import GradingCompany`.

**Verified repo API** — these names are exact, and the near-misses are the ones to avoid: it is `repo.list_inventory()` (**not** `list_inventory_items()`), `repo.list_transactions(start, end)` (**takes a date range, there is no no-arg form**), and `repo.get_item_id_by_cert(company, cert_number)`.

- [x] **Step 2: Run the tests and confirm they FAIL, then STOP**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py::TestConfirmGraded -q --tb=short
```
Expected: failures showing items created with `kind == "raw"` — `StopIteration` from the `next(...)` lookups, because nothing carries a `cert_number` yet.

**Show the owner this output and WAIT for confirmation before Step 3.**

- [x] **Step 3: Implement**

Replace the body of the `for buy_item in items:` loop in `confirm_buy_session` (lines 240-275) so the item dict and the transaction category branch on `kind`. Keep the raw branch **byte-identical** — the smaller the diff on the existing path, the more believable the regression tests:

```python
        # Create a new inventory item
        new_item_id = new_ulid()
        common = {
            "item_id": new_item_id,
            "card_id": buy_item.get("card_id"),
            "status": "available",
            "language": buy_item.get("language", "EN"),
            "location": buy_item.get("location", "toploader"),
            "cost_basis": str(buy_price),
            "market_value_at_purchase": buy_item.get("market_value"),
            "current_market_value": buy_item.get("market_value"),
            "acquired_at": txn_date.isoformat(),
            "acquired_show_id": show_id,
            "display_name": buy_item.get("name"),
            "needs_review": bool(buy_item.get("manual_entry")) or buy_item.get("card_id") is None,
            "review_reason": _review_reason_for_buy(buy_item),
        }

        if buy_item.get("kind") == "graded":
            # `str()` on grade before validation, deliberately: the frontend
            # sends 9.5 as a JSON number, and routing it through str() gives
            # pydantic an exact Decimal("9.5") instead of a binary float.
            item_data = {
                **common,
                "kind": "graded",
                "company": buy_item["company"],
                "grade": str(buy_item["grade"]),
                "cert_number": str(buy_item["cert_number"]),
                "grade_label": buy_item.get("grade_label"),
                "cert_verified_at": buy_item.get("cert_verified_at"),
                "cert_image_url": buy_item.get("cert_image_url"),
                "price_source_id": buy_item.get("price_source_id"),
            }
            category = ItemCategory.GRADED
        else:
            item_data = {
                **common,
                "kind": "raw",
                "finish": buy_item.get("finish", "normal"),
                "condition": buy_item.get("condition", "NM"),
                "condition_modifier": buy_item.get("condition_modifier"),
            }
            category = ItemCategory.RAW
```

Then change the `Transaction(...)` construction to use the branch's category:

```python
            category=category,
```

- [x] **Step 4: Run the tests and confirm they PASS**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py -q --tb=short
```
Expected: all pass. **The pre-existing raw tests are the regression gate** — if any of them changed behaviour, the raw branch was not kept identical.

- [x] **Step 5: Commit**

```bash
git add backend/src/merlins_collection/routers/admin/purchases.py backend/tests/routers/admin/test_purchases.py
git commit -m "feat(buy): confirm graded items, unbreaking slab acquisition"
```

- [x] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 2 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 3 — the `CertInput` component (frontend begins)**, following the four-part definition of
done at the top of this plan.

---

### Task 3: `CertInput` — one input for scanner and keyboard

**Files:**
- Create: `frontend/components/admin/slabs/CertInput.tsx`
- Test: `frontend/components/admin/slabs/__tests__/CertInput.test.tsx`

**Interfaces:**
- Produces: `export default function CertInput(props: CertInputProps)` where
  ```ts
  interface CertInputProps {
    value: string
    onChange: (value: string) => void
    onEnter?: () => void
    onBlur?: () => void
    disabled?: boolean
  }
  ```
  Task 4 uses it as a controlled field and hangs the duplicate check on `onBlur`.

**Design note — Enter must not submit the form.** A wedge scanner ends its burst with Enter, which arrives before the card, grade and cost are filled. So Enter here **advances**, it does not commit the batch row. `onEnter` is how the form moves focus to the Card field.

> **DONE 2026-08-08 — commit `c5b5a00`.** 6 passed in
> `frontend/components/admin/slabs/__tests__/CertInput.test.tsx`; this task
> creates the `slabs/` directory, so that file is the whole selection. RED was
> the predicted `Failed to resolve import "../CertInput"`. Implemented exactly
> as written below — no deviation was needed.
>
> **Checked before implementing, because the component carries both a wrapping
> `<label><span>Cert number</span>` and `aria-label="Cert number"`:**
> `getByLabelText` dedupes its matches (`Array.from(new Set(...))`,
> `@testing-library/dom/dist/queries/label-text.js:89`), so the two routes
> resolving to the same input is safe, not an ambiguous-match failure.
> `autoFocus` has precedent in five existing components, so lint is unaffected.
>
> **⚠️ A trap waiting in Task 4's test, found here.** Task 4 renders inputs
> labelled `Grade` **and** `Grade label`, and its helper calls
> `fill(/grade/i, '9.5')`. That regex matches both, and `getByLabelText` throws
> `Found multiple elements` on an ambiguous match — dedupe only collapses one
> element reached twice, it does not pick between two different elements.
> Task 4 must resolve this deliberately (an anchored `/^grade$/i`, or a label
> that does not prefix the other) rather than discover it as a mystery failure.

- [x] **Step 1: Write the failing test**

`frontend/components/admin/slabs/__tests__/CertInput.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CertInput from '../CertInput'

describe('CertInput', () => {
  it('accepts a wedge scanner burst and keeps the digits', () => {
    const onChange = vi.fn()
    render(<CertInput value="" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: '89787279' } })
    expect(onChange).toHaveBeenCalledWith('89787279')
  })

  it('strips a trailing carriage return and newline a scanner appends', () => {
    const onChange = vi.fn()
    render(<CertInput value="" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: '89787279\r\n' } })
    expect(onChange).toHaveBeenCalledWith('89787279')
  })

  it('calls onEnter when Enter is pressed, without needing a scanner', () => {
    const onEnter = vi.fn()
    render(<CertInput value="89787279" onChange={vi.fn()} onEnter={onEnter} />)
    fireEvent.keyDown(screen.getByLabelText(/cert/i), { key: 'Enter' })
    expect(onEnter).toHaveBeenCalledTimes(1)
  })

  it('accepts characters typed one at a time over a long span', () => {
    // The regression a speed-gated implementation introduces: a cert typed
    // slowly must be exactly as valid as one scanned in 40ms.
    const onChange = vi.fn()
    const { rerender } = render(<CertInput value="" onChange={onChange} />)
    const digits = '89787279'
    let acc = ''
    for (const d of digits) {
      acc += d
      fireEvent.change(screen.getByLabelText(/cert/i), { target: { value: acc } })
      rerender(<CertInput value={acc} onChange={onChange} />)
    }
    expect(onChange).toHaveBeenLastCalledWith('89787279')
    expect(onChange).toHaveBeenCalledTimes(digits.length)
  })

  it('does not call onEnter on an empty value', () => {
    const onEnter = vi.fn()
    render(<CertInput value="  " onChange={vi.fn()} onEnter={onEnter} />)
    fireEvent.keyDown(screen.getByLabelText(/cert/i), { key: 'Enter' })
    expect(onEnter).not.toHaveBeenCalled()
  })

  it('fires onBlur so the form can run its duplicate check', () => {
    const onBlur = vi.fn()
    render(<CertInput value="89787279" onChange={vi.fn()} onBlur={onBlur} />)
    fireEvent.blur(screen.getByLabelText(/cert/i))
    expect(onBlur).toHaveBeenCalledTimes(1)
  })
})
```

- [x] **Step 2: Run the test and confirm it FAILS, then STOP**

```bash
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```
Expected: `Failed to resolve import "../CertInput"`.

**Show the owner this output and WAIT for confirmation before Step 3.**

- [x] **Step 3: Implement**

`frontend/components/admin/slabs/CertInput.tsx`:

```tsx
'use client'

interface CertInputProps {
  value: string
  onChange: (value: string) => void
  /** Fired on Enter with a non-blank value. Advances focus; does NOT submit. */
  onEnter?: () => void
  /** Fired when the field loses focus. Task 4 hangs the duplicate check here. */
  onBlur?: () => void
  disabled?: boolean
}

/**
 * The cert field, serving a keyboard-wedge scanner and a human typing equally.
 *
 * A wedge scanner is just a keyboard that types fast and ends with Enter, so
 * there is no scanner-detection here and deliberately no timing logic:
 * submission is NEVER gated on typing speed. A cert typed slowly over ten
 * seconds is exactly as valid as one scanned in 40ms, and for a slab whose
 * barcode will not read, hand entry is the only way in.
 *
 * Enter ADVANCES rather than submits -- the scanner's trailing Enter arrives
 * long before card, grade and cost are filled.
 */
export default function CertInput({ value, onChange, onEnter, onBlur, disabled }: CertInputProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm font-medium">Cert number</span>
      <input
        type="text"
        inputMode="numeric"
        autoFocus
        disabled={disabled}
        value={value}
        aria-label="Cert number"
        // Some scanners append \r, \n or both. Strip on the way in so the
        // value never carries invisible characters into a URL path.
        onChange={(e) => onChange(e.target.value.replace(/[\r\n]/g, '').trim())}
        onBlur={() => onBlur?.()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            if (value.trim()) onEnter?.()
          }
        }}
        className="rounded border px-3 py-2"
      />
    </label>
  )
}
```

- [x] **Step 4: Run the test and confirm it PASSES**

```bash
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```

- [x] **Step 5: Commit**

```bash
git add frontend/components/admin/slabs/CertInput.tsx frontend/components/admin/slabs/__tests__/CertInput.test.tsx
git commit -m "feat(slabs): cert input serving scanner and keyboard equally"
```

- [x] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 3 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 4 — `SlabEntryForm`**, following the four-part definition of
done at the top of this plan.

---

### Task 4: `SlabEntryForm` — catalog autocomplete with a free-text fallback

**Files:**
- Create: `frontend/components/admin/slabs/SlabEntryForm.tsx`
- Test: `frontend/components/admin/slabs/__tests__/SlabEntryForm.test.tsx`

**Interfaces:**
- Consumes: `CertInput` from Task 3.
- Produces:
  ```ts
  export interface StagedSlab {
    key: string            // client-side row id (crypto.randomUUID())
    cert_number: string
    card_id: string | null
    name: string
    company: string        // 'PSA' | 'BGS' | 'CGC' | 'SGC'
    grade: string          // kept as a string in form state; sent as a number
    grade_label: string
    buy_price: string      // kept as a string in form state; sent as a number
    location: string
  }
  export default function SlabEntryForm(props: { onAdd: (row: StagedSlab) => void })
  ```
  Tasks 5 and 6 consume `StagedSlab`.

- [ ] **Step 1: Write the failing test**

`frontend/components/admin/slabs/__tests__/SlabEntryForm.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SlabEntryForm from '../SlabEntryForm'

const mockApi = { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})
// NOTE: useLocations returns `options`, NOT `locations` (lib/use-locations.ts:13).
vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({ options: [{ value: 'toploader', label: 'Toploader' }], loading: false }),
}))

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

describe('SlabEntryForm', () => {
  beforeEach(() => {
    mockApi.get.mockReset()
    mockApi.get.mockResolvedValue({ items: [], total: 0 })
  })

  it('blocks the add when the cert is blank and points at the Buy page', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/card name/i, 'Gengar VMAX')
    fill(/grade/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    expect(onAdd).not.toHaveBeenCalled()
    expect(screen.getByText(/without a cert number.*not a slab/i)).toBeInTheDocument()
    expect(screen.getByText(/buy page/i)).toBeInTheDocument()
  })

  it('adds a row with card_id null when the card was typed by hand', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fill(/card name/i, 'Some JP Card')
    fill(/grade/i, '10')
    fill(/cost/i, '40')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      cert_number: '89787279', card_id: null, name: 'Some JP Card',
      company: 'PSA', grade: '10', buy_price: '40',
    })
  })

  it('sets card_id when a catalog suggestion is chosen', async () => {
    mockApi.get.mockResolvedValue({
      items: [{ card_id: 'en:swsh8-271', name: 'Gengar VMAX', set_name: 'Fusion Strike', number: '271' }],
      total: 1,
    })
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fill(/card name/i, 'Gengar')

    const suggestion = await screen.findByRole('button', { name: /Gengar VMAX/ })
    fireEvent.click(suggestion)
    fill(/grade/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))

    await waitFor(() => expect(onAdd).toHaveBeenCalled())
    expect(onAdd.mock.calls[0][0].card_id).toBe('en:swsh8-271')
  })

  it('warns but still allows the add when the cert is already owned', async () => {
    mockApi.get.mockImplementation((path: string) =>
      path.startsWith('/slabs/certs/')
        ? Promise.resolve({ owned: true, item_id: '01ABC', status: 'available', name: 'Gengar VMAX' })
        : Promise.resolve({ items: [], total: 0 })
    )
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    fill(/cert number/i, '89787279')
    fireEvent.blur(screen.getByLabelText(/cert number/i))

    expect(await screen.findByText(/already in inventory/i)).toBeInTheDocument()

    fill(/card name/i, 'Gengar VMAX')
    fill(/grade/i, '9.5')
    fill(/cost/i, '900.50')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1))
  })

  it('defaults company to PSA and allows CGC', async () => {
    const onAdd = vi.fn()
    render(<SlabEntryForm onAdd={onAdd} />)
    expect((screen.getByLabelText(/company/i) as HTMLSelectElement).value).toBe('PSA')
    fireEvent.change(screen.getByLabelText(/company/i), { target: { value: 'CGC' } })
    fill(/cert number/i, '1234')
    fill(/card name/i, 'Charizard')
    fill(/grade/i, '9')
    fill(/cost/i, '10')
    fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
    await waitFor(() => expect(onAdd.mock.calls[0][0].company).toBe('CGC'))
  })
})
```

- [ ] **Step 2: Run and confirm FAIL, then STOP**

```bash
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```
Expected: `Failed to resolve import "../SlabEntryForm"`.

**Show the owner this output and WAIT for confirmation.**

- [ ] **Step 3: Implement**

Read `frontend/app/(admin)/admin/buy/page.tsx:52-122` first and mirror its catalog-search structure — in particular the `searchSeqRef` sequence guard, which stops a slow search from overwriting a newer one's results.

`frontend/components/admin/slabs/SlabEntryForm.tsx`:

```tsx
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import { useLocations } from '@/lib/use-locations'
import CertInput from './CertInput'

export interface StagedSlab {
  key: string
  cert_number: string
  card_id: string | null
  name: string
  company: string
  grade: string
  grade_label: string
  buy_price: string
  location: string
}

interface CatalogCard {
  card_id: string
  name: string
  set_name?: string
  number?: string
}

interface OwnedCheck {
  owned: boolean
  item_id?: string
  status?: string
  name?: string
}

const COMPANIES = ['PSA', 'BGS', 'CGC', 'SGC']

export default function SlabEntryForm({ onAdd }: { onAdd: (row: StagedSlab) => void }) {
  const api = useAdminApi()
  // `options`, not `locations` -- see lib/use-locations.ts:13.
  const { options: locationOptions } = useLocations()

  const [cert, setCert] = useState('')
  const [name, setName] = useState('')
  const [cardId, setCardId] = useState<string | null>(null)
  const [company, setCompany] = useState('PSA')
  const [grade, setGrade] = useState('')
  const [gradeLabel, setGradeLabel] = useState('')
  const [cost, setCost] = useState('')
  const [location, setLocation] = useState('toploader')

  const [results, setResults] = useState<CatalogCard[]>([])
  const [owned, setOwned] = useState<OwnedCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  // A catalog search can take seconds and several can be in flight; only the
  // newest may write results. Same guard the Buy page uses.
  const seqRef = useRef(0)
  const nameRef = useRef<HTMLInputElement>(null)

  const searchCatalog = useCallback(async (q: string) => {
    if (!q.trim() || cardId) { setResults([]); return }
    const seq = ++seqRef.current
    try {
      const res = await api.get<{ items: CatalogCard[] }>('/market/search', { name: q })
      if (seq !== seqRef.current) return
      setResults(res.items.slice(0, 8))
    } catch {
      if (seq === seqRef.current) setResults([])
    }
  }, [api, cardId])

  useEffect(() => {
    const t = setTimeout(() => searchCatalog(name), 300)
    return () => clearTimeout(t)
  }, [name, searchCatalog])

  const checkOwned = async () => {
    if (!cert.trim()) return
    try {
      setOwned(await api.get<OwnedCheck>(`/slabs/certs/${encodeURIComponent(cert)}`, { company }))
    } catch {
      setOwned(null)  // a failed check is not evidence of anything
    }
  }

  const submit = () => {
    if (!cert.trim()) {
      setError('Without a cert number this is not a slab, it is just a normal card — add it on the Buy page instead.')
      return
    }
    if (!grade.trim() || !cost.trim()) {
      setError('Grade and cost are required.')
      return
    }
    setError(null)
    onAdd({
      key: crypto.randomUUID(),
      cert_number: cert.trim(), card_id: cardId, name: name.trim(),
      company, grade: grade.trim(), grade_label: gradeLabel.trim(),
      buy_price: cost.trim(), location,
    })
    setCert(''); setName(''); setCardId(null); setGrade('')
    setGradeLabel(''); setCost(''); setResults([]); setOwned(null)
  }

  return (
    <div className="flex flex-col gap-3">
      <CertInput value={cert} onChange={(v) => { setCert(v); setOwned(null) }}
                 onEnter={() => nameRef.current?.focus()} onBlur={checkOwned} />
      {owned?.owned && (
        <p role="status" className="text-amber-700">
          Already in inventory ({owned.status}) — {owned.name}. You can still add it.
        </p>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Card name</span>
        <input ref={nameRef} aria-label="Card name" value={name} className="rounded border px-3 py-2"
               onChange={(e) => { setName(e.target.value); setCardId(null) }} />
      </label>
      {results.length > 0 && !cardId && (
        <ul>
          {results.map((c) => (
            <li key={c.card_id}>
              <button type="button" onClick={() => {
                setCardId(c.card_id); setName(c.name); setResults([])
              }}>
                {c.name} — {c.set_name} #{c.number}
              </button>
            </li>
          ))}
        </ul>
      )}
      {cardId && <p className="text-sm text-green-700">Linked to catalog ({cardId})</p>}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Company</span>
        <select aria-label="Company" value={company} className="rounded border px-3 py-2"
                onChange={(e) => setCompany(e.target.value)}>
          {COMPANIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Grade</span>
        <input aria-label="Grade" inputMode="decimal" value={grade} className="rounded border px-3 py-2"
               onChange={(e) => setGrade(e.target.value)} />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Grade label</span>
        <input aria-label="Grade label" value={gradeLabel} className="rounded border px-3 py-2"
               onChange={(e) => setGradeLabel(e.target.value)} />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Cost</span>
        <input aria-label="Cost" inputMode="decimal" value={cost} className="rounded border px-3 py-2"
               onChange={(e) => setCost(e.target.value)} />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Location</span>
        <select aria-label="Location" value={location} className="rounded border px-3 py-2"
                onChange={(e) => setLocation(e.target.value)}>
          {locationOptions.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
      </label>

      {error && <p role="alert" className="text-red-700">{error}</p>}
      <button type="button" onClick={submit} className="rounded bg-green-700 px-4 py-2 text-white">
        Add to batch
      </button>
    </div>
  )
}
```

The duplicate check hangs off `CertInput`'s `onBlur` (added in Task 3), which is what the test's `fireEvent.blur` triggers. A failed check sets `owned` to `null` rather than showing an error: a check that threw is not evidence the cert is unowned, and it must never block the add.

- [ ] **Step 4: Run and confirm PASS**

```bash
cd frontend && npx vitest run components/admin/slabs --reporter=verbose
```

- [ ] **Step 5: Commit**

```bash
git add frontend/components/admin/slabs/SlabEntryForm.tsx frontend/components/admin/slabs/__tests__/SlabEntryForm.test.tsx
git commit -m "feat(slabs): slab entry form with catalog autocomplete and manual fallback"
```

- [ ] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 4 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 5 — `StagingTable`**, following the four-part definition of
done at the top of this plan.

---

### Task 5: `StagingTable` — the batch

**Files:**
- Create: `frontend/components/admin/slabs/StagingTable.tsx`
- Test: `frontend/components/admin/slabs/__tests__/StagingTable.test.tsx`

**Interfaces:**
- Consumes: `StagedSlab` from Task 4.
- Produces: `export default function StagingTable(props: { rows: StagedSlab[]; onRemove: (key: string) => void })`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StagingTable from '../StagingTable'
import type { StagedSlab } from '../SlabEntryForm'

function row(over: Partial<StagedSlab> = {}): StagedSlab {
  return {
    key: 'k1', cert_number: '89787279', card_id: 'en:swsh8-271', name: 'Gengar VMAX',
    company: 'PSA', grade: '9.5', grade_label: 'MINT 9.5', buy_price: '900.50',
    location: 'toploader', ...over,
  }
}

describe('StagingTable', () => {
  it('renders one row per staged slab with cert, card, grade and cost', () => {
    render(<StagingTable rows={[row()]} onRemove={vi.fn()} />)
    expect(screen.getByText('89787279')).toBeInTheDocument()
    expect(screen.getByText('Gengar VMAX')).toBeInTheDocument()
    expect(screen.getByText(/9\.5/)).toBeInTheDocument()
    expect(screen.getByText(/900\.50/)).toBeInTheDocument()
  })

  it('marks a row with no catalog link so the operator knows it lands in Triage', () => {
    render(<StagingTable rows={[row({ card_id: null })]} onRemove={vi.fn()} />)
    expect(screen.getByText(/no catalog link/i)).toBeInTheDocument()
  })

  it('removes a row by key', () => {
    const onRemove = vi.fn()
    render(<StagingTable rows={[row()]} onRemove={onRemove} />)
    fireEvent.click(screen.getByRole('button', { name: /remove/i }))
    expect(onRemove).toHaveBeenCalledWith('k1')
  })

  it('renders nothing but an empty note when there are no rows', () => {
    render(<StagingTable rows={[]} onRemove={vi.fn()} />)
    expect(screen.getByText(/nothing staged/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run and confirm FAIL, then STOP.** Same command as Task 4. **WAIT for owner confirmation.**

- [ ] **Step 3: Implement**

```tsx
'use client'

import type { StagedSlab } from './SlabEntryForm'

export default function StagingTable({ rows, onRemove }: {
  rows: StagedSlab[]
  onRemove: (key: string) => void
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-gray-600">Nothing staged yet.</p>
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr>
          <th className="text-left">Cert</th><th className="text-left">Card</th>
          <th className="text-left">Company</th><th className="text-left">Grade</th>
          <th className="text-left">Cost</th><th />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td>{r.cert_number}</td>
            <td>
              {r.name}
              {/* Honest up front: an unlinked slab gets no automatic price and
                  lands in Triage. Better said here than discovered later. */}
              {!r.card_id && <span className="ml-2 text-amber-700">no catalog link</span>}
            </td>
            <td>{r.company}</td>
            <td>{r.grade}</td>
            <td>${r.buy_price}</td>
            <td>
              <button type="button" onClick={() => onRemove(r.key)} aria-label={`Remove ${r.cert_number}`}>
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 4: Run and confirm PASS.**

- [ ] **Step 5: Commit**

```bash
git add frontend/components/admin/slabs/StagingTable.tsx frontend/components/admin/slabs/__tests__/StagingTable.test.tsx
git commit -m "feat(slabs): staging table for a slab intake batch"
```

- [ ] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 5 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 6 — the page, commit flow and sidebar**, following the four-part definition of
done at the top of this plan.

---

### Task 6: The page, the commit flow, and the sidebar

**Files:**
- Create: `frontend/app/(admin)/admin/slabs/page.tsx`
- Modify: `frontend/components/admin/AdminShell.tsx:29-45`
- Test: `frontend/app/(admin)/admin/slabs/__tests__/page.test.tsx`

**Interfaces:**
- Consumes: `SlabEntryForm`, `StagedSlab`, `StagingTable`.
- Produces: the `/admin/slabs` route.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import SlabsPage from '../page'

const mockApi = { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }
vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})
// NOTE: useLocations returns `options`, NOT `locations` (lib/use-locations.ts:13).
vi.mock('@/lib/use-locations', () => ({
  useLocations: () => ({ options: [{ value: 'toploader', label: 'Toploader' }], loading: false }),
}))

function stageOne() {
  fireEvent.change(screen.getByLabelText(/cert number/i), { target: { value: '89787279' } })
  fireEvent.change(screen.getByLabelText(/card name/i), { target: { value: 'Gengar VMAX' } })
  fireEvent.change(screen.getByLabelText(/grade/i), { target: { value: '9.5' } })
  fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '900.50' } })
  fireEvent.click(screen.getByRole('button', { name: /add to batch/i }))
}

describe('Slabs page', () => {
  beforeEach(() => {
    mockApi.get.mockReset(); mockApi.post.mockReset()
    mockApi.get.mockResolvedValue({ items: [], total: 0 })
    mockApi.post.mockResolvedValue({ buy_id: 'BUY1' })
  })

  it('commits create -> items -> confirm in that order with kind graded', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    const paths = mockApi.post.mock.calls.map((c) => c[0])
    expect(paths).toEqual(['/purchases', '/purchases/BUY1/items', '/purchases/BUY1/confirm'])
    expect(mockApi.post.mock.calls[1][1]).toMatchObject({ kind: 'graded', cert_number: '89787279' })
  })

  it('sends buy_price and grade as JSON numbers, not strings', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    const body = mockApi.post.mock.calls[1][1]
    expect(typeof body.buy_price).toBe('number')
    expect(body.buy_price).toBe(900.5)
    expect(typeof body.grade).toBe('number')
  })

  it('never sends manual_entry — every slab is hand-typed and must not flood Triage', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(3))
    expect(mockApi.post.mock.calls[1][1]).not.toHaveProperty('manual_entry')
  })

  it('stops without confirming when an item post fails, keeping the rows', async () => {
    mockApi.post
      .mockResolvedValueOnce({ buy_id: 'BUY1' })
      .mockRejectedValueOnce(new Error('boom'))
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    const paths = mockApi.post.mock.calls.map((c) => c[0])
    expect(paths).not.toContain('/purchases/BUY1/confirm')
    expect(screen.getByText('89787279')).toBeInTheDocument()
  })

  it('clears the batch and reports the total on success', async () => {
    render(<SlabsPage />)
    stageOne()
    await screen.findByText('89787279')
    fireEvent.click(screen.getByRole('button', { name: /commit/i }))
    await waitFor(() => expect(screen.getByText(/nothing staged/i)).toBeInTheDocument())
    expect(screen.getByText(/900\.50/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run and confirm FAIL, then STOP.**

```bash
cd frontend && npx vitest run "app/(admin)/admin/slabs" --reporter=verbose
```
**WAIT for owner confirmation.**

- [ ] **Step 3: Implement**

`frontend/app/(admin)/admin/slabs/page.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import SlabEntryForm, { type StagedSlab } from '@/components/admin/slabs/SlabEntryForm'
import StagingTable from '@/components/admin/slabs/StagingTable'

export default function SlabsPage() {
  const api = useAdminApi()
  const [rows, setRows] = useState<StagedSlab[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const commit = async () => {
    if (rows.length === 0) return
    setBusy(true); setError(null); setResult(null)
    try {
      const session = await api.post<{ buy_id: string }>('/purchases', {})
      const buyId = session.buy_id

      for (const r of rows) {
        // Numbers, not strings: the backend coerces through str() to an exact
        // Decimal, and sending strings here is what let the float bug hide.
        // `manual_entry` is deliberately ABSENT -- every slab here is typed by
        // hand, so sending it would flag the whole shelf into Triage.
        await api.post(`/purchases/${buyId}/items`, {
          kind: 'graded',
          name: r.name,
          card_id: r.card_id,
          company: r.company,
          grade: Number(r.grade),
          cert_number: r.cert_number,
          grade_label: r.grade_label || null,
          buy_price: Number(r.buy_price),
          location: r.location,
        })
      }

      await api.post(`/purchases/${buyId}/confirm`, {})
      const total = rows.reduce((sum, r) => sum + Number(r.buy_price), 0)
      setResult(`Committed ${rows.length} slab(s), $${total.toFixed(2)}`)
      setRows([])
    } catch (e) {
      // Stop where we are. An unconfirmed draft creates no inventory, so
      // "do nothing" is the safe state -- never half-commit a batch.
      setError(`Commit failed before confirming: ${(e as Error).message}. Nothing was created; the batch is intact.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Slabs</h1>
      <SlabEntryForm onAdd={(row) => setRows((rs) => [...rs, row])} />
      <StagingTable rows={rows} onRemove={(key) => setRows((rs) => rs.filter((r) => r.key !== key))} />
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {result && <p role="status" className="text-green-700">{result}</p>}
      <button type="button" onClick={commit} disabled={busy || rows.length === 0}
              className="self-start rounded bg-green-700 px-4 py-2 text-white disabled:opacity-50">
        Commit batch
      </button>
    </div>
  )
}
```

In `AdminShell.tsx`, add `ScanLine` to the `lucide-react` import and insert after the Buy entry:

```tsx
  { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
```

- [ ] **Step 4: Run and confirm PASS**

```bash
cd frontend && npx vitest run components/admin/slabs "app/(admin)/admin/slabs" --reporter=verbose
cd frontend && npm run lint
```

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(admin)/admin/slabs" frontend/components/admin/slabs frontend/components/admin/AdminShell.tsx
git commit -m "feat(slabs): manual slab intake tab, scan to committed inventory"
```

- [ ] **Step 6: Tick this task's checkboxes, then hand off**

Tick every `- [ ]` in Task 6 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

Then end your final message with a copy-pasteable prompt for a **fresh
conversation** to execute **Task 7 — documentation catches up**, following the four-part definition of
done at the top of this plan.

---

### Task 7: Documentation catches up with the pivot

**Files:**
- Modify: `docs/rfcs/0009-slab-intake-and-graded-pricing.md`
- Modify: `docs/plans/rfc-0009/t3-buy-session-graded.md`, `t4-slabs-tab-scan-to-commit.md`
- Modify: `docs/plans/rfc-0009/progress.md`, `README.md`

No tests — this task is prose. It is separate because a reviewer can reject the docs while accepting the code.

**Already done up front, on 2026-08-08 — do not redo:** the *navigational* corrections
that had to land before any task ran, because a fresh conversation reading them would
otherwise have built the superseded design. `progress.md` carries a pivot banner and
corrected T3/T4/T5 rows, `README.md`'s dependency table points here, the RFC carries an
amendment banner, and `t3-*.md` / `t4-*.md` carry SUPERSEDED banners naming their two
wrong instructions. **This task is the substantive rewrite**, not the redirect.

- [ ] **Step 1: Correct the RFC**

In §5.2, replace "1 credit per card" with the measured **2 credits per card** (`costPerCard: 2`, 1 for the card + 1 for `includeEbay`), and add that **billing is on `limit`, not on hits** — a `limit=2` search matching zero cards still cost 4 credits.

In §5.1, keep "no rate-limit headers" but add that a 429 carries `Retry-After`, and add the **403 `"Access to this API is limited to approved customers"`** failure mode, which §9's table does not list.

In §9, add a row: `PSA 403 (account not approved)` → manual entry, and the message must say the fix is account approval, not a retry.

Add to §1 that intake is **manual-first**: PSA lookup pre-fills the form when available and is not required.

- [ ] **Step 2: Rewrite the T4 task doc**

Replace `t4-slabs-tab-scan-to-commit.md`'s scan-and-lookup pipeline with this plan's form-based design: entry form, catalog autocomplete with free-text fallback, cert required, no `/lookup` call, dependencies **T3 only**.

- [ ] **Step 3: Amend the T3 task doc**

Delete the `cert_verified_at is None → cert_lookup_failed` rule and record why (it would flag every slab now that manual entry is primary). Note that `BuySessionItem` is unused, so validation belongs in `add_buy_item`.

- [ ] **Step 4: Update `progress.md` and `README.md`**

Mark T3 and T4 DONE with their commit shas, set T2 to DEFERRED with the dependency change (T4 no longer needs it), and note in the Decisions table that hand-entered slabs are not review-flagged.

- [ ] **Step 5: Commit**

```bash
git add docs/rfcs/0009-slab-intake-and-graded-pricing.md docs/plans/rfc-0009
git commit -m "docs(slabs): manual-first intake, and the RFC corrections T0 measured"
```

- [ ] **Step 6: Tick this task's checkboxes, then hand off — this plan is complete**

Tick every `- [ ]` in Task 7 above to `- [x]` and amend or add a commit so the
record is durable — a fresh conversation trusts these boxes over any message.

**This is the last task in this plan**, so the handoff leaves it. Run the
verification block below, then end your final message with a copy-pasteable prompt
for a fresh conversation to execute **RFC 0009 T6 — pricing provider + slab list**
(`docs/plans/rfc-0009/t6-pricing-provider-and-slab-list.md`), following the
four-part definition of done in *that* doc, which is the RFC-task variant rather
than the one at the top of this plan.

Tell the owner in that message that intake is now usable end to end, and that T2
(PSA lookup) and T5 (camera) remain deferred behind PSA account approval.

---

## Verification before calling the feature done

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py backend/tests/routers/admin/test_slabs.py -q --tb=short
cd frontend && npx vitest run components/admin/slabs "app/(admin)/admin/slabs" --reporter=verbose
cd frontend && npm run lint
./.venv/Scripts/python.exe -m ruff check backend/src
```

Then run the app and type a real slab in end to end — a test suite cannot tell you whether the field order feels right with a stack of slabs in hand, and that is the one thing this feature lives or dies on.
