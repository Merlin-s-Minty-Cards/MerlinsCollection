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
Under a sustained DB brownout a failed recompute serves last-known-good and
opens a short error-backoff window (``_CACHE_ERROR_BACKOFF_SECONDS``), so the
failing scan is retried at most once per window — not once per request — and
recovery is automatic once a scan succeeds. The lock is acquired with a bounded
timeout so a hung scan can never wedge callers indefinitely.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from threading import Lock
from typing import Callable, TypeVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
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

# On a compute (DynamoDB scan) FAILURE while a last-known-good value exists, keep
# serving that stale value for this long before re-attempting a scan. This turns a
# sustained brownout into ONE failed scan per backoff window instead of one per
# request. It is short relative to the TTL, so recovery lags the DB healing by at
# most this window, and the data is already allowed to be _CACHE_TTL_SECONDS stale.
_CACHE_ERROR_BACKOFF_SECONDS = 30.0

# Max time to wait for the single-flight lock before giving up. A scan that hangs
# while holding the lock must not wedge every other caller of this endpoint
# indefinitely: past this bound we serve last-known-good (or fail 503) instead of
# blocking. Comfortably longer than a healthy scan, shorter than "forever".
_CACHE_LOCK_TIMEOUT_SECONDS = 10.0

# Fixed back-off hint on the 503 we raise when the lock can't be acquired and no
# cached value exists, so a client backs off instead of hammering a wedged path.
_CACHE_UNAVAILABLE_RETRY_AFTER = 5

# The business (and its customers) are in US/Pacific. Production runs on UTC, so
# "today" MUST be computed in the business timezone or a same-day show misfiles as
# "past" for the last ~7-8h of every show day.
_BUSINESS_TZ = ZoneInfo("America/Los_Angeles")

# next/image only renders images from hosts allowlisted in next.config.ts. An
# image on any other host — or a non-https / malformed URL — throws inside
# next/image at SSR and 500s the whole home page, so a non-conforming card must
# never become a FeaturedCard. Keep this in lockstep with next.config.ts.
#
# ``assets.tcgdex.net`` is the host every reseeded card carries: the TCGdex
# mapper (``services/tcgdex.py``) DROPS an image on any other host, so it is the
# only one the current catalog can produce. It was missing here while
# next.config.ts already allowed it, which put the two out of the lockstep this
# comment demands and emptied the featured strip for every card in the reseeded
# catalog. ``images.pokemontcg.io`` is retained only for rows predating the
# reseed; drop it once no stored card carries such a URL (same note as
# next.config.ts).
_ALLOWED_IMAGE_HOSTS = frozenset({"assets.tcgdex.net", "images.pokemontcg.io"})

T = TypeVar("T")


class _TTLCache:
    """Single-flight, serve-stale-on-error memo of one value for ``ttl`` seconds.

    ``compute`` runs UNDER the lock, so a concurrent burst in a cold/just-expired
    window coalesces to exactly one call (the rest wait, then read the fresh
    value) — thundering-herd suppression.

    SERVE-STALE WITH BACKOFF: if ``compute`` raises and a previous value exists,
    that last-known-good value is served AND an error-backoff window is opened
    (``error_backoff`` seconds). While that window is open, subsequent calls keep
    serving the stale value WITHOUT re-running ``compute`` — so a sustained
    DynamoDB brownout costs one failed scan per window, not one per request. Once
    the window elapses a call retries ``compute``; a success refreshes the value
    and clears the backoff (automatic recovery). A first-call failure with NO
    prior value still propagates — a value that never existed is never served.

    BOUNDED LOCKING: the single-flight lock is acquired with a ``lock_timeout``.
    If a scan hangs while holding the lock, a new caller does not block forever —
    past the timeout it serves last-known-good if present, else raises a 503. The
    fallback reads ``self._value`` without the lock, which is safe under CPython's
    GIL because the reference is only ever REPLACED, never mutated in place.
    """

    def __init__(
        self,
        ttl: float,
        *,
        error_backoff: float = _CACHE_ERROR_BACKOFF_SECONDS,
        lock_timeout: float = _CACHE_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._ttl = ttl
        self._error_backoff = error_backoff
        self._lock_timeout = lock_timeout
        self._lock = Lock()
        self._at: float | None = None
        self._value: object | None = None
        # Monotonic instant before which a failed recompute keeps serving stale
        # (the error-backoff window); ``None`` when not in backoff.
        self._retry_at: float | None = None

    def get_or_compute(self, compute: Callable[[], T]) -> T:
        if not self._lock.acquire(timeout=self._lock_timeout):
            # A prior scan is wedged holding the lock. Serve last-known-good rather
            # than block this (and every other) caller indefinitely; if we have
            # nothing cached, fail cleanly with a 503 instead of hanging.
            cached = self._value
            if cached is not None:
                return cached  # type: ignore[return-value]
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="This resource is temporarily unavailable; please retry shortly.",
                headers={"Retry-After": str(_CACHE_UNAVAILABLE_RETRY_AFTER)},
            )
        try:
            now = time.monotonic()
            # Fresh value within the TTL: serve it.
            if self._value is not None and self._at is not None and now - self._at < self._ttl:
                return self._value  # type: ignore[return-value]
            # Inside an error-backoff window: serve stale without re-scanning.
            if self._value is not None and self._retry_at is not None and now < self._retry_at:
                return self._value  # type: ignore[return-value]
            try:
                value = compute()
            except Exception:
                if self._value is not None:
                    # Open/renew the backoff window so the next request serves stale
                    # instead of re-running the failing scan immediately.
                    self._retry_at = time.monotonic() + self._error_backoff
                    return self._value  # type: ignore[return-value]
                raise
            self._at = time.monotonic()
            self._value = value
            self._retry_at = None  # a good recompute clears any backoff
            return value
        finally:
            self._lock.release()

    def clear(self) -> None:
        with self._lock:
            self._at = None
            self._value = None
            self._retry_at = None


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
