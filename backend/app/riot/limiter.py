"""Rate limiting for the Riot API.

Riot enforces limits at two scopes at once, and a 429 from either counts against
the key's standing:

* **Application** limits apply to the key as a whole. A development key is
  ``20:1,100:120``: 20 requests per second, 100 per two minutes. The second
  window is the binding one, working out to 0.83 req/s sustained.
* **Method** limits apply per endpoint and differ between them. We do not
  hardcode these. Riot advertises them on every response via
  ``X-Method-Rate-Limit``, so we learn them from the first call and enforce them
  from then on.

The limiter is deliberately *proactive*. Spending a 429 to discover a limit is
not free -- Riot tracks violations and repeat offenders lose their keys -- so we
block locally before sending rather than apologising afterwards.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field

# Application limits for a Riot development key.
DEV_KEY_LIMITS: list[tuple[int, float]] = [(20, 1.0), (100, 120.0)]

# The moment, on the monotonic clock, after which the current caller would
# rather be told "not now" than keep waiting for a slot. Unset, a caller waits
# as long as the key needs, which is right for the ingest CLI. A web request
# sets it (see `RiotWaitBudget` in app/main.py), because the visitor is behind
# Cloudflare, which abandons an origin after 100 seconds: measured on
# 2026-09-22, a leaderboard page waited 102 to 108 seconds for the limiter
# while the key's two-minute budget refilled, which in production is a 524
# instead of a page.
wait_deadline: ContextVar[float | None] = ContextVar("riot_wait_deadline", default=None)


class WaitTooLong(Exception):
    """A slot would free only after the caller's deadline. Nothing was reserved."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"next slot in {retry_after:.1f}s, past the caller's deadline")
        self.retry_after = retry_after


def parse_limit_header(value: str | None) -> list[tuple[int, float]]:
    """Parse Riot's ``count:period,count:period`` limit syntax.

    ``"20:1,100:120"`` -> ``[(20, 1.0), (100, 120.0)]``. Malformed chunks are
    skipped rather than raising: a header we cannot read should degrade into
    "no extra limit learned", never into a failed request.
    """
    if not value:
        return []
    out: list[tuple[int, float]] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        count, _, period = chunk.partition(":")
        try:
            out.append((int(count), float(period)))
        except ValueError:
            continue
    return out


@dataclass(slots=True)
class SlidingWindow:
    """Counts hits in a rolling window of ``period`` seconds."""

    limit: int
    period: float
    hits: deque[float] = field(default_factory=deque)

    def prune(self, now: float) -> None:
        cutoff = now - self.period
        while self.hits and self.hits[0] <= cutoff:
            self.hits.popleft()

    def retry_after(self, now: float) -> float:
        """Seconds until a slot frees. 0.0 if one is available right now."""
        self.prune(now)
        if len(self.hits) < self.limit:
            return 0.0
        return max(0.0, self.hits[0] + self.period - now)

    def record(self, now: float) -> None:
        self.hits.append(now)

    def sync(self, observed: int, now: float) -> None:
        """Reconcile our count with Riot's own.

        Our count can sit below Riot's: another process may share the key, and
        Riot counts a request on arrival while we count on response. We only
        ever top *up*, never down, so drift resolves conservatively.

        The subtlety is *when* to place the hits we did not make. Riot reports
        how many requests the window holds but not their timestamps. Stacking
        them all at ``now`` is maximally pessimistic: it asserts the window only
        frees a full ``period`` from this instant, so a key that Riot reports as
        busy stalls the very next request for the entire window. Observed live:
        Riot returned ``x-app-rate-limit-count: 100:120`` alongside a 200, and
        this method turned that into a flat 120-second block.

        Spreading them evenly across the window is both closer to the truth and
        better behaved. The oldest synthetic hit sits at the far edge and ages
        out almost immediately, so instead of a cliff we throttle to the drip
        rate the remaining headroom actually supports (a full 100/120s window
        yields a 1.2s wait, which is exactly its sustainable pace).
        """
        self.prune(now)
        missing = observed - len(self.hits)
        if missing <= 0:
            return
        step = self.period / max(observed, 1)
        oldest = now - self.period
        synthetic = [oldest + step * (i + 1) for i in range(missing)]
        # hits must stay ascending: prune() pops from the left.
        self.hits = deque(sorted([*self.hits, *synthetic]))


class RateLimiter:
    """Shared, proactive limiter for a single API key.

    One instance per key, shared by every caller in the process. All mutation
    happens under a single lock; waiting happens outside it so a slow caller
    never blocks others from re-checking.
    """

    def __init__(self, app_limits: list[tuple[int, float]] | None = None) -> None:
        limits = app_limits or DEV_KEY_LIMITS
        self._app: list[SlidingWindow] = [SlidingWindow(c, p) for c, p in limits]
        self._method: dict[str, list[SlidingWindow]] = {}
        # Scope ("application" or a method key) -> monotonic deadline from a 429.
        self._penalty: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _windows_for(self, method_key: str) -> list[SlidingWindow]:
        return self._app + self._method.get(method_key, [])

    def _wait_for(self, now: float, method_key: str) -> float:
        """Longest cooldown across every limit that governs this method."""
        wait = 0.0
        for scope in ("application", method_key):
            deadline = self._penalty.get(scope)
            if deadline is None:
                continue
            if deadline <= now:
                self._penalty.pop(scope, None)
            else:
                wait = max(wait, deadline - now)
        for window in self._windows_for(method_key):
            wait = max(wait, window.retry_after(now))
        return wait

    async def acquire(self, method_key: str) -> None:
        """Block until a request to ``method_key`` may be sent, then reserve a slot.

        Raises :class:`WaitTooLong` instead of sleeping when the slot would
        free after the caller's ``wait_deadline``. Checked on every pass, so a
        wait that starts inside the deadline and is then lengthened by a 429
        penalty gives up rather than overrunning it.
        """
        while True:
            async with self._lock:
                now = time.monotonic()
                wait = self._wait_for(now, method_key)
                if wait <= 0.0:
                    for window in self._windows_for(method_key):
                        window.record(now)
                    return
            deadline = wait_deadline.get()
            if deadline is not None and now + wait > deadline:
                raise WaitTooLong(wait)
            # Cap the nap so a long penalty still re-checks periodically, and so
            # a window that frees early is noticed promptly.
            await asyncio.sleep(min(wait, 5.0))

    async def observe(self, method_key: str, headers: Mapping[str, str]) -> None:
        """Learn method limits and resync counters from a response's headers."""
        method_limits = parse_limit_header(headers.get("X-Method-Rate-Limit"))
        async with self._lock:
            now = time.monotonic()
            if method_limits:
                existing = self._method.get(method_key)
                shape = [(w.limit, w.period) for w in existing] if existing else None
                # Riot occasionally retunes a method's limits; rebuild on change.
                if shape != method_limits:
                    self._method[method_key] = [
                        SlidingWindow(c, p) for c, p in method_limits
                    ]
            self._sync(self._app, headers.get("X-App-Rate-Limit-Count"), now)
            self._sync(
                self._method.get(method_key),
                headers.get("X-Method-Rate-Limit-Count"),
                now,
            )

    @staticmethod
    def _sync(
        windows: list[SlidingWindow] | None, header: str | None, now: float
    ) -> None:
        if not windows or not header:
            return
        counts = {period: count for count, period in parse_limit_header(header)}
        for window in windows:
            observed = counts.get(window.period)
            if observed is not None:
                window.sync(observed, now)

    async def penalize(self, scope: str, retry_after: float) -> None:
        """Honour a 429. ``scope`` is ``"application"`` or the method key."""
        async with self._lock:
            deadline = time.monotonic() + max(0.0, retry_after)
            self._penalty[scope] = max(self._penalty.get(scope, 0.0), deadline)

    def spare(self) -> int:
        """Free slots in the longest application window right now.

        The long window is the binding one on a development key (100 per two
        minutes against 20 per second), and the short one empties within a
        second, so reading it too would report a busy key during every burst.
        Counts include what Riot reported for other processes on the key.
        """
        now = time.monotonic()
        longest = max(self._app, key=lambda w: w.period, default=None)
        if longest is None:
            return 0
        longest.prune(now)
        return max(0, longest.limit - len(longest.hits))

    def snapshot(self) -> dict:
        """Current utilisation, for /health and the UI's rate-budget meter."""
        now = time.monotonic()
        for window in self._app:
            window.prune(now)
        return {
            "app": [
                {"used": len(w.hits), "limit": w.limit, "period": w.period}
                for w in self._app
            ],
            "methods_tracked": len(self._method),
            "penalties": {
                scope: round(max(0.0, deadline - now), 2)
                for scope, deadline in self._penalty.items()
                if deadline > now
            },
        }
