"""Read-only analytics for the admin analyst chat (RFC 0018).

**This module exists so the admin MCP server can be a PYTHON process** (roadmap
item 4). Every money figure here is computed by importing the helpers the admin
pages already use — ``services.ledger.countable`` and
``routers.admin.analytics.summarize_transactions`` — rather than by
re-implementing the arithmetic in a second language. A TypeScript mirror could
have pinned a *value* with a parity test; it could not have pinned a *call
graph*, and ``services/ledger.py``'s docstring enumerates its readers precisely
because the failure mode is a reader that forgets to call it.

Nothing here writes. Nothing here is denormalised or cached: a second stored
copy of a money figure is how two sets of books start disagreeing, which is the
concern CLAUDE.md already records for ``ledger.is_countable``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from merlins_collection.services.dynamodb import InventoryRepository

#: "All time" is bounded, deliberately — never an unbounded table walk.
#: `InventoryRepository.list_transactions` queries one DynamoDB partition PER
#: MONTH in the requested range, so a caller free to pick "the start of the
#: universe" as a default would turn one chat message into hundreds of
#: sequential Queries against a 30s Lambda budget (CLAUDE.md: "ONE chat
#: request is bounded by three things"). Measured against the live table
#: 2026-08-28: the earliest real transaction is 2026-01-01 (188 rows total),
#: so 3 years is a wide safety margin today — 36 month-partition queries,
#: comfortably inside the 10s per-tool-call timeout even at high per-query
#: latency — while staying cheap. Revisit this once the ledger is actually
#: older than that.
_ALL_TIME_LOOKBACK_YEARS = 3


def _default_all_time_window(
    start: date | None, end: date | None, as_of: date | None
) -> tuple[date, date]:
    """The one place "all time" gets computed — every tool on this surface
    that accepts optional bounds calls this, so "all time" cannot mean a
    different window depending on which tool answered (RFC 0020: refactored
    out of `profit_summary`/`raw_transactions` during adversarial review,
    which flagged the original two-copy duplication as a drift risk — a
    future change to one call site's window logic with no reason to touch the
    other would silently make "all time" mean two different things).
    """
    end = end or as_of or date.today()
    start = start or (end - timedelta(days=365 * _ALL_TIME_LOOKBACK_YEARS))
    return start, end


def profit_summary(
    repo: InventoryRepository,
    *,
    start: date | None = None,
    end: date | None = None,
    show_id: str | None = None,
    as_of: date | None = None,
) -> dict:
    """Gross, cost, net and margin for a period, optionally scoped to one show.

    Bounds are INCLUSIVE on both ends — an admin asking for "July" means the
    31st too, and an exclusive end silently drops the busiest show day of a
    month that ends on a weekend.

    ``start``/``end`` are both OPTIONAL — "all time" must not require the
    caller (model or human) to invent a literal date. ``end`` defaults to
    today; ``start`` defaults to ``_ALL_TIME_LOOKBACK_YEARS`` before ``end``,
    a deliberately bounded stand-in for "the beginning" (see that constant's
    docstring for why an unbounded default is not safe to offer).

    ``as_of`` is injectable so "today" is testable without freezing the clock,
    same seam ``aging_stock`` already uses.

    ``margin_pct`` is ``None`` on zero sales, never ``0.0``: a margin on nothing
    is undefined, and reporting it as zero tells the operator the period lost
    money rather than that it had no sales. Same discipline as the absent-price
    rule — an absent figure is never a guess.
    """
    # Imported here rather than at module scope: routers.admin.analytics pulls
    # in FastAPI, and this module is loaded by a standalone MCP subprocess that
    # has no reason to build a router. The function itself is pure.
    from merlins_collection.routers.admin.analytics import summarize_transactions

    start, end = _default_all_time_window(start, end, as_of)

    txns = repo.list_transactions(start, end)
    if show_id is not None:
        txns = [t for t in txns if t.show_id == show_id]

    # summarize_transactions filters through services.ledger.countable itself —
    # this module deliberately does NOT repeat that filter, so there is one
    # definition of "does this row count" and monkeypatching it changes the
    # answer here too (there is a test asserting exactly that).
    summary = summarize_transactions(txns)

    gross: Decimal = summary["total_sold"]
    purchases: Decimal = summary["total_bought"]
    net: Decimal = summary["net_sales"]

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "show_id": show_id,
        "gross_sales": gross,
        "total_purchases": purchases,
        "net": net,
        "items_sold": summary["items_sold_count"],
        "items_bought": summary["items_bought_count"],
        "trades": summary["trades_count"],
        "margin_pct": float(net / gross * 100) if gross else None,
    }


def shows_with_analytics(
    repo: InventoryRepository,
    *,
    start: date | None = None,
    end: date | None = None,
    include_archived: bool = True,
    limit: int = 200,
) -> list[dict]:
    """Every show, joined with its analytics snapshot when one exists (RFC 0020).

    The "librarian" answer to "which show was most profitable" — the model
    scans this list for the max ``net_sales`` itself rather than being handed
    one pre-computed answer, because the number it needs was ALREADY computed
    correctly by ``generate_show_analytics`` (which routes through the same
    ``countable`` + ``summarize_transactions`` path this module's
    ``profit_summary`` does) the moment each show archived. Nothing here
    re-derives profit from raw transactions — that would risk the trade-cash-
    leg double-count ``summarize_transactions`` already guards against.

    Field names are RENAMED from ``ShowAnalyticsSnapshot``'s own
    (``total_sold``/``total_bought``) to match ``profit_summary``'s response
    (``gross_sales``/``total_purchases``) — deliberately, so the model sees one
    spelling of "gross sales" everywhere in this tool surface rather than a
    different one depending on which tool reported it.

    ``include_archived`` defaults to ``True``, the OPPOSITE of
    ``GET /admin/shows``: most real shows are archived, and hiding them by
    default would hide the answer to almost every question this tool exists
    to answer. This is a research tool, not a picker.

    A show with no stored snapshot — never archived, never manually
    "Generate"-d — gets ``has_analytics: False`` and every money/count field
    ``None``, never ``0``: an absent figure is never a guess, same discipline
    as an absent price.

    Sorted NEWEST first before ``limit`` is applied. ``repo.list_shows()``
    itself returns oldest-first (its SK embeds the date); capping that
    order directly would make ``limit`` silently return the OLDEST matching
    shows to a caller who — reasonably — expects "recent" (found in
    adversarial review of this function's first draft).
    """
    shows = repo.list_shows()
    if not include_archived:
        shows = [s for s in shows if not s.archived]
    if start is not None:
        shows = [s for s in shows if s.date >= start]
    if end is not None:
        shows = [s for s in shows if s.date <= end]
    shows = sorted(shows, key=lambda s: s.date, reverse=True)

    rows: list[dict] = []
    for show in shows[:limit]:
        snapshot = repo.get_show_analytics(show.show_id)
        if snapshot is None:
            has_analytics = False
            gross_sales = total_purchases = net_sales = None
            items_sold_count = items_bought_count = trades_count = None
            stale = False
        else:
            has_analytics = True
            gross_sales = snapshot.total_sold
            total_purchases = snapshot.total_bought
            net_sales = snapshot.net_sales
            items_sold_count = snapshot.items_sold_count
            items_bought_count = snapshot.items_bought_count
            trades_count = snapshot.trades_count
            stale = snapshot.stale

        rows.append({
            "show_id": show.show_id,
            "name": show.name,
            "date": show.date.isoformat(),
            "venue": show.venue,
            "city": show.city,
            "archived": show.archived,
            "has_analytics": has_analytics,
            "stale": stale,
            "gross_sales": gross_sales,
            "total_purchases": total_purchases,
            "net_sales": net_sales,
            "items_sold_count": items_sold_count,
            "items_bought_count": items_bought_count,
            "trades_count": trades_count,
        })

    return rows


#: Never let one tool call drag more than this many rows into a Bedrock
#: context window — NOT the REST archive's 500-row cap (`_ARCHIVE_LIMIT` in
#: `routers/admin/analytics.py`), which feeds a scrollable table, not a chat
#: turn. A caller-supplied `limit` above this is clamped, never trusted.
_MAX_TRANSACTIONS_RETURNED = 100


def raw_transactions(
    repo: InventoryRepository,
    *,
    start: date | None = None,
    end: date | None = None,
    show_id: str | None = None,
    type: str | None = None,  # noqa: A002 - matches the tool's public argument name
    include_voided: bool = False,
    sort: str | None = None,
    limit: int = _MAX_TRANSACTIONS_RETURNED,
    as_of: date | None = None,
) -> dict:
    """Raw ledger rows in a date range, for the "librarian" tool set (RFC 0020).

    Unlike ``profit_summary``, this hands back individual rows rather than a
    computed total — so every row carries ``is_countable`` (``services.ledger
    .is_countable``) and ``is_trade_cash_leg`` (``routers.admin.analytics
    .is_trade_cash_leg``) computed explicitly. Neither convention is visible
    from a row's own fields without knowing it, and a raw-listing tool cannot
    assume the caller will reconstruct either rule on its own — see CLAUDE.md's
    math-trust-boundary discussion and RFC 0020's Detailed Design.

    ``start``/``end`` default exactly the way ``profit_summary``'s do — same
    ``_ALL_TIME_LOOKBACK_YEARS`` window, not the shorter default
    ``routers/admin/analytics.py``'s REST archive uses — so "all time" means
    the same thing everywhere on this tool surface. ``as_of`` is injectable
    for the same reason ``profit_summary``'s is: testable without freezing the
    clock.

    ``include_voided`` defaults ``False``: a voided row is dropped from
    ``items`` unless explicitly requested, but even when included it still
    carries ``voided_at`` and ``is_countable: False`` so it can never be
    mistaken for a real one.

    ``sort`` reuses ``services.transactions_sort`` — but that helper (like the
    ``table_sort`` factory it is built on) silently returns rows UNTOUCHED on
    an unparseable ``sort`` string; it is the *caller's* job to reject a bad
    one, same as ``GET /admin/transactions``'s router does. This function does
    that validation itself, raising rather than silently no-op'ing (CLAUDE.md:
    "an unknown sort field is a 422, never a silent no-op"). When ``sort`` is
    omitted, rows come back newest-first by ``(date, txn_id)`` — the same
    default order the REST archive uses.

    ``limit`` is clamped to ``_MAX_TRANSACTIONS_RETURNED`` regardless of what
    is requested. ``total_matched``/``truncated`` are always present so a
    partial answer is never presented as a complete one.
    """
    # Imported here, not at module scope: this module is loaded by a
    # standalone MCP subprocess with no FastAPI app built around it, and
    # routers.admin.analytics pulls in FastAPI. Same pattern profit_summary
    # already uses for summarize_transactions.
    from merlins_collection.models.business import TransactionType
    from merlins_collection.routers.admin.analytics import is_trade_cash_leg
    from merlins_collection.services.ledger import is_countable
    from merlins_collection.services.transactions_sort import (
        SORT_FIELDS,
        parse_sort,
        sort_transactions,
    )

    start, end = _default_all_time_window(start, end, as_of)

    txn_type: TransactionType | None = None
    if type is not None:
        try:
            txn_type = TransactionType(type)
        except ValueError as exc:
            raise ValueError(
                f"unknown type {type!r}; expected one of "
                f"{sorted(t.value for t in TransactionType)}"
            ) from exc

    if sort is not None and parse_sort(sort) is None:
        raise ValueError(
            f"unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
            f"where field is one of: {', '.join(sorted(SORT_FIELDS))}."
        )

    # A negative `limit` is nonsense, not "no cap" — and Python slicing treats
    # a negative stop as "all but the last N", so `txns[:-1]` on a 5-row match
    # would silently return 4 rows and report `truncated: True`, which reads
    # as a real (if incomplete) answer rather than the caller error it is
    # (adversarial review, RFC 0020 item 3). Reject it the same way an
    # unknown `type` or `sort` value is rejected, rather than letting it
    # through disguised as a plausible result.
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")

    txns = repo.list_transactions(start, end)
    if show_id is not None:
        txns = [t for t in txns if t.show_id == show_id]
    if txn_type is not None:
        txns = [t for t in txns if t.type == txn_type]
    if not include_voided:
        txns = [t for t in txns if is_countable(t)]

    if sort is None:
        txns.sort(key=lambda t: (t.date, t.txn_id), reverse=True)
    else:
        txns = sort_transactions(txns, sort)

    total_matched = len(txns)
    capped_limit = min(limit, _MAX_TRANSACTIONS_RETURNED)
    page = txns[:capped_limit]

    items = []
    for txn in page:
        row = txn.model_dump(mode="json")
        row["is_countable"] = is_countable(txn)
        row["is_trade_cash_leg"] = is_trade_cash_leg(txn)
        items.append(row)

    return {
        "total_matched": total_matched,
        "returned": len(items),
        "truncated": total_matched > len(items),
        "items": items,
    }


#: Never let one tool call drag more than this many rows into a Bedrock
#: context window. Inventory is the LARGEST table in the system (hundreds to
#: low thousands of rows) — a caller-supplied `limit` above this is clamped,
#: never trusted, same discipline as `_MAX_TRANSACTIONS_RETURNED` above.
_MAX_INVENTORY_RETURNED = 100


def raw_inventory(
    repo: InventoryRepository,
    *,
    filters: list[str] | None = None,
    sort: str | None = None,
    limit: int = _MAX_INVENTORY_RETURNED,
) -> dict:
    """Raw admin-visible inventory rows, for the "librarian" tool set (RFC 0020).

    Reuses the SAME registries ``GET /admin/inventory/search`` validates
    against — ``services.inventory_filters`` for ``filters``,
    ``services.inventory_sort`` for ``sort`` — rather than a second
    definition of what a filter or a sort field means. Both raise
    ``ValueError`` on a bad input (unknown field, unparseable triple/bound,
    or — for ``sort`` — a string ``parse_sort`` can't resolve); this function
    has no HTTP boundary to turn that into a 422, so it just lets the error
    propagate, same as ``raw_transactions`` already does.

    ``sort="consignor_name_desc"`` is rejected too, even though
    ``inventory_sort.parse_sort`` would otherwise resolve it (a real,
    REST-supported field, per CLAUDE.md's "A `consignor_id` filter joined
    this registry"): resolving it needs an extra ``repo.list_consignors()``
    id->name map this function's signature has no slot for, and without one
    ``sort_items`` silently degrades to an unchanged order that LOOKS sorted
    — the exact silent-no-op CLAUDE.md bans for sort fields. Every row
    already carries the raw ``consignment.consignor_id`` for the model to
    join against a separate ``list_consignors`` call itself.

    No default order when ``sort`` is omitted, unlike ``raw_transactions``'s
    RFC-stated date-descending default — this mirrors
    ``GET /admin/inventory/search``'s own router instead, which lets
    ``sort=None`` pass through ``repo.list_inventory()``'s order unchanged.

    ``limit`` clamps to ``_MAX_INVENTORY_RETURNED`` and rejects negative
    values outright, same reasoning ``raw_transactions`` documents for why a
    negative stop must never reach Python's slicing.

    Each row is the item's FULL ``model_dump(mode="json")`` plus one
    synthesized field, ``name`` — resolved through
    ``services.card_text.admin_item_name`` (the one shared naming authority)
    since no single field on the base model carries it (raw/graded have
    ``display_name``, sealed has ``product_name``, bulk has neither) —
    falling back to ``None``, matching ``POST /admin/inventory/items-brief``'s
    ``name or None`` convention.
    """
    # Imported here, not at module scope: this module is loaded by a
    # standalone MCP subprocess with no FastAPI app built around it. Nothing
    # imported below pulls in FastAPI, but the pattern is kept consistent
    # with profit_summary/raw_transactions above.
    from merlins_collection.services.card_text import admin_item_name
    from merlins_collection.services.inventory_filters import (
        apply_filters,
        validate_filters,
    )
    from merlins_collection.services.inventory_sort import (
        SORT_FIELDS,
        parse_sort,
        sort_items,
    )

    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")

    parsed_filters = validate_filters(filters or [])

    if sort is not None:
        parsed_sort = parse_sort(sort)
        if parsed_sort is None or parsed_sort[0] not in SORT_FIELDS:
            raise ValueError(
                f"unknown sort {sort!r}. Expected {{field}}_asc or "
                f"{{field}}_desc, where field is one of: "
                f"{', '.join(sorted(SORT_FIELDS))}."
            )

    items = repo.list_inventory()
    items = apply_filters(items, parsed_filters)
    items = sort_items(items, sort)

    total_matched = len(items)
    capped_limit = min(limit, _MAX_INVENTORY_RETURNED)
    page = items[:capped_limit]

    rows = []
    for item in page:
        row = item.model_dump(mode="json")
        row["name"] = admin_item_name(item) or None
        rows.append(row)

    return {
        "total_matched": total_matched,
        "returned": len(rows),
        "truncated": total_matched > len(rows),
        "items": rows,
    }


#: Statuses that mean the item is no longer sitting on a shelf waiting to sell.
#: `SOLD` is the obvious one; the other two are items the business no longer
#: holds, and reporting either as "aging stock" tells the operator to discount
#: something they cannot sell.
_NOT_HELD = frozenset({"sold", "lost", "returned_to_consignor"})


def aging_stock(
    repo: InventoryRepository,
    *,
    min_days: int = 90,
    location: str | None = None,
    min_value: Decimal | None = None,
    as_of: date | None = None,
    limit: int = 50,
) -> list[dict]:
    """Held stock that has been sitting unsold longest, oldest first.

    ``as_of`` is injectable so the arithmetic is testable without freezing the
    clock; it defaults to today.

    There is deliberately **no missing-``acquired_at`` branch**: the field is a
    required, non-optional ``date`` on every inventory model, so a validated
    item always has one and a guard here would be unreachable code pretending
    to be caution. ``test_every_held_item_has_an_acquisition_date`` pins the
    invariant this relies on, so if the model ever relaxes it this function
    fails a test rather than silently sorting unknown-provenance rows to the
    top of the list — the loudest possible place to be wrong.

    ``limit`` is a real bound rather than politeness: the reply is fed back into
    a Bedrock turn, and an unbounded list of a thousand rows is both a cost and
    a context problem.
    """
    today = as_of or date.today()
    rows: list[dict] = []

    for item in repo.list_inventory():
        status = getattr(item, "status", None)
        status_value = getattr(status, "value", status)
        if status_value in _NOT_HELD:
            continue

        days_held = (today - item.acquired_at).days
        if days_held < min_days:
            continue

        if location is not None and getattr(item, "location", None) != location:
            continue

        value = getattr(item, "current_market_value", None)
        if value is None:
            value = getattr(item, "listed_price", None)
        if min_value is not None and (value is None or value < min_value):
            continue

        rows.append({
            # CLAUDE.md's absolute rule reaches the chat through this field: the
            # panel hydrates image/name/price from it. A tool that answered with
            # names alone would leave the operator unable to tell twelve
            # Charizards apart.
            "item_id": item.item_id,
            "card_id": getattr(item, "card_id", None),
            "days_held": days_held,
            "acquired_at": item.acquired_at,
            "location": getattr(item, "location", None),
            "value": value,
            "cost_basis": getattr(item, "cost_basis", None),
        })

    rows.sort(key=lambda r: r["days_held"], reverse=True)
    return rows[:limit]


def consignor_position(
    repo: InventoryRepository,
    *,
    consignor_id: str | None = None,
) -> list[dict]:
    """What the business is holding on each consignor's behalf, and whose it is.

    **``split_percent`` is OUR cut, as a 0-1 fraction** (``ConsignmentTerms``:
    "our cut as a 0-1 fraction (0.05 = a 5% cut)"). The consignor's share is
    therefore the COMPLEMENT. Reading it the other way round inverts every
    payout figure, and both numbers look equally plausible on screen — which is
    why there is a test named for exactly this.

    **Archived consignors are included**, unlike `/admin/cosigners`' list.
    Archiving is a UI-tidiness decision; it is not settlement, and "whose stock
    am I holding" is a question about obligations. The row carries `archived`
    so the caller can say so rather than silently mixing them in.

    An unpriced consigned item is COUNTED but contributes nothing to the value,
    and is reported separately as ``items_unpriced``. Valuing it at zero would
    understate what is being held for someone else — the direction that causes
    an argument.
    """
    names = {c.consignor_id: c for c in repo.list_consignors()}
    positions: dict[str, dict] = {}

    for item in repo.list_inventory():
        terms = getattr(item, "consignment", None)
        if terms is None:
            continue
        if consignor_id is not None and terms.consignor_id != consignor_id:
            continue

        status = getattr(item, "status", None)
        if getattr(status, "value", status) in _NOT_HELD:
            continue

        consignor = names.get(terms.consignor_id)
        row = positions.setdefault(terms.consignor_id, {
            "consignor_id": terms.consignor_id,
            # A ULID is not an answer — resolve the name, and fall back to the
            # id only when the consignor row is genuinely missing, so the
            # operator can still trace it.
            "name": consignor.name if consignor else terms.consignor_id,
            "archived": bool(getattr(consignor, "archived", False)),
            "items_held": 0,
            "items_unpriced": 0,
            "value_held": Decimal("0"),
            "our_projected_cut": Decimal("0"),
            "consignor_projected_share": Decimal("0"),
            "item_ids": [],
        })

        row["items_held"] += 1
        row["item_ids"].append(item.item_id)

        value = getattr(item, "current_market_value", None)
        if value is None:
            value = getattr(item, "listed_price", None)
        if value is None:
            row["items_unpriced"] += 1
            continue

        our_cut = value * terms.split_percent
        row["value_held"] += value
        row["our_projected_cut"] += our_cut
        row["consignor_projected_share"] += value - our_cut

    return sorted(positions.values(), key=lambda r: r["value_held"], reverse=True)


#: The questions `pricing_outliers` can actually answer from stored data.
#:
#: **`stale` is deliberately absent.** RFC 0018's tool table lists a
#: `max_age_days` input, but no inventory model carries a per-item price
#: timestamp — `value_note` mentions an age in PROSE, and parsing a number back
#: out of a sentence to drive a money answer is a guess wearing a filter's
#: clothes. Better to answer three questions correctly than four with one
#: fabricated. If per-item price age is wanted, it needs a real stored field
#: first.
_OUTLIER_DIRECTIONS = frozenset({"over", "under", "unpriced"})


def pricing_outliers(
    repo: InventoryRepository,
    *,
    direction: str,
    threshold_pct: float = 20.0,
    limit: int = 50,
) -> list[dict]:
    """Held stock whose asking price disagrees with the market figure.

    ``direction`` is ``over`` (asking above market), ``under`` (below), or
    ``unpriced`` (no asking price at all). An unknown value raises rather than
    returning ``[]`` — same rule as an unknown ``triage_reason`` or sort field,
    and for the same reason: an empty list reads as "no outliers", which is a
    reassuring answer to a question nobody actually asked.

    ``threshold_pct`` is a MAGNITUDE; ``direction`` alone decides the sign, so a
    card 40% under market can never satisfy ``direction="over"``.

    ``unpriced`` is its own direction rather than an infinite deviation.
    Treating an absent price as zero would report every unpriced card as -100%
    off market and bury the genuinely mispriced ones — an absent price is
    absent, never a guess.
    """
    if direction not in _OUTLIER_DIRECTIONS:
        raise ValueError(
            f"unknown direction {direction!r}; expected one of "
            f"{sorted(_OUTLIER_DIRECTIONS)}"
        )

    rows: list[dict] = []
    for item in repo.list_inventory():
        status = getattr(item, "status", None)
        if getattr(status, "value", status) in _NOT_HELD:
            continue

        # The sticker is what a buyer at the table actually sees; the listing
        # is the fallback for stock that has never been stickered.
        asking = getattr(item, "sticker_price", None)
        if asking is None:
            asking = getattr(item, "listed_price", None)
        market = getattr(item, "current_market_value", None)

        if direction == "unpriced":
            if asking is not None:
                continue
            rows.append(_outlier_row(item, asking=None, market=market, delta=None))
            continue

        # No asking price or no market figure means there is nothing to
        # compare — never a division, never a substituted zero.
        if asking is None or market is None or market == 0:
            continue

        delta_pct = float((asking - market) / market * 100)
        if direction == "over" and delta_pct < threshold_pct:
            continue
        if direction == "under" and delta_pct > -threshold_pct:
            continue

        rows.append(_outlier_row(item, asking=asking, market=market, delta=delta_pct))

    rows.sort(key=lambda r: abs(r["delta_pct"] or 0), reverse=True)
    return rows[:limit]


def _outlier_row(item, *, asking, market, delta) -> dict:
    return {
        # The panel hydrates image/name/price from this — CLAUDE.md's rule that
        # a card is never identified by name alone.
        "item_id": item.item_id,
        "card_id": getattr(item, "card_id", None),
        "asking_price": asking,
        "market_value": market,
        "delta_pct": delta,
        "location": getattr(item, "location", None),
        "cost_basis": getattr(item, "cost_basis", None),
    }


def raw_consignors(
    repo: InventoryRepository,
    *,
    include_archived: bool = True,
    limit: int = 200,
) -> list[dict]:
    """Every consignor's identity and default payout_percent (RFC 0020).

    Complements ``consignor_position``'s item-level aggregate — this is for
    identity/contact/archived-status questions, not for computing anyone's
    cut. ``payout_percent`` is THEIR share as a percent (50 = 50%), the
    OPPOSITE convention from ``ConsignmentTerms.split_percent`` (OUR cut, a
    0-1 fraction) — the tool description states this explicitly, the same
    landmine CLAUDE.md already documents.

    ``include_archived`` defaults to ``True``, same reasoning as
    ``shows_with_analytics``'s: archiving is not settlement, so an archived
    consignor may still be owed money.

    No sort is applied before ``limit`` — unlike ``shows_with_analytics``,
    which needed one because a real business accumulates hundreds of shows,
    a consignor list stays small enough that `limit` truncating an
    unspecified order is not the live risk it was there.
    """
    consignors = repo.list_consignors()
    if not include_archived:
        consignors = [c for c in consignors if not c.archived]
    return [c.model_dump(mode="json") for c in consignors[:limit]]
