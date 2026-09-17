"""Classifying items, so a final inventory can be read as a build.

A participant's ``items`` array is six inventory slots plus a trinket. It is not
a build: the slots are wherever the player happened to leave things, and the
corpus proves it (the same boots turn up in all six slots at roughly equal
rates). What we *can* recover is which of the six are finished items, which are
boots, and therefore what the completed build was.

Deciding "is this a finished item" turns out to need six clauses, and every one
of them was added because it excluded something real. They are kept together
here, with the reason attached, so nobody quietly deletes one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Summoner's Rift. Data Dragon keys `maps` by id, as strings.
SUMMONERS_RIFT = "11"

# Cheapest legendary is comfortably above this; the most expensive epic is below.
LEGENDARY_GOLD_FLOOR = 2000


@dataclass(slots=True)
class ItemTaxonomy:
    """Item id -> what kind of item it is, derived from Data Dragon."""

    boots: set[int] = field(default_factory=set)
    legendary: set[int] = field(default_factory=set)
    trinkets: set[int] = field(default_factory=set)
    version: str | None = None

    def rebuild(self, items: dict[int, dict], version: str | None = None) -> None:
        self.boots.clear()
        self.legendary.clear()
        self.trinkets.clear()

        for item_id, item in items.items():
            tags = item.get("tags") or []
            gold = item.get("gold") or {}
            maps = item.get("maps") or {}
            name = item.get("name") or ""

            if "Trinket" in tags:
                self.trinkets.add(item_id)
                continue

            # Boots are terminal items but they are a slot of their own, so they
            # are classified before the legendary test rather than inside it.
            if "Boots" in tags and gold.get("purchasable"):
                self.boots.add(item_id)
                continue

            if (
                # Rift only: ARAM and Arena ship their own item pools, and mixing
                # them into a Summoner's Rift build list is nonsense.
                maps.get(SUMMONERS_RIFT)
                # Excludes items you cannot buy, e.g. quest transformations.
                and gold.get("purchasable")
                # A terminal item builds into nothing. Components do.
                and not (item.get("into") or [])
                # Separates legendaries from epics and components.
                and gold.get("total", 0) >= LEGENDARY_GOLD_FLOOR
                # Ornn's masterwork upgrades require Ornn on the team; they are
                # not a build choice anyone can make.
                and not item.get("requiredAlly")
                # Riot ships placeholder entries named "Legendary Mage Item" and
                # friends for modes that randomise items. They are not items.
                and "Legendary " not in name
            ):
                self.legendary.add(item_id)

        self.version = version
        log.info(
            "item taxonomy: %d legendary, %d boots, %d trinkets (patch %s)",
            len(self.legendary), len(self.boots), len(self.trinkets), version,
        )

    # ------------------------------------------------------------------ query

    def is_boots(self, item_id: int | None) -> bool:
        return bool(item_id) and item_id in self.boots

    def is_legendary(self, item_id: int | None) -> bool:
        return bool(item_id) and item_id in self.legendary

    def is_trinket(self, item_id: int | None) -> bool:
        return bool(item_id) and item_id in self.trinkets

    def classify(self, item_id: int | None) -> str:
        if not item_id:
            return "empty"
        if item_id in self.boots:
            return "boots"
        if item_id in self.trinkets:
            return "trinket"
        if item_id in self.legendary:
            return "legendary"
        return "other"

    def split_build(self, items: list[int] | None) -> tuple[list[int], int | None]:
        """Split a final inventory into (legendary items, boots).

        The six inventory slots only; the seventh is the trinket. Legendaries are
        returned **sorted**, because the slot order carries no meaning and two
        players with the same build must produce the same key.
        """
        if not items:
            return [], None
        slots = [i for i in items[:6] if i]
        cores = sorted(i for i in slots if self.is_legendary(i))
        boots = next((i for i in slots if self.is_boots(i)), None)
        return cores, boots


item_taxonomy = ItemTaxonomy()


def ensure_taxonomy(static) -> ItemTaxonomy:
    """Rebuild the taxonomy when the patch changes. Cheap and idempotent."""
    if item_taxonomy.version != static.version or not item_taxonomy.legendary:
        item_taxonomy.rebuild(static.items, static.version)
    return item_taxonomy
