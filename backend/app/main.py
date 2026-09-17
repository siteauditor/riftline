"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.routes import champions as champion_routes
from app.api.routes import draft as draft_routes
from app.api.routes import leaderboard as leaderboard_routes
from app.api.routes import matches as match_routes
from app.api.routes import meta as meta_routes
from app.api.routes import static_data as static_routes
from app.api.routes import summoner as summoner_routes
from app.api.schemas import HealthResponse
from app.config import get_settings
from app.db.base import init_db
from app.riot.client import RiotClient
from app.riot.errors import (
    RiotApiError,
    RiotForbidden,
    RiotGone,
    RiotNotFound,
    RiotRateLimited,
    RiotUnauthorized,
    RiotUnavailable,
)
from app.riot.limiter import RateLimiter
from app.riot.routing import UnknownPlatform
from app.services.players import PlayerNotFound
from app.services.static_data import static_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()

    # One client, one limiter, for the whole process. See app/api/deps.py.
    app.state.riot = RiotClient(
        settings.riot_api_key,
        limiter=RateLimiter(settings.parsed_rate_limits),
        timeout=settings.riot_timeout_seconds,
        max_retries=settings.riot_max_retries,
    )

    if not settings.has_key:
        log.warning(
            "RIOT_API_KEY is not set. Static data works, but every player lookup "
            "will fail. Put a key in backend/.env and restart."
        )

    try:
        await static_data.ensure_loaded()
    except Exception as exc:  # noqa: BLE001 -- never block startup on a CDN
        log.warning("Static data unavailable at startup: %s", exc)

    try:
        yield
    finally:
        await app.state.riot.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LoL Analytics API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- error translation -------------------------------------------------
    # Riot's failure modes are turned into honest HTTP status codes here, once,
    # so no route has to wrap its calls in try/except.

    def problem(status: int, detail: str, **extra) -> ORJSONResponse:
        return ORJSONResponse({"detail": detail, **extra}, status_code=status)

    @app.exception_handler(PlayerNotFound)
    async def _player_not_found(_: Request, exc: PlayerNotFound):
        return problem(404, str(exc))

    @app.exception_handler(UnknownPlatform)
    async def _bad_platform(_: Request, exc: UnknownPlatform):
        return problem(400, str(exc))

    @app.exception_handler(RiotNotFound)
    async def _riot_not_found(_: Request, exc: RiotNotFound):
        return problem(404, "Not found on this platform.")

    @app.exception_handler(RiotForbidden)
    async def _riot_forbidden(_: Request, exc: RiotForbidden):
        # 403, not 503: the key works, this endpoint does not. Sending the
        # expired-key hint here would have people regenerating a fine key.
        return problem(403, exc.message, hint="endpoint_unavailable")

    @app.exception_handler(RiotUnauthorized)
    async def _riot_unauthorized(_: Request, exc: RiotUnauthorized):
        # 503, not 401: the caller did nothing wrong, our key is the problem.
        return problem(503, exc.message, hint="expired_api_key")

    @app.exception_handler(RiotRateLimited)
    async def _riot_rate_limited(_: Request, exc: RiotRateLimited):
        response = problem(
            429,
            "Riot rate limit reached. This is expected on a development key "
            "(100 requests per 2 minutes).",
            retry_after=exc.retry_after,
            scope=exc.scope,
        )
        response.headers["Retry-After"] = str(int(exc.retry_after) or 1)
        return response

    @app.exception_handler(RiotGone)
    async def _riot_gone(_: Request, exc: RiotGone):
        return problem(410, exc.message)

    @app.exception_handler(RiotUnavailable)
    async def _riot_unavailable(_: Request, exc: RiotUnavailable):
        return problem(502, "Riot's API is not responding right now.")

    @app.exception_handler(RiotApiError)
    async def _riot_error(_: Request, exc: RiotApiError):
        return problem(502, exc.message)

    # --- routes ------------------------------------------------------------
    app.include_router(summoner_routes.router)
    app.include_router(static_routes.router)
    app.include_router(meta_routes.router)
    app.include_router(champion_routes.router)
    app.include_router(draft_routes.router)
    app.include_router(leaderboard_routes.router)
    app.include_router(match_routes.router)

    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok",
            riot_key_configured=settings.has_key,
            static_data_version=static_data.version,
            rate_limit=request.app.state.riot.limiter.snapshot(),
            spectator_enabled=settings.enable_spectator,
        )

    return app


app = create_app()
