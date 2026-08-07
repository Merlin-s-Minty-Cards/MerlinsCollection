"""In-process cache of the full catalog card list (RFC 0008 T9).

``GET /admin/market/search`` has no index on card name, so a name search has to
read every catalog row and filter in Python. Measured against the live table
that is 11.7 MB over 12 sequential 1 MB scan pages -- **11.2 seconds, on every
request**, which the Buy page fires on a 300ms keystroke debounce. The catalog
only changes when a sync runs, so the fix is to read it once and keep it.

Why a process-local cache and not a name GSI: DynamoDB cannot substring-match,
so a ``begins_with`` index would find ``Pikachu`` for ``"pika"`` but never
``Surfing Pikachu``. Keeping the rows in memory keeps the substring search the
admin already relies on. The deployment is single-worker (see the
``_SYNC_STATUS`` comment in ``routers/admin/market.py``), so one process-local
copy is coherent.

**Sizing.** 31,603 parsed ``CatalogCard`` objects measure **~93 MB** resident.
Do not confuse this with the 11.7 MB the table occupies on the wire -- parsed
pydantic models cost roughly 8x their serialized form. Anything that grows the
catalog grows this proportionally, so check the container's memory limit before
assuming there is headroom.

The cache is only safe because of the three rules below. They are not
defensive extras; each one is the difference between a performance fix and a
silent correctness bug.

**1. A stale catalog must expire on its own.** ``TTL_SECONDS`` bounds how long
a write this process did not make -- ``scripts/seed_catalog.py`` runs in a
SEPARATE process and cannot call ``invalidate()`` -- can stay invisible.

**2. An empty scan is never stored.** Otherwise the owner seeds 31k cards and
still watches Buy find nothing until the TTL expires, which looks exactly like
the bug they just fixed. An empty table also scans fast, so re-reading it costs
almost nothing.

**3. A scan that straddles an invalidation is discarded.** A search that starts
its 11-second read before a sync and finishes after it would otherwise write
pre-sync rows back with a *fresh* timestamp, undoing the sync for a full TTL.
``_generation`` catches that: the filler captures it before reading and stores
only if it still matches.

Callers get the internal list back, not a copy -- copying 31k objects per
request is the cost this module exists to remove. **Nothing may mutate the
returned list or the cards in it.**
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: How long a cached catalog is served before it is re-read. Sized for the one
#: writer this process cannot hear about: the out-of-process catalog seed.
TTL_SECONDS = 900

# Two locks with two different jobs, and the order between them is fixed:
# `_fill_lock` is always the outer one. Nothing acquires `_fill_lock` while
# holding `_state_lock`, so there is no cycle to deadlock on.
#
# `_fill_lock` is held across the whole scan, deliberately. Twelve concurrent
# keystroke requests against a cold cache should cost one 11-second scan that
# they all wait on, not twelve of them run at once.
_fill_lock = threading.Lock()
# `_state_lock` guards the three variables below and is held for microseconds
# only -- never across a scan, and never across a call that could block.
_state_lock = threading.Lock()

_cards: list | None = None
_stored_at: float | None = None
_generation: int = 0


def invalidate() -> None:
    """Drop the cached catalog. Safe to call from any thread, never blocks.

    Called at the end of every sync that can write catalog rows. It bumps
    ``_generation`` as well as clearing the rows so that a scan already in
    flight cannot come back and undo this.
    """
    global _cards, _stored_at, _generation
    with _state_lock:
        _cards = None
        _stored_at = None
        _generation += 1


def get_catalog_cards(loader: Callable[[], list[T]]) -> list[T]:
    """Return every catalog card, reading through ``loader`` on a cache miss.

    ``loader`` is the expensive full-table scan (in practice
    ``repo.list_all_catalog_cards``). Taking it as an argument keeps this module
    free of any repository import, and lets tests count exactly how many scans a
    sequence of searches costs.

    A ``loader`` that raises propagates untouched and leaves the cache alone --
    a DynamoDB timeout must surface as a failed request, never as a cached
    empty catalog.
    """
    cached = _read_fresh()
    if cached is not None:
        return cached

    with _fill_lock:
        # Whoever held the lock ahead of us has just finished a scan; take it
        # rather than running a second identical one.
        cached = _read_fresh()
        if cached is not None:
            return cached

        with _state_lock:
            generation = _generation

        # Free the expired copy BEFORE building its replacement. Holding both
        # at once would peak at roughly double the ~93 MB steady state, in a
        # container sized for one. Safe to drop: it is past its TTL, so it
        # would not have been served anyway.
        _release_expired()

        started = time.perf_counter()
        cards = loader()
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("catalog cache: scanned %d cards in %.0f ms", len(cards), elapsed_ms)

        _store(cards, generation)
        return cards


def _read_fresh() -> list | None:
    """The cached rows, or ``None`` if absent or past their TTL."""
    with _state_lock:
        if _cards is None or _stored_at is None:
            return None
        if time.monotonic() - _stored_at > TTL_SECONDS:
            # `monotonic`, not `time.time`: an NTP correction must not be able
            # to extend a stale catalog's life or expire a fresh one early.
            return None
        return _cards


def _release_expired() -> None:
    """Drop the cached rows without bumping the generation.

    Deliberately NOT ``invalidate()``: this is a filler reclaiming memory it is
    about to replace, not a writer announcing the catalog changed. Bumping the
    generation here would make the fill discard its own result and re-scan
    forever.
    """
    global _cards, _stored_at
    with _state_lock:
        _cards = None
        _stored_at = None


def _store(cards: list, generation: int) -> None:
    """Store a completed scan, unless rule 2 or rule 3 above says otherwise."""
    global _cards, _stored_at

    if not cards:
        logger.info("catalog cache: empty scan not cached")
        return

    with _state_lock:
        if generation != _generation:
            logger.info(
                "catalog cache: discarding a scan that straddled an invalidation"
            )
            return
        _cards = cards
        _stored_at = time.monotonic()
