"""Draft assistant endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PlayerServiceDep, StaticDep
from app.api.schemas import ChampionRef
from app.riot.errors import RiotApiError
from app.riot.routing import UnknownPlatform
from app.services.aggregate import ALL_BRACKETS, available_slices
from app.services.draft import DraftAdvisor, DraftContext
from app.services.players import PlayerNotFound

router = APIRouter(prefix="/api/draft", tags=["draft"])

POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


class DraftRequest(BaseModel):
    position: str = Field(description="The role you are picking for.")
    allies: list[int] = Field(default_factory=list, description="Champion ids already on your team.")
    enemies: list[int] = Field(default_factory=list)
    bans: list[int] = Field(default_factory=list)
    enemy_laner: int | None = Field(
        default=None, description="The enemy champion in your lane, when known."
    )
    patch: str | None = None
    queue_id: int = 420
    rank_bracket: str = Field(
        default=ALL_BRACKETS, description="Crawl provenance, not a measured rank."
    )
    min_games: int = 20
    # Optional: weight suggestions toward champions this player actually knows.
    platform: str | None = None
    game_name: str | None = None
    tag_line: str | None = None
    comfort_weight: float = Field(default=0.15, ge=0.0, le=1.0)


class SuggestionOut(BaseModel):
    champion: ChampionRef
    score: float
    base_win_rate: float
    adjusted_win_rate: float
    games: int
    matchup_win_rate: float | None = None
    matchup_games: int = 0
    mastery_points: int = 0
    comfort: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class DraftResponse(BaseModel):
    patch: str
    position: str
    enemy_laner: ChampionRef | None = None
    personalised: bool = False
    suggestions: list[SuggestionOut] = Field(default_factory=list)


@router.post("/suggest", response_model=DraftResponse)
async def suggest(
    body: DraftRequest,
    db: DbDep,
    sd: StaticDep,
    players: PlayerServiceDep,
) -> DraftResponse:
    """Rank the champions worth picking, with the reasoning attached."""
    position = body.position.upper()
    if position not in POSITIONS:
        raise HTTPException(400, f"position must be one of {', '.join(POSITIONS)}")

    patch = body.patch
    if patch is None:
        slices = [s for s in await available_slices(db) if s["queue_id"] == body.queue_id]
        if not slices:
            raise HTTPException(
                404,
                "No aggregated data yet. Run `python -m scripts.ingest crawl` then "
                "`python -m scripts.ingest aggregate` to build the corpus this uses.",
            )
        patch = slices[0]["patch"]

    # Personalisation is optional and must never break the core suggestion.
    puuid = None
    if body.platform and body.game_name and body.tag_line:
        try:
            player = await players.resolve(body.platform, body.game_name, body.tag_line)
            await players.masteries(player, body.platform)
            puuid = player.puuid
        except (PlayerNotFound, UnknownPlatform, RiotApiError):
            # Personalisation is a bonus. A bad Riot ID, an expired key or a
            # rate limit should cost you the mastery weighting, not the advice.
            puuid = None

    ctx = DraftContext(
        position=position,
        patch=patch,
        queue_id=body.queue_id,
        rank_bracket=(body.rank_bracket or ALL_BRACKETS).upper(),
        allies=body.allies,
        enemies=body.enemies,
        bans=body.bans,
        enemy_laner=body.enemy_laner,
        puuid=puuid,
        comfort_weight=body.comfort_weight,
        min_games=body.min_games,
    )

    suggestions = await DraftAdvisor(db).suggest(ctx)
    if not suggestions:
        raise HTTPException(
            404,
            f"No champion has {body.min_games}+ games at {position} on patch {patch}. "
            "Ingest more matches or lower min_games.",
        )

    return DraftResponse(
        patch=patch,
        position=position,
        enemy_laner=(
            ChampionRef(
                id=body.enemy_laner,
                name=sd.champion_name(body.enemy_laner),
                icon_url=sd.champion_icon(body.enemy_laner),
            )
            if body.enemy_laner
            else None
        ),
        personalised=puuid is not None,
        suggestions=[
            SuggestionOut(
                champion=ChampionRef(
                    id=s.champion_id,
                    name=sd.champion_name(s.champion_id),
                    icon_url=sd.champion_icon(s.champion_id),
                ),
                score=s.score,
                base_win_rate=s.base_win_rate,
                adjusted_win_rate=s.adjusted_win_rate,
                games=s.games,
                matchup_win_rate=s.matchup_win_rate,
                matchup_games=s.matchup_games,
                mastery_points=s.mastery_points,
                comfort=s.comfort,
                reasons=s.reasons,
            )
            for s in suggestions
        ],
    )
