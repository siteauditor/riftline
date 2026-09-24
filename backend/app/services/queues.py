"""Which queues a figure covers, in one vocabulary for every page.

A profile used to pool every queue into one set of numbers: one player read
62% and a 4.47 KDA over all their stored games, and 50% and 3.85 over the
ranked ones (2026-09-24). Ranked games, ARAM and Swiftplay are different
games, so each figure now names the queues it covers, and the profile opens
on ranked. The words are the URL's and the API's (`?scope=ranked`), and the
page's chips; `frontend/src/lib/profileScope.ts` holds the same list.
"""

from __future__ import annotations

from typing import Literal

QueueScope = Literal["ranked", "solo", "flex", "normal", "swiftplay", "aram", "all"]

# The queue ids behind each word. None is every queue, customs and all.
SCOPE_QUEUES: dict[str, frozenset[int] | None] = {
    "ranked": frozenset({420, 440}),
    "solo": frozenset({420}),
    "flex": frozenset({440}),
    # Draft, blind and quickplay.
    "normal": frozenset({400, 430, 490}),
    "swiftplay": frozenset({480}),
    # Howling Abyss and the ARAM: Mayhem variant.
    "aram": frozenset({450, 2400}),
    "all": None,
}

SCOPE_LABELS: dict[str, str] = {
    "ranked": "Ranked",
    "solo": "Ranked Solo/Duo",
    "flex": "Ranked Flex",
    "normal": "Normal",
    "swiftplay": "Swiftplay",
    "aram": "ARAM",
    "all": "All queues",
}

# Arena is offered on group pages only: Riot splits it across four queue ids,
# and a profile's history is paged by Riot, which filters by one.
ARENA_QUEUES = frozenset({1700, 1710, 1740, 1750})

# The one queue id Riot's history is asked for when a scope is a single queue
# or starts with one, and `type=ranked` for both ranked queues together.
# Riot's match list filters by one queue, or by a type.
LIVE_FILTER: dict[str, tuple[int | None, str | None]] = {
    "ranked": (None, "ranked"),
    "solo": (420, None),
    "flex": (440, None),
    "normal": (400, None),
    "swiftplay": (480, None),
    "aram": (450, None),
    "all": (None, None),
}


def scope_queues(scope: str) -> frozenset[int] | None:
    return SCOPE_QUEUES[scope]


__all__ = [
    "ARENA_QUEUES",
    "LIVE_FILTER",
    "SCOPE_LABELS",
    "SCOPE_QUEUES",
    "QueueScope",
    "scope_queues",
]
