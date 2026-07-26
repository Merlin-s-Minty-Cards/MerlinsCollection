"""One-shot importer: spreadsheet CSV exports -> the DynamoDB schema.

Each tab has an ``import_<tab>`` function taking parsed CSV rows plus an
``ImportContext``. The import uses SAFE REPLACE semantics: ``run_import`` refuses
to run unless the export is complete, stamps every write with a generation id,
loads the whole new dataset, and deletes the previous generation only once every
tab commits (rolling this run back otherwise) — so a re-run is idempotent under
any sheet edit (insert/delete/sort rows) and a missing/failed tab can never
silently wipe a live ledger. Row-based records get fresh ULIDs; natural-keyed
entities (shows, consignors) key on their business identity. Ambiguity never
guesses silently: unmappable rows are skipped-and-counted, uncertain mappings set
``needs_review=True``.

Print language is read out of the card-name text (``"Seismitoad (jp)"``) and
stored as a field, because it is part of a card's identity: the catalog is
English-only, so a non-English item is never matched against it and keeps the
sheet's own money figures instead of an English price.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial

from pydantic import ValidationError

from merlins_collection.models.business import (
    BalanceSheetLine,
    BalanceSheetSnapshot,
    BuyingPolicy,
    CashAccount,
    Consignor,
    Debt,
    DebtDirection,
    Expense,
    ExpenseCategory,
    ItemCategory,
    PaymentMethod,
    Payout,
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
    Language,
    RawInventoryItem,
    SealedInventoryItem,
    new_ulid,
)

# Normalization and language detection live in ``card_text`` so the importer, the
# review page and the decision applier all share one implementation.
from merlins_collection.services.card_text import (
    _QUALIFIER_TOKENS,
    CatalogIndex,
    build_catalog_index,
    core_name,
    format_display_name,
    language_from_url,
    normalize_name,
    normalize_number,
    number_keys,
    parse_language,
    set_hint_from_url,
    sets_agree,
)

logger = logging.getLogger(__name__)

# A per-row guard skips only genuine DATA problems (a bad cell). Infrastructure
# errors (a DynamoDB throttle / ClientError) must NOT be swallowed as a "skipped"
# row — they propagate to the per-tab envelope, fail that tab, and trigger the
# import rollback instead of silently dropping a real record.
_DATA_ERRORS = (ValueError, KeyError, TypeError, ArithmeticError,
                InvalidOperation, ValidationError)


class ExistingBusinessDataError(Exception):
    """The target table already holds import-owned business data.

    The spreadsheet was imported ONCE; from then on the DATABASE is the source of
    truth. A second import is not an "update" — it replaces every import-owned
    record with whatever the sheet currently says, discarding anything written or
    corrected since. ``run_import`` therefore refuses outright, before any write,
    unless the operator opts in with ``force_replace=True`` / ``--force-replace``.
    """


def parse_money(text) -> Decimal | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace("$", "").replace(",", "")
    if cleaned in ("", "-"):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    # DynamoDB rejects non-finite (NaN/Infinity), out-of-range magnitudes, and
    # numbers with >38 significant digits (a boto3 decimal.Inexact at write time).
    # Refuse all three at the boundary so one poison cell can't abort a mid-import
    # write into the live table.
    if not value.is_finite():
        return None
    if value != 0 and not (Decimal("1E-130") <= abs(value) <= Decimal("9.9E125")):
        return None
    if len(value.as_tuple().digits) > 38:
        return None
    return value


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


# Only a WHOLE label equal to one of these is a summary row. Matching any name
# that merely *contains* a "total" word would silently drop real records like the
# vendor "Total Wine & More" or event "Total Sports Card Expo" (C2).
_TOTAL_LABELS = frozenset({
    "total", "totals", "subtotal", "subtotals", "grand total", "total cogs",
})


def _is_total_label(text) -> bool:
    """True only when the ENTIRE normalized label is a summary/total label —
    'Total', 'Totals', 'Grand Total', 'Total COGS', 'Subtotal' (punctuation and
    case ignored). A multi-word name that merely starts with 'Total' is NOT a
    total and is kept."""
    norm = " ".join(re.sub(r"[^a-z ]", " ", str(text or "").lower()).split())
    return norm in _TOTAL_LABELS


_FIND_FUZZY_MIN = 6  # shortest alias length allowed to prefix-match (B3)


def _find(row: dict, *names: str):
    """Look up a value tolerating the real workbook's header drift.

    Resolution order: exact header, then whitespace-stripped header, then — only
    as a last resort — a prefix match against the shortest alias. That fuzzy
    branch exists to survive dated-suffix renames (e.g. "Sticker" -> "Sticker
    updated 7/16"), but it is gated to aliases of length >= ``_FIND_FUZZY_MIN``
    so short, ambiguous cores like "Date"/"Name" can never silently bind a
    sibling column ("Date Sold", "Name of Charge"). For a short/ambiguous field
    whose header is verbose, pass the full header as an explicit alias instead of
    relying on the prefix match.
    """
    for name in names:
        if name in row:
            return row[name]
    stripped = {k.strip(): v for k, v in row.items() if isinstance(k, str)}
    for name in names:
        if name in stripped:
            return stripped[name]
    core = min(names, key=len).strip().lower()
    if len(core) >= _FIND_FUZZY_MIN:
        for key, value in row.items():
            if isinstance(key, str) and key.strip().lower().startswith(core):
                return value
    return None


def _text(value) -> str | None:
    """Trim a free-text cell to a value, or ``None`` when it is blank/absent."""
    text = str(value or "").strip()
    return text or None


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


def deterministic_id(tab: str, key) -> str:
    """26-char id from the tab + a stable NATURAL/business key.

    Used only for entities that have a real business identity in the sheet — a
    show (day + name), a consignor (name), a balance-sheet snapshot (label) — so
    a re-import overwrites the same record. Row-based records with no natural key
    (inventory items, transactions, expenses, debts, payouts) instead get a fresh
    ``new_ulid`` on each run; ``run_import``'s load-then-swap generation replace
    makes that a clean replace rather than a duplicate.
    """
    digest = hashlib.sha1(
        (tab + "|" + json.dumps(key, sort_keys=True, default=str)).encode("utf-8")
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
    # The normalized catalog index ``_match_card`` reads, always built through
    # ``build_catalog_index`` (production and tests alike, RFC F.1) so there is one
    # keying path — no un-normalized flat-dict shortcut can re-introduce the outage.
    catalog_index: CatalogIndex = field(default_factory=CatalogIndex)


def _first_hit(table: dict, key_name: str, keys: list[str]) -> list:
    """The first non-empty hit list across the number forms, most literal first."""
    for key in keys:
        hits = table.get((key_name, key))
        if hits:
            return hits
    return []


def _match_card(ctx: ImportContext, name: str, number: str, *,
                language: Language = Language.EN, set_text: str = ""):
    """Conservative catalog match on normalized (name, number); a UNIQUE hit
    returns its card_id, everything ambiguous returns ``None`` for human review.

    The catalog holds ENGLISH cards only, so a non-English item is refused
    outright — before any lookup — no matter how exactly its name and number line
    up with an English entry. A Japanese Seismitoad #38 is not the English
    Seismitoad #38: linking them would hang an English price on a card that
    trades at a different one. ``card_id is None`` is the correct, final answer
    for such an item, not a failed match to retry later. The gate lives here, in
    the single place a catalog lookup can happen, so every caller inherits it.

    Both sides are normalized identically (``build_catalog_index`` on the catalog,
    ``normalize_name``/``number_keys`` on the sheet row) so an Excel float artifact
    ("181.0"), a slash form ("182/167") or name punctuation no longer defeats a
    lookup. Matching is exact-then-narrow: full name+number, then variant-stripped
    name+number, then — only when several sets share that name+number AND set text
    is available — set narrowing. A tie that set text cannot reduce to one card
    stays ``None``; there is deliberately no fuzzy auto-linking here (that, and its
    human confirm, belongs to the review toolchain).
    """
    if language is not Language.EN:
        return None
    index = ctx.catalog_index
    n_full = normalize_name(name)
    if not n_full:  # a fully non-ASCII name is "no evidence", never a match
        return None
    keys = number_keys(normalize_number(number))

    hits = _first_hit(index.by_name_number, n_full, keys)
    core_tier = False
    if not hits:
        hits = _first_hit(index.by_core_number, core_name(name), keys)
        core_tier = True

    if len(hits) == 1:
        card = hits[0]
        # A present Set text that CONTRADICTS the lone hit is not agreement — it is
        # evidence of the WRONG card (a McDonald's Pikachu #58 is not the Base Set
        # Pikachu #58). Route it to review rather than hang the wrong set's price.
        if set_text and not sets_agree(set_text, card.set_name):
            return None
        # A core-tier match reached the catalog only by dropping a variant word. A
        # dropped FINISH word (holo/reverse) costs no confidence, but a dropped
        # QUALIFIER (alt/art/gold/1st…) means a materially different print at a
        # different price — never auto-link that; route it to review.
        if core_tier and _dropped_qualifier(name, card.name):
            return None
        return card.card_id
    if len(hits) > 1 and set_text:
        narrowed = [c for c in hits if sets_agree(set_text, c.set_name)]
        if len(narrowed) == 1:
            card = narrowed[0]
            # Same guard as the single-hit branch: narrowing to one set does not
            # restore a qualifier the core tier dropped, so a variant narrowed to
            # the base card's set is still the wrong print at the wrong price —
            # route it to review rather than link it (Council MUST-FIX B).
            if core_tier and _dropped_qualifier(name, card.name):
                return None
            return card.card_id
    return None


def _dropped_qualifier(sheet_name: str, card_name: str) -> bool:
    """True when the sheet name carries a qualifier token (alt/art/gold/1st…) that
    the matched catalog card's name lacks — mirroring ``build_review``'s "a
    variant-token-dropped match is never HIGH confidence" guard so the importer
    auto-links only what the review page would confirm without a human."""
    sheet_tokens = set(normalize_name(sheet_name).split())
    card_tokens = set(normalize_name(card_name).split())
    return bool((sheet_tokens & _QUALIFIER_TOKENS) - card_tokens)


def _record_sheet_sale(ctx, item, *, sold, date_sold, venmo, venmo_fees, category,
                       consignor_payout=None):
    """Record a sheet sale ATOMICALLY: flip the already-persisted (available) item
    to sold and append its ledger row in one ``record_sale`` transaction, so a
    failed ledger write never leaves a half-sold item with no revenue row. The
    txn gets a fresh ULID; run_import's load-then-swap generation replace makes a
    re-import a clean replace rather than a double-count."""
    txn = Transaction(
        txn_id=new_ulid(),
        type=TransactionType.SALE,
        item_id=item.item_id,
        category=(ItemCategory.CONSIGNMENT if item.consignment else category),
        date=date_sold,
        amount=sold,
        payment_method="venmo" if venmo else "cash",
        fee=venmo_fees or Decimal("0"),
        show_id=nearest_show_id(date_sold, ctx.shows),
        consignor_payout=consignor_payout,
    )
    ctx.repo.record_sale(txn)


def import_singles(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            raw_condition = str(row.get("Condition") or "").strip()
            if raw_condition:
                condition, modifier = parse_condition(raw_condition)
                blank_condition = False
            else:
                # A card with no condition: default NM but flag it rather than drop.
                condition, modifier, blank_condition = Condition.NM, None, True
            loc = map_location(row.get("Location"))
            # Language is read FIRST: it decides whether the English catalog may
            # be consulted at all, and the cleaned name is what gets matched and
            # preserved. Three live rows carry no marker in the name and are
            # identifiable only from their TCGplayer link, so that is consulted
            # as a fallback.
            tcg_url = str(row.get("TCG Link") or "").strip() or None
            language, name = parse_language(row["Name"])
            if language is Language.EN:
                language = language_from_url(tcg_url)
            # The Singles tab has no Set column, so a name+number shared across
            # several sets can't be resolved from the row alone. The TCGplayer
            # link does carry the set in its slug, so derive a set hint from it
            # to narrow those ties (``_match_card`` already narrows a multi-hit by
            # set text; singles simply never had any to pass).
            card_id = _match_card(ctx, name, row.get("Card #", ""), language=language,
                                  set_text=set_hint_from_url(tcg_url))
            needs_review = card_id is None or blank_condition
            notes = " — ".join(x for x in (
                f"{name} #{row.get('Card #', '')}".strip(" #"),
                str(row.get("Notes") or "").strip() or None,
                loc["notes_extra"],
            ) if x)
            # Sanitized customer-facing name from the STRUCTURED identity columns
            # only (never the Notes free-text), materialized once and stored.
            display = format_display_name(name, row.get("Card #", ""))
            item = RawInventoryItem(
                item_id=new_ulid(),
                card_id=card_id,
                display_name=display,
                language=language,
                finish="normal",
                condition=condition,
                condition_modifier=modifier,
                factory_sealed=loc["factory_sealed"],
                status=loc["status"],
                location=loc["location"],
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ purchase")),
                listed_price=parse_money(_find(row, "Sticker")),
                acquired_at=parse_date(row.get("Date")) or date(2026, 1, 1),
                notes=notes or None,
                tcg_url=tcg_url,
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
        except _DATA_ERRORS:
            logger.exception("Singles row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def import_slabs(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            language, name = parse_language(
                _find(row, "Name", "Name (pkm + rarity + language )") or "")
            # A handful of slab rows put the marker in the Set cell instead
            # ("Pikachu" / "jp 151"), so both columns are read before deciding.
            set_language, set_name = parse_language(row.get("Set", ""))
            if language is Language.EN:
                language = set_language
            # A slab has a Set column, so pass it: it narrows a name+number that
            # hits the same card printed in several sets down to the right one.
            card_id = _match_card(ctx, name, row.get("card#", ""),
                                  language=language, set_text=set_name)
            display = format_display_name(name, row.get("card#", ""))
            cert_number = str(row.get("Cert #") or "").strip() or "unknown"
            # A slab needs a human only when we could not identify the card or its
            # cert number is missing. Company defaults to PSA — the sheet has no
            # company column and PSA is the house grader — but that assumption is
            # no longer, by itself, a reason to flag EVERY slab for review.
            needs_review = card_id is None or cert_number == "unknown"
            item = GradedInventoryItem(
                item_id=new_ulid(),
                card_id=card_id,
                display_name=display,
                language=language,
                company="PSA",  # sheet has no company column; PSA is the default grader
                grade=Decimal(str(row["Grade"]).strip()),
                cert_number=cert_number,
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(
                    _find(row, "Market @ purchase", "Market @ time of purchase")),
                listed_price=parse_money(_find(row, "Sticker")),
                acquired_at=parse_date(row.get("Date Recieved")) or date(2026, 1, 1),
                notes=f"{name} — {set_name} #{row.get('card#', '')}",
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
                                   category=ItemCategory.GRADED)
                summary["sales"] += 1
        except _DATA_ERRORS:
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
            language, name = parse_language(row["Name"])
            product_type, needs_review = _guess_product_type(name)
            item = SealedInventoryItem(
                item_id=new_ulid(),
                product_name=name.strip(),
                product_type=product_type,
                language=language,
                status="on_hold" if parse_bool(row.get("Hold")) else "available",
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ time of purchase")),
                listed_price=parse_money(_find(row, "Sticker")),
                acquired_at=parse_date(_find(row, "Date", "Column 1")) or date(2026, 1, 1),
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
        except _DATA_ERRORS:
            logger.exception("Sealed row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def import_bulk(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            language, description = parse_language(row["Name"])
            item = BulkInventoryItem(
                item_id=new_ulid(),
                description=description.strip(),
                language=language,
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
        except _DATA_ERRORS:
            logger.exception("Bulk row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def _parse_percent(text) -> Decimal | None:
    return parse_money(str(text or "").replace("%", ""))


def _parse_fraction(text) -> Decimal | None:
    """A cut expressed as a 0-1 fraction. "5%", "5" and "0.05" all mean 0.05.

    A "%" divides by 100; a bare number > 1 is read as a whole-number percent (so
    "5" -> 0.05, never 500%). Anything still outside [0, 1] is rejected (None)
    rather than poisoning payout math with a negative or over-100% split.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    value = parse_money(raw.replace("%", ""))
    if value is None:
        return None
    if "%" in raw or value > 1:
        value = value / Decimal("100")
    if not (Decimal("0") <= value <= Decimal("1")):
        return None
    return value


def import_shows(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            day = parse_date(row.get("Day"))
            name = str(row.get("Show") or "").strip()
            if day is None or not name:
                summary["skipped"] += 1
                continue
            # Natural key (day + name): editing a show's goal/cash keeps its id.
            show = Show(
                show_id=deterministic_id("Show", {"Day": row.get("Day"), "Show": name}),
                name=name,
                date=day,
                # Populated only when the source carries structured columns; the
                # historical free-text ledger has none, so old shows stay None
                # (no venue/city is ever invented — RFC 0002).
                venue=_text(_find(row, "Venue")),
                city=_text(_find(row, "City", "Location")),
                sales_goal=parse_money(row.get("Goal")),
                cash_at_start=parse_money(_find(
                    row, "Cash at Beginning of Every Show Day", "Cash at Beginning of Show")),
                inventory_value_at_start=parse_money(_find(
                    row, "Inventory Value at Beginning of show",
                    "Inventory Value heading into the show")),
            )
            ctx.repo.put_show(show)
            ctx.shows.append(show)
            summary["imported"] += 1
        except _DATA_ERRORS:
            logger.exception("Vending Net row skipped: %r", row.get("Show"))
            summary["skipped"] += 1
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
                split_percent=_parse_fraction(row.get("Percentage we get")) or Decimal("0"),
                minimum_price=parse_money(row.get("Minimum")),
                paid_out=parse_bool(row.get("Paid Out?")),
            )
            returned = str(row.get("Sold/Returned") or "").strip().lower() == "returned"
            language, card_name = parse_language(row["Card Name"])
            common = dict(
                item_id=new_ulid(),
                status="returned_to_consignor" if returned else "available",
                language=language,
                cost_basis=Decimal("0"),  # not ours; we never paid for it
                market_value_at_purchase=parse_money(row.get("Market")),
                acquired_at=parse_date(row.get("Date recieved")) or date(2026, 1, 1),
                consignment=terms,
                notes=f"{card_name} #{row.get('Card #', '')}".strip(" #"),
                # Structured-identity display name (raw and graded both carry it).
                display_name=format_display_name(card_name, row.get("Card #", "")),
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
            date_sold = parse_date(_find(row, "Date Sold", "Date Sold or Returned"))
            if sold is not None and date_sold is not None and not returned:
                payout = parse_money(row.get("To payout"))
                if payout is None:
                    payout = sold - (sold * terms.split_percent)
                _record_sheet_sale(
                    ctx, item, sold=sold, date_sold=date_sold,
                    venmo=parse_bool(row.get("Venmo?")),
                    venmo_fees=parse_money(row.get("Venmo Fees")),
                    category=ItemCategory.CONSIGNMENT, consignor_payout=payout,
                )
                summary["sales"] += 1
        except _DATA_ERRORS:
            logger.exception("Consignments row skipped: %r", row.get("Card Name"))
            summary["skipped"] += 1
    return summary


def import_cash(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            account = str(row.get("Type") or "").strip().lower()
            amount = parse_money(row.get("Amount"))
            if not account or _is_total_label(account) or amount is None:
                summary["skipped"] += 1
                continue
            ctx.repo.put_cash_account(CashAccount(account=account, balance=amount))
            summary["imported"] += 1
        except _DATA_ERRORS:
            logger.exception("Cash row skipped: %r", row.get("Type"))
            summary["skipped"] += 1
    return summary


def import_buying_guidelines(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            product_type = str(_find(row, "Product Type") or "").strip().lower()
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
        except _DATA_ERRORS:
            logger.exception("Buying Guidelines row skipped: %r", row.get("Product Type"))
            summary["skipped"] += 1
    return summary


def import_expenses(rows: list[dict], ctx: ImportContext, category: ExpenseCategory,
                    *, link_show: bool = False) -> dict:
    """Flat expense tabs (Show Fees / Other COGS / Marketing / Supplies).

    Amount keeps its sign (negative = money came in). A ``Total(s)`` summary row
    and rows lacking a name+amount are skipped. ``link_show`` ties show-day costs
    to the nearest show; general overhead (marketing/supplies) stays unlinked.
    """
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            name = str(_find(row, "Name") or "").strip()
            amount = parse_money(_find(row, "Amount",
                                       "Amount (neg numbers is money coming in)"))
            if not name or _is_total_label(name) or amount is None:
                summary["skipped"] += 1
                continue
            day = parse_date(_find(row, "Date of Transaction", "Date")) or date(2026, 1, 1)
            platform = str(_find(row, "Platform") or "").strip().lower() or "cash"
            reason = str(
                _find(row, "Reason", "Why is this COGS?", "Notes") or "").strip() or None
            ctx.repo.put_expense(Expense(
                expense_id=new_ulid(),
                category=category, date=day, amount=amount,
                payment_method=platform, description=name, reason=reason,
                show_id=nearest_show_id(day, ctx.shows) if link_show else None,
            ))
            summary["imported"] += 1
        except _DATA_ERRORS:
            logger.exception("%s row skipped: %r", category.value, row.get("Name"))
            summary["skipped"] += 1
    return summary


_WAGE_PERSON_COLS = ("Person 1 Amt", "Person 2 Amt", "Person 3 Amt")


def import_employee_wages(rows: list[dict], ctx: ImportContext) -> dict:
    """Per-show wages: one expense per person with a non-zero amount."""
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            day = parse_date(_find(row, "Date")) or date(2026, 1, 1)
            show_id = nearest_show_id(day, ctx.shows)
            paid = parse_bool(row.get("Paid?"))
            wrote = False
            for person_col in _WAGE_PERSON_COLS:
                amount = parse_money(row.get(person_col))
                if amount is None or amount == 0:
                    continue
                ctx.repo.put_expense(Expense(
                    expense_id=new_ulid(),
                    category=ExpenseCategory.EMPLOYEE_WAGE, date=day, amount=amount,
                    payment_method="cash", person=person_col.replace(" Amt", ""),
                    description=str(row.get("Show") or "").strip() or None,
                    show_id=show_id, paid=paid,
                    notes=str(row.get("Notes") or "").strip() or None,
                ))
                summary["imported"] += 1
                wrote = True
            if not wrote:
                summary["skipped"] += 1
        except _DATA_ERRORS:
            logger.exception("Wages row skipped: %r", row.get("Show"))
            summary["skipped"] += 1
    return summary


def import_employee_expenses(rows: list[dict], ctx: ImportContext) -> dict:
    """Employee reimbursements (food/travel at an event)."""
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            name = str(_find(row, "Name of Charge") or "").strip()
            amount = parse_money(_find(row, "Amount"))
            if not name or _is_total_label(name) or amount is None:
                summary["skipped"] += 1
                continue
            day = parse_date(_find(row, "Event Date", "Date")) or date(2026, 1, 1)
            ctx.repo.put_expense(Expense(
                expense_id=new_ulid(),
                category=ExpenseCategory.EMPLOYEE_EXPENSE, date=day, amount=amount,
                payment_method="cash", description=name,
                reason=str(_find(row, "Reason") or "").strip() or None,
                show_id=nearest_show_id(day, ctx.shows),
                paid=parse_bool(row.get("Paid?")),
                notes=str(row.get("Event name") or "").strip() or None,
            ))
            summary["imported"] += 1
        except _DATA_ERRORS:
            logger.exception("Employee Expenses row skipped: %r", row.get("Name of Charge"))
            summary["skipped"] += 1
    return summary


_DEBT_SIDES = (
    # direction, amount-column aliases, and the (deduped) date/who/reason/cleared
    # columns. Amounts go through ``_find`` like every other importer so a
    # reworded/dated header ("Amount Owed to Company (as of 7/16)") still binds
    # instead of silently skipping the whole side.
    (DebtDirection.OWED_TO_US,
     ("Amount Owed to Company", "Amount Owed to Us", "Amount Owed"),
     "Date", "Who", "Reason", "Cleared"),
    (DebtDirection.WE_OWE,
     ("Amount in Debt to Others", "Amount We Owe", "Amount in Debt"),
     "Date_2", "Who_2", "Reason_2", "Cleared_2"),
)


def import_debts(rows: list[dict], ctx: ImportContext) -> dict:
    """The Debts tab is two ledgers side by side (owed-to-us | we-owe) that reuse
    the same header names; ``run_import`` de-dupes repeats to ``_2`` so both are
    reachable. A row can contribute a debt on either or both sides."""
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            wrote = False
            for direction, amount_cols, date_col, who_col, reason_col, cleared_col in _DEBT_SIDES:
                amount = parse_money(_find(row, *amount_cols))
                who = str(row.get(who_col) or "").strip()
                if amount is None or not who:
                    continue
                ctx.repo.put_debt(Debt(
                    debt_id=new_ulid(),
                    direction=direction,
                    date=parse_date(row.get(date_col)) or date(2026, 1, 1),
                    amount=amount,
                    counterparty=who,
                    reason=str(row.get(reason_col) or "").strip() or None,
                    cleared=parse_bool(row.get(cleared_col)),
                ))
                summary["imported"] += 1
                wrote = True
            if not wrote:
                summary["skipped"] += 1
        except _DATA_ERRORS:
            # Log only the counterparty name, never the whole row — the amount
            # columns are the owner's financial data and must not reach logs.
            logger.exception("Debts row skipped: %r", row.get("Who"))
            summary["skipped"] += 1
    return summary


# Columns on the Payouts tab that are NOT partners. A partner is any *other*
# column; we deny-list the known meta/derived/total columns (and de-duped blank
# spacers like "_2") so a per-row Total/Revenue column can't become a phantom
# partner with the summed amount.
_PAYOUT_NON_PARTNER_COLS = {
    "event", "note", "notes", "percentage", "total", "totals", "subtotal",
    "revenue", "gross", "day", "date", "",
}


def import_payouts(rows: list[dict], ctx: ImportContext) -> dict:
    """Payouts tab: each row is one event; every column that is NOT a known
    meta/total column is a partner, and a non-zero cell is that partner's cut. A
    totals row (no event, or an event labelled 'Total') is skipped."""
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        try:
            event = str(_find(row, "Event") or "").strip()
            if not event or _is_total_label(event):
                summary["skipped"] += 1
                continue
            percent = _parse_fraction(_find(row, "Percentage"))
            note = str(_find(row, "Note", "Notes") or "").strip() or None
            wrote = False
            for col, value in row.items():
                if not isinstance(col, str):
                    continue
                key = col.strip().lower()
                # Not a partner: known meta columns, de-duped blank spacers ("_2"),
                # or any header carrying a "total"/"subtotal" word (Total Cut,
                # Running Total, Net Total) — partners are people's names, never
                # these. (F3: fail closed on derived-total columns.)
                if (key in _PAYOUT_NON_PARTNER_COLS or re.fullmatch(r"_\d+", key)
                        or any(w.startswith(("total", "subtotal")) for w in key.split())):
                    continue
                amount = parse_money(value)
                if amount is None or amount == 0:
                    continue
                ctx.repo.put_payout(Payout(
                    payout_id=new_ulid(),
                    event=event, partner=col.strip(), amount=amount,
                    percent=percent, notes=note,
                ))
                summary["imported"] += 1
                wrote = True
            if not wrote:
                summary["skipped"] += 1
        except _DATA_ERRORS:
            logger.exception("Payouts row skipped: %r", row.get("Event"))
            summary["skipped"] += 1
    return summary


_BS_SECTIONS = {"assets": "asset", "liabilities": "liability", "equity": "equity"}


def import_balance_sheet(rows: list[dict], ctx: ImportContext, *,
                         label: str, frozen: bool) -> dict:
    """A balance-sheet tab (col 1 = line label, col 2 = amount, col 3 = note).

    Tracks the current top-level section from ``Assets``/``Liabilities``/``Equity``
    header rows and stores only leaf lines — section headers and ``Total ...``
    subtotals are computed, so they are skipped.

    The FROZEN baseline is WRITE-ONCE: once captured it is an immutable,
    non-re-derivable point-in-time record, so a later import never re-writes it.
    That is what makes a *partially* truncated Beginning tab harmless — it can no
    longer overwrite the complete baseline in place with a subset (BLOCKING-1a).
    """
    if frozen:
        existing = ctx.repo.get_frozen_balance_sheet(label)
        if existing is not None:
            logger.info(
                "Frozen balance sheet %r already captured — immutable baseline, "
                "leaving it untouched (%d lines).", label, len(existing.lines))
            return {"imported": 0, "skipped": len(rows), "preserved": True}
    section = None
    lines = []
    for row in rows:
        try:
            label_cell = str(row.get("Column 1") or "").strip()
            low = label_cell.lower()
            if low in _BS_SECTIONS:
                section = _BS_SECTIONS[low]
                continue
            amount = parse_money(row.get("Column 2"))
            # Balance-sheet Column-1 labels are structured accounting terms (no
            # free-text vendor names), so a plain startswith is safe here and
            # correctly drops subtotals like "Total Current Assets".
            if (not label_cell or amount is None or low.startswith("total")
                    or section is None):
                continue
            lines.append(BalanceSheetLine(
                section=section, label=label_cell, amount=amount,
                note=str(row.get("Column 3") or "").strip() or None))
        except _DATA_ERRORS:
            # Log only the non-financial line label — never the whole row, which
            # carries the amount (Column 2).
            logger.exception("Balance sheet %r line skipped: %r",
                             label, row.get("Column 1"))
    # A present balance-sheet tab always has content, so ZERO leaf lines means the
    # export is broken: a renamed label column / reworded section header (drift),
    # or a truncated/empty download. Persisting a valid-looking empty snapshot
    # would let the commit delete the prior — non-re-derivable — frozen baseline.
    # FAIL the tab instead so the run rolls back and the prior snapshot survives;
    # never return a success dict that authorizes the destructive swap.
    if not lines:
        raise ValueError(
            f"Balance sheet {label!r}: tab produced zero leaf lines (layout drift "
            "or truncated/empty export?) — refusing to store an empty snapshot")
    ctx.repo.put_balance_sheet(BalanceSheetSnapshot(
        snapshot_id=deterministic_id("BalanceSheet", label),
        label=label, frozen=frozen, lines=lines))
    return {"imported": len(lines), "skipped": 0}


def seed_payment_methods(repo) -> None:
    """Seed the payment methods the sheet actually uses. Only Venmo charges a
    fee today; the rest (cash, card, bank, trade, cashapp, zelle, reimbursed)
    are fee-free but recorded so a transaction's method always resolves."""
    repo.put_payment_method(PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                                          fee_fixed=Decimal("0.10")))
    for method in ("cash", "card", "bank", "trade", "cashapp", "zelle", "reimbursed"):
        repo.put_payment_method(PaymentMethod(method=method))


# Every tab listed here is covered automatically by the per-tab truncation guard
# (`_empty_tabs`): if it is present but imports zero records the run fails closed.
# Adding a tab needs no second registry to stay in sync — the guard derives from
# this table, so a new ledger cannot silently default to unguarded. An importer
# added here MUST return a summary carrying an ``imported`` count for that to work.
_TAB_IMPORTERS = [  # shows first: everything else matches sales/costs to them
    ("Vending Net", import_shows),
    ("Cash", import_cash),
    ("Buying Guidelines", import_buying_guidelines),
    ("Singles", import_singles),
    ("Slabs", import_slabs),
    ("Sealed", import_sealed),
    ("Bulk", import_bulk),
    ("Consignments", import_consignments),
    ("Show Fees", partial(import_expenses, category=ExpenseCategory.SHOW_FEE,
                          link_show=True)),
    ("Other COGS", partial(import_expenses, category=ExpenseCategory.OTHER_COGS)),
    ("Marketing", partial(import_expenses, category=ExpenseCategory.MARKETING)),
    ("Supplies", partial(import_expenses, category=ExpenseCategory.SUPPLIES)),
    ("Employee Wages", import_employee_wages),
    ("Employee Expenses", import_employee_expenses),
    ("Debts", import_debts),
    ("Payouts", import_payouts),
    ("Balance Sheet Beginning",
     partial(import_balance_sheet, label="beginning", frozen=True)),
    ("Copy of Balance Sheet Beginning",
     partial(import_balance_sheet, label="current", frozen=False)),
]


def _dedupe_headers(header: list[str]) -> list[str]:
    """Make a header row unique by suffixing repeats (``Date`` -> ``Date_2``).

    ``csv.DictReader`` silently drops all but the last cell of a duplicated
    header; some tabs (Debts) reuse names across two side-by-side ledgers, so we
    build the dict ourselves from a de-duplicated header instead.
    """
    seen: dict[str, int] = {}
    out = []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        out.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    return out


def _read_tab_rows(path, csv_module) -> list[dict]:
    """Read one tab CSV into de-duped-header row dicts. May raise (e.g. a cell
    over the csv field-size limit) — the caller isolates that per tab."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv_module.reader(f)
        try:
            fieldnames = _dedupe_headers(next(reader))
        except StopIteration:
            return []
        return [dict(zip(fieldnames, r)) for r in reader]


def _empty_tabs(summaries: dict, allow_empty) -> list[str]:
    """Present tabs that imported ZERO records and were not declared empty.

    A tab whose CSV is present but which yields no records is either a TRUNCATED
    export (the silent-loss case: committing would delete the prior rows it failed
    to re-create) or a legitimately empty ledger. The two are indistinguishable
    from the bytes, so the run fails closed and the operator opts in per tab via
    ``allow_empty``. Checking per TAB — not per entity — is what catches a single
    truncated tab of a MULTI-tab entity (one of the six expense tabs, one of the
    four inventory tabs), where the entity total stays non-zero because the
    sibling tabs imported fine (BLOCKING-2).
    """
    return sorted(
        tab for tab, s in summaries.items()
        if isinstance(s, dict) and not tab.startswith("_")
        and "failed" not in s and not s.get("preserved")
        and s.get("imported") == 0 and tab not in allow_empty
    )


def run_import(csv_dir, repo, *, require_complete: bool = True,
               allow_empty=frozenset(), force_replace: bool = False) -> dict:
    """Import the workbook's tab CSVs from ``csv_dir`` with SAFE REPLACE semantics.

    Five guarantees protect the live money table:

    * **Re-import guard** (``force_replace``): the outermost layer. If the table
      already holds ANY import-owned business data, the run raises
      ``ExistingBusinessDataError`` before a single write — the first import made
      the DB the source of truth, and a second one would replace it wholesale.
      ``force_replace=True`` is the operator's deliberate "yes, replace it".
    * **Single-flight lock**: the run takes a conditional-write import lock and
      refuses to start (``ImportInProgressError``) while another import is in
      flight, so two overlapping runs can never race the destructive swap.
    * **Completeness precondition** (``require_complete``): the run refuses to touch
      the DB unless ``csv_dir`` exists and every expected tab CSV is present. A
      wrong directory, a dropped/renamed tab, or an intentional subset export
      raises *before* any write — it can never silently wipe a ledger and reload
      nothing. (Tests scope to a subset with ``require_complete=False``.)
    * **Load-then-swap** (generations): every write is stamped with a fresh
      generation id — including the natural-key entities, whose sort keys are
      generation-scoped so they no longer overwrite in place — the whole new
      dataset is loaded first, and the *previous* generation is deleted only if
      EVERY tab committed. If any tab fails, this run's generation is rolled back
      instead and the prior data (including every stable-key row) survives intact.
    * **Per-tab truncation guard**: a present tab that imports zero records fails
      the run unless its name is listed in ``allow_empty`` (the operator's explicit
      "this ledger is genuinely empty" acknowledgement).

    Returns per-tab summaries plus ``_committed`` (bool), ``_removed`` (count) and,
    when the truncation guard fires, ``_empty_tabs``.
    """
    import csv
    from pathlib import Path

    csv_dir = Path(csv_dir)
    if require_complete:
        if not csv_dir.is_dir():
            raise ImportError(f"csv_dir is not a directory: {csv_dir}")
        missing = [tab for tab, _ in _TAB_IMPORTERS
                   if not (csv_dir / f"{tab}.csv").exists()]
        if missing:
            raise ImportError(
                f"incomplete export — refusing to import; missing tab CSVs: {missing}")

    # Outermost guard, evaluated before the lock and before any generation is
    # stamped, so a refused run leaves the table byte-for-byte untouched.
    if not force_replace:
        existing = repo.find_import_owned_entity()
        if existing is not None:
            raise ExistingBusinessDataError(
                f"refusing to import: this table already contains business data "
                f"(found an existing {existing!r} record). The DATABASE, not the "
                f"spreadsheet, is the source of truth now, and a re-import "
                f"REPLACES every import-owned record (inventory, transactions, "
                f"expenses, debts, payouts, shows, consignors, cash accounts, "
                f"buying policies, payment methods, balance-sheet snapshots) with "
                f"the sheet's current contents, discarding anything written or "
                f"corrected since the last import. If that is genuinely what you "
                f"want, re-run deliberately with --force-replace "
                f"(run_import(..., force_replace=True))."
            )

    gen = new_ulid()
    repo.acquire_import_lock(gen)  # raises ImportInProgressError if one is running
    summaries: dict = {}
    try:
        repo.set_import_generation(gen)
        seed_payment_methods(repo)
        ctx = ImportContext(
            repo=repo,
            catalog_index=build_catalog_index(repo.iter_catalog_cards()),
        )
        for tab, importer in _TAB_IMPORTERS:
            path = csv_dir / f"{tab}.csv"
            if not path.exists():
                continue
            try:
                rows = _read_tab_rows(path, csv)
                summaries[tab] = importer(rows, ctx)
            except Exception as exc:  # isolate a whole-tab failure (incl. infra)
                logger.exception("Tab %r failed", tab)
                summaries[tab] = {"failed": repr(exc)}
        committed = not any(
            isinstance(s, dict) and "failed" in s for s in summaries.values())
        if committed:
            empty = _empty_tabs(summaries, allow_empty)
            if empty:
                logger.error(
                    "refusing to commit: present tab(s) imported zero records "
                    "(truncated export?): %s — re-run with allow_empty={...} if "
                    "these ledgers are genuinely empty.", empty)
                summaries["_empty_tabs"] = empty
                committed = False
        summaries["_removed"] = repo.finalize_import(gen, committed=committed)
        summaries["_committed"] = committed
    finally:
        repo.set_import_generation(None)
        repo.release_import_lock(gen)
    return summaries
