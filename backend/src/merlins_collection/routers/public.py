"""``/public`` router — the two UNAUTHENTICATED read endpoints.

This router exists so "these routes are intentionally unauthenticated" is legible
in one place (auth posture is a router-level property) and so the allowlist
response models live next to the router that owns them. Both endpoints expose
ONLY safe fields via purpose-built response models — the internal ``Show`` /
inventory figures are not present in the model at all, so a field added upstream
later can never leak here.

Both endpoints fan out over the whole inventory / show list, and they are the
anonymous abuse surface, so they are defended in depth: a per-IP rate cap
(``rate_limit_public``) blunts a burst before it reaches the body, and a
single-flight in-process TTL cache (``_TTLCache``) coalesces a *concurrent*
burst in a cold/just-expired window to ONE DynamoDB scan, serving the
last-known-good value to a request whose recompute fails. In the happy path
the cache is per-process and clears on restart — worst case is one scan per
instance per TTL window, and data is at most ``_CACHE_TTL_SECONDS`` stale.
That guarantee does NOT extend to a sustained DB brownout: a failed recompute
leaves the cache's timestamp unset, so the next request (and every request
after it, one at a time behind the lock — never a concurrent storm) retries
the scan immediately, with no backoff, until one succeeds.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Callable, TypeVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.rate_limit import rate_limit_public

# ``customer_visible_items`` is the ONE shared cohort predicate (available
# raw/graded) — a security boundary imported from the inventory router rather
# than re-implemented, so the anonymous public surface can never drift from the
# authenticated search surface.
from merlins_collection.routers.inventory import customer_visible_items
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/public", tags=["public"])

_CACHE_TTL_SECONDS = 300.0

# The business (and its customers) are in US/Pacific. Production runs on UTC, so
# "today" MUST be computed in the business timezone or a same-day show misfiles as
# "past" for the last ~7-8h of every show day.
_BUSINESS_TZ = ZoneInfo("America/Los_Angeles")

# next/image only renders images from hosts allowlisted in next.config.ts. An
# image on any other host — or a non-https / malformed URL — throws inside
# next/image at SSR and 500s the whole home page, so a non-conforming card must
# never become a FeaturedCard. Keep this in lockstep with next.config.ts.
_ALLOWED_IMAGE_HOSTS = frozenset({"images.pokemontcg.io"})

T = TypeVar("T")


class _TTLCache:
    """Single-flight, serve-stale-on-error memo of one value for ``ttl`` seconds.

    ``compute`` runs UNDER the lock, so a concurrent burst in a cold/just-expired
    window coalesces to exactly one call (the rest wait, then read the fresh
    value) — this is thundering-herd suppression, not brownout protection. If
    ``compute`` raises and a previous value exists, that last-known-good value is
    served for THIS call, but the cached timestamp is left unset, so the very
    next call (and every one after it, still one at a time behind the lock) will
    retry ``compute`` immediately. There is no backoff: a sustained upstream
    failure is re-scanned on every request until it recovers, just serialized
    rather than concurrent.
    """

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._lock = Lock()
        self._at: float | None = None
        self._value: object | None = None
        self._has_value = False

    def get_or_compute(self, compute: Callable[[], T]) -> T:
        with self._lock:
            now = time.monotonic()
            if self._has_value and self._at is not None and now - self._at < self._ttl:
                return self._value  # type: ignore[return-value]
            try:
                value = compute()
            except Exception:
                if self._has_value:
                    return self._value  # type: ignore[return-value]
                raise
            self._at = time.monotonic()
            self._value = value
            self._has_value = True
            return value

    def clear(self) -> None:
        with self._lock:
            self._at = None
            self._value = None
            self._has_value = False


_shows_cache = _TTLCache(_CACHE_TTL_SECONDS)
_featured_cache = _TTLCache(_CACHE_TTL_SECONDS)


def reset_caches() -> None:
    """Drop both cached responses (used by tests; harmless at runtime)."""
    _shows_cache.clear()
    _featured_cache.clear()


def _business_today() -> date:
    """Today's date in the business's Pacific timezone (not the server clock)."""
    return datetime.now(tz=_BUSINESS_TZ).date()


def _is_safe_image_url(url: str | None) -> bool:
    """True only for an ``https://`` URL on an allowlisted image host."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_IMAGE_HOSTS


# ---- /public/shows ----

class PublicShow(BaseModel):
    """A show as the public site sees it — name, date, and optional location only."""

    name: str
    date: date
    venue: str | None = None
    city: str | None = None


class PublicShowsResponse(BaseModel):
    upcoming: list[PublicShow]
    past: list[PublicShow]


def _compute_shows(repo: InventoryRepository) -> PublicShowsResponse:
    today = _business_today()
    upcoming: list[PublicShow] = []
    past: list[PublicShow] = []
    for show in repo.list_shows():
        entry = PublicShow(name=show.name, date=show.date,
                           venue=show.venue, city=show.city)
        # A show dated today counts as upcoming (boundary decision, RFC 0002).
        (upcoming if show.date >= today else past).append(entry)
    upcoming.sort(key=lambda s: s.date)              # ascending: next show first
    past.sort(key=lambda s: s.date, reverse=True)    # descending: most recent first
    return PublicShowsResponse(upcoming=upcoming, past=past)


@router.get("/shows", response_model=PublicShowsResponse)
def public_shows(
    _cap: None = Depends(rate_limit_public),
    repo: InventoryRepository = Depends(get_repo),
) -> PublicShowsResponse:
    """All shows, split into upcoming/past by the business's current (Pacific) date."""
    return _shows_cache.get_or_compute(lambda: _compute_shows(repo))


# ---- /public/featured-cards ----

class FeaturedCard(BaseModel):
    """A featured card for the homepage — display name + image URL only."""

    name: str
    image_url: str


class FeaturedCardsResponse(BaseModel):
    cards: list[FeaturedCard]


def _market_first(item) -> Decimal:
    """Ranking value: current market value, else listed price, else 0.

    Null-coalescing (not falsy-``or``) so a genuine 0.00 market value is honoured
    rather than skipped. This is market-FIRST by design (RFC 0002) — the opposite
    of the customer search's listed-first ``_price`` helper; do not "correct" it.
    """
    if item.current_market_value is not None:
        return item.current_market_value
    if item.listed_price is not None:
        return item.listed_price
    return Decimal(0)


def _compute_featured(repo: InventoryRepository) -> FeaturedCardsResponse:
    items = customer_visible_items(repo)
    card_ids = {i.card_id for i in items if getattr(i, "card_id", None)}
    catalog = repo.batch_get_catalog_cards(card_ids) if card_ids else {}

    # Keep only items that resolve to a catalog card whose image is a safe URL
    # (https on an allowlisted host — anything else would crash next/image).
    qualifying = []
    for item in items:
        card = catalog.get(getattr(item, "card_id", None))
        if card is not None and _is_safe_image_url(card.images.small):
            qualifying.append((item, card))

    # Rank market-value desc, tie-broken by card_id for a stable, deterministic
    # order across the 300s recompute (negate the Decimal so both keys sort with
    # a single non-reversed sort).
    qualifying.sort(key=lambda pair: (-_market_first(pair[0]), pair[1].card_id))

    # De-duplicate by card_id (a vendor holding several copies of one card must
    # not fill the strip with it), keeping the highest-ranked copy; then take 5.
    seen: set[str] = set()
    cards: list[FeaturedCard] = []
    for _item, card in qualifying:
        if card.card_id in seen:
            continue
        seen.add(card.card_id)
        cards.append(FeaturedCard(name=card.name, image_url=card.images.small))
        if len(cards) == 5:
            break
    return FeaturedCardsResponse(cards=cards)


@router.get("/featured-cards", response_model=FeaturedCardsResponse)
def public_featured_cards(
    _cap: None = Depends(rate_limit_public),
    repo: InventoryRepository = Depends(get_repo),
) -> FeaturedCardsResponse:
    """Top 5 distinct available customer-visible cards that have a safe catalog image."""
    return _featured_cache.get_or_compute(lambda: _compute_featured(repo))
