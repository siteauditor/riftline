"""Match fetching, normalisation and storage.

Cost model, because it drives every decision here: one call returns up to 100
match *ids*, but each match's detail is a separate call. On a development key
(100 requests / 2 minutes) a cold 20-game history is ~21 calls. A warm one is a
single call, and often zero.

So: matches are immutable once played, and are stored permanently on first
fetch. We only ever request ids we do not already hold.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Match, MatchParticipant
from app.riot.client import RiotClient
from app.riot.errors import RiotApiError, RiotNotFound
from app.riot.routing import Regional, resolve_platform
from app.services.scores import ScoreService, lifted_fields

log = logging.getLogger(__name__)

# Games shorter than this are remakes; including them skews every aggregate.
REMAKE_SECONDS = 300
# How many match fetches to have in flight. The limiter paces the actual sends;
# this just bounds memory and keeps one slow player from monopolising the pool.
FETCH_CONCURRENCY = 8

_PATCH_RE = re.compile(r"^(\d+)\.(\d+)")


def patch_of(game_version: str | None) -> str | None:
    """'15.18.704.2255' -> '15.18'. Stats only compare within a patch."""
    if not game_version:
        return None
    match = _PATCH_RE.match(game_version)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def duration_seconds(info: dict) -> int:
    """Normalise gameDuration.

    Riot changed this in patch 11.20: matches carrying a ``gameEndTimestamp``
    report duration in seconds, older ones in milliseconds. Getting it wrong
    turns CS/min into nonsense, so we branch on the field's presence exactly as
    Riot documents it.
    """
    raw = int(info.get("gameDuration") or 0)
    if info.get("gameEndTimestamp") is None and raw > 10_000:
        return raw // 1000
    return raw


class PlayedRow(NamedTuple):
    """One stored game from a single player's point of view."""

    champion_id: int
    team_position: str | None
    win: bool
    kills: int
    deaths: int
    assists: int
    total_minions: int
    vision_score: int
    damage_to_champions: int
    queue_id: int
    game_creation: int
    game_duration: int
    # Null on a game the score was withheld for, or that has no timeline.
    performance_score: float | None = None
    performance_rank: int | None = None
    performance_detail: dict | None = None
    gold_diff_14: int | None = None
    # Appended rather than placed with the other match columns, because rows are
    # built positionally with `PlayedRow(*row)`: a field in the middle would
    # silently shift every value after it.
    match_id: str | None = None


@dataclass(slots=True)
class HistoryPage:
    """One page of history.

    ``id_count`` is how many ids Riot returned, which is deliberately *not* the
    same as ``len(matches)``: a match can fail to fetch or have aged out of
    retention. Paging must key off what Riot has, or one bad match silently
    truncates the rest of a player's history.
    """

    matches: list[Match] = field(default_factory=list)
    id_count: int = 0


@dataclass(slots=True)
class StoredHistoryPage:
    """One page of a player's stored games, and how many there are in all."""

    matches: list[Match] = field(default_factory=list)
    total: int = 0


class MatchService:
    def __init__(
        self,
        session: AsyncSession,
        client: RiotClient,
        settings,
        *,
        source_bracket: str | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.settings = settings
        # Set by the crawler to record which ladder a match was collected from.
        # On-demand lookups leave it None: we have no idea what bracket some
        # random searched player's game was, and guessing would be worse than
        # admitting it.
        self.source_bracket = source_bracket

    # ------------------------------------------------------------------- ids

    async def match_ids(
        self,
        puuid: str,
        platform_name: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
    ) -> list[str]:
        platform = resolve_platform(platform_name)
        return await self.client.match_ids(
            puuid, platform.regional, start=start, count=count, queue=queue
        )

    async def known_ids(self, match_ids: Sequence[str]) -> set[str]:
        if not match_ids:
            return set()
        stmt = select(Match.match_id).where(Match.match_id.in_(list(match_ids)))
        return set((await self.session.execute(stmt)).scalars())

    # --------------------------------------------------------------- fetching

    async def ensure_matches(
        self, match_ids: Sequence[str], regional: Regional | str
    ) -> list[Match]:
        """Return the given matches, fetching only the ones we do not hold."""
        if not match_ids:
            return []

        have = await self.known_ids(match_ids)
        missing = [m for m in match_ids if m not in have]
        if missing:
            log.info("fetching %d new matches (%d cached)", len(missing), len(have))
            await self._fetch_and_store(missing, regional)

        found = await self._load(match_ids)
        if not await self._score_unscored(found):
            # The rollback expired every loaded object, and reading an expired
            # one under asyncio fails outright, so read them again.
            found = await self._load(match_ids)
        return found

    async def _load(self, match_ids: Sequence[str]) -> list[Match]:
        stmt = (
            select(Match)
            .where(Match.match_id.in_(list(match_ids)))
            .options(selectinload(Match.participants))
        )
        by_id = {m.match_id: m for m in (await self.session.execute(stmt)).scalars()}
        # Preserve Riot's ordering (newest first); drop any that failed to fetch.
        return [by_id[mid] for mid in match_ids if mid in by_id]

    async def _score_unscored(self, matches: Sequence[Match]) -> bool:
        """Score any of these that have not been through scoring yet.

        Returns False if it had to roll back, which expires the loaded matches.

        Costs no Riot call: a score is the stored match against the stored
        percentiles. Before this, a game fetched by a profile view waited for
        the nightly run, so a player's newest games were exactly the ones with
        no score (19 of 20 on HONEY BADGER#LIVID on 2026-09-19). Older stored
        games that missed scoring are lifted and scored here too, so that
        backlog clears page by page as profiles are opened.
        """
        pending = [
            m for m in matches
            if any(p.performance_scored_at is None for p in m.participants)
        ]
        if not pending:
            return True
        scorer = ScoreService(self.session)
        try:
            for match in pending:
                if any(p.time_dead is None for p in match.participants):
                    scorer.lift_match(match)
            await scorer.score_and_stamp(pending)
            await self.session.commit()
        except Exception:  # noqa: BLE001 -- a missing score must never cost the page
            log.exception("scoring %d fetched matches failed", len(pending))
            await self.session.rollback()
            return False
        return True

    async def _fetch_and_store(
        self, match_ids: Sequence[str], regional: Regional | str
    ) -> None:
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def fetch(match_id: str) -> dict | None:
            async with semaphore:
                try:
                    return await self.client.match(match_id, regional)
                except RiotNotFound:
                    # Match aged out of Riot's retention window.
                    log.info("match %s no longer available", match_id)
                    return None
                except RiotApiError as exc:
                    # One bad match must not fail the whole page.
                    log.warning("match %s failed: %s", match_id, exc)
                    return None

        payloads = await asyncio.gather(*(fetch(mid) for mid in match_ids))

        # Drop blanks and repeats before touching the session: adding the same
        # primary key twice fails the entire transaction, taking good matches
        # down with the duplicate.
        fresh: dict[str, dict] = {}
        for payload in payloads:
            if not payload:
                continue
            mid = (payload.get("metadata") or {}).get("matchId")
            if mid and mid not in fresh:
                fresh[mid] = payload
        if not fresh:
            return

        # Another request may have stored some of these while we were fetching.
        already = await self.known_ids(list(fresh))
        pending = [p for mid, p in fresh.items() if mid not in already]
        if not pending:
            return

        for payload in pending:
            self._store(payload)
        try:
            await self.session.commit()
        except IntegrityError:
            # A concurrent request won the race on at least one match. Matches
            # are immutable, so the winner wrote the same bytes we would have.
            # Retry one at a time so the genuinely-new ones still land.
            await self.session.rollback()
            log.info("write race on %d matches; retrying individually", len(pending))
            await self._store_individually(pending)

    async def _store_individually(self, payloads: Sequence[dict]) -> None:
        for payload in payloads:
            mid = (payload.get("metadata") or {}).get("matchId")
            if not mid or await self.known_ids([mid]):
                continue
            self._store(payload)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()

    # ---------------------------------------------------------- normalisation

    def _store(self, payload: dict) -> Match | None:
        info = payload.get("info") or {}
        metadata = payload.get("metadata") or {}
        match_id = metadata.get("matchId")
        if not match_id or not info:
            return None

        seconds = duration_seconds(info)
        participants = info.get("participants") or []
        early_surrender = any(p.get("gameEndedInEarlySurrender") for p in participants)

        match = Match(
            match_id=match_id,
            platform_id=info.get("platformId") or "",
            queue_id=int(info.get("queueId") or 0),
            game_mode=info.get("gameMode"),
            game_type=info.get("gameType"),
            game_version=info.get("gameVersion"),
            patch=patch_of(info.get("gameVersion")),
            map_id=info.get("mapId"),
            game_creation=int(info.get("gameCreation") or 0),
            game_duration=seconds,
            game_end_timestamp=info.get("gameEndTimestamp"),
            end_of_game_result=info.get("endOfGameResult"),
            is_remake=seconds < REMAKE_SECONDS or early_surrender,
            source_bracket=self.source_bracket,
            teams=info.get("teams"),
            raw=payload,
        )
        self.session.add(match)

        for index, p in enumerate(participants):
            self.session.add(self._participant(match_id, p, index))
        return match

    @staticmethod
    def _participant(match_id: str, p: dict, index: int) -> MatchParticipant:
        return MatchParticipant(
            match_id=match_id,
            # Riot's own ordering, kept so a scoreboard renders the same way twice.
            participant_index=p.get("participantId") or index + 1,
            puuid=p.get("puuid") or "",
            # match-v5 carries every player's Riot ID inline, so a scoreboard
            # costs no extra account-v1 calls.
            riot_id_game_name=p.get("riotIdGameName") or p.get("riotIdName"),
            riot_id_tagline=p.get("riotIdTagline"),
            champion_id=int(p.get("championId") or 0),
            champion_name=p.get("championName"),
            team_id=int(p.get("teamId") or 0),
            # teamPosition is matchmaking's assignment and is the trustworthy
            # one; `lane` and `role` are legacy and often disagree.
            team_position=(p.get("teamPosition") or "") or None,
            individual_position=p.get("individualPosition"),
            win=bool(p.get("win")),
            kills=p.get("kills") or 0,
            deaths=p.get("deaths") or 0,
            assists=p.get("assists") or 0,
            champ_level=p.get("champLevel") or 0,
            gold_earned=p.get("goldEarned") or 0,
            total_minions=(p.get("totalMinionsKilled") or 0)
            + (p.get("neutralMinionsKilled") or 0),
            vision_score=p.get("visionScore") or 0,
            damage_to_champions=p.get("totalDamageDealtToChampions") or 0,
            damage_taken=p.get("totalDamageTaken") or 0,
            heal_on_teammates=p.get("totalHealsOnTeammates") or 0,
            time_played=p.get("timePlayed") or 0,
            double_kills=p.get("doubleKills") or 0,
            triple_kills=p.get("tripleKills") or 0,
            quadra_kills=p.get("quadraKills") or 0,
            penta_kills=p.get("pentaKills") or 0,
            first_blood_kill=bool(p.get("firstBloodKill")),
            early_surrender=bool(p.get("gameEndedInEarlySurrender")),
            summoner1_id=p.get("summoner1Id"),
            summoner2_id=p.get("summoner2Id"),
            items=[p.get(f"item{i}") or 0 for i in range(7)],
            perks=p.get("perks"),
            # The fields the score reads, lifted at birth so the row can be
            # scored straight away instead of waiting for the nightly backfill.
            **lifted_fields(p),
        )

    # ---------------------------------------------------------------- history

    async def history(
        self,
        puuid: str,
        platform_name: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
    ) -> HistoryPage:
        platform = resolve_platform(platform_name)
        ids = await self.match_ids(
            puuid, platform_name, start=start, count=count, queue=queue
        )
        matches = await self.ensure_matches(ids, platform.regional)
        return HistoryPage(matches=matches, id_count=len(ids))

    async def stored_history(
        self,
        puuid: str,
        *,
        champion_id: int,
        queue: int | None = None,
        start: int = 0,
        count: int = 20,
    ) -> StoredHistoryPage:
        """This player's games on one champion, **from storage only**, newest first.

        Riot's history endpoint filters by queue, type and time, never by
        champion, so a champion filter can only be read from the games we hold.
        It costs no Riot call, and the response says it is stored games.

        Remakes are left out, as `played_by` leaves them out, so the count
        matches the one the champions table shows beside the link here.
        """
        conditions = [
            MatchParticipant.puuid == puuid,
            MatchParticipant.champion_id == champion_id,
            Match.is_remake.is_(False),
        ]
        if queue is not None:
            conditions.append(Match.queue_id == queue)
        base = (
            select(Match.match_id)
            .join(MatchParticipant, MatchParticipant.match_id == Match.match_id)
            .where(*conditions)
        )
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        ids = list(
            (
                await self.session.execute(
                    # Match id second, so games stored with the same start time
                    # still page in one fixed order.
                    base.order_by(Match.game_creation.desc(), Match.match_id.desc())
                    .offset(start)
                    .limit(count)
                )
            ).scalars()
        )
        return StoredHistoryPage(matches=await self._load(ids), total=int(total))

    # --------------------------------------------------------------- analytics

    async def played_by(
        self, puuid: str, *, queue: int | None = None, limit: int = 300
    ) -> list[PlayedRow]:
        """This player's games **from storage only**, newest first.

        Deliberately does not call Riot. Analytics are a view over what we have
        already fetched, so opening the page costs nothing and can never sit
        behind a rate limit. The corollary is that it describes the matches we
        hold, not the player's whole season, which the response states outright.
        """
        stmt = (
            select(
                MatchParticipant.champion_id,
                MatchParticipant.team_position,
                MatchParticipant.win,
                MatchParticipant.kills,
                MatchParticipant.deaths,
                MatchParticipant.assists,
                MatchParticipant.total_minions,
                MatchParticipant.vision_score,
                MatchParticipant.damage_to_champions,
                Match.queue_id,
                Match.game_creation,
                Match.game_duration,
                MatchParticipant.performance_score,
                MatchParticipant.performance_rank,
                MatchParticipant.performance_detail,
                MatchParticipant.gold_diff_14,
                MatchParticipant.match_id,
            )
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.puuid == puuid, Match.is_remake.is_(False))
            .order_by(Match.game_creation.desc())
            .limit(limit)
        )
        if queue is not None:
            stmt = stmt.where(Match.queue_id == queue)
        return [PlayedRow(*row) for row in (await self.session.execute(stmt)).all()]

    async def last_stored(self, puuid: str) -> PlayedRow | None:
        """The newest game we hold for this player, or None if we hold none.

        The newest game **we hold**, which is not the newest they played: the
        corpus is crawled, and for a player with five or more stored games the
        newest one is a median of four days old. Whatever shows this has to say
        so.
        """
        rows = await self.played_by(puuid, limit=1)
        return rows[0] if rows else None

    async def stored_count(self, puuid: str) -> int:
        """How many games we hold for this player. Zero is an answer."""
        stmt = (
            select(func.count())
            .select_from(MatchParticipant)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.puuid == puuid, Match.is_remake.is_(False))
        )
        return int((await self.session.execute(stmt)).scalar() or 0)
