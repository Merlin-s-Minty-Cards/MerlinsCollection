"""Outbound call budgets for the slab providers (RFC 0009).

Two windows, for two different reasons:

``DailyQuota`` is a HARD budget. The pricing vendor's free tier is 100 credits a
day and a graded lookup costs **2** — measured, not read off the docs
(spike-findings §2.1) — so the real ceiling is **50 slab lookups a day**. Worse,
**you are billed on ``limit``, not on hits**: T0's very first probe used
``limit=2``, matched zero cards, and was still charged 4 credits. That is why the
check has to happen BEFORE the socket opens; a guard that reads the response has
already spent the money it was meant to protect.

``MinuteWindow`` is a PACER, not a budget. The vendor allows 60 calls a minute,
which no interactive path can reach — but T7's nightly refresh loops, and a loop
is exactly the shape that walks into a per-minute ceiling. It blocks rather than
raising, because the caller's honest response to "you are going too fast" is to
go slower, not to fail.

**Both windows are per-process and in-memory**, which is deliberate and worth
being explicit about: the daily budget is not shared across ECS tasks, so two
tasks each believe they have the full allowance. That is acceptable here and
nowhere near acceptable for the app's user-facing limits — those live in
``rate_limit.py`` and are DynamoDB-backed for exactly this reason. The
difference is the consequence: overshooting here means the vendor returns 429
and a nightly refresh finishes tomorrow instead of tonight, while overshooting
there means unmetered Bedrock spend. When the refresh becomes a scheduled job
with real concurrency (T7), revisit this.

The counter self-corrects anyway: the vendor reports the truth in
``x-ratelimit-daily-remaining`` on every response, and ``DailyQuota.sync`` folds
that back in, so a process that drifted low is pulled back to reality on its
next successful call.
"""

from __future__ import annotations

import threading
import time
from collections import deque


def _epoch_day(now: float) -> int:
    """The UTC day number. The vendor resets on a fixed epoch-day boundary
    (``x-ratelimit-daily-reset`` is midnight UTC), so this mirrors it rather
    than tracking a rolling 24 hours."""
    return int(now // 86_400)


class QuotaExceeded(RuntimeError):
    """The daily budget is spent. Raised BEFORE any HTTP call is attempted."""


class DailyQuota:
    """A per-day spend counter, keyed ``<key>:<epoch-day>``.

    ``key`` is the counter's name without the day suffix (e.g.
    ``"outbound:pricing"``); the day is appended by ``window_key`` so a new
    budget is minted at UTC midnight without anyone having to reset anything.
    Separate providers pass separate keys so a spent pricing budget never
    silently blocks a cert lookup, or the reverse.
    """

    def __init__(self, limit: int, key: str):
        self.limit = limit
        self.key = key
        self._lock = threading.Lock()
        self._day = _epoch_day(time.time())
        self._spent = 0

    @property
    def window_key(self) -> str:
        return f"{self.key}:{self._day}"

    @property
    def spent(self) -> int:
        with self._lock:
            self._roll(time.time())
            return self._spent

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def _roll(self, now: float) -> None:
        """Reset the counter if the UTC day has turned. Caller holds the lock."""
        day = _epoch_day(now)
        if day != self._day:
            self._day = day
            self._spent = 0

    def check(self, cost: int) -> None:
        """Raise ``QuotaExceeded`` if ``cost`` would overrun today's budget.

        Deliberately does NOT reserve the cost — ``record`` does that, after the
        call. A failed request that never reached the vendor was never billed,
        and a budget that debits itself for connection errors would strand a
        night's refresh over a flaky DNS lookup.
        """
        with self._lock:
            self._roll(time.time())
            if self._spent + cost > self.limit:
                raise QuotaExceeded(
                    f"{self.window_key}: {self._spent}/{self.limit} spent; "
                    f"a {cost}-credit call would overrun today's budget"
                )

    def record(self, cost: int) -> None:
        """Debit ``cost`` credits against today's budget."""
        with self._lock:
            self._roll(time.time())
            self._spent += cost

    def sync(self, remaining: int | None, limit: int | None = None) -> None:
        """Fold the vendor's own accounting back into the counter.

        The vendor is the authority — it knows about calls this process did not
        make. Only ever moves the counter UP (i.e. toward less remaining): a
        vendor figure that looks more generous than our own is far more likely
        to be a stale cached header than a refund.
        """
        if remaining is None:
            return
        with self._lock:
            self._roll(time.time())
            if limit is not None and limit > 0:
                self.limit = limit
            self._spent = max(self._spent, self.limit - max(0, remaining))


class MinuteWindow:
    """A sliding one-minute pacer. Blocks; never raises.

    Per-instance, so a fresh client starts with an empty window — which is what
    keeps the test suite from sleeping. A long-lived client (the nightly job)
    accumulates and paces itself.
    """

    def __init__(self, limit: int, *, sleep=time.sleep, clock=time.monotonic):
        self.limit = limit
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = clock

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._hits and now - self._hits[0] >= 60.0:
                    self._hits.popleft()
                if len(self._hits) < self.limit:
                    self._hits.append(now)
                    return
                wait = 60.0 - (now - self._hits[0])
            # Slept OUTSIDE the lock: holding it would serialize every other
            # caller behind the one that happened to fill the window.
            self._sleep(max(wait, 0.01))
