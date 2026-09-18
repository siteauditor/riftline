"""Players we already hold, for the search box.

Its own router rather than a path under ``/api/summoner``, whose routes all take
``/{platform}/{name}/{tag}`` and resolve one account through Riot. This one
never calls Riot: see ``services.suggest`` for why it cannot afford to.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import DbDep, StaticDep
from app.riot.routing import resolve_platform
from app.services.suggest import MAX_SUGGESTIONS, load_index

router = APIRouter(prefix="/api/players", tags=["players"])


class PlayerSuggestion(BaseModel):
    riot_id: str
    game_name: str
    tag_line: str
    platform: str
    platform_label: str
    profile_icon_url: str | None = None
    summoner_level: int | None = None
    # Solo queue, as stored. Null when we hold no solo entry, which is not a
    # claim that the player is unranked, so the UI shows nothing rather than
    # "Unranked".
    tier: str | None = None
    division: str | None = None
    league_points: int | None = None


class SuggestResponse(BaseModel):
    query: str
    players: list[PlayerSuggestion] = Field(default_factory=list)


@router.get("/suggest", response_model=SuggestResponse)
async def suggest_players(
    db: DbDep,
    sd: StaticDep,
    q: str = Query("", max_length=64, description="Name, or Name#TAG with a partial tag."),
    platform: str | None = Query(None, description="Region to rank first, e.g. euw1."),
    limit: int = Query(MAX_SUGGESTIONS, ge=1, le=20),
) -> SuggestResponse:
    """Riot IDs we already hold that start with what was typed."""
    preferred = resolve_platform(platform).id if platform else None
    index = await load_index(db)
    return SuggestResponse(
        query=q,
        players=[
            PlayerSuggestion(
                riot_id=f"{p.game_name}#{p.tag_line}",
                game_name=p.game_name,
                tag_line=p.tag_line,
                platform=p.platform,
                platform_label=p.platform_label,
                profile_icon_url=sd.profile_icon(p.profile_icon_id),
                summoner_level=p.summoner_level,
                tier=p.tier,
                division=p.division,
                league_points=p.league_points,
            )
            for p in index.suggest(q, preferred, limit)
        ],
    )
