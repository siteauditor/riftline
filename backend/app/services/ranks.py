"""Ranks for PUUIDs we were not looking up.

``PlayerService.ranks`` answers "what rank is the player on this page", and it
needs a hydrated ``Player`` built from a Riot ID to do it. A live lobby hands us
nine bare PUUIDs at once, most of which we have never seen and none of which we
have a Riot ID for. That is a different primitive, so it lives here.

Three things make the batch affordable, and they are the whole reason the
historical backfill is an hour rather than a week:

* **Ranks are cached per player, not per lookup.** A player appears in 6.0
  matches on average across the current corpus, so the second match that
  contains them is free.
* **Stub player rows cost nothing.** ``ranked_entries.puuid`` is a foreign key
  to ``players.puuid``, so a rank row needs a player row. Creating one from a
  PUUID alone takes no Riot call at all.
* **Names come from matches we already stored.** ``match-v5`` carries
  ``riotIdGameName`` for every participant, so any player in the corpus is
  already named, for free, forever.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant, Player, RankedEntry, utcnow
from app.riot.client import RiotClient
from app.riot.routing import Platform, resolve_platform

log = logging.getLogger(__name__)

# In flight at once. The app-scope window is the binding constraint anyway, so
# this bounds memory and keeps one lobby from monopolising the limiter.
RANK_CONCURRENCY = 4

# How many times to retry creating stub player rows when a concurrent
# request wins the race. Two is enough for any realistic interleaving;
# the bound is there so a genuine constraint problem cannot spin.
_STUB_INSERT_ATTEMPTS = 3


def is_fresh(stamp: datetime | None, ttl_seconds: int) -> bool:
    """Is a cache stamp still inside its TTL?

    Lives here rather than in ``players`` because both modules need it and this
    is the lower-level one, so the import only ever points one way.
    """
    if stamp is None:
        return False
    if stamp.tzinfo is None:  # SQLite hands back naive datetimes
        stamp = stamp.replace(tzinfo=UTC)
    return datetime.now(UTC) - stamp < timedelta(seconds=ttl_seconds)


@dataclass(slots=True)
class RankSnapshot:
    """What we know about one player's ranks right now.

    ``known=False`` is not the same as unranked. It means we never got an answer
    this round -- the fetch failed, or the caller's time budget ran out -- and
    the caller must say "unknown" rather than "unranked". Conflating the two
    turns a timeout into a false claim about somebody's rank.
    """

    puuid: str
    entries: list[RankedEntry] = field(default_factory=list)
    known: bool = True


async def apply_league_entries(
    session: AsyncSession,
    puuid: str,
    raw_entries: Iterable[dict] | None,
    existing: Sequence[RankedEntry],
) -> None:
    """Fold a league-v4 response into ``ranked_entries``. Does not commit.

    Shared with :meth:`PlayerService.ranks` so the two paths cannot drift on
    something as easy to get subtly wrong as which queues to delete.
    """
    by_queue = {e.queue_type: e for e in existing}
    seen: set[str] = set()

    for raw in raw_entries or []:
        queue = raw.get("queueType") or "UNKNOWN"
        seen.add(queue)
        entry = by_queue.get(queue) or RankedEntry(puuid=puuid, queue_type=queue)
        entry.tier = raw.get("tier")
        entry.division = raw.get("rank")
        entry.league_points = raw.get("leaguePoints") or 0
        entry.wins = raw.get("wins") or 0
        entry.losses = raw.get("losses") or 0
        entry.hot_streak = bool(raw.get("hotStreak"))
        entry.veteran = bool(raw.get("veteran"))
        entry.fresh_blood = bool(raw.get("freshBlood"))
        entry.inactive = bool(raw.get("inactive"))
        if queue not in by_queue:
            session.add(entry)

    # A queue that vanished means a demotion or a season reset. Dropping the row
    # beats showing a rank the player no longer holds.
    for queue, entry in by_queue.items():
        if queue not in seen:
            await session.delete(entry)


class RankCache:
    """Batch rank lookups for arbitrary PUUIDs, served from cache where possible."""

    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    # ------------------------------------------------------------- players

    async def ensure_players(
        self, puuids: Sequence[str], platform: Platform | str
    ) -> dict[str, Player]:
        """Make sure every PUUID has a ``players`` row, creating stubs as needed.

        A stub carries no ``search_name``, and ``PlayerService._find_cached``
        matches on ``search_name``, so a stub can never be returned by a Riot ID
        lookup. If that player is searched for later, ``_upsert_from_account``
        fills this same row in. Do not "clean these up": they are the cache.
        """
        wanted = [p for p in dict.fromkeys(puuids) if p]
        if not wanted:
            return {}

        platform_id = resolve_platform(platform).id
        rows = (
            await self.session.execute(select(Player).where(Player.puuid.in_(wanted)))
        ).scalars()
        known = {p.puuid: p for p in rows}

        # Any name match-v5 already gave us is free; use the most recent one,
        # because riot_id_game_name is the name as of *that* match and people
        # rename.
        names = await self.names_from_matches(
            [p for p in wanted if p not in known]
        )

        # Retried, not just re-read.
        #
        # A rollback discards *every* insert in the transaction, not only the
        # one that collided. Re-reading alone therefore recovered whatever the
        # racing request happened to have created and silently dropped the
        # rest, and `get_many` then raised KeyError on the first one missing --
        # a 500 on the live-game endpoint under exactly the concurrency a
        # polling live view creates. Verified: nine stubs, one collision, one
        # row surviving.
        for _ in range(_STUB_INSERT_ATTEMPTS):
            missing = [p for p in wanted if p not in known]
            if not missing:
                break
            for puuid in missing:
                name, tag = names.get(puuid, (None, None))
                known[puuid] = Player(
                    puuid=puuid, platform=platform_id, game_name=name, tag_line=tag
                )
                self.session.add(known[puuid])
            try:
                # Committed, not flushed. A flush opens a write transaction that
                # would then stay open across the Riot calls in `get_many` -- on
                # SQLite that is a minutes-long exclusive lock on the whole
                # database, which blocks the API while a backfill runs. These
                # rows are independently useful, so there is nothing to hold
                # them for.
                await self.session.commit()
                break
            except IntegrityError:
                await self.session.rollback()
                rows = (
                    await self.session.execute(
                        select(Player).where(Player.puuid.in_(wanted))
                    )
                ).scalars()
                known = {p.puuid: p for p in rows}
        else:
            log.warning(
                "could not create player rows for %d puuid(s) after %d attempts",
                len([p for p in wanted if p not in known]),
                _STUB_INSERT_ATTEMPTS,
            )
        return known

    async def names_from_matches(
        self, puuids: Sequence[str]
    ) -> dict[str, tuple[str | None, str | None]]:
        """Most recent Riot ID seen for each PUUID in our stored matches.

        Ordered by ``game_creation`` on purpose. ``riot_id_game_name`` is the
        name the player had *in that match*, so the arbitrary row a plain
        ``WHERE puuid IN (...)`` returns can easily be a name they abandoned
        years ago.
        """
        wanted = [p for p in dict.fromkeys(puuids) if p]
        if not wanted:
            return {}
        stmt = (
            select(
                MatchParticipant.puuid,
                MatchParticipant.riot_id_game_name,
                MatchParticipant.riot_id_tagline,
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.puuid.in_(wanted),
                MatchParticipant.riot_id_game_name.isnot(None),
            )
            .order_by(Match.game_creation.desc())
        )
        out: dict[str, tuple[str | None, str | None]] = {}
        for puuid, name, tag in (await self.session.execute(stmt)).all():
            out.setdefault(puuid, (name, tag))
        return out

    # --------------------------------------------------------------- ranks

    async def get_many(
        self,
        puuids: Sequence[str],
        platform: Platform | str,
        *,
        ttl: int | None = None,
        budget_seconds: float | None = None,
        refresh: bool = False,
    ) -> dict[str, RankSnapshot]:
        """Ranks for every PUUID, fetching only the ones we do not hold fresh.

        ``budget_seconds`` bounds the whole fetch. Running out is not an error:
        whatever landed is written, so the next call starts warmer and finishes
        the job. A live-game view would rather render in two seconds with seven
        of nine ranks than block for twelve.
        """
        wanted = [p for p in dict.fromkeys(puuids) if p]
        if not wanted:
            return {}
        ttl = self.settings.ttl_league if ttl is None else ttl
        resolved = resolve_platform(platform)

        players = await self.ensure_players(wanted, resolved)
        cached = (
            await self.session.execute(
                select(RankedEntry).where(RankedEntry.puuid.in_(wanted))
            )
        ).scalars()
        by_puuid: dict[str, list[RankedEntry]] = {p: [] for p in wanted}
        for entry in cached:
            by_puuid[entry.puuid].append(entry)

        # `.get`, not `[...]`: if a row could not be created after retries we
        # still owe the caller an answer for that puuid, as `known=False`.
        # A cached rank belongs to a shard, so a row filled from another one is
        # stale here however recent it is. Two shards can hold the same puuid.
        stale = [
            p
            for p in wanted
            if p in players
            and (
                refresh
                or players[p].league_platform != resolved.id
                or not is_fresh(players[p].league_fetched_at, ttl)
            )
        ]
        unreachable = [p for p in wanted if p not in players]
        out = {p: RankSnapshot(p, by_puuid[p]) for p in wanted}
        if not stale:
            return out

        fetched = await self._fetch(stale, resolved, budget_seconds)
        for puuid, raw in fetched.items():
            if raw is None:
                out[puuid] = RankSnapshot(puuid, by_puuid[puuid], known=False)
                continue
            await apply_league_entries(self.session, puuid, raw, by_puuid[puuid])
            players[puuid].league_platform = resolved.id
            players[puuid].league_fetched_at = utcnow()

        for puuid in (*stale, *unreachable):
            if puuid not in fetched:
                out[puuid] = RankSnapshot(puuid, by_puuid[puuid], known=False)

        await self._commit_tolerating_race()

        refreshed = (
            await self.session.execute(
                select(RankedEntry).where(RankedEntry.puuid.in_(wanted))
            )
        ).scalars()
        final: dict[str, list[RankedEntry]] = {p: [] for p in wanted}
        for entry in refreshed:
            final[entry.puuid].append(entry)
        for puuid, snapshot in out.items():
            out[puuid] = RankSnapshot(puuid, final[puuid], known=snapshot.known)
        return out

    async def _fetch(
        self,
        puuids: Sequence[str],
        platform: Platform,
        budget_seconds: float | None,
    ) -> dict[str, list[dict] | None]:
        semaphore = asyncio.Semaphore(RANK_CONCURRENCY)
        results: dict[str, list[dict] | None] = {}

        async def one(puuid: str) -> None:
            async with semaphore:
                try:
                    results[puuid] = await self.client.league_entries_by_puuid(
                        puuid, platform
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # Deliberately everything, not just RiotApiError. A 200
                    # carrying an edge HTML error page raises JSONDecodeError,
                    # which is not a RiotApiError; escaping `gather` it would
                    # fail the whole lobby and leave the sibling coroutines
                    # running as orphans, still spending the rate limit and
                    # writing into a dict nobody will read. One bad player
                    # should cost one `known=False`.
                    log.info("rank lookup failed for %s: %s", puuid[:12], exc)
                    results[puuid] = None

        tasks = [one(p) for p in puuids]
        try:
            if budget_seconds is None:
                await asyncio.gather(*tasks)
            else:
                async with asyncio.timeout(budget_seconds):
                    await asyncio.gather(*tasks)
        except TimeoutError:
            # Partial is the point. Whatever landed has been recorded; the rest
            # come back unknown and the next call picks them up.
            log.info(
                "rank budget of %.1fs expired with %d of %d fetched",
                budget_seconds,
                len(results),
                len(puuids),
            )
        return results

    async def _commit_tolerating_race(self) -> None:
        """Two requests on the same lobby both insert the same rows; one loses.

        Both read the same upstream data, so the loser adopts what landed.

        **The rollback expires every object in the session, including objects
        this method never touched.** FastAPI hands one session to every service
        in a request, so the caller's ``Player`` or ``Match`` instances are
        expired too and the next attribute read on one fires a lazy SELECT,
        which under asyncio surfaces as MissingGreenlet from somewhere
        unrelated. Callers therefore read what they need *before* calling into
        this path; see the route in ``api/routes/summoner.py`` and the
        plan-building step in ``LobbyRankBackfill.measure``.
        """
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            log.info("concurrent rank write; adopting the committed rows")
