"""Static game data from Data Dragon.

Champions, items, runes, summoner spells and queue names. Data Dragon is a plain
CDN: no API key, no rate limit, and entirely separate from the Riot API budget,
so this is the one place we can be generous with requests.

Two details worth knowing:

* ``champion.json`` is keyed by the champion's *identifier* ("MonkeyKing"), while
  every Riot API response uses the numeric ``key`` (62). We index both, because
  mixing them up is the usual cause of missing champion icons.
* Riot ships new champions to the live API slightly before Data Dragon catches
  up, so every lookup degrades to a placeholder instead of raising.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.db.base import PROJECT_ROOT

log = logging.getLogger(__name__)

DDRAGON = "https://ddragon.leagueoflegends.com"
# Community Dragon serves the centred splash crop and square tiles that Data
# Dragon does not. Verified reachable 2026-09-17.
CDRAGON = "https://cdn.communitydragon.org/latest"
QUEUES_URL = "https://static.developer.riotgames.com/docs/lol/queues.json"
# Riot's own queues.json stopped being updated years ago: it has nothing for
# Swiftplay (480), Bravery Arena (1740) or Arena 3x6 (1750), so those games read
# as "Queue 1740" in a match list. Community Dragon extracts the client's live
# queue table, which names them. Measured 2026-09-18: Riot's file knows 0 of
# those three, Community Dragon knows all three.
CDRAGON_QUEUES_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data"
    "/global/default/v1/queues.json"
)
CACHE_DIR = PROJECT_ROOT / "data" / "static"
# How long to serve stale data before retrying a CDN that just failed.
RETRY_AFTER_FAILURE = 60.0


@dataclass(slots=True)
class Champion:
    id: int
    key: str           # "MonkeyKing" -- the Data Dragon identifier
    name: str          # "Wukong" -- what players call them
    title: str
    tags: list[str] = field(default_factory=list)
    partype: str = ""


class StaticDataService:
    """Loads and caches Data Dragon assets, with a disk fallback."""

    def __init__(self, *, ttl: int = 21_600, locale: str = "en_US") -> None:
        self.ttl = ttl
        self.locale = locale
        self.version: str | None = None
        self.champions_by_id: dict[int, Champion] = {}
        self.champions_by_key: dict[str, Champion] = {}
        self.items: dict[int, dict] = {}
        self.summoner_spells: dict[int, dict] = {}
        self.runes: list[dict] = []
        self.rune_index: dict[int, dict] = {}
        self.queues: dict[int, dict] = {}
        # queue id -> the client's own name, from Community Dragon.
        self.queue_names: dict[int, str] = {}
        self._loaded_at: float = 0.0
        # Set after a failed refresh so we stop hammering a CDN that is down.
        self._retry_not_before: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ state

    @property
    def is_stale(self) -> bool:
        if not self.version:
            return True  # nothing to serve; we have to try
        if time.time() < self._retry_not_before:
            # A refresh failed recently. Keep serving what we have rather than
            # paying the HTTP timeout again on this request.
            return False
        return (time.time() - self._loaded_at) > self.ttl

    @property
    def cdn(self) -> str:
        return f"{DDRAGON}/cdn/{self.version}"

    async def ensure_loaded(self) -> None:
        if not self.is_stale:
            return
        async with self._lock:
            if not self.is_stale:  # another caller won the race
                return
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001
                # Never fail a request over static data. Champion names and
                # icons degrade to placeholders, which beats a 500 on every
                # page for as long as the CDN is unreachable.
                self._retry_not_before = time.time() + RETRY_AFTER_FAILURE
                log.warning(
                    "static data unavailable (%s); serving placeholders, retrying in %ds",
                    exc,
                    int(RETRY_AFTER_FAILURE),
                )

    # ---------------------------------------------------------------- loading

    async def refresh(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                versions = await self._get_json(http, f"{DDRAGON}/api/versions.json")
                # Held locally until every fetch lands. Publishing the new
                # version early would point asset URLs at a patch whose champion
                # index we had not loaded yet.
                version = versions[0]
                base = f"{DDRAGON}/cdn/{version}/data/{self.locale}"
                champions, items, spells, runes, queues, live_queues = (
                    await asyncio.gather(
                        self._get_json(http, f"{base}/champion.json"),
                        self._get_json(http, f"{base}/item.json"),
                        self._get_json(http, f"{base}/summoner.json"),
                        self._get_json(http, f"{base}/runesReforged.json"),
                        self._get_json(http, QUEUES_URL),
                        # Optional: a name is a nicety, and Community Dragon
                        # being down must not cost us champions and items.
                        self._get_json(http, CDRAGON_QUEUES_URL, optional=True),
                    )
                )
            self.version = version
            self._index(champions, items, spells, runes, queues, live_queues)
            self._save_disk_cache(champions, items, spells, runes, queues, live_queues)
            self._loaded_at = time.time()
            self._retry_not_before = 0.0
            log.info("Data Dragon %s loaded", version)
        except Exception as exc:  # noqa: BLE001 -- any failure falls back to disk
            # Back off before the next network attempt. _load_disk_cache leaves
            # _loaded_at alone on purpose, so without this every single request
            # would pay the full HTTP timeout while the CDN is down.
            self._retry_not_before = time.time() + RETRY_AFTER_FAILURE
            log.warning("Data Dragon refresh failed (%s); falling back to disk", exc)
            if not self._load_disk_cache():
                raise

    @staticmethod
    async def _get_json(
        http: httpx.AsyncClient, url: str, *, optional: bool = False
    ) -> Any:
        try:
            response = await http.get(url)
            response.raise_for_status()
            return response.json()
        except Exception:
            if not optional:
                raise
            log.warning("optional static source unavailable: %s", url)
            return None

    def _index(
        self,
        champions: dict,
        items: dict,
        spells: dict,
        runes: list,
        queues: list,
        live_queues: Any = None,
    ) -> None:
        self.champions_by_id.clear()
        self.champions_by_key.clear()
        for key, c in (champions.get("data") or {}).items():
            champ = Champion(
                id=int(c["key"]),
                key=key,
                name=c.get("name", key),
                title=c.get("title", ""),
                tags=list(c.get("tags") or []),
                partype=c.get("partype", ""),
            )
            self.champions_by_id[champ.id] = champ
            self.champions_by_key[key] = champ

        self.items = {
            int(k): v for k, v in (items.get("data") or {}).items() if k.isdigit()
        }
        self.summoner_spells = {
            int(v["key"]): v for v in (spells.get("data") or {}).values() if v.get("key")
        }
        self.runes = runes or []
        self.rune_index = {}
        for tree in self.runes:
            self.rune_index[tree["id"]] = tree
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    self.rune_index[rune["id"]] = rune

        self.queues = {q["queueId"]: q for q in (queues or []) if "queueId" in q}

        # Community Dragon ships this as a list in some builds and as an
        # id-keyed object in others, so read whichever arrived.
        rows = live_queues.values() if isinstance(live_queues, dict) else live_queues
        self.queue_names = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            queue_id, name = row.get("id"), (row.get("name") or "").strip()
            if isinstance(queue_id, int) and name:
                self.queue_names[queue_id] = name

    # ------------------------------------------------------------ disk cache

    def _save_disk_cache(self, *payloads: Any) -> None:
        names = ("champion", "item", "summoner", "runes", "queues", "live_queues")
        try:
            (CACHE_DIR / "version.txt").write_text(self.version or "", encoding="utf-8")
            for name, payload in zip(names, payloads, strict=True):
                (CACHE_DIR / f"{name}.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
        except OSError as exc:
            log.warning("Could not write static cache: %s", exc)

    def _load_disk_cache(self) -> bool:
        try:
            version = (CACHE_DIR / "version.txt").read_text(encoding="utf-8").strip()
            payloads = [
                json.loads((CACHE_DIR / f"{n}.json").read_text(encoding="utf-8"))
                for n in ("champion", "item", "summoner", "runes", "queues")
            ]
        except (OSError, ValueError):
            return False
        # Written since this file was first cached, so a cache from an older
        # build simply has no queue names rather than failing to load at all.
        try:
            payloads.append(
                json.loads((CACHE_DIR / "live_queues.json").read_text(encoding="utf-8"))
            )
        except (OSError, ValueError):
            payloads.append(None)
        self.version = version or self.version
        self._index(*payloads)
        # Deliberately not updating _loaded_at: stale data should keep retrying
        # the network on the next request rather than settle for the cache.
        log.info("Loaded static data from disk cache (version %s)", self.version)
        return True

    # ----------------------------------------------------------- public lookup

    def champion(self, champion_id: int | None) -> Champion | None:
        if champion_id is None:
            return None
        return self.champions_by_id.get(int(champion_id))

    def champion_name(self, champion_id: int | None) -> str:
        champ = self.champion(champion_id)
        return champ.name if champ else f"Champion {champion_id}"

    def champion_icon(self, champion_id: int | None) -> str | None:
        champ = self.champion(champion_id)
        return f"{self.cdn}/img/champion/{champ.key}.png" if champ else None

    def champion_art(self, champion_id: int | None) -> str | None:
        """Splash art cropped so the champion is centred.

        Data Dragon's own splash is composed for the client's skin carousel, so
        the character sits off to one side and a banner crop decapitates half
        the roster. Community Dragon serves the centred cut, which is the one
        that survives being used as a background.
        """
        champ = self.champion(champion_id)
        return (
            f"{CDRAGON}/champion/{champ.id}/splash-art/centered" if champ else None
        )

    def champion_tile(self, champion_id: int | None, skin: int | None = None) -> str | None:
        """Square key art, for cards that want more than a 48px icon.

        ``skin`` is the skin number, which spectator reports per player as
        ``lastSelectedSkinIndex``: the live tab shows the skin each player is
        actually wearing rather than the base art. Community Dragon serves
        ``/tile/skin/{n}`` for every skin number (checked on skin 47, 2026-09-19).
        """
        champ = self.champion(champion_id)
        if not champ:
            return None
        base = f"{CDRAGON}/champion/{champ.id}/tile"
        return f"{base}/skin/{skin}" if skin else base

    def champion_splash(self, champion_id: int | None, skin: int = 0) -> str | None:
        champ = self.champion(champion_id)
        return (
            f"{DDRAGON}/cdn/img/champion/splash/{champ.key}_{skin}.jpg"
            if champ
            else None
        )

    def item_icon(self, item_id: int | None) -> str | None:
        if not item_id:  # 0 means "empty slot"
            return None
        return f"{self.cdn}/img/item/{item_id}.png"

    def item_name(self, item_id: int | None) -> str | None:
        item = self.items.get(int(item_id)) if item_id else None
        return item.get("name") if item else None

    def spell_icon(self, spell_id: int | None) -> str | None:
        spell = self.summoner_spells.get(int(spell_id)) if spell_id else None
        return f"{self.cdn}/img/spell/{spell['id']}.png" if spell else None

    def spell_name(self, spell_id: int | None) -> str | None:
        spell = self.summoner_spells.get(int(spell_id)) if spell_id else None
        return spell.get("name") if spell else None

    def rune_icon(self, rune_id: int | None) -> str | None:
        rune = self.rune_index.get(int(rune_id)) if rune_id else None
        # Rune icon paths are version-independent and live at the CDN root.
        return f"{DDRAGON}/cdn/img/{rune['icon']}" if rune and rune.get("icon") else None

    def profile_icon(self, icon_id: int | None) -> str | None:
        return f"{self.cdn}/img/profileicon/{icon_id}.png" if icon_id is not None else None

    def queue_name(self, queue_id: int | None) -> str:
        """Human label for a queue, e.g. 420 -> 'Ranked Solo/Duo'.

        Three sources, best first: our own labels for the queues players talk
        about daily, then the client's live table, then Riot's frozen
        queues.json. A numeric id only survives when no source names it, which
        is honest: inventing a name for an unlisted queue would be worse.
        """
        if queue_id is None:
            return "Unknown"
        friendly = _FRIENDLY_QUEUES.get(queue_id)
        if friendly:
            return friendly
        live = self.queue_names.get(queue_id)
        if live:
            return live
        queue = self.queues.get(queue_id)
        if not queue:
            return f"Queue {queue_id}"
        # Riot writes these as "5v5 Ranked Solo games" and, in newer rows,
        # "Swiftplay Games". Case-insensitively, the suffix is noise either way.
        description = (queue.get("description") or "").strip()
        if description.lower().endswith(" games"):
            description = description[: -len(" games")].strip()
        return description or queue.get("map") or f"Queue {queue_id}"

    def all_champions(self) -> list[Champion]:
        return sorted(self.champions_by_id.values(), key=lambda c: c.name)


# Riot's own queue descriptions are inconsistent ("5v5 Ranked Solo games"), so
# the queues players actually care about get hand-written labels.
_FRIENDLY_QUEUES: dict[int, str] = {
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    450: "ARAM",
    490: "Quickplay",
    700: "Clash",
    720: "ARAM Clash",
    830: "Co-op vs AI (Intro)",
    840: "Co-op vs AI (Beginner)",
    850: "Co-op vs AI (Intermediate)",
    900: "ARURF",
    1020: "One for All",
    1300: "Nexus Blitz",
    1400: "Ultimate Spellbook",
    1700: "Arena",
    1710: "Arena",
    1900: "URF",
}

static_data = StaticDataService()
