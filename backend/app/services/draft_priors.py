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

It also reports how teams fared by how one-sided their damage was, read from
their champions' usual profiles (`damage`), which is what a draft knows. The
draft shows the mix and does not score it; this is the measurement that would
have to say otherwise first.

Two more priors the pages use are measured here too. The spread of champion
win rates in a role, which says how many games a champion's own record needs
before it is half signal (about 950 on 16.18) and how well the tier list's
order on one patch predicts the next. And the spread of players' average
scores on a champion, which sets how far the best-players board pulls a short
record toward the champion's average (`PLAYER_SCORE_STRENGTH`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionStat, Match, MatchParticipant, MatchupStat, SynergyStat
from app.services.aggregate import (
    ALL_BRACKETS,
    POSITIONS,
    TIER_MIN_GAMES,
    aggregated_slices,
    poolable_patches,
    wilson_lower_bound,
    wilson_upper_bound,
)
from app.services.damage import load_profiles, team_mix
from app.services.evidence import ALLY_STRENGTH, LANE_STRENGTH, TEAM_STRENGTH

# The champion's own record needs this many games to be a reference at all.
MIN_OWN_GAMES = 20

SCOPES = (("lane", LANE_STRENGTH), ("enemy team", TEAM_STRENGTH), ("ally", ALLY_STRENGTH))

# Where the damage report cuts teams by the share of their main damage type.
# The draft calls a side one-sided at 70%.
MIX_EDGES = (0.6, 0.7, 0.8)


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
class MixBucket:
    # The main type's share of the team's damage, from `low` up to `high`.
    low: float
    high: float | None
    teams: int
    wins: int


@dataclass(slots=True)
class DamageMixReport:
    # Teams whose five champions all had a profile, and those left out.
    teams: int
    unmeasured: int
    buckets: list[MixBucket]


@dataclass(slots=True)
class ChampionRateReport:
    """How far champion win rates in a role truly differ, and what that means."""

    # Champion and role rows with `TIER_MIN_GAMES` or more on the newer patch.
    rows: int
    # The true spread of their win rates, beyond binomial noise, and the prior
    # strength in games it implies: a record of that many games is half signal.
    spread: float | None
    strength: float | None
    # Rows whose whole range sits above 50%, and below it.
    separated_above: int
    separated_below: int
    # The older patch's top and bottom tenth by the tier list's order (the
    # range's low end), and the win rate each group had on the newer patch.
    split_rows: int = 0
    top_next: float | None = None
    bottom_next: float | None = None


@dataclass(slots=True)
class PlayerScoreReport:
    """How far players' average scores on a champion truly differ."""

    # Player and champion pairs with `min_scored` or more scored games.
    pairs: int
    min_scored: int
    # A game's score around the player's own average, and players' true
    # averages around each other: their ratio of variances is the strength.
    within_sd: float | None
    between_sd: float | None
    strength: float | None


@dataclass(slots=True)
class PriorsReport:
    queue_id: int
    newer: str | None
    older: str | None
    scopes: list[ScopeReport]
    damage: DamageMixReport | None = None
    champion_rates: ChampionRateReport | None = None
    player_scores: PlayerScoreReport | None = None


def rate_spread(rows: list[tuple[int, int]]) -> tuple[float | None, float | None]:
    """(wins, games) rows: the true spread of their rates, and its prior strength.

    Games-weighted method of moments: the rows' spread around the pooled rate,
    less what binomial noise alone produces. None where the noise explains it all.
    """
    games = sum(g for _, g in rows)
    if not rows or not games:
        return None, None
    pooled = sum(w for w, _ in rows) / games
    spread = sum(g * (w / g - pooled) ** 2 for w, g in rows)
    noise = sum((w / g) * (1 - w / g) for w, g in rows)
    tau2 = (spread - noise) / games
    if tau2 <= 0:
        return None, None
    return math.sqrt(tau2), pooled * (1 - pooled) / tau2


def score_prior(groups: list[list[float]]) -> tuple[float | None, float | None, float | None]:
    """Scores grouped by player: (within sd, between sd, prior strength in games)."""
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return None, None, None
    within = sum(
        sum((x - sum(g) / len(g)) ** 2 for x in g) / (len(g) - 1) for g in groups
    ) / len(groups)
    means = [sum(g) / len(g) for g in groups]
    grand = sum(means) / len(means)
    between = sum((m - grand) ** 2 for m in means) / len(means) - sum(
        within / len(g) for g in groups
    ) / len(groups)
    if between <= 0:
        return math.sqrt(within), None, None
    return math.sqrt(within), math.sqrt(between), within / between


async def _role_rates(session: AsyncSession, patch: str, queue_id: int) -> dict[tuple[int, str], tuple[int, int]]:
    rows = await session.execute(
        select(ChampionStat.champion_id, ChampionStat.team_position, ChampionStat.wins, ChampionStat.games).where(
            ChampionStat.patch == patch,
            ChampionStat.queue_id == queue_id,
            ChampionStat.rank_bracket == ALL_BRACKETS,
            ChampionStat.team_position.in_(POSITIONS),
            ChampionStat.games >= TIER_MIN_GAMES,
        )
    )
    return {(c, pos): (w, g) for c, pos, w, g in rows.all()}


async def champion_rates(
    session: AsyncSession, queue_id: int, newer: str, older: str | None
) -> ChampionRateReport:
    new = await _role_rates(session, newer, queue_id)
    spread, strength = rate_spread(list(new.values()))
    report = ChampionRateReport(
        rows=len(new),
        spread=spread,
        strength=strength,
        separated_above=sum(1 for w, g in new.values() if wilson_lower_bound(w, g) >= 0.5),
        separated_below=sum(1 for w, g in new.values() if wilson_upper_bound(w, g) <= 0.5),
    )
    if older is None:
        return report
    old = await _role_rates(session, older, queue_id)
    both = sorted(
        (k for k in old if k in new), key=lambda k: wilson_lower_bound(*old[k]), reverse=True
    )
    tenth = len(both) // 10
    report.split_rows = len(both)
    if tenth:
        def next_rate(keys: list) -> float:
            return sum(new[k][0] for k in keys) / sum(new[k][1] for k in keys)

        report.top_next = next_rate(both[:tenth])
        report.bottom_next = next_rate(both[-tenth:])
    return report


async def player_scores(session: AsyncSession, min_scored: int = 5) -> PlayerScoreReport:
    rows = await session.execute(
        select(MatchParticipant.champion_id, MatchParticipant.puuid, MatchParticipant.performance_score)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(
            Match.is_remake.is_(False),
            MatchParticipant.team_position.in_(POSITIONS),
            MatchParticipant.performance_score.is_not(None),
        )
    )
    grouped: dict[tuple[int, str], list[float]] = {}
    for champion, puuid, score in rows.all():
        grouped.setdefault((champion, puuid), []).append(float(score))
    groups = [g for g in grouped.values() if len(g) >= min_scored]
    within, between, strength = score_prior(groups)
    return PlayerScoreReport(
        pairs=len(groups), min_scored=min_scored, within_sd=within, between_sd=between, strength=strength
    )


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


async def _damage_mix(session: AsyncSession, queue_id: int, patches: tuple[str, ...]) -> DamageMixReport:
    """How teams fared by how one-sided their champions' usual damage was."""
    profiles = await load_profiles(session, patches)
    rows = await session.execute(
        select(
            MatchParticipant.match_id,
            MatchParticipant.team_id,
            MatchParticipant.champion_id,
            MatchParticipant.team_position,
            MatchParticipant.win,
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(
            Match.queue_id == queue_id,
            Match.patch.in_(list(patches)),
            Match.is_remake.is_(False),
        )
    )
    teams: dict[tuple[str, int], list[tuple[int, str | None, bool]]] = {}
    for match_id, team_id, champion, position, win in rows.all():
        teams.setdefault((match_id, team_id), []).append((champion, position or None, bool(win)))

    edges = (0.0, *MIX_EDGES)
    buckets = [MixBucket(low, high, 0, 0) for low, high in zip(edges, (*MIX_EDGES, None), strict=True)]
    measured = unmeasured = 0
    for players in teams.values():
        if len(players) != 5:
            continue
        mix = team_mix(profiles, [(champion, position) for champion, position, _ in players])
        if mix.missing or mix.shares is None:
            unmeasured += 1
            continue
        measured += 1
        _, share = mix.shares.dominant
        bucket = next(b for b in reversed(buckets) if share >= b.low)
        bucket.teams += 1
        bucket.wins += int(players[0][2])
    return DamageMixReport(teams=measured, unmeasured=unmeasured, buckets=buckets)


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
    return PriorsReport(
        queue_id,
        newer,
        older,
        scopes,
        await _damage_mix(session, queue_id, pool),
        await champion_rates(session, queue_id, newer, older),
        await player_scores(session),
    )
