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
- ``refresh_held_prices`` — the Tier 2 DEPTH pass: fetches per-card detail
  (rarity + prices) from TCGdex for the cards the business actually holds.
- ``refresh_catalog_prices`` — the weekly CYCLE (RFC 0010 T17): the same
  per-card fetch for a slice of the catalog we do NOT own, ~5,500 a night
  stalest-first, so every one of the ~31,300 remaining rows is re-priced at
  least once a week. Both passes share ``_refresh_one_card``; each owns only its
  candidate selection and its budget.

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
from datetime import date, datetime, timezone

from merlins_collection.config import settings
from merlins_collection.models.catalog import PricePoint
from merlins_collection.models.inventory import ItemStatus, Language, _market_price, new_ulid
from merlins_collection.services import catalog_cache
from merlins_collection.services.condition_pricing import apply_condition_adjustment
from merlins_collection.services.dynamodb import CatalogReseedInProgressError
from merlins_collection.services.tcgdex import (
    build_card_id,
    parse_card_id,
    to_catalog_card,
    to_catalog_card_brief,
    to_price_points,
)

logger = logging.getLogger(__name__)

# Write buffer size for `sync_new_sets`. A newly released set is a few hundred
# cards at most, orders of magnitude below `scripts/seed_catalog.py`'s
# 23k-card whole-catalog walk, so one flush per set-language pass is typically
# enough; the cap exists so a pathological response still writes in bounded
# chunks rather than building one unbounded list in memory.
_NEW_SETS_BATCH_SIZE = 500


def snapshot_graded_prices(repo, today: date) -> dict:
    """Append a daily history point for each owned graded slab with a market value.

    Deduplicates by ``(card_id, company, grade)`` so multiples of the same slab
    write only one point per day.

    The point carries the STORED row's ``source`` rather than a hardcoded
    ``"manual"`` (RFC 0009 T7). Before ``refresh_graded_prices`` existed, every
    graded value really was hand-typed and the constant was honest; now a chart
    has to be able to tell a figure someone typed from one the provider fetched,
    and those are different claims about how much to trust the line. A row
    written before T6 added the field has no ``source`` at all, so it falls back
    to ``"manual"`` — which is what it was.
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
        row = repo.get_graded_price_row(item.card_id, item.company, item.grade)
        value = row.get("market_value") if row else None
        if value is None:
            continue
        repo.append_price_points(
            [
                PricePoint(
                    card_id=item.card_id, date=today,
                    source=row.get("source") or "manual",
                    kind="graded", company=item.company, grade=item.grade, market=value,
                )
            ]
        )
        written += 1
    return {"graded_points_written": written}


# ---------------------------------------------------------------------------
# Graded pricing — the nightly provider pass (RFC 0009 T7)
# ---------------------------------------------------------------------------

# Statuses that still mean "we own it". Mirrors `_held_card_ids`, and for the
# same reason (RFC 0003 §7): a live market figure for something we no longer own
# has no consumer. Here the reason is sharper, because producing one costs 2 of
# a 100-credit day.
_OWNED_STATUSES = (ItemStatus.AVAILABLE, ItemStatus.ON_HOLD)

# 1 credit for the card + 1 for the eBay sales block. `costPerCard: 2`, read off
# a live response rather than the docs (spike-findings §2.1). This is the whole
# reason the free tier is FIFTY slabs a night and not a hundred.
_CREDITS_PER_LOOKUP = 2

# Much tighter than the depth pass's 25, because the unit of waste is different.
# Every failed call is still BILLED — the client debits as soon as the vendor
# answers, whatever it answered — so a vendor 500ing at everything would spend
# the entire day's budget producing nothing. TCGdex failures cost only time.
_MAX_CONSECUTIVE_FAILURES = 5


def build_pricing_provider():
    """The configured graded-pricing client, or ``None`` when there is no key.

    ``None`` rather than a raise, because the two callers want opposite things
    from the same absence. The nightly job must degrade — a missing or
    mid-rotation key cannot be allowed to take down the depth pass and both
    snapshots with it — while the admin button must report a failure, because a
    human is standing there waiting for prices that are never coming.
    """
    from merlins_collection.services.slab.pricing import (
        PokemonPriceTrackerClient,
        PricingProviderError,
    )

    try:
        return PokemonPriceTrackerClient(
            api_key=settings.pokemonpricetracker_api_key
        )
    except PricingProviderError as exc:
        # `exc` is constructed from the config's absence, never from the key.
        logger.warning("graded pricing unavailable: %s", exc)
        return None


class _ProviderMemo:
    """Answers a repeated question from within one run instead of re-buying it.

    Two savings, and the second matters more than the money. One vendor response
    carries EVERY grade — ~23 buckets spanning PSA/BGS/CGC/SGC (spike §2.2) — so
    a card held in PSA 9 and PSA 10 is one lookup rather than two. And because
    the memo covers ``resolve`` as well, the FUZZY search runs at most once per
    card even when several grades of it are queued: T0 measured that search
    returning the wrong card roughly a third of the time, so halving the number
    of times we ask is a correctness win, not only a cost one.

    Scoped to one run, deliberately. A figure from last night is exactly what
    tonight's run exists to replace.

    ``calls`` counts what actually left the process, INCLUDING a call that
    raised — the vendor bills a 500 the same as a 200 — so it is the honest
    measure of budget spent.
    """

    def __init__(self, provider):
        self._provider = provider
        self._resolved: dict = {}
        self._priced: dict = {}
        self.calls = 0

    def resolve(self, *, name, set_name, number, language=Language.EN):
        key = (name, set_name, number, language)
        if key in self._resolved:
            return self._resolved[key]
        self.calls += 1
        result = self._provider.resolve(name=name, set_name=set_name,
                                        number=number, language=language)
        self._resolved[key] = result
        return result

    def prices(self, price_source_id):
        if price_source_id in self._priced:
            return self._priced[price_source_id]
        self.calls += 1
        result = self._provider.prices(price_source_id)
        self._priced[price_source_id] = result
        return result


def _graded_candidates(repo) -> list:
    """Owned slabs, one per ``(card_id, company, grade)``.

    Deduped before anything is spent: two copies of the same slab at the same
    grade share one price row, so the second copy's lookup would buy a number we
    already have. An UNLINKED slab is kept as its own candidate — there is no
    key to dedupe it by, and the loop skips it for free anyway.
    """
    seen = set()
    candidates = []
    for item in repo.list_inventory():
        if item.kind != "graded" or item.status not in _OWNED_STATUSES:
            continue
        if item.card_id is not None:
            key = (item.card_id, str(item.company), str(item.grade))
            if key in seen:
                continue
            seen.add(key)
        candidates.append(item)
    return candidates


def _staleness_key(row, item) -> tuple:
    """Sort key: never-priced first, then oldest first, then oldest item.

    A slab with no value at all is more urgent than one priced yesterday, and
    with the budget smaller than the shelf that ordering is the only thing
    deciding who gets tonight's credits. The ``item_id`` tie-break is not
    cosmetic: item ids are ULIDs so it is a stable, time-ordered fallback, and
    without it a truncated run would abandon a *different* arbitrary subset
    every night — the same trap `refresh_held_prices` sorts its held set to
    avoid.
    """
    if row is None:
        return (0, "", item.item_id)
    return (1, str(row.get("updated_at") or ""), item.item_id)


def refresh_graded_prices(repo, provider, *,
                          max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES
                          ) -> dict:
    """Fetch provider prices for owned slabs, stalest first, within today's budget.

    **This job never calls PSA.** A cert's identity is immutable and population —
    the only mutable field — is ``null`` on the public API anyway (RFC 0009
    §5.1), so there is nothing about a slab for PSA to refresh. The only
    collaborator is the injected pricing provider.

    Everything expensive is decided before a socket opens:

    - a slab with no ``card_id`` is skipped for FREE. ``attach_price`` would
      refuse it too, but only after paying 2 credits for the answer, and being
      unlinked is a normal state Triage already surfaces rather than an error.
    - a PINNED price is skipped for free (owner's decision, 2026-08-09). It is
      the one figure the operator has said not to touch.
    - candidates are deduped, then ordered never-priced-first, then capped at
      what the daily budget can actually pay for.

    Failure posture, mirroring the depth pass because it runs just as
    unattended: one card's failure is caught, counted and stepped over, so a
    hiccup on slab 3 of 80 does not cost the other 77. Two things end a run
    early instead — the budget running out (a clean stop, reported), and
    ``max_consecutive_failures`` in a row (a dead vendor, whose every 500 is
    still billed).

    The order of the two ``except`` clauses is load-bearing:
    ``PricingQuotaExceeded`` SUBCLASSES ``PricingProviderError``, so catching the
    parent first would book the budget running out as a per-item failure and
    spin through every remaining candidate collecting 429s.
    """
    from merlins_collection.services.slab.pricing import (
        PricingQuotaExceeded,
        attach_price,
    )

    candidates = _graded_candidates(repo)
    skipped = pinned = priced = unpriced = failures = 0

    plan = []
    for item in candidates:
        if not item.card_id:
            skipped += 1
            continue
        row = repo.get_graded_price_row(item.card_id, item.company, item.grade)
        if row is not None and row.get("pinned"):
            pinned += 1
            continue
        plan.append((_staleness_key(row, item), item))
    plan.sort(key=lambda pair: pair[0])

    budget = _lookup_budget(provider)
    memo = _ProviderMemo(provider)
    consecutive = 0
    aborted = quota_exhausted = False

    for _key, item in plan:
        if memo.calls >= budget:
            # Not a failure: tonight's allowance is simply spent, and the rest of
            # the shelf is first in line tomorrow because it is now the stalest.
            quota_exhausted = True
            break
        try:
            result = attach_price(item=item, provider=memo, repo=repo)
        except PricingQuotaExceeded:
            # MUST precede the parent clause below.
            quota_exhausted = True
            logger.info("graded pricing: daily budget spent; stopping cleanly "
                        "after %d lookups", memo.calls)
            break
        except Exception as exc:  # noqa: BLE001 - one bad card must not end the run
            failures += 1
            consecutive += 1
            # The message, never the request: nothing here may carry the key.
            logger.warning("graded pricing: %s failed (%s)", item.item_id,
                           type(exc).__name__)
            if consecutive >= max_consecutive_failures:
                aborted = True
                logger.error("graded pricing aborted after %d consecutive "
                             "failures; existing prices are untouched", consecutive)
                break
            continue
        consecutive = 0
        if result.attached:
            priced += 1
        else:
            # Refused, not failed — no coverage for this grade, or the verified
            # join said no. `result.reason` is the honest answer to "why is this
            # slab still unpriced?", which is what /admin/slabs?priced=false asks.
            unpriced += 1
            logger.info("graded pricing: %s not priced (%s)", item.item_id,
                        result.reason)

    remaining = _credits_remaining(provider)
    logger.info(
        "graded pricing: %d candidates, %d priced, %d unpriced, %d skipped, "
        "%d pinned, %d failures, %d lookups, %d credits remaining%s",
        len(candidates), priced, unpriced, skipped, pinned, failures,
        memo.calls, remaining if remaining is not None else -1,
        " (ABORTED)" if aborted else "",
    )

    return {
        "graded_candidates": len(candidates),
        "graded_priced": priced,
        "graded_unpriced": unpriced,
        "graded_skipped": skipped,
        "graded_pinned": pinned,
        "graded_failures": failures,
        "graded_lookups": memo.calls,
        "graded_quota_exhausted": quota_exhausted,
        "graded_aborted": aborted,
        "graded_credits_remaining": remaining,
    }


def _lookup_budget(provider) -> int:
    """How many slabs today's remaining credits can actually pay for.

    Read off the provider's own counter when it has one, so a run started with a
    partly-spent budget refreshes what is left rather than what a fresh day
    would allow.
    """
    remaining = _credits_remaining(provider)
    if remaining is None:
        remaining = settings.pricing_daily_quota
    return max(0, remaining // _CREDITS_PER_LOOKUP)


def _credits_remaining(provider) -> int | None:
    quota = getattr(provider, "quota", None)
    return None if quota is None else quota.remaining


def _no_pricing_provider_summary() -> dict:
    """The graded keys, all zero, when there is no provider to ask.

    Present rather than absent so a caller reading the summary sees "nothing was
    priced" instead of a ``KeyError`` — and so the nightly job's printed report
    has the same shape whether the key is configured or not.
    """
    return {
        "graded_candidates": 0, "graded_priced": 0, "graded_unpriced": 0,
        "graded_skipped": 0, "graded_pinned": 0, "graded_failures": 0,
        "graded_lookups": 0, "graded_quota_exhausted": False,
        "graded_aborted": False, "graded_credits_remaining": None,
    }


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
        # All three in a `finally`: an unexpected raise must not leave the lock
        # held for its full hour-long TTL, blocking tomorrow's run and any
        # reseed -- nor leave the API serving the prices this pass replaced.
        # A run that dies partway has still written the cards it got through,
        # and the Buy page reads `prices` straight off a search result.
        repo.set_catalog_generation(None)
        repo.release_catalog_lock(lock_gen)
        catalog_cache.invalidate()


def _refresh_held_prices(repo, client, today, request_delay_seconds,
                         max_consecutive_failures) -> dict:
    """The depth pass proper; ``refresh_held_prices`` owns the lock around it.

    Held cards are fetched in sorted order — see the wrapper's docstring for
    why an unsorted walk would abandon a different arbitrary subset every time.
    """
    return _refresh_cards(
        repo, client, sorted(_held_card_ids(repo)), today,
        request_delay_seconds=request_delay_seconds,
        max_consecutive_failures=max_consecutive_failures,
        label="depth pass",
    )


def _refresh_one_card(repo, client, card_id, language, tcgdex_id, today,
                      stale_days) -> str | None:
    """Fetch, map and write ONE catalog card. ``None`` means TCGdex 404'd it.

    **This is a specification, not a loop body** (RFC 0003 §7), which is why
    both passes share it rather than each keeping a copy:

    - a 404 writes NOTHING — in particular no bare identity row for a card that
      has no catalog row yet, which would publish an empty shell we never had
      data for. Any existing row keeps the price it already has.
    - a *priceless success* — a complete HTTP 200 whose ``pricing`` block yields
      no band, which ``services.tcgdex`` calls routine rather than exceptional —
      is still written, because it can carry a corrected ``rarity``, but through
      ``upsert_catalog_card_preserving_prices``, which omits an empty ``prices``
      from the write so the stored bands survive.
    - **an existing price is never deleted, zeroed or nulled**, on any path.

    Errors are RAISED, not swallowed: the budget and the consecutive-failure
    posture belong to the caller, which is the only thing the two passes
    legitimately disagree about.
    """
    raw = client.get_card(language, tcgdex_id)
    if raw is None:
        return None
    card = _annotate_stale_prices(
        to_catalog_card(raw, language, fx_rate=settings.eur_usd_rate),
        today, stale_days,
    )
    # NOT `batch_upsert_catalog_cards`: that is a whole-item put and an empty
    # `prices` would erase yesterday's bands (RFC 0003 §7).
    repo.upsert_catalog_card_preserving_prices(card)
    repo.append_price_points(to_price_points(card, today))
    return "priced" if card.prices else "no_usable_price"


def _refresh_cards(repo, client, card_ids, today, *, request_delay_seconds,
                   max_consecutive_failures, label, deadline=None) -> dict:
    """Walk ``card_ids``, pricing each through ``_refresh_one_card``.

    The failure posture is the depth pass's, unchanged, because it runs
    unattended and RFC 0003 §7 specifies it: a per-card error is caught, counted
    and stepped over; ``max_consecutive_failures`` in a row aborts rather than
    burning thousands of timeouts against a dead endpoint; the counter RESETS on
    a success so a scatter of unlucky cards never trips it; and a 404 **neither
    increments nor resets** it, because counting retirements as failures would
    let a pocket of retired cards abort the job every morning, forever.

    ``deadline`` (a ``time.monotonic()`` value) is the one thing the weekly
    catalog cycle needs and the ~300-card depth pass does not: a mis-set nightly
    budget must not be able to outlive the catalog lock's 3600 s TTL. Crossing
    it is a CLEAN stop — reported, but not a failure — because nothing is broken;
    the cards it did not reach are simply still the stalest and tomorrow takes
    them. ``None`` disables the check entirely, so the depth pass does not so
    much as read the clock.
    """
    stale_days = settings.catalog_price_stale_days
    updated = failures = not_found = unparsable = requested = 0
    no_usable_price = 0
    consecutive = 0
    aborted = runtime_exceeded = False
    for card_id in card_ids:
        if deadline is not None and time.monotonic() >= deadline:
            runtime_exceeded = True
            logger.warning("%s: runtime cap reached after %d cards; stopping "
                           "cleanly rather than outliving the catalog lock",
                           label, requested)
            break
        parsed = parse_card_id(card_id)
        if parsed is None:
            # A pokemontcg.io-era id, or one no language claims. Counted rather
            # than raised, and kept OUT of `failures` so a pocket of legacy rows
            # can never trip the consecutive-failure abort on a healthy endpoint.
            unparsable += 1
            logger.warning("%s: %r is not a TCGdex card id; skipping", label, card_id)
            continue
        language, tcgdex_id = parsed
        if requested and request_delay_seconds:
            # Politeness toward a free volunteer-run API, not a rate limit we
            # have hit. Between requests only, so a one-card run never sleeps.
            time.sleep(request_delay_seconds)
        requested += 1
        try:
            outcome = _refresh_one_card(repo, client, card_id, language,
                                        tcgdex_id, today, stale_days)
        except Exception as exc:  # noqa: BLE001 - one bad card must not end the run
            failures += 1
            consecutive += 1
            logger.warning("%s: %s failed (%s: %s)", label, card_id,
                           type(exc).__name__, exc)
            if consecutive >= max_consecutive_failures:
                logger.error("%s aborted after %d consecutive failures; "
                             "existing prices are untouched", label, consecutive)
                aborted = True
                break
            continue
        if outcome is None:
            # Retired upstream — neither a success nor an infrastructure
            # failure, so `consecutive` is left exactly where it was.
            not_found += 1
            logger.info("%s: %s is gone from TCGdex (404)", label, card_id)
            continue
        if outcome == "no_usable_price":
            # Fetched fine, nobody prices it. A SUBSET of `cards_updated`, not a
            # failure — "priced" and "priceless" are different operational facts.
            no_usable_price += 1
            logger.info("%s: %s returned no usable price; keeping the stored "
                        "band", label, card_id)
        consecutive = 0
        updated += 1
    return {"cards_updated": updated, "failures": failures,
            "not_found": not_found, "unparsable_card_ids": unparsable,
            "no_usable_price": no_usable_price, "aborted": aborted,
            "runtime_exceeded": runtime_exceeded}


# ---------------------------------------------------------------------------
# The weekly catalog price cycle (RFC 0010 T17)
# ---------------------------------------------------------------------------

# 45 minutes, against the catalog lock's 3600 s TTL. The cap exists so a
# mis-typed `CATALOG_REFRESH_CARDS_PER_NIGHT` cannot blow that TTL: at 5,500
# cards x 0.262 s the pass takes ~24 min, but a stray zero would make it ~4 h,
# and the failure mode there is not a stale price — an expired lock is
# STEALABLE, and a write landing across a reseed's swap carries the superseded
# generation and is swept, so the card silently vanishes from a live catalog.
_CATALOG_MAX_RUNTIME_SECONDS = 2700

# 162 ms of TCGdex latency + the 100 ms courtesy delay, measured 2026-08-10.
# Exported because both the runtime estimate in `scripts/reprice_catalog.py` and
# the sizing argument above are derived from this one number.
SECONDS_PER_CARD = 0.262


def as_utc(moment: datetime) -> datetime:
    """``moment`` as an aware UTC datetime, treating a naive one as UTC.

    Stored ``last_synced_at`` values are written aware, but a row from an older
    writer can come back naive — and comparing the two raises ``TypeError``
    mid-sort, which would take down the nightly job over a formatting detail.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def select_catalog_refresh_candidates(repo, *, limit: int | None) -> list[str]:
    """Catalog cards to re-price, never-priced first then stalest, capped.

    ``limit=None`` means "every candidate" and is for the one-time reprice
    script; the nightly cycle always passes a number.

    **The ordering is the design.** ``detail == "brief"`` is checked FIRST and
    not as a tiebreak, because ``last_synced_at`` is bumped by ANY write
    including ``sync_new_sets``' breadth pass — so a brand-new row with no price
    at all looks *fresher* than a priced row from last week. Ordering on the
    timestamp alone would push exactly the cards this cycle exists to reach to
    the back of the queue. Same shape as ``refresh_graded_prices``: never-priced
    first, then stalest, capped at a budget.

    Held cards are excluded: ``refresh_held_prices`` covers them every night, so
    fetching them here would be pure waste, and disjoint candidate sets keep the
    two passes' summary counts readable. A card held only as a graded SLAB is
    not in that set and is therefore a candidate here — correctly: this writes a
    catalog card's raw-single bands, which is what a catalog row is, and never
    touches the ``GRADEDPRICE#`` row the graded pipeline owns.

    The scan is streamed and only three small fields per card are kept: the
    whole catalog parsed and held at once measures ~93 MB.
    """
    if limit is not None and limit <= 0:
        return []
    held = _held_card_ids(repo)
    plan = [
        (0 if card.detail == "brief" else 1, as_utc(card.last_synced_at), card.card_id)
        for card in repo.iter_catalog_cards()
        if card.card_id not in held
    ]
    plan.sort()
    chosen = plan if limit is None else plan[:limit]
    return [card_id for _priority, _synced, card_id in chosen]


def _catalog_summary(*, candidates: int = 0, result: dict | None = None,
                     skipped: str | None = None) -> dict:
    """The catalog pass's counts under their OWN keys.

    Prefixed rather than merged into the depth pass's, or a 5,500-card catalog
    walk and a 300-card held refresh become indistinguishable in the one report
    anybody reads. Every key is always present — including ``catalog_skipped:
    None`` on the happy path — so a reader never has to tell "absent" from
    "zero" (the same reasoning as ``_no_pricing_provider_summary``).
    """
    result = result or {}
    return {
        "catalog_skipped": skipped,
        "catalog_candidates": candidates,
        "catalog_cards_updated": result.get("cards_updated", 0),
        "catalog_failures": result.get("failures", 0),
        "catalog_not_found": result.get("not_found", 0),
        "catalog_unparsable_card_ids": result.get("unparsable_card_ids", 0),
        "catalog_no_usable_price": result.get("no_usable_price", 0),
        "catalog_aborted": result.get("aborted", False),
        "catalog_runtime_exceeded": result.get("runtime_exceeded", False),
    }


def refresh_catalog_prices(repo, client, today: date, *,
                           cards_per_night: int | None = None,
                           card_ids=None,
                           request_delay_seconds: float = 0.1,
                           max_consecutive_failures: int = 25,
                           max_runtime_seconds: float = _CATALOG_MAX_RUNTIME_SECONDS,
                           ) -> dict:
    """Re-price a slice of the catalog we do NOT own — the weekly cycle (T17).

    ``refresh_held_prices`` prices the ~300 cards the business holds. Every
    other row in the 31,603-row catalog has no price at all, which is backwards
    for the Buy table: the card someone is trying to sell you is by definition
    one you do not own yet. This pass walks the rest, ~5,500 a night
    (``CATALOG_REFRESH_CARDS_PER_NIGHT``), so every row is re-priced at least
    once a week — 5.7 nights per cycle, leaving Friday as slack.

    **It is deliberately not one full-catalog pass a night**, and the reason is
    the lock rather than the clock: 31,603 x 0.262 s is 2 h 18 min, which
    outlives the catalog lock's 3600 s TTL. See ``_CATALOG_MAX_RUNTIME_SECONDS``
    for what an expired lock actually costs.

    A night that fails loses nothing: its cards stay stale, so tomorrow's
    stalest-first selection picks them up. **There is no cycle cursor** — a
    cursor is state that can be wrong, and it strands whatever an aborted night
    skipped.

    ``card_ids`` bypasses selection, and exists for ``scripts/reprice_catalog.py``:
    that script selects ONCE for its whole run and feeds this function chunks, so
    a card TCGdex 404s (and which therefore never gets a fresher
    ``last_synced_at``) is not re-fetched by every subsequent chunk. Nightly the
    retry is correct and free; inside one overnight run it would eat the budget.
    """
    lock_gen = new_ulid()
    try:
        repo.acquire_catalog_lock(lock_gen)
    except CatalogReseedInProgressError:
        logger.warning("catalog price cycle skipped: a catalog reseed holds "
                       "the catalog lock")
        return _catalog_summary(skipped="catalog reseed in flight")
    try:
        repo.set_catalog_generation(repo.current_catalog_generation())
        if card_ids is None:
            limit = (settings.catalog_refresh_cards_per_night
                     if cards_per_night is None else cards_per_night)
            card_ids = select_catalog_refresh_candidates(repo, limit=limit)
        else:
            card_ids = list(card_ids)
        result = _refresh_cards(
            repo, client, card_ids, today,
            request_delay_seconds=request_delay_seconds,
            max_consecutive_failures=max_consecutive_failures,
            label="catalog cycle",
            deadline=time.monotonic() + max_runtime_seconds,
        )
        logger.info("catalog cycle: %d candidates, %d updated, %d not found, "
                    "%d failures%s%s", len(card_ids), result["cards_updated"],
                    result["not_found"], result["failures"],
                    " (ABORTED)" if result["aborted"] else "",
                    " (RUNTIME CAP)" if result["runtime_exceeded"] else "")
        return _catalog_summary(candidates=len(card_ids), result=result)
    finally:
        # Same three as the depth pass, and for the same reasons: an unexpected
        # raise must not leave the lock held for its full hour-long TTL, must not
        # leave this process stamping later writes with a generation from a run
        # that never finished, and must not leave the API serving prices this
        # pass replaced.
        repo.set_catalog_generation(None)
        repo.release_catalog_lock(lock_gen)
        catalog_cache.invalidate()


def run_daily_sync(repo, client, today: date, *, pricing_provider=None) -> dict:
    """Run all sync steps in order and return their merged summary.

    The depth pass runs FIRST and the order is load-bearing (RFC 0003 §7):
    ``refresh_inventory_market_values`` denormalizes the catalog prices
    ``refresh_held_prices`` has just written, so the other order publishes
    yesterday's figures for a day and makes every new holding wait two runs for
    its first price.

    The graded pass (RFC 0009 T7) sits between them for exactly the same reason:
    it must land before ``snapshot_graded_prices`` reads the figures into
    history, and before the denormalization copies them onto the items.

    ``pricing_provider`` is injectable so tests never touch the network; left
    unset it is built from config. A missing key degrades to "no slabs priced
    tonight" and NOTHING else — the depth pass, both snapshots and the
    denormalization all still run. That is deliberate: the graded provider is
    the newest and least load-bearing of the four steps, and T8's checklist
    includes rotating both keys, so "no key right now" is a state this job will
    really meet.

    The weekly catalog cycle (T17) runs LAST, and that is the mirror image of
    the depth pass's argument: it prices cards we do NOT own, so it feeds no
    denormalizer and nothing downstream reads what it wrote. Putting a
    ~24-minute catalog walk anywhere earlier would delay publishing today's
    figures for the stock actually on the table.
    """
    summary = dict(refresh_held_prices(repo, client, today))

    provider = pricing_provider if pricing_provider is not None else build_pricing_provider()
    if provider is None:
        logger.warning("graded pricing skipped: no pricing provider is configured")
        summary.update(_no_pricing_provider_summary())
    else:
        summary.update(refresh_graded_prices(repo, provider))

    summary.update(snapshot_graded_prices(repo, today))
    summary.update(snapshot_sealed_prices(repo, today))
    summary["items_refreshed"] = refresh_inventory_market_values(repo)
    summary.update(refresh_catalog_prices(repo, client, today))
    return summary


def sync_new_sets(repo, client, *, dry_run: bool = False) -> dict:
    """Incremental catalog sync, dropping the API's catalog cache when it ends.

    Same wrapper shape as ``refresh_held_prices``: the run proper is
    ``_sync_new_sets`` below, which carries the contract. The invalidation is in
    a ``finally`` because a run that raises partway has still written the cards
    it got through, and a cache that survived that would hide them until its
    TTL expired.
    """
    try:
        return _sync_new_sets(repo, client, dry_run=dry_run)
    finally:
        catalog_cache.invalidate()


def _sync_new_sets(repo, client, *, dry_run: bool = False) -> dict:
    """Incremental catalog sync: seed identity rows for any set we hold none of.

    The "check for new sets" button/schedule (Round 3 Tasks 3.8/3.9). Distinct
    from BOTH catalog jobs this module already has: it is not the full-catalog
    breadth seed (``scripts/seed_catalog.py``, CLI-only, can rewrite ~31k rows)
    and not the depth pass (``refresh_held_prices``, prices only, for cards
    already held). This is the narrow case in between -- a new Pokemon set
    releases, we hold none of it yet, and its cards are entirely missing from
    the catalog -- so it is cheap and safe enough to run from a button or a
    monthly schedule with no dry-run rail.

    Reuses the exact breadth-pass building blocks ``seed_catalog.seed_language``
    uses, so an incrementally-added set has byte-identical row shape to one
    seeded by the full bootstrap: ``client.list_sets`` to enumerate sets,
    ``client.iter_brief_cards`` to walk a language's cards, and
    ``to_catalog_card_brief`` to map a list row into an identity-only
    (no-price) ``CatalogCard``. Prices are deliberately NOT fetched here --
    that is ``refresh_held_prices``' job once a card is actually held.

    A set counts as "new" when ``repo.list_cards_by_set`` on its composite id
    returns nothing. Any set with even one existing row is left alone
    entirely -- its cards are never walked, let alone written -- which is what
    makes "never overwrite an existing card row" a structural guarantee here
    rather than a promise resting on the writer. The writer underneath
    (``batch_upsert_catalog_cards(..., preserve_priced=True)``) is the same
    conditional-write path the breadth seed's ``flush()`` uses, kept as a
    second, independent layer of the same guarantee.

    ``dry_run`` counts what WOULD be written (``new_sets``, ``cards_added``)
    without calling the writer at all -- mirroring the breadth seed's own
    dry-run-by-default posture, even though this incremental path is safe
    enough to default to executing.

    Only ``list_sets`` for one language failing degrades that language to zero
    new sets found (logged, not raised) -- one struggling upstream endpoint
    must not abort the whole run when the other language is healthy.

    It also maintains the ``catalog_set`` REGISTRY (T8) -- one row per set, so
    ``GET /admin/catalog/sets`` can list every set in the catalog with a single
    query instead of the full-table scan that "read the set off 31,600 card
    rows" would require. This job is the natural writer because it already
    fetches the set list for both languages, so the registry costs no extra
    upstream request. Two properties of that write are load-bearing and both
    have tests:

    * **every set is registered, not just the new ones.** The registry describes
      the whole catalog, and this job's steady state is "nothing is new" -- a
      writer sitting after the ``missing_set_ids`` early-out would register
      nothing on almost every run.
    * ``card_count`` is **the rows WE hold**, never TCGdex's advertised
      ``cardCount.total``. 108 of TCGdex's 177 Japanese sets advertise a card
      count while carrying zero card rows (see ``scripts/seed_catalog.py``'s
      ``MIN_EXPECTED_RATIO_BY_LANGUAGE``), so the advertised figure would report
      a set as covered when our catalog has nothing in it at all -- the exact
      question the admin opens this dropdown to answer.
    """
    sets_checked = 0
    new_sets: list[str] = []
    cards_added = 0
    sets_registered = 0
    synced_at = datetime.now(timezone.utc)

    for language in Language:
        try:
            sets = client.list_sets(language)
        except Exception as exc:  # noqa: BLE001 - one language's outage must not sink the run
            logger.warning("catalog sync: set list unavailable for %s (%s: %s); "
                           "skipping", language, type(exc).__name__, exc)
            continue
        sets_checked += len(sets)

        missing_set_ids: set[str] = set()
        # Registry material, gathered from the membership check this loop was
        # already paying for: `list_cards_by_set` returns the set's rows, so the
        # count is a `len()` on a query we ran anyway.
        held_counts: dict[str, int] = {}
        names_by_composite: dict[str, str] = {}
        for raw_set in sets:
            raw_set_id = raw_set.get("id")
            if not raw_set_id:
                continue
            composite_set_id = build_card_id(language, raw_set_id)
            held = len(repo.list_cards_by_set(composite_set_id))
            held_counts[composite_set_id] = held
            names_by_composite[composite_set_id] = raw_set.get("name") or ""
            if not held:
                missing_set_ids.add(composite_set_id)

        added_by_set: dict[str, int] = {}
        if missing_set_ids:
            new_sets.extend(sorted(missing_set_ids))

            set_names = {s["id"]: s.get("name", "") for s in sets}
            buffer: list = []

            def flush():
                nonlocal buffer, cards_added
                if not buffer:
                    return
                cards_added += len(buffer)
                if not dry_run:
                    repo.batch_upsert_catalog_cards(buffer, preserve_priced=True)
                buffer = []

            for raw in client.iter_brief_cards(language):
                try:
                    card = to_catalog_card_brief(raw, language, set_names=set_names,
                                                 synced_at=synced_at)
                except Exception as exc:  # noqa: BLE001 - one bad row must not abort the run
                    logger.warning("catalog sync: skipped %r (%s: %s)",
                                   raw.get("id"), type(exc).__name__, exc)
                    continue
                if card.set_id not in missing_set_ids:
                    continue
                added_by_set[card.set_id] = added_by_set.get(card.set_id, 0) + 1
                buffer.append(card)
                if len(buffer) >= _NEW_SETS_BATCH_SIZE:
                    flush()
            flush()

        if not dry_run and held_counts:
            # Counted AFTER the walk, so a set seeded by this very run records
            # the cards it just gained rather than the zero it started at.
            sets_registered += repo.put_catalog_sets([
                {
                    "set_id": set_id,
                    "set_name": names_by_composite[set_id],
                    "language": language.value,
                    "card_count": held + added_by_set.get(set_id, 0),
                    "updated_at": synced_at.isoformat(),
                }
                for set_id, held in held_counts.items()
            ])

    return {"sets_checked": sets_checked, "new_sets": new_sets,
            "cards_added": cards_added, "sets_registered": sets_registered}
