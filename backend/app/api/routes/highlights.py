"""Highlights for the home page, read from stored scores.

Nothing here calls Riot. The week's best games are already scored on disk, and
the page links each one to its full scoreboard at ``/api/matches/{id}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import DbDep, StaticDep
from app.api.routes.meta import TierListChampion
from app.api.schemas import BadgeOut, _badges_out
from app.services.highlights import HIGHLIGHT_DAYS, best_games

router = APIRouter(prefix="/api/highlights", tags=["highlights"])


class BestGameOut(BaseModel):
    match_id: str
    # The shard the game was played on, lower case, for the profile link.
    platform: str
    puuid: str
    game_name: str | None = None
    tag_line: str | None = None
    champion: TierListChampion
    position: str
    score: float
    # Placement in its lobby, 1 to 10.
    placement: int | None = None
    kills: int
    deaths: int
    assists: int
    win: bool
    badges: list[BadgeOut] = Field(default_factory=list)
    game_creation: int
    game_duration: int


class BestGamesResponse(BaseModel):
    queue_id: int
    queue_name: str
    days: int
    since: int
    # What the games were chosen from.
    scored_players: int
    scored_games: int
    games: list[BestGameOut] = Field(default_factory=list)


@router.get("/best-games", response_model=BestGamesResponse)
async def get_best_games(
    db: DbDep,
    sd: StaticDep,
    days: int = Query(HIGHLIGHT_DAYS, ge=1, le=30),
    queue_id: int = Query(420),
) -> BestGamesResponse:
    """The highest Riftline score in each role over the last few days."""
    found = await best_games(db, queue_id=queue_id, days=days)
    return BestGamesResponse(
        queue_id=queue_id,
        queue_name=sd.queue_name(queue_id),
        days=days,
        since=found.since_ms,
        scored_players=found.scored_players,
        scored_games=found.scored_games,
        games=[
            BestGameOut(
                match_id=p.match_id,
                platform=p.match.platform_id.lower(),
                puuid=p.puuid,
                game_name=p.riot_id_game_name,
                tag_line=p.riot_id_tagline,
                champion=TierListChampion(
                    id=p.champion_id,
                    name=sd.champion_name(p.champion_id),
                    icon_url=sd.champion_icon(p.champion_id),
                    tile_url=sd.champion_tile(p.champion_id),
                ),
                position=p.team_position,
                score=p.performance_score,
                placement=p.performance_rank,
                kills=p.kills,
                deaths=p.deaths,
                assists=p.assists,
                win=p.win,
                badges=_badges_out(p, p.match),
                game_creation=p.match.game_creation,
                game_duration=p.match.game_duration,
            )
            for p in found.picks
        ],
    )
