"""Champion meta: tier lists and per-role statistics.

Everything here reads the rollups built by ``services.aggregate``; nothing calls
Riot. If the corpus is empty the endpoints say so plainly rather than returning
an empty list that looks like "no champions are any good".
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbDep, SettingsDep, StaticDep
from app.api.schemas import ChampionRef, LobbyRanksOut, epoch_ms, lobby_ranks_out
from app.db.models import ChampionStat, Match
from app.services import seo
from app.services.aggregate import (
    ALL_BRACKETS,
    MIN_LANING_TIMELINES,
    POSITIONS,
    TIER_MIN_GAMES,
    available_brackets,
    cached_aggregated_slices,
    cached_lobby_rank_mix,
    default_patch,
    poolable_patches,
    rates_differ,
    tier_for,
    wilson_lower_bound,
    wilson_upper_bound,
)

log = logging.getLogger(__name__)

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
    # The row's place in its role, S to D, among the champions with
    # `tier_min_games` or more in the role. None under that floor, or when the
    # role has too few such champions for a percentile to mean anything.
    tier: str | None = None
    avg_kda: float
    avg_cs_per_min: float
    avg_damage: float
    avg_vision: float
    # Over `timeline_games` only, the games whose timeline we hold, and null
    # under `MIN_LANING_TIMELINES` of them.
    avg_gold_diff_14: float | None = None
    timeline_games: int = 0
    # The same champion and role on `previous_patch`, and whether the win rate
    # moved by more than chance (the two 95% ranges stop overlapping). Most rows
    # never move by that test, which is why the page marks only those that do.
    previous_win_rate: float | None = None
    previous_games: int = 0
    win_rate_moved: bool = False


class MetaResponse(BaseModel):
    patch: str
    queue_id: int
    position: str | None = None
    rank_bracket: str = "ALL"
    sample_matches: int
    min_games: int
    rows: list[ChampionMetaRow] = Field(default_factory=list)
    lobby_ranks: LobbyRanksOut | None = None
    # The close earlier patch each row is compared with, when one is held.
    previous_patch: str | None = None
    # The games a champion needs in a role to carry a letter, whatever
    # `min_games` shows: the field every page's letters are places in.
    tier_min_games: int = TIER_MIN_GAMES
    # Rows whose whole range sits above 50%, and below it: what the games
    # actually separate from an average pick. On 16.18 that was 8 and 8 of 247
    # rows (measured 2026-09-24), while percentile letters give 28 an S, so the
    # page states these counts beside the letters.
    separated_above: int = 0
    separated_below: int = 0
    # Why `rows` is empty, when it is: no champion has `min_games` in this
    # slice. `most_games` is the most any champion has, so the page can offer a
    # floor that shows something.
    empty_reason: Literal["min_games"] | None = None
    most_games: int = 0


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

    Rows arrive sorted best first, and are the field: the caller passes only the
    rows with `TIER_MIN_GAMES` or more. Banded per role rather than across the
    whole list: pooled, "All roles" at 20+ games on 16.18 gave about 19 S rows
    spread unevenly over the roles, when a reader takes S to mean the top of
    that role.

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


_corpus_held: tuple[float, CorpusResponse] | None = None


@router.get("/corpus", response_model=CorpusResponse)
async def get_corpus(db: DbDep, settings: SettingsDep) -> CorpusResponse:
    """What data has actually been aggregated. Useful before trusting a tier list.

    Kept for `ttl_corpus` seconds: the tier list, the draft and every slice
    control ask for it, and it took 0.57 s on production (2026-09-24).
    """
    global _corpus_held
    now = time.monotonic()
    if _corpus_held is not None and now - _corpus_held[0] < settings.ttl_corpus:
        return _corpus_held[1]
    slices = await cached_aggregated_slices(db)
    # Two queries, not one: SQLite answers a lone max() from an index and
    # scans the table for two in one statement (239 ms against under 1).
    latest_game = (await db.execute(select(func.max(Match.game_creation)))).scalar()
    latest_ingest = (await db.execute(select(func.max(Match.ingested_at)))).scalar()
    answer = CorpusResponse(
        slices=slices,
        brackets=await available_brackets(db),
        total_matches=sum(s["matches"] for s in slices),
        latest_game_at=latest_game,
        latest_ingest_at=epoch_ms(latest_ingest),
    )
    _corpus_held = (now, answer)
    return answer


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

    slices = await cached_aggregated_slices(db)
    if patch is None:
        patch = default_patch(slices, queue_id)
        if patch is None:
            # The ingest hint is for whoever runs the server, not for a reader.
            log.warning(
                "tier list: nothing aggregated for queue %s; run `python -m scripts.ingest "
                "crawl` then `python -m scripts.ingest aggregate`", queue_id
            )
            raise HTTPException(404, "Riftline holds no ranked games for this queue yet.")

    bracket = (bracket or ALL_BRACKETS).upper()
    # Every row in the slice, whatever `min_games` says: the letters are places
    # in the `TIER_MIN_GAMES` field, and a floor chosen for display must not
    # re-band them. At 5 games instead of 20, 81 of 175 rows changed letter
    # and disagreed with the champion page one click away (2026-09-24).
    stmt = select(ChampionStat).where(
        ChampionStat.patch == patch,
        ChampionStat.queue_id == queue_id,
        ChampionStat.rank_bracket == bracket,
        ChampionStat.games > 0,
    )
    stmt = stmt.where(
        ChampionStat.team_position == position
        if position
        else ChampionStat.team_position.in_(POSITIONS)
    )
    stats = list((await db.execute(stmt)).scalars())

    if not stats:
        raise HTTPException(404, f"Riftline holds no ranked games on patch {patch} yet.")

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
            avg_gold_diff_14=(
                s.avg_gold_diff_14 if s.timeline_games >= MIN_LANING_TIMELINES else None
            ),
            timeline_games=s.timeline_games,
        )
        for s in stats
    ]

    # The trend: each row against the close earlier patch, as the champion
    # page's change figure, so the list and the page agree.
    held = [s["patch"] for s in slices if s["queue_id"] == queue_id]
    close = poolable_patches(held or [patch], patch)
    previous_patch = close[1] if len(close) > 1 else None
    if previous_patch:
        before = {
            (c, pos): (w, g)
            for c, pos, w, g in (
                await db.execute(
                    select(
                        ChampionStat.champion_id,
                        ChampionStat.team_position,
                        ChampionStat.wins,
                        ChampionStat.games,
                    ).where(
                        ChampionStat.patch == previous_patch,
                        ChampionStat.queue_id == queue_id,
                        ChampionStat.rank_bracket == bracket,
                        ChampionStat.games > 0,
                    )
                )
            ).all()
        }
        for row in rows:
            held_before = before.get((row.champion.id, row.position))
            if held_before:
                wins, games = held_before
                row.previous_win_rate = wins / games
                row.previous_games = games
                row.win_rate_moved = rates_differ(row.wins, row.games, wins, games)

    rows.sort(key=lambda r: r.confidence_win_rate, reverse=True)
    assign_tiers([r for r in rows if r.games >= TIER_MIN_GAMES])
    shown = [r for r in rows if r.games >= min_games]
    mix = await cached_lobby_rank_mix(db, patch, queue_id, bracket)

    return MetaResponse(
        patch=patch,
        queue_id=queue_id,
        position=position,
        rank_bracket=bracket,
        sample_matches=sample,
        min_games=min_games,
        rows=shown,
        lobby_ranks=lobby_ranks_out(mix),
        previous_patch=previous_patch,
        separated_above=sum(1 for r in shown if r.confidence_win_rate >= 0.5),
        separated_below=sum(1 for r in shown if r.confidence_high <= 0.5),
        # An empty list is an answer, not an error: the floor is above what the
        # slice holds, and the page offers a lower one.
        empty_reason=None if shown else "min_games",
        most_games=max((r.games for r in rows), default=0),
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
