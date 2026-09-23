"""Draft assistant endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, PlayerServiceDep, StaticDep
from app.api.schemas import ChampionRef
from app.db.models import ChampionMastery, ChampionStat
from app.riot.errors import RiotApiError
from app.riot.routing import UnknownPlatform, resolve_platform
from app.services.aggregate import (
    ALL_BRACKETS,
    aggregated_slices,
    available_brackets,
    default_patch,
)
from app.services.draft import (
    ALLY_SHRINKAGE,
    COMFORT_MAX_BONUS,
    CONTEXT_LIFT_CAP,
    MATCHUP_SHRINKAGE,
    TEAM_SHRINKAGE,
    DraftAdvisor,
    DraftContext,
)
from app.services.players import PlayerNotFound, PlayerService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/draft", tags=["draft"])

# How long the board waits for Riot to say who the Riot ID is and what they
# play. The limiter lets a web request wait up to 40 seconds for a slot, and
# the nightly crawl shares the key, so without this a draft could hang for as
# long as the crawl held the key. Mastery is a preference: past two seconds
# the board answers without it, or with what is stored.
PERSONALISE_BUDGET_SECONDS = 2.0

PersonalisationStatus = Literal["off", "used", "stale", "not_found", "busy", "no_mastery"]


Position = Literal["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

# A draft has four other picks on your side, five on theirs and at most ten
# bans. Past that the board is not a draft, and every id is a parameter in an
# IN clause: a 3,000-champion enemy list was accepted and answered with a
# misleading "no champion has 20+ games" (seen 2026-09-24).
MAX_ALLIES = 4
MAX_ENEMIES = 5
MAX_BANS = 10


class DraftRequest(BaseModel):
    position: Position = Field(description="The role you are picking for, in any case.")
    allies: list[int] = Field(
        default_factory=list, max_length=MAX_ALLIES,
        description="Champion ids already on your team.",
    )
    enemies: list[int] = Field(default_factory=list, max_length=MAX_ENEMIES)
    bans: list[int] = Field(default_factory=list, max_length=MAX_BANS)
    enemy_laner: int | None = Field(
        default=None, description="The enemy champion in your lane, one of `enemies`."
    )
    # Letters, digits and dots, as long as the column: a patch is "16.18", and the
    # tests' fixture patches are "D9.00" so they never become the newest held.
    patch: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.]{1,12}$")
    queue_id: Literal[420, 440] = 420
    rank_bracket: str = Field(
        default=ALL_BRACKETS, description="Crawl provenance, not a measured rank."
    )
    min_games: int = Field(default=20, ge=1, le=500)
    # Optional: weight suggestions toward champions this player actually knows.
    platform: str | None = None
    game_name: str | None = None
    tag_line: str | None = None
    comfort_weight: float = Field(default=0.15, ge=0.0, le=1.0)

    _warnings: list[str] = PrivateAttr(default_factory=list)

    @field_validator("position", mode="before")
    @classmethod
    def _any_case(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _a_real_board(self) -> DraftRequest:
        # The same champion twice in one list is a double click, not a board
        # that cannot exist: kept once, and said so.
        for side in ("allies", "enemies", "bans"):
            ids = getattr(self, side)
            unique = list(dict.fromkeys(ids))
            if len(unique) != len(ids):
                self._warnings.append(f"{side}: repeated champions were counted once")
                setattr(self, side, unique)
        # One champion in two places is not a draft: a champion is picked by
        # one team and a ban removes it from both.
        seen: dict[int, str] = {}
        for side in ("allies", "enemies", "bans"):
            for champion_id in getattr(self, side):
                if champion_id in seen:
                    raise ValueError(
                        f"champion {champion_id} is in both {seen[champion_id]} and {side}"
                    )
                seen[champion_id] = side
        if self.enemy_laner is not None and self.enemy_laner not in self.enemies:
            raise ValueError("enemy_laner must be one of enemies")
        return self


class EvidenceOut(BaseModel):
    """One record behind a suggestion, with the sample it rests on."""

    # "lane", "enemy" or "ally".
    kind: str
    champion: ChampionRef
    games: int
    wins: int
    win_rate: float
    # What the record claims, and the part its own sample supports. The list is
    # ranked on the second one.
    lift: float
    credible_lift: float
    # Lane only, and only once enough of those games have a timeline.
    gold_diff_14: float | None = None
    laning_score: float | None = None
    timeline_games: int = 0


class SuggestionOut(BaseModel):
    champion: ChampionRef
    # Baseline plus what the board supports plus comfort: the sort key.
    score: float
    base_win_rate: float
    # Baseline plus everything the records claim, uncapped: "if they hold".
    adjusted_win_rate: float
    games: int
    matchup_win_rate: float | None = None
    matchup_games: int = 0
    mastery_points: int = 0
    comfort: float = 0.0
    # The two parts of the score that are not the baseline.
    context_lift: float = 0.0
    comfort_bonus: float = 0.0
    evidence: list[EvidenceOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class BanCandidateOut(BaseModel):
    champion: ChampionRef
    position: str
    base_win_rate: float
    games: int
    score: float
    reasons: list[str] = Field(default_factory=list)


class PersonalisationOut(BaseModel):
    """Whether the list was weighted by a player's mastery, and if not, why.

    ``off``: no Riot ID, or the mastery weight is off. ``used``: fresh mastery.
    ``stale``: Riot did not answer in time, so the mastery stored from an earlier
    lookup was used. ``not_found``: no such account (or a Riot ID that cannot
    exist, which is not asked about). ``busy``: Riot did not answer and nothing
    is stored. ``no_mastery``: the account has no champion mastery.
    """

    status: PersonalisationStatus
    # As Riot spells it once found, else as it was asked for.
    riot_id: str | None = None
    platform: str | None = None
    # Champions with mastery behind the weighting.
    champions: int = 0


class DraftModelOut(BaseModel):
    """The constants behind the score, so the page can state them."""

    comfort_weight: float
    comfort_max_bonus: float
    lane_shrinkage: float
    team_shrinkage: float
    ally_shrinkage: float
    context_lift_cap: float


class DraftResponse(BaseModel):
    patch: str
    position: str
    enemy_laner: ChampionRef | None = None
    allies: list[ChampionRef] = Field(default_factory=list)
    enemies: list[ChampionRef] = Field(default_factory=list)
    # Kept for one release, for pages loaded before `personalisation` existed.
    personalised: bool = False
    personalisation: PersonalisationOut = Field(
        default_factory=lambda: PersonalisationOut(status="off")
    )
    suggestions: list[SuggestionOut] = Field(default_factory=list)
    # Who to deny. False when no ally is locked in yet: then these are simply
    # the patch's strongest picks, which the page has to say rather than imply
    # it read the draft.
    bans_read_the_draft: bool = False
    ban_candidates: list[BanCandidateOut] = Field(default_factory=list)
    model: DraftModelOut
    # Why `suggestions` is empty, when it is: no champion has `min_games` in
    # this role on this patch. `most_games` is the most any champion has, so
    # the page can offer a floor that shows something.
    empty_reason: Literal["min_games"] | None = None
    most_games: int = 0
    # What the request asked that was quietly put right (a champion listed
    # twice on one side, counted once).
    warnings: list[str] = Field(default_factory=list)


async def _check_champions(
    body: DraftRequest, sd, db: AsyncSession, patch: str
) -> None:
    """422 for a champion id nobody plays.

    Known means in Riot's static data or in the rollups: a champion released
    after the static data was cached still counts once it has games. If the
    static data failed to load, the check is skipped rather than turning every
    request into a 422 while Data Dragon is down.
    """
    asked = [*body.allies, *body.enemies, *body.bans]
    if not asked:
        return
    known = {c.id for c in sd.all_champions()}
    if not known:
        return
    unknown = [c for c in asked if c not in known]
    if unknown:
        held = set(
            (
                await db.execute(
                    select(ChampionStat.champion_id)
                    .where(ChampionStat.patch == patch, ChampionStat.champion_id.in_(unknown))
                    .distinct()
                )
            ).scalars()
        )
        unknown = [c for c in unknown if c not in held]
    if unknown:
        raise HTTPException(422, f"Unknown champion id {unknown[0]}.")


async def _most_games(db: AsyncSession, ctx: DraftContext) -> int:
    """The most games any champion has in this role, slice and patch."""
    value = (
        await db.execute(
            select(func.max(ChampionStat.games)).where(
                ChampionStat.patch == ctx.patch,
                ChampionStat.queue_id == ctx.queue_id,
                ChampionStat.team_position == ctx.position,
                ChampionStat.rank_bracket == ctx.rank_bracket,
            )
        )
    ).scalar_one_or_none()
    return int(value or 0)


def _plausible_riot_id(name: str, tag: str) -> bool:
    """Whether a Riot ID could exist, before anybody asks Riot about it.

    Riot's tags are three to five letters or digits. The tag is the part people
    are still typing when a request goes out, and "Caps#E" was an account-v1
    call for an account that cannot exist. Names are only bounded above: a
    lower bound in characters is not the rule in every script.
    """
    return 1 <= len(name) <= 16 and 3 <= len(tag) <= 5 and tag.isalnum()


async def _mastery_count(db: AsyncSession, puuid: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(ChampionMastery)
            .where(ChampionMastery.puuid == puuid)
        )
    ).scalar_one()


async def _personalise(
    body: DraftRequest, players: PlayerService, db: AsyncSession
) -> tuple[str | None, PersonalisationOut]:
    """The puuid whose mastery weights the list, and what to tell the page.

    Personalisation is a bonus and must never cost the advice: a bad Riot ID,
    an expired key, a rate limit or a slow Riot answer each cost the mastery
    weighting only, and the page is told which of those it was.
    """
    if not (body.platform and body.game_name and body.tag_line) or body.comfort_weight <= 0:
        return None, PersonalisationOut(status="off")
    name = body.game_name.strip()
    tag = body.tag_line.strip().lstrip("#")
    missing = PersonalisationOut(status="not_found", riot_id=f"{name}#{tag}", platform=body.platform)
    try:
        platform = resolve_platform(body.platform)
    except UnknownPlatform:
        return None, missing
    missing.platform = platform.id
    if not _plausible_riot_id(name, tag):
        return None, missing

    try:
        async with asyncio.timeout(PERSONALISE_BUDGET_SECONDS):
            player = await players.resolve(platform.id, name, tag, remember_miss=True)
            # The home shard, as the mastery page reads it. champion-mastery-v4
            # answers 200 with an empty list on any other, so an OCE Riot ID
            # whose account is on SG2 came back "personalised" with no mastery
            # behind it, and stamped that empty answer as fresh.
            home = await players.effective_platform(player, platform)
            await players.masteries(player, home.id)
    except PlayerNotFound:
        return None, missing
    except (RiotApiError, TimeoutError):
        # The cancelled lookup may have stopped half way through a write.
        await db.rollback()
        try:
            stored = await players.resolve_stored(platform.id, name, tag)
        except PlayerNotFound:
            return None, missing.model_copy(update={"status": "busy"})
        count = await _mastery_count(db, stored.puuid)
        if not count:
            return None, missing.model_copy(update={"status": "busy"})
        return stored.puuid, PersonalisationOut(
            status="stale", riot_id=stored.riot_id, platform=platform.id, champions=count
        )

    count = await _mastery_count(db, player.puuid)
    return (player.puuid if count else None), PersonalisationOut(
        status="used" if count else "no_mastery",
        riot_id=player.riot_id,
        platform=home.id,
        champions=count,
    )


@router.post("/suggest", response_model=DraftResponse)
async def suggest(
    body: DraftRequest,
    db: DbDep,
    sd: StaticDep,
    players: PlayerServiceDep,
) -> DraftResponse:
    """Rank the champions worth picking, with the reasoning attached."""
    position = body.position
    bracket = (body.rank_bracket or ALL_BRACKETS).upper()
    if bracket != ALL_BRACKETS and bracket not in await available_brackets(db):
        raise HTTPException(422, f"No games are held for the bracket {body.rank_bracket}.")

    patch = body.patch
    if patch is None:
        patch = default_patch(await aggregated_slices(db), body.queue_id)
        if patch is None:
            # The ingest hint is for whoever runs the server, not for a player
            # reading the page.
            log.warning(
                "draft: nothing aggregated for queue %s; run `python -m scripts.ingest "
                "crawl` then `python -m scripts.ingest aggregate`", body.queue_id
            )
            raise HTTPException(404, "Riftline holds no ranked games for this queue yet.")

    await _check_champions(body, sd, db, patch)

    puuid, personalisation = await _personalise(body, players, db)

    ctx = DraftContext(
        position=position,
        patch=patch,
        queue_id=body.queue_id,
        rank_bracket=bracket,
        allies=body.allies,
        enemies=body.enemies,
        bans=body.bans,
        enemy_laner=body.enemy_laner,
        puuid=puuid,
        comfort_weight=body.comfort_weight,
        min_games=body.min_games,
    )

    advisor = DraftAdvisor(db)
    suggestions = await advisor.suggest(ctx)
    bans = await advisor.ban_candidates(ctx)
    # An empty list is an answer, not an error: the floor is set above what the
    # corpus holds for this role, and the page says so and offers a lower one.
    most_games = 0 if suggestions else await _most_games(db, ctx)

    def champion(champion_id: int) -> ChampionRef:
        return ChampionRef(
            id=champion_id,
            name=sd.champion_name(champion_id),
            icon_url=sd.champion_icon(champion_id),
        )

    return DraftResponse(
        patch=patch,
        position=position,
        enemy_laner=champion(body.enemy_laner) if body.enemy_laner else None,
        allies=[champion(c) for c in dict.fromkeys(body.allies)],
        enemies=[champion(c) for c in dict.fromkeys(body.enemies)],
        personalised=puuid is not None,
        personalisation=personalisation,
        suggestions=[
            SuggestionOut(
                champion=champion(s.champion_id),
                score=s.score,
                base_win_rate=s.base_win_rate,
                adjusted_win_rate=s.adjusted_win_rate,
                games=s.games,
                matchup_win_rate=s.matchup_win_rate,
                matchup_games=s.matchup_games,
                mastery_points=s.mastery_points,
                comfort=s.comfort,
                context_lift=s.context_lift,
                comfort_bonus=s.comfort_bonus,
                evidence=[
                    EvidenceOut(
                        kind=e.kind,
                        champion=champion(e.champion_id),
                        games=e.games,
                        wins=e.wins,
                        win_rate=e.win_rate,
                        lift=e.lift,
                        credible_lift=e.credible_lift,
                        gold_diff_14=e.gold_diff_14,
                        laning_score=e.laning_score,
                        timeline_games=e.timeline_games,
                    )
                    for e in s.evidence
                ],
                reasons=s.reasons,
            )
            for s in suggestions
        ],
        bans_read_the_draft=bool(body.allies),
        ban_candidates=[
            BanCandidateOut(
                champion=champion(c.champion_id),
                position=c.position,
                base_win_rate=c.base_win_rate,
                games=c.games,
                score=c.score,
                reasons=c.reasons,
            )
            for c in bans
        ],
        empty_reason=None if suggestions else "min_games",
        most_games=most_games,
        warnings=body._warnings,
        model=DraftModelOut(
            comfort_weight=body.comfort_weight,
            comfort_max_bonus=COMFORT_MAX_BONUS,
            lane_shrinkage=MATCHUP_SHRINKAGE,
            team_shrinkage=TEAM_SHRINKAGE,
            ally_shrinkage=ALLY_SHRINKAGE,
            context_lift_cap=CONTEXT_LIFT_CAP,
        ),
    )
