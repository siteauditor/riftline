"""One Riot call per question, however many requests ask it at once.

A profile page sends its requests together (the profile, the games, the
analytics, the mastery), and each of them used to resolve the player on its
own: one view of a stale prerendered profile made 29 Riot calls on 2026-09-24,
six of them the same account and summoner lookups made twice or more.

``Flights`` puts one lock on each question while it is being asked. The first
request asks Riot; the others wait for it and then read what it stored. That is
the protocol ``LadderService`` uses for a ladder refresh: note when the wait
began, take the lock, read the row again, and accept an answer stamped after
that moment rather than asking a second time.

A lock lives only while a request holds it or waits for it, so the dict holds
the questions in flight and nothing else. The API runs one worker, so a
process-local dict is the whole mechanism.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from datetime import UTC, datetime


class _Flight:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        # Holders and waiters. The lock is dropped when the last one leaves.
        self.users = 0


class Flights:
    """Per-key locks that exist only while somebody holds or waits for one."""

    def __init__(self) -> None:
        self._flights: dict[Hashable, _Flight] = {}

    def __len__(self) -> int:
        return len(self._flights)

    @asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        flight = self._flights.get(key)
        if flight is None:
            flight = self._flights[key] = _Flight()
        flight.users += 1
        try:
            async with flight.lock:
                yield
        finally:
            # Reached by a holder, and by a waiter cancelled before it got the
            # lock, so a request that gave up cannot leave a lock behind.
            flight.users -= 1
            if flight.users == 0 and self._flights.get(key) is flight:
                del self._flights[key]

    def clear(self) -> None:
        """For tests, which must not inherit each other's locks."""
        self._flights.clear()


def stamped_since(stamp: datetime | None, moment: datetime) -> bool:
    """Whether a cache stamp was written at or after ``moment``.

    The waiter's half of the protocol: an answer stamped after the wait began
    was written by the request it waited for, whatever the TTL says. Without it
    a TTL of zero, as the tests run with, made every waiter ask again.
    """
    if stamp is None:
        return False
    if stamp.tzinfo is None:  # SQLite hands back naive datetimes
        stamp = stamp.replace(tzinfo=UTC)
    return stamp >= moment


class TtlCache[K: Hashable, V]:
    """A bounded process-local cache whose entries expire.

    The shape of the live page's mastery cache in ``live.py``: stamped with the
    monotonic clock, and the oldest fifth dropped when it is full, so it cannot
    grow for ever. The age limit is given on each read rather than fixed here,
    so a setting (and the tests, which zero every TTL) governs it.
    """

    def __init__(self, limit: int = 5000) -> None:
        self.limit = limit
        self._entries: dict[K, tuple[float, V]] = {}
        _caches.append(self)

    def __len__(self) -> int:
        return len(self._entries)

    def get(
        self, key: K, max_age: float, *, since: float | None = None
    ) -> tuple[bool, V | None]:
        """``(True, value)`` for an entry younger than ``max_age`` seconds, or
        put at or after ``since`` (a ``time.monotonic()`` reading).

        A pair, because ``None`` is a value worth caching: "no record on this
        shard" is an answer, not a miss. ``since`` is the waiter's half of the
        flight protocol, as ``stamped_since`` is for a stored row.
        """
        hit = self._entries.get(key)
        if hit is None:
            return False, None
        if since is not None and hit[0] >= since:
            return True, hit[1]
        if time.monotonic() - hit[0] >= max_age:
            self._entries.pop(key, None)
            return False, None
        return True, hit[1]

    def put(self, key: K, value: V) -> None:
        if key not in self._entries and len(self._entries) >= self.limit:
            by_age = sorted(self._entries, key=lambda k: self._entries[k][0])
            for stale in by_age[: max(1, self.limit // 5)]:
                self._entries.pop(stale, None)
        self._entries[key] = (time.monotonic(), value)

    def age(self, key: K) -> float | None:
        """Seconds since ``key`` was put, or None when it is not held."""
        hit = self._entries.get(key)
        return None if hit is None else time.monotonic() - hit[0]

    def pop(self, key: K) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()


_caches: list[TtlCache] = []

# One set of flights for every service in the process: the questions they ask
# of Riot overlap (a profile and a draft board both resolve a Riot ID).
flights = Flights()


def clear_all() -> None:
    """Forget every cached answer and lock. For tests."""
    flights.clear()
    for cache in _caches:
        cache.clear()


__all__ = ["Flights", "TtlCache", "clear_all", "flights", "stamped_since"]
