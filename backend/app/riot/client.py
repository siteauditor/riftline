"""Async Riot API client.

Everything that talks to Riot goes through here, so rate limiting, retries and
error translation are enforced in exactly one place.

A note on identity, because Riot moved the goalposts and most older tutorials
are now wrong: **PUUID is the only real primary key.** ``summoner-v4`` no longer
returns ``name`` or ``accountId``, ``by-name`` lookups are gone entirely, and
``league-v4`` moved from ``by-summoner/{summonerId}`` to ``by-puuid``. A player's
display name lives solely in ``account-v1`` as ``gameName#tagLine``. So every
lookup in this app starts by resolving a Riot ID to a PUUID and carries that
PUUID from there.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from app.riot.errors import (
    RiotApiError,
    RiotForbidden,
    RiotGone,
    RiotNotFound,
    RiotRateLimited,
    RiotUnauthorized,
    RiotUnavailable,
)
from app.riot.limiter import RateLimiter, WaitTooLong
from app.riot.routing import (
    Platform,
    Regional,
    platform_host,
    regional_host,
    resolve_platform,
)

log = logging.getLogger(__name__)

# Riot sends no Retry-After on a few edge cases; this keeps us from hot-looping.
FALLBACK_RETRY_AFTER = 5.0


class RiotClient:
    """One client per process, sharing a single rate limiter and connection pool."""

    def __init__(
        self,
        api_key: str,
        *,
        limiter: RateLimiter | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.limiter = limiter or RateLimiter()
        self.max_retries = max_retries
        # Whether Riot accepted the key on its latest answer, and when (epoch
        # seconds). None until the first answer. /api/health reports it, so a
        # page can say live data is paused before a visitor's lookup fails on
        # it, and the deploy's health check prints it.
        self.key_ok: bool | None = None
        self.key_checked_at: float | None = None
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "X-Riot-Token": api_key,
                "Accept": "application/json",
                # Riot's edge is picky about clients that omit a UA.
                "User-Agent": "lol-analytics/0.1 (+local development)",
            },
            transport=transport,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RiotClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ core

    async def get(
        self,
        host: str,
        template: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        """GET a Riot endpoint.

        ``template`` is the *unsubstituted* path (``/lol/match/v5/matches/{matchId}``).
        Keying the limiter on the template rather than the concrete URL is what
        makes method-scope limits work: every match fetch shares one budget.

        ``allow_404`` returns ``None`` instead of raising, for the endpoints
        where "absent" is a normal answer (no live game, unranked player).
        """
        # Every segment quoted, `/` included. A Riot ID is user input, and
        # left raw a searched "abc?x#EUW" became a query string and a lookup
        # of "abc" instead of the 404 the player is owed.
        path = template.format(
            **{k: quote(str(v), safe="") for k, v in (path_params or {}).items()}
        )
        url = f"{host}{path}"
        # Limits are per-region as well as per-method, so the host is part of the key.
        method_key = f"{host.split('//')[-1].split('.')[0]}:{template}"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                await self.limiter.acquire(method_key)
            except WaitTooLong as exc:
                # The caller has a deadline and the key has no slot before it.
                # Said as a rate limit, which it is, so the page shows its
                # countdown instead of a request hanging past the edge timeout.
                raise RiotRateLimited(
                    "Riot's rate limit is busy; try again shortly.",
                    retry_after=exc.retry_after,
                    scope="local",
                    status=429,
                    url=url,
                ) from None
            try:
                response = await self._http.get(url, params=dict(params or {}))
            except httpx.TimeoutException as exc:
                last_error = exc
                log.warning("Riot timeout %s (attempt %d)", path, attempt + 1)
                await self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("Riot transport error %s: %s", path, exc)
                await self._backoff(attempt)
                continue

            await self.limiter.observe(method_key, response.headers)
            status = response.status_code
            self._note_key(status, response.headers)

            if status == 200:
                return response.json()

            if status == 404:
                if allow_404:
                    return None
                raise RiotNotFound("Not found on this route.", status=404, url=url)

            if status == 403 and not _has_rate_limit_headers(response.headers):
                # Riot refuses an endpoint the key may not call at the edge, so
                # the reply carries no rate-limit headers. A key that is simply
                # expired is rejected by the API itself and does carry them.
                # Telling the user to regenerate a working key would send them
                # chasing the wrong problem.
                raise RiotForbidden(
                    f"Riot refused this endpoint ({template}). The key is fine; "
                    "either it is not entitled to this endpoint or Riot has "
                    "withdrawn it.",
                    status=403,
                    url=url,
                )

            if status in (401, 403):
                raise RiotUnauthorized(
                    "Riot rejected the API key. Development keys expire after 24 "
                    "hours, so regenerate it at https://developer.riotgames.com "
                    "and restart the server.",
                    status=status,
                    url=url,
                )

            if status == 410:
                raise RiotGone(
                    f"Riot has withdrawn this endpoint ({template}).",
                    status=410,
                    url=url,
                )

            if status == 429:
                retry_after = _retry_after(response.headers)
                scope = response.headers.get("X-Rate-Limit-Type", "application")
                # "service" is Riot shedding load, not our key misbehaving, so it
                # is penalised against the method rather than the whole app.
                penalty_scope = "application" if scope == "application" else method_key
                await self.limiter.penalize(penalty_scope, retry_after)
                log.warning(
                    "Riot 429 (%s scope) on %s, waiting %.1fs", scope, path, retry_after
                )
                last_error = RiotRateLimited(
                    "Rate limited by Riot.",
                    retry_after=retry_after,
                    scope=scope,
                    status=429,
                    url=url,
                )
                if attempt < self.max_retries:
                    continue
                raise last_error

            if 500 <= status < 600:
                last_error = RiotUnavailable(
                    f"Riot returned {status}.", status=status, url=url
                )
                log.warning("Riot %d on %s (attempt %d)", status, path, attempt + 1)
                await self._backoff(attempt)
                continue

            raise RiotApiError(
                f"Unexpected status {status} from Riot.", status=status, url=url
            )

        if isinstance(last_error, RiotApiError):
            raise last_error
        raise RiotUnavailable(
            f"Riot unreachable after {self.max_retries + 1} attempts: {last_error}",
            url=url,
        )

    def _note_key(self, status: int, headers: Mapping[str, str]) -> None:
        """What an answer says about the key. A 403 without rate-limit headers
        is an endpoint refused at Riot's edge and says nothing about it, and
        neither does a 5xx."""
        if status in (401, 403) and (status == 401 or _has_rate_limit_headers(headers)):
            self.key_ok = False
        elif status < 500 and status not in (401, 403):
            self.key_ok = True
        else:
            return
        self.key_checked_at = time.time()

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(min(2.0**attempt * 0.5, 8.0))

    # ------------------------------------------------------- account-v1 (regional)

    async def account_by_riot_id(
        self, game_name: str, tag_line: str, regional: Regional | str
    ) -> dict:
        """Resolve ``gameName#tagLine`` to a PUUID. The entry point for everything."""
        return await self.get(
            regional_host(regional),
            "/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}",
            path_params={"gameName": game_name, "tagLine": tag_line},
        )

    async def account_by_puuid(self, puuid: str, regional: Regional | str) -> dict:
        return await self.get(
            regional_host(regional),
            "/riot/account/v1/accounts/by-puuid/{puuid}",
            path_params={"puuid": puuid},
        )

    async def active_region(self, puuid: str, regional: Regional | str) -> str | None:
        """The shard this account plays League on now, as Riot reports it.

        Any account region answers it: measured on 2026-09-24, europe and
        americas both named euw1 for a EUW account, and asia named oc1 for an
        OCE account whose games are on OC1 and sg2 for two whose games are on
        SG2, matching the platforms of their stored games. It replaces guessing
        the home from which shard has a summoner record, which a level 30 NA
        record on a EUW Challenger fooled. None when Riot has no answer.
        """
        data = await self.get(
            regional_host(regional),
            "/riot/account/v1/region/by-game/{game}/by-puuid/{puuid}",
            path_params={"game": "lol", "puuid": puuid},
            allow_404=True,
        )
        region = data.get("region") if isinstance(data, dict) else None
        if not isinstance(region, str) or not region.strip():
            return None
        return region.strip().lower()

    # ------------------------------------------------ summoner / league (platform)

    async def summoner_by_puuid(self, puuid: str, platform: Platform | str) -> dict:
        """Profile icon, level and revision date. No name -- that is account-v1's job."""
        return await self.get(
            platform_host(platform),
            "/lol/summoner/v4/summoners/by-puuid/{puuid}",
            path_params={"puuid": puuid},
        )

    async def league_entries_by_puuid(
        self, puuid: str, platform: Platform | str
    ) -> list[dict]:
        """Ranked entries. An empty list simply means unranked in every queue."""
        return await self.get(
            platform_host(platform),
            "/lol/league/v4/entries/by-puuid/{puuid}",
            path_params={"puuid": puuid},
        )

    async def apex_league(
        self, queue: str, tier: str, platform: Platform | str
    ) -> dict:
        """Challenger / Grandmaster / Master ladder, used to seed ingestion."""
        tiers = {
            "challenger": "/lol/league/v4/challengerleagues/by-queue/{queue}",
            "grandmaster": "/lol/league/v4/grandmasterleagues/by-queue/{queue}",
            "master": "/lol/league/v4/masterleagues/by-queue/{queue}",
        }
        try:
            template = tiers[tier.lower()]
        except KeyError:
            raise ValueError(f"apex_league expects challenger/grandmaster/master, got {tier!r}") from None
        return await self.get(
            platform_host(platform), template, path_params={"queue": queue}
        )

    async def league_entries(
        self,
        queue: str,
        tier: str,
        division: str,
        platform: Platform | str,
        *,
        page: int = 1,
    ) -> list[dict]:
        """A page of the ladder for a tier/division, 205 entries per page."""
        return await self.get(
            platform_host(platform),
            "/lol/league/v4/entries/{queue}/{tier}/{division}",
            path_params={"queue": queue, "tier": tier.upper(), "division": division.upper()},
            params={"page": page},
        )

    # ----------------------------------------------- champion-mastery (platform)

    async def champion_masteries(
        self, puuid: str, platform: Platform | str
    ) -> list[dict]:
        return await self.get(
            platform_host(platform),
            "/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}",
            path_params={"puuid": puuid},
        )

    async def champion_mastery(
        self, puuid: str, champion_id: int, platform: Platform | str
    ) -> dict | None:
        """One player's mastery on one champion, or ``None`` if they have none.

        Riot answers 404 for a champion the player has never earned a point on,
        which is a real answer ("first time on this champion"), so it comes back
        as ``None`` rather than an error. The live tab uses this instead of the
        full table because it needs one champion per player, and the full table
        is a hundred-odd rows each.
        """
        return await self.get(
            platform_host(platform),
            "/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/by-champion/{champion_id}",
            path_params={"puuid": puuid, "champion_id": champion_id},
            allow_404=True,
        )

    async def mastery_score(self, puuid: str, platform: Platform | str) -> int:
        return await self.get(
            platform_host(platform),
            "/lol/champion-mastery/v4/scores/by-puuid/{puuid}",
            path_params={"puuid": puuid},
        )

    # ------------------------------------------------------ match-v5 (regional)

    async def match_ids(
        self,
        puuid: str,
        regional: Regional | str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        type_: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[str]:
        params: dict[str, Any] = {"start": start, "count": min(count, 100)}
        if queue is not None:
            params["queue"] = queue
        if type_ is not None:
            params["type"] = type_
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return await self.get(
            regional_host(regional),
            "/lol/match/v5/matches/by-puuid/{puuid}/ids",
            path_params={"puuid": puuid},
            params=params,
        )

    async def match(self, match_id: str, regional: Regional | str) -> dict:
        """A finished match. Immutable, so callers cache it permanently."""
        return await self.get(
            regional_host(regional),
            "/lol/match/v5/matches/{matchId}",
            path_params={"matchId": match_id},
        )

    async def match_timeline(self, match_id: str, regional: Regional | str) -> dict:
        return await self.get(
            regional_host(regional),
            "/lol/match/v5/matches/{matchId}/timeline",
            path_params={"matchId": match_id},
        )

    # ------------------------------------------------------ spectator (platform)

    async def active_game(self, puuid: str, platform: Platform | str) -> dict | None:
        """Live game, or ``None`` when the player is not in one.

        Riot announced Spectator-V5's deactivation in October 2025 alongside the
        in-client anonymity options. Callers must treat ``None`` and
        :class:`RiotGone` as ordinary outcomes.
        """
        return await self.get(
            platform_host(platform),
            "/lol/spectator/v5/active-games/by-summoner/{puuid}",
            path_params={"puuid": puuid},
            allow_404=True,
        )

    async def champion_rotations(self, platform: Platform | str) -> dict:
        return await self.get(
            platform_host(platform), "/lol/platform/v3/champion-rotations"
        )


def _has_rate_limit_headers(headers: Mapping[str, str]) -> bool:
    """Did this response come from the API itself, or from the edge?

    Riot stamps every response the API actually handled with its rate-limit
    counters. A refusal at the edge carries none, which is how an endpoint the
    key may not call is told apart from a key that has expired.
    """
    return any(k.lower().startswith("x-app-rate-limit") for k in headers)


def _retry_after(headers: Mapping[str, str]) -> float:
    try:
        return max(0.0, float(headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return FALLBACK_RETRY_AFTER


__all__ = ["RiotClient", "resolve_platform"]
