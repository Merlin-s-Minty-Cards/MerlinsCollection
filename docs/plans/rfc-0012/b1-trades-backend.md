# Task B1: Allow a Graded Trade Incoming Leg Without a `card_id`

**Files:**
- Modify: `backend/src/merlins_collection/routers/admin/trades.py:430-437`
- Modify: `backend/tests/routers/admin/test_trades.py:1546-1558` (replace the
  test that currently asserts the 422 this task removes)
- Test: `backend/tests/routers/admin/test_trades.py` (new test added in this task)

**Interfaces:**
- Consumes: `is_missing_card_id` from `backend/src/merlins_collection/services/triage.py`
  (already exists, unchanged by this task) — the test proves it fires for a
  graded item, it does not modify it.
- Produces: nothing new consumed by other tasks. B2 (frontend) does not
  import from this file; the two are connected only by the shared HTTP
  contract (a graded leg with `card_id: null` is now a 201, not a 422),
  which B2's own tests exercise independently via mocks.

## Context

`POST /admin/trades/{trade_id}/incoming` currently 422s any graded leg
missing `card_id` ("Decision 14"). Traced in RFC 0012 (`docs/rfcs/0012-...md`,
section B): this is Trade-specific policy, not a data-model or pricing-service
requirement — `GradedInventoryItem.card_id` is already `str | None = None`,
and `purchases.py`'s own graded item-add endpoint never required it. The
owner has decided to lift this so a graded slab can be manually entered from
Buy/Sell/Trade the same way it already can from `/admin/slabs`. The item
lands unpriced (same state a JP slab is already in) and self-routes to
Triage via the existing `is_missing_card_id` predicate — no new routing code.

- [ ] **Step 1: Write the failing test — replace the old 422 assertion**

Open `backend/tests/routers/admin/test_trades.py`. Find and DELETE this
existing test (lines 1546-1558):

```python
    def test_a_graded_leg_without_a_card_id_is_a_422(self, admin_client):
        """Decision 14. Graded pricing joins on (card_id, company, grade), so an
        unlinked slab is unpriceable by construction."""
        client, _, token = admin_client
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token),
                           json={"name": "Charizard", "agreed_value": 400,
                                 "kind": "graded", "company": "PSA", "grade": 10,
                                 "cert_number": "1"})

        assert resp.status_code == 422
        assert "catalog card" in resp.json()["detail"]
```

Replace it with:

```python
    def test_a_graded_leg_without_a_card_id_is_accepted(self, admin_client):
        """RFC 0012: a graded incoming leg no longer requires a catalog card_id
        (reverses Decision 14) — manual entry is now identical to how
        /admin/slabs intake has always worked. The leg is accepted with
        card_id: null."""
        client, _, token = admin_client
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token),
                           json={"name": "Charizard", "agreed_value": 400,
                                 "kind": "graded", "company": "PSA", "grade": 10,
                                 "cert_number": "1"})

        assert resp.status_code == 200
        legs = resp.json()["incoming_legs"]
        assert legs[-1]["card_id"] is None
        assert legs[-1]["kind"] == "graded"
        assert legs[-1]["company"] == "PSA"
```

Also add a new test in the same `TestTradeSessionIncoming`-style class (find
the class containing `test_a_graded_leg_without_a_card_id_is_a_422` and add
this alongside it) proving the whole confirm-through-Triage path:

```python
    def test_a_manually_entered_graded_item_self_routes_to_triage(self, admin_client):
        """RFC 0012: no new triage-routing code exists for this — it relies
        entirely on services/triage.py's is_missing_card_id(), which already
        treats any card_id-less item (raw or graded) as needing Triage. This
        test proves that reliance is correct for a graded item created via
        this specific endpoint, not just in unit-tested isolation."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1"))

        trade_id = _start_trade(client, token)
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual", "manual_basis": "20.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token), json={
            "name": "Mystery Charizard", "agreed_value": "400.00",
            "kind": "graded", "company": "PSA", "grade": 10, "cert_number": "99",
        })
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "0",
        }, headers=_auth(token))

        confirm = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert confirm.status_code == 200

        new_items = [i for i in repo.list_inventory() if i.item_id != "our-1"]
        assert len(new_items) == 1
        created = new_items[0]
        assert created.card_id is None

        search = client.get("/admin/inventory/search", params={"triage": "true"},
                            headers=_auth(token))
        assert search.status_code == 200
        rows = search.json()["items"]
        matching = [r for r in rows if r["item_id"] == created.item_id]
        assert len(matching) == 1
        assert "missing_card_id" in matching[0]["triage_reasons"]
```

If the trade confirm flow requires a balanced cash amount and `50.00` (out)
vs `400.00` (in) doesn't balance under manual basis mode, adjust
`manual_basis`/cash amount to whatever the existing `test_confirm_full_trade`
test (same file, ~line 296) uses as its balancing pattern — copy its
approach rather than guessing at the confirm endpoint's balance rule.

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary"
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_trades.py -k "graded_leg_without_a_card_id_is_accepted or self_routes_to_triage" -v
```
Expected: both FAIL — the first gets a 422 instead of 200 (old code still in
place), the second fails at the `confirm.status_code == 200` assertion for
the same reason (the incoming leg itself was rejected before confirm ever ran).

- [ ] **Step 3: Remove the Decision-14 check**

In `backend/src/merlins_collection/routers/admin/trades.py`, find (around
line 422-437):

```python
    graded_fields = ("company", "grade", "cert_number")
    if kind == "graded":
        missing = [f for f in graded_fields if body.get(f) in (None, "")]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"A graded incoming leg needs {', '.join(missing)}.",
            )
        # Decision 14: a graded leg is ALWAYS a catalog pick. Graded pricing joins on
        # (card_id, company, grade), so a slab with no card_id is unpriceable by
        # construction (RFC 0009) -- not a state to create by accident from a trade.
        if not body.get("card_id"):
            raise HTTPException(
                status_code=422,
                detail="A graded incoming leg must be linked to a catalog card.",
            )
    else:
```

Delete the `if not body.get("card_id"):` block (and its Decision-14
comment), keeping the `missing` required-fields check above it intact:

```python
    graded_fields = ("company", "grade", "cert_number")
    if kind == "graded":
        missing = [f for f in graded_fields if body.get(f) in (None, "")]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"A graded incoming leg needs {', '.join(missing)}.",
            )
        # RFC 0012: card_id is no longer required for a graded leg. A graded
        # item with no card_id is unpriceable by construction (same state a
        # JP slab is already in, see services/slab/pricing.py) and self-routes
        # to Triage via services/triage.py's is_missing_card_id — no routing
        # code needed here.
    else:
```

Do not touch the `else:` branch below it (the raw-leg-carrying-graded-fields
422) — that rule is unrelated and stays.

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_trades.py -v
```
Expected: PASS, full file (not just the two new/changed tests) — confirms
nothing else in this file assumed the removed 422.

- [ ] **Step 5: Run the full backend suite**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/merlins_collection/routers/admin/trades.py backend/tests/routers/admin/test_trades.py
git commit -m "fix(rfc-0012): allow graded trade incoming leg without card_id"
```
