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
    BuyingPolicy,
    CashAccount,
    Consignor,
    ItemCategory,
    PaymentMethod,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConditionModifier,
    ConsignmentTerms,
    GradedInventoryItem,
    ItemStatus,
    RawInventoryItem,
    SealedInventoryItem,
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


def import_slabs(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            card_id = _match_card(ctx, row["Name"], row.get("card#", ""))
            item = GradedInventoryItem(
                item_id=deterministic_id("Slabs", row),
                card_id=card_id,
                company="PSA",  # sheet has no company column; flagged for review
                grade=Decimal(str(row["Grade"]).strip()),
                cert_number=str(row.get("Cert #") or "").strip() or "unknown",
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date Recieved")) or date(2026, 1, 1),
                notes=f"{row['Name']} — {row.get('Set', '')} #{row.get('card#', '')}",
                needs_review=True,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.GRADED)
                summary["sales"] += 1
        except Exception:
            logger.exception("Slabs row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


_PRODUCT_KEYWORDS = [("booster box", "booster_box"), ("elite trainer", "etb"),
                     ("etb", "etb"), ("bundle", "bundle"),
                     ("booster pack", "booster_pack"), ("collection", "collection_box")]


def _guess_product_type(name: str) -> tuple[str, bool]:
    lowered = name.lower()
    for keyword, ptype in _PRODUCT_KEYWORDS:
        if keyword in lowered:
            return ptype, False
    return "other", True  # unrecognized -> needs review


def import_sealed(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            product_type, needs_review = _guess_product_type(row["Name"])
            item = SealedInventoryItem(
                item_id=deterministic_id("Sealed", row),
                product_name=str(row["Name"]).strip(),
                product_type=product_type,
                status="on_hold" if parse_bool(row.get("Hold")) else "available",
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ time of purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date")) or date(2026, 1, 1),
                tcg_url=str(row.get("TCG Link") or "").strip() or None,
                needs_review=needs_review,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += int(needs_review)
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.SEALED)
                summary["sales"] += 1
        except Exception:
            logger.exception("Sealed row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def import_bulk(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            item = BulkInventoryItem(
                item_id=deterministic_id("Bulk", row),
                description=str(row["Name"]).strip(),
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                acquired_at=date(2026, 1, 1),  # tab has no acquisition date
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.BULK)
                summary["sales"] += 1
        except Exception:
            logger.exception("Bulk row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def _parse_percent(text) -> Decimal | None:
    return parse_money(str(text or "").replace("%", ""))


def import_shows(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        day = parse_date(row.get("Day"))
        name = str(row.get("Show") or "").strip()
        if day is None or not name:
            summary["skipped"] += 1
            continue
        show = Show(
            show_id=deterministic_id("Show", {"Day": row.get("Day"), "Show": name}),
            name=name,
            date=day,
            sales_goal=parse_money(row.get("Goal")),
            cash_at_start=parse_money(row.get("Cash at Beginning of Every Show Day")),
            inventory_value_at_start=parse_money(
                row.get("Inventory Value at Beginning of show")),
        )
        ctx.repo.put_show(show)
        ctx.shows.append(show)
        summary["imported"] += 1
    return summary


def import_consignments(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    consignors: dict[str, Consignor] = {}
    for row in rows:
        try:
            person = str(row["Persons Name"]).strip()
            if person not in consignors:
                consignor = Consignor(
                    consignor_id=deterministic_id("Consignor", {"name": person}),
                    name=person,
                )
                ctx.repo.put_consignor(consignor)
                consignors[person] = consignor
            terms = ConsignmentTerms(
                consignor_id=consignors[person].consignor_id,
                split_percent=_parse_percent(row.get("Percentage we get")) or Decimal("0"),
                minimum_price=parse_money(row.get("Minimum")),
                paid_out=parse_bool(row.get("Paid Out?")),
            )
            returned = str(row.get("Sold/Returned") or "").strip().lower() == "returned"
            common = dict(
                item_id=deterministic_id("Consignments", row),
                status="returned_to_consignor" if returned else "available",
                cost_basis=Decimal("0"),  # not ours; we never paid for it
                market_value_at_purchase=parse_money(row.get("Market")),
                acquired_at=parse_date(row.get("Date recieved")) or date(2026, 1, 1),
                consignment=terms,
                notes=f"{row['Card Name']} #{row.get('Card #', '')}".strip(" #"),
            )
            if parse_bool(row.get("Slab")):
                grade_text = str(row.get("Condition") or "").strip()
                grade = (Decimal(grade_text)
                         if grade_text.replace(".", "", 1).isdigit() else Decimal("10"))
                item = GradedInventoryItem(company="PSA", grade=grade,
                                           cert_number="unknown", needs_review=True,
                                           **common)
                summary["needs_review"] += 1
            else:
                condition, modifier = parse_condition(row.get("Condition") or "NM")
                item = RawInventoryItem(finish="normal", condition=condition,
                                        condition_modifier=modifier, **common)
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None and not returned:
                payout = parse_money(row.get("To payout"))
                if payout is None:
                    payout = sold - (sold * terms.split_percent / Decimal("100"))
                ctx.repo.put_inventory_item(
                    item.model_copy(update={"status": ItemStatus.SOLD}))
                ctx.repo.put_transaction(Transaction(
                    txn_id=deterministic_id("txn", {"item": item.item_id}),
                    type=TransactionType.SALE,
                    item_id=item.item_id,
                    category=ItemCategory.CONSIGNMENT,
                    date=date_sold,
                    amount=sold,
                    payment_method="venmo" if parse_bool(row.get("Venmo?")) else "cash",
                    fee=parse_money(row.get("Venmo Fees")) or Decimal("0"),
                    show_id=nearest_show_id(date_sold, ctx.shows),
                    consignor_payout=payout,
                ))
                summary["sales"] += 1
        except Exception:
            logger.exception("Consignments row skipped: %r", row.get("Card Name"))
            summary["skipped"] += 1
    return summary


def import_cash(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        account = str(row.get("Type") or "").strip().lower()
        amount = parse_money(row.get("Amount"))
        if not account or account == "total" or amount is None:
            summary["skipped"] += 1
            continue
        ctx.repo.put_cash_account(CashAccount(account=account, balance=amount))
        summary["imported"] += 1
    return summary


def import_buying_guidelines(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        product_type = str(row.get("Product Type") or "").strip().lower()
        if not product_type:
            summary["skipped"] += 1
            continue
        ctx.repo.put_buying_policy(BuyingPolicy(
            product_type=product_type,
            cash_pct_min=_parse_percent(row.get("Cash % Min")),
            cash_pct_max=_parse_percent(row.get("Cash % Max")),
            trade_pct_min=_parse_percent(row.get("Trade % Min")),
            trade_pct_max=_parse_percent(row.get("Trade % Max")),
        ))
        summary["imported"] += 1
    return summary


def seed_payment_methods(repo) -> None:
    repo.put_payment_method(PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                                          fee_fixed=Decimal("0.10")))
    repo.put_payment_method(PaymentMethod(method="cash"))


_TAB_IMPORTERS = [  # shows first: everything else matches sales to them
    ("Vending Net", import_shows),
    ("Cash", import_cash),
    ("Buying Guidelines", import_buying_guidelines),
    ("Singles", import_singles),
    ("Slabs", import_slabs),
    ("Sealed", import_sealed),
    ("Bulk", import_bulk),
    ("Consignments", import_consignments),
]


def run_import(csv_dir, repo) -> dict:
    """Import every recognized ``<Tab>.csv`` in ``csv_dir``; returns per-tab summaries."""
    import csv
    from pathlib import Path

    csv_dir = Path(csv_dir)
    seed_payment_methods(repo)
    catalog_index: dict = {}
    for card in repo.iter_catalog_cards():
        catalog_index.setdefault((card.name.lower(), card.number), []).append(card)
    ctx = ImportContext(repo=repo, catalog_index=catalog_index)
    summaries = {}
    for tab, importer in _TAB_IMPORTERS:
        path = csv_dir / f"{tab}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        summaries[tab] = importer(rows, ctx)
    return summaries
