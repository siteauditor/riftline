"""A group's table and its "played together", read from storage only.

No Riot call happens here: fetching is `groups.Warmer`'s job, and this shows
whatever has landed so far, saying per player how much that is. The rules are
the rest of the site's: every average carries its count, and figures from
fewer than ``MIN_GAMES`` games are withheld rather than shown.

**Riot's policy decides the order.** Riot does not allow alternatives to its
ranked ladder ("MMR or ELO calculators"), so the default order is the official
rank, every other figure is a column the page can sort by, and nothing here
folds them into one group rating.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChampionRef,
    ComponentAverageOut,
    GroupChampionOut,
    GroupHistoryOut,
    GroupMemberOut,
    GroupPairOut,
    GroupQueueOut,
    GroupResponse,
    GroupTogetherOut,
    LaneRecordOut,
    ReviewMetricOut,
    RoleReviewOut,
    RoleScoreProfileOut,
    RoleShare,
    TogetherGameOut,
    TogetherPlayerOut,
    epoch_ms,
    to_rank_info,
)
from app.db.models import (
    GroupMember,
    HistoryCursor,
    Match,
    MatchParticipant,
    Player,
    PlayerGroup,
    RankedEntry,
)
from app.riot.routing import UnknownPlatform, resolve_platform
from app.services.groups import MAX_MEMBERS
from app.services.lanes import lane_labeler, lane_records
from app.services.matches import MatchService, PlayedRow
from app.services.profile_stats import MIN_SCORED_FOR_PROFILE, champion_totals, score_profile
from app.services.reviews import LOWER_IS_BETTER, MIN_PROFILE_GAMES, review_profile
from app.services.reviews import METRIC_LABELS as REVIEW_LABELS
from app.services.static_data import StaticDataService

# The queue filters a group page offers, and the Riot queue ids behind each.
# None is every queue, customs and all.
QUEUE_FILTERS: dict[str, tuple[str, frozenset[int] | None]] = {
    "all": ("All queues", None),
    "solo": ("Ranked Solo/Duo", frozenset({420})),
    "flex": ("Ranked Flex", frozenset({440})),
    "normal": ("Normal", frozenset({400, 430, 490})),
    "swiftplay": ("Swiftplay", frozenset({480})),
    "aram": ("ARAM", frozenset({450, 2400})),
    "arena": ("Arena", frozenset({1700, 1710, 1740, 1750})),
}
# No lanes and no roles, so the Riftline score, the review and lane labels do
# not exist for these: said as such rather than shown empty.
UNSCORED = frozenset({"aram", "arena"})

# Below five games a win rate moves twenty points on one game.
MIN_GAMES = 5
# Two players who queued together twice is a coincidence as often as a duo.
MIN_PAIR_GAMES = 3
RECENT_RESULTS = 10
TOGETHER_RECENT = 10

SOLO = "RANKED_SOLO_5x5"


def member_pending(
    player: Player | None, member: GroupMember, cursor: HistoryCursor | None, cap: int
) -> bool:
    """Whether this player is still being fetched: rank never read on their
    shard, or history short of the cap with more to read."""
    if player is None or player.league_platform != member.platform or player.league_fetched_at is None:
        return True
    if cursor is None or cursor.checked_at is None:
        return True
    return not cursor.exhausted and cursor.offset < cap


async def pending_count(session: AsyncSession, members: Sequence[GroupMember], cap: int) -> int:
    puuids = [m.puuid for m in members]
    players = {
        p.puuid: p
        for p in (await session.execute(select(Player).where(Player.puuid.in_(puuids)))).scalars()
    }
    cursors = {
        c.puuid: c
        for c in (
            await session.execute(select(HistoryCursor).where(HistoryCursor.puuid.in_(puuids)))
        ).scalars()
    }
    return sum(
        member_pending(players.get(m.puuid), m, cursors.get(m.puuid), cap) for m in members
    )


def _rank_key(member: GroupMemberOut) -> tuple:
    """Official solo rank, then flex, then unranked; LP within a tier."""
    solo = next((r.numeric_rank for r in member.ranks if r.queue == SOLO and r.tier), None)
    other = max((r.numeric_rank for r in member.ranks if r.tier), default=None)
    return (
        solo is None,
        -(solo or 0),
        other is None,
        -(other or 0),
        (member.riot_id or "").casefold(),
    )


async def group_table(
    session: AsyncSession,
    settings,
    sd: StaticDataService,
    group: PlayerGroup,
    members: Sequence[GroupMember],
    *,
    queue_key: str,
    can_edit: bool,
) -> GroupResponse:
    queues = QUEUE_FILTERS[queue_key][1]
    scored_mode = queue_key not in UNSCORED
    cap = int(settings.group_history_cap)
    puuids = [m.puuid for m in members]

    players = {
        p.puuid: p
        for p in (await session.execute(select(Player).where(Player.puuid.in_(puuids)))).scalars()
    }
    ranks: dict[str, list[RankedEntry]] = defaultdict(list)
    for entry in (
        await session.execute(select(RankedEntry).where(RankedEntry.puuid.in_(puuids)))
    ).scalars():
        ranks[entry.puuid].append(entry)
    cursors = {
        c.puuid: c
        for c in (
            await session.execute(select(HistoryCursor).where(HistoryCursor.puuid.in_(puuids)))
        ).scalars()
    }
    stored = {
        puuid: (count, oldest)
        for puuid, count, oldest in (
            await session.execute(
                select(MatchParticipant.puuid, func.count(), func.min(Match.game_creation))
                .join(Match, Match.match_id == MatchParticipant.match_id)
                .where(MatchParticipant.puuid.in_(puuids), Match.is_remake.is_(False))
                .group_by(MatchParticipant.puuid)
            )
        ).all()
    }

    # played_by reads storage only, so no Riot client is needed behind it.
    matches = MatchService(session, None, settings)  # type: ignore[arg-type]
    labeler = await lane_labeler(session) if scored_mode else None

    out: list[GroupMemberOut] = []
    for member in members:
        player = players.get(member.puuid)
        rows = await matches.played_by(member.puuid, queues=queues, limit=cap)
        row = _member_row(sd, member, player, ranks.get(member.puuid, []), rows)
        if scored_mode:
            _add_scores(row, rows)
            row.review = _review_out(await review_profile(session, member.puuid, queues=queues))
            row.lanes = [
                LaneRecordOut.model_validate(r, from_attributes=True)
                for r in await lane_records(
                    session, member.puuid, queues=queues, limit=cap, labeler=labeler
                )
            ]
        cursor = cursors.get(member.puuid)
        count, oldest = stored.get(member.puuid, (0, None))
        row.history = GroupHistoryOut(
            stored=count,
            oldest=oldest,
            read=cursor.offset if cursor else 0,
            exhausted=bool(cursor and cursor.exhausted),
            pending=member_pending(player, member, cursor, cap),
        )
        out.append(row)
    out.sort(key=_rank_key)

    return GroupResponse(
        slug=group.slug,
        name=group.name,
        created_at=epoch_ms(group.created_at),
        updated_at=epoch_ms(group.updated_at),
        can_edit=can_edit,
        max_members=MAX_MEMBERS,
        history_cap=cap,
        min_games=MIN_GAMES,
        queue=queue_key,
        queues=[GroupQueueOut(key=k, label=v[0]) for k, v in QUEUE_FILTERS.items()],
        scored_mode=scored_mode,
        members=out,
        together=await played_together(session, sd, puuids, queues),
        pending=sum(1 for r in out if r.history.pending),
    )


def _member_row(
    sd: StaticDataService,
    member: GroupMember,
    player: Player | None,
    entries: list[RankedEntry],
    rows: list[PlayedRow],
) -> GroupMemberOut:
    try:
        platform_label = resolve_platform(member.platform).label
    except UnknownPlatform:
        platform_label = member.platform.upper()
    # Ranks are shown only when they were read on the shard the player is on:
    # a row left from another shard would be someone else's standing there.
    ranked_here = player is not None and player.league_platform == member.platform
    infos = [to_rank_info(e) for e in entries] if ranked_here else []
    infos.sort(key=lambda r: (r.queue != SOLO, -r.numeric_rank))

    games = len(rows)
    wins = sum(1 for r in rows if r.win)
    row = GroupMemberOut(
        puuid=member.puuid,
        riot_id=player.riot_id if player else member.puuid[:8],
        game_name=player.game_name if player else None,
        tag_line=player.tag_line if player else None,
        platform=member.platform,
        platform_label=platform_label,
        profile_icon_url=sd.profile_icon(player.profile_icon_id) if player else None,
        summoner_level=player.summoner_level if player else None,
        label=member.label,
        added_at=epoch_ms(member.added_at),
        ranks=infos,
        rank_read_at=epoch_ms(player.league_fetched_at) if ranked_here else None,
        games=games,
        wins=wins,
        recent=[r.win for r in rows[:RECENT_RESULTS]],
    )
    if games < MIN_GAMES:
        row.withheld = (
            "No stored games here yet" if games == 0
            else f"{games} stored game{'s' if games != 1 else ''} here; figures need {MIN_GAMES}"
        )
        return row

    minutes = sum(max(1.0, r.game_duration / 60) for r in rows)
    kills = sum(r.kills for r in rows)
    deaths = sum(r.deaths for r in rows)
    assists = sum(r.assists for r in rows)
    row.win_rate = wins / games
    row.kda = (kills + assists) / max(1, deaths)
    row.avg_kills = kills / games
    row.avg_deaths = deaths / games
    row.avg_assists = assists / games
    row.cs_per_min = sum(r.total_minions for r in rows) / minutes
    row.damage_per_min = sum(r.damage_to_champions for r in rows) / minutes
    row.vision_per_min = sum(r.vision_score for r in rows) / minutes
    row.avg_minutes = minutes / games

    role_games: Counter[str] = Counter()
    role_wins: Counter[str] = Counter()
    for r in rows:
        if r.team_position:
            role_games[r.team_position] += 1
            role_wins[r.team_position] += int(r.win)
    role_total = sum(role_games.values())
    row.positions = [
        RoleShare(position=p, games=n, share=n / role_total, win_rate=role_wins[p] / n)
        for p, n in role_games.most_common()
    ]
    row.main_position = row.positions[0].position if row.positions else None
    row.champions = [
        GroupChampionOut(
            champion=ChampionRef(
                id=t.champion_id,
                name=sd.champion_name(t.champion_id),
                icon_url=sd.champion_icon(t.champion_id),
            ),
            games=t.games,
            wins=t.wins,
            win_rate=t.wins / t.games,
            kda=(t.kills + t.assists) / max(1, t.deaths),
        )
        for t in champion_totals(rows)[:3]
    ]
    return row


def _add_scores(row: GroupMemberOut, rows: list[PlayedRow]) -> None:
    scored = [r.performance_score for r in rows if r.performance_score is not None]
    row.scored_games = len(scored)
    if len(scored) >= MIN_GAMES:
        row.avg_score = sum(scored) / len(scored)
    row.score_profile = [
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
                    id=c.id, label=c.label, measures=c.measures, avg_percentile=c.avg_percentile
                )
                for c in p.components
            ],
            sample=p.sample,
            min_scored=MIN_SCORED_FOR_PROFILE,
        )
        for p in score_profile(rows)
    ]


def _review_out(profiles) -> list[RoleReviewOut]:
    return [
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
        for r in profiles
    ]


async def played_together(
    session: AsyncSession,
    sd: StaticDataService,
    puuids: Sequence[str],
    queues: Collection[int] | None,
) -> GroupTogetherOut:
    """Stored games where two or more of these players were on the same team.

    Opponents do not count: two members on opposite sides of a game were not
    playing together, whatever else they were doing.
    """
    together = GroupTogetherOut(min_pair_games=MIN_PAIR_GAMES)
    if len(puuids) < 2:
        return together
    stmt = (
        select(
            MatchParticipant.match_id,
            MatchParticipant.team_id,
            MatchParticipant.puuid,
            MatchParticipant.win,
            MatchParticipant.champion_id,
            MatchParticipant.team_position,
            MatchParticipant.kills,
            MatchParticipant.deaths,
            MatchParticipant.assists,
            Match.queue_id,
            Match.game_creation,
            Match.game_duration,
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.puuid.in_(list(puuids)), Match.is_remake.is_(False))
    )
    if queues is not None:
        stmt = stmt.where(Match.queue_id.in_(list(queues)))

    sides: dict[tuple[str, int], list] = defaultdict(list)
    for row in (await session.execute(stmt)).all():
        sides[(row.match_id, row.team_id)].append(row)
    shared = [rows for rows in sides.values() if len(rows) >= 2]
    if not shared:
        return together

    pairs: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for rows in shared:
        won = bool(rows[0].win)
        together.games += 1
        together.wins += int(won)
        for a, b in combinations(sorted(r.puuid for r in rows), 2):
            pairs[(a, b)][0] += 1
            pairs[(a, b)][1] += int(won)
    together.pairs = sorted(
        (
            GroupPairOut(a=a, b=b, games=games, wins=wins, win_rate=wins / games)
            for (a, b), (games, wins) in pairs.items()
            if games >= MIN_PAIR_GAMES
        ),
        key=lambda p: (-p.games, -p.win_rate),
    )
    shared.sort(key=lambda rows: rows[0].game_creation, reverse=True)
    together.recent = [
        TogetherGameOut(
            match_id=rows[0].match_id,
            queue_id=rows[0].queue_id,
            queue_name=sd.queue_name(rows[0].queue_id),
            game_creation=rows[0].game_creation,
            game_duration=rows[0].game_duration,
            win=bool(rows[0].win),
            players=[
                TogetherPlayerOut(
                    puuid=r.puuid,
                    champion=ChampionRef(
                        id=r.champion_id,
                        name=sd.champion_name(r.champion_id),
                        icon_url=sd.champion_icon(r.champion_id),
                    ),
                    position=r.team_position,
                    kills=r.kills,
                    deaths=r.deaths,
                    assists=r.assists,
                )
                for r in rows
            ],
        )
        for rows in shared[:TOGETHER_RECENT]
    ]
    return together
