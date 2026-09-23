"""Draft suggestions.

Given a role, what is already picked, and what is banned, rank the champions
worth taking, and show every record behind the ranking.

**Ranked on what the corpus supports.** Each champion starts from its own win
rate in the role on the default patch, shown with its Wilson range, and the
list is ordered by the low end of that range, as the tier list is, so a thin
sample does not float to the top. The board then moves it by what the records
support, read by `evidence.read_records`: a posterior with a measured prior,
patch by patch against the champion's own rate, symmetric in wins and losses.

**Only lane records move the ranking.** Measured 2026-09-24 (see `evidence`):
a lane record's deviation repeats from one patch to the next, so lane matchups
are real and measurable; enemy-team and ally records do not measurably repeat
on this corpus. They are returned with their samples and their calls, so the
page can show them, but they are not scored until `python -m scripts.ingest
draftpriors` finds them repeating. Records pool the patch before the default
one when it is close enough (`aggregate.poolable_patches`), which doubles the
lane pairs with ten or more games (120 to 244 on 16.18).

**Comfort is a preference, not evidence.** The player's mastery, weighted by how
recently they played the champion, adds up to `COMFORT_MAX_BONUS` points at a
weight of 1. It moves the ranking, and it is shown as its own figure beside the
range rather than inside it.

Before 2026-09-24 records were measured against the champion's Wilson lower
bound and a margin sized on one proportion was subtracted from another: Ekko
took +3.3 points from one 7-1 record over eight games while three records of
8-13 counted nothing, and a 2-0 lane record moved Cassiopeia from fifth to
fourth.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChampionMastery, ChampionStat, MatchupStat, SynergyStat
from app.services.aggregate import (
    ALL_BRACKETS,
    MIN_LANE_TIMELINES,
    MIN_LANING_TIMELINES,
    aggregated_slices,
    poolable_patches,
    wilson_lower_bound,
    wilson_upper_bound,
)
from app.services.evidence import (
    ALLY_STRENGTH,
    LANE_STRENGTH,
    TEAM_STRENGTH,
    Call,
    OwnRates,
    RecordPart,
    parts_by_patch,
    read_records,
)
from app.services.roles import assign_partial, load_priors, usual_share

log = logging.getLogger(__name__)

# The most all the scored records together may move a pick, in win-rate points.
CONTEXT_LIFT_CAP = 0.08

# Mastery points that count as "fully comfortable".
COMFORT_CEILING = 100_000.0

# Win-rate points a fully comfortable champion gains at a weight of 1.0. The
# page offers up to 0.4, so at most 4 points: enough to break a tie between
# similar picks without letting comfort outrank a genuinely better champion.
COMFORT_MAX_BONUS = 0.10

# Comfort fades with time since the champion was last played: full within a
# month, half at six months, a quarter from a year on. Mastery points never
# decay, and a champion untouched for two years counted as fully comfortable.
# A judgement about a preference, stated as one, not a measurement.
COMFORT_FULL_DAYS = 30
COMFORT_HALF_DAYS = 180
COMFORT_FLOOR_DAYS = 365

# An enemy counts as possibly in your lane from this probability. Below it the
# record is noise weighted by almost nothing, and listing it would crowd the row.
MIN_LANE_WEIGHT = 0.05
# With no lane opponent at least this likely, the pick is a blind one, and the
# page lists each suggestion's worst known lanes instead.
BLIND_BELOW = 0.5
# An ally who plays your role in this share of their games is flagged: the
# board says so rather than letting a mis-set role go unnoticed.
CLASH_SHARE = 0.6
CLASH_MIN_GAMES = 20
# The worst lanes shown for a blind pick.
BLIND_RISKS = 2

EvidenceKind = Literal["lane", "enemy", "ally"]


@dataclass(slots=True)
class Evidence:
    """One record about a pick, with its sample and how it was read."""

    kind: EvidenceKind
    # The other champion: the laner, an enemy pick, or an ally.
    champion_id: int
    games: int
    wins: int
    win_rate: float
    # The champion's own rate over the same patches: the record's reference.
    own_rate: float
    lift: float
    call: Call
    # Whether this record moves the ranking (lane only, for now).
    scored: bool
    patches: tuple[str, ...]
    # Lane only, and only where enough games have timelines.
    gold_diff_14: float | None = None
    laning_score: float | None = None
    timeline_games: int = 0
    # How likely the record applies: the chance this enemy is in your lane (1
    # when you marked them), or, for a blind pick's risk, how often that
    # opponent is picked in the role.
    weight: float = 1.0


@dataclass(slots=True)
class Laning:
    """A champion's own laning figures in the role, over its games with timelines."""

    gold_diff_14: float | None
    cs_diff_14: float | None
    laning_score: float | None
    timeline_games: int


@dataclass
class Suggestion:
    champion_id: int
    games: int
    wins: int
    win_rate: float
    # The Wilson range of the champion's own record, shifted by the context.
    range_low: float
    range_high: float
    # The part of the range's shift that came from the scored records, capped.
    context_lift: float = 0.0
    # Own rate plus the context: the pick's win rate on this board.
    expected: float = 0.0
    comfort: float = 0.0
    comfort_bonus: float = 0.0
    mastery_points: int = 0
    last_played_days: int | None = None
    # What the list is sorted by: the low end plus comfort.
    rank_score: float = 0.0
    # The low end with no board at all, kept for pages loaded before this model.
    base_low: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    # Its place in the full ranking, and whether it is under the sample floor
    # (a champion checked by hand can be).
    rank: int | None = None
    below_min: bool = False
    # With no lane opponent known: the lanes this pick is known to lose.
    blind_risks: list[Evidence] = field(default_factory=list)
    laning: Laning | None = None


@dataclass(slots=True)
class RoleGuess:
    champion_id: int
    position: str
    probability: float


@dataclass
class BoardRead:
    """What the board says before any champion is scored."""

    # Enemy -> the chance they are in your lane; {laner: 1.0} when marked.
    lane_weights: dict[int, float] = field(default_factory=dict)
    lane_opponent: int | None = None
    lane_source: Literal["marked", "inferred"] | None = None
    lane_probability: float = 0.0
    # Bot and support: the enemy's other bot laner, most likely.
    duo: int | None = None
    enemy_roles: list[RoleGuess] = field(default_factory=list)
    ally_roles: list[RoleGuess] = field(default_factory=list)
    # An ally who mostly plays your role, and how much of the time.
    role_clash: tuple[int, float] | None = None

    @property
    def blind(self) -> bool:
        return self.lane_probability < BLIND_BELOW


@dataclass
class BanCandidate:
    """A champion worth denying: the strongest picks, by the low end."""

    champion_id: int
    position: str
    games: int
    wins: int
    win_rate: float
    range_low: float
    range_high: float
    # Records against the champions your team has locked in, shown, not scored.
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.range_low


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
    # When "now" is, for how long ago a champion was played. Tests pin it.
    now: float | None = None
    # With no laner marked: whether to infer one from the enemy picks.
    infer_lane: bool = True

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


def _clamp(rate: float) -> float:
    return max(0.0, min(1.0, rate))


def recency(days: float | None) -> float:
    """How much of a champion's mastery still counts, by days since it was played."""
    if days is None:
        return 1.0
    if days <= COMFORT_FULL_DAYS:
        return 1.0
    if days <= COMFORT_HALF_DAYS:
        return 1.0 - 0.5 * (days - COMFORT_FULL_DAYS) / (COMFORT_HALF_DAYS - COMFORT_FULL_DAYS)
    if days <= COMFORT_FLOOR_DAYS:
        return 0.5 - 0.25 * (days - COMFORT_HALF_DAYS) / (COMFORT_FLOOR_DAYS - COMFORT_HALF_DAYS)
    return 0.25



class DraftAdvisor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def read_board(self, ctx: DraftContext) -> BoardRead:
        """The enemies' likely roles and your lane opponent, before any scoring.

        A marked laner is certain. Otherwise each enemy's chance of being in
        your lane comes from how often it plays each role
        (`roles.assign_partial`), and the lane evidence is weighted by it
        rather than trusting one guess: a flex pick split between top and mid
        counts half in each. `infer_lane` off (the page's "no lane opponent
        yet") leaves the lane unknown, which makes the pick a blind one.
        """
        priors = await load_priors(self.session)
        enemies = list(dict.fromkeys(ctx.enemies))
        board = BoardRead()
        if enemies:
            placed = assign_partial(enemies, priors)
            board.enemy_roles = [
                RoleGuess(c, call.position, call.confidence) for c, call in zip(enemies, placed.calls, strict=True)
            ]
            if ctx.enemy_laner is None and ctx.infer_lane:
                board.lane_weights = {
                    c: probs.get(ctx.position, 0.0)
                    for c, probs in zip(enemies, placed.probabilities, strict=True)
                    if probs.get(ctx.position, 0.0) >= MIN_LANE_WEIGHT
                }
            if ctx.position in ("BOTTOM", "UTILITY"):
                partner = "UTILITY" if ctx.position == "BOTTOM" else "BOTTOM"
                chances = {
                    c: probs.get(partner, 0.0)
                    for c, probs in zip(enemies, placed.probabilities, strict=True)
                    if c != ctx.enemy_laner
                }
                if chances:
                    duo = max(chances, key=chances.get)
                    board.duo = duo if chances[duo] >= BLIND_BELOW else None
        if ctx.enemy_laner is not None:
            board.lane_weights = {ctx.enemy_laner: 1.0}
            board.lane_opponent, board.lane_source, board.lane_probability = ctx.enemy_laner, "marked", 1.0
        elif board.lane_weights:
            top = max(board.lane_weights, key=board.lane_weights.get)
            board.lane_opponent, board.lane_source = top, "inferred"
            board.lane_probability = board.lane_weights[top]

        allies = list(dict.fromkeys(ctx.allies))
        if allies:
            placed = assign_partial(allies, priors, exclude=[ctx.position])
            board.ally_roles = [
                RoleGuess(c, call.position, call.confidence) for c, call in zip(allies, placed.calls, strict=True)
            ]
            clashes = []
            for ally in allies:
                share, games = usual_share(priors, ally, ctx.position)
                if games >= CLASH_MIN_GAMES and share >= CLASH_SHARE:
                    clashes.append((share, ally))
            if clashes:
                share, ally = max(clashes)
                board.role_clash = (ally, share)
        return board

    async def suggest(
        self, ctx: DraftContext, *, board: BoardRead | None = None, limit: int = 15
    ) -> list[Suggestion]:
        top, _ = await self.suggest_and_check(ctx, board=board, limit=limit)
        return top

    async def suggest_and_check(
        self,
        ctx: DraftContext,
        *,
        board: BoardRead | None = None,
        include: list[int] | None = None,
        limit: int = 15,
    ) -> tuple[list[Suggestion], list[Suggestion]]:
        """The top of the ranking, and up to three champions checked by hand.

        A checked champion comes back with its place in the whole ranking, or
        flagged as under the sample floor when it has too few games to be in it.
        """
        board = board if board is not None else await self.read_board(ctx)
        pool = await self.pool(ctx)
        own = await self._own_rates(ctx, pool, [ctx.position])
        ranked = await self._ranked(ctx, board, pool, own, await self._role_stats(ctx))
        for place, suggestion in enumerate(ranked, start=1):
            suggestion.rank = place
        top = ranked[:limit]

        wanted = [c for c in dict.fromkeys(include or []) if c not in ctx.unavailable][:3]
        by_id = {s.champion_id: s for s in ranked}
        missing = [c for c in wanted if c not in by_id]
        if missing:
            for suggestion in await self._ranked(ctx, board, pool, own, await self._stats_for(ctx, missing)):
                suggestion.below_min = True
                by_id[suggestion.champion_id] = suggestion
        pinned = [by_id[c] for c in wanted if c in by_id]

        if board.blind:
            await self._blind_risks(ctx, pool, own, [*top, *pinned])
        return top, pinned

    async def _ranked(
        self,
        ctx: DraftContext,
        board: BoardRead,
        pool: tuple[str, ...],
        own: OwnRates,
        stats: list[ChampionStat],
    ) -> list[Suggestion]:
        """Every champion in `stats`, scored and sorted."""
        # The laner counts as taken even when the caller did not also list them
        # among the enemy picks: the champion you are facing is on the board.
        unavailable = ctx.unavailable
        stats = [s for s in stats if s.champion_id not in unavailable]
        if not stats:
            return []
        lanes = await self._lanes(ctx, pool, own, board.lane_weights)
        enemies = await self._enemy_team(ctx, pool, own)
        allies = await self._ally_synergy(ctx, pool, own)
        mastery = await self._mastery(ctx)
        now = ctx.now if ctx.now is not None else time.time()

        suggestions: list[Suggestion] = []
        for stat in stats:
            evidence = [
                *lanes.get(stat.champion_id, ()),
                *enemies.get(stat.champion_id, ()),
                *allies.get(stat.champion_id, ()),
            ]
            context = _cap(sum(e.weight * e.lift for e in evidence if e.scored))
            low = wilson_lower_bound(stat.wins, stat.games)
            high = wilson_upper_bound(stat.wins, stat.games)
            win_rate = stat.wins / stat.games

            points, played_at = mastery.get(stat.champion_id, (0, None))
            days = None if played_at is None else max(0.0, (now * 1000 - played_at) / 86_400_000)
            comfort = min(1.0, points / COMFORT_CEILING) * recency(days)
            bonus = ctx.comfort_weight * comfort * COMFORT_MAX_BONUS

            suggestion = Suggestion(
                champion_id=stat.champion_id,
                games=stat.games,
                wins=stat.wins,
                win_rate=win_rate,
                range_low=_clamp(low + context),
                range_high=_clamp(high + context),
                context_lift=context,
                expected=_clamp(win_rate + context),
                comfort=comfort,
                comfort_bonus=bonus,
                mastery_points=points,
                last_played_days=None if days is None else int(days),
                rank_score=low + context + bonus,
                base_low=low,
                evidence=evidence,
                laning=(
                    Laning(
                        gold_diff_14=stat.avg_gold_diff_14,
                        cs_diff_14=stat.avg_cs_diff_14,
                        laning_score=stat.avg_laning_score,
                        timeline_games=stat.timeline_games,
                    )
                    if (stat.timeline_games or 0) >= MIN_LANING_TIMELINES
                    else None
                ),
            )
            suggestion.reasons = self._explain(suggestion, ctx, board)
            suggestions.append(suggestion)

        suggestions.sort(key=lambda s: s.rank_score, reverse=True)
        return suggestions

    async def ban_candidates(self, ctx: DraftContext, *, limit: int = 5) -> list[BanCandidate]:
        """The strongest picks on the patch, each in its main role, by the low end.

        Records against the allies already locked in are attached for the page
        to show, from each candidate's main role only: taken from every role a
        champion plays, one champion could bring four records against the base
        of one role. They do not reorder the list, for the reason team-scope
        records do not move suggestions.
        """
        unavailable = ctx.unavailable
        best = await self._best_role_stats(ctx)
        candidates = sorted(
            (stat for champion, stat in best.items() if champion not in unavailable),
            key=lambda stat: wilson_lower_bound(stat.wins, stat.games),
            reverse=True,
        )[:limit]
        if not candidates:
            return []
        pool = await self.pool(ctx)
        against = await self._threats_to_allies(ctx, pool, {s.champion_id: s.team_position for s in candidates})

        out: list[BanCandidate] = []
        for stat in candidates:
            candidate = BanCandidate(
                champion_id=stat.champion_id,
                position=stat.team_position,
                games=stat.games,
                wins=stat.wins,
                win_rate=stat.wins / stat.games,
                range_low=wilson_lower_bound(stat.wins, stat.games),
                range_high=wilson_upper_bound(stat.wins, stat.games),
                evidence=against.get(stat.champion_id, []),
            )
            candidate.reasons = [
                f"{candidate.win_rate * 100:.1f}% over {candidate.games} games, "
                f"at least {candidate.range_low * 100:.1f}% on this sample"
            ]
            out.append(candidate)
        return out

    # ------------------------------------------------------------- sources

    async def pool(self, ctx: DraftContext) -> tuple[str, ...]:
        """Every patch a record may come from: the patch and a close one before it."""
        held = [s["patch"] for s in await aggregated_slices(self.session) if s["queue_id"] == ctx.queue_id]
        return poolable_patches(held or [ctx.patch], ctx.patch)

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

    async def _stats_for(self, ctx: DraftContext, champions: list[int]) -> list[ChampionStat]:
        """These champions in the role, whatever their games: for a hand check."""
        return list(
            (
                await self.session.execute(
                    select(ChampionStat).where(
                        ChampionStat.patch == ctx.patch,
                        ChampionStat.queue_id == ctx.queue_id,
                        ChampionStat.team_position == ctx.position,
                        ChampionStat.rank_bracket == ctx.rank_bracket,
                        ChampionStat.champion_id.in_(champions),
                        ChampionStat.games > 0,
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

    async def _own_rates(self, ctx: DraftContext, pool: tuple[str, ...], positions: list[str]) -> OwnRates:
        """Each champion's own rate in these roles on each pooled patch."""
        rows = await self.session.execute(
            select(
                ChampionStat.champion_id, ChampionStat.team_position, ChampionStat.patch,
                ChampionStat.wins, ChampionStat.games,
            ).where(
                ChampionStat.patch.in_(pool),
                ChampionStat.queue_id == ctx.queue_id,
                ChampionStat.team_position.in_(positions),
                ChampionStat.rank_bracket == ctx.rank_bracket,
                ChampionStat.games > 0,
            )
        )
        return {(c, pos, patch): w / g for c, pos, patch, w, g in rows.all()}

    def _evidence(
        self, kind: EvidenceKind, other: int, parts: list[RecordPart], patches: tuple[str, ...],
        strength: float, scored: bool,
    ) -> Evidence | None:
        if not parts:
            return None
        read = read_records(parts, strength)
        return Evidence(
            kind=kind,
            champion_id=other,
            games=read.games,
            wins=read.wins,
            win_rate=read.wins / read.games,
            own_rate=read.own_rate,
            lift=read.lift,
            call=read.call,
            scored=scored,
            patches=patches,
        )

    async def _lanes(
        self, ctx: DraftContext, pool: tuple[str, ...], own: OwnRates, weights: dict[int, float]
    ) -> dict[int, list[Evidence]]:
        """Head-to-head records against whoever may be in the lane, keyed by our champion.

        Each carries the chance that enemy is the laner, and counts in the
        context in that proportion: 1 for a marked laner.
        """
        if not weights:
            return {}
        rows = (
            await self.session.execute(
                select(MatchupStat).where(
                    MatchupStat.patch.in_(pool),
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id.in_(list(weights)),
                    MatchupStat.scope == "LANE",
                )
            )
        ).scalars().all()
        by_pair: dict[tuple[int, int], list[MatchupStat]] = defaultdict(list)
        for row in rows:
            by_pair[(row.champion_id, row.enemy_champion_id)].append(row)

        out: dict[int, list[Evidence]] = defaultdict(list)
        for (champion, enemy), group in by_pair.items():
            parts, patches = parts_by_patch(
                [(r.patch, r.wins, r.games) for r in group], own, champion, ctx.position
            )
            evidence = self._evidence("lane", enemy, parts, patches, LANE_STRENGTH, True)
            if evidence is None:
                continue
            evidence.weight = weights[enemy]
            # The gold lead and laning score pooled over the timelines behind
            # them, and withheld below the floor rather than averaged over two.
            used = [r for r in group if r.patch in patches]
            timelines = sum(r.timeline_games or 0 for r in used)
            if timelines >= MIN_LANE_TIMELINES:
                gold = [r for r in used if r.avg_gold_diff_14 is not None and r.timeline_games]
                laning = [r for r in used if r.avg_laning_score is not None and r.timeline_games]
                if gold:
                    evidence.gold_diff_14 = sum(r.avg_gold_diff_14 * r.timeline_games for r in gold) / sum(
                        r.timeline_games for r in gold
                    )
                if laning:
                    evidence.laning_score = sum(r.avg_laning_score * r.timeline_games for r in laning) / sum(
                        r.timeline_games for r in laning
                    )
            evidence.timeline_games = timelines
            out[champion].append(evidence)
        for records in out.values():
            records.sort(key=lambda e: e.weight, reverse=True)
        return out

    async def _blind_risks(
        self, ctx: DraftContext, pool: tuple[str, ...], own: OwnRates, suggestions: list[Suggestion]
    ) -> None:
        """For a blind pick, each suggestion's worst known lanes.

        Only records the posterior calls unfavoured, ranked by how much they
        cost times how often that opponent is picked in the role, so the list
        is the lanes likely to happen and likely to lose, not the worst of fifty
        thin records (the winner's curse of taking a minimum).
        """
        ids = [s.champion_id for s in suggestions]
        if not ids:
            return
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id, MatchupStat.enemy_champion_id, MatchupStat.patch,
                    MatchupStat.wins, MatchupStat.games,
                ).where(
                    MatchupStat.patch.in_(pool),
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.champion_id.in_(ids),
                    MatchupStat.scope == "LANE",
                    MatchupStat.games > 0,
                )
            )
        ).all()
        picks = (
            await self.session.execute(
                select(ChampionStat.champion_id, ChampionStat.games).where(
                    ChampionStat.patch == ctx.patch,
                    ChampionStat.queue_id == ctx.queue_id,
                    ChampionStat.team_position == ctx.position,
                    ChampionStat.rank_bracket == ctx.rank_bracket,
                )
            )
        ).all()
        total = sum(games for _, games in picks) or 1
        share = {champion: games / total for champion, games in picks}

        by_pair: dict[tuple[int, int], list[tuple[str, int, int]]] = defaultdict(list)
        for champion, enemy, patch, wins, games in rows:
            by_pair[(champion, enemy)].append((patch, wins, games))
        risks: dict[int, list[Evidence]] = defaultdict(list)
        for (champion, enemy), group in by_pair.items():
            parts, patches = parts_by_patch(group, own, champion, ctx.position)
            evidence = self._evidence("lane", enemy, parts, patches, LANE_STRENGTH, False)
            if evidence is None or evidence.call != "unfavoured" or enemy in ctx.unavailable:
                continue
            evidence.weight = share.get(enemy, 0.0)
            risks[champion].append(evidence)
        for suggestion in suggestions:
            found = risks.get(suggestion.champion_id, [])
            found.sort(key=lambda e: -e.lift * e.weight, reverse=True)
            suggestion.blind_risks = found[:BLIND_RISKS]

    async def _enemy_team(
        self, ctx: DraftContext, pool: tuple[str, ...], own: OwnRates
    ) -> dict[int, list[Evidence]]:
        """Records against each enemy pick other than the laner, shown not scored.

        Scope TEAM: "this champion was somewhere on the enemy side", a different
        question from the lane, and the reason the laner is excluded here rather
        than counted twice.
        """
        # A marked laner is lane evidence only. An inferred one may not be the
        # laner, so their team record is listed as well.
        wanted = ctx.other_enemies
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id, MatchupStat.enemy_champion_id, MatchupStat.patch,
                    MatchupStat.wins, MatchupStat.games,
                ).where(
                    MatchupStat.patch.in_(pool),
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.team_position == ctx.position,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.enemy_champion_id.in_(wanted),
                    MatchupStat.scope == "TEAM",
                    MatchupStat.games > 0,
                )
            )
        ).all()
        return self._grouped("enemy", rows, own, ctx.position, TEAM_STRENGTH)

    async def _ally_synergy(
        self, ctx: DraftContext, pool: tuple[str, ...], own: OwnRates
    ) -> dict[int, list[Evidence]]:
        """How each candidate has done beside the allies locked in, shown not scored.

        Summed over the ally's role: SynergyStat is keyed by it, and an ally
        seen in two roles was counted as two records.
        """
        wanted = list(dict.fromkeys(ctx.allies))
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(
                    SynergyStat.champion_id, SynergyStat.ally_champion_id, SynergyStat.patch,
                    SynergyStat.wins, SynergyStat.games,
                ).where(
                    SynergyStat.patch.in_(pool),
                    SynergyStat.queue_id == ctx.queue_id,
                    SynergyStat.team_position == ctx.position,
                    SynergyStat.rank_bracket == ctx.rank_bracket,
                    SynergyStat.ally_champion_id.in_(wanted),
                    SynergyStat.games > 0,
                )
            )
        ).all()
        return self._grouped("ally", rows, own, ctx.position, ALLY_STRENGTH)

    def _grouped(self, kind: EvidenceKind, rows, own: OwnRates, position: str, strength: float):
        by_pair: dict[tuple[int, int], list[tuple[str, int, int]]] = defaultdict(list)
        for champion, other, patch, wins, games in rows:
            by_pair[(champion, other)].append((patch, wins, games))
        out: dict[int, list[Evidence]] = defaultdict(list)
        for (champion, other), group in by_pair.items():
            parts, patches = parts_by_patch(group, own, champion, position)
            evidence = self._evidence(kind, other, parts, patches, strength, False)
            if evidence is not None:
                out[champion].append(evidence)
        return out

    async def _threats_to_allies(
        self, ctx: DraftContext, pool: tuple[str, ...], roles: dict[int, str]
    ) -> dict[int, list[Evidence]]:
        """Each ban candidate's TEAM records against our allies, in its main role only."""
        allies = list(dict.fromkeys(ctx.allies))
        if not allies or not roles:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MatchupStat.champion_id, MatchupStat.team_position, MatchupStat.enemy_champion_id,
                    MatchupStat.patch, MatchupStat.wins, MatchupStat.games,
                ).where(
                    MatchupStat.patch.in_(pool),
                    MatchupStat.queue_id == ctx.queue_id,
                    MatchupStat.rank_bracket == ctx.rank_bracket,
                    MatchupStat.champion_id.in_(list(roles)),
                    MatchupStat.enemy_champion_id.in_(allies),
                    MatchupStat.scope == "TEAM",
                    MatchupStat.games > 0,
                )
            )
        ).all()
        own = await self._own_rates(ctx, pool, sorted(set(roles.values())))
        by_pair: dict[tuple[int, int], list[tuple[str, int, int]]] = defaultdict(list)
        for champion, position, ally, patch, wins, games in rows:
            if roles.get(champion) != position:
                continue
            by_pair[(champion, ally)].append((patch, wins, games))
        out: dict[int, list[Evidence]] = defaultdict(list)
        for (champion, ally), group in by_pair.items():
            parts, patches = parts_by_patch(group, own, champion, roles[champion])
            evidence = self._evidence("ally", ally, parts, patches, TEAM_STRENGTH, False)
            if evidence is not None:
                out[champion].append(evidence)
        return out

    async def _mastery(self, ctx: DraftContext) -> dict[int, tuple[int, int | None]]:
        if not ctx.puuid:
            return {}
        rows = (
            await self.session.execute(
                select(
                    ChampionMastery.champion_id,
                    ChampionMastery.champion_points,
                    ChampionMastery.last_play_time,
                ).where(ChampionMastery.puuid == ctx.puuid)
            )
        ).all()
        return {champion: (points, played) for champion, points, played in rows}

    # ------------------------------------------------------------ wording

    @staticmethod
    def _explain(s: Suggestion, ctx: DraftContext, board: BoardRead) -> list[str]:
        """Sentences for what is not a record. The page writes the record lines
        itself, with the champions' names, from `evidence`."""
        reasons: list[str] = []
        if board.lane_source == "marked" and not any(e.kind == "lane" for e in s.evidence):
            reasons.append("no head-to-head record for this lane yet")
        if s.mastery_points >= 10_000:
            when = ""
            if s.last_played_days is not None and s.last_played_days > COMFORT_FULL_DAYS:
                months = max(1, round(s.last_played_days / 30))
                when = f", last played {months} month{'s' if months != 1 else ''} ago"
            reasons.append(f"{s.mastery_points // 1000}k mastery points{when}")
        elif ctx.puuid and s.mastery_points == 0:
            reasons.append("never played on this account")
        return reasons


__all__ = [
    "BLIND_BELOW",
    "BoardRead",
    "COMFORT_MAX_BONUS",
    "Laning",
    "RoleGuess",
    "CONTEXT_LIFT_CAP",
    "MIN_LANE_TIMELINES",
    "BanCandidate",
    "DraftAdvisor",
    "DraftContext",
    "Evidence",
    "Suggestion",
    "recency",
]
