"""Single-table DynamoDB repository for catalog cards, inventory, and prices.

Everything lives in one table keyed by ``PK``/``SK`` plus one GSI
(``GSI1PK``/``GSI1SK``); every item carries an ``entity`` tag. This module is the
*only* place that knows the key formats — callers work in domain models. Key
layout (see ``backend/README.md`` for the access patterns):

====================  ====================  ============================================
entity                PK                    SK
====================  ====================  ============================================
catalog_card          ``CARD#<id>``         ``META``
inventory_item        ``INV#<shard>``       ``ITEM#<item_id>``
graded_price          ``CARD#<id>``         ``GRADEDPRICE#<company>#<grade>``
price_point           ``CARD#<id>``         ``PRICE#RAW#<finish>#<date>`` / ``PRICE#GRADED#...``
====================  ====================  ============================================

Inventory is sharded across ``INVENTORY_SHARD_COUNT`` partitions (by a stable
hash of ``item_id``) so a single "all inventory" partition never goes hot;
``list_inventory`` fans out across every shard. Card-linked items also carry
sparse GSI1 keys (``CARD#<card_id>`` / ``ITEM#<item_id>``) for by-card lookups;
sealed/bulk items have no card and stay out of GSI1.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from merlins_collection.models.business import (
    BalanceSheetSnapshot,
    BuyingPolicy,
    CashAccount,
    Consignor,
    Debt,
    Expense,
    PaymentMethod,
    Payout,
    Show,
    Transaction,
)
from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import InventoryItemAdapter

logger = logging.getLogger(__name__)

INVENTORY_SHARD_COUNT = 10

# A throttled BatchGetItem returns its keys in ``UnprocessedKeys`` on a *200*
# response (no exception), so boto3's own retries never fire — we must bound the
# drain loop ourselves or a sustained throttle hangs the request forever.
_MAX_BATCH_ATTEMPTS = 8


def _grade_key(grade) -> str:
    # Canonical string for a grade in a key: trailing zeros stripped, plain (non-exponent) notation.
    return f"{Decimal(str(grade)).normalize():f}"


def _bucket(key: str) -> int:
    # Shard an inventory ``item_id`` (or txn's item_id) across INVENTORY_SHARD_COUNT
    # partitions via md5 — stable across processes, unlike builtin hash() which is
    # salted by PYTHONHASHSEED.
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
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


class ItemAlreadySoldError(Exception):
    """The sale's target item is already sold (or doesn't exist)."""


class ImportInProgressError(Exception):
    """Another import already holds the single-flight import lock.

    Raised by ``acquire_import_lock`` when a live (non-expired) lock is held, so a
    second concurrent run refuses to start rather than racing the first into a
    mutual-wipe. The lock — not cross-machine ULID wall-clock ordering — is what
    makes the finalize swap safe under concurrency (BLOCKING-4).
    """


class InventoryRepository:
    """Data-access layer over the single DynamoDB table.

    Reads/writes domain models (``CatalogCard``, ``InventoryItem``,
    ``PricePoint``) and hides the key schema. ``endpoint_url`` is for local /
    moto testing; production points at real DynamoDB via the default endpoint.
    """

    def __init__(self, table_name, *, endpoint_url=None, region_name="us-east-1"):
        self._import_gen = None  # set during an import so writes carry a generation
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
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        self._table.wait_until_exists()

    # Entities the spreadsheet import OWNS and fully replaces on each run. The
    # catalog side (catalog_card / price_point / graded_price / item_price_point)
    # is NOT import-owned and is preserved.
    _IMPORT_OWNED_ENTITIES = frozenset({
        "inventory_item", "transaction", "expense", "debt", "payout",
        "show", "consignor", "cash_account", "buying_policy", "payment_method",
        "balance_sheet_snapshot",
    })

    # Every import-owned entity EXCEPT the two month-partitioned ledgers lives in
    # one of these fixed partitions (plus the ten ``INV#`` inventory shards), which
    # is what makes "does this table already hold business data?" answerable
    # without a table scan.
    _BUSINESS_PARTITIONS = ("SHOWLIST", "DEBTLIST", "PAYOUTLIST", "BALANCESHEET",
                            "CONSIGNORLIST", "CONFIG")

    def find_import_owned_entity(self) -> str | None:
        """Name of an import-owned entity already present in this table, else ``None``.

        Cheap by construction: one ``Limit=1``, strongly-consistent Query per KNOWN
        business partition — the ten ``INV#`` shards plus the six fixed lists above,
        ~16 single-item reads regardless of table size. It never queries the
        ``CARD#``/``ITEM#`` partitions where the ~53k-row catalog lives, so the
        catalog can neither be mistaken for business data nor make the probe
        expensive. No ``FilterExpression`` is used (a filtered page can come back
        empty while the partition is not), so a non-empty partition always yields a
        row; the ``entity`` tag is then checked against ``_IMPORT_OWNED_ENTITIES``,
        which is what keeps the non-owned ``import_lock`` item from tripping it.

        The month-partitioned ledgers (``TXN#<YYYY-MM>``, ``EXP#<YYYY-MM>``) have
        unbounded partition names and are deliberately NOT probed: neither can exist
        in isolation. Every import seeds the ``CONFIG`` payment methods before any
        tab runs, and a sale writes its ``INV#`` item alongside the txn, so any run
        that produced a ledger row necessarily left a probed partition non-empty —
        and a rollback removes both together, since they share one generation.
        """
        partitions = [f"INV#{b}" for b in range(INVENTORY_SHARD_COUNT)]
        partitions.extend(self._BUSINESS_PARTITIONS)
        for pk in partitions:
            kwargs = {
                "KeyConditionExpression": Key("PK").eq(pk),
                "ProjectionExpression": "PK, SK, #e",
                "ExpressionAttributeNames": {"#e": "entity"},
                "ConsistentRead": True,
                "Limit": 1,
            }
            while True:
                resp = self._table.query(**kwargs)
                for item in resp.get("Items", []):
                    if item.get("entity") in self._IMPORT_OWNED_ENTITIES:
                        return item["entity"]
                last = resp.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
        return None

    # ---- single-flight import lock (BLOCKING-4) ----
    # A conditional-write lock item. Only one import may be in flight at a time,
    # so `finalize_import`'s "delete every generation that is not mine" swap can
    # never race a concurrent run. This replaces R5's monotonic ULID ordering,
    # which rested on cross-machine wall-clock agreement (clock skew / a backward
    # NTP step could invert it and let an older-content run delete a newer
    # committed generation). The lock item is NOT an import-owned entity, so
    # `finalize_import` never sweeps it.
    _LOCK_KEY = {"PK": "IMPORTLOCK", "SK": "LOCK"}
    _LOCK_TTL_SECONDS = 3600  # >> a full import; only a crashed holder is stolen

    def acquire_import_lock(self, gen, *, ttl_seconds: int | None = None):
        """Take the single-flight import lock for ``gen``.

        Conditional on the lock being absent or EXPIRED, so a crashed holder's
        stale lock is reclaimed after ``ttl_seconds`` instead of wedging imports
        forever. Raises ``ImportInProgressError`` if a live lock is held.
        """
        ttl = self._LOCK_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        now = int(time.time())
        try:
            self._table.put_item(
                Item={**self._LOCK_KEY, "entity": "import_lock", "gen": gen,
                      "acquired_at": now, "expires_at": now + ttl},
                ConditionExpression="attribute_not_exists(PK) OR #x < :now",
                ExpressionAttributeNames={"#x": "expires_at"},
                ExpressionAttributeValues={":now": now},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ImportInProgressError(
                    "another import is already in flight (import lock held); "
                    "refusing to start a second run"
                ) from exc
            raise

    def release_import_lock(self, gen):
        """Release the lock if we still hold it (no-op if it was stolen)."""
        try:
            self._table.delete_item(
                Key=self._LOCK_KEY,
                ConditionExpression="#g = :gen",
                ExpressionAttributeNames={"#g": "gen"},
                ExpressionAttributeValues={":gen": gen},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            logger.warning("import lock was not ours to release (gen=%r)", gen)

    # ---- import generations (load-then-swap replace) ----
    def set_import_generation(self, gen):
        """Stamp every subsequent import-owned write with ``gen`` (None to stop).
        Lets ``finalize_import`` swap generations without destroying old data
        until the new one is fully written."""
        self._import_gen = gen

    def _gen(self) -> dict:
        return {"gen": self._import_gen} if self._import_gen else {}

    def _gen_sk(self, sk: str) -> str:
        """Suffix a NATURAL/deterministic-key SK with the current import generation.

        Stable-key entities (show, consignor, cash_account, buying_policy,
        payment_method, the non-frozen balance sheet) would otherwise overwrite
        their prior copy IN PLACE during the load phase — before commit/rollback is
        decided — leaving no prior generation for the swap to protect and no
        survivor for a rollback to restore (BLOCKING-1b). Generation-scoping their
        sort key makes old and new coexist until `finalize_import` swaps them,
        exactly like the fresh-ULID ledgers. Within one run the gen is constant, so
        natural-key de-duplication still works (same key -> overwrite).
        """
        return f"{sk}#{self._import_gen}" if self._import_gen else sk

    def finalize_import(self, gen, *, committed: bool) -> int:
        """End an import stamped with ``gen`` (load-then-swap):

        * ``committed=True`` — delete every import-owned record that is NOT of this
          generation (the previous generation + orphans). Old data is removed only
          now, after the whole new dataset landed. Correctness rests on the
          single-flight import lock, not on generation *values*: because only one
          import runs at a time, any other generation present is necessarily a
          PRIOR committed run, so the run that commits LAST wins — independent of
          wall-clock/ULID ordering (BLOCKING-4).
        * ``committed=False`` — delete every record OF this generation (roll back
          this run); every other generation is left untouched. Stable-key entities
          are generation-scoped (``_gen_sk``), so their prior copies survive a
          rollback instead of being destroyed by an in-place overwrite
          (BLOCKING-1b).

        The scan reads strongly-consistently (``ConsistentRead=True``) so a record
        written into this generation milliseconds earlier is never stale-read as
        prior and deleted on its own commit (BLOCKING-3).

        A FROZEN balance-sheet snapshot is never deleted on a COMMIT: the baseline
        is an immutable, non-re-derivable point-in-time record that outlives every
        generation (BLOCKING-1a). A rollback still removes one that this failed run
        itself created, so a bad baseline is never locked in permanently.

        The catalog/price entities are never touched. Returns records removed.
        """
        this_gen_keys: list[dict] = []
        other_gen_keys: list[dict] = []
        kwargs = {
            "ProjectionExpression": "PK, SK, #e, #g, #f",
            "ExpressionAttributeNames": {"#e": "entity", "#g": "gen",
                                         "#f": "frozen"},
            "ConsistentRead": True,
        }
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                entity = item.get("entity")
                if entity not in self._IMPORT_OWNED_ENTITIES:
                    continue
                key = {"PK": item["PK"], "SK": item["SK"]}
                if entity == "balance_sheet_snapshot" and item.get("frozen"):
                    # The immutable baseline is never swept by a commit. Only a
                    # ROLLBACK removes one, and only if THIS failed run created it.
                    if not committed and item.get("gen") == gen:
                        this_gen_keys.append(key)
                    continue
                if item.get("gen") == gen:
                    this_gen_keys.append(key)
                else:
                    other_gen_keys.append(key)
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        keys = other_gen_keys if committed else this_gen_keys
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)
        return len(keys)

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
        """Insert/overwrite catalog cards in bulk.

        ``overwrite_by_pkeys`` is load-bearing, not tidiness: boto3 does NOT
        deduplicate a batch, so two rows carrying the same id in one page raise
        ``ValidationException: Provided list of item keys contains duplicates``
        and fail the entire 25-item batch — killing the run over rows that were
        merely redundant, not wrong. With it, the last write of a key wins.
        """
        with self._table.batch_writer(  # auto-chunks to 25 + retries unprocessed
            overwrite_by_pkeys=["PK", "SK"]
        ) as batch:
            for card in cards:
                batch.put_item(Item=self._catalog_item(card))

    def batch_get_catalog_cards(self, card_ids):
        """Point-read many catalog cards at once; missing ids are simply absent.

        Returns ``{card_id: CatalogCard}``. Chunks at DynamoDB's 100-key
        BatchGetItem limit and retries ``UnprocessedKeys`` until drained.
        """
        unique_ids = list(dict.fromkeys(card_ids))
        found: dict[str, CatalogCard] = {}
        for start in range(0, len(unique_ids), 100):
            keys = [
                {"PK": f"CARD#{cid}", "SK": "META"}
                for cid in unique_ids[start:start + 100]
            ]
            for attempt in range(_MAX_BATCH_ATTEMPTS):
                resp = self._resource.batch_get_item(
                    RequestItems={self._table_name: {"Keys": keys}}
                )
                for item in resp.get("Responses", {}).get(self._table_name, []):
                    card = CatalogCard.model_validate(item)
                    found[card.card_id] = card
                keys = (
                    resp.get("UnprocessedKeys", {})
                    .get(self._table_name, {})
                    .get("Keys", [])
                )
                if not keys:
                    break
                # Back off before retrying the throttled keys (skipped once we're
                # about to exit the loop on the final attempt).
                if attempt < _MAX_BATCH_ATTEMPTS - 1:
                    time.sleep(min(0.05 * 2**attempt, 1.0))
            else:
                # Exhausted retries with keys still throttled — give up rather than
                # loop forever; those ids are simply absent (enrichment degrades).
                logger.warning(
                    "batch_get_catalog_cards: %d keys still unprocessed after %d "
                    "attempts; returning partial result",
                    len(keys),
                    _MAX_BATCH_ATTEMPTS,
                )
        return found

    def iter_catalog_cards(self):
        """Yield every catalog card (paginated scan; import-time only)."""
        from boto3.dynamodb.conditions import Attr

        kwargs = {"FilterExpression": Attr("entity").eq("catalog_card")}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                yield CatalogCard.model_validate(item)
            last = resp.get("LastEvaluatedKey")
            if not last:
                return
            kwargs["ExclusiveStartKey"] = last

    def list_cards_by_set(self, set_id):
        """Return every catalog card in a set via the GSI1 ``SET#`` partition."""
        items = self._query_all(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"SET#{set_id}")
            & Key("GSI1SK").begins_with("CARD#"),
        )
        return [CatalogCard.model_validate(i) for i in items]

    # ---- inventory (keyed by item_id; card link is a sparse GSI1) ----
    def put_inventory_item(self, item):
        """Insert or overwrite one inventory item (one physical unit)."""
        body = _serialize(item.model_dump(mode="python"))
        record = {
            "PK": f"INV#{_bucket(item.item_id)}",
            "SK": f"ITEM#{item.item_id}",
            "entity": "inventory_item",
            **self._gen(),
            **body,
        }
        card_id = getattr(item, "card_id", None)
        if card_id:
            record["GSI1PK"] = f"CARD#{card_id}"
            record["GSI1SK"] = f"ITEM#{item.item_id}"
        self._table.put_item(Item=record)

    def get_inventory_item(self, item_id: str):
        """Fetch one item by id, or ``None`` if absent.

        Strongly consistent: the only caller is the decision applier, which reads
        an item to decide whether to write it. An eventually-consistent read there
        could validate against a stale copy — and could report "already applied"
        for a row a previous batch had only just changed.
        """
        found = self._table.get_item(
            Key={"PK": f"INV#{_bucket(item_id)}", "SK": f"ITEM#{item_id}"},
            ConsistentRead=True,
        ).get("Item")
        return InventoryItemAdapter.validate_python(found) if found else None

    def delete_inventory_item(self, item_id: str):
        """Delete one item by id."""
        self._table.delete_item(
            Key={"PK": f"INV#{_bucket(item_id)}", "SK": f"ITEM#{item_id}"}
        )

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
            & Key("GSI1SK").begins_with("ITEM#"),
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

    # ---- transaction ledger ----
    @staticmethod
    def _txn_keys(txn: Transaction) -> dict:
        keys = {
            "PK": f"TXN#{txn.date.strftime('%Y-%m')}",
            "SK": f"{txn.date.isoformat()}#{txn.txn_id}",
        }
        if txn.show_id:
            keys["GSI2PK"] = f"SHOW#{txn.show_id}"
            keys["GSI2SK"] = f"{txn.date.isoformat()}#{txn.txn_id}"
        return keys

    def put_transaction(self, txn: Transaction):
        """Append one ledger record (purchase or sale)."""
        body = _serialize(txn.model_dump(mode="python"))
        self._table.put_item(Item={**self._txn_keys(txn), "entity": "transaction",
                                    **self._gen(), **body})

    def _query_month_partitions(self, prefix: str, start: date, end: date):
        """Walk ``<prefix>#<YYYY-MM>`` partitions from ``start`` to ``end`` and
        return every row whose SK date falls in ``[start, end]``.

        The upper bound gets a ``#~`` suffix: ``~`` sorts after every id
        character, making the ``between`` inclusive of the end date. Shared by
        the transaction and expense ledgers so the inclusive-bound trick lives in
        exactly one place.
        """
        results = []
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            results.extend(self._query_all(
                KeyConditionExpression=Key("PK").eq(f"{prefix}#{year:04d}-{month:02d}")
                & Key("SK").between(start.isoformat(), end.isoformat() + "#~"),
            ))
            month += 1
            if month == 13:
                year, month = year + 1, 1
        return results

    def list_transactions(self, start: date, end: date):
        """All ledger records with start <= date <= end (month-partition walk)."""
        return [Transaction.model_validate(i)
                for i in self._query_month_partitions("TXN", start, end)]

    def record_sale(self, txn: Transaction):
        """Atomically append the sale txn and flip its item to ``sold``.

        Condition-guarded: if the item is missing or already sold, nothing is
        written and ``ItemAlreadySoldError`` is raised. The resource-derived
        client auto-marshals plain Python values (boto3 injects the DynamoDB
        document transform), so values are passed unmarshalled here.
        """
        txn_item = {**self._txn_keys(txn), "entity": "transaction", **self._gen(),
                    **_serialize(txn.model_dump(mode="python"))}
        try:
            self._resource.meta.client.transact_write_items(TransactItems=[
                {"Put": {
                    "TableName": self._table_name,
                    "Item": txn_item,
                }},
                {"Update": {
                    "TableName": self._table_name,
                    "Key": {
                        "PK": f"INV#{_bucket(txn.item_id)}",
                        "SK": f"ITEM#{txn.item_id}",
                    },
                    "UpdateExpression": "SET #status = :sold",
                    "ConditionExpression":
                        "attribute_exists(PK) AND #status <> :sold",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {":sold": "sold"},
                }},
            ])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                raise ItemAlreadySoldError(txn.item_id) from exc
            raise

    # ---- expense ledger (own EXP# month partitions; deliberately off GSI2) ----
    def put_expense(self, expense: Expense):
        """Append one expense. Kept out of GSI2 so the show index stays purely
        transactions; per-show costs are derived by filtering ``list_expenses``."""
        body = _serialize(expense.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": f"EXP#{expense.date.strftime('%Y-%m')}",
            "SK": f"{expense.date.isoformat()}#{expense.expense_id}",
            "entity": "expense", **self._gen(), **body,
        })

    def list_expenses(self, start: date, end: date):
        """All expenses with start <= date <= end (month-partition walk)."""
        return [Expense.model_validate(i)
                for i in self._query_month_partitions("EXP", start, end)]

    def list_transactions_for_show(self, show_id: str):
        items = self._query_all(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"SHOW#{show_id}"),
        )
        return [Transaction.model_validate(i) for i in items]

    # ---- shows ----
    def put_show(self, show: Show):
        """Insert one show/event day (generation-scoped during an import)."""
        body = _serialize(show.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "SHOWLIST",
            "SK": self._gen_sk(f"SHOW#{show.date.isoformat()}#{show.show_id}"),
            "entity": "show", **self._gen(), **body,
        })

    def list_shows(self):
        """Return every show, oldest first (SK embeds the date)."""
        items = self._query_all(KeyConditionExpression=Key("PK").eq("SHOWLIST"))
        return [Show.model_validate(i) for i in items]

    def get_show(self, show_id: str):
        """Return one show by id, or ``None``. (SK embeds the date, so a point
        read would need it; the show list is tiny, so filter instead.)"""
        return next((s for s in self.list_shows() if s.show_id == show_id), None)

    # ---- debts (single small partition, both directions) ----
    def put_debt(self, debt: Debt):
        body = _serialize(debt.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "DEBTLIST",
            "SK": f"DEBT#{debt.direction.value}#{debt.date.isoformat()}#{debt.debt_id}",
            "entity": "debt", **self._gen(), **body,
        })

    def list_debts(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("DEBTLIST"))
        return [Debt.model_validate(i) for i in items]

    # ---- payouts (single small partition) ----
    def put_payout(self, payout: Payout):
        body = _serialize(payout.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "PAYOUTLIST",
            "SK": f"PAYOUT#{payout.partner}#{payout.payout_id}",
            "entity": "payout", **self._gen(), **body,
        })

    def list_payouts(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("PAYOUTLIST"))
        return [Payout.model_validate(i) for i in items]

    # ---- balance sheet snapshots (BALANCESHEET partition) ----
    def put_balance_sheet(self, snapshot: BalanceSheetSnapshot):
        """Store a balance-sheet snapshot.

        A FROZEN snapshot is the immutable, non-re-derivable baseline: it is
        written at a FIXED key (never generation-scoped) and ``finalize_import``
        never sweeps it on a commit, so it survives every later generation.
        Write-once is enforced by the importer, which refuses to re-write an
        existing baseline. It still carries the generation that CREATED it, so a
        rollback can undo a baseline captured by a run that later failed — without
        that, a truncated first export would permanently lock in a bad baseline
        that write-once forbids correcting.

        The non-frozen ``current`` snapshot is generation-scoped and swapped like
        every other stable-key entity.
        """
        body = _serialize(snapshot.model_dump(mode="python"))
        sk = f"SNAPSHOT#{snapshot.label}#{snapshot.snapshot_id}"
        self._table.put_item(Item={
            "PK": "BALANCESHEET",
            "SK": sk if snapshot.frozen else self._gen_sk(sk),
            "entity": "balance_sheet_snapshot", **self._gen(), **body,
        })

    def get_frozen_balance_sheet(self, label: str):
        """Return the immutable frozen snapshot for ``label``, or ``None``.

        Used by the importer to enforce write-once: an already-captured baseline is
        never overwritten by a later (possibly truncated) export.
        """
        return next((s for s in self.list_balance_sheets()
                     if s.frozen and s.label == label), None)

    def list_balance_sheets(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("BALANCESHEET"))
        return [BalanceSheetSnapshot.model_validate(i) for i in items]

    # ---- consignors ----
    def put_consignor(self, consignor: Consignor):
        """Insert one consignor (generation-scoped during an import)."""
        body = _serialize(consignor.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "CONSIGNORLIST",
            "SK": self._gen_sk(f"CONSIGNOR#{consignor.consignor_id}"),
            "entity": "consignor", **self._gen(), **body,
        })

    def list_consignors(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("CONSIGNORLIST"))
        return [Consignor.model_validate(i) for i in items]

    # ---- config entities (CONFIG partition) ----
    def _put_config(self, sk: str, entity: str, model):
        body = _serialize(model.model_dump(mode="python"))
        self._table.put_item(Item={"PK": "CONFIG", "SK": self._gen_sk(sk),
                                   "entity": entity, **self._gen(), **body})

    def _list_config(self, prefix: str, model_cls):
        items = self._query_all(
            KeyConditionExpression=Key("PK").eq("CONFIG") & Key("SK").begins_with(prefix)
        )
        return [model_cls.model_validate(i) for i in items]

    def put_cash_account(self, account: CashAccount):
        self._put_config(f"CASH#{account.account}", "cash_account", account)

    def list_cash_accounts(self):
        return self._list_config("CASH#", CashAccount)

    def put_buying_policy(self, policy: BuyingPolicy):
        self._put_config(f"BUYPOLICY#{policy.product_type}", "buying_policy", policy)

    def list_buying_policies(self):
        return self._list_config("BUYPOLICY#", BuyingPolicy)

    def put_payment_method(self, method: PaymentMethod):
        self._put_config(f"PAYMETHOD#{method.method}", "payment_method", method)

    def get_payment_method(self, method: str):
        """Return one payment method by name, or ``None``.

        Filters the (tiny) list rather than point-reading a fixed SK, because
        config SKs are generation-scoped during an import (see ``_gen_sk``).
        """
        return next((m for m in self.list_payment_methods() if m.method == method),
                    None)

    def list_payment_methods(self):
        return self._list_config("PAYMETHOD#", PaymentMethod)

    # ---- per-item price history (sealed/bulk have no card to hang history on) ----
    def append_item_price_point(self, item_id: str, day: date, value: Decimal):
        """Record one dated market-value point for a non-card item."""
        self._table.put_item(Item={
            "PK": f"ITEM#{item_id}", "SK": f"PRICE#{day.isoformat()}",
            "entity": "item_price_point", "item_id": item_id,
            "date": day.isoformat(), "market_value": value,
        })

    def get_item_price_history(self, item_id: str):
        """Return an item's price points as raw dicts, oldest first."""
        return self._query_all(
            KeyConditionExpression=Key("PK").eq(f"ITEM#{item_id}")
            & Key("SK").begins_with("PRICE#")
        )

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
