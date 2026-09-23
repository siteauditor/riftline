"""How the site's own numbers are made, and how well they hold up.

One endpoint for the method page: the Riftline score's weights and its audit,
the win-chance model's features, accuracy and calibration, the death review's
rules and the rates they produce, and the lane labels' cut points. Everything
here is read from storage; nothing calls Riot.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbDep
from app.api.schemas import PublishedComponentOut
from app.db.models import ModelReport, ParticipantReview
from app.services import audit, lanes, reviews, winchance
from app.services.scores import (
    COMPONENT_LABELS,
    COMPONENTS,
    MIN_GAMES_FOR_SCORE,
    WEIGHTS,
    WEIGHTS_VERSION,
)

router = APIRouter(prefix="/api/method", tags=["method"])


class AuditDecileOut(BaseModel):
    low: float
    high: float
    win_rate: float
    games: int


class AuditFittedOut(BaseModel):
    per_ten_points: dict[str, float] = Field(default_factory=dict)
    normalised: dict[str, float] = Field(default_factory=dict)


class AuditRoleOut(BaseModel):
    position: str
    players: int
    winners_mean: float
    losers_mean: float
    auc: float | None = None
    deciles: list[AuditDecileOut] = Field(default_factory=list)
    components: dict[str, float | None] = Field(default_factory=dict)
    set_weights: dict[str, float] = Field(default_factory=dict)
    fitted: AuditFittedOut = Field(default_factory=AuditFittedOut)
    correlation: dict[str, dict[str, float]] = Field(default_factory=dict)


class AuditOverallOut(BaseModel):
    winners_mean: float | None = None
    losers_mean: float | None = None
    auc: float | None = None
    top_on_winning_team: float | None = None
    bottom_on_losing_team: float | None = None


class ScoreAuditOut(BaseModel):
    """The nightly audit of the score against wins, as `scripts.ingest audit`
    stores it. Typed here rather than passed through as a dict, so the page
    that reads it compiles against the same shape."""

    weights_version: int
    queue_id: int
    games: int
    players: int
    overall: AuditOverallOut
    roles: list[AuditRoleOut] = Field(default_factory=list)


class ScoreMethod(BaseModel):
    version: int
    components: list[PublishedComponentOut]
    weights: dict[str, dict[str, float]]
    min_games: int
    # The latest audit, or null before the first one ran.
    audit: ScoreAuditOut | None = None
    audited_at: str | None = None


class WinFeatureOut(BaseModel):
    id: str
    label: str
    unit: str


class WinEffectOut(BaseModel):
    feature: str
    label: str
    unit: str
    # Points of win chance at each minute, keyed by the minute as text. Null
    # where the training games never had the feature at that time.
    points: dict[str, float | None] = Field(default_factory=dict)


class CvOverallOut(BaseModel):
    rows: int
    accuracy: float
    brier: float
    log_loss: float
    baseline_brier: float
    skill: float


class CvPhaseOut(BaseModel):
    label: str
    rows: int
    accuracy: float
    brier: float
    log_loss: float


class ReliabilityBinOut(BaseModel):
    low: float
    high: float
    predicted: float
    observed: float
    rows: int


class CrossValidationOut(BaseModel):
    folds: int | None = None
    overall: CvOverallOut | None = None
    phases: list[CvPhaseOut] = Field(default_factory=list)
    reliability: list[ReliabilityBinOut] = Field(default_factory=list)
    ece: float | None = None
    blue_win_rate: float | None = None


class WinGateOut(BaseModel):
    min_games: int | None = None
    min_skill: float | None = None
    max_ece: float | None = None


class WinModelMethod(BaseModel):
    version: int
    published: bool
    withheld: str | None = None
    trained_games: int = 0
    trained_rows: int = 0
    patches: list[str] = Field(default_factory=list)
    queue_id: int
    applies_to: list[int] = Field(default_factory=list)
    features: list[WinFeatureOut] = Field(default_factory=list)
    # Points of win chance for one unit of each feature, from an even game.
    effects: list[WinEffectOut] = Field(default_factory=list)
    cv: CrossValidationOut = Field(default_factory=CrossValidationOut)
    gate: WinGateOut = Field(default_factory=WinGateOut)
    trained_at: str | None = None


class ReviewMetricMethodOut(BaseModel):
    id: str
    label: str
    measures: str
    lower_is_better: bool


class ReviewMethod(BaseModel):
    trade_seconds: int
    trade_kinds: list[str]
    convert_kinds: list[str]
    min_profile_games: int
    metrics: list[ReviewMetricMethodOut]
    # What the rules produce on our ranked games.
    games: int = 0
    deaths: int = 0
    traded: int = 0
    takedowns: int = 0
    converted: int = 0
    contests: int = 0
    contests_won: int = 0


class LaneMethod(BaseModel):
    even_below: float
    big_from: float
    labels: dict[str, str]
    min_games: int


class MethodResponse(BaseModel):
    score: ScoreMethod
    win_model: WinModelMethod | None = None
    review: ReviewMethod
    lanes: LaneMethod


@router.get("", response_model=MethodResponse)
async def get_method(db: DbDep) -> MethodResponse:
    reports = {
        r.kind: r
        for r in (
            await db.execute(
                select(ModelReport).where(ModelReport.kind.in_((audit.KIND, winchance.KIND)))
            )
        ).scalars()
    }

    audit_row = reports.get(audit.KIND)
    score = ScoreMethod(
        version=WEIGHTS_VERSION,
        components=[
            PublishedComponentOut(id=c, label=COMPONENT_LABELS[c][0], measures=COMPONENT_LABELS[c][1])
            for c in COMPONENTS
        ],
        weights=WEIGHTS,
        min_games=MIN_GAMES_FOR_SCORE,
        # An audit of older weights describes a score the site no longer shows.
        audit=audit_row.payload if audit_row and audit_row.version == WEIGHTS_VERSION else None,
        audited_at=audit_row.computed_at.isoformat() if audit_row else None,
    )

    model_row = reports.get(winchance.KIND)
    win_model = None
    if model_row is not None:
        payload = model_row.payload or {}
        win_model = WinModelMethod(
            version=model_row.version,
            published=bool(payload.get("published")),
            withheld=payload.get("withheld"),
            trained_games=payload.get("trained_games", 0),
            trained_rows=payload.get("trained_rows", 0),
            patches=payload.get("patches", []),
            queue_id=payload.get("queue_id", winchance.TRAIN_QUEUE),
            applies_to=payload.get("applies_to", list(winchance.MODEL_QUEUES)),
            features=[
                {"id": f, "label": winchance.FEATURE_LABELS[f][0], "unit": winchance.FEATURE_LABELS[f][1]}
                for f in winchance.FEATURES
            ],
            effects=payload.get("effects", []),
            cv=payload.get("cv", {}),
            gate=payload.get("gate", {}),
            trained_at=model_row.computed_at.isoformat() if model_row.computed_at else None,
        )

    totals = (
        await db.execute(
            select(
                func.count(func.distinct(ParticipantReview.match_id)),
                func.coalesce(func.sum(ParticipantReview.deaths), 0),
                func.coalesce(func.sum(ParticipantReview.untraded), 0),
                func.coalesce(func.sum(ParticipantReview.takedowns), 0),
                func.coalesce(func.sum(ParticipantReview.converted), 0),
                func.coalesce(func.sum(ParticipantReview.contests), 0),
                func.coalesce(func.sum(ParticipantReview.contests_won), 0),
            ).where(ParticipantReview.queue_id == winchance.TRAIN_QUEUE)
        )
    ).one()
    games, deaths, untraded, takedowns, converted, contests, contests_won = (int(v) for v in totals)
    review = ReviewMethod(
        trade_seconds=reviews.TRADE_MS // 1000,
        trade_kinds=sorted(reviews.TRADE_KINDS),
        convert_kinds=sorted(reviews.CONVERT_KINDS),
        min_profile_games=reviews.MIN_PROFILE_GAMES,
        metrics=[
            {
                "id": m,
                "label": reviews.METRIC_LABELS[m][0],
                "measures": reviews.METRIC_LABELS[m][1],
                "lower_is_better": m in reviews.LOWER_IS_BETTER,
            }
            for m in reviews.REVIEW_METRICS
        ],
        games=games,
        deaths=deaths,
        traded=deaths - untraded,
        takedowns=takedowns,
        converted=converted,
        contests=contests,
        contests_won=contests_won,
    )

    return MethodResponse(
        score=score,
        win_model=win_model,
        review=review,
        lanes=LaneMethod(
            even_below=lanes.EVEN_BELOW,
            big_from=lanes.BIG_FROM,
            labels=lanes.LABELS,
            min_games=MIN_GAMES_FOR_SCORE,
        ),
    )
