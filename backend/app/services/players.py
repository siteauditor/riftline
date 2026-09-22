"""Player lookup: Riot ID -> PUUID -> profile, rank and mastery.

Every request here is rationed. On a development key the binding limit is 100
requests per two minutes, so the cache is not an optimisation, it is what makes
the feature usable at all. A cold profile costs three calls (account, summoner,
league); a warm one inside its TTL costs zero.
"""

from __future__ import annotations

import logging
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChampionMastery,
    Match,
    MatchParticipant,
    Player,
    RankedEntry,
    utcnow,
)
from app.riot.client import RiotClient
from app.riot.errors import RiotNotFound
from app.riot.routing import (
    Platform,
    UnknownPlatform,
    resolve_platform,
)
from app.services.ranks import apply_league_entries, is_fresh, puuids_with_history

log = logging.getLogger(__name__)


class PlayerNotFound(Exception):
    """No such Riot ID on this platform."""


def normalize_riot_name(name: str) -> str:
    """Fold a Riot ID name into the form used as a cache key.

    Riot matches Riot IDs loosely. Asking account-v1 for ``Caps#EUW`` returns
    the account that displays as ``Cäps#EUW``, so storing what Riot returns and
    then looking it up by exact match means the cache never hits and every page
    view spends an account-v1 call -- the most expensive mistake you can make on
    a 100-per-2-minutes budget.

    Folding both the query and the stored name through NFKD, dropping combining
    marks, and lowercasing makes ``Caps`` and ``Cäps`` land on the same key.
    Riot IDs are unique under its own folding, so this cannot merge two real
    accounts; and because rows are keyed by PUUID, a wrong guess self-heals on
    the next fetch.
    """
    folded = unicodedata.normalize("NFKD", (name or "").strip())
    without_marks = "".join(c for c in folded if not unicodedata.combining(c))
    # Riot also ignores internal spacing when matching.
    return without_marks.replace(" ", "").casefold()


# Shared with `ranks`, which owns it: both modules need the same TTL rule.
_is_fresh = is_fresh

# A refresh goes back to Riot only once the cached answer is at least this old.
# Without a floor `?refresh=true` skipped every TTL, so reloading one public URL
# could spend a development key's 100 requests per two minutes, and the profile's
# Update button makes that one click. Riot's own data does not move faster than
# a game, so a minute loses nothing.
REFRESH_FLOOR_SECONDS = 60


def _cached_is_good(stamp, ttl: int, refresh: bool) -> bool:
    """Whether a cached answer may be served instead of asking Riot again."""
    return _is_fresh(stamp, min(ttl, REFRESH_FLOOR_SECONDS) if refresh else ttl)


class PlayerService:
    def __init__(self, session: AsyncSession, client: RiotClient, settings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    # ----------------------------------------------------------------- lookup

    async def resolve(
        self, platform_name: str, game_name: str, tag_line: str, *, refresh: bool = False
    ) -> Player:
        """Find a player by Riot ID, hitting Riot only when the cache is cold.

        Riot IDs are case- and space-insensitive for lookup but we store them as
        Riot returns them, so the UI shows the player's own capitalisation.
        """
        platform = resolve_platform(platform_name)
        tag_line = tag_line.lstrip("#")

        player = await self._find_cached(platform, game_name, tag_line)

        if player is None or not _cached_is_good(
            player.account_fetched_at, self.settings.ttl_account, refresh
        ):
            try:
                account = await self.client.account_by_riot_id(
                    game_name, tag_line, platform.account_region
                )
            except RiotNotFound:
                if player is not None:
                    # Riot is unsure but we have a cached hit: a rename, most
                    # likely. Serve what we have rather than 404ing the user.
                    log.info("account-v1 miss for %s#%s; serving cache", game_name, tag_line)
                    return player
                raise PlayerNotFound(f"{game_name}#{tag_line} not found on {platform.label}") from None
            player = await self._upsert_from_account(account, platform, existing=player)

        await self.ensure_summoner(player, platform, refresh=refresh)
        return player

    async def resolve_stored(self, platform_name: str, game_name: str, tag_line: str) -> Player:
        """The row we hold for a Riot ID, and nothing from Riot.

        For the prerendered profile: a page is written for every player with
        enough scored games, and a thousand pages each spending an account-v1
        call would be the whole key's budget for twenty minutes. Nothing here
        is refreshed either, so the answer is whatever the last visit left,
        which is what the page says it is.
        """
        platform = resolve_platform(platform_name)
        player = await self._find_cached(platform, game_name, tag_line.lstrip("#"))
        if player is None:
            raise PlayerNotFound(f"{game_name}#{tag_line} is not stored for {platform.label}")
        return player

    async def _find_cached(
        self, platform: Platform, game_name: str, tag_line: str
    ) -> Player | None:
        stmt = select(Player).where(
            Player.platform == platform.id,
            Player.search_name == normalize_riot_name(game_name),
            func.lower(Player.tag_line) == tag_line.strip().lower(),
        )
        # limit(1): a rename could in principle leave two rows folding to the
        # same key, and a stale duplicate must not turn a lookup into a 500.
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def _upsert_from_account(
        self, account: dict, platform: Platform, *, existing: Player | None = None
    ) -> Player:
        puuid = account["puuid"]

        # The row we matched on name may belong to a *different* account: the
        # player renamed and someone else took the name. Retire the stale row's
        # search key, or two rows fold to the same lookup forever and the cache
        # starts returning whichever one the database happens to pick first.
        if existing is not None and existing.puuid != puuid:
            log.info(
                "riot id %s#%s now resolves to a different puuid; retiring stale cache row",
                account.get("gameName"),
                account.get("tagLine"),
            )
            existing.search_name = None

        player = await self.session.get(Player, puuid)
        if player is None:
            player = Player(puuid=puuid, platform=platform.id)
            self.session.add(player)

        # gameName/tagLine are optional in the DTO for accounts without a Riot ID.
        player.game_name = account.get("gameName") or player.game_name
        player.tag_line = account.get("tagLine") or player.tag_line
        player.search_name = normalize_riot_name(player.game_name or "")
        player.platform = platform.id
        player.account_fetched_at = utcnow()

        try:
            await self.session.commit()
        except IntegrityError:
            # Two requests for the same new player raced. They carry identical
            # data, so the loser simply adopts the winner's row rather than
            # failing a page load over it.
            await self.session.rollback()
            player = await self.session.get(Player, puuid)
            if player is None:
                raise
        return player

    # --------------------------------------------------------------- summoner

    async def ensure_summoner(
        self, player: Player, platform: Platform, *, refresh: bool = False
    ) -> Player:
        """Top up level and profile icon. summoner-v4 no longer returns a name.

        The cache is scoped to a platform: the same account can hold a record on
        more than one shard, and the level shown has to belong to the shard being
        viewed.
        """
        cached_here = player.summoner_platform == platform.id
        if cached_here and _cached_is_good(
            player.summoner_fetched_at, self.settings.ttl_summoner, refresh
        ):
            return player
        try:
            data = await self.client.summoner_by_puuid(player.puuid, platform)
        except RiotNotFound:
            # A valid Riot account with no record on *this* shard. account-v1
            # resolves a Riot ID across a whole region, so searching the wrong
            # one gets this far and then has no level, no icon and no ranks.
            # Left alone it renders as a hollow profile, so the blanks are kept
            # deliberately and `home_platform` below names the real shard.
            #
            # The stamp is cleared rather than set. A level belongs to a
            # platform, and this row holds one of each: stamping a miss as
            # fresh cached "no level" against the puuid, so the same account
            # then read as level-less on the shard it really plays on, for the
            # whole TTL. Measured on Rhasta#0403, who is on SG.
            player.profile_icon_id = None
            player.summoner_level = None
            player.summoner_platform = platform.id
            player.summoner_fetched_at = utcnow()
            await self.session.commit()
            return player
        player.profile_icon_id = data.get("profileIconId")
        player.summoner_level = data.get("summonerLevel")
        player.revision_date = data.get("revisionDate")
        player.summoner_platform = platform.id
        player.summoner_fetched_at = utcnow()
        await self.session.commit()
        return player

    async def home_platform(self, puuid: str, asked: Platform) -> Platform | None:
        """Which shard this account actually plays on, when it is not ``asked``.

        match-v5 ids are prefixed with the platform that hosted the game
        ("SG2_7412..."), which is the only way to answer this: no endpoint maps
        a puuid to a shard. Stored matches answer it for free, and only an
        account we have never seen costs one regional call.

        ``None`` means we could not tell, which is different from "they are on
        this shard" and is reported as such.
        """
        stored = (
            await self.session.execute(
                select(Match.platform_id)
                .join(MatchParticipant, MatchParticipant.match_id == Match.match_id)
                .where(MatchParticipant.puuid == puuid)
                .order_by(Match.game_creation.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if stored is None:
            try:
                ids = await self.client.match_ids(
                    puuid, asked.regional, start=0, count=1
                )
            except Exception as exc:  # noqa: BLE001 -- a hint, never a page failure
                log.warning("could not read a match id for %s: %s", puuid[:8], exc)
                return None
            if not ids:
                return None
            stored = ids[0].split("_", 1)[0]

        try:
            found = resolve_platform(stored)
        except UnknownPlatform:
            log.warning("match id carried an unknown platform %r", stored)
            return None
        return None if found.id == asked.id else found

    async def effective_platform(self, player: Player, asked: Platform) -> Platform:
        """The shard whose per-shard endpoints actually hold this account.

        account-v1 resolves a Riot ID across a whole *region*, so a search on
        any shard in that region finds the account. Everything after that is
        per shard: summoner-v4, league-v4, champion-mastery-v4 and
        spectator-v5 each answer only for the platform they are asked. On the
        wrong one, summoner-v4 says 404 while the other three answer 200 with
        nothing in them, which is the worse failure: a real account renders as
        unranked, with no mastery and never in a game.

        OCE is where this bites in practice. `oc1` and `sg2` share the `sea`
        regional route, so an OCE Riot ID resolves and its matches load, while
        the account itself lives on SG2 and the four endpoints above are blank.

        Call this after ``resolve``: a null ``summoner_level`` is
        ``ensure_summoner`` reporting that this shard has no record, which is
        the only cheap signal that the question needs asking at all. When it
        does, ``home_platform`` reads the answer out of stored matches for
        free, and costs one regional call only for an account nobody has
        looked at yet.
        """
        if player.summoner_level is not None:
            return asked
        return await self.home_platform(player.puuid, asked) or asked

    async def summoner_snapshot(self, puuid: str, platform: Platform) -> dict | None:
        """summoner-v4 on ``platform``, read only: nothing is written.

        Deliberately not cached. The Player row holds one level and one icon,
        stamped with the shard they came from, and writing another shard's
        record into it would make the two shards overwrite each other on every
        view. This is only reached when a profile is being read on a shard the
        account has no record on, which is rare, so one uncached call is the
        cheaper mistake.
        """
        try:
            return await self.client.summoner_by_puuid(puuid, platform)
        except Exception as exc:  # noqa: BLE001 -- a nicety, never a page failure
            log.warning("could not read %s record for %s: %s", platform.id, puuid[:8], exc)
            return None

    # ------------------------------------------------------------------ ranks

    async def stored_ranks(self, player: Player) -> list[RankedEntry]:
        """The ranks as last read, from storage only."""
        stmt = select(RankedEntry).where(RankedEntry.puuid == player.puuid)
        return list((await self.session.execute(stmt)).scalars())

    async def ranks(
        self, player: Player, platform_name: str, *, refresh: bool = False
    ) -> list[RankedEntry]:
        platform = resolve_platform(platform_name)
        stmt = select(RankedEntry).where(RankedEntry.puuid == player.puuid)
        current = list((await self.session.execute(stmt)).scalars())

        # Same scoping as the summoner cache: a ranked entry is per shard, and
        # the stored rows are rewritten for whichever platform is being read.
        if player.league_platform == platform.id and _cached_is_good(
            player.league_fetched_at, self.settings.ttl_league, refresh
        ):
            return current

        entries = await self.client.league_entries_by_puuid(player.puuid, platform)
        # Shared with RankCache so the two rank paths cannot drift on which
        # queues to write and which to drop.
        tracked = await puuids_with_history(self.session, [player.puuid])
        await apply_league_entries(
            self.session, player.puuid, entries, current,
            platform=platform.id, baseline=player.puuid not in tracked,
        )

        player.league_platform = platform.id
        player.league_fetched_at = utcnow()
        await self._commit_tolerating_race(player)
        return list((await self.session.execute(stmt)).scalars())

    # ---------------------------------------------------------------- mastery

    async def masteries(
        self, player: Player, platform_name: str, *, refresh: bool = False
    ) -> list[ChampionMastery]:
        platform = resolve_platform(platform_name)
        stmt = select(ChampionMastery).where(ChampionMastery.puuid == player.puuid)
        current = list((await self.session.execute(stmt)).scalars())

        # Scoped to the platform, like the summoner and league caches above and
        # for the same reason: mastery on the wrong shard is an empty 200, and
        # stamping that as fresh hides the real table until the TTL runs out.
        if player.mastery_platform == platform.id and _cached_is_good(
            player.mastery_fetched_at, self.settings.ttl_mastery, refresh
        ):
            return current

        raw_list = await self.client.champion_masteries(player.puuid, platform)
        existing = {m.champion_id: m for m in current}

        for raw in raw_list or []:
            champion_id = raw.get("championId")
            if champion_id is None:
                continue
            mastery = existing.get(champion_id) or ChampionMastery(
                puuid=player.puuid, champion_id=champion_id
            )
            mastery.champion_level = raw.get("championLevel") or 0
            mastery.champion_points = raw.get("championPoints") or 0
            mastery.points_since_last_level = raw.get("championPointsSinceLastLevel") or 0
            mastery.points_until_next_level = raw.get("championPointsUntilNextLevel") or 0
            mastery.last_play_time = raw.get("lastPlayTime")
            mastery.tokens_earned = raw.get("tokensEarned") or 0
            mastery.season_milestone = raw.get("championSeasonMilestone")
            mastery.milestone_grades = raw.get("milestoneGrades")
            # `chestGranted` and `markRequiredForNextLevel` are no longer read.
            # Riot removed chests in 2024: measured false on 166 of 166 entries
            # for a real account and on all 789 rows we hold. The marks figure
            # has never reached a response or a test. Their columns stay for
            # now, because `chest_granted` is NOT NULL with no server default
            # and this deploy runs migrations *after* the new code is already
            # serving, so a model without the column would spend that window
            # failing every insert, swallowed by `_commit_tolerating_race` as a
            # concurrent write.
            if champion_id not in existing:
                self.session.add(mastery)

        player.mastery_platform = platform.id
        player.mastery_fetched_at = utcnow()
        await self._commit_tolerating_race(player)
        return list((await self.session.execute(stmt)).scalars())

    async def _commit_tolerating_race(self, player: Player) -> None:
        """Commit, treating a concurrent identical write as success.

        ``ranked_entries`` and ``champion_masteries`` are uniquely keyed per
        player, so two requests that arrive together both try to insert the same
        rows and one loses. Both read the same upstream data, so the loser can
        simply adopt what landed.

        The refresh is not optional. ``rollback()`` expires *every* object in the
        session, the caller's ``player`` included, and the next attribute access
        on it would emit a lazy SELECT -- which under asyncio surfaces as
        MissingGreenlet from somewhere far away. Repopulating it here keeps the
        service from handing its caller a landmine.
        """
        # Read the key while the object is still usable. A failed flush leaves
        # the session refusing every read until it is rolled back, so even
        # `player.puuid` would raise PendingRollbackError from inside the
        # handler -- including from the log line meant to describe the problem.
        puuid = player.puuid
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            log.info("concurrent write for %s; adopting the committed rows", puuid[:12])
            await self.session.refresh(player)
