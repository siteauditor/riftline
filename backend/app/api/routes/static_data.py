"""Static game data: champions, queues, patch version.

Served from our own process so the frontend makes one call instead of parsing
Data Dragon's 400KB champion blob in the browser.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StaticDep
from app.api.schemas import ChampionRef

router = APIRouter(prefix="/api/static", tags=["static"])


@router.get("/version")
async def get_version(sd: StaticDep) -> dict:
    return {"version": sd.version, "cdn": sd.cdn}


@router.get("/champions")
async def get_champions(sd: StaticDep) -> dict:
    """Every champion, with the icon URL already resolved."""
    return {
        "version": sd.version,
        "champions": [
            {
                **ChampionRef(
                    id=c.id, name=c.name, icon_url=sd.champion_icon(c.id)
                ).model_dump(),
                "key": c.key,
                "title": c.title,
                "tags": c.tags,
                "splash_url": sd.champion_splash(c.id),
                "art_url": sd.champion_art(c.id),
                "tile_url": sd.champion_tile(c.id),
            }
            for c in sd.all_champions()
        ],
    }


@router.get("/queues")
async def get_queues(sd: StaticDep) -> dict:
    """Queues worth offering as a filter, in the order players expect them."""
    featured = [420, 440, 400, 430, 490, 450, 1700, 900]
    return {
        "queues": [
            {"id": q, "name": sd.queue_name(q)}
            for q in featured
            if q in sd.queues or q in (420, 440, 450)
        ]
    }
