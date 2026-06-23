from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import (
    Condition, GradingCompany, RawInventoryItem, GradedInventoryItem,
)
from merlins_collection.services.dynamodb import INVENTORY_SHARD_COUNT, _bucket


def _raw_item(card_id="swsh1-1", finish="holofoil", condition="NM", qty=1):
    return RawInventoryItem(
        card_id=card_id, quantity=qty, listed_price=Decimal("10"),
        cost_basis=Decimal("4"), acquired_at=_date(2026, 1, 1),
        finish=finish, condition=Condition(condition),
    )


def _card(card_id="swsh1-1", set_id="swsh1", market="12.50"):
    return CatalogCard(
        card_id=card_id, name="Celebi V", set_id=set_id, set_name="S&S",
        number="1", images={"small": "s", "large": "l"},
        prices={"holofoil": {"market": Decimal(market)}},
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )


def test_upsert_then_get_catalog_card(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card()])
    got = dynamo_repo.get_catalog_card("swsh1-1")
    assert got is not None
    assert got.name == "Celebi V"
    assert got.prices["holofoil"].market == Decimal("12.50")


def test_get_missing_card_returns_none(dynamo_repo):
    assert dynamo_repo.get_catalog_card("nope") is None


def test_list_cards_by_set(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card("a-1", "setA"), _card("a-2", "setA"), _card("b-1", "setB")])
    cards = dynamo_repo.list_cards_by_set("setA")
    assert {c.card_id for c in cards} == {"a-1", "a-2"}


def test_batch_upsert_handles_more_than_25(dynamo_repo):
    cards = [_card(f"big-{i}", "setBig") for i in range(30)]
    dynamo_repo.batch_upsert_catalog_cards(cards)
    assert len(dynamo_repo.list_cards_by_set("setBig")) == 30


def test_graded_price_set_and_get(dynamo_repo):
    from merlins_collection.models.inventory import GradingCompany

    dynamo_repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500"))
    assert dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10")) == Decimal("500")


def test_graded_price_grade_key_is_normalized(dynamo_repo):
    from merlins_collection.models.inventory import GradingCompany

    dynamo_repo.set_graded_market_value("swsh1-1", GradingCompany.BGS, Decimal("9.5"), Decimal("100"))
    # A differently-spelled-but-equal grade must resolve to the same key.
    assert dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.BGS, Decimal("9.50")) == Decimal("100")


def test_catalog_upsert_does_not_clobber_graded_price(dynamo_repo):
    from merlins_collection.models.inventory import GradingCompany

    dynamo_repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500"))
    dynamo_repo.batch_upsert_catalog_cards([_card()])  # re-sync the same card
    assert dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10")) == Decimal("500")


def _raw_point(card_id, d, market):
    return PricePoint(card_id=card_id, date=d, source="pokemontcg.io",
                      kind="raw", finish="holofoil", market=Decimal(market))


def test_price_history_range_for_finish(dynamo_repo):
    dynamo_repo.append_price_points([
        _raw_point("c1", _date(2026, 6, 20), "10"),
        _raw_point("c1", _date(2026, 6, 21), "11"),
        _raw_point("c1", _date(2026, 6, 22), "12"),
    ])
    got = dynamo_repo.get_price_history(
        "c1", finish="holofoil", start=_date(2026, 6, 21), end=_date(2026, 6, 22)
    )
    assert [p.date for p in got] == [_date(2026, 6, 21), _date(2026, 6, 22)]
    assert got[-1].market == Decimal("12")


def test_price_history_all_raw(dynamo_repo):
    dynamo_repo.append_price_points([_raw_point("c2", _date(2026, 6, 20), "5")])
    assert len(dynamo_repo.get_price_history("c2", finish="holofoil")) == 1


def test_query_pagination_follows_last_evaluated_key(dynamo_repo, monkeypatch):
    # Drive the LastEvaluatedKey loop deterministically (no need for >1MB of data).
    item1 = {"card_id": "c9", "date": "2026-06-20", "source": "x",
             "kind": "raw", "finish": "holofoil", "market": Decimal("1")}
    item2 = {"card_id": "c9", "date": "2026-06-21", "source": "x",
             "kind": "raw", "finish": "holofoil", "market": Decimal("2")}
    calls = []

    def fake_query(**kwargs):
        calls.append(kwargs)
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": [item1], "LastEvaluatedKey": {"PK": "CARD#c9", "SK": "p"}}
        return {"Items": [item2]}

    monkeypatch.setattr(dynamo_repo._table, "query", fake_query)
    got = dynamo_repo.get_price_history("c9", finish="holofoil")
    assert len(got) == 2
    assert len(calls) == 2
    assert "ExclusiveStartKey" in calls[1]


def test_bucket_is_stable_and_in_range():
    assert _bucket("swsh1-1") == _bucket("swsh1-1")
    assert 0 <= _bucket("swsh1-1") < INVENTORY_SHARD_COUNT


def test_put_then_get_inventory_item(dynamo_repo):
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item) == item


def test_delete_inventory_item(dynamo_repo):
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    dynamo_repo.delete_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item) is None


def test_list_inventory_gathers_across_shards(dynamo_repo):
    # card_ids chosen so they land in different buckets in a real run; the count is what matters
    items = [_raw_item(card_id=f"card-{i}") for i in range(25)]
    for it in items:
        dynamo_repo.put_inventory_item(it)
    listed = dynamo_repo.list_inventory()
    assert len(listed) == 25
    assert {i.card_id for i in listed} == {f"card-{i}" for i in range(25)}


def test_list_inventory_for_card(dynamo_repo):
    dynamo_repo.put_inventory_item(_raw_item(condition="NM"))
    dynamo_repo.put_inventory_item(_raw_item(condition="LP"))
    dynamo_repo.put_inventory_item(_raw_item(card_id="other"))
    rows = dynamo_repo.list_inventory_for_card("swsh1-1")
    assert len(rows) == 2
    assert {r.condition for r in rows} == {Condition.NM, Condition.LP}


def test_put_then_get_graded_inventory_item(dynamo_repo):
    item = GradedInventoryItem(
        card_id="swsh1-1", quantity=1, listed_price=Decimal("600"),
        cost_basis=Decimal("300"), acquired_at=_date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number="12345678",
    )
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item) == item
