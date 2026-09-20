"""Draft suggestions.

Given a role, what is already picked, and what is banned, rank the champions
worth taking.

The scoring is deliberately transparent and every component comes back in the
response. A draft tool that answers "pick Malphite" with no reason is one nobody
trusts on the third pick, so the baseline, every record behind an adjustment and
the mastery weighting are all visible on the card.

**What the list is sorted by is what the evidence supports, not what it claims.**
Measured on the live API on 2026-09-21: mid into Ahri put Yone first, lifting a
50.7% baseline to 60.0% on a 10-2 record over twelve games. The tier list refuses
to let a thin sample top a list; this used to do exactly that. Every record now
gives up the part its own sample cannot support (``credible``), and the ranking
adds only the remainder. The unrestrained figure stays in the response as
``adjusted_win_rate``, which is the honest "if that record holds" number.

Four kinds of evidence, all local rollups, all reported with their samples:

* **Base** -- how the champion performs in this role on this patch, as a Wilson
  lower bound so thin samples do not float to the top.
* **Lane** -- the head-to-head record against the enemy laner (``MatchupStat``,
  scope LANE), with the gold lead at 14 minutes where timelines exist.
* **The enemy team** -- the record against each other enemy pick (scope TEAM).
  A champion can be fine in lane and hopeless into the composition, and only
  this scope sees that. It is also where the data is: 1,838 champion pairs with
  ten or more games on 16.18, against 288 in lane.
* **Allies** -- how the champion does alongside each ally already locked in
  (``SynergyStat``).

and one preference, not evidence:

* **Comfort** -- the player's own mastery. A 51% champion with 200k points beats
  a 54% champion they have never played, and every draft tool that ignores this
  gives advice people cannot execute.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionMastery, ChampionStat, MatchupStat, SynergyStat
from app.services.aggregate import ALL_BRACKETS, WILSON_Z, wilson_lower_bound

log = logging.getLogger(__name__)

# Games at which a record earns half its weight. Below this the estimate is
# pulled toward the champion's own baseline. Lane records are the most direct
# evidence there is, so they are shrunk least; a champion being somewhere on the
# enemy side, or beside an ally, says less per game.
MATCHUP_SHRINKAGE = 30.0
TEAM_SHRINKAGE = 40.0
ALLY_SHRINKAGE = 40.0

# The most all the context put together may move a pick, in win-rate points.
# Nine sources (one lane, four enemies, four allies) each pulling a few points
# in the same direction would otherwise add up to a number no sample supports.
CONTEXT_LIFT_CAP = 0.08

# Mastery points that count as "fully comfortable".
COMFORT_CEILING = 100_000.0

# Win-rate points a fully comfortable champion can gain at comfort_weight 1.0.
# Scored in the same units as win rate so the two are directly comparable: at
# the default weight of 0.15 a maxed-out champion pool is worth +1.5pp, enough
# to break a tie between similar picks without letting comfort outrank a
# genuinely better champion.
COMFORT_MAX_BONUS = 0.10

# Below this many games with a timeline, a lane's gold lead at 14 is one stomp.
MIN_TIMELINE_GAMES = 5

EvidenceKind = Literal["lane", "enemy", "ally"]


def credible_lift(
    observed: float, base: float, games: int, shrinkage: float
) -> tuple[float, float]:
    """What a record claims, and what its own sample can support.

    The first number is the existing shrinkage: a record counts for
    ``games / (games + shrinkage)`` of the distance between it and the
    champion's baseline. The second takes off that record's own standard error,
    scaled the same way, and never crosses zero. A 10-2 lane record claims about
    +9 win-rate points and supports about +3; a 55% over twenty games claims
    +1.8 and supports nothing at all, which is the honest reading of 20 games.
    """
    if games <= 0:
        return 0.0, 0.0
    weight = games / (games + shrinkage)
    claimed = weight * (observed - base)
    # The record's own standard error, weighted like the lift it is qualifying.
    # Taken on the Agresti-Coull adjusted proportion rather than the raw one,
    # because the raw error of a perfect record is zero: a 2-0 was giving up
    # almost nothing and arguing for +2.6 points.
    padded = games + WILSON_Z**2
    adjusted = (observed * games + WILSON_Z**2 / 2) / padded
    margin = WILSON_Z * math.sqrt(adjusted * (1 - adjusted) / padded) * weight
    if claimed >= 0:
        return claimed, max(0.0, claimed - margin)
    return claimed, min(0.0, claimed + margin)


@dataclass(slots=True)
class Evidence:
    """One record that argues for or against a pick, with its sample."""

    kind: EvidenceKind
    # The other champion: the laner, an enemy pick, or an ally.
    champion_id: int
    games: int
    wins: int
    win_rate: float
    # What the record claims, and the part its sample supports.
    lift: float
    credible_lift: float
    # Lane only, and only where timelines exist.
    gold_diff_14: float | None = None
    laning_score: float | None = None
    timeline_games: int = 0


@dataclass
class Suggestion:
    champion_id: int
    base_win_rate: float
    games: int
    matchup_win_rate: float | None = None
    matchup_games: int = 0
    # Baseline plus everything the records claim: "if they hold".
    adjusted_win_rate: float = 0.0
    comfort: float = 0.0
    mastery_points: int = 0
    # What the list is sorted by: baseline plus what the records support.
    score: float = 0.0
    comfort_bonus: float = 0.0
    # The part of the score that came from the board, after the cap.
    context_lift: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class BanCandidate:
    """A champion worth denying, scored the same way from the other side."""

    champion_id: int
    position: str
    base_win_rate: float
    games: int
    score: float
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class DraftContext:
    position: str
    patch: str
    queue_id: int = 420
    # Rollups are stored per bracket, and ALL overlaps the per-tier slices. A
    # query without this returns the same champion once per bracket it appears
    # in, so it is a filter, not a preference.
    rank_bracket: str = ALL_BRACKETS
    allies: list[int] = field(default_factory=list)
    enemies: list[int] = field(default_factory=list)
    bans: list[int] = field(default_factory=list)
    # The enemy champion actually in this lane, when the client knows it.
    enemy_laner: int | None = None
    puuid: str | None = None
    comfort_weight: float = 0.15
    min_games: int = 20

    @property
    def unavailable(self) -> set[int]:
        """Champions nobody can pick any more, the lane opponent included."""
        taken = set(self.allies) | set(self.enemies) | set(self.bans)
        if self.enemy_laner is not None:
            taken.add(self.enemy_laner)
        return taken

    @property
    def other_enemies(self) -> list[int]:
        """Enemy picks other than the laner, who is counted as lane evidence."""
        return [c for c in dict.fromkeys(self.enemies) if c != self.enemy_laner]


def _cap(total: float) -> float:
    return max(-CONTEXT_LIFT_CAP, min(CONTEXT_LIFT_CAP, total))


class DraftAdvisor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def suggest(self, ctx: DraftContext, *, limit: int = 15) -> list[Suggestion]:
        # The laner counts as taken even when the caller did not also list them
        # among the enemy picks: the champion you are facing is on the board.
        unavailable = ctx.unavailable
        stats = await self._role_stats(ctx)
        if not stats:
            return []

        lane = await self._lane(ctx)
        enemies = await self._enemy_team(ctx)
        allies = await self._ally_synergy(ctx)
        mastery = await self._mastery(ctx)

        suggestions: list[Suggestion] = []
        for stat in stats:
            if stat.champion_id in unavailable:
                continue

            base = wilson_lower_bound(stat.wins, stat.games)
            suggestion = Suggestion(
                champion_id=stat.champion_id,
                base_win_rate=base,
                games=stat.games,
                adjusted_win_rate=base,
            )
            evidence: list[Evidence] = []

            row = lane.get(stat.champion_id)
            if row is not None and row.games > 0:
                observed = row.wins / row.games
                claimed, supported = credible_lift(
                    observed, base, row.games, MATCHUP_SHRINKAGE
                )
                suggestion.matchup_win_rate = observed
                suggestion.matchup_games = row.games
                evidence.append(
                    Evidence(
                        kind="lane",
                        champion_id=row.enemy_champion_id,
                        games=row.games,
                        wins=row.wins,
                        win_rate=observed,
                        lift=claimed,
                        credible_lift=supported,
                        # Withheld below the floor rather than averaged over
                        # two games, like every other thin figure here.
                        gold_diff_14=(
                            row.avg_gold_diff_14
                            if row.timeline_games >= MIN_TIMELINE_GAMES
                            else None
                        ),
                        laning_score=(
                            row.avg_laning_score
                            if row.timeline_games >= MIN_TIMELINE_GAMES
                            else None
                        ),
                        timeline_games=row.timeline_games or 0,
                    )
                )

            for kind, rows, shrinkage in (
                ("enemy", enemies.get(stat.champion_id, ()), TEAM_SHRINKAGE),
                ("ally", allies.get(stat.champion_id, ()), ALLY_SHRINKAGE),
            ):
                for other, wins, games in rows:
                    observed = wins / games
                    claimed, supported = credible_lift(observed, base, games, shrinkage)
                    evidence.append(
                        Evidence(
                            kind=kind,
                            champion_id=other,
                            games=games,
                            wins=wins,
                            win_rate=observed,
                            lift=claimed,
                            credible_lift=supported,
                        )
                    )

            suggestion.evidence = evidence
            # Uncapped, and clamped only to a real win rate: this is the "if
            # those records hold" figure, and a 40-game 75% lane record really
            # does claim that much. The cap belongs to the ranking, below.
            suggestion.adjusted_win_rate = min(
                1.0, max(0.0, base + sum(e.lift for e in evidence))
            )
            suggestion.context_lift = _cap(sum(e.credible_lift for e in evidence))

            points = mastery.get(stat.champion_id, 0)
            suggestion.mastery_points = points
            suggestion.comfort = min(1.0, points / COMFORT_CEILING)
            suggestion.comfort_bonus = (
                ctx.comfort_weight * suggestion.comfort * COMFORT_MAX_BONUS
            )

            suggestion.score = base + suggestion.context_lift + suggestion.comfort_bonus
            suggestion.reasons = self._explain(suggestion, ctx)
            suggestions.append(suggestion)

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:limit]

    async def ban_candidates(
        self, ctx: DraftContext, *, limit: int = 5
    ) -> list[BanCandidate]:
        """Who to deny: the same scoring, read from the enemy's side.

        A champion is judged on its own baseline plus its record against the
        allies already locked in. With nothing locked in there is no draft to
        read, so this degrades to the strongest picks of the patch, and the
        caller says so rather than implying it knows more than it does.
        """
        unavailable = ctx.unavailable
        best_by_champion = await self._best_role_stats(ctx)
        against_allies = await self._threats_to_allies(ctx)

        out: list[BanCandidate] = []
        for champion_id, stat in best_by_champion.items():
            if champion_id in unavailable:
                continue
            base = wilson_lower_bound(stat.wins, stat.games)
            evidence = []
            for ally, wins, games in against_allies.get(champion_id, ()):
                observed = wins / games
                claimed, supported = credible_lift(observed, base, games, TEAM_SHRINKAGE)
                evidence.append(
                    Evidence(
                        kind="ally",
                        champion_id=ally,
                        games=games,
                        wins=wins,
                        win_rate=observed,
                        lift=claimed,
                        credible_lift=supported,
                    )
                )
            candidate = BanCandidate(
                champion_id=champion_id,
                position=stat.team_position,
                base_win_rate=base,
                games=stat.games,
                score=base + _cap(sum(e.credible_lift for e in evidence)),
                evidence=evidence,
            )
            candidate.reasons = self._explain_ban(candidate)
            out.append(candidate)

        out.sort(key=lambda c: c.score, reverse=True)
        return out[:limit]

    # ------------------------------------------------------------- sources

    async def _role_stats(self, ctx: DraftContext) -> list[ChampionStat]:
        return list(
            (
                await self.session.execute(
                    select(ChampionStat).where(
                        ChampionStat.patch == ctx.patch,
                        ChampionStat.queue_id == ctx.queue_id,
                        ChampionStat.team_position == ctx.position,
                        ChampionStat.rank_bracket == ctx.rank_bracket,
                        ChampionStat.games >= ctx.min_games,
                    )
                )
            ).scalars()
        )

    async def _best_role_stats(self, ctx: DraftContext) -> dict[int, ChampionStat]:
        """Every champion in its most played role, for the ban list."""
        rows = (
            await self.session.execute(
                select(ChampionStat).where(
                    ChampionStat.patch == ctx.patch,
                    ChampionStat.queue_id == ctx.queue_id,
                    ChampionStat.rank_bracket == ctx.rank_bracket,
                    ChampionStat.team_position != "ALL",
                    ChampionStat.games >= ctx.min_games,
                )
            )
        ).scalars()
        best: dict[int, ChampionStat] = {}
        for row in rows:
            held = best.get(row.champion_id)
            if held is None or row.games > held.games:
                best[row.champion_id] = row
        return best

    async def _lane(self, ctx: DraftContext) -> dict[int, MatchupStat]:
        """Head-to-head records against the enemy laner, keyed by our champion."""
        if ctx.enemy_laner is None:
            return {}
        rows = (
            await self.session.execute(
                select(MatchupStat).where(
                    MatchupStat.patch == ctx.patch,
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id == ctx.enemy_laner,
                    MatchupStat.scope == "LANE",
                )
            )
        ).scalars()
        return {row.champion_id: row for row in rows}

    async def _enemy_team(self, ctx: DraftContext) -> dict[int, list[tuple[int, int, int]]]:
        """Records against each enemy pick other than the laner.

        Scope TEAM: "this champion was somewhere on the enemy side", which is a
        different question from the lane, and the reason the laner is excluded
        here rather than counted twice.
        """
        wanted = ctx.other_enemies
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id,
                    MatchupStat.enemy_champion_id,
                    MatchupStat.wins,
                    MatchupStat.games,
                ).where(
                    MatchupStat.patch == ctx.patch,
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id.in_(wanted),
                    MatchupStat.scope == "TEAM",
                    MatchupStat.games > 0,
                )
            )
        ).all()
        out: dict[int, list[tuple[int, int, int]]] = {}
        for champion, enemy, wins, games in rows:
            out.setdefault(champion, []).append((enemy, wins, games))
        return out

    async def _threats_to_allies(
        self, ctx: DraftContext
    ) -> dict[int, list[tuple[int, int, int]]]:
        """The same TEAM records, read as "how this champion does against ours"."""
        if not ctx.allies:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id,
                    MatchupStat.enemy_champion_id,
                    MatchupStat.wins,
                    MatchupStat.games,
                ).where(
                    MatchupStat.patch == ctx.patch,
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id.in_(list(dict.fromkeys(ctx.allies))),
                    MatchupStat.scope == "TEAM",
                    MatchupStat.games > 0,
                )
            )
        ).all()
        out: dict[int, list[tuple[int, int, int]]] = {}
        for champion, ally, wins, games in rows:
            out.setdefault(champion, []).append((ally, wins, games))
        return out

    async def _ally_synergy(self, ctx: DraftContext) -> dict[int, list[tuple[int, int, int]]]:
        """How each candidate has done alongside the allies already locked in."""
        wanted = list(dict.fromkeys(ctx.allies))
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(
                    SynergyStat.champion_id,
                    SynergyStat.ally_champion_id,
                    SynergyStat.wins,
                    SynergyStat.games,
                ).where(
                    SynergyStat.patch == ctx.patch,
                    SynergyStat.queue_id == ctx.queue_id,
                    SynergyStat.team_position == ctx.position,
                    SynergyStat.rank_bracket == ctx.rank_bracket,
                    SynergyStat.ally_champion_id.in_(wanted),
                    SynergyStat.games > 0,
                )
            )
        ).all()
        out: dict[int, list[tuple[int, int, int]]] = {}
        for champion, ally, wins, games in rows:
            out.setdefault(champion, []).append((ally, wins, games))
        return out

    async def _mastery(self, ctx: DraftContext) -> dict[int, int]:
        if not ctx.puuid:
            return {}
        rows = (
            await self.session.execute(
                select(ChampionMastery.champion_id, ChampionMastery.champion_points).where(
                    ChampionMastery.puuid == ctx.puuid
                )
            )
        ).all()
        return dict(rows)

    # ------------------------------------------------------------ wording

    @staticmethod
    def _explain(s: Suggestion, ctx: DraftContext) -> list[str]:
        reasons: list[str] = []
        # The row already prints the score. Repeating the same figure underneath
        # it reads as a template filling itself in, so the percentage appears
        # only when the adjustment moved it and the two numbers really differ.
        if s.adjusted_win_rate == s.base_win_rate:
            reasons.append(f"baseline over {s.games} games")
        else:
            reasons.append(
                f"{s.base_win_rate * 100:.1f}% baseline over {s.games} games"
            )

        lane = next((e for e in s.evidence if e.kind == "lane"), None)
        if lane is not None:
            direction = "favoured" if lane.lift >= 0 else "unfavoured"
            supported = (
                f"supports {lane.credible_lift * 100:+.1f} points"
                if lane.credible_lift
                else "too few games to move the score"
            )
            reasons.append(
                f"{direction} into this lane: {lane.win_rate * 100:.0f}% over "
                f"{lane.games} games, {supported}"
            )
            if lane.gold_diff_14 is not None:
                reasons.append(
                    f"usually {lane.gold_diff_14:+,.0f} gold by 14 in that lane, "
                    f"over {lane.timeline_games} games with timelines"
                )
        elif ctx.enemy_laner is not None:
            reasons.append("no head-to-head data for this matchup yet")

        for kind, label in (("enemy", "enemy team"), ("ally", "alongside")):
            rows = [e for e in s.evidence if e.kind == kind and e.credible_lift]
            if rows:
                total = sum(e.credible_lift for e in rows) * 100
                reasons.append(
                    f"{label}: {total:+.1f} points over {len(rows)} "
                    f"{'record' if len(rows) == 1 else 'records'}"
                )

        if s.mastery_points >= 10_000:
            reasons.append(f"{s.mastery_points // 1000}k mastery points")
        elif ctx.puuid and s.mastery_points == 0:
            reasons.append("never played on this account")

        return reasons

    @staticmethod
    def _explain_ban(candidate: BanCandidate) -> list[str]:
        reasons = [f"{candidate.base_win_rate * 100:.1f}% baseline over {candidate.games} games"]
        strong = [e for e in candidate.evidence if e.credible_lift > 0]
        strong.sort(key=lambda e: e.credible_lift, reverse=True)
        for e in strong[:2]:
            reasons.append(
                f"{e.win_rate * 100:.0f}% against one of your picks over {e.games} games"
            )
        return reasons


__all__ = [
    "ALLY_SHRINKAGE",
    "CONTEXT_LIFT_CAP",
    "MATCHUP_SHRINKAGE",
    "MIN_TIMELINE_GAMES",
    "TEAM_SHRINKAGE",
    "BanCandidate",
    "DraftAdvisor",
    "DraftContext",
    "Evidence",
    "Suggestion",
    "credible_lift",
]
