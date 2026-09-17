"""Champion meta: tier lists and per-role statistics.

Everything here reads the rollups built by ``services.aggregate``; nothing calls
Riot. If the corpus is empty the endpoints say so plainly rather than returning
an empty list that looks like "no champions are any good".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, StaticDep
from app.api.schemas import ChampionRef
from app.db.models import ChampionStat
from app.services.aggregate import (
    ALL_BRACKETS,
    POSITIONS,
    available_brackets,
    available_slices,
    tier_for,
    wilson_lower_bound,
)

router = APIRouter(prefix="/api/meta", tags=["meta"])


class TierListChampion(ChampionRef):
    """A champion in the tier list, carrying square key art.

    Kept off the base ``ChampionRef`` on purpose: that type appears ten times
    per match row, so putting art on it would add two hundred unused URLs to
    every page of match history.
    """

    tile_url: str | None = None


class ChampionMetaRow(BaseModel):
    champion: TierListChampion
    position: str
    games: int
    wins: int
    win_rate: float
    # Defensible win rate at this sample size; what the list is ordered by.
    confidence_win_rate: float
    pick_rate: float
    ban_rate: float
    # None when the slice has too few champions for percentile banding to mean
    # anything. The UI shows that as "too thin to rank", not as a letter.
    tier: str | None = None
    avg_kda: float
    avg_cs_per_min: float
    avg_damage: float
    avg_vision: float


class MetaResponse(BaseModel):
    patch: str
    queue_id: int
    position: str | None = None
    rank_bracket: str = "ALL"
    sample_matches: int
    min_games: int
    rows: list[ChampionMetaRow] = Field(default_factory=list)


class CorpusResponse(BaseModel):
    slices: list[dict]
    brackets: list[str] = Field(default_factory=list)
    total_matches: int


def assign_tiers(rows: list[ChampionMetaRow]) -> None:
    """Stamp each row with its percentile tier, or leave it unranked.

    See ``tier_for``: below MIN_ROWS_FOR_TIERS a percentile says more about the
    length of the list than about the champions in it.
    """
    total = len(rows)
    for index, row in enumerate(rows):
        row.tier = tier_for(index, total)


@router.get("/corpus", response_model=CorpusResponse)
async def get_corpus(db: DbDep) -> CorpusResponse:
    """What data has actually been ingested. Useful before trusting a tier list."""
    slices = await available_slices(db)
    return CorpusResponse(
        slices=slices,
        brackets=await available_brackets(db),
        total_matches=sum(s["matches"] for s in slices),
    )


@router.get("/champions", response_model=MetaResponse)
async def get_champion_meta(
    db: DbDep,
    sd: StaticDep,
    patch: str | None = Query(None, description="Defaults to the newest patch held."),
    queue_id: int = Query(420),
    position: str | None = Query(None, description="TOP, JUNGLE, MIDDLE, BOTTOM or UTILITY."),
    bracket: str = Query(
        ALL_BRACKETS,
        description="Crawl provenance, e.g. CHALLENGER. Not a measured lobby rank.",
    ),
    min_games: int = Query(20, ge=1, description="Drop champions below this sample size."),
) -> MetaResponse:
    if position:
        position = position.upper()
        if position not in POSITIONS:
            raise HTTPException(400, f"position must be one of {', '.join(POSITIONS)}")

    if patch is None:
        slices = await available_slices(db)
        matching = [s for s in slices if s["queue_id"] == queue_id]
        if not matching:
            raise HTTPException(
                404,
                "No aggregated data yet. Run `python -m scripts.ingest crawl` to "
                "collect matches, then `python -m scripts.ingest aggregate`.",
            )
        patch = matching[0]["patch"]

    bracket = (bracket or ALL_BRACKETS).upper()
    stmt = select(ChampionStat).where(
        ChampionStat.patch == patch,
        ChampionStat.queue_id == queue_id,
        ChampionStat.rank_bracket == bracket,
        ChampionStat.games >= min_games,
    )
    stmt = stmt.where(
        ChampionStat.team_position == position
        if position
        else ChampionStat.team_position.in_(POSITIONS)
    )
    stats = list((await db.execute(stmt)).scalars())

    if not stats:
        raise HTTPException(
            404,
            f"No champion has {min_games}+ games on patch {patch} "
            f"({bracket}, queue {queue_id}). "
            "Ingest more matches or lower min_games.",
        )

    sample = max((s.pool_games for s in stats), default=0)
    rows = [
        ChampionMetaRow(
            champion=TierListChampion(
                id=s.champion_id,
                name=sd.champion_name(s.champion_id),
                icon_url=sd.champion_icon(s.champion_id),
                tile_url=sd.champion_tile(s.champion_id),
            ),
            position=s.team_position,
            games=s.games,
            wins=s.wins,
            win_rate=s.wins / s.games if s.games else 0.0,
            confidence_win_rate=wilson_lower_bound(s.wins, s.games),
            pick_rate=s.games / s.pool_games if s.pool_games else 0.0,
            ban_rate=s.bans / s.pool_games if s.pool_games else 0.0,
            tier=None,
            avg_kda=(s.avg_kills + s.avg_assists) / max(0.5, s.avg_deaths),
            avg_cs_per_min=s.avg_cs_per_min,
            avg_damage=s.avg_damage,
            avg_vision=s.avg_vision,
        )
        for s in stats
    ]

    rows.sort(key=lambda r: r.confidence_win_rate, reverse=True)
    assign_tiers(rows)

    return MetaResponse(
        patch=patch,
        queue_id=queue_id,
        position=position,
        rank_bracket=bracket,
        sample_matches=sample,
        min_games=min_games,
        rows=rows,
    )
