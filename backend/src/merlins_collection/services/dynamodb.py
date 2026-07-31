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


class CatalogReseedInProgressError(Exception):
    """A catalog reseed already holds the single-flight catalog lock.

    The catalog's counterpart to ``ImportInProgressError``, and deliberately a
    DISTINCT type: the two locks guard unrelated lifecycles, and the daily depth
    pass swallows this one (it skips and retries tomorrow) while an import
    holding up another import is an operator-facing refusal. One exception type
    for both would make the depth pass silently swallow an import collision too.
    """


class InventoryRepository:
    """Data-access layer over the single DynamoDB table.

    Reads/writes domain models (``CatalogCard``, ``InventoryItem``,
    ``PricePoint``) and hides the key schema. ``endpoint_url`` is for local /
    moto testing; production points at real DynamoDB via the default endpoint.
    """

    def __init__(self, table_name, *, endpoint_url=None, region_name="us-east-1"):
        self._import_gen = None  # set during an import so writes carry a generation
        self._catalog_gen = None  # set during a catalog reseed (see purge_card_data)
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

    # Which fixed partitions a SCOPED probe reads for each import-owned entity.
    # Consulted ONLY when a caller narrows `find_import_owned_entity` with
    # ``entities=``; the unscoped probe still walks the full list above, so the
    # default path is untouched by this table's existence.
    #
    # The two month-partitioned ledgers map to NO partition on purpose: their
    # partition names are unbounded (``TXN#<YYYY-MM>`` / ``EXP#<YYYY-MM>``) and
    # are never queried directly, so neither is probeable on its own. Each is
    # covered only in company of an entity that IS probed and that it cannot
    # exist without (a sale writes its ``INV#`` item in the same transaction as
    # its txn row; every import seeds the ``CONFIG`` payment methods before any
    # expense tab runs). A scope naming one of them ALONE is therefore refused
    # rather than silently answering "no data" — see the ``entities`` docs.
    #
    # A test asserts this map covers every ``_IMPORT_OWNED_ENTITIES`` member and
    # that its values union to exactly the unscoped partition list, so the two
    # cannot drift apart when an entity is added.
    _ENTITY_PARTITIONS = {
        "inventory_item": tuple(f"INV#{b}" for b in range(INVENTORY_SHARD_COUNT)),
        "transaction": (),               # TXN#<YYYY-MM> — see above
        "expense": (),                   # EXP#<YYYY-MM> — see above
        "show": ("SHOWLIST",),
        "debt": ("DEBTLIST",),
        "payout": ("PAYOUTLIST",),
        "consignor": ("CONSIGNORLIST",),
        "balance_sheet_snapshot": ("BALANCESHEET",),
        "cash_account": ("CONFIG",),
        "buying_policy": ("CONFIG",),
        "payment_method": ("CONFIG",),
    }

    def find_import_owned_entity(self, *, entities=None) -> str | None:
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

        ``entities`` (default ``None`` = today's full scope, byte-for-byte) narrows
        the question to a SUBSET of ``_IMPORT_OWNED_ENTITIES``: only the partitions
        those entities live in are read, and only their tags count as a hit. A
        single-tab run that will write — and later sweep — nothing but
        ``inventory_item``/``transaction`` asks with that pair, so the live table's
        shows/debts/payouts/consignors/config neither refuse it nor get read.

        Narrowing the probe narrows the PROTECTION with it: an entity left out is
        no longer checked for pre-existing data, which is only safe because the
        caller also never writes or sweeps it. Pair ``entities`` with the matching
        ``finalize_import(entity_scope=...)`` or the guarantee breaks.

        Raises ``ValueError`` for a name that is not import-owned, and for a scope
        with no probeable partition (empty, or only month-partitioned ledgers) —
        such a probe could only ever answer ``None``, which would read as "the
        table is clean" and silently disarm the guard.
        """
        if entities is None:
            wanted = self._IMPORT_OWNED_ENTITIES
            partitions = [f"INV#{b}" for b in range(INVENTORY_SHARD_COUNT)]
            partitions.extend(self._BUSINESS_PARTITIONS)
        else:
            wanted = frozenset(entities)
            unknown = wanted - self._IMPORT_OWNED_ENTITIES
            if unknown:
                raise ValueError(
                    f"cannot scope the re-import probe to {sorted(unknown)}: "
                    f"not import-owned entities")
            partitions = sorted({p for entity in wanted
                                 for p in self._ENTITY_PARTITIONS[entity]})
            if not partitions:
                raise ValueError(
                    f"cannot scope the re-import probe to {sorted(wanted)}: no "
                    f"probeable partition — the month-partitioned ledgers are "
                    f"never queried directly, so this probe could only ever "
                    f"answer 'no data'. Include the entity that stands for them "
                    f"(inventory_item for transaction, a CONFIG entity for "
                    f"expense).")
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
                    if item.get("entity") in wanted:
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
    _LOCK_TTL_SECONDS = 3600  # >> a full import or reseed; only a crashed holder is stolen

    def _acquire_lock(self, key, gen, ttl, *, entity, error, message):
        """Take a single-flight lock item, or raise ``error``.

        ONE algorithm, two configurations (RFC 0003 §8): the import lock and the
        catalog lock differ only in their key, entity tag and refusal message.
        Copying the body per domain is how the two silently drift — one gains a
        TTL reclaim or a condition fix and the other does not — so the domains
        below are thin wrappers and this is the only place the semantics live.

        Conditional on the lock being absent or EXPIRED, so a crashed holder's
        stale lock is reclaimed after ``ttl`` instead of wedging the pipeline
        forever.
        """
        now = int(time.time())
        try:
            self._table.put_item(
                Item={**key, "entity": entity, "gen": gen,
                      "acquired_at": now, "expires_at": now + ttl},
                ConditionExpression="attribute_not_exists(PK) OR #x < :now",
                ExpressionAttributeNames={"#x": "expires_at"},
                ExpressionAttributeValues={":now": now},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise error(message) from exc
            raise

    def _release_lock(self, key, gen, *, label):
        """Delete a lock item if ``gen`` still holds it (no-op if it was stolen)."""
        try:
            self._table.delete_item(
                Key=key,
                ConditionExpression="#g = :gen",
                ExpressionAttributeNames={"#g": "gen"},
                ExpressionAttributeValues={":gen": gen},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            logger.warning("%s lock was not ours to release (gen=%r)", label, gen)

    def acquire_import_lock(self, gen, *, ttl_seconds: int | None = None):
        """Take the single-flight import lock for ``gen``.

        Conditional on the lock being absent or EXPIRED, so a crashed holder's
        stale lock is reclaimed after ``ttl_seconds`` instead of wedging imports
        forever. Raises ``ImportInProgressError`` if a live lock is held.
        """
        self._acquire_lock(
            self._LOCK_KEY, gen,
            self._LOCK_TTL_SECONDS if ttl_seconds is None else ttl_seconds,
            entity="import_lock", error=ImportInProgressError,
            message="another import is already in flight (import lock held); "
                    "refusing to start a second run",
        )

    def release_import_lock(self, gen):
        """Release the lock if we still hold it (no-op if it was stolen)."""
        self._release_lock(self._LOCK_KEY, gen, label="import")

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

    def finalize_import(self, gen, *, committed: bool, entity_scope=None) -> int:
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

        ``entity_scope`` (default ``None`` = today's full ``_IMPORT_OWNED_ENTITIES``
        sweep, byte-for-byte) restricts BOTH halves of the swap to a subset of the
        import-owned entities. Rows of any other entity type are skipped outright —
        never deleted, whatever generation they carry. That is what lets a
        single-tab run replace its own entity types without the sweep reading
        "these were not re-stamped this run" as "these are stale" and destroying
        ledgers the run never even opened.

        The sentinel is ``None``, not falsiness: an EMPTY scope is a caller bug
        (a sweep that can remove nothing), so it raises rather than silently
        turning the swap into a no-op. Unknown entity names raise too.

        *** SCOPING IS BY ENTITY TYPE, WHICH IS COARSER THAN "one tab's rows". ***
        Every tab that writes inventory (Singles, Sealed, Bulk, Consignments)
        writes the SAME ``inventory_item`` entity, so a scoped sweep cannot tell
        one tab's rows from another's — it removes every prior-generation row of
        the types in scope. See ``run_singles_only_import`` in
        ``services/spreadsheet_import.py`` for why that is exactly right today and
        precisely what must change before a second inventory-writing tab is turned
        back on. Do not read this parameter as general multi-tab safety.
        """
        if entity_scope is None:
            scope = self._IMPORT_OWNED_ENTITIES
        else:
            scope = frozenset(entity_scope)
            unknown = scope - self._IMPORT_OWNED_ENTITIES
            if unknown:
                raise ValueError(
                    f"cannot scope the import sweep to {sorted(unknown)}: not "
                    f"import-owned entities")
            if not scope:
                raise ValueError(
                    "entity_scope is empty — a sweep that can remove nothing is a "
                    "caller bug; pass None for the full sweep")
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
                if entity not in scope:
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

    # ---- catalog generations (load-then-swap replace for CARD data) ----
    # The import generation above belongs to the SPREADSHEET pipeline and sweeps
    # `_IMPORT_OWNED_ENTITIES`, which includes shows and consignors. The catalog is
    # written by a different pipeline (TCGdex) and is deliberately not
    # import-owned, so a catalog reseed cannot reuse `finalize_import` without
    # destroying the very business master data D4 says to preserve. It gets its own
    # stamp instead, and `purge_card_data` is the swap half.
    #
    # Only these entities are EVER deleted by that swap. It is an allowlist, not a
    # preserve-list, so an entity nobody thought about (auth tokens, rate-limit
    # counters, anything added later) survives by default rather than by vigilance.
    #
    # This is exactly D4's delete list and nothing more. Two entities that were
    # once here have been deliberately REMOVED, because they are hand-curated and
    # not reseedable:
    #
    # * `graded_price` — slab values entered by hand. TCGdex has no graded prices
    #   at all, so nothing can rebuild them.
    # * `item_price_point` — the only price history sealed/bulk items have; they
    #   have no card to re-derive it from.
    #
    # Stamping them with a catalog generation at their write sites was the other
    # candidate fix and would NOT have worked: the reseed writes only
    # `catalog_card` rows, so such a stamp could only ever record a PAST
    # generation and the next wipe would delete them anyway. They are master data;
    # the wipe simply has no business touching them.
    _CARD_DATA_ENTITIES = frozenset({
        "catalog_card", "price_point", "inventory_item", "transaction",
    })

    # Card-keyed rows: once the catalog is replaced these are orphans by
    # construction, so they are kept only if they carry the incoming generation.
    _CATALOG_GEN_ENTITIES = frozenset({"catalog_card", "price_point"})

    def set_catalog_generation(self, gen):
        """Stamp every subsequent catalog/price write with ``gen`` (None to stop).

        Lets a reseed load a whole new catalog alongside the old one and hand the
        generation to ``purge_card_data``, so the table is never half-empty while
        the site is serving ``/inventory``.
        """
        self._catalog_gen = gen

    def _cat_gen(self) -> dict:
        return {"cat_gen": self._catalog_gen} if self._catalog_gen else {}

    # ---- single-flight catalog lock (RFC 0003 §8) ----
    # A second, PARALLEL lock domain — not an extension of the import lock. The
    # spreadsheet import and a catalog reseed touch disjoint entities and run on
    # unrelated cadences, so sharing one lock item would make each block the other
    # for no reason. Both go through `_acquire_lock`/`_release_lock` above, so
    # there is one algorithm with two configurations rather than a copy.
    #
    # What it actually guards: a reseed's `finalize_catalog` deletes every
    # `catalog_card` not of its generation. A depth-pass write landing after the
    # reseed has passed that card but before the swap carries the OLD generation
    # and is deleted — the card silently vanishes from a live catalog. So the
    # daily depth pass takes this lock too, and skips its whole run when a reseed
    # holds it.
    _CATALOG_LOCK_KEY = {"PK": "CATALOGLOCK", "SK": "LOCK"}

    # The committed catalog generation, written by the reseed's finalize step.
    _CATALOG_GEN_KEY = {"PK": "CATALOGGEN", "SK": "CURRENT"}

    def acquire_catalog_lock(self, gen, *, ttl_seconds: int | None = None):
        """Take the single-flight catalog lock for ``gen``.

        Same conditional-write + TTL-expiry semantics as the import lock, in its
        own key space. Raises ``CatalogReseedInProgressError`` if a live lock is
        held.
        """
        self._acquire_lock(
            self._CATALOG_LOCK_KEY, gen,
            self._LOCK_TTL_SECONDS if ttl_seconds is None else ttl_seconds,
            entity="catalog_lock", error=CatalogReseedInProgressError,
            message="a catalog reseed is already in flight (catalog lock held); "
                    "refusing to start a second run",
        )

    def release_catalog_lock(self, gen):
        """Release the catalog lock if we still hold it (no-op if it was stolen)."""
        self._release_lock(self._CATALOG_LOCK_KEY, gen, label="catalog")

    def current_catalog_generation(self):
        """The generation of the catalog currently committed, or ``None``.

        Read strongly-consistently: the depth pass uses it to stamp its own
        writes, and an eventually-consistent read straight after a reseed's
        finalize would stamp them with the SUPERSEDED generation — precisely the
        rows the next swap deletes.

        ``None`` means no reseed has ever committed a generation (a fresh table,
        or today's not-yet-wired reseed path). Callers stamp nothing in that
        case, which is exactly how catalog writes behave today.
        """
        item = self._table.get_item(
            Key=self._CATALOG_GEN_KEY, ConsistentRead=True
        ).get("Item")
        return item.get("gen") if item else None

    @staticmethod
    def _card_language(pk: str):
        """The language code embedded in a ``CARD#`` partition key, or ``None``.

        ``card_id`` is the composite ``"{lang}:{tcgdex_id}"``, so the language is
        readable straight off the key the scan already projects. ``None`` means
        the row predates that scheme — i.e. it is a dead pokemontcg.io-era row
        ("xy7-54"), which is precisely what the wipe exists to remove, so it must
        never be rescued by language scoping.
        """
        card_id = pk[len("CARD#"):] if pk.startswith("CARD#") else pk
        return card_id.split(":", 1)[0] if ":" in card_id else None

    def purge_card_data(self, *, keep_catalog_gen, languages=None,
                        keep_card_ids=None, dry_run: bool = True) -> dict:
        """Delete card data that is not part of catalog generation ``keep_catalog_gen``.

        This is the SWAP half of the catalog load-then-swap: run it only after the
        new catalog has fully landed. Returns ``{entity: rows}`` counts; with
        ``dry_run`` (the default) it counts without deleting, which is what the
        wipe entrypoint reports before ``--execute`` is given.

        What goes:

        * ``catalog_card`` / ``price_point`` not stamped with ``keep_catalog_gen``;
        * every ``inventory_item`` — D4 rebuilds all holdings from the sheet;
        * ``transaction`` rows carrying an import ``gen``, i.e. derived from a
          spreadsheet import. A sale the live app recorded through ``record_sale``
          carries no generation and is NOT sheet-derived, so it survives — that
          stamp is the only durable evidence of which writer produced a row.

        What stays: everything else, by allowlist (``_CARD_DATA_ENTITIES``).
        Shows, consignors, config, auth and rate-limit rows are never candidates,
        and neither are hand-curated ``graded_price`` / ``item_price_point`` rows.

        ``languages`` scopes the sweep to the language codes the reseed actually
        loaded. Without it, ``--language en`` would mint one generation, stamp
        only English rows with it, and then delete the entire Japanese catalog as
        "not of this generation" — while exiting 0. Retrying one language after an
        abort is a normal operator move, so this is a likely invocation, not a
        contrived one. ``None`` means every language is in scope.

        ``keep_card_ids`` lets a DRY RUN predict honestly. A dry run writes
        nothing, so nothing carries the new generation and the naive count is
        "the entire catalog" — not a prediction, and an operator who sees an
        absurd number learns to ignore the last check standing between them and
        an irreversible wipe. Passing the ids the reseed *would* write makes the
        reported figure the real one.

        ``keep_catalog_gen`` is mandatory. Without one this is not a swap, it is
        "delete the catalog", and a typo would empty the customer-facing table.
        """
        if not keep_catalog_gen:
            raise ValueError(
                "purge_card_data requires keep_catalog_gen: the generation of the "
                "catalog that was just loaded. Without it this would delete every "
                "card row and leave nothing behind."
            )
        counts = dict.fromkeys(self._CARD_DATA_ENTITIES, 0)
        keys: list[dict] = []
        kwargs = {
            "ProjectionExpression": "PK, SK, #e, #g, #c",
            "ExpressionAttributeNames": {"#e": "entity", "#g": "gen",
                                         "#c": "cat_gen"},
            "ConsistentRead": True,
        }
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                entity = item.get("entity")
                if entity not in self._CARD_DATA_ENTITIES:
                    continue
                if entity in self._CATALOG_GEN_ENTITIES:
                    if item.get("cat_gen") == keep_catalog_gen:
                        continue
                    language = self._card_language(item["PK"])
                    if languages is not None and language is not None \
                            and language not in languages:
                        continue  # another language's catalog; not this run's
                    if keep_card_ids is not None and \
                            item["PK"][len("CARD#"):] in keep_card_ids:
                        continue  # the reseed would replace this row, not orphan it
                elif entity == "transaction" and not item.get("gen"):
                    continue
                counts[entity] += 1
                keys.append({"PK": item["PK"], "SK": item["SK"]})
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        if not dry_run:
            with self._table.batch_writer() as batch:
                for key in keys:
                    batch.delete_item(Key=key)
        return counts

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
            **self._cat_gen(),
            **body,
        }

    # ---- catalog ----
    def get_catalog_card(self, card_id):
        """Point-read one catalog card by id, or ``None`` if it isn't synced."""
        item = self._table.get_item(Key={"PK": f"CARD#{card_id}", "SK": "META"}).get("Item")
        return CatalogCard.model_validate(item) if item else None

    def batch_upsert_catalog_cards(self, cards, *, preserve_priced: bool = False) -> int:
        """Insert/overwrite catalog cards in bulk; returns rows left untouched.

        ``preserve_priced`` is for the BREADTH seed, which carries identity only:
        it refuses to replace a row a depth pass has already filled in
        (``detail="full"``), because a whole-item ``put_item`` does not merge and
        would revert every price it landed on.

        That refusal is a ``ConditionExpression``, not a read-then-decide, and the
        difference is the whole point (Phase 2.0a): the condition is evaluated by
        DynamoDB inside the same operation as the write, so a depth pass landing
        between the caller's decision and its put cannot be clobbered. The
        previous check-then-act shape was safe only while no depth pass existed.
        The cost is one request per card instead of a 25-item batch — the same
        write capacity, more round trips, and it drops the ``batch_get`` the old
        shape needed, so the seed's read cost goes to zero.

        The default (unconditional) path is a whole-item replace and will
        therefore blank a stored ``prices`` map if handed a card that has none —
        a write that carries prices, or carries none *by construction* (the
        BREADTH seed's brief rows), is fine here. **A depth-pass write, whose
        emptiness means "upstream told us nothing today", must go through
        ``upsert_catalog_card_preserving_prices`` instead.** There,
        ``overwrite_by_pkeys`` is load-bearing
        rather than tidiness: boto3 does NOT deduplicate a batch, so two rows
        carrying the same id in one page raise ``ValidationException: Provided
        list of item keys contains duplicates`` and fail the entire 25-item batch
        — killing the run over rows that were merely redundant, not wrong.
        """
        if preserve_priced:
            return self._upsert_catalog_cards_preserving_priced(cards)
        with self._table.batch_writer(  # auto-chunks to 25 + retries unprocessed
            overwrite_by_pkeys=["PK", "SK"]
        ) as batch:
            for card in cards:
                batch.put_item(Item=self._catalog_item(card))
        return 0

    def _upsert_catalog_cards_preserving_priced(self, cards) -> int:
        preserved = 0
        for card in cards:
            item = self._catalog_item(card)
            try:
                self._table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK) OR #d <> :full",
                    ExpressionAttributeNames={"#d": "detail"},
                    ExpressionAttributeValues={":full": "full"},
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
                preserved += 1
                if self._catalog_gen:
                    # Re-stamp the survivor, or "preserve" and "swap" cancel out
                    # into data loss: the row keeps its OLD generation, so the
                    # purge that follows the reseed deletes it and the card ends
                    # up neither replaced nor kept.
                    self._table.update_item(
                        Key={"PK": item["PK"], "SK": item["SK"]},
                        UpdateExpression="SET #c = :gen",
                        ExpressionAttributeNames={"#c": "cat_gen"},
                        ExpressionAttributeValues={":gen": self._catalog_gen},
                    )
        return preserved

    def upsert_catalog_card_preserving_prices(self, card: CatalogCard) -> None:
        """Write ``card``, but NEVER replace a stored price map with an empty one.

        This is the depth pass's write, and it exists because RFC 0003 §7's
        "never deletes, zeroes, or nulls an existing price" has to be a property
        of the write itself. ``to_catalog_card`` returns ``prices={}`` for a
        perfectly good HTTP 200 whose ``pricing`` block is absent or yields no
        band — ``services.tcgdex`` calls that routine, not exceptional — and it
        raises nothing, so a caller has no signal to react to. Through
        ``batch_upsert_catalog_cards`` that ``{}`` is a whole-item ``put_item``
        and yesterday's bands are gone.

        The policy, and it is deliberate:

        * an **empty** incoming ``prices`` is the absence of information, so it
          is omitted from the write and the stored map survives untouched;
        * a **non-empty** one replaces the stored map wholesale rather than
          merging finish by finish. ``_prices_from_pricing`` applies its provider
          preference at CARD level precisely so a card is never described by two
          providers at once; a per-finish merge would reintroduce exactly the
          mixed TCGplayer/Cardmarket bands that rule exists to prevent, and would
          keep a retired finish alive forever;
        * every non-price field is written either way. A priceless response can
          still carry a corrected ``rarity`` or ``name``, and skipping the write
          outright would trade one data-loss problem for a smaller one.

        One ``update_item``, not a read-then-decide. That is the same reasoning
        ``_upsert_catalog_cards_preserving_priced`` already applies one method
        up: reading the prior card in the caller and merging its prices into the
        model before a ``put_item`` is check-then-act, and a concurrent write
        landing in that window is erased anyway. DynamoDB evaluates this inside
        the same operation as the write, so there is no window.

        Side effect of ``update_item``: an attribute absent from the item — a
        ``cat_gen`` this process is not stamping — is LEFT ALONE rather than
        removed. That is the behavior we want and the opposite of ``put_item``'s:
        a depth-pass write must not strip a reseed's generation stamp off a row
        and orphan it into the next purge.
        """
        item = self._catalog_item(card)
        attributes = {k: v for k, v in item.items() if k not in ("PK", "SK")}
        if not card.prices:
            attributes.pop("prices", None)
        # Placeholders for every name: `name` is a DynamoDB reserved word, and
        # so is any field a future model adds.
        names, values, assignments = {}, {}, []
        for index, (attribute, value) in enumerate(attributes.items()):
            names[f"#a{index}"] = attribute
            values[f":v{index}"] = value
            assignments.append(f"#a{index} = :v{index}")
        self._table.update_item(
            Key={"PK": item["PK"], "SK": item["SK"]},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

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
        return {"PK": f"CARD#{p.card_id}", "SK": sk, "entity": "price_point",
                **self._cat_gen(), **body}

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

    # ---- catalog full list (admin market search) ----
    def list_all_catalog_cards(self):
        """Return all catalog cards via filtered scan. Expensive — admin-only."""
        return list(self.iter_catalog_cards())

    # ---- watchlist (admin feature) ----
    def put_watchlist_entry(self, entry: dict):
        """Insert a watchlist entry."""
        entry_id = entry["entry_id"]
        record = {
            "PK": f"WATCHLIST#{entry_id}",
            "SK": "META",
            "entity": "watchlist_entry",
            "GSI1PK": "WATCHLIST#ALL",
            "GSI1SK": entry.get("added_at", ""),
            **_serialize(entry),
        }
        self._table.put_item(Item=record)

    def get_watchlist_entry(self, entry_id: str) -> dict | None:
        """Fetch one watchlist entry by id."""
        item = self._table.get_item(
            Key={"PK": f"WATCHLIST#{entry_id}", "SK": "META"},
        ).get("Item")
        return item if item else None

    def list_watchlist_entries(self) -> list[dict]:
        """List all watchlist entries via the GSI1 WATCHLIST#ALL partition."""
        items = self._query_all(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("WATCHLIST#ALL"),
        )
        return items

    def delete_watchlist_entry(self, entry_id: str):
        """Delete a watchlist entry."""
        self._table.delete_item(
            Key={"PK": f"WATCHLIST#{entry_id}", "SK": "META"},
        )

    # ---- sell sessions (admin feature) ----
    def put_sell_session(self, session: dict):
        """Insert or update a sell session."""
        sell_id = session["sell_id"]
        record = {
            "PK": f"SELL#{sell_id}",
            "SK": "META",
            "entity": "sell_session",
            "GSI1PK": f"SELLS#{session.get('status', 'draft')}",
            "GSI1SK": session.get("created_at", ""),
            **_serialize(session),
        }
        self._table.put_item(Item=record)

    def get_sell_session(self, sell_id: str) -> dict | None:
        """Fetch one sell session by id."""
        item = self._table.get_item(
            Key={"PK": f"SELL#{sell_id}", "SK": "META"},
        ).get("Item")
        return item if item else None

    # ---- buy sessions (admin feature) ----
    def put_buy_session(self, session: dict):
        """Insert or update a buy session."""
        buy_id = session["buy_id"]
        record = {
            "PK": f"BUY#{buy_id}",
            "SK": "META",
            "entity": "buy_session",
            "GSI1PK": f"BUYS#{session.get('status', 'draft')}",
            "GSI1SK": session.get("created_at", ""),
            **_serialize(session),
        }
        self._table.put_item(Item=record)

    def get_buy_session(self, buy_id: str) -> dict | None:
        """Fetch one buy session by id."""
        item = self._table.get_item(
            Key={"PK": f"BUY#{buy_id}", "SK": "META"},
        ).get("Item")
        return item if item else None