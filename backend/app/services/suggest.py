"""Riot ID suggestions for the search box, from players we already hold.

Nothing here calls Riot. account-v1 is the only way to turn a typed name into an
account, each lookup costs one request, and a development key allows 100 per two
minutes: suggesting from Riot as somebody types would spend the whole budget on
one visitor spelling "Hide on bush". So suggestions come from the players table,
and the only names offered are ones Riot itself returned, from account-v1 on a
lookup or from match-v5 for a player seen in a stored game.

**Not the ``search_name`` column.** That column is the Riot ID cache key, and it
is left empty on purpose on rows created from match data, because a name read
from a stored game can be out of date and must never answer a lookup (see
``RankCache.ensure_players``). Measured on the local corpus on 2026-09-19: 439 of
3,626 rows carry one. A suggestion only fills in the search field, and the
profile lookup then goes through Riot, so suggestions can use every named row.
The names are folded here, in process, with the same ``normalize_riot_name``.
"""

from __future__ import annotations

import time
from bisect import bisect_left
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import epoch_ms, numeric_rank
from app.db.models import Player, RankedEntry
from app.riot.routing import UnknownPlatform, resolve_platform
from app.services.players import normalize_riot_name

# Rebuilt at most this often. A player looked up a minute ago is missing from the
# list until then, which costs nothing: whoever searched them has them in their
# own recent searches, which the browser keeps.
SUGGEST_TTL_SECONDS = 600
# One folded character matches a tenth of the table, which is noise, not help.
# A Hangul syllable folds to two or three jamo, so one Korean character passes.
MIN_QUERY_CHARS = 2
MAX_SUGGESTIONS = 8


@dataclass(frozen=True, slots=True)
class KnownPlayer:
    puuid: str
    game_name: str
    tag_line: str
    # Resolved, so a row stored under a merged shard (th2, ph2) links to the
    # shard those accounts live on now.
    platform: str
    platform_label: str
    profile_icon_id: int | None
    summoner_level: int | None
    tier: str | None
    division: str | None
    league_points: int | None
    # numeric_rank of the solo queue entry, 0 when unranked.
    rank: int
    folded: str
    tag_folded: str


@dataclass(frozen=True, slots=True)
class SuggestIndex:
    """Every named player, sorted by folded name so a prefix is one bisect."""

    players: list[KnownPlayer]
    keys: list[str]

    def suggest(
        self, query: str, platform: str | None = None, limit: int = MAX_SUGGESTIONS
    ) -> list[KnownPlayer]:
        # Split on the last "#", as the search form does. Everything before it
        # is the name and everything after is a prefix of the tag.
        if "#" in query:
            name, _, tag = query.rpartition("#")
        else:
            name, tag = query, ""
        key = normalize_riot_name(name)
        tag_key = tag.strip().casefold()
        if len(key) < MIN_QUERY_CHARS:
            return []

        hits = []
        for player in self.players[bisect_left(self.keys, key):]:
            if not player.folded.startswith(key):
                break
            if tag_key and not player.tag_folded.startswith(tag_key):
                continue
            hits.append(player)

        # The name typed in full first, then the region the visitor has
        # selected, then the highest rank: with a short prefix the list is
        # otherwise alphabetical noise, and a ranked player is the likelier
        # search.
        hits.sort(
            key=lambda p: (
                p.folded != key,
                p.platform != platform,
                -p.rank,
                p.folded,
                p.tag_folded,
            )
        )
        return hits[:limit]


_cache: tuple[float, SuggestIndex] | None = None


def clear_suggest_cache() -> None:
    """For tests, which share one database and add players between requests."""
    global _cache
    _cache = None


async def load_index(session: AsyncSession) -> SuggestIndex:
    """Every player with a Riot ID, rebuilt at most once per TTL per process."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < SUGGEST_TTL_SECONDS:
        return _cache[1]

    rows = (
        await session.execute(
            select(
                Player.puuid,
                Player.game_name,
                Player.tag_line,
                Player.platform,
                Player.profile_icon_id,
                Player.summoner_level,
                Player.account_fetched_at,
                RankedEntry.tier,
                RankedEntry.division,
                RankedEntry.league_points,
            )
            .outerjoin(
                RankedEntry,
                and_(
                    RankedEntry.puuid == Player.puuid,
                    RankedEntry.queue_type == "RANKED_SOLO_5x5",
                    # The home's rank only. A row stamped for another shard is
                    # not the rank of the region the suggestion links to; an
                    # unstamped one predates the stamps and was read there.
                    or_(
                        Player.league_platform.is_(None),
                        Player.league_platform == Player.platform,
                    ),
                ),
            )
            .where(Player.game_name.is_not(None), Player.tag_line.is_not(None))
        )
    ).all()

    # A rename can leave two rows holding one Riot ID: the account that owns it
    # now, and a stale row for the account that gave it up. Keep the one
    # account-v1 confirmed most recently, and a confirmed row over one whose
    # name was only read from a stored game. One suggestion per Riot ID, not
    # per shard: a Riot ID names one account, and its link is the home's.
    rows = sorted(rows, key=lambda r: epoch_ms(r.account_fetched_at) or 0, reverse=True)
    seen: set[tuple[str, str]] = set()
    players: list[KnownPlayer] = []
    for row in rows:
        try:
            platform = resolve_platform(row.platform)
        except UnknownPlatform:
            continue
        folded = normalize_riot_name(row.game_name)
        tag_folded = row.tag_line.strip().casefold()
        if not folded or (folded, tag_folded) in seen:
            continue
        seen.add((folded, tag_folded))
        players.append(
            KnownPlayer(
                puuid=row.puuid,
                game_name=row.game_name,
                tag_line=row.tag_line,
                platform=platform.id,
                platform_label=platform.label,
                profile_icon_id=row.profile_icon_id,
                summoner_level=row.summoner_level,
                tier=row.tier,
                division=row.division,
                league_points=row.league_points,
                rank=numeric_rank(row.tier, row.division, row.league_points or 0),
                folded=folded,
                tag_folded=tag_folded,
            )
        )

    players.sort(key=lambda p: p.folded)
    index = SuggestIndex(players=players, keys=[p.folded for p in players])
    _cache = (now, index)
    return index


__all__ = [
    "MAX_SUGGESTIONS",
    "MIN_QUERY_CHARS",
    "KnownPlayer",
    "SuggestIndex",
    "clear_suggest_cache",
    "load_index",
]
