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
import contextlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
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
# Every skin and the chromas under it. Spectator reports a player wearing a
# chroma by the chroma's own number, and a chroma has no art of its own, so
# this is what maps it back to the skin it recolours. It is also the skin
# catalogue, and the only honest one: Data Dragon lists chromas as skins, so
# Ahri has 95 "skins" there and 21 here (9,120 against 2,116 across the 173
# champions, measured 2026-09-21), and 74 of those 95 have no art to show.
CDRAGON_SKINS_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data"
    "/global/default/v1/skins.json"
)
# Skin line names. skins.json carries only a line's id, and a gallery grouped
# under "line 12" says nothing. 27 KB, 229 lines (measured 2026-09-21).
CDRAGON_SKINLINES_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data"
    "/global/default/v1/skinlines.json"
)
CACHE_DIR = PROJECT_ROOT / "data" / "static"
# How long to serve stale data before retrying a CDN that just failed.
RETRY_AFTER_FAILURE = 60.0

# Data Dragon writes a global ability as a range of 25000 or more (33 of them,
# plus one 4294967295, measured 2026-09-21): a sentinel, not a distance.
GLOBAL_RANGE = 25_000

# The roster size below which "zero on every champion" proves nothing.
MIN_ROSTER_FOR_GROWTH_CHECK = 20

# Community Dragon's rarity enum, in words. "kNoRarity" (836 of 2,155 skins,
# most of them base skins and the older price tiers) has no word on purpose.
_RARITY = {
    "kRare": "Rare",
    "kEpic": "Epic",
    "kLegendary": "Legendary",
    "kMythic": "Mythic",
    "kUltimate": "Ultimate",
    "kExalted": "Exalted",
    "kTranscendent": "Transcendent",
}

_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class Champion:
    id: int
    key: str           # "MonkeyKing" -- the Data Dragon identifier
    name: str          # "Wukong" -- what players call them
    title: str
    tags: list[str] = field(default_factory=list)
    partype: str = ""
    # The three below come from champion.json, which is required, so a champion
    # page keeps its ratings and base stats when championFull.json fails.
    blurb: str = ""
    # Riot's own 0 to 10 ratings: attack, defense, magic, difficulty.
    info: dict[str, int] = field(default_factory=dict)
    # Level 1 values and their growth per level, under Data Dragon's own names
    # ("hp", "hpperlevel", "attackrange" and so on, 20 in all).
    stats: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Ability:
    # "P" for the passive, then "Q", "W", "E", "R".
    slot: str
    name: str
    # Plain text. Riot's markup is taken out on the way in; see `_plain`.
    description: str
    # Data Dragon's file name, e.g. "AhriQ.png".
    image: str
    cooldown: str | None = None
    cost: str | None = None
    range: str | None = None


@dataclass(slots=True)
class ChampionLore:
    """What championFull.json adds: the story, the tips, and the abilities."""

    lore: str
    ally_tips: list[str] = field(default_factory=list)
    enemy_tips: list[str] = field(default_factory=list)
    passive: Ability | None = None
    spells: list[Ability] = field(default_factory=list)


@dataclass(slots=True)
class Skin:
    # Champion * 1000 + skin number, as Riot writes it.
    id: int
    num: int
    name: str
    rarity: str | None = None
    legacy: bool = False
    # Skin line ids, first one first. Names come from `skin_line_name`.
    lines: list[int] = field(default_factory=list)
    description: str | None = None
    chromas: int = 0


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
        # chroma id -> the id of the skin it recolours, from Community Dragon.
        # Ids are champion * 1000 + skin number, as Riot writes them.
        self.chroma_parent: dict[int, int] = {}
        # champion id -> lore, tips and abilities, from championFull.json.
        self.lore_by_id: dict[int, ChampionLore] = {}
        # champion id -> every skin, base first, from Community Dragon.
        self.skins_by_champion: dict[int, list[Skin]] = {}
        # skin line id -> its name.
        self.skin_lines: dict[int, str] = {}
        # Growth fields Data Dragon ships as zero for the whole roster.
        self.unpublished_growth: set[str] = set()
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
                (
                    champions,
                    items,
                    spells,
                    runes,
                    queues,
                    live_queues,
                    skins,
                    skin_lines,
                    full,
                ) = await asyncio.gather(
                    self._get_json(http, f"{base}/champion.json"),
                    self._get_json(http, f"{base}/item.json"),
                    self._get_json(http, f"{base}/summoner.json"),
                    self._get_json(http, f"{base}/runesReforged.json"),
                    self._get_json(http, QUEUES_URL),
                    # Optional: a name is a nicety, and Community Dragon
                    # being down must not cost us champions and items.
                    self._get_json(http, CDRAGON_QUEUES_URL, optional=True),
                    # Optional for the same reason. Without it a chroma
                    # shows the champion's base art instead of its skin's
                    # (the page falls back on a failed image by itself).
                    self._get_json(http, CDRAGON_SKINS_URL, optional=True),
                    self._get_json(http, CDRAGON_SKINLINES_URL, optional=True),
                    # 0.41 MB gzipped for all 173 champions (measured
                    # 2026-09-21). Optional because champion.json already
                    # carries everything a page cannot do without.
                    self._get_json(http, f"{base}/championFull.json", optional=True),
                )
            self.version = version
            self._index(champions, items, spells, runes, queues, live_queues)
            self._save_disk_cache(champions, items, spells, runes, queues, live_queues)
            # Each optional source falls back to its own last known copy, so
            # Community Dragon or one Data Dragon file being down costs only
            # what that file adds.
            if skins:
                self._index_chromas(skins)
                self._index_skins(skins)
                self._save_chroma_cache()
                self._save_skin_cache()
            else:
                if not self.chroma_parent:
                    self._load_chroma_cache()
                if not self.skins_by_champion:
                    self._load_skin_cache()
            if skin_lines:
                self._index_skin_lines(skin_lines)
                self._save_skin_line_cache()
            elif not self.skin_lines:
                self._load_skin_line_cache()
            if full:
                self._index_lore(full)
                self._save_lore_cache()
            elif not self.lore_by_id:
                self._load_lore_cache()
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
                blurb=_plain(c.get("blurb")),
                info={
                    k: int(v) for k, v in (c.get("info") or {}).items()
                    if isinstance(v, (int, float))
                },
                stats={
                    k: float(v) for k, v in (c.get("stats") or {}).items()
                    if isinstance(v, (int, float))
                },
            )
            self.champions_by_id[champ.id] = champ
            self.champions_by_key[key] = champ

        # A growth figure that is zero on every champion is missing, not zero.
        # Data Dragon 16.18.1 gives `attackdamageperlevel: 0` for all 173
        # (measured 2026-09-21), which would print every champion's level 18
        # attack damage as its level 1 value. Real zeros are never roster wide:
        # one champion has no armor growth and 28 have no mana. Only judged on
        # a full roster, so a one-champion fixture is not "all champions".
        roster = list(self.champions_by_id.values())
        growth = {k for c in roster for k in c.stats if k.endswith("perlevel")}
        self.unpublished_growth = (
            {k for k in growth if all(not c.stats.get(k) for c in roster)}
            if len(roster) >= MIN_ROSTER_FOR_GROWTH_CHECK
            else set()
        )

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

    def _index_chromas(self, skins: Any) -> None:
        """Map every chroma to the skin it recolours.

        A player wearing a chroma is reported by the chroma's own number:
        ``lastSelectedSkinIndex`` 23 on Jayce is "Resistance Jayce (Obsidian)",
        a chroma of skin 15. Community Dragon has no tile for a chroma and
        answers 404, which the live tab rendered as a broken image with the
        champion's name in it. The parent skin is the right picture: a chroma
        is that skin recoloured.
        """
        rows = skins.values() if isinstance(skins, dict) else (skins or [])
        mapping: dict[int, int] = {}
        for skin in rows:
            parent = skin.get("id") if isinstance(skin, dict) else None
            if not isinstance(parent, int):
                continue
            for chroma in skin.get("chromas") or []:
                if isinstance(chroma, dict) and isinstance(chroma.get("id"), int):
                    mapping[chroma["id"]] = parent
        # An empty result is a malformed file, not "no chromas exist": keep
        # the map we had rather than forget every chroma at once.
        if mapping:
            self.chroma_parent = mapping

    def _save_chroma_cache(self) -> None:
        try:
            (CACHE_DIR / "chromas.json").write_text(
                json.dumps(self.chroma_parent), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("Could not write the chroma cache: %s", exc)

    def _load_chroma_cache(self) -> None:
        # JSON object keys are strings, so they come back as strings.
        try:
            raw = json.loads((CACHE_DIR / "chromas.json").read_text(encoding="utf-8"))
            self.chroma_parent = {int(k): int(v) for k, v in raw.items()}
        except (OSError, ValueError, AttributeError):
            pass

    def _index_skins(self, skins: Any) -> None:
        """Every skin, grouped by champion, base skin first.

        Read from Community Dragon rather than Data Dragon because Data Dragon
        lists each chroma as a skin of its own. A chroma is counted on the skin
        it recolours instead, which is what the chroma map above already knows.
        """
        rows = skins.values() if isinstance(skins, dict) else (skins or [])
        catalogue: dict[int, list[Skin]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                continue
            skin_id = row["id"]
            rarity = row.get("rarity") or ""
            catalogue.setdefault(skin_id // 1000, []).append(
                Skin(
                    id=skin_id,
                    num=skin_id % 1000,
                    name=(row.get("name") or "").strip(),
                    # An enum we have not met yet still gets a word, minus the
                    # "k" prefix, rather than silently reading as no rarity.
                    rarity=_RARITY.get(rarity)
                    or (rarity[1:] if rarity.startswith("k") and rarity != "kNoRarity" else None),
                    legacy=bool(row.get("isLegacy")),
                    lines=[
                        line["id"]
                        for line in row.get("skinLines") or []
                        if isinstance(line, dict) and isinstance(line.get("id"), int)
                    ],
                    description=_plain(row.get("description")) or None,
                    chromas=len(row.get("chromas") or []),
                )
            )
        for champion_skins in catalogue.values():
            champion_skins.sort(key=lambda s: s.num)
        # Same rule as the chroma map: an empty parse is a broken file.
        if catalogue:
            self.skins_by_champion = catalogue

    def _save_skin_cache(self) -> None:
        self._write_cache(
            "skin_catalogue.json",
            {k: [asdict(s) for s in v] for k, v in self.skins_by_champion.items()},
        )

    def _load_skin_cache(self) -> None:
        raw = self._read_cache("skin_catalogue.json")
        try:
            loaded = {int(k): [Skin(**s) for s in v] for k, v in (raw or {}).items()}
        except (TypeError, ValueError, AttributeError):
            return
        if loaded:
            self.skins_by_champion = loaded

    def _index_skin_lines(self, lines: Any) -> None:
        rows = lines.values() if isinstance(lines, dict) else (lines or [])
        names = {
            row["id"]: row["name"].strip()
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            # Line 0 is Community Dragon's empty placeholder.
            and (row.get("name") or "").strip()
        }
        if names:
            self.skin_lines = names

    def _save_skin_line_cache(self) -> None:
        self._write_cache("skin_lines.json", self.skin_lines)

    def _load_skin_line_cache(self) -> None:
        raw = self._read_cache("skin_lines.json")
        with contextlib.suppress(TypeError, ValueError, AttributeError):
            self.skin_lines = {int(k): str(v) for k, v in (raw or {}).items()} or self.skin_lines

    def _index_lore(self, full: Any) -> None:
        """Lore, tips and abilities for every champion in championFull.json.

        Trimmed to what a page draws on the way in: 1.20 MB held rather than
        the file's 2.12 MB (measured 2026-09-21).
        """
        data = full.get("data") if isinstance(full, dict) else None
        lore: dict[int, ChampionLore] = {}
        for champion in (data or {}).values():
            if not isinstance(champion, dict):
                continue
            try:
                champion_id = int(champion["key"])
            except (KeyError, TypeError, ValueError):
                continue
            partype = champion.get("partype") or ""
            passive = champion.get("passive") or {}
            lore[champion_id] = ChampionLore(
                lore=_plain(champion.get("lore")),
                ally_tips=[_plain(t) for t in champion.get("allytips") or [] if t],
                enemy_tips=[_plain(t) for t in champion.get("enemytips") or [] if t],
                passive=(
                    Ability(
                        slot="P",
                        name=passive.get("name") or "",
                        description=_plain(passive.get("description")),
                        image=(passive.get("image") or {}).get("full") or "",
                    )
                    if passive.get("name")
                    else None
                ),
                spells=[
                    Ability(
                        slot=slot,
                        name=spell.get("name") or "",
                        description=_plain(spell.get("description")),
                        image=(spell.get("image") or {}).get("full") or "",
                        cooldown=_burn(spell.get("cooldownBurn")),
                        cost=_ability_cost(spell, partype),
                        range=_ability_range(spell.get("rangeBurn")),
                    )
                    for slot, spell in zip("QWER", champion.get("spells") or [], strict=False)
                    if isinstance(spell, dict)
                ],
            )
        if lore:
            self.lore_by_id = lore

    def _save_lore_cache(self) -> None:
        self._write_cache(
            "champion_detail.json", {k: asdict(v) for k, v in self.lore_by_id.items()}
        )

    def _load_lore_cache(self) -> None:
        raw = self._read_cache("champion_detail.json")
        loaded: dict[int, ChampionLore] = {}
        try:
            for key, value in (raw or {}).items():
                passive = value.get("passive")
                loaded[int(key)] = ChampionLore(
                    lore=value.get("lore") or "",
                    ally_tips=list(value.get("ally_tips") or []),
                    enemy_tips=list(value.get("enemy_tips") or []),
                    passive=Ability(**passive) if passive else None,
                    spells=[Ability(**s) for s in value.get("spells") or []],
                )
        except (TypeError, ValueError, AttributeError):
            return
        if loaded:
            self.lore_by_id = loaded

    @staticmethod
    def _write_cache(name: str, payload: Any) -> None:
        try:
            (CACHE_DIR / name).write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write the %s cache: %s", name, exc)

    @staticmethod
    def _read_cache(name: str) -> Any:
        try:
            return json.loads((CACHE_DIR / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

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
        self._load_chroma_cache()
        self._load_skin_cache()
        self._load_skin_line_cache()
        self._load_lore_cache()
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
        if skin:
            # A chroma has no art of its own; show the skin it recolours.
            parent = self.chroma_parent.get(champ.id * 1000 + skin)
            if parent is not None:
                skin = parent % 1000
        base = f"{CDRAGON}/champion/{champ.id}/tile"
        return f"{base}/skin/{skin}" if skin else base

    def champion_splash(self, champion_id: int | None, skin: int = 0) -> str | None:
        champ = self.champion(champion_id)
        return (
            f"{DDRAGON}/cdn/img/champion/splash/{champ.key}_{skin}.jpg"
            if champ
            else None
        )

    def champion_skin_splash(self, champion_id: int | None, skin: int = 0) -> str | None:
        """One skin's splash, centred for the reason `champion_art` gives.

        Only for real skin numbers: a chroma has no splash and answers 404
        (tile 95 on Ahri, checked 2026-09-21), which is why the catalogue never
        lists one.
        """
        champ = self.champion(champion_id)
        if not champ:
            return None
        base = f"{CDRAGON}/champion/{champ.id}/splash-art/centered"
        return f"{base}/skin/{skin}" if skin else base

    def champion_lore(self, champion_id: int | None) -> ChampionLore | None:
        if champion_id is None:
            return None
        return self.lore_by_id.get(int(champion_id))

    def champion_skins(self, champion_id: int | None) -> list[Skin]:
        if champion_id is None:
            return []
        return self.skins_by_champion.get(int(champion_id), [])

    def skin_line_name(self, line_id: int | None) -> str | None:
        return self.skin_lines.get(line_id) if line_id is not None else None

    def champion_ability(self, champion_id: int | None, slot: int) -> Ability | None:
        """Ability 1 to 4 (Q, W, E, R), which is how skill orders number them."""
        lore = self.champion_lore(champion_id)
        if not lore or not 1 <= slot <= len(lore.spells):
            return None
        return lore.spells[slot - 1]

    def ability_icon(self, ability: Ability | None) -> str | None:
        if not ability or not ability.image:
            return None
        # The passive's art lives in its own folder; Q to R share the summoner
        # spell folder, which is how Data Dragon lays both out.
        folder = "passive" if ability.slot == "P" else "spell"
        return f"{self.cdn}/img/{folder}/{ability.image}"

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


def _plain(text: str | None) -> str:
    """Riot's text with its markup taken out.

    93 ability descriptions and 40 passives carry tags (measured 2026-09-21):
    229 line breaks, 94 ``<font color>`` and a dozen of Riot's own such as
    ``<keywordMajor>`` and ``<status>``. None of them carries a ``{{ }}``
    placeholder, which is why ``description`` is read and ``tooltip`` never
    is. Breaks become newlines and every other tag goes, so a page renders text
    and never Riot's HTML.
    """
    if not text:
        return ""
    text = _TAG.sub("", _BREAK.sub("\n", text))
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _burn(value: Any) -> str | None:
    """A per rank figure as Data Dragon writes it ("10/9/8/7/6"), or None for 0."""
    text = str(value or "").strip()
    return None if text in ("", "0") else text


def _ability_cost(spell: dict, partype: str) -> str | None:
    """What an ability costs, in words, or None where it cannot be said.

    556 of 692 abilities write their cost as the template ``{{ cost }}
    {{ abilityresourcename }}``, which is ``costBurn`` in the champion's own
    resource. 93 say they are free. The rest are written against variables this
    file does not carry (``{{ hpcost*100 }}% of current Health``), and are
    withheld rather than printed half filled.
    """
    resource = (spell.get("resource") or "").strip()
    if resource.lower() == "no cost":
        return "No cost"
    if not resource or resource.lower() == "passive":
        return None
    if "{{" not in resource:
        return resource  # "Generates 1 Ferocity"
    cost = _burn(spell.get("costBurn"))
    if cost is None:
        return None
    # Six champions have no resource at all ("None") and one an empty one;
    # "50 None" would be worse than nothing.
    name = partype if partype not in ("", "None") else ""
    filled = resource.replace("{{ cost }}", cost).replace("{{ abilityresourcename }}", name)
    filled = " ".join(filled.split())
    return None if "{{" in filled or (filled == cost and not name) else filled


def _ability_range(value: Any) -> str | None:
    text = _burn(value)
    if text is None or text.lower() == "self":
        return None
    if text.isdigit() and int(text) >= GLOBAL_RANGE:
        return "Global"
    return text


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
