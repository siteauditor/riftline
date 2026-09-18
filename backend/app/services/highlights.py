"""The best games of the week by Riftline score, one per role.

One per role rather than the five highest overall, because the overall list is
all carries: on 2026-09-19 the eight highest scores of the week were all top,
mid and bot laners. A support scoring 9.5 is the clearest evidence that the
score is not a kill count, and the overall list never shows one.

Nothing here calls Riot, and nothing is stored: the scores already are.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.db.models import Match, MatchParticipant
from app.services.aggregate import POSITIONS

HIGHLIGHT_DAYS = 7
# Read per role before choosing, because one player may top several roles or
# several games in one role. Twenty-five leaves room for both.
CANDIDATES_PER_ROLE = 25
DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class BestGames:
    # At most one per role, in role order, each with its match and lobby loaded.
    picks: list[MatchParticipant]
    # What the picks were chosen from, so the page can say so.
    scored_players: int
    scored_games: int
    since_ms: int


async def best_games(
    session: AsyncSession,
    *,
    queue_id: int,
    days: int = HIGHLIGHT_DAYS,
    now_ms: int | None = None,
) -> BestGames:
    """The highest score in each role over the window, one game per player."""
    since = (now_ms if now_ms is not None else int(time.time() * 1000)) - days * DAY_MS
    in_window = (
        Match.queue_id == queue_id,
        Match.game_creation >= since,
        Match.is_remake.is_(False),
        MatchParticipant.performance_score.is_not(None),
    )

    players, games = (
        await session.execute(
            select(func.count(MatchParticipant.id), func.count(func.distinct(Match.match_id)))
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(*in_window)
        )
    ).one()

    # Candidates as plain tuples, every role in one pass. Loading them as ORM
    # rows dragged each candidate's match along with its full `raw` payload,
    # and that was most of 400 ms measured on the local corpus.
    ranked = (
        select(
            MatchParticipant.id,
            MatchParticipant.puuid,
            MatchParticipant.team_position,
            MatchParticipant.performance_score,
            Match.game_creation,
            func.row_number()
            .over(
                partition_by=MatchParticipant.team_position,
                # Newest first on a tie. Ties at the top are real: two games
                # shared the week's best score, 9.78, on 2026-09-19.
                order_by=(
                    MatchParticipant.performance_score.desc(),
                    Match.game_creation.desc(),
                ),
            )
            .label("place"),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(*in_window, MatchParticipant.team_position.in_(POSITIONS))
        .subquery()
    )
    candidates = (
        await session.execute(
            select(
                ranked.c.id,
                ranked.c.puuid,
                ranked.c.team_position,
                ranked.c.performance_score,
                ranked.c.game_creation,
            ).where(ranked.c.place <= CANDIDATES_PER_ROLE)
        )
    ).all()

    # Highest score first across all roles, so a player who tops two roles is
    # shown in the one they scored higher in and the other role falls to its
    # next best player.
    candidates.sort(key=lambda c: (-c.performance_score, -c.game_creation, c.id))
    roles: set[str] = set()
    people: set[str] = set()
    chosen: list[int] = []
    for c in candidates:
        if c.team_position in roles or c.puuid in people:
            continue
        roles.add(c.team_position)
        people.add(c.puuid)
        chosen.append(c.id)

    picks = list(
        (
            await session.execute(
                select(MatchParticipant)
                .where(MatchParticipant.id.in_(chosen))
                # The whole lobby, because two badge explanations are shares of
                # the team's totals. Not the raw payload, which nothing here
                # reads.
                .options(
                    selectinload(MatchParticipant.match)
                    .options(defer(Match.raw), defer(Match.teams))
                    .selectinload(Match.participants)
                )
            )
        ).scalars()
    )
    picks.sort(key=lambda p: POSITIONS.index(p.team_position))

    return BestGames(
        picks=picks, scored_players=players, scored_games=games, since_ms=since
    )


__all__ = ["HIGHLIGHT_DAYS", "BestGames", "best_games"]
