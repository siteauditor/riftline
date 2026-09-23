"""Champion meta: tier lists and per-role statistics.

Everything here reads the rollups built by ``services.aggregate``; nothing calls
Riot. If the corpus is empty the endpoints say so plainly rather than returning
an empty list that looks like "no champions are any good".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbDep, SettingsDep, StaticDep
from app.api.schemas import ChampionRef, LobbyRanksOut, epoch_ms, lobby_ranks_out
from app.db.models import ChampionStat, Match
from app.services import seo
from app.services.aggregate import (
    ALL_BRACKETS,
    POSITIONS,
    TIER_MIN_GAMES,
    aggregated_slices,
    available_brackets,
    default_patch,
    lobby_rank_mix,
    tier_for,
    wilson_lower_bound,
    wilson_upper_bound,
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
    # The top of the same interval. With the low end it is the range the sample
    # supports, which is what the page draws.
    confidence_high: float = 1.0
    pick_rate: float
    ban_rate: float
    # None when the slice has too few champions for percentile banding to mean
    # anything. The UI shows that as "too thin to rank", not as a letter.
    tier: str | None = None
    avg_kda: float
    avg_cs_per_min: float
    avg_damage: float
    avg_vision: float
    # Over `timeline_games` only, the games whose timeline we hold.
    avg_gold_diff_14: float | None = None
    timeline_games: int = 0


class MetaResponse(BaseModel):
    patch: str
    queue_id: int
    position: str | None = None
    rank_bracket: str = "ALL"
    sample_matches: int
    min_games: int
    rows: list[ChampionMetaRow] = Field(default_factory=list)
    lobby_ranks: LobbyRanksOut | None = None


class CorpusSliceOut(BaseModel):
    patch: str
    queue_id: int
    matches: int


class CorpusResponse(BaseModel):
    slices: list[CorpusSliceOut]
    brackets: list[str] = Field(default_factory=list)
    total_matches: int
    # Epoch ms. The newest game held and when the last one was stored. The home
    # page states the age rather than "updated nightly": with an expired
    # development key the nightly crawl is skipped, and a schedule would claim
    # a freshness the data does not have.
    latest_game_at: int | None = None
    latest_ingest_at: int | None = None


def assign_tiers(rows: list[ChampionMetaRow]) -> None:
    """Stamp each row with its percentile tier within its own role.

    Rows arrive sorted best first. Banded per role rather than across the whole
    list: pooled, "All roles" at 20+ games on 16.18 gave about 19 S rows spread
    unevenly over the roles, when a reader takes S to mean the top of that role.

    See ``tier_for``: below MIN_ROWS_FOR_TIERS in a role a percentile says more
    about the length of the list than about the champions in it.
    """
    by_role: dict[str, list[ChampionMetaRow]] = {}
    for row in rows:
        by_role.setdefault(row.position, []).append(row)
    for group in by_role.values():
        total = len(group)
        for index, row in enumerate(group):
            row.tier = tier_for(index, total)


@router.get("/corpus", response_model=CorpusResponse)
async def get_corpus(db: DbDep) -> CorpusResponse:
    """What data has actually been aggregated. Useful before trusting a tier list."""
    slices = await aggregated_slices(db)
    latest_game, latest_ingest = (
        await db.execute(select(func.max(Match.game_creation), func.max(Match.ingested_at)))
    ).one()
    return CorpusResponse(
        slices=slices,
        brackets=await available_brackets(db),
        total_matches=sum(s["matches"] for s in slices),
        latest_game_at=latest_game,
        latest_ingest_at=epoch_ms(latest_ingest),
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
    min_games: int = Query(
        TIER_MIN_GAMES, ge=1, description="Drop champions below this sample size."
    ),
) -> MetaResponse:
    if position:
        position = position.upper()
        if position not in POSITIONS:
            raise HTTPException(400, f"position must be one of {', '.join(POSITIONS)}")

    if patch is None:
        patch = default_patch(await aggregated_slices(db), queue_id)
        if patch is None:
            raise HTTPException(
                404,
                "No aggregated data yet. Run `python -m scripts.ingest crawl` to "
                "collect matches, then `python -m scripts.ingest aggregate`.",
            )

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
            confidence_high=wilson_upper_bound(s.wins, s.games),
            pick_rate=s.games / s.pool_games if s.pool_games else 0.0,
            ban_rate=s.bans / s.pool_games if s.pool_games else 0.0,
            tier=None,
            avg_kda=(s.avg_kills + s.avg_assists) / max(0.5, s.avg_deaths),
            avg_cs_per_min=s.avg_cs_per_min,
            avg_damage=s.avg_damage,
            avg_vision=s.avg_vision,
            avg_gold_diff_14=s.avg_gold_diff_14,
            timeline_games=s.timeline_games,
        )
        for s in stats
    ]

    rows.sort(key=lambda r: r.confidence_win_rate, reverse=True)
    assign_tiers(rows)
    mix = await lobby_rank_mix(db, patch, queue_id, bracket)

    return MetaResponse(
        patch=patch,
        queue_id=queue_id,
        position=position,
        rank_bracket=bracket,
        sample_matches=sample,
        min_games=min_games,
        rows=rows,
        lobby_ranks=lobby_ranks_out(mix),
    )


# --- what search engines are told ---------------------------------------------


class PageOut(BaseModel):
    path: str
    kind: str
    indexable: bool
    # Epoch ms of the data behind the page, when it carries a time.
    lastmod: int | None = None
    # A page the prerender must produce, or the build is wrong.
    required: bool = False
    reason: str | None = None


class PagesResponse(BaseModel):
    """The prerenderer's manifest: every page, and which may be indexed."""

    origin: str
    index_patch: str | None = None
    pages: list[PageOut]


@router.get("/pages", response_model=PagesResponse)
async def get_pages(db: DbDep, sd: StaticDep, settings: SettingsDep) -> PagesResponse:
    patch, entries = await seo.pages(db, sd)
    return PagesResponse(
        origin=settings.site_origin,
        index_patch=patch,
        pages=[
            PageOut(
                path=p.path,
                kind=p.kind,
                indexable=p.indexable,
                lastmod=epoch_ms(p.lastmod),
                required=p.required,
                reason=p.reason,
            )
            for p in entries
        ],
    )


@router.get("/sitemap.xml", include_in_schema=False)
async def get_sitemap(db: DbDep, sd: StaticDep, settings: SettingsDep) -> Response:
    """The indexable pages, from the same list the prerenderer renders. nginx
    serves it at /sitemap.xml. An hour of caching: the numbers behind
    `lastmod` move once a night."""
    _, entries = await seo.pages(db, sd)
    return Response(
        content=seo.sitemap_xml(settings.site_origin, entries),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )
