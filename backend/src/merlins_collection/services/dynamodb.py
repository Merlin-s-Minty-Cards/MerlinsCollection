"""Single-table DynamoDB repository for catalog cards, inventory, and prices.

Everything lives in one table keyed by ``PK``/``SK`` plus one GSI
(``GSI1PK``/``GSI1SK``); every item carries an ``entity`` tag. This module is the
*only* place that knows the key formats — callers work in domain models. Key
layout (see ``backend/README.md`` for the access patterns):

====================  ====================  ============================================
entity                PK                    SK
====================  ====================  ============================================
catalog_card          ``CARD#<id>``         ``META``
inventory_item (raw)  ``INV#<shard>``       ``CARD#<id>#RAW#<finish>#<condition>``
inventory_item (grd)  ``INV#<shard>``       ``CARD#<id>#GRADED#<company>#<grade>#<cert>``
graded_price          ``CARD#<id>``         ``GRADEDPRICE#<company>#<grade>``
price_point           ``CARD#<id>``         ``PRICE#RAW#<finish>#<date>`` / ``PRICE#GRADED#...``
====================  ====================  ============================================

Inventory is sharded across ``INVENTORY_SHARD_COUNT`` partitions (by a stable
hash of ``card_id``) so a single "all inventory" partition never goes hot;
``list_inventory`` fans out across every shard.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Key

from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import InventoryItemAdapter

INVENTORY_SHARD_COUNT = 10


def _grade_key(grade) -> str:
    # Canonical string for a grade in a key: trailing zeros stripped, plain (non-exponent) notation.
    return f"{Decimal(str(grade)).normalize():f}"


def _bucket(card_id: str) -> int:
    # Stable across processes — never use builtin hash() (salted by PYTHONHASHSEED).
    digest = hashlib.md5(card_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % INVENTORY_SHARD_COUNT


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


class InventoryRepository:
    """Data-access layer over the single DynamoDB table.

    Reads/writes domain models (``CatalogCard``, ``InventoryItem``,
    ``PricePoint``) and hides the key schema. ``endpoint_url`` is for local /
    moto testing; production points at real DynamoDB via the default endpoint.
    """

    def __init__(self, table_name, *, endpoint_url=None, region_name="us-east-1"):
        self._resource = boto3.resource(
            "dynamodb", endpoint_url=endpoint_url, region_name=region_name
        )
        self._table_name = table_name
        self._table = self._resource.Table(table_name)

    # ---- table management (tests / local dev; prod table is provisioned by infra) ----
    def create_table(self):
        """Create the table + GSI1 and block until it's active (tests/local dev)."""
        self._resource.create_table(
            TableName=self._table_name,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        self._table.wait_until_exists()

    # ---- internal helpers ----
    def _query_all(self, **kwargs):
        """Run a query, following ``LastEvaluatedKey`` until all pages are read."""
        items = []
        while True:
            resp = self._table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                return items
            kwargs["ExclusiveStartKey"] = last

    def _catalog_item(self, card: CatalogCard) -> dict:
        body = _serialize(card.model_dump(mode="python"))
        return {
            "PK": f"CARD#{card.card_id}",
            "SK": "META",
            "GSI1PK": f"SET#{card.set_id}",
            "GSI1SK": f"CARD#{card.card_id}",
            "entity": "catalog_card",
            **body,
        }

    # ---- catalog ----
    def get_catalog_card(self, card_id):
        """Point-read one catalog card by id, or ``None`` if it isn't synced."""
        item = self._table.get_item(Key={"PK": f"CARD#{card_id}", "SK": "META"}).get("Item")
        return CatalogCard.model_validate(item) if item else None

    def batch_upsert_catalog_cards(self, cards):
        """Insert/overwrite catalog cards in bulk (used by the daily sync)."""
        with self._table.batch_writer() as batch:  # auto-chunks to 25 + retries unprocessed
            for card in cards:
                batch.put_item(Item=self._catalog_item(card))

    def list_cards_by_set(self, set_id):
        """Return every catalog card in a set via the GSI1 ``SET#`` partition."""
        items = self._query_all(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"SET#{set_id}")
            & Key("GSI1SK").begins_with("CARD#"),
        )
        return [CatalogCard.model_validate(i) for i in items]

    # ---- inventory ----
    def _inventory_keys(self, item) -> tuple[str, str, str]:
        """Compose ``(PK, SK, GSI1SK)`` for an inventory item from its identity."""
        pk = f"INV#{_bucket(item.card_id)}"
        if item.kind == "raw":
            sk = f"CARD#{item.card_id}#RAW#{item.finish}#{item.condition}"
            gsi1sk = f"INV#RAW#{item.finish}#{item.condition}"
        else:
            grade_key = _grade_key(item.grade)
            sk = f"CARD#{item.card_id}#GRADED#{item.company}#{grade_key}#{item.cert_number}"
            gsi1sk = f"INV#GRADED#{item.company}#{grade_key}"
        return pk, sk, gsi1sk

    def put_inventory_item(self, item):
        """Insert or overwrite a single inventory item (keyed by its identity)."""
        pk, sk, gsi1sk = self._inventory_keys(item)
        body = _serialize(item.model_dump(mode="python"))
        self._table.put_item(
            Item={
                "PK": pk, "SK": sk,
                "GSI1PK": f"CARD#{item.card_id}", "GSI1SK": gsi1sk,
                "entity": "inventory_item", **body,
            }
        )

    def get_inventory_item(self, item):
        """Fetch the stored copy of an item by identity, or ``None`` if absent.

        Takes a model so the caller can round-trip an item it already holds; only
        the key fields are used to locate it.
        """
        pk, sk, _ = self._inventory_keys(item)
        found = self._table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
        return InventoryItemAdapter.validate_python(found) if found else None

    def delete_inventory_item(self, item):
        """Delete an inventory item identified by its key fields."""
        pk, sk, _ = self._inventory_keys(item)
        self._table.delete_item(Key={"PK": pk, "SK": sk})

    def list_inventory(self):
        """Return the entire inventory, fanning out across all shard partitions."""
        items = []
        for bucket in range(INVENTORY_SHARD_COUNT):
            items.extend(self._query_all(KeyConditionExpression=Key("PK").eq(f"INV#{bucket}")))
        return [InventoryItemAdapter.validate_python(i) for i in items]

    def list_inventory_for_card(self, card_id):
        """Return every inventory item for one card via the GSI1 ``CARD#`` partition."""
        items = self._query_all(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"CARD#{card_id}")
            & Key("GSI1SK").begins_with("INV#"),
        )
        return [InventoryItemAdapter.validate_python(i) for i in items]

    # ---- graded current price (separate item; catalog put never touches it) ----
    def set_graded_market_value(self, card_id, company, grade, value: Decimal):
        """Record the current manual market value for a graded slab.

        Stored under its own ``GRADEDPRICE#`` item so a catalog re-sync (which
        overwrites the ``META`` item) never clobbers a hand-entered graded price.
        """
        self._table.put_item(
            Item={
                "PK": f"CARD#{card_id}",
                "SK": f"GRADEDPRICE#{company}#{_grade_key(grade)}",
                "entity": "graded_price",
                "card_id": card_id,
                "company": _serialize(company),
                "grade": grade,
                "market_value": value,
                "source": "manual",
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

    def get_graded_market_value(self, card_id, company, grade):
        """Return the stored graded market value, or ``None`` if none is set."""
        item = self._table.get_item(
            Key={"PK": f"CARD#{card_id}", "SK": f"GRADEDPRICE#{company}#{_grade_key(grade)}"}
        ).get("Item")
        return item["market_value"] if item else None

    # ---- price history ----
    def _price_point_item(self, p: PricePoint) -> dict:
        if p.kind == "raw":
            if not p.finish:
                raise ValueError("raw price points require 'finish'")
            sk = f"PRICE#RAW#{p.finish}#{p.date.isoformat()}"
        else:
            if not p.company or p.grade is None:
                raise ValueError("graded price points require 'company' and 'grade'")
            sk = f"PRICE#GRADED#{p.company}#{_grade_key(p.grade)}#{p.date.isoformat()}"
        body = _serialize(p.model_dump(mode="python"))
        return {"PK": f"CARD#{p.card_id}", "SK": sk, "entity": "price_point", **body}

    def append_price_points(self, points):
        """Bulk-append daily price-history points (one item per point)."""
        with self._table.batch_writer() as batch:
            for p in points:
                batch.put_item(Item=self._price_point_item(p))

    def get_price_history(self, card_id, *, finish=None, company=None,
                          grade=None, start=None, end=None):
        """Return price-history points for a card, narrowed by finish or grade.

        Pass ``company`` (+ ``grade``) for graded history or ``finish`` for raw;
        ``start``/``end`` bound the date range. For a *graded* range query
        ``grade`` is required — without it the ``SK`` prefix spans grades and the
        ``between`` bounds won't line up with the grade-segmented keys.
        """
        if company is not None:
            if grade is not None:
                prefix = f"PRICE#GRADED#{company}#{_grade_key(grade)}#"
            else:
                prefix = f"PRICE#GRADED#{company}#"
        elif finish is not None:
            prefix = f"PRICE#RAW#{finish}#"
        else:
            prefix = "PRICE#RAW#"
        pk = Key("PK").eq(f"CARD#{card_id}")
        if start is not None or end is not None:
            if company is not None and grade is None:
                raise ValueError("graded range queries require 'grade'")
            lo = (start or date.min).isoformat()
            hi = (end or date.max).isoformat()
            cond = pk & Key("SK").between(f"{prefix}{lo}", f"{prefix}{hi}")
        else:
            cond = pk & Key("SK").begins_with(prefix)
        items = self._query_all(KeyConditionExpression=cond)
        return [PricePoint.model_validate(i) for i in items]
