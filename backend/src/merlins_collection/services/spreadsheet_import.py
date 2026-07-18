"""One-shot importer: spreadsheet CSV exports -> the DynamoDB schema.

Each tab has an ``import_<tab>`` function taking parsed CSV rows plus an
``ImportContext``. Ids are deterministic (tab + row content hash) so re-running
the import overwrites instead of duplicating. Ambiguity never guesses silently:
unmappable rows are skipped-and-counted, uncertain mappings set
``needs_review=True``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    ItemStatus,
    RawInventoryItem,
)

logger = logging.getLogger(__name__)


def parse_money(text) -> Decimal | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace("$", "").replace(",", "")
    if cleaned in ("", "-"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(text) -> date | None:
    if not text or not str(text).strip():
        return None
    cleaned = str(text).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_bool(text) -> bool:
    return str(text or "").strip().lower() in ("yes", "y", "true", "x", "1")


def parse_condition(text: str) -> tuple[Condition, ConditionModifier | None]:
    cleaned = str(text).strip().upper().replace(" ", "")
    modifier = None
    if cleaned.endswith("+"):
        modifier, cleaned = ConditionModifier.PLUS, cleaned[:-1]
    elif cleaned.endswith("-"):
        modifier, cleaned = ConditionModifier.MINUS, cleaned[:-1]
    if cleaned == "D":
        cleaned = "DMG"
    if cleaned not in Condition.__members__:
        raise ValueError(f"unknown condition: {text!r}")
    return Condition[cleaned], modifier


def map_location(text) -> dict:
    """Split the sheet's Location column into location/status/factory_sealed.

    "Sealed" on a *single* means factory-wrapped (a condition premium), not a
    sealed product; "Hold"/"Lost"/"Grading"/"For David" are statuses, not places.
    """
    out = {"location": None, "status": "available", "factory_sealed": False,
           "notes_extra": None}
    cleaned = str(text or "").strip()
    if not cleaned:
        return out
    lowered = cleaned.lower()
    if lowered == "sealed":
        out["factory_sealed"] = True
    elif lowered == "hold":
        out["status"] = "on_hold"
    elif lowered == "lost":
        out["status"] = "lost"
    elif lowered == "grading":
        out["status"] = "out_for_grading"
    elif lowered == "for david":
        out["status"] = "on_hold"
        out["notes_extra"] = cleaned
    else:
        out["location"] = lowered
    return out


def deterministic_id(tab: str, row: dict) -> str:
    """26-char id from the tab + row content, so re-imports overwrite in place."""
    digest = hashlib.sha1(
        (tab + "|" + json.dumps(row, sort_keys=True, default=str)).encode("utf-8")
    ).hexdigest()
    return digest[:26]


def nearest_show_id(day: date, shows: list[Show]) -> str | None:
    """The show closest in time to ``day`` (the business dates off-show deals
    to the nearest show anyway), or ``None`` when no shows are known."""
    if not shows:
        return None
    return min(shows, key=lambda s: abs((s.date - day).days)).show_id


@dataclass
class ImportContext:
    repo: object
    shows: list[Show] = field(default_factory=list)
    catalog_index: dict = field(default_factory=dict)  # (name_lower, number) -> [CatalogCard]


def _match_card(ctx: ImportContext, name: str, number: str):
    """Exact match on (name, number); a unique hit returns its card_id."""
    hits = ctx.catalog_index.get((name.strip().lower(), str(number).strip()), [])
    return hits[0].card_id if len(hits) == 1 else None


def _record_sheet_sale(ctx, item, *, sold, date_sold, venmo, venmo_fees, category):
    """Persist the item as sold + its ledger record (import path)."""
    ctx.repo.put_inventory_item(item.model_copy(update={"status": ItemStatus.SOLD}))
    txn = Transaction(
        txn_id=deterministic_id("txn", {"item": item.item_id}),
        type=TransactionType.SALE,
        item_id=item.item_id,
        category=(ItemCategory.CONSIGNMENT if item.consignment else category),
        date=date_sold,
        amount=sold,
        payment_method="venmo" if venmo else "cash",
        fee=venmo_fees or Decimal("0"),
        show_id=nearest_show_id(date_sold, ctx.shows),
    )
    ctx.repo.put_transaction(txn)


def import_singles(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            condition, modifier = parse_condition(row["Condition"])
            loc = map_location(row.get("Location"))
            card_id = _match_card(ctx, row["Name"], row.get("Card #", ""))
            needs_review = card_id is None
            notes = " — ".join(x for x in (
                f"{row['Name']} #{row.get('Card #', '')}".strip(" #"),
                str(row.get("Notes") or "").strip() or None,
                loc["notes_extra"],
            ) if x)
            item = RawInventoryItem(
                item_id=deterministic_id("Singles", row),
                card_id=card_id,
                finish="normal",
                condition=condition,
                condition_modifier=modifier,
                factory_sealed=loc["factory_sealed"],
                status=loc["status"],
                location=loc["location"],
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date")) or date(2026, 1, 1),
                notes=notes or None,
                tcg_url=str(row.get("TCG Link") or "").strip() or None,
                needs_review=needs_review,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += int(needs_review)
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(
                    ctx, item, sold=sold, date_sold=date_sold,
                    venmo=parse_bool(row.get("Venmo?")),
                    venmo_fees=parse_money(row.get("Venmo Fees")),
                    category=ItemCategory.RAW,
                )
                summary["sales"] += 1
        except Exception:
            logger.exception("Singles row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary
