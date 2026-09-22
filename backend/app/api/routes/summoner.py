"""Summoner profile, match history and champion mastery.

Riot IDs are passed as two path segments (``/euw1/Caps/EUW``) rather than one
``Name#TAG`` string, because ``#`` is a URL fragment delimiter and survives
neither browsers nor proxies reliably.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import (
    DbDep,
    LadderServiceDep,
    LiveServiceDep,
    MatchServiceDep,
    PlayerServiceDep,
    SettingsDep,
    StaticDep,
)
from app.api.schemas import (
    AnalyticsResponse,
    ChampionPlayed,
    ClassShare,
    ComponentAverageOut,
    LadderPositionOut,
    LaneRecordOut,
    LiveGameResponse,
    MasteryResponse,
    MatchHistoryResponse,
    MatchResolveResponse,
    MatchSummary,
    PlayStyleTotals,
    ProfileResponse,
    RankHistoryResponse,
    RankPointOut,
    ReviewMetricOut,
    RoleReviewOut,
    RoleScoreProfileOut,
    RoleShare,
    epoch_ms,
    numeric_rank,
    to_idle_summary,
    to_live_game,
    to_mastery_response,
    to_match_summary,
    to_profile,
)
from app.api.schemas import ChampionRef as ChampionRefSchema
from app.db.models import Match, MatchParticipant, RankHistory
from app.riot.errors import RiotForbidden
from app.riot.routing import resolve_platform
from app.services.lanes import lane_labeler, lane_records
from app.services.profile_stats import (
    MIN_SCORED_FOR_PROFILE,
    champion_totals,
    score_profile,
)
from app.services.reviews import LOWER_IS_BETTER, MIN_PROFILE_GAMES, review_profile
from app.services.reviews import METRIC_LABELS as REVIEW_LABELS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summoner", tags=["summoner"])

PLATFORM_DESC = "Platform shard: na1, euw1, kr, eun1, br1, oc1, ..."

# `?source=stored` answers from storage alone: the player row as the last
# visit left it, the ranks as last read, the games we hold. It is what the
# prerenderer asks for, so that writing a page for every player with enough
# scored games costs no Riot call. It is not a refresh, and it says so in the
# response where the shape allows (`source`, `basis`).
SOURCE_DESC = "live (default) asks Riot where the cache is stale; stored reads storage only."
SOURCE_PATTERN = "^(live|stored)$"


@router.get("/{platform}/{game_name}/{tag_line}", response_model=ProfileResponse)
async def get_profile(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    ladders: LadderServiceDep,
    sd: StaticDep,
    refresh: bool = Query(
        False,
        description="Re-fetch from Riot, once the cached answer is at least a minute old.",
    ),
    source: str = Query("live", pattern=SOURCE_PATTERN, description=SOURCE_DESC),
) -> ProfileResponse:
    """Profile header: level, icon, every ranked queue and the ladder position."""
    asked = resolve_platform(platform)
    if source == "stored":
        player = await players.resolve_stored(platform, game_name, tag_line)
        ranks = await players.stored_ranks(player)
        # The ranks were read on one shard and the row says which; that is the
        # home shard, without the match-id call `effective_platform` may make.
        home = resolve_platform(player.league_platform) if player.league_platform else asked
        elsewhere = home if home.id != asked.id else None
        elsewhere_summoner = None
    else:
        player = await players.resolve(platform, game_name, tag_line, refresh=refresh)
        # Where this account's per-shard data actually is, which for an OCE Riot
        # ID is usually SG2. Asked before the ranks, not after: reading league-v4
        # on the shard that has no record answers 200 with an empty list, and
        # that renders as an unranked Challenger.
        home = await players.effective_platform(player, asked)
        ranks = await players.ranks(player, home.id, refresh=refresh)
        elsewhere = home if home.id != asked.id else None
        # Their level and icon live on that shard, so read them from there
        # rather than showing a blank avatar for an account that plainly has one.
        elsewhere_summoner = (
            await players.summoner_snapshot(player.puuid, elsewhere) if elsewhere else None
        )
    # Read from stored ladder snapshots only; no Riot call. On the home shard,
    # because a ladder is per shard just like the rank it is ordered by.
    solo = next((r for r in ranks if r.queue_type == "RANKED_SOLO_5x5"), None)
    found = (
        await ladders.position_of(player.puuid, home, solo.tier) if solo else None
    )
    ladder = (
        LadderPositionOut(
            tier=found.tier,
            tier_position=found.tier_position,
            position=found.position,
            platform=found.platform,
            platform_label=resolve_platform(found.platform).label,
            as_of=epoch_ms(found.as_of),
        )
        if found
        else None
    )
    return to_profile(
        player, ranks, sd, asked.label, elsewhere, elsewhere_summoner, ladder=ladder
    )


@router.get(
    "/{platform}/{game_name}/{tag_line}/rank-history", response_model=RankHistoryResponse
)
async def get_rank_history(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    db: DbDep,
    queue: str = Query("RANKED_SOLO_5x5", description="RANKED_SOLO_5x5 or RANKED_FLEX_SR."),
) -> RankHistoryResponse:
    """Every rank reading we took for this player, oldest first.

    Riot keeps no history, so this starts on the day we first read the rank and
    has a point only where the rank changed. ``tracking_since`` says when that
    was, so an empty or short graph reads as young, not as inactive.
    """
    player = await players.resolve(platform, game_name, tag_line)
    rows = (
        await db.execute(
            select(RankHistory)
            .where(RankHistory.puuid == player.puuid, RankHistory.queue_type == queue)
            .order_by(RankHistory.taken_at)
        )
    ).scalars().all()
    return RankHistoryResponse(
        queue_type=queue,
        tracking_since=epoch_ms(rows[0].taken_at) if rows else None,
        points=[
            RankPointOut(
                at=epoch_ms(r.taken_at),
                tier=r.tier,
                division=r.division,
                league_points=r.league_points,
                wins=r.wins,
                losses=r.losses,
                numeric_rank=numeric_rank(r.tier, r.division, r.league_points),
            )
            for r in rows
        ],
    )


@router.get("/{platform}/{game_name}/{tag_line}/matches", response_model=MatchHistoryResponse)
async def get_matches(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    matches: MatchServiceDep,
    sd: StaticDep,
    start: int = Query(0, ge=0, le=900),
    count: int = Query(20, ge=1, le=100),
    queue: int | None = Query(None, description="Riot queue id, e.g. 420 for Solo/Duo."),
    champion: int | None = Query(
        None, ge=1, description="Champion id. Read from stored games: Riot cannot filter by it."
    ),
    source: str = Query("live", pattern=SOURCE_PATTERN, description=SOURCE_DESC),
) -> MatchHistoryResponse:
    """Match history.

    Cold pages are slow by design: each new match is one request against a
    budget of 100 per two minutes. Already-seen matches are served from storage.
    With `champion` or `source=stored`, the page is stored games only and
    makes no Riot call at all.
    """
    if source == "stored":
        player = await players.resolve_stored(platform, game_name, tag_line)
    else:
        player = await players.resolve(platform, game_name, tag_line)
    # Read the identifier out of the ORM object now. Storing matches can hit a
    # write race and roll back, and a rollback expires every object in the
    # session -- including this `player`. Touching it afterwards would emit a
    # lazy SELECT and fail with MissingGreenlet.
    puuid = player.puuid

    # Lane labels read the role spreads once for the whole page.
    lanes = await lane_labeler(matches.session)

    if champion is not None or source == "stored":
        stored = await matches.stored_history(
            puuid, champion_id=champion, queue=queue, start=start, count=count
        )
        return MatchHistoryResponse(
            puuid=puuid,
            matches=[
                summary
                for match in stored.matches
                if (summary := to_match_summary(match, puuid, sd, lanes)) is not None
            ],
            start=start,
            count=count,
            has_more=start + count < stored.total,
            source="stored",
            stored_total=stored.total,
        )

    page = await matches.history(puuid, platform, start=start, count=count, queue=queue)
    summaries: list[MatchSummary] = []
    for match in page.matches:
        summary = to_match_summary(match, puuid, sd, lanes)
        if summary is not None:
            summaries.append(summary)
    return MatchHistoryResponse(
        puuid=puuid,
        matches=summaries,
        start=start,
        count=count,
        # Keyed off the ids Riot returned, not the matches we managed to
        # render: a single unfetchable match must not truncate the rest of
        # the player's history.
        has_more=page.id_count >= count,
    )


@router.get("/{platform}/{game_name}/{tag_line}/mastery", response_model=MasteryResponse)
async def get_mastery(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    sd: StaticDep,
    refresh: bool = Query(False),
) -> MasteryResponse:
    """Full champion mastery table: one call to Riot, every champion the player has touched."""
    player = await players.resolve(platform, game_name, tag_line)
    puuid = player.puuid
    # champion-mastery-v4 on a shard this account has no record on answers 200
    # with an empty list, so asking the wrong one reports a player who has
    # never touched a champion.
    home = await players.effective_platform(player, resolve_platform(platform))
    masteries = await players.masteries(player, home.id, refresh=refresh)
    # Read after the fetch, and safe to: the session keeps objects usable after
    # a commit, and the one path that rolls back refreshes the player itself.
    # The shard is worth saying out loud, because it is often not the one in the
    # URL and the page has no other way to know.
    return to_mastery_response(
        puuid,
        masteries,
        sd,
        platform=player.mastery_platform,
        fetched_at=epoch_ms(player.mastery_fetched_at),
    )


@router.get("/{platform}/{game_name}/{tag_line}/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    matches: MatchServiceDep,
    sd: StaticDep,
    queue: int | None = Query(None, description="Riot queue id, e.g. 420."),
    limit: int = Query(300, ge=10, le=1000, description="Stored games to analyse."),
    source: str = Query("live", pattern=SOURCE_PATTERN, description=SOURCE_DESC),
) -> AnalyticsResponse:
    """Play style: role share, champion class mix, and when this player plays.

    Reads **stored matches only**, so it costs nothing beyond resolving the Riot
    ID (and with ``source=stored``, not even that) and can never be blocked by a
    rate limit. It therefore describes the games we have fetched rather than a
    whole season, which the ``basis`` field says outright instead of letting
    the number imply more than it means.
    """
    if source == "stored":
        player = await players.resolve_stored(platform, game_name, tag_line)
    else:
        player = await players.resolve(platform, game_name, tag_line)
    puuid = player.puuid

    rows = await matches.played_by(puuid, queue=queue, limit=limit)
    if not rows:
        # Not an error: a profile nobody has opened yet simply has nothing stored.
        return AnalyticsResponse(puuid=puuid)

    role_games: Counter[str] = Counter()
    role_wins: Counter[str] = Counter()
    class_games: Counter[str] = Counter()
    activity = [0] * 24

    totals = {"wins": 0, "k": 0, "d": 0, "a": 0, "cs": 0, "vision": 0, "damage": 0, "minutes": 0.0}

    for row in rows:
        minutes = max(1.0, row.game_duration / 60)
        if row.team_position:
            role_games[row.team_position] += 1
            role_wins[row.team_position] += int(row.win)

        champion = sd.champion(row.champion_id)
        for tag in (champion.tags if champion else []):
            class_games[tag] += 1

        # game_creation is epoch milliseconds, UTC.
        activity[int((row.game_creation // 1000 // 3600) % 24)] += 1

        totals["wins"] += int(row.win)
        totals["k"] += row.kills
        totals["d"] += row.deaths
        totals["a"] += row.assists
        totals["cs"] += row.total_minions
        totals["vision"] += row.vision_score
        totals["damage"] += row.damage_to_champions
        totals["minutes"] += minutes

    played = len(rows)
    role_total = sum(role_games.values()) or 1
    class_total = sum(class_games.values()) or 1

    return AnalyticsResponse(
        puuid=puuid,
        games_analysed=played,
        roles=[
            RoleShare(
                position=position,
                games=games,
                share=games / role_total,
                win_rate=role_wins[position] / games,
            )
            for position, games in role_games.most_common()
        ],
        classes=[
            ClassShare(tag=tag, games=games, share=games / class_total)
            for tag, games in class_games.most_common()
        ],
        activity_utc=activity,
        champions=[
            ChampionPlayed(
                champion=ChampionRefSchema(
                    id=t.champion_id,
                    name=sd.champion_name(t.champion_id),
                    icon_url=sd.champion_icon(t.champion_id),
                ),
                games=t.games,
                wins=t.wins,
                win_rate=t.wins / t.games,
                kda=(t.kills + t.assists) / max(1, t.deaths),
                cs_per_min=t.cs / t.minutes if t.minutes else 0.0,
                avg_kills=t.kills / t.games,
                avg_deaths=t.deaths / t.games,
                avg_assists=t.assists / t.games,
                damage_per_min=t.damage / t.minutes if t.minutes else 0.0,
                main_position=t.main_position,
                last_played=t.last_played or None,
                scored_games=t.scored_games,
                avg_score=t.score_total / t.scored_games if t.scored_games else None,
                timeline_games=t.timeline_games,
                avg_gold_diff_14=(
                    t.gold_diff_total / t.timeline_games if t.timeline_games else None
                ),
            )
            for t in champion_totals(rows)
        ],
        review=[
            RoleReviewOut(
                position=r.position,
                games=r.games,
                min_games=MIN_PROFILE_GAMES,
                withheld=r.withheld,
                metrics=[
                    ReviewMetricOut(
                        metric=m.metric,
                        label=REVIEW_LABELS[m.metric][0],
                        measures=REVIEW_LABELS[m.metric][1],
                        value=m.value,
                        better_than=m.better_than,
                        lower_is_better=m.metric in LOWER_IS_BETTER,
                        games=m.games,
                    )
                    for m in r.metrics
                ],
                contests=r.contests,
                contests_won=r.contests_won,
            )
            for r in await review_profile(matches.session, puuid, queue)
        ],
        lanes=[
            LaneRecordOut.model_validate(r, from_attributes=True)
            for r in await lane_records(matches.session, puuid, queue=queue, limit=limit)
        ],
        score_profile=[
            RoleScoreProfileOut(
                position=p.position,
                scored_games=p.scored_games,
                enough=p.enough,
                avg_score=p.avg_score,
                avg_placement=p.avg_placement,
                mvp=p.mvp,
                ace=p.ace,
                components=[
                    ComponentAverageOut(
                        id=c.id,
                        label=c.label,
                        measures=c.measures,
                        avg_percentile=c.avg_percentile,
                    )
                    for c in p.components
                ],
                sample=p.sample,
                min_scored=MIN_SCORED_FOR_PROFILE,
            )
            for p in score_profile(rows)
        ],
        totals=PlayStyleTotals(
            win_rate=totals["wins"] / played,
            kda=(totals["k"] + totals["a"]) / max(1, totals["d"]),
            avg_kills=totals["k"] / played,
            avg_deaths=totals["d"] / played,
            avg_assists=totals["a"] / played,
            cs_per_min=totals["cs"] / totals["minutes"],
            vision_per_game=totals["vision"] / played,
            damage_per_min=totals["damage"] / totals["minutes"],
        ),
    )


@router.get("/{platform}/{game_name}/{tag_line}/live", response_model=LiveGameResponse)
async def get_live_game(
    platform: str,
    game_name: str,
    tag_line: str,
    players: PlayerServiceDep,
    live: LiveServiceDep,
    matches: MatchServiceDep,
    sd: StaticDep,
    settings: SettingsDep,
) -> LiveGameResponse:
    """The game this player is in right now, if any.

    Answers 200 with ``in_game: false`` when they are not playing. That is the
    common case and it is not an error: a 404 here would render as "no player
    found", which is false -- the player exists, the game does not.

    Roughly a third of any lobby has opted out of third-party visibility, so
    expect participants in the ``hidden`` state with no name and no rank. See
    ``app/services/live.py`` for why that is reported rather than papered over.
    """
    import time

    # Checked before resolving the player, not after. The service checks it too,
    # but by then a disabled server has already spent an account-v1 and a
    # summoner-v4 call to answer a question it was never going to answer.
    if not settings.enable_spectator:
        raise RiotForbidden(
            "Live game lookup is switched off on this server (ENABLE_SPECTATOR).",
            status=403,
        )

    player = await players.resolve(platform, game_name, tag_line)
    # Read before the live lookup, not after. `RankCache` tolerates a write race
    # by rolling back, and a rollback expires every object in the session -- one
    # session is shared by every service in a request -- so `player.puuid` after
    # this line would fire a lazy SELECT and fail as MissingGreenlet. The match
    # history route guards the same way.
    puuid = player.puuid
    # spectator-v5 is per shard as well, and "not in a game" on the wrong shard
    # is indistinguishable from the truth, so ask the one that holds the
    # account. The response names the shard actually checked rather than the one
    # in the URL: reporting `oc1` for a lookup made against `sg2` would be a
    # quiet lie about where the answer came from.
    home = await players.effective_platform(player, resolve_platform(platform))
    game = await live.for_puuid(puuid, home.id)
    # Two storage reads, and only on the branch nobody wanted: 31 production
    # lookups on 2026-09-21 found nobody in a game, so this is the state the
    # page is almost always in, and it used to be an empty box. A game in
    # progress pays for none of it.
    idle = (
        to_idle_summary(
            await matches.last_stored(puuid), await matches.stored_count(puuid), sd
        )
        if game is None
        else None
    )
    return LiveGameResponse(
        puuid=puuid,
        platform=home.id,
        in_game=game is not None,
        game=(
            to_live_game(game, sd, sd.queue_name(game.queue_id))
            if game is not None
            else None
        ),
        idle=idle,
        checked_at=int(time.time() * 1000),
    )


# Riot publishes a finished match a minute or two after it ends, and a live page
# polls, so the spend is bounded per match id rather than per request: one
# process-global dict, the same shape and the same trim as the mastery cache in
# `app/services/live.py`.
_resolve_attempts: dict[str, tuple[float, int]] = {}
_RESOLVE_CACHE_LIMIT = 5000
# A Riot match id: a platform prefix, an underscore, and the game id.
_MATCH_ID = re.compile(r"^[A-Z0-9]{2,7}_\d{1,20}$")


def clear_resolve_cache() -> None:
    """For tests, which must not inherit each other's attempt counts."""
    _resolve_attempts.clear()


def _remember_attempt(match_id: str, attempts: int) -> None:
    if len(_resolve_attempts) >= _RESOLVE_CACHE_LIMIT:
        # The oldest fifth out, so the dict cannot grow for ever.
        by_age = sorted(_resolve_attempts, key=lambda k: _resolve_attempts[k][0])
        for stale in by_age[: _RESOLVE_CACHE_LIMIT // 5]:
            _resolve_attempts.pop(stale, None)
    _resolve_attempts[match_id] = (time.monotonic(), attempts)



async def _their_line(db, match_id: str, puuid: str) -> tuple[bool | None, float | None, int | None]:
    """The searched player's own result in a stored match.

    One indexed read, so the band can say "you won" rather than "the result
    exists". A player whose row is not in the match, which happens when the id
    came from somewhere else, gets nulls rather than a guess.
    """
    row = (
        await db.execute(
            select(
                MatchParticipant.win,
                MatchParticipant.performance_score,
                MatchParticipant.performance_rank,
            ).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.puuid == puuid,
            )
        )
    ).first()
    return (row[0], row[1], row[2]) if row is not None else (None, None, None)


@router.get(
    "/{platform}/{game_name}/{tag_line}/live/result/{match_id}",
    response_model=MatchResolveResponse,
)
async def get_live_result(
    platform: str,
    game_name: str,
    tag_line: str,
    match_id: str,
    players: PlayerServiceDep,
    matches: MatchServiceDep,
    db: DbDep,
    settings: SettingsDep,
) -> MatchResolveResponse:
    """Has the game that just ended reached storage yet?

    The only Riot call the live page spends beyond the lookup itself, so it sits
    behind four gates, three of them free: the id has to look like a match id,
    storage is checked first, a cooldown holds the second tab off, and a cap
    stops a match id that is never going to publish from costing anything more.

    Under the summoner path deliberately. A bare ``/api/matches/{id}/resolve``
    would be a generic "make the server fetch any match from Riot" door open to
    anyone; here it needs a resolvable Riot ID, which the live poll just looked
    up and which is cached for a day, and every fetch is tied to an account.
    """
    match_id = match_id.upper()
    if not _MATCH_ID.match(match_id):
        raise HTTPException(status_code=400, detail=f"{match_id!r} is not a match id.")
    try:
        regional = resolve_platform(match_id.split("_")[0]).regional
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{match_id!r} names a platform we do not serve."
        ) from None

    # Before resolving the player, so a disabled server does not spend an
    # account lookup answering a question it will not answer.
    if not settings.enable_spectator:
        raise RiotForbidden(
            "Live game lookup is switched off on this server (ENABLE_SPECTATOR).",
            status=403,
        )

    stored = (
        await db.execute(
            select(Match.game_creation, Match.game_duration).where(
                Match.match_id == match_id
            )
        )
    ).first()
    if stored is not None:
        # Resolve the player from cache to read their own line. The account
        # lookup is cached for a day and the live poll just made it, so this is
        # free in practice and never a Riot call of its own.
        player = await players.resolve(platform, game_name, tag_line)
        win, score, placement = await _their_line(db, match_id, player.puuid)
        return MatchResolveResponse(
            match_id=match_id,
            status="stored",
            game_creation=stored[0],
            game_duration=stored[1],
            win=win,
            score=score,
            placement=placement,
        )

    now = time.monotonic()
    last_at, attempts = _resolve_attempts.get(match_id, (0.0, 0))
    waited = now - last_at
    if attempts >= settings.live_result_max_attempts:
        return MatchResolveResponse(
            match_id=match_id,
            status="gave_up",
            hint=(
                "Riot has not published this game. That happens when a game was "
                "remade or was not a queue Riot publishes."
            ),
        )
    if waited < settings.live_result_cooldown_seconds:
        return MatchResolveResponse(
            match_id=match_id,
            status="pending",
            retry_after=int(settings.live_result_cooldown_seconds - waited) + 1,
        )

    # The one call. `ensure_matches` checks storage itself, swallows a 404 from
    # Riot and returns an empty list for a match that is not published yet, and
    # scores what it stores on the way through.
    player = await players.resolve(platform, game_name, tag_line)
    # Read before the fetch: `ensure_matches` can roll back, and a rollback
    # expires every ORM object in the shared session, so a later attribute read
    # would fire a lazy SELECT and fail as MissingGreenlet.
    puuid = player.puuid
    _remember_attempt(match_id, attempts + 1)
    found = await matches.ensure_matches([match_id], regional)
    if found:
        log.info("resolved finished live game %s", match_id)
        win, score, placement = await _their_line(db, match_id, puuid)
        return MatchResolveResponse(
            match_id=match_id,
            status="stored",
            attempted=True,
            game_creation=found[0].game_creation,
            game_duration=found[0].game_duration,
            win=win,
            score=score,
            placement=placement,
        )
    return MatchResolveResponse(
        match_id=match_id,
        status="pending",
        attempted=True,
        retry_after=int(settings.live_result_cooldown_seconds) + 1,
        hint="Riot has not published the result yet.",
    )
