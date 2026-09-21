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

from sqlalchemy import func, select

from app.db.models import ChampionStat, Match, MatchParticipant, MatchupStat, RankedEntry
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotForbidden
from app.riot.routing import Platform, resolve_platform
from app.services.aggregate import (
    ALL_BRACKETS,
    POSITIONS,
    available_slices,
    patch_sort_key,
    win_as_int,
)
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

# How far the lane record may reach when this patch holds too few games.
# Measured 2026-09-21 over the lanes of forty real lobbies: 26% of them have a
# five game lane record on the current patch, 34% once the previous patch is
# pooled in, and 35% have a team scope record for the same pair. A third patch
# was never measured, so it is not assumed.
MAX_POOLED_PATCHES = 2
# And only a patch close enough to still describe the same game. Judgement
# rather than a measurement: the corpus is crawled rather than exhaustive, so
# the next patch held can be a number or two down, but past that the items and
# the kits have moved and pooling would be a different claim.
POOL_MAX_MINOR_GAP = 2

# How many stored games a player needs before we describe their play at all, and
# how many before a percentage is published rather than a W-L. Both are defined
# in schemas, which this module imports rather than the other way round, so the
# response models publish the same numbers the service applies.
from app.api.schemas import MIN_GAMES_FOR_WIN_RATE, MIN_RECORD_GAMES  # noqa: E402

# "Their usual role" needs enough positioned games to be a habit, and a share
# big enough to be one role rather than a rotation. Measured over 712 players
# with eight or more positioned games: the top role holds a median 76% of them,
# 82% of players reach 60%, and 94% reach 50%. At 50% a genuine two-role player
# would be called off role, which is a claim about them we cannot support.
MIN_GAMES_FOR_MAIN_ROLE = 8
MAIN_ROLE_SHARE = 0.6

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
class PlayedRecord:
    """A player's own record from stored games, never shown without its size."""

    games: int
    wins: int
    scored_games: int
    score_total: float
    # Epoch ms. Both ends, because a 12-8 spread over fourteen months and a 12-8
    # in three weeks are different facts and only the dates tell them apart.
    last_played: int | None = None
    first_played: int | None = None

    @property
    def losses(self) -> int:
        return self.games - self.wins

    @property
    def win_rate(self) -> float | None:
        """None under MIN_GAMES_FOR_WIN_RATE: the W-L is always there instead."""
        if self.games < MIN_GAMES_FOR_WIN_RATE:
            return None
        return self.wins / self.games

    @property
    def avg_score(self) -> float | None:
        return self.score_total / self.scored_games if self.scored_games else None


@dataclass(slots=True)
class PlayerRecord:
    """What the corpus holds about one player in a live lobby.

    Withheld rather than zeroed: a player we hold nothing for has no record at
    all, and `LiveParticipant.stored_games` says so separately. A record full of
    zeroes would read as a player who loses every game.
    """

    overall: PlayedRecord
    # None means we hold no game of theirs on this champion, which is not the
    # same claim as "they have never played it": that one belongs to mastery,
    # which covers their whole history rather than what we crawled.
    on_champion: PlayedRecord | None
    main_position: str | None
    main_position_games: int
    positioned_games: int
    # None whenever either side of the comparison is unknown.
    on_main_position: bool | None


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """A win-loss record from the stored corpus, never shown without its size."""

    games: int
    wins: int
    # Lane records only, and only once enough of those games have timelines.
    gold_diff_14: float | None = None
    timeline_games: int = 0
    # Which step of the fallback ladder this came from: "role" for a champion's
    # own record, then "lane", "lane_pooled", "team". The page labels the weaker
    # ones, because a team scope record shown as a lane record is a false claim.
    basis: str = "lane"
    patches: tuple[str, ...] = ()


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
    # How many games we hold for this player, always, even when the record below
    # is withheld: "we hold two games" and "we hold nothing" are different facts
    # and the page has to be able to tell them apart.
    stored_games: int = 0
    record: PlayerRecord | None = None


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
    # Every patch the lane fallback was allowed to read, newest first.
    corpus_patches: list[str] = field(default_factory=list)
    # Which games the player records were counted over: this queue, or every
    # queue we hold. The crawl is nearly all solo queue, so scoping a flex lobby
    # to flex would blank ten cards for nothing.
    record_basis: str = "all_queues"
    record_queue_id: int | None = None


def _poolable_patches(held: list[str]) -> tuple[str, ...]:
    """The newest patch, plus the one before it when it is close enough.

    `available_slices` already orders by patch, newest first, so this only has
    to decide whether the second one is near enough to describe the same game.
    """
    newest = held[0]
    pool = [newest]
    for patch in held[1:]:
        if len(pool) >= MAX_POOLED_PATCHES:
            break
        a, b = patch_sort_key(newest), patch_sort_key(patch)
        if a[0] == b[0] and a[1] - b[1] <= POOL_MAX_MINOR_GAP:
            pool.append(patch)
    return tuple(pool)


def _pool(rows: list[MatchupStat], patches: tuple[str, ...], basis: str) -> CorpusRecord | None:
    """Sum a matchup's rows, or return None when they are still too thin.

    The gold lead is weighted by the timelines behind it, not averaged twice
    over: 300 over six timelines pooled with -100 over two is 200, not 100.
    """
    if not rows:
        return None
    games = sum(r.games for r in rows)
    if games < MIN_CORPUS_GAMES:
        return None
    timeline_games = sum(r.timeline_games for r in rows)
    weighted = [r for r in rows if r.avg_gold_diff_14 is not None and r.timeline_games]
    gold_diff = (
        sum(r.avg_gold_diff_14 * r.timeline_games for r in weighted)
        / sum(r.timeline_games for r in weighted)
        if weighted and timeline_games >= MIN_CORPUS_GAMES
        else None
    )
    return CorpusRecord(
        games=games,
        wins=sum(r.wins for r in rows),
        # A TEAM row's gold lead is this champion's lead against its own laner
        # in games where the named enemy was somewhere on the other team. It is
        # not a lead against that enemy, so it is dropped rather than relabelled.
        gold_diff_14=gold_diff if basis != "team" else None,
        timeline_games=timeline_games if basis != "team" else 0,
        basis=basis,
        patches=tuple(p for p in patches if any(r.patch == p for r in rows)),
    )


def _best_matchup_record(
    rows: list[MatchupStat],
    champion_id: int,
    enemy_id: int,
    position: str | None,
    patches: tuple[str, ...],
) -> CorpusRecord | None:
    """Walk the fallback ladder and stop at the first step that clears the floor."""
    pair = [r for r in rows if r.champion_id == champion_id and r.enemy_champion_id == enemy_id]
    lane = [r for r in pair if r.scope == "LANE" and r.team_position == position]

    current = _pool([r for r in lane if r.patch == patches[0]], patches, "lane")
    if current is not None:
        return current
    pooled = _pool(lane, patches, "lane_pooled")
    if pooled is not None:
        return pooled
    # A TEAM row still carries this champion's own role: the scope drops the
    # join on the *enemy's* position, not on ours. So this is still "this
    # champion in this lane", against that enemy anywhere on the map.
    return _pool(
        [r for r in pair if r.scope == "TEAM" and r.team_position == position],
        patches,
        "team",
    )


def _main_position(counts: dict[str, int]) -> tuple[str | None, int]:
    """The role this player usually takes, or None when they do not have one.

    Ties break on games, then on the fixed `POSITIONS` order, so the label is
    the same on every run rather than depending on dict ordering.
    """
    total = sum(counts.values())
    if total < MIN_GAMES_FOR_MAIN_ROLE:
        return None, 0
    best = max(counts, key=lambda pos: (counts[pos], -POSITIONS.index(pos)))
    if counts[best] / total >= MAIN_ROLE_SHARE:
        return best, counts[best]
    return None, counts[best]


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
        corpus_patch, corpus_patches = (
            await self._attach_corpus_records(participants, queue_id)
            if positions_inferred
            else (None, [])
        )
        # After the positions, because "off their usual role" compares against
        # the position inferred above. Storage only, like the two before it, and
        # on the same session rather than as a third leg of the gather.
        record_basis, record_queue_id = await self._attach_player_records(
            participants, queue_id
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
            corpus_patches=corpus_patches,
            record_basis=record_basis,
            record_queue_id=record_queue_id,
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
    ) -> tuple[str | None, list[str]]:
        """Each pick in its role, and against its lane opponent, from storage.

        **The lane record is the page's one comparative number, and it used to
        be missing three lanes in four.** Measured across forty real lobbies:
        only 26% of lanes have a five game record on the newest patch. So the
        read falls back in a stated order, and every record says which step it
        came from, because a team scope record rendered as a lane record would
        be a claim we cannot support:

        1. `LANE` on the newest patch held for this queue        (26% of lanes)
        2. `LANE` pooled with the previous patch held            (34%)
        3. `TEAM` for the same champion pair, pooled the same way (35% have one)
        4. nothing

        Step 1 wins even when step 2 would be a bigger sample: a current patch
        record must not be diluted by older rows under a label that says
        current.

        Returns the newest patch read and every patch the ladder was allowed to
        touch, so the page can say so.
        """
        slices = [s for s in await available_slices(self.session) if s["queue_id"] == queue_id]
        if not slices:
            return None, []
        patches = _poolable_patches([s["patch"] for s in slices])
        champions = {p.champion_id for p in participants}

        role_rows = (
            await self.session.execute(
                select(ChampionStat).where(
                    ChampionStat.patch == patches[0],
                    ChampionStat.queue_id == queue_id,
                    ChampionStat.rank_bracket == ALL_BRACKETS,
                    ChampionStat.champion_id.in_(champions),
                    ChampionStat.games >= MIN_CORPUS_GAMES,
                )
            )
        ).scalars()
        by_role = {(r.champion_id, r.team_position): r for r in role_rows}

        # Both scopes and both patches in one query: `ix_matchup_lookup` leads
        # with `patch`, so two patches are two index ranges. The five game floor
        # is applied in Python rather than in SQL, because three games on each
        # of two patches has to survive to be summed.
        matchup_rows = (
            await self.session.execute(
                select(MatchupStat).where(
                    MatchupStat.patch.in_(patches),
                    MatchupStat.queue_id == queue_id,
                    MatchupStat.rank_bracket == ALL_BRACKETS,
                    MatchupStat.scope.in_(("LANE", "TEAM")),
                    MatchupStat.champion_id.in_(champions),
                    MatchupStat.enemy_champion_id.in_(champions),
                )
            )
        ).scalars().all()

        opponent = {(p.team_id, p.position): p for p in participants}
        for p in participants:
            role = by_role.get((p.champion_id, p.position))
            if role is not None:
                p.champion_record = CorpusRecord(
                    games=role.games, wins=role.wins, basis="role", patches=(patches[0],)
                )
            # Summoner's Rift teams are 100 and 200, so the other side is 300 - id.
            enemy = opponent.get((300 - p.team_id, p.position))
            if enemy is not None:
                p.lane_record = _best_matchup_record(
                    matchup_rows, p.champion_id, enemy.champion_id, p.position, patches
                )
        return patches[0], list(patches)

    async def _attach_player_records(
        self, participants: list[LiveParticipant], queue_id: int
    ) -> tuple[str, int | None]:
        """What the corpus holds about each player, not about their champion.

        The page shows rank, mastery and the champion's win rate, so nothing on
        it was about the people in the lobby. Measured 2026-09-21: a median of 9
        of 10 players in a recent stored lobby have three or more other stored
        games, every one of them scored, so this is populated for almost
        everyone in a crawled bracket.

        Two grouped queries rather than ten `played_by` calls: `played_by`
        selects `performance_detail` for every row, so ten players would pull up
        to three thousand JSON blobs off disk, once a minute per open tab, to
        compute seven numbers. Measured at 5.2 ms and 1.4 ms on the local corpus
        against `ix_participant_puuid_match`, whose leading column is `puuid`.

        Returns the basis these counts were taken on, for the response to state.
        """
        identified = [p for p in participants if p.puuid]
        if not identified:
            return "all_queues", None
        puuids = [p.puuid for p in identified]

        # Solo queue only. The crawl is nearly all 420, so scoping a flex or an
        # ARAM lobby to its own queue would withhold every record in it.
        scoped = queue_id == 420
        basis = "queue" if scoped else "all_queues"

        by_position = (
            select(
                MatchParticipant.puuid,
                MatchParticipant.team_position,
                func.count().label("games"),
                func.sum(win_as_int()).label("wins"),
                func.count(MatchParticipant.performance_score).label("scored"),
                func.coalesce(func.sum(MatchParticipant.performance_score), 0.0).label(
                    "score_total"
                ),
                func.max(Match.game_creation).label("newest"),
                func.min(Match.game_creation).label("oldest"),
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.puuid.in_(puuids), Match.is_remake.is_(False))
            .group_by(MatchParticipant.puuid, MatchParticipant.team_position)
        )
        by_champion = (
            select(
                MatchParticipant.puuid,
                MatchParticipant.champion_id,
                func.count().label("games"),
                func.sum(win_as_int()).label("wins"),
                func.count(MatchParticipant.performance_score).label("scored"),
                func.coalesce(func.sum(MatchParticipant.performance_score), 0.0).label(
                    "score_total"
                ),
                func.max(Match.game_creation).label("newest"),
                func.min(Match.game_creation).label("oldest"),
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.puuid.in_(puuids),
                MatchParticipant.champion_id.in_({p.champion_id for p in identified}),
                Match.is_remake.is_(False),
            )
            .group_by(MatchParticipant.puuid, MatchParticipant.champion_id)
        )
        if scoped:
            by_position = by_position.where(Match.queue_id == queue_id)
            by_champion = by_champion.where(Match.queue_id == queue_id)

        position_rows = (await self.session.execute(by_position)).all()
        champion_rows = (await self.session.execute(by_champion)).all()

        totals: dict[str, list] = {}
        positions: dict[str, dict[str, int]] = {}
        for puuid, position, games, wins, scored, score_total, newest, oldest in position_rows:
            bucket = totals.setdefault(puuid, [0, 0, 0, 0.0, None, None])
            bucket[0] += games
            bucket[1] += wins or 0
            bucket[2] += scored
            bucket[3] += float(score_total or 0.0)
            bucket[4] = newest if bucket[4] is None else max(bucket[4], newest)
            bucket[5] = oldest if bucket[5] is None else min(bucket[5], oldest)
            if position in POSITIONS:
                positions.setdefault(puuid, {})[position] = games

        on_champion: dict[tuple[str, int], PlayedRecord] = {}
        for puuid, champion_id, games, wins, scored, score_total, newest, oldest in champion_rows:
            on_champion[(puuid, champion_id)] = PlayedRecord(
                games=games,
                wins=wins or 0,
                scored_games=scored,
                score_total=float(score_total or 0.0),
                last_played=newest,
                first_played=oldest,
            )

        for p in identified:
            bucket = totals.get(p.puuid)
            p.stored_games = bucket[0] if bucket else 0
            if bucket is None or bucket[0] < MIN_RECORD_GAMES:
                continue
            counts = positions.get(p.puuid, {})
            main, main_games = _main_position(counts)
            p.record = PlayerRecord(
                overall=PlayedRecord(
                    games=bucket[0],
                    wins=bucket[1],
                    scored_games=bucket[2],
                    score_total=bucket[3],
                    last_played=bucket[4],
                    first_played=bucket[5],
                ),
                on_champion=on_champion.get((p.puuid, p.champion_id)),
                main_position=main,
                main_position_games=main_games,
                positioned_games=sum(counts.values()),
                on_main_position=(
                    None if main is None or p.position is None else main == p.position
                ),
            )
        return basis, (queue_id if scoped else None)

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
