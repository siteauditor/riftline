"""The game a player is in right now, and who is in it with them.

Built on ``spectator-v5``, which Riot announced it would deactivate in October
2025 over player anonymity. It still answers as of 2026-09-17, so this exists;
it is gated behind ``ENABLE_SPECTATOR`` and kept a leaf of the dependency graph
so that the day it goes dark costs one route and one tab, nothing else.

**Roughly a third of a lobby cannot be identified.** Riot's anonymity option
means those participants come back with no ``puuid`` at all, and with ``riotId``
set to the champion's own name -- "Sivir", "Camille" -- which is a placeholder,
not a name. Measured across three live games: 5 of 10, 9 of 10, 7 of 10
identified. Without a PUUID there is no rank lookup and no profile link, so this
module carries the distinction all the way to the caller rather than quietly
dropping those rows or, worse, rendering a champion name as a person.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.db.models import RankedEntry
from app.riot.client import RiotClient
from app.riot.errors import RiotForbidden
from app.riot.routing import Platform, resolve_platform
from app.services.ranks import RankCache

log = logging.getLogger(__name__)

# Which ranked queue a game's rank should be read from. Anything else (ARAM,
# normals, Arena) has no rank of its own, so solo queue is shown and flagged.
# Defined once in schemas and re-exported, so the live view, the stored-match
# badge and the backfill cannot disagree about what counts as ranked.
from app.api.schemas import RANKED_QUEUE_BY_ID  # noqa: E402

DEFAULT_QUEUE = "RANKED_SOLO_5x5"

# Below this many identified players the lobby rank is withheld entirely.
# Six of ten is already a thin sample; four is a number that would mislead.
# Defined in schemas so the stored-match badge applies the identical rule.
from app.api.schemas import MIN_RANKED_FOR_LOBBY_RANK as MIN_RANKED_FOR_AVERAGE  # noqa: E402

ParticipantState = Literal["ranked", "unranked", "hidden", "bot", "unknown"]

APEX_TIER_NAMES = ("MASTER", "GRANDMASTER", "CHALLENGER")


def rank_points(entry: RankedEntry) -> int:
    from app.api.schemas import numeric_rank

    return numeric_rank(entry.tier, entry.division, entry.league_points)


def median_entry(entries: Sequence[RankedEntry]) -> RankedEntry:
    """The middle player by rank, biased low on an even count.

    Deliberately a real player rather than an interpolated midpoint: an
    interpolated value between, say, Diamond I and Master lands in the gap
    between two tiers and decodes to whichever side the arithmetic falls on,
    which is a rank nobody in the lobby holds.
    """
    ordered = sorted(entries, key=rank_points)
    return ordered[(len(ordered) - 1) // 2]


@dataclass(slots=True)
class LiveParticipant:
    puuid: str | None
    champion_id: int
    team_id: int
    spell1_id: int | None
    spell2_id: int | None
    keystone_id: int | None
    secondary_style_id: int | None
    profile_icon_id: int | None
    # None whenever the player is hidden. Never the champion name Riot puts in
    # `riotId` for them: rendering that would invent a person, and linking it
    # would produce a profile URL that 404s.
    game_name: str | None
    tag_line: str | None
    state: ParticipantState
    rank: RankedEntry | None = None


@dataclass(slots=True)
class LobbyRank:
    """The lobby's rank, always carrying the sample it was taken over.

    **The median, not the mean, and the difference is not academic.**
    ``numeric_rank`` is an ordinal scale with wildly unequal steps: one point
    separates Diamond I from Master, and six thousand separate Master from
    Grandmaster. A mean over that is not a rank. Nine Gold IV players and one
    Challenger average out to "Diamond III", and five Gold players with one
    Challenger average to "Master" -- and a smurf in a low-elo game is precisely
    the case anybody looks at this number for.

    The median is the rank of an actual player in the lobby, so the label is
    always something somebody really holds, and one outlier cannot move it.
    """

    median_points: int | None
    tier: str | None
    division: str | None
    # The median player's own LP. Apex has no divisions, so "Grandmaster" alone
    # says very little: the tier spans thousands of LP.
    league_points: int | None
    ranked: int
    unranked: int
    hidden: int
    bots: int
    # Identified, but the rank lookup failed or ran out of time budget. Kept
    # apart from `unranked` because "we did not find out" and "they have no
    # rank" are different claims and only one of them is ours to make.
    unknown: int
    queue_type: str
    # False for ARAM and friends, where the rank shown is solo queue standing
    # and not a rank in the queue actually being played.
    queue_matches_game: bool


@dataclass(slots=True)
class LiveGame:
    game_id: int
    platform_id: str
    queue_id: int
    game_mode: str | None
    map_id: int | None
    # `gameLength` is negative during champion select and loading. Measured at
    # -28 on a real game, which would render as a clock counting backwards.
    phase: Literal["loading", "in_progress"]
    game_start_time: int
    game_length: int
    observed_at: int
    banned_champion_ids: list[int] = field(default_factory=list)
    participants: list[LiveParticipant] = field(default_factory=list)
    lobby_rank: LobbyRank | None = None
    # False when the player we looked up is themselves anonymised: Riot still
    # returns their game, but no row in it can be attributed to them.
    you_identified: bool = True


def spectator_keystone(perks: dict | None) -> int | None:
    """Keystone id from a spectator payload.

    Spectator and match-v5 disagree on the shape of ``perks`` and nothing warns
    you. Spectator sends ``{"perkIds": [...], "perkStyle": N, "perkSubStyle": N}``
    while match-v5 sends ``{"styles": [{"description": ..., "selections": ...}]}``.
    Reusing the match-v5 reader here returns ``None`` for every live player, so
    the two have their own accessors on purpose.
    """
    ids = (perks or {}).get("perkIds")
    if isinstance(ids, list) and ids:
        first = ids[0]
        return int(first) if isinstance(first, int) else None
    return None


def spectator_secondary_style(perks: dict | None) -> int | None:
    style = (perks or {}).get("perkSubStyle")
    return int(style) if isinstance(style, int) and style else None


def split_riot_id(riot_id: str | None) -> tuple[str | None, str | None]:
    if not riot_id or "#" not in riot_id:
        return None, None
    name, _, tag = riot_id.partition("#")
    return (name or None), (tag or None)


def parse_participants(raw_participants: list[dict]) -> list[LiveParticipant]:
    """Turn the spectator roster into rows, without ranks attached yet.

    A missing PUUID means one of two very different things, and they must not be
    merged: ``bot: true`` is a bot, anything else is a human who has opted out
    of third-party visibility. Treating bots as hidden humans would report five
    "hidden players" in every co-op lobby.
    """
    out: list[LiveParticipant] = []
    for raw in raw_participants or []:
        puuid = raw.get("puuid") or None
        is_bot = bool(raw.get("bot"))
        name, tag = split_riot_id(raw.get("riotId"))
        if not puuid:
            # For an anonymised player Riot puts the champion name in `riotId`
            # with no tag line, so the absence of "#" is a second signal.
            name = tag = None
        out.append(
            LiveParticipant(
                puuid=puuid,
                champion_id=int(raw.get("championId") or 0),
                team_id=int(raw.get("teamId") or 0),
                spell1_id=raw.get("spell1Id"),
                spell2_id=raw.get("spell2Id"),
                keystone_id=spectator_keystone(raw.get("perks")),
                secondary_style_id=spectator_secondary_style(raw.get("perks")),
                profile_icon_id=raw.get("profileIconId"),
                game_name=name,
                tag_line=tag,
                state="bot" if is_bot else ("hidden" if not puuid else "unknown"),
            )
        )
    return out


def lobby_rank(participants: list[LiveParticipant], queue_id: int) -> LobbyRank:
    """The median rank of the identified players, and the sample it came from.

    Four buckets, never two. A player who is visible but genuinely unranked is
    not the same as one we could not see, and one whose lookup failed is not the
    same as either. None is imputed; all are counted and reported beside the
    number, because the ~30% who hide are not missing at random and nothing here
    can correct for that.
    """
    queue_type = RANKED_QUEUE_BY_ID.get(queue_id, DEFAULT_QUEUE)
    ranked_entries: list[RankedEntry] = []
    unranked = hidden = bots = unknown = 0

    for p in participants:
        if p.state == "bot":
            bots += 1
        elif p.state == "hidden":
            hidden += 1
        elif p.state == "unknown":
            unknown += 1
        elif p.rank is None or not p.rank.tier:
            unranked += 1
        else:
            ranked_entries.append(p.rank)

    ranked = len(ranked_entries)
    counts = {
        "ranked": ranked, "unranked": unranked, "hidden": hidden,
        "bots": bots, "unknown": unknown, "queue_type": queue_type,
        "queue_matches_game": queue_id in RANKED_QUEUE_BY_ID,
    }
    if ranked < MIN_RANKED_FOR_AVERAGE:
        # Withheld, not estimated. A greyed-out fake number is still a number.
        return LobbyRank(
            median_points=None, tier=None, division=None, league_points=None,
            **counts,
        )

    middle = median_entry(ranked_entries)
    return LobbyRank(
        median_points=rank_points(middle),
        tier=middle.tier,
        division=None if (middle.tier or "").upper() in APEX_TIER_NAMES else middle.division,
        league_points=middle.league_points,
        **counts,
    )


class LiveGameService:
    def __init__(self, session, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings
        self.ranks = RankCache(session, client, settings)

    async def for_puuid(
        self,
        puuid: str,
        platform: Platform | str,
        *,
        with_ranks: bool = True,
        observed_at_ms: int | None = None,
    ) -> LiveGame | None:
        """The player's current game, or ``None`` when they are not in one.

        ``None`` is the ordinary answer, not a failure: most lookups land on
        somebody who is not playing.
        """
        if not self.settings.enable_spectator:
            raise RiotForbidden(
                "Live game lookup is switched off on this server "
                "(ENABLE_SPECTATOR).",
                status=403,
            )

        resolved = resolve_platform(platform)
        payload = await self.client.active_game(puuid, resolved)
        if not payload:
            return None

        participants = parse_participants(payload.get("participants") or [])
        if with_ranks:
            await self._attach_ranks(participants, resolved, payload)

        length = int(payload.get("gameLength") or 0)
        game = LiveGame(
            game_id=int(payload.get("gameId") or 0),
            platform_id=payload.get("platformId") or resolved.id.upper(),
            queue_id=int(payload.get("gameQueueConfigId") or 0),
            game_mode=payload.get("gameMode"),
            map_id=payload.get("mapId"),
            phase="in_progress" if length > 0 else "loading",
            game_start_time=int(payload.get("gameStartTime") or 0),
            game_length=max(0, length),
            observed_at=observed_at_ms or int(time.time() * 1000),
            banned_champion_ids=[
                int(b.get("championId"))
                for b in (payload.get("bannedChampions") or [])
                if isinstance(b.get("championId"), int) and b.get("championId", -1) > 0
            ],
            participants=participants,
            you_identified=any(p.puuid == puuid for p in participants),
        )
        game.lobby_rank = lobby_rank(participants, game.queue_id)
        return game

    async def _attach_ranks(
        self, participants: list[LiveParticipant], platform: Platform, payload: dict
    ) -> None:
        identified = [p for p in participants if p.puuid]
        if not identified:
            return

        queue_id = int(payload.get("gameQueueConfigId") or 0)
        queue_type = RANKED_QUEUE_BY_ID.get(queue_id, DEFAULT_QUEUE)
        snapshots = await self.ranks.get_many(
            [p.puuid for p in identified],
            platform,
            ttl=self.settings.ttl_league_bulk,
            budget_seconds=self.settings.spectator_rank_budget_seconds,
        )
        names = await self.ranks.names_from_matches([p.puuid for p in identified])

        for p in identified:
            # The name first, and unconditionally. It came from a database query
            # that ran for every identified player, so a rank lookup that timed
            # out has no business also blanking a name we already held: the same
            # player would render named or unnamed depending on whether the
            # budget happened to reach them.
            if not p.game_name:
                p.game_name, p.tag_line = names.get(p.puuid, (None, None))

            snapshot = snapshots.get(p.puuid)
            if snapshot is None or not snapshot.known:
                # We did not find out. Saying "unranked" here would be a claim
                # we have not earned.
                p.state = "unknown"
                continue
            entry = next(
                (e for e in snapshot.entries if e.queue_type == queue_type), None
            )
            p.rank = entry
            p.state = "ranked" if entry and entry.tier else "unranked"



__all__ = [
    "LiveGame",
    "LiveGameService",
    "LiveParticipant",
    "LobbyRank",
    "RANKED_QUEUE_BY_ID",
    "lobby_rank",
    "parse_participants",
    "spectator_keystone",
    "spectator_secondary_style",
]
