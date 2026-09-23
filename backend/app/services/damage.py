"""Damage profiles: how a champion's damage to champions splits into physical,
magic and true, and what a team's picks add up to.

Read from `match_participants`, where the score stage lifts the three types out
of `matches.raw`, so none of this costs a Riot call. The draft shows it and does
not score it: whether a one-sided team actually loses more is a question for
`python -m scripts.ingest draftpriors`, and until that answers, the page states
the mix and leaves the judgement to the player.

Measured 2026-09-24 on the local corpus (23,517 ranked solo players with a lane
role, 4,703 teams):

- **A profile settles fast.** Two separate ten-game samples of the same
  champion in the same role differ by 1.2 points of physical share at the
  median and 4.1 at the 90th percentile; three-game samples by 2.2 and 7.6.
  Ten games make a profile.
- **The role matters for a few champions.** Twisted Fate dealt 12% physical
  damage in mid and 56% in bot, Kog'Maw 9% in mid and 32% in bot. A profile is
  read in the champion's role when that role has the games, else over all of
  its roles.
- **One-sided teams are rare.** In the games' own totals, 3.7% of teams dealt
  70% or more of one type and 24.7% dealt 60% or more. Seventy is where the
  page calls a team one-sided, so the call means something when it appears.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant
from app.services.aggregate import POSITIONS

DamageType = Literal["physical", "magic", "true"]

# Games a champion needs, in a role or over all of them, before its damage is
# read as a profile. See the module docstring for the measurement.
MIN_PROFILE_GAMES = 10

# The share of one type at which a team is called one-sided, from two measured
# champions: one champion is a pick, not a team.
ONE_SIDED_SHARE = 0.70
MIN_LEANING_CHAMPIONS = 2

# A board champion's profile is read in its likely role from this probability;
# below it, over all its roles, which is what an unplaced flex pick deals.
ROLE_SURE = 0.5

# A kit deals the same damage in solo and flex queue, so a profile pools both:
# a flex board would otherwise leave most champions under the floor.
PROFILE_QUEUES = (420, 440)

# The profile table is one GROUP BY over the pooled patches' players. The board
# asks on every change, so it is kept for ten minutes: short enough that a
# backfill shows within minutes of finishing.
PROFILE_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class Shares:
    """Fractions of damage by type, summing to 1."""

    physical: float
    magic: float
    true: float

    def of(self, kind: DamageType) -> float:
        return {"physical": self.physical, "magic": self.magic, "true": self.true}[kind]

    @property
    def dominant(self) -> tuple[DamageType, float]:
        kinds: tuple[DamageType, ...] = ("physical", "magic", "true")
        kind = max(kinds, key=self.of)
        return kind, self.of(kind)


@dataclass(frozen=True, slots=True)
class Profile:
    """A champion's average damage to champions per game, by type."""

    games: int
    physical: float
    magic: float
    true: float

    @property
    def total(self) -> float:
        return self.physical + self.magic + self.true

    def shares(self) -> Shares:
        total = self.total
        return Shares(self.physical / total, self.magic / total, self.true / total)


@dataclass(slots=True)
class Profiles:
    by_role: dict[tuple[int, str], Profile] = field(default_factory=dict)
    overall: dict[int, Profile] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """No stored game has the damage types yet: the columns await a backfill."""
        return not self.overall

    def get(self, champion_id: int, position: str | None = None) -> Profile | None:
        """The profile in the role when it has the games, else over every role."""
        if position is not None:
            held = self.by_role.get((champion_id, position))
            if held is not None and held.games >= MIN_PROFILE_GAMES and held.total > 0:
                return held
        held = self.overall.get(champion_id)
        if held is not None and held.games >= MIN_PROFILE_GAMES and held.total > 0:
            return held
        return None


@dataclass(slots=True)
class TeamMix:
    """A side's damage, summed over its measured champions' average games.

    Summing the averages weights each champion by how much damage it deals: a
    support that deals a third of a carry's damage moves the mix a third as much.
    """

    shares: Shares | None
    measured: list[int]
    missing: list[int]

    @property
    def leaning(self) -> DamageType | None:
        if self.shares is None or len(self.measured) < MIN_LEANING_CHAMPIONS:
            return None
        kind, share = self.shares.dominant
        return kind if share >= ONE_SIDED_SHARE else None


@dataclass(slots=True)
class PickDamage:
    """A suggestion's own damage in the role, and your team's with it added."""

    own: Shares
    games: int
    team_after: Shares | None
    # The type your team leans to, when this pick deals mostly something else.
    balances: DamageType | None


@dataclass(slots=True)
class DraftDamage:
    available: bool
    allies: TeamMix | None
    enemies: TeamMix | None
    picks: dict[int, PickDamage] = field(default_factory=dict)


def team_mix(profiles: Profiles, members: Iterable[tuple[int, str | None]]) -> TeamMix:
    totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}
    measured: list[int] = []
    missing: list[int] = []
    for champion, position in members:
        profile = profiles.get(champion, position)
        if profile is None:
            missing.append(champion)
            continue
        measured.append(champion)
        totals["physical"] += profile.physical
        totals["magic"] += profile.magic
        totals["true"] += profile.true
    total = sum(totals.values())
    shares = (
        Shares(totals["physical"] / total, totals["magic"] / total, totals["true"] / total)
        if total > 0
        else None
    )
    return TeamMix(shares, measured, missing)


def read_draft(
    profiles: Profiles,
    position: str,
    allies: Sequence[tuple[int, str | None]],
    enemies: Sequence[tuple[int, str | None]],
    picks: Iterable[int],
) -> DraftDamage:
    """Both sides' mixes, and what each pick would make of yours."""
    ally_mix = team_mix(profiles, allies) if allies else None
    enemy_mix = team_mix(profiles, enemies) if enemies else None
    leaning = ally_mix.leaning if ally_mix else None
    read = DraftDamage(available=not profiles.empty, allies=ally_mix, enemies=enemy_mix)
    for champion in picks:
        profile = profiles.get(champion, position)
        if profile is None:
            continue
        own = profile.shares()
        after = team_mix(profiles, [*allies, (champion, position)]).shares if ally_mix and ally_mix.measured else None
        read.picks[champion] = PickDamage(
            own=own,
            games=profile.games,
            team_after=after,
            # Mostly another type: the pick pulls the team back toward even.
            balances=leaning if leaning is not None and own.of(leaning) < 0.5 else None,
        )
    return read


_cache: dict[tuple[str, ...], tuple[float, Profiles]] = {}


def clear_profile_cache() -> None:
    """For tests: the cache outlives a request, and the suite shares one database."""
    _cache.clear()


async def load_profiles(session: AsyncSession, patches: Sequence[str]) -> Profiles:
    """Every champion's damage profile over these patches, by role and overall."""
    key = tuple(sorted(patches))
    held = _cache.get(key)
    now = time.monotonic()
    if held is not None and now - held[0] < PROFILE_TTL_SECONDS:
        return held[1]

    stmt = (
        select(
            MatchParticipant.champion_id,
            MatchParticipant.team_position,
            func.count(),
            func.sum(MatchParticipant.physical_damage_to_champions),
            func.sum(MatchParticipant.magic_damage_to_champions),
            func.sum(MatchParticipant.true_damage_to_champions),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(
            Match.queue_id.in_(PROFILE_QUEUES),
            Match.patch.in_(list(key)),
            Match.is_remake.is_(False),
            # Rows stored before the damage types existed, until the backfill.
            MatchParticipant.physical_damage_to_champions.is_not(None),
        )
        .group_by(MatchParticipant.champion_id, MatchParticipant.team_position)
    )
    profiles = Profiles()
    sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for champion, position, games, physical, magic, true in (await session.execute(stmt)).all():
        games = int(games or 0)
        if games <= 0:
            continue
        physical, magic, true = float(physical or 0), float(magic or 0), float(true or 0)
        if position in POSITIONS:
            profiles.by_role[(champion, position)] = Profile(
                games, physical / games, magic / games, true / games
            )
        # Every game counts toward the overall profile, a game with no lane
        # role too: it is the same champion dealing the same kind of damage.
        total = sums[champion]
        total[0] += games
        total[1] += physical
        total[2] += magic
        total[3] += true
    for champion, (games, physical, magic, true) in sums.items():
        profiles.overall[champion] = Profile(int(games), physical / games, magic / games, true / games)

    _cache[key] = (now, profiles)
    return profiles
