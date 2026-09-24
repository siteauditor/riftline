"""Which shard is a player's home, and what may be stored for it.

A Riot ID resolves across a whole region, but summoner-v4, league-v4,
champion-mastery-v4 and spectator-v5 answer per shard, and an account can hold
a record on more than one. On 2026-09-24 one view of
``/summoner/na1/Dekap/EUW`` (a EUW Challenger with a level 30 NA record) moved
the player's row to na1, deleted the EUW rank, made the stored profile a 404
and moved the prerendered page to the NA path, because every per-shard cache
was rewritten for whichever shard a URL named.

The rule since then:

* ``Player.platform`` is the home shard, as account-v1's active-region lookup
  names it. It changes only when Riot says so (``move_home``), or when the
  ``homes`` repair corrects a guess from stored games.
* Only the home shard's summoner record, ranks and mastery are stored.
* A request for another shard is a ``ShardView``: ``second`` when the account
  holds a rank or stored games there, read live and stored nowhere; ``absent``
  when it holds neither, answered with the home shard's data so the page can
  move to it. Match payloads, timelines and scores are global and are stored
  whatever shard asked for them.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChampionMastery,
    GroupMember,
    Match,
    MatchParticipant,
    Player,
    RankedEntry,
    RankHistory,
)
from app.riot.routing import Platform, UnknownPlatform, platform_ids_for, resolve_platform

log = logging.getLogger(__name__)

Role = Literal["home", "second", "absent"]


@dataclass(frozen=True, slots=True)
class ShardView:
    """What a request that names ``asked`` shows for this player.

    ``home``: the account plays on the asked shard; read and store there.
    ``second``: it plays elsewhere but holds a rank or stored games on the
    asked shard; read that shard live and store nothing. ``absent``: nothing of
    theirs is on the asked shard; answer with the home shard's data and say
    where they play.
    """

    asked: Platform
    home: Platform
    role: Role
    # The asked shard's league answer, when deciding the view read it, so the
    # profile does not ask Riot the same question twice. Only for "second".
    league: tuple[dict, ...] | None = None

    @property
    def shown(self) -> Platform:
        """The shard whose data the answer carries."""
        return self.asked if self.role == "second" else self.home

    @property
    def platform_ids(self) -> frozenset[str] | None:
        """The match platform ids a stored list is limited to; None for all.

        A second shard's view shows its own games only. The home view shows
        every stored game, as it always has: games from before a transfer are
        still the player's.
        """
        return platform_ids_for(self.asked) if self.role == "second" else None


def canonical(value: str | None) -> str | None:
    """A platform id in its canonical spelling (th2 is sg2), or None."""
    if not value:
        return None
    try:
        return resolve_platform(value).id
    except UnknownPlatform:
        return None


@dataclass(frozen=True, slots=True)
class Address:
    """Where a stored player's profile lives: their home, and the Riot ID
    account-v1 last confirmed for them (None while nobody has asked)."""

    platform: str
    game_name: str | None
    tag_line: str | None


async def addresses(session: AsyncSession, puuids: Collection[str]) -> dict[str, Address]:
    """The profile address of every stored player among ``puuids``.

    A link built from a stored game names the shard the game was played on
    (PH2 for a game from before Riot merged it into SG2, the other region for
    a player on a bootcamp) and the name the player had in it. Their page is
    under their home and their confirmed Riot ID (`seo.profile_pages`), so a
    link built that way went to an address the page then had to move from.
    A name read from a game is not confirmed, and is left to the caller's
    game, which may be newer.
    """
    if not puuids:
        return {}
    rows = (
        await session.execute(
            select(
                Player.puuid, Player.platform, Player.game_name, Player.tag_line,
                Player.search_name,
            ).where(Player.puuid.in_(list(set(puuids))))
        )
    ).all()
    out: dict[str, Address] = {}
    for row in rows:
        home = canonical(row.platform)
        if home is None:
            continue
        confirmed = bool(row.search_name and row.game_name and row.tag_line)
        out[row.puuid] = Address(
            platform=home,
            game_name=row.game_name if confirmed else None,
            tag_line=row.tag_line if confirmed else None,
        )
    return out


async def restore_ranks(session: AsyncSession, player: Player, home_id: str) -> int:
    """Rebuild ``ranked_entries`` from the newest home reading of each queue.

    ``rank_history`` is never deleted, so a rank that a read of the wrong shard
    removed is still there, and ``league_fetched_at`` is set to the reading's
    own time: the page says how old it is, and the next live view reads it
    fresh. Returns the queues restored. Does not commit.
    """
    rows = (
        await session.execute(
            select(RankHistory)
            .where(RankHistory.puuid == player.puuid, RankHistory.platform == home_id)
            .order_by(RankHistory.taken_at.desc(), RankHistory.id.desc())
        )
    ).scalars()
    newest: dict[str, RankHistory] = {}
    for reading in rows:
        newest.setdefault(reading.queue_type, reading)
    for reading in newest.values():
        session.add(
            RankedEntry(
                puuid=player.puuid,
                queue_type=reading.queue_type,
                tier=reading.tier,
                division=reading.division,
                league_points=reading.league_points,
                wins=reading.wins,
                losses=reading.losses,
            )
        )
    if newest:
        player.league_platform = home_id
        player.league_fetched_at = max(r.taken_at for r in newest.values())
    return len(newest)


async def drop_league(session: AsyncSession, player: Player) -> None:
    # A statement, not `session.delete`: the unit of work flushes inserts
    # before deletes, so a restored entry for the same queue would collide
    # with the row it replaces on the (puuid, queue_type) key.
    await session.execute(delete(RankedEntry).where(RankedEntry.puuid == player.puuid))
    player.league_platform = None
    player.league_fetched_at = None


def drop_summoner(player: Player) -> None:
    player.summoner_level = None
    player.profile_icon_id = None
    player.revision_date = None
    player.summoner_platform = None
    player.summoner_fetched_at = None


async def drop_mastery(session: AsyncSession, player: Player) -> None:
    await session.execute(delete(ChampionMastery).where(ChampionMastery.puuid == player.puuid))
    player.mastery_platform = None
    player.mastery_fetched_at = None


async def move_home(session: AsyncSession, player: Player, new_home: Platform | str) -> None:
    """Make ``new_home`` this player's home shard. Does not commit.

    Every per-shard cache not read on the new home is dropped, because it
    describes another shard; the rank is rebuilt from the newest reading taken
    there, if any. Group members follow the player. ``rank_history`` is never
    touched: each reading names its own shard.
    """
    home_id = resolve_platform(new_home).id
    if player.league_platform != home_id:
        await drop_league(session, player)
        await restore_ranks(session, player, home_id)
    if player.summoner_platform != home_id:
        drop_summoner(player)
    if player.mastery_platform != home_id:
        await drop_mastery(session, player)
    await session.execute(
        update(GroupMember)
        .where(GroupMember.puuid == player.puuid, GroupMember.platform != home_id)
        .values(platform=home_id)
    )
    player.platform = home_id


# ----------------------------------------------------------------- repair

# Players loaded and committed at once. Small enough that a batch is a short
# write, so the API is never blocked behind the repair for long.
REPAIR_BATCH = 200

CacheAction = Literal["keep", "adopt", "drop"]


@dataclass(slots=True)
class _Plan:
    home: str
    move: bool = False
    stub: bool = False
    alias: bool = False
    recheck: bool = False
    league: CacheAction = "keep"
    summoner: CacheAction = "keep"
    mastery: CacheAction = "keep"
    retire: bool = False

    def changes(self) -> bool:
        return (
            self.move
            or self.alias
            or self.recheck
            or self.retire
            or "adopt" in (self.league, self.summoner, self.mastery)
            or "drop" in (self.league, self.summoner, self.mastery)
        )


@dataclass(slots=True)
class RepairReport:
    """What the repair changed, or would change on a dry run."""

    players: int = 0
    stubs_moved: int = 0
    searched_moved: int = 0
    rechecks: int = 0
    aliases: int = 0
    ranks_adopted: int = 0
    ranks_dropped: int = 0
    ranks_restored: int = 0
    summoners_adopted: int = 0
    summoners_dropped: int = 0
    masteries_adopted: int = 0
    masteries_dropped: int = 0
    claims_retired: int = 0
    members_synced: int = 0
    examples: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"players read:           {self.players}",
            f"stubs moved:            {self.stubs_moved}",
            f"searched rows moved:    {self.searched_moved}",
            f"home to confirm:        {self.rechecks}",
            f"alias ids made canonical: {self.aliases}",
            f"ranks adopted:          {self.ranks_adopted}",
            f"ranks dropped:          {self.ranks_dropped}",
            f"ranks restored:         {self.ranks_restored}",
            f"summoners adopted:      {self.summoners_adopted}",
            f"summoners dropped:      {self.summoners_dropped}",
            f"masteries adopted:      {self.masteries_adopted}",
            f"masteries dropped:      {self.masteries_dropped}",
            f"duplicate claims retired: {self.claims_retired}",
            f"group members synced:   {self.members_synced}",
        ]


def _cache_action(stamp: str | None, has_data: bool, home: str) -> CacheAction:
    """What to do with one per-shard cache, given the home it should describe.

    A cache with no stamp predates the stamps (2026-09-17). It was read on the
    shard the row named then, which is the home unless the row moves, so it is
    adopted rather than thrown away: 2,885 local players held a rank like that.
    """
    if stamp is None:
        return "adopt" if has_data else "keep"
    if canonical(stamp) != home:
        return "drop"
    # Read on the home under an alias spelling (th2 for sg2): restamped.
    return "keep" if stamp == home else "adopt"


async def _games_by_shard(
    session: AsyncSession, puuids: Collection[str] | None
) -> dict[str, dict[str, int]]:
    """Each player's newest stored game per shard, in canonical ids."""
    stmt = (
        select(
            MatchParticipant.puuid,
            Match.platform_id,
            func.max(Match.game_creation),
        )
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(Match.is_remake.is_(False))
        .group_by(MatchParticipant.puuid, Match.platform_id)
    )
    if puuids is not None:
        stmt = stmt.where(MatchParticipant.puuid.in_(list(puuids)))
    rows = (await session.execute(stmt)).all()
    out: dict[str, dict[str, int]] = {}
    for puuid, platform_id, newest in rows:
        shard = canonical((platform_id or "").lower())
        if shard is None or not puuid:
            continue
        mine = out.setdefault(puuid, {})
        mine[shard] = max(mine.get(shard, 0), int(newest or 0))
    return out


async def repair_homes(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    batch: int = REPAIR_BATCH,
    puuids: Collection[str] | None = None,
) -> RepairReport:
    """Put every player row back on its home shard, from storage only.

    It may move a stub (a row nobody searched) to the shard of its newest
    stored game; move a searched row only when its shard holds none of its
    games and another does; ask for the home to be confirmed (by clearing
    ``account_fetched_at``, so the next view or the names stage asks Riot) when
    the newest game is elsewhere; drop caches read on another shard and
    rebuild the rank from the newest home reading; adopt caches from before
    the shard stamps; retire all but the newest claim of one Riot ID; make
    alias ids canonical; and move group members with their player.

    It may not call Riot, delete a player, or touch rank history, matches or
    scores. Running it twice changes nothing the second time. ``puuids``
    limits it to those players, claims and group members included.
    """
    report = RepairReport()
    scope = list(puuids) if puuids is not None else None
    rows = (
        await session.execute(
            select(
                Player.puuid,
                Player.platform,
                Player.search_name,
                Player.tag_line,
                Player.game_name,
                Player.account_fetched_at,
                Player.league_platform,
                Player.summoner_platform,
                Player.mastery_platform,
                Player.summoner_level,
                Player.profile_icon_id,
            ).where(Player.puuid.in_(scope) if scope is not None else True)
        )
    ).all()
    report.players = len(rows)
    games = await _games_by_shard(session, scope)

    def scoped(column):
        return column.in_(scope) if scope is not None else True

    with_entries = set(
        (
            await session.execute(
                select(RankedEntry.puuid).where(scoped(RankedEntry.puuid)).distinct()
            )
        ).scalars()
    )
    with_masteries = set(
        (
            await session.execute(
                select(ChampionMastery.puuid).where(scoped(ChampionMastery.puuid)).distinct()
            )
        ).scalars()
    )
    history = {
        (puuid, platform)
        for puuid, platform in (
            await session.execute(
                select(RankHistory.puuid, RankHistory.platform)
                .where(scoped(RankHistory.puuid))
                .distinct()
            )
        ).all()
    }

    # The newest confirmed claim of each folded Riot ID keeps it.
    claims: dict[tuple[str, str], list] = {}
    for row in rows:
        if row.search_name and row.tag_line:
            claims.setdefault((row.search_name, row.tag_line.lower()), []).append(row)
    retired: set[str] = set()
    for holders in claims.values():
        if len(holders) > 1:
            holders.sort(key=lambda r: _stamp_key(r.account_fetched_at), reverse=True)
            retired.update(r.puuid for r in holders[1:])

    plans: dict[str, _Plan] = {}
    for row in rows:
        current = canonical(row.platform)
        if current is None:
            continue
        plan = _Plan(home=current, alias=current != row.platform, stub=row.search_name is None)
        shards = games.get(row.puuid, {})
        newest = max(shards, key=shards.__getitem__) if shards else None
        if newest is not None and newest != current:
            if plan.stub:
                plan.home, plan.move = newest, True
            elif current not in shards:
                plan.home, plan.move, plan.recheck = newest, True, True
            else:
                plan.recheck = True
        if plan.recheck and row.account_fetched_at is None:
            plan.recheck = False
        plan.retire = row.puuid in retired
        if not plan.move:
            plan.league = _cache_action(row.league_platform, row.puuid in with_entries, plan.home)
            plan.summoner = _cache_action(
                row.summoner_platform,
                row.summoner_level is not None or row.profile_icon_id is not None,
                plan.home,
            )
            plan.mastery = _cache_action(row.mastery_platform, row.puuid in with_masteries, plan.home)
        if not plan.changes():
            continue
        plans[row.puuid] = plan
        _count(
            report, plan, row, history,
            held=(
                row.puuid in with_entries,
                row.summoner_level is not None or row.profile_icon_id is not None,
                row.puuid in with_masteries,
            ),
        )

    report.members_synced = await _members_to_sync(session, plans, scope)
    if dry_run:
        return report

    todo = sorted(plans)
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        loaded = {
            p.puuid: p
            for p in (
                await session.execute(select(Player).where(Player.puuid.in_(chunk)))
            ).scalars()
        }
        for puuid in chunk:
            player = loaded.get(puuid)
            if player is not None:
                await _apply(session, player, plans[puuid])
        await session.commit()

    # Members of players the plans did not touch can still disagree (a member
    # added before the rule), so this is one statement over the whole table.
    await session.execute(
        update(GroupMember)
        .where(
            scoped(GroupMember.puuid),
            GroupMember.platform
            != select(Player.platform).where(Player.puuid == GroupMember.puuid).scalar_subquery(),
        )
        .values(
            platform=select(Player.platform)
            .where(Player.puuid == GroupMember.puuid)
            .scalar_subquery()
        )
    )
    await session.commit()
    return report


def _stamp_key(stamp: datetime | None) -> float:
    return stamp.timestamp() if stamp is not None else float("-inf")


def _count(
    report: RepairReport, plan: _Plan, row, history: set, *, held: tuple[bool, bool, bool]
) -> None:
    """Tally one plan. ``held`` says whether a rank, a summoner record and a
    mastery table are stored, so a drop is counted only where there was data
    or a stamp to drop."""
    has_rank, has_summoner, has_mastery = held
    if plan.move:
        if plan.stub:
            report.stubs_moved += 1
        else:
            report.searched_moved += 1
        if len(report.examples) < 10:
            name = f"{row.game_name}#{row.tag_line}" if row.game_name else row.puuid[:12]
            report.examples.append(f"{name}: {row.platform} -> {plan.home}")
    report.rechecks += plan.recheck
    report.aliases += plan.alias
    report.claims_retired += plan.retire
    def dropped(action: CacheAction, stamp: str | None, has: bool) -> bool:
        if plan.move:
            return canonical(stamp) != plan.home and (has or stamp is not None)
        return action == "drop"

    if dropped(plan.league, row.league_platform, has_rank):
        report.ranks_dropped += 1
        report.ranks_restored += (row.puuid, plan.home) in history
    report.ranks_adopted += plan.league == "adopt"
    report.summoners_adopted += plan.summoner == "adopt"
    report.summoners_dropped += dropped(plan.summoner, row.summoner_platform, has_summoner)
    report.masteries_adopted += plan.mastery == "adopt"
    report.masteries_dropped += dropped(plan.mastery, row.mastery_platform, has_mastery)


async def _members_to_sync(
    session: AsyncSession, plans: dict[str, _Plan], scope: list[str] | None
) -> int:
    stmt = select(GroupMember.puuid, GroupMember.platform, Player.platform).join(
        Player, Player.puuid == GroupMember.puuid
    )
    if scope is not None:
        stmt = stmt.where(GroupMember.puuid.in_(scope))
    rows = (await session.execute(stmt)).all()
    count = 0
    for puuid, member_platform, player_platform in rows:
        target = plans[puuid].home if puuid in plans else canonical(player_platform)
        count += member_platform != target
    return count


async def _apply(session: AsyncSession, player: Player, plan: _Plan) -> None:
    if plan.retire:
        player.search_name = None
    if plan.recheck:
        player.account_fetched_at = None
    if plan.move:
        # Stamps in an alias spelling are made canonical first, so a cache
        # read on the new home under its old name is kept.
        for attr in ("league_platform", "summoner_platform", "mastery_platform"):
            setattr(player, attr, canonical(getattr(player, attr)))
        await move_home(session, player, plan.home)
        log.info("moved %s to %s", player.puuid[:12], plan.home)
        return
    player.platform = plan.home
    if plan.league == "drop":
        await drop_league(session, player)
        await restore_ranks(session, player, plan.home)
    elif plan.league == "adopt":
        player.league_platform = plan.home
    if plan.summoner == "drop":
        drop_summoner(player)
    elif plan.summoner == "adopt":
        player.summoner_platform = plan.home
    if plan.mastery == "drop":
        await drop_mastery(session, player)
    elif plan.mastery == "adopt":
        player.mastery_platform = plan.home


__all__ = [
    "REPAIR_BATCH",
    "Address",
    "RepairReport",
    "Role",
    "ShardView",
    "addresses",
    "canonical",
    "drop_league",
    "drop_mastery",
    "drop_summoner",
    "move_home",
    "repair_homes",
    "restore_ranks",
]
