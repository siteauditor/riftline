"""Typed errors for the Riot API surface."""

from __future__ import annotations


class RiotApiError(Exception):
    """Base class for every Riot API failure."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.url = url


class RiotUnauthorized(RiotApiError):
    """401/403.

    On a development key this almost always means the key expired: development
    keys last 24 hours and must be regenerated at https://developer.riotgames.com.
    We surface that hint rather than a bare 403 because it is the single most
    common stumble when building against a dev key.
    """


class RiotForbidden(RiotApiError):
    """403 for the endpoint rather than for the key.

    Riot answers a key that may not call an endpoint at the edge, before the key
    is ever evaluated against it, and that response carries **no rate-limit
    headers at all**. A genuine key problem is answered by the API itself and
    does carry them. That difference is the only signal available, and it is
    worth acting on: without it a withdrawn endpoint tells every user to
    regenerate a key that is perfectly fine.

    Measured on 2026-09-17 with a valid key: ``/lol/spectator/v5/featured-games``
    returns 403 with no ``X-App-Rate-Limit``, while ``active-games/by-summoner``
    on the same key returns 404 with the full header set.
    """


class RiotNotFound(RiotApiError):
    """404. The Riot ID, PUUID or match does not exist on that route.

    Note this is also what you get when a player exists but has never played on
    the platform you asked about, which is a legitimate, expected answer.
    """


class RiotRateLimited(RiotApiError):
    """429. Carries the server-supplied cooldown so callers can surface it."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float,
        scope: str = "application",
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after
        self.scope = scope


class RiotUnavailable(RiotApiError):
    """5xx, or a transport failure that survived every retry."""


class RiotGone(RiotApiError):
    """The endpoint itself has been withdrawn by Riot.

    Spectator-V5 is the live case: Riot announced its deactivation in October
    2025 alongside the in-client anonymity options. Features built on it must
    degrade rather than break.
    """
