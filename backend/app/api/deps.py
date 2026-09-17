"""FastAPI dependencies.

The Riot client and its rate limiter are process-wide singletons held on
``app.state``. That is not incidental: the limiter only works if every request
in the process shares one budget, so handing out per-request clients would
silently let us blow through the key's limits.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import SessionLocal
from app.riot.client import RiotClient
from app.services.ladders import LadderService
from app.services.live import LiveGameService
from app.services.matches import MatchService
from app.services.players import PlayerService
from app.services.static_data import StaticDataService, static_data


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_riot(request: Request) -> RiotClient:
    return request.app.state.riot


async def get_static() -> StaticDataService:
    # Cheap when warm; refreshes itself once the TTL lapses.
    await static_data.ensure_loaded()
    return static_data


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RiotDep = Annotated[RiotClient, Depends(get_riot)]
StaticDep = Annotated[StaticDataService, Depends(get_static)]


def get_player_service(db: DbDep, riot: RiotDep, settings: SettingsDep) -> PlayerService:
    return PlayerService(db, riot, settings)


def get_match_service(db: DbDep, riot: RiotDep, settings: SettingsDep) -> MatchService:
    return MatchService(db, riot, settings)


def get_live_service(db: DbDep, riot: RiotDep, settings: SettingsDep) -> LiveGameService:
    return LiveGameService(db, riot, settings)


def get_ladder_service(db: DbDep, riot: RiotDep, settings: SettingsDep) -> LadderService:
    return LadderService(db, riot, settings)


PlayerServiceDep = Annotated[PlayerService, Depends(get_player_service)]
MatchServiceDep = Annotated[MatchService, Depends(get_match_service)]
LiveServiceDep = Annotated[LiveGameService, Depends(get_live_service)]
LadderServiceDep = Annotated[LadderService, Depends(get_ladder_service)]
