"""One stored match, in full, and its story.

Match history serves twenty rows at a time and each row shows one player's
game. This serves the other nine: the whole scoreboard, the objectives both
teams took, and the model behind every Riftline score on it.

Its own endpoint on purpose. Folding this into `MatchHistoryResponse` would put
ten players times twenty matches of items, wards and damage on the wire every
time someone scrolls, to render a panel most of them never open.

The scoreboard calls no Riot endpoint. A match we do not hold is a 404, not a
fetch: the history endpoint is what puts matches in storage, and it is always
the page you arrived from. The story is the one exception: it needs the game's
timeline, which profile games only get at the nightly run, so opening a story
without one fetches it, once, and keeps it.
"""

from __future__ import annotations

import gzip
import json

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbDep, RiotDep, SettingsDep, StaticDep
from app.api.schemas import ChampionRef, MatchDetailResponse, to_match_detail
from app.db.models import Match, MatchTimeline, ParticipantReview
from app.riot.errors import RiotRateLimited
from app.services.lanes import lane_labeler
from app.services.reviews import PlayerReview, described, review_game, sides_of, store_reviews
from app.services.timelines import EXTRACT_VERSION, TimelineService, extract
from app.services.winchance import MODEL_QUEUES, TRAIN_QUEUE, current_model, evaluate, moments

router = APIRouter(prefix="/api/matches", tags=["matches"])

MatchId = Path(
    description="Riot match id, which carries its own platform: EUW1_7986353741.",
    min_length=6,
    max_length=32,
)


async def _load(db, match_id: str) -> Match:
    match = (
        await db.execute(
            select(Match)
            .where(Match.match_id == match_id.upper())
            .options(selectinload(Match.participants))
        )
    ).scalars().first()
    if match is None:
        raise HTTPException(
            404,
            f"{match_id} is not in storage. Open the player's match history first: "
            "that is what fetches a match from Riot.",
        )
    return match


@router.get("/{match_id}", response_model=MatchDetailResponse)
async def get_match(db: DbDep, sd: StaticDep, match_id: str = MatchId) -> MatchDetailResponse:
    """The full scoreboard for a match we already hold."""
    match = await _load(db, match_id)
    return to_match_detail(match, sd, lanes=await lane_labeler(db))


# ------------------------------------------------------------------- story


class CurvePoint(BaseModel):
    ms: int
    # Blue's chance to win, 0 to 1. The page flips it for red.
    blue: float
    # A minute frame rather than an event. Frames are a minute apart but not on
    # the minute (one stored game's fifth sits at 300,146 ms), so the page
    # cannot find them by their time.
    frame: bool = False


class MomentOut(BaseModel):
    start_ms: int
    end_ms: int
    # Blue's chance after minus before, -1 to 1.
    swing: float
    # The side it went for: 100 blue, 200 red.
    team: int
    text: str


class StoryPlayerRef(BaseModel):
    participant_index: int
    champion: ChampionRef


class DeathOut(BaseModel):
    ms: int
    killer: StoryPlayerRef | None = None
    assisters: int = 0
    x: int = 0
    y: int = 0
    traded: bool
    # Win chance, 0 to 1, the death took. Null without a published model.
    cost: float | None = None


class TakedownOut(BaseModel):
    ms: int
    victim: StoryPlayerRef | None = None
    killed: bool
    converted: bool
    gain: float | None = None


class PlayerStoryOut(BaseModel):
    participant_index: int
    puuid: str
    team_id: int
    riot_id: str | None = None
    champion: ChampionRef
    position: str | None = None
    deaths: int = 0
    untraded: int = 0
    win_lost: float | None = None
    takedowns: int = 0
    converted: int = 0
    win_gained: float | None = None
    contests: int = 0
    contests_won: int = 0
    death_list: list[DeathOut] = Field(default_factory=list)
    takedown_list: list[TakedownOut] = Field(default_factory=list)


class StoryModelOut(BaseModel):
    version: int
    published: bool
    # Why the curve is not shown, when it is not.
    withheld: str | None = None
    trained_games: int = 0
    trained_queue: int = TRAIN_QUEUE
    accuracy: float | None = None
    phases: list[dict] = Field(default_factory=list)


class GameStoryResponse(BaseModel):
    match_id: str
    available: bool
    # True when Riot's rate limit kept the timeline from being fetched just
    # now; the page offers to try again after `retry_after` seconds.
    pending: bool = False
    retry_after: float | None = None
    reason: str | None = None
    queue_id: int | None = None
    duration_ms: int = 0
    blue_won: bool | None = None
    curve: list[CurvePoint] = Field(default_factory=list)
    moments: list[MomentOut] = Field(default_factory=list)
    players: list[PlayerStoryOut] = Field(default_factory=list)
    model: StoryModelOut | None = None
    # Data Dragon's Summoner's Rift minimap, for the death map.
    map_url: str | None = None


def _unavailable(match: Match, reason: str) -> GameStoryResponse:
    return GameStoryResponse(
        match_id=match.match_id, available=False, reason=reason, queue_id=match.queue_id
    )


@router.get("/{match_id}/story", response_model=GameStoryResponse)
async def get_story(
    db: DbDep,
    sd: StaticDep,
    riot: RiotDep,
    settings: SettingsDep,
    match_id: str = MatchId,
) -> GameStoryResponse:
    """Each team's chance to win over the game, the moments that decided it,
    and every player's deaths and takedowns weighed.

    Fetches the game's timeline from Riot if we do not hold it: one call, once.
    """
    match = await _load(db, match_id)
    if match.is_remake:
        return _unavailable(match, "A remake has no story to tell.")
    if match.queue_id not in MODEL_QUEUES:
        return _unavailable(
            match,
            "The win-chance model is trained on ranked Summoner's Rift games, and "
            "this game is from another queue.",
        )

    timeline = await db.get(MatchTimeline, match.match_id)
    if timeline is None:
        try:
            timeline = await TimelineService(db, riot, settings).ensure_one(match)
        except RiotRateLimited as exc:
            return GameStoryResponse(
                match_id=match.match_id,
                available=False,
                pending=True,
                retry_after=round(exc.retry_after, 1),
                reason="Riot's rate limit is busy, so this game's timeline could not be fetched yet.",
                queue_id=match.queue_id,
            )
        if timeline is None:
            return _unavailable(match, "Riot no longer keeps this game's timeline.")
        # Storing the timeline wrote the laning and build columns and
        # committed, which expired the loaded rows.
        match = await _load(db, match.match_id)

    extracted = timeline.extracted or {}
    if (extracted.get("v") or 0) < EXTRACT_VERSION and timeline.raw_gz:
        # Older than the fields a story reads: bring this one up to date now
        # rather than waiting for the nightly re-extraction.
        extracted = extract(json.loads(gzip.decompress(timeline.raw_gz)), match.game_duration or 0)
        timeline.extracted = extracted
        await db.commit()
        match = await _load(db, match.match_id)
    if not extracted.get("tf"):
        return _unavailable(match, "This game's timeline has no frames to read.")

    model = await current_model(db)
    published = model is not None and model.published
    story = evaluate(extracted, model) if published else None
    reviews = review_game(extracted, story.effects if story else None, sides_of(match))

    if published:
        stored = (
            await db.execute(
                select(ParticipantReview.model_version).where(
                    ParticipantReview.match_id == match.match_id
                )
            )
        ).scalars().all()
        if not stored or any(v != model.version for v in stored):
            await store_reviews(db, match, reviews, model.version)
            await db.commit()
            match = await _load(db, match.match_id)

    by_index = {p.participant_index: p for p in match.participants}

    def ref(index: int) -> StoryPlayerRef | None:
        player = by_index.get(index)
        if player is None:
            return None
        return StoryPlayerRef(
            participant_index=index,
            champion=ChampionRef(
                id=player.champion_id,
                name=sd.champion_name(player.champion_id),
                icon_url=sd.champion_icon(player.champion_id),
            ),
        )

    players = []
    for p in sorted(match.participants, key=lambda p: p.participant_index):
        review = reviews.get(p.participant_index) or PlayerReview(p.participant_index)
        summary = described(review)
        players.append(PlayerStoryOut(
            participant_index=p.participant_index,
            puuid=p.puuid,
            team_id=p.team_id,
            riot_id=(
                f"{p.riot_id_game_name}#{p.riot_id_tagline}"
                if p.riot_id_game_name and p.riot_id_tagline else None
            ),
            champion=ChampionRef(
                id=p.champion_id,
                name=sd.champion_name(p.champion_id),
                icon_url=sd.champion_icon(p.champion_id),
            ),
            position=p.team_position,
            deaths=summary["deaths"],
            untraded=summary["untraded"],
            win_lost=summary["win_lost"] if published else None,
            takedowns=summary["takedowns"],
            converted=summary["converted"],
            win_gained=summary["win_gained"] if published else None,
            contests=summary["contests"],
            contests_won=summary["contests_won"],
            death_list=[
                DeathOut(
                    ms=d.ms, killer=ref(d.killer), assisters=d.assisters, x=d.x, y=d.y,
                    traded=d.traded, cost=round(d.cost, 4) if d.cost is not None else None,
                )
                for d in review.deaths
            ],
            takedown_list=[
                TakedownOut(
                    ms=t.ms, victim=ref(t.victim), killed=t.killed, converted=t.converted,
                    gain=round(t.gain, 4) if t.gain is not None else None,
                )
                for t in review.takedowns
            ],
        ))

    blue_won = next((p.win for p in match.participants if p.team_id == 100), None)
    model_out = None
    if model is not None:
        cv = (model.payload or {}).get("cv") or {}
        model_out = StoryModelOut(
            version=model.version,
            published=published,
            withheld=model.withheld,
            trained_games=(model.payload or {}).get("trained_games", 0),
            accuracy=(cv.get("overall") or {}).get("accuracy"),
            phases=[{"label": ph["label"], "accuracy": ph["accuracy"]} for ph in cv.get("phases", [])],
        )

    return GameStoryResponse(
        match_id=match.match_id,
        available=True,
        reason=None if published else (
            "No win-chance model yet." if model is None
            else f"The win-chance model is withheld: {model.withheld}."
        ),
        queue_id=match.queue_id,
        duration_ms=(match.game_duration or 0) * 1000,
        blue_won=blue_won,
        curve=[
            CurvePoint(ms=ms, blue=round(p, 4), frame=frame) for ms, p, frame in story.curve
        ] if story else [],
        moments=[
            MomentOut(
                start_ms=m.start_ms, end_ms=m.end_ms, swing=round(m.swing, 4),
                team=100 if m.swing > 0 else 200, text=m.text,
            )
            for m in moments(story.sequences)
        ] if story else [],
        players=players,
        model=model_out,
        map_url=f"{sd.cdn}/img/map/map11.png" if sd.version else None,
    )
