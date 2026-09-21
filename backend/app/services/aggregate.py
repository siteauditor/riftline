"""Rollups: champion statistics, matchups, synergies, and build facets.

Everything here is derived data, recomputed from ``match_participants``. It can
always be thrown away and rebuilt, which is what makes it safe to change the
formulas later.

Judgements baked in:

* Stats are sliced **per patch**. A champion's win rate before and after a rework
  are different numbers about different champions, and blending them produces a
  figure that describes nothing.
* Ranking uses the **Wilson lower bound**, not raw win rate. With a handful of
  games, raw win rate is mostly noise: a 3-0 champion is not the best in the
  game. Wilson asks "what win rate can we actually defend at this sample size",
  which pushes thin samples down instead of letting them top the list.
* Build facets are **order-independent sets**. A participant's item array is
  inventory position, not purchase order, so anything resembling a build *path*
  would be invented. That waits for match timelines.
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, case, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChampionFacetStat,
    ChampionStat,
    Match,
    MatchParticipant,
    MatchupStat,
    SynergyStat,
    utcnow,
)
from app.services.item_taxonomy import ItemTaxonomy, ensure_taxonomy
from app.services.static_data import static_data
from app.services.timelines import skill_priority

log = logging.getLogger(__name__)

# z for a 95% confidence interval.
WILSON_Z = 1.96

# Every aggregate is sliced by this. "ALL" means every bracket we hold.
ALL_BRACKETS = "ALL"

# Positions that mean something. ARAM and Arena report an empty teamPosition,
# stored as NULL, and are correctly excluded from positional aggregates.
POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


def wilson_lower_bound(wins: int, games: int, z: float = WILSON_Z) -> float:
    """Lower bound of the Wilson score interval for a win rate.

    Answers "given this sample, how high is the win rate we can defend?".
    A 60% win rate over 10 games lands near 0.31; over 1,000 games, near 0.57.
    """
    if games <= 0:
        return 0.0
    phat = wins / games
    denominator = 1 + z**2 / games
    centre = phat + z**2 / (2 * games)
    margin = z * math.sqrt((phat * (1 - phat) + z**2 / (4 * games)) / games)
    return max(0.0, (centre - margin) / denominator)


def wilson_upper_bound(wins: int, games: int, z: float = WILSON_Z) -> float:
    """Upper bound of the same interval: how high the win rate could plausibly be.

    Shown beside the lower bound so a pick is read as a range. The tier list
    ranks on the low end, and a 70% over 20 games sorting below 63% over 79
    only makes sense once the reader can see how wide the first one is.
    """
    if games <= 0:
        return 1.0
    phat = wins / games
    denominator = 1 + z**2 / games
    centre = phat + z**2 / (2 * games)
    margin = z * math.sqrt((phat * (1 - phat) + z**2 / (4 * games)) / games)
    # Never below the observed rate. At 20 wins from 20 the formula is exactly
    # 1.0 on paper and 0.9999999999999999 in floating point, which drew the
    # range's top a hair under the win rate it is meant to contain.
    return min(1.0, max(phat, (centre + margin) / denominator))


# Fewer rows than this and a percentile describes the list's length rather than
# the champions in it: with one row, that row is automatically "the top 10%".
MIN_ROWS_FOR_TIERS = 10

# Percentile bands, not fixed win-rate thresholds. Win rates cluster tightly
# around 50% by design, so "above 52%" means different things on different
# patches, whereas "top 10% of this patch" always means the same.
_TIER_CUTS = ((0.10, "S"), (0.30, "A"), (0.60, "B"), (0.85, "C"))


def tier_for(rank_index: int, total: int) -> str | None:
    """Letter tier for a row at ``rank_index`` of ``total``, best first.

    ``None`` when the sample cannot support banding, which the UI renders as
    "too thin to rank" rather than inventing a confident letter.
    """
    if total < MIN_ROWS_FOR_TIERS or rank_index < 0 or rank_index >= total:
        return None
    position = rank_index / total
    return next((label for cut, label in _TIER_CUTS if position < cut), "D")


def win_as_int():
    """Count wins portably.

    ``CAST(win AS INTEGER)`` works on SQLite but Postgres rejects it outright
    ("cannot cast type boolean to integer"), so the aggregation would break on
    the very migration this schema is designed for. CASE is valid on both.
    """
    return case((MatchParticipant.win, 1), else_=0)


def _slice_filter(
    stmt: Select, patch: str, queue_id: int, rank_bracket: str = ALL_BRACKETS
) -> Select:
    stmt = stmt.where(
        Match.patch == patch,
        Match.queue_id == queue_id,
        Match.is_remake.is_(False),
    )
    if rank_bracket and rank_bracket != ALL_BRACKETS:
        stmt = stmt.where(Match.source_bracket == rank_bracket)
    return stmt


def _as_json(value: Any) -> Any:
    """Tolerate a JSON column arriving as text.

    Column-level selects do not always run the JSON type's result processor the
    way loading a whole ORM object does, and a silently unparsed string here
    would make every facet count zero.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


async def slice_match_count(
    session: AsyncSession, patch: str, queue_id: int, rank_bracket: str = ALL_BRACKETS
) -> int:
    stmt = _slice_filter(
        select(func.count(Match.match_id)), patch, queue_id, rank_bracket
    )
    return (await session.execute(stmt)).scalar() or 0


# Master, Grandmaster and Challenger as one bucket. A lobby's median rank decodes
# exactly below Master, but which apex tier a points value belongs to depends on
# each region's live cutoffs, so splitting them would be a guess.
APEX_BUCKET = "MASTER+"


@dataclass(slots=True)
class LobbyRankMix:
    """How the games in a slice were ranked, by each lobby's measured median.

    ``total`` counts every game in the slice and ``measured`` the ones whose
    lobby rank was measured, so the page can say how much of the slice the mix
    describes. ``as_of`` is when the newest measurement was taken: Riot keeps no
    historical rank, so this is where those players stood on that day, not when
    they played.
    """

    total: int = 0
    measured: int = 0
    # (bucket, games), highest first.
    buckets: list[tuple[str, int]] = field(default_factory=list)
    as_of: datetime | None = None


async def lobby_rank_mix(
    session: AsyncSession, patch: str, queue_id: int, rank_bracket: str = ALL_BRACKETS
) -> LobbyRankMix:
    """The measured lobby ranks behind one slice of the tier list."""
    # Imported here: the schemas module imports services that import this one.
    from app.api.schemas import TIER_ORDER, rank_from_points

    stmt = _slice_filter(
        select(Match.lobby_rank_points, Match.lobby_rank_measured_at),
        patch, queue_id, rank_bracket,
    )
    mix = LobbyRankMix()
    counts: Counter[str] = Counter()
    for points, measured_at in (await session.execute(stmt)).all():
        mix.total += 1
        if points is None:
            continue
        tier, _ = rank_from_points(int(points))
        if tier is None:
            continue
        mix.measured += 1
        counts[APEX_BUCKET if tier in ("MASTER", "GRANDMASTER", "CHALLENGER") else tier] += 1
        if measured_at is not None and (mix.as_of is None or measured_at > mix.as_of):
            mix.as_of = measured_at
    order = [APEX_BUCKET, *reversed(TIER_ORDER[: TIER_ORDER.index("MASTER")])]
    mix.buckets = [(bucket, counts[bucket]) for bucket in order if counts[bucket]]
    return mix


async def _ban_counts(
    session: AsyncSession, patch: str, queue_id: int, rank_bracket: str
) -> Counter[int]:
    """Count bans from each match's stored team payload.

    Done in Python rather than SQL because JSON access is the least portable
    thing in SQL and this runs offline. At warehouse scale you would denormalise
    bans into their own table at ingest time instead.
    """
    stmt = _slice_filter(select(Match.teams), patch, queue_id, rank_bracket)
    counts: Counter[int] = Counter()
    for (teams,) in (await session.execute(stmt)).all():
        for team in _as_json(teams) or []:
            for ban in team.get("bans") or []:
                champion_id = ban.get("championId")
                # -1 means the ban slot went unused.
                if isinstance(champion_id, int) and champion_id > 0:
                    counts[champion_id] += 1
    return counts


# --------------------------------------------------------------- champion stats


async def rebuild_champion_stats(
    session: AsyncSession,
    *,
    patch: str,
    queue_id: int,
    rank_bracket: str = ALL_BRACKETS,
) -> int:
    """Recompute champion rollups for one patch/queue/bracket slice."""
    pool_games = await slice_match_count(session, patch, queue_id, rank_bracket)
    if pool_games == 0:
        return 0

    bans = await _ban_counts(session, patch, queue_id, rank_bracket)

    # CS/min has to be computed per game before averaging: averaging the ratio
    # and the ratio of averages are different numbers, and the second one is
    # wrong whenever game lengths vary.
    # A CASE, not func.max(a, b): that is a scalar function in SQLite but an
    # aggregate in Postgres, so it would break silently on the move.
    safe_duration = case((Match.game_duration > 0, Match.game_duration), else_=1)
    cs_per_min = MatchParticipant.total_minions * 60.0 / safe_duration

    stmt = (
        select(
            MatchParticipant.champion_id,
            MatchParticipant.team_position,
            func.count().label("games"),
            func.sum(win_as_int()).label("wins"),
            func.avg(MatchParticipant.kills),
            func.avg(MatchParticipant.deaths),
            func.avg(MatchParticipant.assists),
            func.avg(cs_per_min),
            func.avg(MatchParticipant.gold_earned),
            func.avg(MatchParticipant.damage_to_champions),
            func.avg(MatchParticipant.vision_score),
            # count() over a nullable column counts only the rows that have one,
            # and avg() skips nulls, so these describe the timeline subset
            # without contaminating the totals above.
            func.count(MatchParticipant.laning_score),
            func.avg(MatchParticipant.laning_score),
            func.avg(MatchParticipant.gold_diff_14),
            func.avg(MatchParticipant.cs_diff_14),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .group_by(MatchParticipant.champion_id, MatchParticipant.team_position)
    )
    rows = (
        await session.execute(_slice_filter(stmt, patch, queue_id, rank_bracket))
    ).all()

    await session.execute(
        delete(ChampionStat).where(
            ChampionStat.patch == patch,
            ChampionStat.queue_id == queue_id,
            ChampionStat.rank_bracket == rank_bracket,
        )
    )

    now = utcnow()
    payload = [
        {
            "patch": patch,
            "queue_id": queue_id,
            "rank_bracket": rank_bracket,
            "champion_id": champion_id,
            "team_position": position or "ALL",
            "games": games,
            "wins": int(wins or 0),
            "pool_games": pool_games,
            "bans": bans.get(champion_id, 0),
            "avg_kills": float(k or 0),
            "avg_deaths": float(d or 0),
            "avg_assists": float(a or 0),
            "avg_cs_per_min": float(cspm or 0),
            "avg_gold": float(gold or 0),
            "avg_damage": float(damage or 0),
            "avg_vision": float(vision or 0),
            "timeline_games": int(tl_games or 0),
            "avg_laning_score": float(laning) if laning is not None else None,
            "avg_gold_diff_14": float(gold_diff) if gold_diff is not None else None,
            "avg_cs_diff_14": float(cs_diff) if cs_diff is not None else None,
            "computed_at": now,
        }
        for (
            champion_id, position, games, wins, k, d, a, cspm, gold, damage, vision,
            tl_games, laning, gold_diff, cs_diff,
        ) in rows
    ]
    if payload:
        await session.execute(insert(ChampionStat), payload)
    await session.commit()
    log.info(
        "champion stats: %d rows for %s/%s/%s from %d matches",
        len(payload), patch, queue_id, rank_bracket, pool_games,
    )
    return len(payload)


# -------------------------------------------------------------------- matchups


async def rebuild_matchup_stats(
    session: AsyncSession,
    *,
    patch: str,
    queue_id: int,
    rank_bracket: str = ALL_BRACKETS,
    min_games: int = 2,
) -> int:
    """Recompute head-to-head records, in both scopes.

    ``LANE`` joins on the same ``team_position``: the two players matchmaking put
    in the same lane. ``TEAM`` drops that condition, so a champion is measured
    against all five opponents. A pick can be comfortable into its laner and
    hopeless into the enemy composition, and only the second scope sees that.
    """
    enemy = MatchParticipant.__table__.alias("enemy")

    await session.execute(
        delete(MatchupStat).where(
            MatchupStat.patch == patch,
            MatchupStat.queue_id == queue_id,
            MatchupStat.rank_bracket == rank_bracket,
        )
    )

    written = 0
    now = utcnow()
    for scope in ("LANE", "TEAM"):
        on_clause = (enemy.c.match_id == MatchParticipant.match_id) & (
            enemy.c.team_id != MatchParticipant.team_id
        )
        if scope == "LANE":
            on_clause = on_clause & (
                enemy.c.team_position == MatchParticipant.team_position
            )

        stmt = (
            select(
                MatchParticipant.team_position,
                MatchParticipant.champion_id,
                enemy.c.champion_id,
                func.count().label("games"),
                func.sum(win_as_int()).label("wins"),
                func.count(MatchParticipant.laning_score),
                func.avg(MatchParticipant.laning_score),
                func.avg(MatchParticipant.gold_diff_14),
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .join(enemy, on_clause)
            .where(MatchParticipant.team_position.in_(POSITIONS))
            .group_by(
                MatchParticipant.team_position,
                MatchParticipant.champion_id,
                enemy.c.champion_id,
            )
            .having(func.count() >= min_games)
        )
        rows = (
            await session.execute(_slice_filter(stmt, patch, queue_id, rank_bracket))
        ).all()

        payload = [
            {
                "patch": patch,
                "queue_id": queue_id,
                "rank_bracket": rank_bracket,
                "scope": scope,
                "team_position": position,
                "champion_id": champion_id,
                "enemy_champion_id": enemy_id,
                "games": games,
                "wins": int(wins or 0),
                "timeline_games": int(tl_games or 0),
                "avg_laning_score": float(laning) if laning is not None else None,
                "avg_gold_diff_14": float(gold_diff) if gold_diff is not None else None,
                "computed_at": now,
            }
            for (
                position, champion_id, enemy_id, games, wins,
                tl_games, laning, gold_diff,
            ) in rows
        ]
        if payload:
            await session.execute(insert(MatchupStat), payload)
        written += len(payload)

    await session.commit()
    log.info("matchups: %d rows for %s/%s/%s", written, patch, queue_id, rank_bracket)
    return written


# --------------------------------------------------------------------- synergy


async def rebuild_synergy_stats(
    session: AsyncSession,
    *,
    patch: str,
    queue_id: int,
    rank_bracket: str = ALL_BRACKETS,
    min_games: int = 2,
) -> int:
    """Recompute how a champion performs alongside each ally.

    Same match, same team, different player. Teammates share a result, so summing
    the subject's ``win`` gives the pair's win count.
    """
    ally = MatchParticipant.__table__.alias("ally")

    stmt = (
        select(
            MatchParticipant.team_position,
            MatchParticipant.champion_id,
            ally.c.team_position,
            ally.c.champion_id,
            func.count().label("games"),
            func.sum(win_as_int()).label("wins"),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .join(
            ally,
            (ally.c.match_id == MatchParticipant.match_id)
            & (ally.c.team_id == MatchParticipant.team_id)
            # Same team but not the same row, or every champion would be its own
            # best friend with a perfect pair rate.
            & (ally.c.participant_index != MatchParticipant.participant_index),
        )
        .where(
            MatchParticipant.team_position.in_(POSITIONS),
            ally.c.team_position.in_(POSITIONS),
        )
        .group_by(
            MatchParticipant.team_position,
            MatchParticipant.champion_id,
            ally.c.team_position,
            ally.c.champion_id,
        )
        .having(func.count() >= min_games)
    )
    rows = (
        await session.execute(_slice_filter(stmt, patch, queue_id, rank_bracket))
    ).all()

    await session.execute(
        delete(SynergyStat).where(
            SynergyStat.patch == patch,
            SynergyStat.queue_id == queue_id,
            SynergyStat.rank_bracket == rank_bracket,
        )
    )
    now = utcnow()
    payload = [
        {
            "patch": patch,
            "queue_id": queue_id,
            "rank_bracket": rank_bracket,
            "team_position": position,
            "champion_id": champion_id,
            "ally_position": ally_position,
            "ally_champion_id": ally_id,
            "games": games,
            "wins": int(wins or 0),
            "computed_at": now,
        }
        for position, champion_id, ally_position, ally_id, games, wins in rows
    ]
    if payload:
        await session.execute(insert(SynergyStat), payload)
    await session.commit()
    log.info("synergies: %d rows for %s/%s/%s", len(payload), patch, queue_id, rank_bracket)
    return len(payload)


# ---------------------------------------------------------------------- facets


def perk_facets(perks: Any) -> tuple[int | None, list[int] | None]:
    """Pull (keystone, full page signature) out of a participant's perks.

    Styles are located by Riot's own ``description`` label rather than by array
    position, for the same reason the match mapper does it: indexing blind
    silently swaps the primary and secondary trees if Riot ever reorders them.
    """
    perks = _as_json(perks)
    if not isinstance(perks, dict):
        return None, None
    styles = perks.get("styles")
    if not isinstance(styles, list):
        return None, None

    def find(description: str) -> dict | None:
        return next(
            (
                s
                for s in styles
                if isinstance(s, dict) and s.get("description") == description
            ),
            None,
        )

    primary, sub = find("primaryStyle"), find("subStyle")
    if not primary:
        return None, None

    picks = [
        s.get("perk") for s in (primary.get("selections") or []) if isinstance(s, dict)
    ]
    keystone = picks[0] if picks else None
    if not sub:
        return keystone, None

    sub_picks = [
        s.get("perk") for s in (sub.get("selections") or []) if isinstance(s, dict)
    ]
    shards = perks.get("statPerks") or {}
    page = [
        primary.get("style"), *picks,
        sub.get("style"), *sub_picks,
        shards.get("offense"), shards.get("flex"), shards.get("defense"),
    ]
    # A partial page is worse than no page: it would collide with other partials.
    return (keystone, page) if all(isinstance(v, int) for v in page) else (keystone, None)


async def rebuild_facet_stats(
    session: AsyncSession,
    *,
    patch: str,
    queue_id: int,
    rank_bracket: str = ALL_BRACKETS,
    min_games: int = 3,
    taxonomy: ItemTaxonomy | None = None,
) -> int:
    """Recompute what champions built, ran and took, for one slice.

    Counted in Python: the inputs are JSON blobs and an item taxonomy, neither of
    which belongs in SQL, and this runs offline. The ``min_games`` floor matters
    more here than anywhere else, because complete builds have a long tail of
    one-offs that would otherwise dominate the table by row count.

    Scaling note: this materialises the whole slice, which is ~17MB at the
    current corpus and would be roughly a gigabyte at a million participants.
    The fix when that day comes is ``session.stream`` with ``yield_per``, not a
    rewrite; the tallies are already incremental. Doing it now would add
    machinery that cannot be exercised at this size.

    ``taxonomy`` is injectable so tests can classify against a handful of known
    items instead of needing Data Dragon loaded. In production it comes from the
    live patch.
    """
    taxonomy = taxonomy or ensure_taxonomy(static_data)

    stmt = (
        select(
            MatchParticipant.champion_id,
            MatchParticipant.team_position,
            MatchParticipant.items,
            MatchParticipant.perks,
            MatchParticipant.summoner1_id,
            MatchParticipant.summoner2_id,
            MatchParticipant.win,
            MatchParticipant.build_order,
            MatchParticipant.skill_order,
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.team_position.in_(POSITIONS))
    )
    rows = (
        await session.execute(_slice_filter(stmt, patch, queue_id, rank_bracket))
    ).all()

    # (champion, position, facet, key) -> [games, wins]
    tally: dict[tuple[int, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    ids_for: dict[tuple[int, str, str, str], list[int]] = {}
    champion_games: Counter[tuple[int, str]] = Counter()

    for (
        champion_id, position, items, perks, spell1, spell2, win,
        build_order, skill_levels,
    ) in rows:
        won = 1 if win else 0
        champion_games[(champion_id, position)] += 1

        def record(facet: str, ids: list[int], *, _c=champion_id, _p=position, _w=won) -> None:
            key = "|".join(str(i) for i in ids)
            entry = tally[(_c, _p, facet, key)]
            entry[0] += 1
            entry[1] += _w
            ids_for[(_c, _p, facet, key)] = ids

        cores, boots = taxonomy.split_build(_as_json(items))
        if cores:
            record("build", cores)
            for item_id in cores:
                record("item", [item_id])
        if boots:
            record("boots", [boots])
        if spell1 and spell2:
            record("spells", sorted((spell1, spell2)))

        keystone, page = perk_facets(perks)
        if keystone:
            record("keystone", [keystone])
        if page:
            record("rune_page", page)

        # --- timeline-derived, present only once a match has been backfilled ---
        # Deliberately NOT sorted: the order is the entire point, and it is the
        # thing the final-inventory `build` facet could never tell us.
        path = [i for i in (_as_json(build_order) or []) if taxonomy.is_legendary(i)][:3]
        if len(path) == 3:
            record("build_path", path)

        levels = _as_json(skill_levels) or []
        if levels:
            # Which abilities were maxed, in order. Six possible values, so it
            # survives a small sample; the exact sequence below does not, and is
            # kept for when the corpus is large enough to support it.
            priority = skill_priority(levels)
            if priority:
                record("skill_priority", priority)
            if len(levels) >= 15:
                record("skill_order", list(levels[:15]))
            # The level 1 pick on its own. Three possible values, so unlike
            # the sequence above it holds up on a few dozen games, and it is
            # the first thing anyone asks about an ability.
            record("skill_first", [levels[0]])

    await session.execute(
        delete(ChampionFacetStat).where(
            ChampionFacetStat.patch == patch,
            ChampionFacetStat.queue_id == queue_id,
            ChampionFacetStat.rank_bracket == rank_bracket,
        )
    )

    now = utcnow()
    payload = [
        {
            "patch": patch,
            "queue_id": queue_id,
            "rank_bracket": rank_bracket,
            "champion_id": champion_id,
            "team_position": position,
            "facet": facet,
            "facet_key": key,
            "facet_ids": ids_for[(champion_id, position, facet, key)],
            "games": games,
            "wins": wins,
            "champion_games": champion_games[(champion_id, position)],
            "computed_at": now,
        }
        for (champion_id, position, facet, key), (games, wins) in tally.items()
        if games >= min_games
    ]
    if payload:
        # Bulk insert: a busy slice produces tens of thousands of rows and
        # session.add() per row is an order of magnitude slower.
        await session.execute(insert(ChampionFacetStat), payload)
    await session.commit()
    log.info("facets: %d rows for %s/%s/%s", len(payload), patch, queue_id, rank_bracket)
    return len(payload)


# ------------------------------------------------------------------- discovery


def patch_sort_key(patch: str) -> tuple[int, ...]:
    """Order a patch string by its numbers rather than its characters.

    Riot patches are dotted numbers, and sorting them as text puts "16.9" above
    "16.18" because "9" beats "1" at the third character. That is not cosmetic:
    `/api/meta` resolves "latest" from the head of this list, so fifteen stray
    16.9 matches became the default tier list slice on a corpus holding 1,128
    games on 16.18, and the page answered "nothing to show yet".

    Sorted here rather than in SQL because the numeric split is written three
    different ways across SQLite and Postgres, and this list is a handful of
    rows.
    """
    return tuple(int(part) if part.isdigit() else -1 for part in patch.split("."))


async def available_slices(session: AsyncSession) -> list[dict]:
    """Patch/queue combinations that have enough data to aggregate."""
    stmt = (
        select(Match.patch, Match.queue_id, func.count(Match.match_id).label("n"))
        .where(Match.is_remake.is_(False), Match.patch.is_not(None))
        .group_by(Match.patch, Match.queue_id)
        .order_by(func.count(Match.match_id).desc())
    )
    slices = [
        {"patch": patch, "queue_id": queue, "matches": n}
        for patch, queue, n in (await session.execute(stmt)).all()
    ]
    slices.sort(key=lambda s: (patch_sort_key(s["patch"]), s["matches"]), reverse=True)
    return slices


async def available_brackets(session: AsyncSession) -> list[str]:
    """Crawl provenances present, busiest first. Always includes ALL."""
    stmt = (
        select(Match.source_bracket, func.count(Match.match_id))
        .where(Match.is_remake.is_(False), Match.source_bracket.is_not(None))
        .group_by(Match.source_bracket)
        .order_by(func.count(Match.match_id).desc())
    )
    found = [b for b, _ in (await session.execute(stmt)).all()]
    return [ALL_BRACKETS, *found]
