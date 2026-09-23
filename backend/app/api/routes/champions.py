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

import logging
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbDep, StaticDep
from app.api.routes.items import CHAMPION_MIN_BUYERS
from app.api.schemas import (
    ChampionRef,
    ItemRef,
    LobbyRanksOut,
    RuneRef,
    SpellRef,
    lobby_ranks_out,
    rune_ref,
)
from app.db.models import (
    ChampionFacetStat,
    ChampionStat,
    ItemChampionStat,
    Match,
    MatchParticipant,
    MatchupStat,
    RankedEntry,
    SynergyStat,
)
from app.services.aggregate import (
    ALL_BRACKETS,
    MIN_LANE_TIMELINES,
    MIN_LANING_TIMELINES,
    POSITIONS,
    TIER_MIN_GAMES,
    aggregated_slices,
    cached_lobby_rank_mix,
    default_patch,
    poolable_patches,
    tier_for,
    wilson_lower_bound,
    wilson_upper_bound,
    win_as_int,
)
from app.services.evidence import (
    ALLY_STRENGTH,
    LANE_STRENGTH,
    TEAM_STRENGTH,
    Call,
    OwnRates,
    parts_by_patch,
    read_records,
)
from app.services.skins import MIN_CHAMPION_SIGHTINGS, champion_skin_counts
from app.services.static_data import Ability, StaticDataService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/champions", tags=["champions"])

# Enough to be useful, small enough that the page stays one quick response.
# Matchups and synergies are not capped: at 15 most opponents could not be
# looked up at all, and a full list for one role is a few kilobytes.
FACET_LIMIT = 12


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
    # The Wilson range of the win rate. Facets are listed by how often they were
    # taken, and a rate over five games, coloured gold from 55%, said more than
    # its sample could.
    range_low: float = 0.0
    range_high: float = 1.0
    # Items only: the win rate against the other items this champion bought in
    # the same slot, from the item guide's rollup (every role, games with a
    # timeline), and the buyers it stands on; null under the item guide's floor.
    # The final inventory favours winners, who finish more items: items ran 2.3
    # points above their champion's own rate on 16.18 (2026-09-24).
    slot_delta: float | None = None
    slot_buyers: int = 0
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
    # The ability taken at level 1, one slot per entry.
    first: list[FacetEntry] = Field(default_factory=list)


class LaningSection(BaseModel):
    """How the laning phase goes, measured at minute 14.

    ``games`` is not the champion's game count: it is how many of those games
    had a timeline. On a partly backfilled corpus that gap is the difference
    between an average and a claim. The averages are null under ``min_games``
    of them, as the tier list's gold column and the draft's laning figures are.
    """

    games: int = 0
    min_games: int = MIN_LANING_TIMELINES
    avg_score: float | None = None
    avg_gold_diff: float | None = None
    avg_cs_diff: float | None = None


class RuneSection(BaseModel):
    keystones: list[FacetEntry] = Field(default_factory=list)
    pages: list[FacetEntry] = Field(default_factory=list)


class PairEntry(BaseModel):
    """One record against an opponent or beside an ally, read as the draft reads it.

    Over the patch shown and the close one before it, each patch against the
    champion's own rate on that patch. Ranked by the raw record, the hardest
    five lanes on each of the 31 busiest local pages were all level by this
    reading, and 22 of 155 sat at or above the champion's own rate
    (2026-09-24).
    """

    champion: ChampionRef
    games: int
    wins: int
    win_rate: float
    # The champion's own rate over the same patches: what the record is read against.
    own_rate: float = 0.0
    # The posterior gap from `own_rate`, as a fraction, and whether it is far
    # enough from even to call (90% on one side). Pairs are ordered by `lift`.
    lift: float = 0.0
    call: Call = "level"
    patches: list[str] = Field(default_factory=list)
    # The Wilson range of the raw record, kept one release for open pages.
    confidence_win_rate: float
    confidence_high: float = 1.0
    # Only set for allies: the lane the ally was in most often.
    position: str | None = None
    # From timelines, so null until the matchup's games have been backfilled,
    # and under `MIN_LANE_TIMELINES` of them.
    # Turns "you lose this" into "you lose this lane by 400 gold".
    avg_laning_score: float | None = None
    avg_gold_diff_14: float | None = None
    timeline_games: int = 0


class CounterSection(BaseModel):
    lane: list[PairEntry] = Field(default_factory=list)
    team: list[PairEntry] = Field(default_factory=list)


class PairModelOut(BaseModel):
    """The prior each kind of record is read with, in games, so the page can say
    it: a record of that many games counts for half."""

    lane_strength: float = LANE_STRENGTH
    team_strength: float = TEAM_STRENGTH
    ally_strength: float = ALLY_STRENGTH


class PatchChange(BaseModel):
    """The same champion, role and bracket on the patch before.

    Measured on 2026-09-21: of 760 champion and role rows held on both 16.17
    and 16.18, the win rate moved 20 points or more on 293, and 2 of those
    moves survive a test for chance. So a change is published only where the
    two 95% Wilson intervals stop overlapping, and ``*_moved`` says when that
    is. Pick rate stands on the whole slice, so 32 of its moves survive.
    """

    patch: str
    games: int
    win_rate: float
    pick_rate: float
    win_rate_moved: bool = False
    pick_rate_moved: bool = False


class ChampionOverview(BaseModel):
    games: int
    wins: int
    win_rate: float
    confidence_win_rate: float
    # The top of the same range: the page shows the range, as the tier list does.
    confidence_high: float = 1.0
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
    # Null on the oldest patch held, or where the role was not played before.
    previous: PatchChange | None = None


class ChampionDetail(BaseModel):
    champion: ChampionInfo
    patch: str
    queue_id: int
    position: str
    rank_bracket: str
    sample_matches: int
    min_games: int
    # Set when the slice asked for had no games and another was served: "role"
    # when the champion has no games in the asked role (the main role is
    # served), "patch" when the asked patch is not held or the champion has no
    # games on it (the default patch is served). The page says so, with what
    # was asked. A 404 here used to open the page on its story, silently.
    fallback: Literal["role", "patch"] | None = None
    requested_position: str | None = None
    requested_patch: str | None = None
    # Who the games behind the numbers were: the lobbies' measured median rank.
    lobby_ranks: LobbyRanksOut | None = None
    positions: list[PositionShare] = Field(default_factory=list)
    overview: ChampionOverview
    builds: BuildSection
    runes: RuneSection
    skills: SkillSection
    laning: LaningSection
    spells: list[FacetEntry] = Field(default_factory=list)
    counters: CounterSection
    synergies: list[PairEntry] = Field(default_factory=list)
    pair_model: PairModelOut = Field(default_factory=PairModelOut)


# --- profile: who the champion is ---------------------------------------------


class Rating(BaseModel):
    key: str
    label: str
    # Riot's own 0 to 10.
    value: int


class BaseStat(BaseModel):
    key: str
    label: str
    level1: float
    # Null for the stats that do not grow (move speed, attack range), and for
    # the ones whose growth Riot did not publish; `growth_published` says which.
    level18: float | None = None
    growth_published: bool = True


class AbilityOut(BaseModel):
    # "P" for the passive, then "Q", "W", "E", "R".
    slot: str
    name: str
    description: str
    icon_url: str | None = None
    cooldown: str | None = None
    cost: str | None = None
    range: str | None = None


class SkinOut(BaseModel):
    id: int
    num: int
    name: str
    rarity: str | None = None
    legacy: bool = False
    line: str | None = None
    description: str | None = None
    chromas: int = 0
    tile_url: str | None = None
    splash_url: str | None = None
    # Live games this skin was seen in. Null while the champion is under the
    # sighting floor, which is not the same as zero.
    sightings: int | None = None


class ChampionProfile(BaseModel):
    """Everything about a champion that is not a statistic.

    Its own endpoint, not part of the detail above, because that one is a
    404 on any patch where the champion has no games (one champion on 16.17,
    and every new release on its first day). A story does not depend on a
    sample size.
    """

    champion: ChampionInfo
    blurb: str = ""
    lore: str | None = None
    resource: str | None = None
    ratings: list[Rating] = Field(default_factory=list)
    stats: list[BaseStat] = Field(default_factory=list)
    ally_tips: list[str] = Field(default_factory=list)
    enemy_tips: list[str] = Field(default_factory=list)
    passive: AbilityOut | None = None
    abilities: list[AbilityOut] = Field(default_factory=list)
    # False when championFull.json has not arrived: lore, tips and abilities
    # are then missing for that reason, not because the champion has none.
    detail_loaded: bool = False
    skins: list[SkinOut] = Field(default_factory=list)
    # Every live sighting of this champion, and the count it needs before any
    # per skin figure is shown.
    skin_sightings: int = 0
    skin_sightings_floor: int = MIN_CHAMPION_SIGHTINGS


# --- players: who is good on it -----------------------------------------------

# Five games on the champion, three of them scored. At 5+ games the corpus holds
# 621 player and champion pairs across 146 champions (measured 2026-09-21), and
# 612 of them are fully scored, so the second floor rarely bites; it is there
# for the games scored before the score existed.
PLAYER_MIN_GAMES = 5

# How far a player's average is pulled toward the champion's, in games: a
# player's score is (their score sum + this many games at the champion's mean)
# over (their scored games + this many). Measured 2026-09-24 over 830 player
# and champion pairs with five or more scored games: a game's score varies by
# 1.66 around the player's own average, and players' true averages by 0.55, so
# nine games make an average half signal. Ranked on the raw average, 13 of the
# 15 best Lee Sin players had fewer than ten games.
PLAYER_SCORE_STRENGTH = 9
PLAYER_MIN_SCORED = 3
# Fewer than this and a board is a list of whoever was crawled, not a ranking.
PLAYER_MIN_ROWS = 3
PLAYER_LIMIT = 20


class ChampionPlayer(BaseModel):
    puuid: str
    game_name: str | None = None
    tag_line: str | None = None
    # Lower case, for the profile link: the shard of their latest stored game.
    platform: str
    games: int
    wins: int
    win_rate: float
    avg_score: float
    scored_games: int
    # What the board is ordered by: the average pulled toward the champion's
    # by `PLAYER_SCORE_STRENGTH` games.
    ranked_score: float = 0.0
    tier: str | None = None
    division: str | None = None
    league_points: int | None = None


class ChampionPlayers(BaseModel):
    champion_id: int
    min_games: int = PLAYER_MIN_GAMES
    min_scored: int = PLAYER_MIN_SCORED
    # The pull toward the champion's average, and that average.
    score_strength: int = PLAYER_SCORE_STRENGTH
    champion_score: float | None = None
    # How many players cleared the floors, whether or not the list is shown.
    qualified: int = 0
    players: list[ChampionPlayer] = Field(default_factory=list)


_RATINGS = (
    ("attack", "Attack"),
    ("defense", "Defense"),
    ("magic", "Magic"),
    ("difficulty", "Difficulty"),
)

# (key, label, growth per level). Regeneration is per 5 seconds, as Riot
# writes it. The resource rows take the champion's own resource name.
_BASE_STATS = (
    ("hp", "Health", "hpperlevel"),
    ("hpregen", "Health regen", "hpregenperlevel"),
    ("mp", None, "mpperlevel"),
    ("mpregen", None, "mpregenperlevel"),
    ("attackdamage", "Attack damage", "attackdamageperlevel"),
    ("attackspeed", "Attack speed", "attackspeedperlevel"),
    ("armor", "Armor", "armorperlevel"),
    ("spellblock", "Magic resist", "spellblockperlevel"),
    ("movespeed", "Move speed", None),
    ("attackrange", "Attack range", None),
)


def _base_stats(
    stats: dict[str, float], resource: str, unpublished: set[str] | frozenset[str] = frozenset()
) -> list[BaseStat]:
    """Level 1 and level 18, from Data Dragon's base values and growth.

    Riot's growth curve is ``growth * (n - 1) * (0.7025 + 0.0175 * (n - 1))``,
    which at level 18 is exactly ``growth * 17``. Attack speed is the exception:
    its growth is a percentage of the base, not a flat amount. A growth field
    in ``unpublished`` is one Data Dragon ships as zero for every champion, so
    its level 18 figure is withheld rather than printed equal to level 1.
    """
    out: list[BaseStat] = []
    for key, label, growth_key in _BASE_STATS:
        if key not in stats:
            continue
        base = stats[key]
        if key in ("mp", "mpregen"):
            # A champion without a resource carries zeros here, and "Mana 0"
            # on Garen is a wrong fact rather than a missing one.
            if not base or resource in ("", "None"):
                continue
            label = resource if key == "mp" else f"{resource} regen"
        published = growth_key not in unpublished
        growth = stats.get(growth_key, 0.0) if growth_key and published else None
        if growth is None:
            level18 = None
        elif key == "attackspeed":
            level18 = base * (1 + growth / 100 * 17)
        else:
            level18 = base + growth * 17
        out.append(
            BaseStat(
                key=key,
                label=label or key,
                level1=base,
                level18=level18,
                growth_published=published,
            )
        )
    return out


def _ability_out(ability: Ability | None, sd: StaticDataService) -> AbilityOut | None:
    if ability is None:
        return None
    return AbilityOut(
        slot=ability.slot,
        name=ability.name,
        description=ability.description,
        icon_url=sd.ability_icon(ability),
        cooldown=ability.cooldown,
        cost=ability.cost,
        range=ability.range,
    )


def _champion_info(champion_id: int, sd: StaticDataService) -> ChampionInfo:
    champion = sd.champion(champion_id)
    return ChampionInfo(
        id=champion_id,
        name=sd.champion_name(champion_id),
        icon_url=sd.champion_icon(champion_id),
        key=champion.key if champion else None,
        title=champion.title if champion else None,
        tags=champion.tags if champion else [],
        splash_url=sd.champion_splash(champion_id),
        art_url=sd.champion_art(champion_id),
        tile_url=sd.champion_tile(champion_id),
    )


def _moved(wins_a: int, games_a: int, wins_b: int, games_b: int) -> bool:
    """True when two proportions' Wilson intervals do not overlap."""
    if not games_a or not games_b:
        return False
    return wilson_lower_bound(wins_a, games_a) > wilson_upper_bound(
        wins_b, games_b
    ) or wilson_lower_bound(wins_b, games_b) > wilson_upper_bound(wins_a, games_a)


def _facet_entry(row: ChampionFacetStat, sd, kind: str) -> FacetEntry:
    ids = list(row.facet_ids or [])
    entry = FacetEntry(
        ids=ids,
        games=row.games,
        wins=row.wins,
        win_rate=row.win_rate,
        pick_rate=row.pick_rate,
        range_low=wilson_lower_bound(row.wins, row.games),
        range_high=wilson_upper_bound(row.wins, row.games),
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
        # Named, shards included (from a table: Data Dragon has no shards).
        entry.runes = [rune_ref(r, sd) for r in ids]
    # Skill facets carry ability slots 1-4, which are not items, spells or runes.
    # They render from `ids` alone as Q/W/E/R, so they intentionally decorate
    # nothing here: an earlier catch-all `else` handed them rune icons.
    return entry


def _read_pairs(
    rows,
    own: OwnRates,
    champion_id: int,
    position: str,
    strength: float,
    min_games: int,
    sd,
    *,
    ally: bool = False,
) -> list[PairEntry]:
    """Records grouped by the other champion, pooled over patches and read.

    ``rows`` are (other, other's position, patch, wins, games, timeline games,
    laning score, gold at 14). An ally's rows in different roles sum into one
    record, labelled with the role it was in most. Gold and laning pool over
    the patches read, weighted by their timelines, and stay null under
    `MIN_LANE_TIMELINES` of them.
    """
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[row[0]].append(row)
    out: list[PairEntry] = []
    for other, group in grouped.items():
        parts, patches = parts_by_patch(
            [(patch, wins, games) for _, _, patch, wins, games, *_ in group], own, champion_id, position
        )
        read = read_records(parts, strength)
        if read.games < min_games:
            continue
        used = [r for r in group if r[2] in patches]
        timelines = sum(r[5] or 0 for r in used)

        def pooled(index: int, rows_=used) -> float | None:
            weighted = [(r[5], r[index]) for r in rows_ if r[5] and r[index] is not None]
            weight = sum(t for t, _ in weighted)
            return sum(t * v for t, v in weighted) / weight if weight else None

        measured = timelines >= MIN_LANE_TIMELINES
        roles: dict[str, int] = defaultdict(int)
        for r in used:
            roles[r[1]] += r[4]
        out.append(
            PairEntry(
                champion=ChampionRef(
                    id=other, name=sd.champion_name(other), icon_url=sd.champion_icon(other)
                ),
                games=read.games,
                wins=read.wins,
                win_rate=read.wins / read.games,
                own_rate=read.own_rate,
                lift=read.lift,
                call=read.call,
                patches=list(patches),
                confidence_win_rate=wilson_lower_bound(read.wins, read.games),
                confidence_high=wilson_upper_bound(read.wins, read.games),
                position=max(roles, key=roles.get) if ally and roles else None,
                avg_laning_score=pooled(6) if measured else None,
                avg_gold_diff_14=pooled(7) if measured else None,
                timeline_games=timelines,
            )
        )
    return out


def _champion_id(ref: str, sd: StaticDataService) -> int:
    """The path segment is a slug ("aatrox") or, from older links, an id.

    An id is taken as it is, whether or not the static data knows it: the
    stored games are the authority on which champions have numbers, and a
    champion released after the cached Data Dragon still has games.
    """
    if ref.strip().isdigit():
        return int(ref)
    champion = sd.champion_by_ref(ref)
    if champion is None:
        raise HTTPException(404, f"No champion called {ref!r}.")
    return champion.id


@router.get("/{champion}", response_model=ChampionDetail)
async def get_champion(
    champion: str,
    db: DbDep,
    sd: StaticDep,
    patch: str | None = Query(None, description="Defaults to the newest patch held."),
    queue_id: int = Query(420),
    position: str | None = Query(None, description="Defaults to the champion's main role."),
    bracket: str = Query(ALL_BRACKETS, description="Crawl provenance, not a measured rank."),
    min_games: int = Query(5, ge=1),
) -> ChampionDetail:
    champion_id = _champion_id(champion, sd)
    bracket = (bracket or ALL_BRACKETS).upper()
    if position:
        position = position.upper()
        if position not in POSITIONS:
            raise HTTPException(400, f"position must be one of {', '.join(POSITIONS)}")

    # Newest first. Read whether or not a patch was asked for, because the
    # patch before the one shown is where the change figures come from.
    slices = await aggregated_slices(db)
    held = [s["patch"] for s in slices if s["queue_id"] == queue_id]
    default = default_patch(slices, queue_id)
    asked_patch, asked_position = patch, position
    fallback: Literal["role", "patch"] | None = None
    if patch is None:
        if default is None:
            # The ingest hint is for whoever runs the server, not for a reader.
            log.warning(
                "champion page: nothing aggregated for queue %s; run `python -m scripts.ingest "
                "crawl` then `python -m scripts.ingest aggregate`", queue_id
            )
            raise HTTPException(404, "Riftline holds no ranked games for this queue yet.")
        patch = default
    elif patch not in held and default is not None:
        patch, fallback = default, "patch"

    async def roles_on(on_patch: str) -> list[ChampionStat]:
        # Every role this champion is played in, so the UI can offer a role
        # switch and default to where they are actually played.
        return list(
            (
                await db.execute(
                    select(ChampionStat).where(
                        ChampionStat.patch == on_patch,
                        ChampionStat.queue_id == queue_id,
                        ChampionStat.rank_bracket == bracket,
                        ChampionStat.champion_id == champion_id,
                        ChampionStat.team_position.in_(POSITIONS),
                    )
                )
            ).scalars()
        )

    role_rows = await roles_on(patch)
    if not role_rows and default is not None and patch != default:
        # Held, but not for this champion: the default patch may have them.
        role_rows = await roles_on(default)
        if role_rows:
            patch, fallback = default, "patch"
    if not role_rows:
        raise HTTPException(
            404,
            f"Riftline holds no ranked games of {sd.champion_name(champion_id)} "
            f"on patch {asked_patch or patch} yet.",
        )
    previous_patch = held[held.index(patch) + 1] if patch in held[:-1] else None

    slice_where = (
        ChampionStat.patch == patch,
        ChampionStat.queue_id == queue_id,
        ChampionStat.rank_bracket == bracket,
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
        # The main role instead, said: the page names the roles it is played in.
        fallback = fallback or "role"
    stat = chosen or role_rows[0]
    position = stat.team_position

    # Tier is this champion's standing among everyone in the same role, so it
    # has to be computed against the field rather than in isolation. The field
    # is the tier list's, not this page's `min_games`, which filters builds and
    # matchups: ranked against a looser field the same champion carried a
    # different letter here than one click away on the tier list.
    peers = list(
        (
            await db.execute(
                select(ChampionStat.champion_id, ChampionStat.wins, ChampionStat.games).where(
                    *slice_where,
                    ChampionStat.team_position == position,
                    ChampionStat.games >= TIER_MIN_GAMES,
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
        confidence_high=wilson_upper_bound(stat.wins, stat.games),
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

    if previous_patch:
        before = (
            await db.execute(
                select(ChampionStat).where(
                    ChampionStat.patch == previous_patch,
                    ChampionStat.queue_id == queue_id,
                    ChampionStat.rank_bracket == bracket,
                    ChampionStat.champion_id == champion_id,
                    ChampionStat.team_position == position,
                )
            )
        ).scalar_one_or_none()
        if before and before.games:
            overview.previous = PatchChange(
                patch=previous_patch,
                games=before.games,
                win_rate=before.win_rate,
                pick_rate=before.pick_rate,
                win_rate_moved=_moved(stat.wins, stat.games, before.wins, before.games),
                pick_rate_moved=_moved(
                    stat.games, stat.pool_games, before.games, before.pool_games
                ),
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
    items = entries("item")
    if items:
        against_slot = {
            row.item_id: row
            for row in (
                await db.execute(
                    select(ItemChampionStat).where(
                        ItemChampionStat.patch == patch,
                        ItemChampionStat.queue_id == queue_id,
                        ItemChampionStat.rank_bracket == bracket,
                        ItemChampionStat.champion_id == champion_id,
                        ItemChampionStat.item_id.in_([e.ids[0] for e in items]),
                    )
                )
            ).scalars()
        }
        for entry in items:
            row = against_slot.get(entry.ids[0])
            if row is None or row.expected_wins is None or not row.buyers:
                continue
            entry.slot_buyers = row.buyers
            if row.buyers >= CHAMPION_MIN_BUYERS:
                entry.slot_delta = (row.buyer_wins - row.expected_wins) / row.buyers
    builds = BuildSection(
        # The whole point of Group B: once a real purchase order exists, stop
        # describing final inventories as if they were builds.
        basis="purchase_order" if path else "final_inventory",
        # Final inventories of three or more finished items. Most sets were one
        # or two items from games that ended early, under a label that said
        # "the full set of finished items".
        complete=[
            _facet_entry(r, sd, "build")
            for r in grouped.get("build", [])
            if len(r.facet_ids or []) >= 3
        ][:FACET_LIMIT],
        items=items,
        boots=entries("boots"),
        path=path,
    )
    runes = RuneSection(keystones=entries("keystone"), pages=entries("rune_page"))
    skills = SkillSection(
        priority=entries("skill_priority"),
        order=entries("skill_order"),
        first=entries("skill_first"),
    )
    # Under the floor the averages are one or two games: 74 of 289 pages drew
    # their laning tab from one to nine (2026-09-24).
    laned = stat.timeline_games >= MIN_LANING_TIMELINES
    laning = LaningSection(
        games=stat.timeline_games,
        avg_score=stat.avg_laning_score if laned else None,
        avg_gold_diff=stat.avg_gold_diff_14 if laned else None,
        avg_cs_diff=stat.avg_cs_diff_14 if laned else None,
    )

    # --- matchups and synergies --------------------------------------------
    # Read as the draft reads them: over this patch and the close one before it
    # (which doubles the lane pairs with ten or more games), each against the
    # champion's own rate on that patch, at the strengths `draftpriors`
    # measured. The page's `min_games` floors the pooled record.
    pool = poolable_patches(held or [patch], patch)
    own: OwnRates = {
        (champion_id, position, p): w / g
        for p, w, g in (
            await db.execute(
                select(ChampionStat.patch, ChampionStat.wins, ChampionStat.games).where(
                    ChampionStat.patch.in_(pool),
                    ChampionStat.queue_id == queue_id,
                    ChampionStat.rank_bracket == bracket,
                    ChampionStat.champion_id == champion_id,
                    ChampionStat.team_position == position,
                    ChampionStat.games > 0,
                )
            )
        ).all()
    }
    matchup_rows = (
        await db.execute(
            select(
                MatchupStat.scope,
                MatchupStat.enemy_champion_id,
                MatchupStat.patch,
                MatchupStat.wins,
                MatchupStat.games,
                MatchupStat.timeline_games,
                MatchupStat.avg_laning_score,
                MatchupStat.avg_gold_diff_14,
            ).where(
                MatchupStat.patch.in_(pool),
                MatchupStat.queue_id == queue_id,
                MatchupStat.rank_bracket == bracket,
                MatchupStat.champion_id == champion_id,
                MatchupStat.team_position == position,
            )
        )
    ).all()
    by_scope: dict[str, list] = defaultdict(list)
    for scope, enemy, p, wins, games, timelines, pair_laning, pair_gold in matchup_rows:
        by_scope[scope].append((enemy, position, p, wins, games, timelines, pair_laning, pair_gold))
    lane = _read_pairs(by_scope["LANE"], own, champion_id, position, LANE_STRENGTH, min_games, sd)
    team = _read_pairs(by_scope["TEAM"], own, champion_id, position, TEAM_STRENGTH, min_games, sd)
    # Hardest first: "weak against" is the question people come here with.
    for rows_ in (lane, team):
        rows_.sort(key=lambda e: (e.lift, -e.games))

    synergy_rows = (
        await db.execute(
            select(
                SynergyStat.ally_champion_id,
                SynergyStat.ally_position,
                SynergyStat.patch,
                SynergyStat.wins,
                SynergyStat.games,
            ).where(
                SynergyStat.patch.in_(pool),
                SynergyStat.queue_id == queue_id,
                SynergyStat.rank_bracket == bracket,
                SynergyStat.champion_id == champion_id,
                SynergyStat.team_position == position,
            )
        )
    ).all()
    synergies = _read_pairs(
        [(ally, ally_position, p, wins, games, 0, None, None) for ally, ally_position, p, wins, games in synergy_rows],
        own, champion_id, position, ALLY_STRENGTH, min_games, sd, ally=True,
    )
    # Best first: an ally is a question about who to pair with, not avoid.
    synergies.sort(key=lambda e: (-e.lift, -e.games))

    mix = await cached_lobby_rank_mix(db, patch, queue_id, bracket)

    return ChampionDetail(
        champion=_champion_info(champion_id, sd),
        patch=patch,
        queue_id=queue_id,
        position=position,
        rank_bracket=bracket,
        sample_matches=stat.pool_games,
        min_games=min_games,
        fallback=fallback,
        # What was asked, wherever it differs from what is served: a patch
        # fallback can also land on a patch where the asked role has no games.
        requested_position=asked_position if asked_position and asked_position != position else None,
        requested_patch=asked_patch if asked_patch and asked_patch != patch else None,
        lobby_ranks=lobby_ranks_out(mix) if mix.total else None,
        positions=positions,
        overview=overview,
        builds=builds,
        runes=runes,
        skills=skills,
        laning=laning,
        spells=entries("spells"),
        counters=CounterSection(lane=lane, team=team),
        synergies=synergies,
    )


@router.get("/{champion_ref}/profile", response_model=ChampionProfile)
async def get_champion_profile(champion_ref: str, db: DbDep, sd: StaticDep) -> ChampionProfile:
    """Story, ratings, base stats, abilities and skins. No Riot call, and one
    indexed read for the skin counts.

    Answers for every champion Data Dragon knows, games or not.
    """
    champion_id = _champion_id(champion_ref, sd)
    champion = sd.champion(champion_id)
    if champion is None:
        raise HTTPException(404, f"No champion with id {champion_id}.")
    lore = sd.champion_lore(champion_id)
    counts = await champion_skin_counts(db, champion_id)
    shown = bool(counts.by_skin)
    return ChampionProfile(
        champion=_champion_info(champion_id, sd),
        blurb=champion.blurb,
        lore=lore.lore if lore and lore.lore else None,
        resource=champion.partype if champion.partype not in ("", "None") else None,
        ratings=[
            Rating(key=key, label=label, value=champion.info[key])
            for key, label in _RATINGS
            if key in champion.info
        ],
        stats=_base_stats(champion.stats, champion.partype, sd.unpublished_growth),
        ally_tips=lore.ally_tips if lore else [],
        enemy_tips=lore.enemy_tips if lore else [],
        passive=_ability_out(lore.passive if lore else None, sd),
        abilities=[a for a in (_ability_out(s, sd) for s in (lore.spells if lore else [])) if a],
        detail_loaded=lore is not None,
        skins=[
            SkinOut(
                id=skin.id,
                num=skin.num,
                name=skin.name,
                rarity=skin.rarity,
                legacy=skin.legacy,
                line=next(
                    (n for n in (sd.skin_line_name(i) for i in skin.lines) if n), None
                ),
                description=skin.description,
                chromas=skin.chromas,
                tile_url=sd.champion_tile(champion_id, skin.num),
                splash_url=sd.champion_skin_splash(champion_id, skin.num),
                # Zero is a real answer once the champion clears the floor: the
                # skin was never seen in that many sightings.
                sightings=counts.by_skin.get(skin.num, 0) if shown else None,
            )
            for skin in sd.champion_skins(champion_id)
        ],
        skin_sightings=counts.total,
    )


@router.get("/{champion}/players", response_model=ChampionPlayers)
async def get_champion_players(champion: str, db: DbDep, sd: StaticDep) -> ChampionPlayers:
    """The players who do best on this champion, by average Riftline score.

    Counts every Summoner's Rift game we hold rather than the page's patch
    slice: who is good on a champion is not a patch question, and the slice
    costs a third of the sample (399 qualifying pairs on 16.18 against 621
    overall, measured 2026-09-21). Remakes are left out, as they are
    everywhere else.
    """
    champion_id = _champion_id(champion, sd)
    games = func.count(MatchParticipant.id)
    scored = func.count(MatchParticipant.performance_score)
    score = func.avg(MatchParticipant.performance_score)
    rows = (
        await db.execute(
            select(
                MatchParticipant.puuid,
                games.label("games"),
                func.sum(win_as_int()).label("wins"),
                score.label("score"),
                scored.label("scored"),
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.champion_id == champion_id,
                MatchParticipant.team_position.in_(POSITIONS),
                Match.is_remake.is_(False),
            )
            .group_by(MatchParticipant.puuid)
            .having(games >= PLAYER_MIN_GAMES, scored >= PLAYER_MIN_SCORED)
        )
    ).all()
    mean = (
        await db.execute(
            select(func.avg(MatchParticipant.performance_score))
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.champion_id == champion_id,
                MatchParticipant.team_position.in_(POSITIONS),
                Match.is_remake.is_(False),
            )
        )
    ).scalar()
    champion_score = float(mean) if mean is not None else None
    result = ChampionPlayers(
        champion_id=champion_id, qualified=len(rows), champion_score=champion_score
    )
    if len(rows) < PLAYER_MIN_ROWS:
        return result

    def ranked(row) -> float:
        centre = champion_score if champion_score is not None else float(row.score)
        return (float(row.score) * row.scored + PLAYER_SCORE_STRENGTH * centre) / (
            row.scored + PLAYER_SCORE_STRENGTH
        )

    # Ties go to the bigger sample.
    top = sorted(rows, key=lambda r: (ranked(r), r.games), reverse=True)[:PLAYER_LIMIT]
    puuids = [r.puuid for r in top]

    # Name and shard from each player's latest stored game on any champion:
    # Riot IDs change, and the latest one is the one a profile link resolves.
    identity: dict[str, tuple[str | None, str | None, str]] = {}
    for puuid, name, tag, platform in (
        await db.execute(
            select(
                MatchParticipant.puuid,
                MatchParticipant.riot_id_game_name,
                MatchParticipant.riot_id_tagline,
                Match.platform_id,
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.puuid.in_(puuids))
            .order_by(Match.game_creation.desc())
        )
    ).all():
        identity.setdefault(puuid, (name, tag, (platform or "").lower()))

    ranks = {
        entry.puuid: entry
        for entry in (
            await db.execute(
                select(RankedEntry).where(
                    RankedEntry.puuid.in_(puuids),
                    RankedEntry.queue_type == "RANKED_SOLO_5x5",
                )
            )
        ).scalars()
    }

    for row in top:
        name, tag, platform = identity.get(row.puuid, (None, None, ""))
        rank = ranks.get(row.puuid)
        result.players.append(
            ChampionPlayer(
                puuid=row.puuid,
                game_name=name,
                tag_line=tag,
                platform=platform,
                games=row.games,
                wins=row.wins or 0,
                win_rate=(row.wins or 0) / row.games,
                avg_score=float(row.score),
                scored_games=row.scored,
                ranked_score=ranked(row),
                tier=rank.tier if rank else None,
                division=rank.division if rank else None,
                league_points=rank.league_points if rank else None,
            )
        )
    return result
