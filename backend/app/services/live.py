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

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select

from app.db.models import ChampionStat, MatchupStat, RankedEntry
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotForbidden
from app.riot.routing import Platform, resolve_platform
from app.services.aggregate import ALL_BRACKETS, POSITIONS, available_slices
from app.services.ranks import RankCache
from app.services.roles import SUMMONERS_RIFT_MAP_ID, assign_team, load_priors

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

# The same floor the champion page applies by default to a matchup or a role, so
# the two pages cannot disagree about whether a record is worth showing. Shown
# as a W-L record rather than a bare percentage, so a thin one looks thin.
MIN_CORPUS_GAMES = 5

# A player's mastery on a champion moves by a few thousand points a game, so
# half an hour of caching loses nothing a person would notice, and it means the
# tab's own polling (every minute while a game runs) costs no mastery calls.
MASTERY_TTL_SECONDS = 1800
MASTERY_CACHE_LIMIT = 5000


@dataclass(frozen=True, slots=True)
class LiveMastery:
    level: int
    points: int
    last_play_time: int | None


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """A win-loss record from the stored corpus, never shown without its size."""

    games: int
    wins: int
    # Lane records only, and only once enough of those games have timelines.
    gold_diff_14: float | None = None
    timeline_games: int = 0


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
    # The skin number spectator reports as `lastSelectedSkinIndex`.
    skin_index: int | None = None
    # Inferred: spectator carries no position at all. See services/roles.py.
    position: str | None = None
    position_confidence: float | None = None
    position_basis: Literal["smite", "inferred"] | None = None
    # `mastery` is None both when the player has never played the champion and
    # when we did not find out; `mastery_known` separates the two, because
    # "first time on this champion" is a claim only an answer from Riot earns.
    mastery: LiveMastery | None = None
    mastery_known: bool = False
    # This champion in this position, and this champion against their lane
    # opponent, both from the stored corpus.
    champion_record: CorpusRecord | None = None
    lane_record: CorpusRecord | None = None


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
    # (champion_id, team_id) in pick order, for showing each side's bans apart.
    bans: list[tuple[int, int]] = field(default_factory=list)
    participants: list[LiveParticipant] = field(default_factory=list)
    lobby_rank: LobbyRank | None = None
    # False when the player we looked up is themselves anonymised: Riot still
    # returns their game, but no row in it can be attributed to them.
    you_identified: bool = True
    # True when every player has a position, which is what lets the page lay the
    # game out lane by lane. False off Summoner's Rift, where lanes do not exist.
    positions_inferred: bool = False
    # The patch the corpus records were read from, so the page can say so.
    corpus_patch: str | None = None


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
                skin_index=(
                    raw["lastSelectedSkinIndex"]
                    if isinstance(raw.get("lastSelectedSkinIndex"), int)
                    else None
                ),
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
            # Both are Riot calls with nothing in common, so they share one time
            # budget side by side instead of spending two in a row. Only the
            # rank lookup touches the database session; mastery is cached in
            # memory, so the two cannot trip over one session.
            await asyncio.gather(
                self._attach_ranks(participants, resolved, payload),
                self._attach_mastery(participants, resolved),
            )

        queue_id = int(payload.get("gameQueueConfigId") or 0)
        # Positions and corpus records cost no Riot calls at all: the first is
        # arithmetic over stored counts, the second two indexed queries.
        positions_inferred = (
            payload.get("mapId") == SUMMONERS_RIFT_MAP_ID
            and await self._infer_positions(participants)
        )
        corpus_patch = (
            await self._attach_corpus_records(participants, queue_id)
            if positions_inferred
            else None
        )

        raw_bans = sorted(
            (
                b
                for b in (payload.get("bannedChampions") or [])
                if isinstance(b.get("championId"), int) and b["championId"] > 0
            ),
            key=lambda b: b.get("pickTurn") or 0,
        )

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
            banned_champion_ids=[int(b["championId"]) for b in raw_bans],
            bans=[(int(b["championId"]), int(b.get("teamId") or 0)) for b in raw_bans],
            participants=participants,
            you_identified=any(p.puuid == puuid for p in participants),
            positions_inferred=positions_inferred,
            corpus_patch=corpus_patch,
        )
        game.lobby_rank = lobby_rank(participants, game.queue_id)
        return game

    async def _infer_positions(self, participants: list[LiveParticipant]) -> bool:
        """Give every player a position, or nobody one.

        All or nothing, because the page lays the game out lane by lane: a lobby
        with seven positions and three blanks has no layout, only a puzzle.
        """
        teams: dict[int, list[LiveParticipant]] = {}
        for p in participants:
            teams.setdefault(p.team_id, []).append(p)
        if len(teams) != 2 or any(len(team) != len(POSITIONS) for team in teams.values()):
            return False

        priors = await load_priors(self.session)
        for team in teams.values():
            calls = assign_team([(p.champion_id, p.spell1_id, p.spell2_id) for p in team], priors)
            if calls is None:
                return False
            for p, call in zip(team, calls, strict=True):
                p.position = call.position
                p.position_confidence = round(call.confidence, 3)
                p.position_basis = call.basis
        return True

    async def _attach_mastery(
        self, participants: list[LiveParticipant], platform: Platform
    ) -> None:
        """Each identified player's mastery on the champion they are playing.

        One call per player, which is why it is cached for half an hour and
        bounded by the same time budget as the rank lookup: a player the budget
        does not reach is left unknown, never reported as a first-timer.
        """
        identified = [p for p in participants if p.puuid]
        if not identified:
            return

        async def one(p: LiveParticipant) -> None:
            key = (platform.id, p.puuid, p.champion_id)
            hit = _mastery_cache.get(key)
            if hit is not None and time.monotonic() - hit[0] < MASTERY_TTL_SECONDS:
                p.mastery, p.mastery_known = hit[1], True
                return
            try:
                raw = await self.client.champion_mastery(p.puuid, p.champion_id, platform)
            except RiotApiError as exc:
                log.info("mastery lookup failed for %s: %s", p.puuid[:8], exc)
                return
            mastery = (
                LiveMastery(
                    level=int(raw.get("championLevel") or 0),
                    points=int(raw.get("championPoints") or 0),
                    last_play_time=raw.get("lastPlayTime"),
                )
                if raw
                else None
            )
            _remember_mastery(key, mastery)
            p.mastery, p.mastery_known = mastery, True

        tasks = [asyncio.create_task(one(p)) for p in identified]
        done, pending = await asyncio.wait(
            tasks, timeout=self.settings.spectator_rank_budget_seconds
        )
        for task in pending:
            task.cancel()
        for task in done:
            # Retrieved so a failure is logged here rather than as an orphaned
            # "exception was never retrieved" at garbage collection.
            if not task.cancelled() and task.exception() is not None:
                log.warning("mastery lookup raised: %r", task.exception())

    async def _attach_corpus_records(
        self, participants: list[LiveParticipant], queue_id: int
    ) -> str | None:
        """Each pick in its role, and against its lane opponent, from stored games.

        The newest patch held for the queue, and the champion page's own floor,
        so a record shown here is one the champion page would also show.
        Returns the patch read, or None when the corpus has nothing for the queue.
        """
        slices = [s for s in await available_slices(self.session) if s["queue_id"] == queue_id]
        if not slices:
            return None
        patch = slices[0]["patch"]
        champions = {p.champion_id for p in participants}

        role_rows = (
            await self.session.execute(
                select(ChampionStat).where(
                    ChampionStat.patch == patch,
                    ChampionStat.queue_id == queue_id,
                    ChampionStat.rank_bracket == ALL_BRACKETS,
                    ChampionStat.champion_id.in_(champions),
                    ChampionStat.games >= MIN_CORPUS_GAMES,
                )
            )
        ).scalars()
        by_role = {(r.champion_id, r.team_position): r for r in role_rows}

        lane_rows = (
            await self.session.execute(
                select(MatchupStat).where(
                    MatchupStat.patch == patch,
                    MatchupStat.queue_id == queue_id,
                    MatchupStat.rank_bracket == ALL_BRACKETS,
                    MatchupStat.scope == "LANE",
                    MatchupStat.champion_id.in_(champions),
                    MatchupStat.enemy_champion_id.in_(champions),
                    MatchupStat.games >= MIN_CORPUS_GAMES,
                )
            )
        ).scalars()
        by_lane = {(r.champion_id, r.enemy_champion_id, r.team_position): r for r in lane_rows}

        opponent = {(p.team_id, p.position): p for p in participants}
        for p in participants:
            role = by_role.get((p.champion_id, p.position))
            if role is not None:
                p.champion_record = CorpusRecord(games=role.games, wins=role.wins)
            # Summoner's Rift teams are 100 and 200, so the other side is 300 - id.
            enemy = opponent.get((300 - p.team_id, p.position))
            lane = by_lane.get((p.champion_id, enemy.champion_id, p.position)) if enemy else None
            if lane is not None:
                p.lane_record = CorpusRecord(
                    games=lane.games,
                    wins=lane.wins,
                    gold_diff_14=(
                        lane.avg_gold_diff_14
                        if lane.timeline_games >= MIN_CORPUS_GAMES
                        else None
                    ),
                    timeline_games=lane.timeline_games,
                )
        return patch

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



_mastery_cache: dict[tuple[str, str, int], tuple[float, LiveMastery | None]] = {}


def _remember_mastery(key: tuple[str, str, int], mastery: LiveMastery | None) -> None:
    if len(_mastery_cache) >= MASTERY_CACHE_LIMIT:
        # The oldest fifth out: cheap, and it stops the cache growing for ever.
        by_age = sorted(_mastery_cache, key=lambda k: _mastery_cache[k][0])
        for stale in by_age[: MASTERY_CACHE_LIMIT // 5]:
            del _mastery_cache[stale]
    _mastery_cache[key] = (time.monotonic(), mastery)


def clear_mastery_cache() -> None:
    """For tests, which must not inherit each other's cached answers."""
    _mastery_cache.clear()


__all__ = [
    "CorpusRecord",
    "LiveGame",
    "LiveMastery",
    "clear_mastery_cache",
    "LiveGameService",
    "LiveParticipant",
    "LobbyRank",
    "RANKED_QUEUE_BY_ID",
    "lobby_rank",
    "parse_participants",
    "spectator_keystone",
    "spectator_secondary_style",
]
