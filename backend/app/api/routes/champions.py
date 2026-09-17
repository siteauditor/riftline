"""Champion detail: builds, runes, spells, counters and synergies.

Every number here comes from a precomputed rollup, so the whole page is a
handful of indexed reads and no Riot calls at all.

The build section reports one of two things, and says which via ``basis``.

A participant's item array records **inventory position, not purchase order**:
across the corpus the same boots turn up in all six slots at roughly equal
rates. From that alone we can only report the *sets* players finished with,
which is ``final_inventory``.

Once a match's timeline has been fetched the real purchase order is known, and
``builds.path`` carries the first three legendary completions in the order they
were actually bought. ``basis`` becomes ``purchase_order`` and the interface
drops its disclaimer, because the thing it was disclaiming is no longer true.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, StaticDep
from app.api.schemas import ChampionRef, ItemRef, RuneRef, SpellRef
from app.db.models import ChampionFacetStat, ChampionStat, MatchupStat, SynergyStat
from app.services.aggregate import (
    ALL_BRACKETS,
    POSITIONS,
    available_slices,
    tier_for,
    wilson_lower_bound,
)

router = APIRouter(prefix="/api/champions", tags=["champions"])

# Enough to be useful, small enough that the page stays one quick response.
FACET_LIMIT = 12
PAIR_LIMIT = 15


class ChampionInfo(ChampionRef):
    key: str | None = None
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    splash_url: str | None = None
    # Centred crop, for use as a page background.
    art_url: str | None = None
    tile_url: str | None = None


class PositionShare(BaseModel):
    position: str
    games: int
    share: float
    win_rate: float


class FacetEntry(BaseModel):
    """One thing a champion took, with how often and how it went."""

    ids: list[int]
    games: int
    wins: int
    win_rate: float
    # Share of this champion's games in the slice, not of all games.
    pick_rate: float
    items: list[ItemRef] = Field(default_factory=list)
    spells: list[SpellRef] = Field(default_factory=list)
    runes: list[RuneRef] = Field(default_factory=list)


class BuildSection(BaseModel):
    # Machine-readable caveat, so the UI phrases it rather than us hardcoding
    # copy. Flips to "purchase_order" once timelines give us a real path, and the
    # UI's final-inventory disclaimer disappears with it.
    basis: str = "final_inventory"
    complete: list[FacetEntry] = Field(default_factory=list)
    items: list[FacetEntry] = Field(default_factory=list)
    boots: list[FacetEntry] = Field(default_factory=list)
    # First three legendary completions, in the order they were actually bought.
    path: list[FacetEntry] = Field(default_factory=list)


class SkillSection(BaseModel):
    # Which abilities were maxed and in what order, e.g. [1, 3, 2] = Q then E then W.
    priority: list[FacetEntry] = Field(default_factory=list)
    # The exact level-up sequence. High cardinality, so usually thin.
    order: list[FacetEntry] = Field(default_factory=list)


class LaningSection(BaseModel):
    """How the laning phase goes, measured at minute 14.

    ``games`` is not the champion's game count: it is how many of those games
    had a timeline. On a partly backfilled corpus that gap is the difference
    between an average and a claim.
    """

    games: int = 0
    avg_score: float | None = None
    avg_gold_diff: float | None = None
    avg_cs_diff: float | None = None


class RuneSection(BaseModel):
    keystones: list[FacetEntry] = Field(default_factory=list)
    pages: list[FacetEntry] = Field(default_factory=list)


class PairEntry(BaseModel):
    champion: ChampionRef
    games: int
    wins: int
    win_rate: float
    confidence_win_rate: float
    # Only set for synergies: which lane the ally was in.
    position: str | None = None
    # From timelines, so null until the matchup's games have been backfilled.
    # Turns "you lose this" into "you lose this lane by 400 gold".
    avg_laning_score: float | None = None
    avg_gold_diff_14: float | None = None
    timeline_games: int = 0


class CounterSection(BaseModel):
    lane: list[PairEntry] = Field(default_factory=list)
    team: list[PairEntry] = Field(default_factory=list)


class ChampionOverview(BaseModel):
    games: int
    wins: int
    win_rate: float
    confidence_win_rate: float
    pick_rate: float
    ban_rate: float
    tier: str | None = None
    avg_kills: float
    avg_deaths: float
    avg_assists: float
    avg_kda: float
    avg_cs_per_min: float
    avg_gold: float
    avg_damage: float
    avg_vision: float


class ChampionDetail(BaseModel):
    champion: ChampionInfo
    patch: str
    queue_id: int
    position: str
    rank_bracket: str
    sample_matches: int
    min_games: int
    positions: list[PositionShare] = Field(default_factory=list)
    overview: ChampionOverview
    builds: BuildSection
    runes: RuneSection
    skills: SkillSection
    laning: LaningSection
    spells: list[FacetEntry] = Field(default_factory=list)
    counters: CounterSection
    synergies: list[PairEntry] = Field(default_factory=list)


def _facet_entry(row: ChampionFacetStat, sd, kind: str) -> FacetEntry:
    ids = list(row.facet_ids or [])
    entry = FacetEntry(
        ids=ids,
        games=row.games,
        wins=row.wins,
        win_rate=row.win_rate,
        pick_rate=row.pick_rate,
    )
    if kind in ("build", "item", "boots", "build_path"):
        entry.items = [
            ItemRef(id=i, name=sd.item_name(i), icon_url=sd.item_icon(i)) for i in ids
        ]
    elif kind == "spells":
        entry.spells = [
            SpellRef(id=s, name=sd.spell_name(s), icon_url=sd.spell_icon(s)) for s in ids
        ]
    elif kind in ("keystone", "rune_page"):
        # Stat shards are not in runesReforged.json, so rune_icon returns None
        # for them and the client renders a placeholder rather than a broken img.
        entry.runes = [RuneRef(id=r, icon_url=sd.rune_icon(r)) for r in ids]
    # Skill facets carry ability slots 1-4, which are not items, spells or runes.
    # They render from `ids` alone as Q/W/E/R, so they intentionally decorate
    # nothing here: an earlier catch-all `else` handed them rune icons.
    return entry


def _pair_entry(
    champion_id: int,
    games: int,
    wins: int,
    sd,
    position: str | None = None,
    *,
    avg_laning_score: float | None = None,
    avg_gold_diff_14: float | None = None,
    timeline_games: int = 0,
) -> PairEntry:
    return PairEntry(
        champion=ChampionRef(
            id=champion_id,
            name=sd.champion_name(champion_id),
            icon_url=sd.champion_icon(champion_id),
        ),
        games=games,
        wins=wins,
        win_rate=wins / games if games else 0.0,
        confidence_win_rate=wilson_lower_bound(wins, games),
        position=position,
        avg_laning_score=avg_laning_score,
        avg_gold_diff_14=avg_gold_diff_14,
        timeline_games=timeline_games,
    )


@router.get("/{champion_id}", response_model=ChampionDetail)
async def get_champion(
    champion_id: int,
    db: DbDep,
    sd: StaticDep,
    patch: str | None = Query(None, description="Defaults to the newest patch held."),
    queue_id: int = Query(420),
    position: str | None = Query(None, description="Defaults to the champion's main role."),
    bracket: str = Query(ALL_BRACKETS, description="Crawl provenance, not a measured rank."),
    min_games: int = Query(5, ge=1),
) -> ChampionDetail:
    bracket = (bracket or ALL_BRACKETS).upper()
    if position:
        position = position.upper()
        if position not in POSITIONS:
            raise HTTPException(400, f"position must be one of {', '.join(POSITIONS)}")

    if patch is None:
        matching = [s for s in await available_slices(db) if s["queue_id"] == queue_id]
        if not matching:
            raise HTTPException(
                404,
                "No aggregated data yet. Run `python -m scripts.ingest crawl` then "
                "`python -m scripts.ingest aggregate`.",
            )
        patch = matching[0]["patch"]

    slice_where = (
        ChampionStat.patch == patch,
        ChampionStat.queue_id == queue_id,
        ChampionStat.rank_bracket == bracket,
    )

    # Every role this champion is played in, so the UI can offer a role switch
    # and default to where they are actually played.
    role_rows = list(
        (
            await db.execute(
                select(ChampionStat).where(
                    *slice_where,
                    ChampionStat.champion_id == champion_id,
                    ChampionStat.team_position.in_(POSITIONS),
                )
            )
        ).scalars()
    )
    if not role_rows:
        raise HTTPException(
            404,
            f"No data for this champion on patch {patch} ({bracket}, queue {queue_id}). "
            "Ingest more matches, or try another patch.",
        )

    role_rows.sort(key=lambda r: r.games, reverse=True)
    total_role_games = sum(r.games for r in role_rows) or 1
    positions = [
        PositionShare(
            position=r.team_position,
            games=r.games,
            share=r.games / total_role_games,
            win_rate=r.win_rate,
        )
        for r in role_rows
    ]

    chosen = next((r for r in role_rows if r.team_position == position), None) if position else None
    if position and chosen is None:
        raise HTTPException(
            404, f"This champion has no recorded games at {position} on patch {patch}."
        )
    stat = chosen or role_rows[0]
    position = stat.team_position

    # Tier is this champion's standing among everyone in the same role, so it
    # has to be computed against the field rather than in isolation.
    peers = list(
        (
            await db.execute(
                select(ChampionStat.champion_id, ChampionStat.wins, ChampionStat.games).where(
                    *slice_where,
                    ChampionStat.team_position == position,
                    ChampionStat.games >= min_games,
                )
            )
        ).all()
    )
    ranked = sorted(
        peers, key=lambda p: wilson_lower_bound(p.wins, p.games), reverse=True
    )
    index = next((i for i, p in enumerate(ranked) if p.champion_id == champion_id), -1)
    tier = tier_for(index, len(ranked)) if index >= 0 else None

    overview = ChampionOverview(
        games=stat.games,
        wins=stat.wins,
        win_rate=stat.win_rate,
        confidence_win_rate=wilson_lower_bound(stat.wins, stat.games),
        pick_rate=stat.pick_rate,
        ban_rate=stat.bans / stat.pool_games if stat.pool_games else 0.0,
        tier=tier,
        avg_kills=stat.avg_kills,
        avg_deaths=stat.avg_deaths,
        avg_assists=stat.avg_assists,
        avg_kda=(stat.avg_kills + stat.avg_assists) / max(0.5, stat.avg_deaths),
        avg_cs_per_min=stat.avg_cs_per_min,
        avg_gold=stat.avg_gold,
        avg_damage=stat.avg_damage,
        avg_vision=stat.avg_vision,
    )

    # --- facets -------------------------------------------------------------
    facet_rows = list(
        (
            await db.execute(
                select(ChampionFacetStat).where(
                    ChampionFacetStat.patch == patch,
                    ChampionFacetStat.queue_id == queue_id,
                    ChampionFacetStat.rank_bracket == bracket,
                    ChampionFacetStat.champion_id == champion_id,
                    ChampionFacetStat.team_position == position,
                    # The aggregation already applied its own floor, but the
                    # control is labelled "min games" and a filter that silently
                    # skips half the page is worse than no filter at all.
                    ChampionFacetStat.games >= min_games,
                )
            )
        ).scalars()
    )
    grouped: dict[str, list[ChampionFacetStat]] = defaultdict(list)
    for row in facet_rows:
        grouped[row.facet].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r.games, reverse=True)

    def entries(kind: str, limit: int = FACET_LIMIT) -> list[FacetEntry]:
        return [_facet_entry(r, sd, kind) for r in grouped.get(kind, [])[:limit]]

    path = entries("build_path")
    builds = BuildSection(
        # The whole point of Group B: once a real purchase order exists, stop
        # describing final inventories as if they were builds.
        basis="purchase_order" if path else "final_inventory",
        complete=entries("build"),
        items=entries("item"),
        boots=entries("boots"),
        path=path,
    )
    runes = RuneSection(keystones=entries("keystone"), pages=entries("rune_page"))
    skills = SkillSection(
        priority=entries("skill_priority"), order=entries("skill_order")
    )
    laning = LaningSection(
        games=stat.timeline_games,
        avg_score=stat.avg_laning_score,
        avg_gold_diff=stat.avg_gold_diff_14,
        avg_cs_diff=stat.avg_cs_diff_14,
    )

    # --- matchups and synergies --------------------------------------------
    matchup_rows = list(
        (
            await db.execute(
                select(MatchupStat).where(
                    MatchupStat.patch == patch,
                    MatchupStat.queue_id == queue_id,
                    MatchupStat.rank_bracket == bracket,
                    MatchupStat.champion_id == champion_id,
                    MatchupStat.team_position == position,
                    MatchupStat.games >= min_games,
                )
            )
        ).scalars()
    )
    by_scope: dict[str, list[PairEntry]] = defaultdict(list)
    for row in matchup_rows:
        by_scope[row.scope].append(
            _pair_entry(
                row.enemy_champion_id, row.games, row.wins, sd,
                avg_laning_score=row.avg_laning_score,
                avg_gold_diff_14=row.avg_gold_diff_14,
                timeline_games=row.timeline_games,
            )
        )
    # Worst first: "weak against" is the question people come here with, and
    # ordering by the confidence bound keeps a 0-2 fluke from topping the list.
    for rows_ in by_scope.values():
        rows_.sort(key=lambda p: p.confidence_win_rate)

    synergy_rows = list(
        (
            await db.execute(
                select(SynergyStat).where(
                    SynergyStat.patch == patch,
                    SynergyStat.queue_id == queue_id,
                    SynergyStat.rank_bracket == bracket,
                    SynergyStat.champion_id == champion_id,
                    SynergyStat.team_position == position,
                    SynergyStat.games >= min_games,
                )
            )
        ).scalars()
    )
    synergies = [
        _pair_entry(r.ally_champion_id, r.games, r.wins, sd, position=r.ally_position)
        for r in synergy_rows
    ]
    # Best first: synergy is a question about who to pair with, not avoid.
    synergies.sort(key=lambda p: p.confidence_win_rate, reverse=True)

    champion = sd.champion(champion_id)
    return ChampionDetail(
        champion=ChampionInfo(
            id=champion_id,
            name=sd.champion_name(champion_id),
            icon_url=sd.champion_icon(champion_id),
            key=champion.key if champion else None,
            title=champion.title if champion else None,
            tags=champion.tags if champion else [],
            splash_url=sd.champion_splash(champion_id),
            art_url=sd.champion_art(champion_id),
            tile_url=sd.champion_tile(champion_id),
        ),
        patch=patch,
        queue_id=queue_id,
        position=position,
        rank_bracket=bracket,
        sample_matches=stat.pool_games,
        min_games=min_games,
        positions=positions,
        overview=overview,
        builds=builds,
        runes=runes,
        skills=skills,
        laning=laning,
        spells=entries("spells"),
        counters=CounterSection(
            lane=by_scope.get("LANE", [])[:PAIR_LIMIT],
            team=by_scope.get("TEAM", [])[:PAIR_LIMIT],
        ),
        synergies=synergies[:PAIR_LIMIT],
    )
