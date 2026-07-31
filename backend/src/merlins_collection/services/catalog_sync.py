"""Daily batch job: price snapshots and inventory market-value denormalization.

``run_daily_sync`` is the entry point, driven by ``scripts/daily_sync.py``; the
individual steps are exposed for testing:

- ``snapshot_graded_prices`` — append a daily history point for each owned
  graded slab that has a manual market value.
- ``snapshot_sealed_prices`` — the same for sealed products, whose history hangs
  off the item rather than a catalog card.
- ``refresh_inventory_market_values`` — denormalize the latest market value onto
  each inventory item so list/search reads don't need a second lookup. Resolves
  raw items' prices through the SAME finish-aware helper as the read paths
  (``models.inventory._market_price``) rather than its own lookup — see the
  function's docstring for why that sharing is load-bearing (Phase 12).
- ``refresh_held_prices`` — the Tier 2 DEPTH pass: the one step here that talks
  to TCGdex, fetching per-card detail (rarity + prices) for the cards the
  business actually holds.

Each function takes ``repo`` (an ``InventoryRepository``) and returns a small
summary dict so the job can log what it did.

The Tier 1 BREADTH seed — every card's identity, no prices — stays in
``scripts/seed_catalog.py`` on its own weekly cadence. Breadth is deliberately
not in the daily job: it is a different kind of data at a different rate, which
is the whole point of RFC 0003 §0.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from merlins_collection.config import settings
from merlins_collection.models.catalog import PricePoint
from merlins_collection.models.inventory import ItemStatus, _market_price, new_ulid
from merlins_collection.services.condition_pricing import apply_condition_adjustment
from merlins_collection.services.dynamodb import CatalogReseedInProgressError
from merlins_collection.services.tcgdex import (
    parse_card_id,
    to_catalog_card,
    to_price_points,
)

logger = logging.getLogger(__name__)


def snapshot_graded_prices(repo, today: date) -> dict:
    """Append a daily history point for each owned graded slab with a market value.

    Deduplicates by ``(card_id, company, grade)`` so multiples of the same slab
    write only one point per day.
    """
    seen = set()
    written = 0
    for item in repo.list_inventory():
        if item.kind != "graded" or item.card_id is None:
            continue
        key = (item.card_id, item.company, item.grade)
        if key in seen:
            continue
        seen.add(key)
        value = repo.get_graded_market_value(item.card_id, item.company, item.grade)
        if value is None:
            continue
        repo.append_price_points(
            [
                PricePoint(
                    card_id=item.card_id, date=today, source="manual",
                    kind="graded", company=item.company, grade=item.grade, market=value,
                )
            ]
        )
        written += 1
    return {"graded_points_written": written}


def refresh_inventory_market_values(repo) -> int:
    """Write the latest market value onto each inventory item; return the count.

    Raw items take their value from the catalog card's finish price; graded items
    from the manual graded value. Per-card lookups are cached, and an item is
    only rewritten when its value actually changed. Returns how many were updated.

    The raw lookup goes through ``models.inventory._market_price`` — the SAME
    finish-aware helper the search and summary paths use — rather than a bare
    ``card.prices.get(item.finish)``. That exact match is what this function used
    to do, and it silently left 174 of 213 live items unpriced: a ``"normal"``-
    finish item against a card TCGdex prices only under ``holofoil`` matched
    nothing here while the read path priced it correctly (claude-progress.txt
    Phase 12, absorbing Phase 10). Sharing the helper is the fix AND the guard
    against the two paths drifting apart again.
    """
    updated = 0
    catalog_cache: dict = {}
    graded_cache: dict = {}
    for item in repo.list_inventory():
        if item.kind not in ("raw", "graded") or item.card_id is None:
            continue
        if item.kind == "raw":
            if item.card_id not in catalog_cache:
                catalog_cache[item.card_id] = repo.get_catalog_card(item.card_id)
            card = catalog_cache[item.card_id]
            value = _market_price(card, item.finish) if card else None
            # Phase 19: apply condition-based multiplier to the raw NM market
            # price. The adjustment is baked into current_market_value so both
            # the website and the MCP server (which reads this field directly)
            # see the same condition-adjusted figure without reimplementing the
            # multiplier logic independently.
            if value is not None:
                value, value_note = apply_condition_adjustment(
                    value, item.condition, item.condition_modifier,
                )
            else:
                value_note = None
        else:
            ckey = (item.card_id, item.company, item.grade)
            if ckey not in graded_cache:
                graded_cache[ckey] = repo.get_graded_market_value(
                    item.card_id, item.company, item.grade
                )
            value = graded_cache[ckey]
            value_note = None
        if value is not None and value != item.current_market_value:
            update_fields: dict = {"current_market_value": value}
            if value_note is not None:
                update_fields["value_note"] = value_note
            repo.put_inventory_item(item.model_copy(update=update_fields))
            updated += 1
    return updated


def snapshot_sealed_prices(repo, today: date) -> dict:
    """Append a daily history point for each sealed item with a market value.

    Sealed products have no catalog card, so their history hangs off the item
    itself (``ITEM#<item_id>`` price points).
    """
    written = 0
    for item in repo.list_inventory():
        if item.kind != "sealed" or item.current_market_value is None:
            continue
        repo.append_item_price_point(item.item_id, today, item.current_market_value)
        written += 1
    return {"sealed_points_written": written}


def _held_card_ids(repo) -> set[str]:
    """Catalog ids of the RAW cards the business still owns — the depth pass's set.

    Sold stock is excluded per RFC 0003 §7: the realized price is on the
    transaction, and a live market figure for something we no longer own has no
    consumer. The tradeoff is that per-card history stops accruing when the last
    copy sells; the history already written is kept either way.

    **Graded slabs are excluded too, and that is a deliberate, permanent
    deviation from §7's written predicate — do not "fix" it back.** A slab's
    price and its descriptive detail both come from the PSA cert API +
    PriceCharting (Phase 4), which owns slab data end to end; TCGdex publishes no
    graded prices at all. Fetching a slab's card here would spend a request to
    overwrite a hand-curated row with raw-single figures that do not describe it.

    ``kind`` is tested before ``card_id``, as everywhere else in this module:
    sealed and bulk items do not merely have a null ``card_id``, they have no
    such field at all, so the reverse order raises ``AttributeError`` on the
    first box in the inventory.
    """
    return {
        item.card_id
        for item in repo.list_inventory()
        if item.kind == "raw"
        and item.card_id
        and item.status in (ItemStatus.AVAILABLE, ItemStatus.ON_HOLD)
    }


def _staleness_note(band, today: date, stale_days: int) -> str | None:
    """A note naming the price's age, or ``None`` when it is fresh (or undated).

    A band with no ``source_updated_at`` gets no note: we do not know it is old,
    and asserting staleness we cannot evidence is its own kind of wrong figure.
    """
    if band.source_updated_at is None:
        return None
    age_days = (today - band.source_updated_at.date()).days
    if age_days <= stale_days:
        return None
    return (f"stale: upstream last updated "
            f"{band.source_updated_at.date().isoformat()} ({age_days} days ago, "
            f"threshold {stale_days})")


def _annotate_stale_prices(card, today: date, stale_days: int):
    """Return ``card`` with a staleness note appended to any long-unchanged band.

    The figure itself is never touched. Suppressing or nulling a stale price
    would replace a number that is merely old with no number at all, which is
    strictly less information for the customer and for us (RFC 0003 §7). The note
    is APPENDED so the Cardmarket path's FX-conversion note survives alongside it.
    """
    annotated = {}
    for finish, band in card.prices.items():
        note = _staleness_note(band, today, stale_days)
        if note is None:
            annotated[finish] = band
            continue
        annotated[finish] = band.model_copy(update={
            "value_note": f"{band.value_note}; {note}" if band.value_note else note
        })
    return card.model_copy(update={"prices": annotated})


def refresh_held_prices(repo, client, today: date, *,
                        request_delay_seconds: float = 0.1,
                        max_consecutive_failures: int = 25) -> dict:
    """Fetch TCGdex detail (rarity + prices) for every held raw card (RFC 0003 §7).

    This is the only step that leaves the building, and it runs unattended, so
    its failure posture is the specification:

    - a per-card error is caught, counted under ``failures``, and the run
      continues. **An existing price is never deleted, zeroed or nulled** — a
      total outage means zero cards updated and yesterday's figures still serving.
    - that promise covers the *priceless success* too, which is the case it used
      to miss: an HTTP 200 carrying a complete record whose ``pricing`` block
      yields no band raises nothing and is otherwise indistinguishable from a
      priced success. Such a response is still written — it can carry a corrected
      ``rarity``, and dropping the whole write would trade one data problem for a
      smaller one — but it goes through
      ``repo.upsert_catalog_card_preserving_prices``, which omits an empty
      ``prices`` from the write so the stored bands survive. It is counted under
      ``no_usable_price`` (a SUBSET of ``cards_updated``, not a failure) because
      "fetched fine, nobody prices it" and "fetched fine, priced" are different
      operational facts and the first was previously invisible.
    - ``max_consecutive_failures`` consecutive errors abort the run
      (``{"aborted": True, ...}``) rather than burning ~300 timeouts against a
      dead endpoint. The counter RESETS on a success, so a scatter of unlucky
      cards never trips it.
    - a 404 (``get_card`` returning ``None``) is counted under ``not_found`` and
      **neither increments nor resets** that counter. A card TCGdex retired is
      neither a success nor an infrastructure failure, and counting retirements
      as failures would let 25 retired holdings abort the job every morning,
      silently and forever.

    Cards are written one at a time rather than batched: a batch that fails takes
    down cards that mapped perfectly well, and ~300 writes a day is nothing.

    Held cards are fetched in sorted order. The set itself is unordered, and
    Python's string hashing is salted per process, so an unsorted walk would pick
    a *different* arbitrary subset to abandon on every aborted run — the same
    outage would leave a different hole each morning.
    """
    # Serialize against a reseed. A depth-pass write that lands after a reseed has
    # passed that card but before its finalize carries the superseded generation
    # and is swept — the card silently disappears from a live catalog (RFC §8).
    lock_gen = new_ulid()
    try:
        repo.acquire_catalog_lock(lock_gen)
    except CatalogReseedInProgressError:
        logger.warning("depth pass skipped: a catalog reseed holds the catalog lock")
        return {"skipped": "catalog reseed in flight"}
    try:
        # Stamp writes with the committed generation so the next reseed's swap
        # keeps them. `None` (nothing has ever committed one) stamps nothing,
        # which is how every catalog write behaves today.
        repo.set_catalog_generation(repo.current_catalog_generation())
        return _refresh_held_prices(repo, client, today, request_delay_seconds,
                                    max_consecutive_failures)
    finally:
        # Both in a `finally`: an unexpected raise must not leave the lock held
        # for its full hour-long TTL, blocking tomorrow's run and any reseed.
        repo.set_catalog_generation(None)
        repo.release_catalog_lock(lock_gen)


def _refresh_held_prices(repo, client, today, request_delay_seconds,
                         max_consecutive_failures) -> dict:
    """The depth pass proper; ``refresh_held_prices`` owns the lock around it."""
    stale_days = settings.catalog_price_stale_days
    updated = failures = not_found = unparsable = requested = 0
    no_usable_price = 0
    consecutive = 0
    aborted = False
    for card_id in sorted(_held_card_ids(repo)):
        parsed = parse_card_id(card_id)
        if parsed is None:
            # A pokemontcg.io-era id, or one no language claims. Counted rather
            # than raised, and kept OUT of `failures` so a pocket of legacy rows
            # can never trip the consecutive-failure abort on a healthy endpoint.
            unparsable += 1
            logger.warning("depth pass: %r is not a TCGdex card id; skipping", card_id)
            continue
        language, tcgdex_id = parsed
        if requested and request_delay_seconds:
            # Politeness toward a free volunteer-run API, not a rate limit we
            # have hit. Between requests only, so a one-card run never sleeps.
            time.sleep(request_delay_seconds)
        requested += 1
        try:
            raw = client.get_card(language, tcgdex_id)
            if raw is None:
                # Retired upstream. Nothing is written — in particular no bare
                # identity row for a card that has no catalog row yet, which
                # would publish an empty shell we never had data for. Any
                # existing row keeps the price it already has.
                not_found += 1
                logger.info("depth pass: %s is gone from TCGdex (404)", card_id)
                continue
            card = _annotate_stale_prices(
                to_catalog_card(raw, language, fx_rate=settings.eur_usd_rate),
                today, stale_days,
            )
            if not card.prices:
                # A complete 200 that no provider prices. Counted, not failed:
                # nothing is broken, there is simply no figure to publish today.
                no_usable_price += 1
                logger.info("depth pass: %s returned no usable price; "
                            "keeping the stored band", card_id)
            # NOT `batch_upsert_catalog_cards`: that is a whole-item put and an
            # empty `prices` would erase yesterday's bands (RFC 0003 §7).
            repo.upsert_catalog_card_preserving_prices(card)
            repo.append_price_points(to_price_points(card, today))
        except Exception as exc:  # noqa: BLE001 - one bad card must not end the run
            failures += 1
            consecutive += 1
            logger.warning("depth pass: %s failed (%s: %s)", card_id,
                           type(exc).__name__, exc)
            if consecutive >= max_consecutive_failures:
                logger.error("depth pass aborted after %d consecutive failures; "
                             "existing prices are untouched", consecutive)
                aborted = True
                break
            continue
        consecutive = 0
        updated += 1
    return {"cards_updated": updated, "failures": failures,
            "not_found": not_found, "unparsable_card_ids": unparsable,
            "no_usable_price": no_usable_price, "aborted": aborted}


def run_daily_sync(repo, client, today: date) -> dict:
    """Run all sync steps in order and return their merged summary.

    The depth pass runs FIRST and the order is load-bearing (RFC 0003 §7):
    ``refresh_inventory_market_values`` denormalizes the catalog prices
    ``refresh_held_prices`` has just written, so the other order publishes
    yesterday's figures for a day and makes every new holding wait two runs for
    its first price.
    """
    summary = dict(refresh_held_prices(repo, client, today))
    summary.update(snapshot_graded_prices(repo, today))
    summary.update(snapshot_sealed_prices(repo, today))
    summary["items_refreshed"] = refresh_inventory_market_values(repo)
    return summary
