# T13 — Slabs can come in through a trade

**RFC:** 0011 §H · **Layer:** backend · **Depends on:** — · **Blocks:** T14, T15
**Owner ask:** *"There needs to be a way for slabs to be going in and out of the trade
menu."*

## Half of this already works — measure before you build

**Trading a slab OUT works today.** Outgoing legs reference an existing `item_id`
(`trades.py:207-211` on the frontend, the outgoing loop on the backend) and never inspect
`kind`, and the search behind the picker is `/inventory/search?status=available` with no
kind filter. A graded item is selectable and sells like any other.

**Coming IN is the gap, and it is one line.** `trades.py:792` hardcodes:

```python
item_data = {
    "kind": "raw",          # <- every incoming leg, unconditionally
    ...
}
```

plus `category=ItemCategory.RAW` on the transaction below it. So a PSA 10 Charizard
received in a trade is written as a **raw NM card**: company, grade and cert are gone, it
never appears in the slab worklist, and `refresh_graded_prices` will never price it
because that job walks graded items.

There is a second, quieter half: `add_incoming_leg` (`trades.py:414-426`) builds the leg
from an **allowlist**, so any graded field the frontend sends is dropped without a word.

## Files

- **Modify:** `backend/src/merlins_collection/routers/admin/trades.py` — the leg allowlist
  (line 414-426), leg validation (line 408-412), the incoming item build (line 786-810)
  and its `Transaction` (line ~812)
- **Test:** `backend/tests/routers/admin/test_trades.py`

## Interfaces

**Produces** (T14 and T15 send exactly these keys):

```
POST /admin/trades/{trade_id}/incoming
{
  "card_id": "en:base1-4",        # REQUIRED for graded (see below)
  "name": "Charizard",
  "agreed_value": 400,
  "kind": "raw" | "graded",       # default "raw"
  # graded only:
  "company": "PSA", "grade": 10, "cert_number": "12345678",
  "grade_label": "GEM MT 10",     # optional
  # raw only:
  "condition": "NM", "finish": "normal"
}
```

## Design

### Validation is symmetric, and both directions are 422

```python
    kind = body.get("kind", "raw")
    if kind not in ("raw", "graded"):
        raise HTTPException(status_code=422, detail=f"Unknown kind {kind!r}...")

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
        present = [f for f in graded_fields if body.get(f) not in (None, "")]
        if present:
            raise HTTPException(
                status_code=422,
                detail=(f"A raw incoming leg cannot carry {', '.join(present)}. "
                        "Set kind to 'graded'."),
            )
```

> **The raw-carrying-graded-fields case is a 422, not a silent drop.** Silently dropping
> them is *exactly* the defect this task fixes, one layer up: the caller believes it sent
> a slab and gets a raw card back. A loud rejection is the only answer that cannot be
> mistaken for success.

### The leg allowlist grows

Add `kind`, `company`, `grade`, `cert_number`, `grade_label` to the dict at line 414. Keep
it an allowlist — it is what stops arbitrary client JSON reaching a stored session.

**`grade` is a number on the wire and must not become a bare float in DynamoDB.**
`services/dynamodb._serialize` coerces `float` → `Decimal` via `str()`, and the trade
session router persists **raw request JSON** — this is precisely the path that 500'd in
production (CLAUDE.md, "Never write a bare `float`"). It works because `_serialize` is
there; do not route around it, and **send `grade` as a JSON number in the tests**, because
every existing test sends strings and that is how the class of bug survived for months.

### The item build branches on kind

```python
        if leg.get("kind") == "graded":
            item_data = {
                **common,
                "kind": "graded",
                "company": leg["company"],
                "grade": str(leg["grade"]),
                "cert_number": leg["cert_number"],
                "grade_label": leg.get("grade_label"),
            }
            category = ItemCategory.GRADED
        else:
            item_data = {
                **common,
                "kind": "raw",
                "finish": leg.get("finish") or "normal",
                "condition": leg.get("condition") or "NM",
            }
            category = ItemCategory.RAW
```

`common` holds everything both kinds share — `item_id`, `card_id`, `status`, `language`,
`location`, `cost_basis`, `market_value_at_purchase`, `current_market_value`,
`acquired_at`, `acquired_show_id`, `display_name`, `lineage_id`, `predecessor_item_id`.
**Do not duplicate that block per branch**; a field added to one and not the other is the
kind of divergence nobody notices until a lineage query comes back empty.

`ItemCategory.GRADED` on the `Transaction` matters beyond tidiness — show analytics and
the ledger group by category, so a slab booked as RAW misreports both.

### The cert-owned warning is the FRONTEND's job, not this endpoint's

`GET /admin/slabs/certs/{cert}` already exists and already answers it. T14 calls it while
the operator types. **This endpoint does not gate on it** — RFC 0009's rule is a *warning
with override, never a gate*, because a slab sold and bought back is legitimate re-entry.
Adding a 409 here would break that deliberately-allowed case.

## RED — write these first, show the failing output, then STOP

In `backend/tests/routers/admin/test_trades.py`:

```python
class TestGradedIncoming:
    """RFC 0011 §H — a slab received in a trade must stay a slab."""

    def test_a_graded_leg_creates_a_graded_item(self, admin_client):
        client, repo, token = admin_client
        trade_id = _start_trade(client, token)
        client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token), json={
            "card_id": "en:base1-4", "name": "Charizard",
            # A JSON NUMBER, not a string. Every existing test sends strings, which is
            # how the bare-float DynamoDB bug survived for months.
            "agreed_value": 400, "kind": "graded",
            "company": "PSA", "grade": 10, "cert_number": "12345678",
        })

        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token), json={})

        [item] = [i for i in repo.list_inventory() if i.kind == "graded"]
        assert item.company == GradingCompany.PSA
        assert item.grade == Decimal("10")
        assert item.cert_number == "12345678"
        assert item.card_id == "en:base1-4"

    def test_the_transaction_is_categorised_graded(self, admin_client):
        """Analytics and the ledger group by category — RAW misreports both."""
        client, repo, token = admin_client
        trade_id = _start_trade(client, token)
        _add_graded_incoming(client, token, trade_id)
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token), json={})

        purchases = [t for t in repo.list_transactions()
                     if t.type == TransactionType.PURCHASE]
        assert [t.category for t in purchases] == [ItemCategory.GRADED]

    def test_a_raw_leg_is_unchanged(self, admin_client):
        """The default path must not move. `kind` is optional and defaults to raw."""
        client, repo, token = admin_client
        trade_id = _start_trade(client, token)
        client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token), json={
            "card_id": "en:base1-4", "name": "Charizard",
            "agreed_value": 40, "condition": "LP",
        })

        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token), json={})

        [item] = [i for i in repo.list_inventory() if i.kind == "raw"]
        assert item.condition == Condition.LP

    def test_a_graded_leg_without_cert_fields_is_a_422(self, admin_client):
        client, _, token = admin_client
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token),
                           json={"card_id": "en:base1-4", "name": "Charizard",
                                 "agreed_value": 400, "kind": "graded"})

        assert resp.status_code == 422
        assert "cert_number" in resp.json()["detail"]

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

    def test_a_raw_leg_carrying_graded_fields_is_a_422(self, admin_client):
        """Silently dropping them is the defect this task fixes, one layer up."""
        client, _, token = admin_client
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token),
                           json={"card_id": "en:base1-4", "name": "Charizard",
                                 "agreed_value": 40, "kind": "raw",
                                 "company": "PSA", "grade": 10, "cert_number": "1"})

        assert resp.status_code == 422

    def test_an_unknown_kind_is_a_422(self, admin_client):
        client, _, token = admin_client
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/incoming", headers=_auth(token),
                           json={"card_id": "en:base1-4", "name": "X",
                                 "agreed_value": 1, "kind": "sealed"})

        assert resp.status_code == 422

    def test_a_graded_leg_survives_the_session_round_trip(self, admin_client):
        """The leg dict is an ALLOWLIST — a field missing from it is dropped silently,
        which is how a slab became a raw card in the first place."""
        client, repo, token = admin_client
        trade_id = _start_trade(client, token)
        _add_graded_incoming(client, token, trade_id)

        session = repo.get_trade_session(trade_id)

        leg = session["incoming_legs"][0]
        assert leg["kind"] == "graded"
        assert leg["cert_number"] == "12345678"
        assert leg["company"] == "PSA"


class TestGradedOutgoingStillWorks:
    def test_a_slab_can_be_traded_out(self, admin_client):
        """Already true before this task — pinned so the branch above cannot break it."""
        client, repo, token = admin_client
        repo.put_inventory_item(_graded_item(item_id="slab", grade="10"))
        trade_id = _start_trade(client, token)

        resp = client.post(f"/admin/trades/{trade_id}/outgoing", headers=_auth(token),
                           json={"item_id": "slab", "name": "Charizard",
                                 "agreed_value": 400})

        assert resp.status_code == 200
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_trades.py -q --tb=short
```

## Watch for

- **Send `grade` and `agreed_value` as JSON numbers in every test.** The router persists
  raw request JSON, and `_serialize` is the only thing standing between a float and a
  boto3 `Float types are not supported` 500. Tests that send strings never exercise it.
- **`_allocate_incoming_basis` splits the basis pool pro-rata across incoming legs.** It
  reads `agreed_value` only and is kind-agnostic — leave it alone, and check the graded
  branch still receives `incoming_basis[index]` exactly as the raw branch does.
- **Build `common` once.** Two per-kind dicts that each restate `lineage_id` and
  `predecessor_item_id` will diverge.
- **Do not add a 409 for an already-owned cert.** Warning with override, never a gate.

## Done means

1. `pytest backend/tests/routers/admin/test_trades.py` passes, output shown;
2. `ruff check backend/src` clean;
3. `progress.md` updated, with a Notes line confirming the exact incoming-leg key names
   for T14/T15.

Do not run the full suite. Do not merge. Do not push.
