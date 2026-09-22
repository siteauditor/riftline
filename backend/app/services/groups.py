"""Groups: players someone put together, shared by link, and kept filled.

There are no accounts. A group is a random slug anyone can read and an edit key
only its maker holds, and the database keeps a hash of the key, never the key.

Most of this module is **warming**: fetching what a group's players still lack
from Riot, a little at a time, without ever spending the calls a Riot ID search
needs. A new player costs about one call per game of history, so a group of
twenty strangers is thousands of calls: hours on a development key. Warming
therefore happens in short bounded passes, one each time someone opens the
group and a larger one each night, and every pass picks up where the last one
stopped. The table itself (``group_table``) reads storage only.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import string
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    GroupMember,
    HistoryCursor,
    Match,
    MatchParticipant,
    MatchTimeline,
    Player,
    PlayerGroup,
    utcnow,
)
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotRateLimited, RiotUnauthorized
from app.riot.limiter import SEARCH_RESERVE, RateLimiter
from app.riot.routing import resolve_platform
from app.services.matches import MatchService
from app.services.players import PlayerService
from app.services.ranks import is_fresh
from app.services.reviews import review_match
from app.services.timelines import TimelineService
from app.services.winchance import MODEL_QUEUES, current_model

log = logging.getLogger(__name__)

MAX_MEMBERS = 20
NAME_MAX = 60
LABEL_MAX = 24
SLUG_LENGTH = 10
SLUG_ALPHABET = string.ascii_letters + string.digits

# A rank is read again after an hour. The table's default order is official
# rank, and an hour of LP drift does not reorder a group of friends.
RANK_STALE_SECONDS = 3600
# New games are looked for at most every ten minutes per player. The group page
# asks again every few seconds while it loads, and without this every ask would
# spend one list call per player.
CHECK_EVERY_SECONDS = 600
# New games are listed from this long before the last look, because a game in
# progress at that moment is listed by its start time once it ends. Ids already
# held cost nothing, so the overlap is free.
CATCH_UP_MARGIN_S = 3600
# Timelines for each player's newest ranked games: what the death review and the
# lane labels read. Not the whole history, which would nearly double both the
# calls and the storage (a timeline is 74 KB beside an 85 KB match).
TIMELINE_GAMES = 20
# match-v5 lists at most 100 ids a call.
PAGE = 100
# Matches fetched for one player before the next player's turn, so one long
# history cannot starve the rest of the group.
CHUNK = 20
# A group nobody has put anyone in is removed after this long.
EMPTY_GROUP_DAYS = 7


class GroupError(Exception):
    """A request the group cannot take, said in words the page can show."""


class GroupFull(GroupError):
    pass


class AlreadyMember(GroupError):
    pass


class BadRiotId(GroupError):
    pass


# ------------------------------------------------------------------ keys


def new_key() -> str:
    """192 random bits: guessing one is not a thing that happens."""
    return secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    # Plain SHA-256 is enough: the key is random, not a password somebody chose,
    # so there is no dictionary to try against the hash.
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_matches(group: PlayerGroup, offered: str | None) -> bool:
    if not offered:
        return False
    return hmac.compare_digest(group.edit_key_hash, hash_key(offered.strip()))


def new_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def clean_text(value: str | None, limit: int) -> str:
    """Whitespace collapsed and cut to length. Escaping is the page's job."""
    return " ".join((value or "").split())[:limit]


def parse_riot_id(text: str) -> tuple[str, str]:
    """'Name#TAG' into its halves, split on the last '#', as the search box does."""
    cleaned = " ".join((text or "").split())
    name, sep, tag = cleaned.rpartition("#")
    name, tag = name.strip(), tag.strip()
    if not sep or not name or not tag:
        raise BadRiotId(f"Write the Riot ID as Name#TAG, not {cleaned!r}.")
    return name, tag


# --------------------------------------------------------------- groups


async def create_group(session: AsyncSession, name: str) -> tuple[PlayerGroup, str]:
    """A new empty group and its edit key, which is shown to its maker once."""
    key = new_key()
    for _ in range(5):
        group = PlayerGroup(
            slug=new_slug(),
            name=clean_text(name, NAME_MAX) or "Unnamed group",
            edit_key_hash=hash_key(key),
        )
        session.add(group)
        try:
            await session.commit()
            return group, key
        except IntegrityError:
            # A slug collision, about one in 10^17. Try another.
            await session.rollback()
    raise RuntimeError("could not find a free group slug")


async def find_group(session: AsyncSession, slug: str) -> PlayerGroup | None:
    return (
        await session.execute(select(PlayerGroup).where(PlayerGroup.slug == slug))
    ).scalar_one_or_none()


async def members_of(session: AsyncSession, group_id: int) -> list[GroupMember]:
    return list(
        (
            await session.execute(
                select(GroupMember)
                .where(GroupMember.group_id == group_id)
                .order_by(GroupMember.added_at, GroupMember.id)
            )
        ).scalars()
    )


async def rotate_key(session: AsyncSession, group: PlayerGroup) -> str:
    key = new_key()
    group.edit_key_hash = hash_key(key)
    group.updated_at = utcnow()
    await session.commit()
    return key


async def rename_group(session: AsyncSession, group: PlayerGroup, name: str) -> None:
    group.name = clean_text(name, NAME_MAX) or group.name
    group.updated_at = utcnow()
    await session.commit()


async def delete_group(session: AsyncSession, group: PlayerGroup) -> None:
    # Members by hand: SQLite leaves foreign keys unenforced unless every
    # connection turns them on, so the ON DELETE CASCADE is not relied on.
    await session.execute(delete(GroupMember).where(GroupMember.group_id == group.id))
    await session.execute(delete(PlayerGroup).where(PlayerGroup.id == group.id))
    await session.commit()


async def add_member(
    session: AsyncSession,
    players: PlayerService,
    group: PlayerGroup,
    riot_id: str,
    platform: str,
    label: str | None = None,
) -> tuple[GroupMember, Player]:
    """Resolve a Riot ID and add the player. One or two calls for a new player.

    The member is stored against the shard the account plays on, which is not
    always the one asked: an OCE Riot ID resolves through SEA while the account
    lives on SG2, and its rank is only on SG2.
    """
    name, tag = parse_riot_id(riot_id)
    count = (
        await session.execute(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
        )
    ).scalar() or 0
    if count >= MAX_MEMBERS:
        raise GroupFull(f"This group is full: {MAX_MEMBERS} players at most.")

    asked = resolve_platform(platform)
    player = await players.resolve(asked.id, name, tag)
    already = (
        await session.execute(
            select(GroupMember.id).where(
                GroupMember.group_id == group.id, GroupMember.puuid == player.puuid
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise AlreadyMember(f"{player.riot_id} is already in this group.")

    home = await players.effective_platform(player, asked)
    if home.id != asked.id:
        # The level and icon shown in the group belong to the shard played on.
        await players.ensure_summoner(player, home)

    member = GroupMember(
        group_id=group.id,
        puuid=player.puuid,
        platform=home.id,
        label=clean_text(label, LABEL_MAX) or None,
    )
    session.add(member)
    group.updated_at = utcnow()
    try:
        await session.commit()
    except IntegrityError:
        # The same player added twice at once, from two tabs.
        await session.rollback()
        raise AlreadyMember(f"{player.riot_id} is already in this group.") from None
    return member, player


async def find_member(session: AsyncSession, group: PlayerGroup, puuid: str) -> GroupMember | None:
    return (
        await session.execute(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.puuid == puuid)
        )
    ).scalar_one_or_none()


async def remove_member(session: AsyncSession, group: PlayerGroup, member: GroupMember) -> None:
    # The player's stored games and history cursor stay: other groups and the
    # profile page read them, and they cost nothing further to keep.
    await session.delete(member)
    group.updated_at = utcnow()
    await session.commit()


async def set_label(session: AsyncSession, group: PlayerGroup, member: GroupMember, label: str | None) -> None:
    member.label = clean_text(label, LABEL_MAX) or None
    group.updated_at = utcnow()
    await session.commit()


async def delete_empty_groups(session: AsyncSession, *, days: int = EMPTY_GROUP_DAYS) -> int:
    """Remove groups that have had nobody in them for ``days``."""
    cutoff = utcnow() - timedelta(days=days)
    stale = list(
        (
            await session.execute(
                select(PlayerGroup.id)
                .outerjoin(GroupMember, GroupMember.group_id == PlayerGroup.id)
                .where(GroupMember.id.is_(None), PlayerGroup.updated_at < cutoff)
            )
        ).scalars()
    )
    if stale:
        await session.execute(delete(PlayerGroup).where(PlayerGroup.id.in_(stale)))
        await session.commit()
    return len(stale)


# -------------------------------------------------------------- throttle


class AddressThrottle:
    """At most ``setting`` actions an hour per visitor address, in this process.

    One process serves the site (see the Dockerfile), so memory is enough, and a
    restart forgiving everyone is harmless. The limit is read from settings on
    each check so it can be changed without touching this.
    """

    PERIOD = 3600.0

    def __init__(self, setting: str) -> None:
        self.setting = setting
        self.hits: dict[str, deque[float]] = {}

    def check(self, address: str, settings) -> float | None:
        """Record one action. Returns seconds to wait when over the limit."""
        limit = int(getattr(settings, self.setting))
        now = time.monotonic()
        if len(self.hits) > 10_000:
            # Forget addresses with nothing inside the hour, so a crawl of the
            # site from many addresses cannot grow this without bound.
            self.hits = {a: q for a, q in self.hits.items() if q and now - q[-1] < self.PERIOD}
        hits = self.hits.setdefault(address, deque())
        while hits and now - hits[0] >= self.PERIOD:
            hits.popleft()
        if len(hits) >= limit:
            return max(1.0, self.PERIOD - (now - hits[0]))
        hits.append(now)
        return None

    def reset(self) -> None:
        self.hits.clear()


CREATES = AddressThrottle("group_creates_per_hour")
ADDS = AddressThrottle("group_adds_per_hour")


# --------------------------------------------------------------- warming


@dataclass(slots=True)
class Budget:
    """What one warming pass may spend: time, calls, and never the reserve.

    A page view gets a few seconds and stops at the key's reserve, so a group
    can never take the calls a Riot ID search needs. The nightly stage gets a
    number of calls and waits for the key instead of stopping.
    """

    limiter: RateLimiter
    deadline: float | None = None
    calls: int | None = None
    wait: bool = False
    # Why the pass ended early: "time", "calls", "key" (at the reserve or rate
    # limited) or "dead" (Riot refused the key).
    stopped: str | None = None
    spent: int = 0

    async def take(self, want: int) -> int:
        """How many of ``want`` calls may be spent now. Zero means stop."""
        if want <= 0:
            return 0
        while True:
            if self.stopped:
                return 0
            if self.deadline is not None and time.monotonic() >= self.deadline:
                self.stopped = "time"
                return 0
            allowed = want if self.calls is None else min(want, self.calls - self.spent)
            if allowed <= 0:
                self.stopped = "calls"
                return 0
            free = self.limiter.spare() - SEARCH_RESERVE
            if free > 0:
                return min(allowed, free)
            if not self.wait:
                self.stopped = "key"
                return 0
            await asyncio.sleep(max(1.0, self.limiter.seconds_until_free(SEARCH_RESERVE + 1)))

    def spend(self, n: int) -> None:
        self.spent += n


@dataclass(slots=True)
class WarmTarget:
    """One player to warm: who, on which shard."""

    puuid: str
    platform: str


@dataclass(slots=True)
class Warmer:
    """One warming pass over some players. See the module docstring."""

    session: AsyncSession
    client: RiotClient
    settings: object
    budget: Budget
    players: PlayerService = field(init=False)
    matches: MatchService = field(init=False)
    timelines: TimelineService = field(init=False)
    puuids: set[str] = field(default_factory=set)
    fetched: int = 0

    def __post_init__(self) -> None:
        self.players = PlayerService(self.session, self.client, self.settings)
        self.matches = MatchService(self.session, self.client, self.settings)
        self.timelines = TimelineService(self.session, self.client, self.settings)

    @property
    def cap(self) -> int:
        return int(self.settings.group_history_cap)

    async def run(self, targets: Sequence[WarmTarget]) -> None:
        """Ranks first (the table's default order), then new games, then one
        round of history, then timelines, then the rest of the history."""
        if not targets:
            return
        await self._create_cursors(targets)
        try:
            for target in targets:
                if not await self._guard(self._rank(target)):
                    return
            for target in targets:
                if not await self._guard(self._new_games(target)):
                    return
            await self._history(targets, rounds=1)
            for target in targets:
                if not await self._guard(self._newest_timelines(target)):
                    return
            await self._history(targets, rounds=None)
        finally:
            log.info(
                "groups: warmed %d players, %d calls, %d games fetched, stopped: %s",
                len(targets), self.budget.spent, self.fetched, self.budget.stopped or "done",
            )

    async def _guard(self, step) -> bool:
        """Run a step, turning Riot's refusals into a reason to stop."""
        try:
            await step
        except RiotRateLimited:
            await self.session.rollback()
            self.budget.stopped = "key"
        except RiotUnauthorized:
            await self.session.rollback()
            self.budget.stopped = "dead"
        except RiotApiError as exc:
            # One player's failure is not the group's: skip to the next.
            await self.session.rollback()
            log.warning("groups: a warming step failed: %s", exc)
        return self.budget.stopped is None

    async def _cursor(self, puuid: str) -> HistoryCursor:
        """The player's cursor, read again if a rollback expired it.

        Read through ``session.get`` every time rather than held: the services
        this calls roll back on a write race, which expires every loaded row,
        and touching an expired row under asyncio fails far from the cause.
        """
        cursor = await self.session.get(HistoryCursor, puuid)
        assert cursor is not None, "made by _create_cursors"
        return cursor

    async def _create_cursors(self, targets: Sequence[WarmTarget]) -> None:
        self.puuids = {t.puuid for t in targets}
        have = set(
            (
                await self.session.execute(
                    select(HistoryCursor.puuid).where(HistoryCursor.puuid.in_(list(self.puuids)))
                )
            ).scalars()
        )
        now_s = int(time.time())
        for puuid in self.puuids - have:
            # History is read from this moment back, new games from here on.
            self.session.add(HistoryCursor(
                puuid=puuid, until_s=now_s, offset=0, exhausted=False,
                since_s=now_s - CATCH_UP_MARGIN_S,
            ))
        try:
            await self.session.commit()
        except IntegrityError:
            # The nightly stage made some of them first; theirs will do.
            await self.session.rollback()

    async def _rank(self, target: WarmTarget) -> None:
        player = await self.session.get(Player, target.puuid)
        if player is None:
            return
        if player.league_platform == target.platform and is_fresh(
            player.league_fetched_at, RANK_STALE_SECONDS
        ):
            return
        if not await self.budget.take(1):
            return
        self.budget.spend(1)
        await self.players.ranks(player, target.platform)

    async def _new_games(self, target: WarmTarget) -> None:
        cursor = await self._cursor(target.puuid)
        if is_fresh(cursor.checked_at, CHECK_EVERY_SECONDS):
            return
        if not await self.budget.take(1):
            return
        now_s = int(time.time())
        regional = resolve_platform(target.platform).regional
        self.budget.spend(1)
        ids = await self.client.match_ids(
            target.puuid, regional, start=0, count=PAGE, start_time=cursor.since_s
        )
        known = await self.matches.known_ids(ids)
        missing = [i for i in ids if i not in known]
        allowed = await self.budget.take(len(missing)) if missing else 0
        await self._fetch(missing[:allowed], regional)
        if len(missing) > allowed:
            # Cut short: listed again next time, from the same point.
            return
        cursor = await self._cursor(target.puuid)
        cursor.since_s = now_s - CATCH_UP_MARGIN_S
        cursor.checked_at = utcnow()
        await self.session.commit()

    async def _history(self, targets: Sequence[WarmTarget], *, rounds: int | None) -> None:
        """Older games, one chunk per player per round, until the cap or the end."""
        active = [t for t in targets if not await self._history_done(t.puuid)]
        done_rounds = 0
        while active and (rounds is None or done_rounds < rounds):
            still = []
            for target in active:
                if not await self._guard(self._history_step(target)):
                    return
                if not await self._history_done(target.puuid):
                    still.append(target)
            active = still
            done_rounds += 1

    async def _history_done(self, puuid: str) -> bool:
        cursor = await self._cursor(puuid)
        return cursor.exhausted or cursor.offset >= self.cap

    async def _history_step(self, target: WarmTarget) -> None:
        cursor = await self._cursor(target.puuid)
        want = min(PAGE, self.cap - cursor.offset)
        if want <= 0 or not await self.budget.take(1):
            return
        regional = resolve_platform(target.platform).regional
        self.budget.spend(1)
        ids = await self.client.match_ids(
            target.puuid, regional, start=cursor.offset, count=want, end_time=cursor.until_s
        )
        if not ids:
            cursor.exhausted = True
            await self.session.commit()
            return
        known = await self.matches.known_ids(ids)
        missing_total = sum(1 for i in ids if i not in known)
        allowed = await self.budget.take(min(CHUNK, missing_total)) if missing_total else 0
        # The ids taken this step: every one up to the last missing one this
        # step may fetch. Held ones cost nothing and are passed over.
        taken, fetch = 0, []
        for match_id in ids:
            if match_id not in known:
                if len(fetch) == allowed:
                    break
                fetch.append(match_id)
            taken += 1
        # A game Riot fails to return is passed over rather than retried
        # forever: one hole in 300 games beats a cursor stuck behind it.
        await self._fetch(fetch, regional)
        cursor = await self._cursor(target.puuid)
        cursor.offset += taken
        if taken == len(ids) and len(ids) < want:
            cursor.exhausted = True
        await self.session.commit()

    async def _fetch(self, match_ids: list[str], regional) -> None:
        if not match_ids:
            return
        self.budget.spend(len(match_ids))
        stored = await self.matches.ensure_matches(match_ids, regional)
        self.fetched += len(stored)
        # New games may be among the newest ranked ones, whose timelines the
        # next pass then fetches.
        for puuid in {p.puuid for m in stored for p in m.participants} & self.puuids:
            (await self._cursor(puuid)).timelines_at = None
        await self.session.commit()

    async def _newest_timelines(self, target: WarmTarget) -> None:
        cursor = await self._cursor(target.puuid)
        if is_fresh(cursor.timelines_at, CHECK_EVERY_SECONDS):
            return
        newest = (
            select(Match.match_id)
            .join(MatchParticipant, MatchParticipant.match_id == Match.match_id)
            .where(
                MatchParticipant.puuid == target.puuid,
                Match.queue_id.in_(MODEL_QUEUES),
                Match.is_remake.is_(False),
            )
            .order_by(Match.game_creation.desc())
            .limit(TIMELINE_GAMES)
            .subquery()
        )
        lacking = list(
            (
                await self.session.execute(
                    select(Match)
                    .join(newest, newest.c.match_id == Match.match_id)
                    .outerjoin(MatchTimeline, MatchTimeline.match_id == Match.match_id)
                    .where(MatchTimeline.match_id.is_(None))
                    .order_by(Match.game_creation.desc())
                )
            ).scalars()
        )
        allowed = await self.budget.take(len(lacking)) if lacking else 0
        if lacking and allowed:
            batch = lacking[:allowed]
            # Read before the fetch, which rolls back on a write race and so
            # expires these rows.
            batch_ids = [m.match_id for m in batch]
            self.budget.spend(len(batch))
            await self.timelines.ensure_timelines(batch)
            await self._review(batch_ids)
        if len(lacking) > allowed:
            return
        cursor = await self._cursor(target.puuid)
        cursor.timelines_at = utcnow()
        await self.session.commit()

    async def _review(self, match_ids: list[str]) -> None:
        """Weigh the new timelines' deaths now, rather than at the nightly run."""
        model = await current_model(self.session)
        if model is None or not model.published:
            return
        matches = (
            await self.session.execute(
                select(Match)
                .where(Match.match_id.in_(match_ids))
                .options(selectinload(Match.participants))
            )
        ).scalars().all()
        for match in matches:
            await review_match(self.session, match, model)
        try:
            await self.session.commit()
        except IntegrityError:
            # The nightly stage or a story view wrote these first: same numbers.
            await self.session.rollback()


async def warm_group(
    session: AsyncSession,
    client: RiotClient,
    settings,
    members: Sequence[GroupMember],
    budget: Budget,
) -> int:
    """One bounded pass over a group's players. Returns the games fetched."""
    warmer = Warmer(session, client, settings, budget)
    await warmer.run([WarmTarget(m.puuid, m.platform) for m in members])
    return warmer.fetched


async def warm_all_groups(
    session: AsyncSession, client: RiotClient, settings, *, calls: int
) -> tuple[int, Budget]:
    """The nightly pass: every group's players, most recently viewed first."""
    rows = (
        await session.execute(
            select(GroupMember.puuid, GroupMember.platform)
            .join(PlayerGroup, PlayerGroup.id == GroupMember.group_id)
            .order_by(
                PlayerGroup.viewed_at.is_(None),
                PlayerGroup.viewed_at.desc(),
                GroupMember.added_at,
            )
        )
    ).all()
    seen: set[str] = set()
    targets = []
    for puuid, platform in rows:
        if puuid not in seen:
            seen.add(puuid)
            targets.append(WarmTarget(puuid, platform))
    budget = Budget(client.limiter, calls=calls, wait=True)
    await Warmer(session, client, settings, budget).run(targets)
    return len(targets), budget


__all__ = [
    "ADDS",
    "CREATES",
    "MAX_MEMBERS",
    "AlreadyMember",
    "BadRiotId",
    "Budget",
    "GroupError",
    "GroupFull",
    "add_member",
    "create_group",
    "delete_empty_groups",
    "delete_group",
    "find_group",
    "find_member",
    "key_matches",
    "members_of",
    "remove_member",
    "rename_group",
    "rotate_key",
    "set_label",
    "warm_all_groups",
    "warm_group",
]
