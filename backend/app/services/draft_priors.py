"""Re-measuring the evidence strengths the draft and the live page use.

`evidence.LANE_STRENGTH`, `TEAM_STRENGTH` and `ALLY_STRENGTH` are constants set
from a measurement, and the corpus grows every night. This reads the stored
rollups and reports what the strengths should be now, three ways, so the
constants can be moved when the numbers say so. Nothing here is served and
nothing calls Riot. Run it as `python -m scripts.ingest draftpriors`.

1. **Repeatability across patches.** The same pair's deviation from the
   champion's own rate on two patches. A real matchup effect repeats; noise
   does not. The correlation r converts to the spread of true effects, and so to
   a prior strength: tau^2 = r * noise / (1 - r), strength = 0.25 / tau^2.
2. **Spread within one patch.** The records' spread around each champion's own
   rate, minus what binomial noise alone produces (a record's games are part of
   the champion's total, so the noise term is p(1-p)(1/n - 1/G)).
3. **Time split.** The older patch's posterior lift at the strength in use,
   against the newer patch's deviation, as a regression slope through zero.
   Near 1 the strength is right; above 1 the prior is too strong (records are
   under-counted), below 1 too weak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionStat, MatchupStat, SynergyStat
from app.services.aggregate import ALL_BRACKETS, aggregated_slices, poolable_patches
from app.services.evidence import ALLY_STRENGTH, LANE_STRENGTH, TEAM_STRENGTH

# The champion's own record needs this many games to be a reference at all.
MIN_OWN_GAMES = 20

SCOPES = (("lane", LANE_STRENGTH), ("enemy team", TEAM_STRENGTH), ("ally", ALLY_STRENGTH))


@dataclass(slots=True)
class Repeatability:
    min_games: int
    pairs: int
    typical_games: float
    r: float
    r_low: float
    r_high: float
    strength: float | None
    strength_low: float | None
    strength_high: float | None


@dataclass(slots=True)
class ScopeReport:
    scope: str
    strength_in_use: float
    repeatability: list[Repeatability]
    within_pairs: int
    within_strength: float | None
    split_pairs: int
    split_slope: float | None


@dataclass(slots=True)
class PriorsReport:
    queue_id: int
    newer: str | None
    older: str | None
    scopes: list[ScopeReport]


def _strength(r: float, noise: float) -> float | None:
    """The prior strength a correlation implies, or None for no effect."""
    if r <= 0:
        return None
    if r >= 1:
        return 0.0
    tau2 = r * noise / (1 - r)
    return 0.25 / tau2


async def _own(session: AsyncSession, patch: str, queue_id: int) -> dict[tuple[int, str], tuple[int, int]]:
    rows = await session.execute(
        select(ChampionStat.champion_id, ChampionStat.team_position, ChampionStat.wins, ChampionStat.games).where(
            ChampionStat.patch == patch,
            ChampionStat.queue_id == queue_id,
            ChampionStat.rank_bracket == ALL_BRACKETS,
            ChampionStat.team_position != "ALL",
            ChampionStat.games >= MIN_OWN_GAMES,
        )
    )
    return {(c, pos): (w, g) for c, pos, w, g in rows.all()}


async def _records(session: AsyncSession, patch: str, queue_id: int, scope: str) -> dict[tuple, tuple[int, int]]:
    """(champion, position, other) -> (wins, games); allies summed over the ally's role."""
    if scope == "ally":
        stmt = (
            select(
                SynergyStat.champion_id, SynergyStat.team_position, SynergyStat.ally_champion_id,
                func.sum(SynergyStat.wins), func.sum(SynergyStat.games),
            )
            .where(
                SynergyStat.patch == patch,
                SynergyStat.queue_id == queue_id,
                SynergyStat.rank_bracket == ALL_BRACKETS,
            )
            .group_by(SynergyStat.champion_id, SynergyStat.team_position, SynergyStat.ally_champion_id)
        )
    else:
        stmt = select(
            MatchupStat.champion_id, MatchupStat.team_position, MatchupStat.enemy_champion_id,
            MatchupStat.wins, MatchupStat.games,
        ).where(
            MatchupStat.patch == patch,
            MatchupStat.queue_id == queue_id,
            MatchupStat.rank_bracket == ALL_BRACKETS,
            MatchupStat.scope == ("LANE" if scope == "lane" else "TEAM"),
        )
    return {(c, pos, o): (int(w), int(g)) for c, pos, o, w, g in (await session.execute(stmt)).all()}


def _repeatability(pairs: list[tuple[float, float, int, int]], min_games: int) -> Repeatability | None:
    """pairs: (older deviation, newer deviation, older games, newer games)."""
    kept = [p for p in pairs if p[2] >= min_games and p[3] >= min_games]
    if len(kept) < 20:
        return None
    xs = [p[0] for p in kept]
    ys = [p[1] for p in kept]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0
    se = 1 / math.sqrt(len(kept))
    typical = (2 * len(kept)) / sum(1 / p[2] + 1 / p[3] for p in kept)
    noise = 0.25 / typical
    return Repeatability(
        min_games=min_games,
        pairs=len(kept),
        typical_games=typical,
        r=r,
        r_low=r - 1.96 * se,
        r_high=r + 1.96 * se,
        strength=_strength(r, noise),
        strength_low=_strength(r + 1.96 * se, noise),
        strength_high=_strength(r - 1.96 * se, noise),
    )


async def measure(session: AsyncSession, queue_id: int = 420) -> PriorsReport:
    held = [s["patch"] for s in await aggregated_slices(session) if s["queue_id"] == queue_id]
    if not held:
        return PriorsReport(queue_id, None, None, [])
    pool = poolable_patches(held, held[0])
    newer = pool[0]
    older = pool[1] if len(pool) > 1 else None
    own_new = await _own(session, newer, queue_id)
    own_old = await _own(session, older, queue_id) if older else {}

    scopes: list[ScopeReport] = []
    for scope, strength in SCOPES:
        new = await _records(session, newer, queue_id, scope)
        old = await _records(session, older, queue_id, scope) if older else {}

        # Spread within the newer patch, beyond binomial noise.
        num = noise = weight = 0.0
        within = 0
        for (c, pos, _), (w, g) in new.items():
            if g < 5 or (c, pos) not in own_new:
                continue
            ow, og = own_new[(c, pos)]
            p = ow / og
            num += g * (w / g - p) ** 2
            noise += g * p * (1 - p) * (1 / g - 1 / og)
            weight += g
            within += 1
        tau2 = (num - noise) / weight if weight else 0.0
        within_strength = 0.25 / tau2 if tau2 > 0 else None

        # The same pair on both patches.
        pairs: list[tuple[float, float, int, int]] = []
        split_num = split_den = 0.0
        for key, (w_new, g_new) in new.items():
            if key not in old:
                continue
            c, pos, _ = key
            if (c, pos) not in own_new or (c, pos) not in own_old:
                continue
            w_old, g_old = old[key]
            p_new = own_new[(c, pos)][0] / own_new[(c, pos)][1]
            p_old = own_old[(c, pos)][0] / own_old[(c, pos)][1]
            d_old = w_old / g_old - p_old
            d_new = w_new / g_new - p_new
            pairs.append((d_old, d_new, g_old, g_new))
            predicted = g_old * d_old / (g_old + strength)
            split_num += g_new * predicted * d_new
            split_den += g_new * predicted * predicted

        scopes.append(
            ScopeReport(
                scope=scope,
                strength_in_use=strength,
                repeatability=[r for r in (_repeatability(pairs, m) for m in (3, 5, 10)) if r],
                within_pairs=within,
                within_strength=within_strength,
                split_pairs=len(pairs),
                split_slope=split_num / split_den if split_den else None,
            )
        )
    return PriorsReport(queue_id, newer, older, scopes)
