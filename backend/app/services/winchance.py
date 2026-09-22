"""The win-chance model: each team's chance to win, minute by minute.

Why it exists
-------------

OP.GG's timeline score and Mobalytics' GPI say how well someone played. Neither
says which moments decided a game, and neither publishes how it works. This
model is what lets a game's story name its turning points ("Red won a fight 3
for 1 and took Baron, +22 points"), and what the death review weighs every
death and takedown with.

How it works
------------

A logistic regression on the game state, blue minus red: gold, kills, towers,
inhibitors down, dragons, soul, Elder and Baron buffs, Voidgrubs, Herald,
Atakhan and levels. Each feature has two weights, its effect at minute 0 and
at minute 40, and between them the effect moves in a straight line with the
clock: a gold lead means something different at 8 minutes and at 35, and
separate models per phase would jump at their boundaries. That is 26 numbers,
all published on the method page.

Every feature's effect is held at zero or above: a lead never counts against
the team that holds it. Fitted freely, on 1,678 games, the model scored the
same but read a tower at 10 minutes as -2.9 points and a Baron buff at 20 as
-4.1, because a tower's worth is mostly its gold, which the gold feature
already counts, and Baron's early weight was extrapolated to minutes it never
happens. Those numbers are harmless to the curve and absurd as the effect of
an event, which is what the story shows.

Honesty
-------

The report is built from held-out predictions: five folds split by game, never
by row, because the minutes of one game are nearly copies of each other and a
game on both sides of a split would grade the model on its own homework. The
curve is shown only when the model beats a constant guess by a clear margin
and its calibration error is small. Otherwise the story page says the model is
not reliable enough yet, the way the site withholds a thin sample.

It is trained on our own games, which are mostly high-elo EUW ranked solo, and
it sees only the state above: not items, not champions, not who is dead.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchParticipant, MatchTimeline, ModelReport, utcnow
from app.services.timelines import (
    ATAKHAN,
    BARON,
    BLUE,
    DRAGON,
    ELDER,
    EXTRACT_VERSION,
    GRUBS,
    HERALD,
    INHIBITOR,
    KILL,
    PLATE,
    RED,
    TOWER,
)

log = logging.getLogger(__name__)

KIND = "win_model"
# Trained on ranked solo, where nearly all our games are. Applied to flex too,
# which plays on the same map with the same objectives, and labelled as such.
TRAIN_QUEUE = 420
MODEL_QUEUES = (420, 440)

FEATURES = (
    "gold", "kills", "towers", "inhibitors", "dragons", "soul",
    "elder", "baron", "grubs", "herald", "atakhan", "level",
)
FEATURE_LABELS = {
    "gold": ("Gold", "1,000 gold"),
    "kills": ("Kills", "1 kill"),
    "towers": ("Towers", "1 tower"),
    "inhibitors": ("Inhibitors down", "1 inhibitor"),
    "dragons": ("Dragons", "1 dragon"),
    "soul": ("Dragon soul", "the soul"),
    "elder": ("Elder buff", "the buff"),
    "baron": ("Baron buff", "the buff"),
    "grubs": ("Voidgrubs", "1 grub"),
    "herald": ("Rift Herald", "1 Herald"),
    "atakhan": ("Atakhan", "Atakhan"),
    "level": ("Levels", "1 level each"),
}
TAU_MINUTES = 40
INHIBITOR_RESPAWN_MS = 300_000
ELDER_BUFF_MS = 150_000
BARON_BUFF_MS = 180_000
SOUL_AT = 4

FOLDS = 5
RIDGE = 1.0
# The gate. Fewer games than this and a fold is too small to grade anything.
MIN_TRAIN_GAMES = 300
# Brier skill against always guessing the side's win rate: 0.10 means the model
# removes a tenth of that guess's squared error. Below it the curve says little
# the plain 50% line does not.
MIN_SKILL = 0.10
# Mean gap between predicted and observed win rate across ten bins.
MAX_ECE = 0.05
PHASES = ((0, 10, "0 to 10"), (10, 20, "10 to 20"), (20, 30, "20 to 30"), (30, 10_000, "30+"))
RELIABILITY_BINS = 10

# An effect is shown only where the feature was actually seen: non-zero in at
# least this share of the training minutes within five of the one asked about.
# Without it the table read an Elder buff at 10 minutes, which cannot happen.
MIN_SUPPORT = 0.005

# Events closer than this belong to one sequence: a fight and what it bought.
CHAIN_MS = 15_000
# A sequence is measured on the curve from just before it to this long after
# its last event, or to the next sequence if that comes sooner. The model
# credits a Baron or a tower mostly through the gold and buildings that follow
# (on 1,678 games a Baron buff alone was worth 1 to 3 points), so adding up the
# events' own effects made the fights that decided games look small.
AFTERMATH_MS = 60_000
MOMENTS = 3

OBJECTIVE_NAMES = {
    DRAGON: ("a dragon", "dragons"),
    ELDER: ("Elder Dragon", "Elder Dragons"),
    GRUBS: ("a Voidgrub", "Voidgrubs"),
    HERALD: ("Rift Herald", "Rift Heralds"),
    BARON: ("Baron", "Barons"),
    ATAKHAN: ("Atakhan", "Atakhan"),
    TOWER: ("a tower", "towers"),
    INHIBITOR: ("an inhibitor", "inhibitors"),
}


# ------------------------------------------------------------------ game state


@dataclass(slots=True)
class Side:
    kills: int = 0
    towers: int = 0
    dragons: int = 0
    grubs: int = 0
    herald: int = 0
    atakhan: int = 0
    # When each was taken, because these wear off.
    inhibitors: list[int] = field(default_factory=list)
    elders: list[int] = field(default_factory=list)
    barons: list[int] = field(default_factory=list)


class GameState:
    """Everything the model reads, replayed event by event."""

    def __init__(self) -> None:
        self.sides = {BLUE: Side(), RED: Side()}

    def apply(self, event: Sequence[Any]) -> None:
        ms, kind, team = event[0], event[1], event[2]
        side = self.sides.get(team)
        if side is None:
            return
        if kind == KILL:
            side.kills += 1
        elif kind == TOWER:
            side.towers += 1
        elif kind == INHIBITOR:
            side.inhibitors.append(ms)
        elif kind == DRAGON:
            side.dragons += 1
        elif kind == ELDER:
            side.elders.append(ms)
        elif kind == BARON:
            side.barons.append(ms)
        elif kind == GRUBS:
            side.grubs += 1
        elif kind == HERALD:
            side.herald += 1
        elif kind == ATAKHAN:
            side.atakhan += 1
        # A plate moves gold, which the frames already count.

    def features(self, ms: float, gold: tuple[float, float], levels: tuple[float, float]) -> list[float]:
        blue, red = self.sides[BLUE], self.sides[RED]

        def active(times: list[int], window: int) -> int:
            return sum(1 for t in times if 0 <= ms - t < window)

        def held(times: list[int], window: int) -> int:
            return 1 if active(times, window) else 0

        return [
            (gold[0] - gold[1]) / 1000,
            blue.kills - red.kills,
            blue.towers - red.towers,
            active(blue.inhibitors, INHIBITOR_RESPAWN_MS) - active(red.inhibitors, INHIBITOR_RESPAWN_MS),
            blue.dragons - red.dragons,
            (1 if blue.dragons >= SOUL_AT else 0) - (1 if red.dragons >= SOUL_AT else 0),
            held(blue.elders, ELDER_BUFF_MS) - held(red.elders, ELDER_BUFF_MS),
            held(blue.barons, BARON_BUFF_MS) - held(red.barons, BARON_BUFF_MS),
            blue.grubs - red.grubs,
            blue.herald - red.herald,
            blue.atakhan - red.atakhan,
            (levels[0] - levels[1]) / 5,
        ]


def _frame_times(tf: Sequence[Sequence[int]]) -> list[int]:
    # Frames are a minute apart. A payload without timestamps is read that way.
    return [int(row[0]) if row[0] else i * 60_000 for i, row in enumerate(tf)]


def _at(tf: Sequence[Sequence[int]], times: list[int], ms: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Team gold and levels at a moment, interpolated between frames."""
    if not tf:
        return (0.0, 0.0), (0.0, 0.0)
    if ms <= times[0]:
        row = tf[0]
        return (row[1], row[2]), (row[3], row[4])
    for i in range(1, len(tf)):
        if ms <= times[i]:
            a, b = tf[i - 1], tf[i]
            span = max(1, times[i] - times[i - 1])
            f = (ms - times[i - 1]) / span
            return (
                (a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f),
                (a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f),
            )
    row = tf[-1]
    return (row[1], row[2]), (row[3], row[4])


def frame_rows(extracted: dict) -> list[tuple[float, list[float]]]:
    """(minute, features) at every frame after the first: the training rows."""
    tf = extracted.get("tf") or []
    ev = extracted.get("ev") or []
    times = _frame_times(tf)
    state = GameState()
    rows: list[tuple[float, list[float]]] = []
    j = 0
    for i, row in enumerate(tf):
        ms = times[i]
        while j < len(ev) and ev[j][0] <= ms:
            state.apply(ev[j])
            j += 1
        if i == 0:
            continue
        rows.append((ms / 60_000, state.features(ms, (row[1], row[2]), (row[3], row[4]))))
    return rows


# ----------------------------------------------------------------- the model


def design(minutes: np.ndarray, features: np.ndarray) -> np.ndarray:
    """Intercept, time, and each feature weighted toward minute 0 and toward
    minute 40: 26 columns. A feature's two weights are its effect at either end.
    """
    tau = np.minimum(minutes, TAU_MINUTES) / TAU_MINUTES
    return np.column_stack([
        np.ones_like(tau), tau, features * (1 - tau)[:, None], features * tau[:, None],
    ])


# Columns whose weight may not go below zero: every feature column, not the
# intercept or the clock.
def _held_non_negative(columns: int) -> np.ndarray:
    held = np.ones(columns, dtype=bool)
    held[:2] = False
    return held


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * z))


@dataclass(slots=True)
class Fitted:
    coef: np.ndarray
    mean: np.ndarray
    scale: np.ndarray

    def predict(self, x: np.ndarray) -> np.ndarray:
        return _sigmoid(((x - self.mean) / self.scale) @ self.coef)


def _loss(z: np.ndarray, y: np.ndarray, w: np.ndarray, penalty: np.ndarray) -> float:
    margin = z @ w
    # log(1 + e^m) - y*m, written to stay finite for large |m|.
    nll = np.logaddexp(0.0, margin) - y * margin
    return float(nll.sum() + 0.5 * w @ penalty @ w)


def fit(x: np.ndarray, y: np.ndarray, *, ridge: float = RIDGE, non_negative: bool = True) -> Fitted:
    """Logistic regression, ridge on everything but the intercept, with every
    feature weight held at zero or above.

    Projected Newton: a weight pinned at zero whose gradient still pushes it
    down stays out of the step, the rest take a Newton step, and the result is
    clipped back to zero and halved until the loss falls. ``non_negative=False``
    lifts the constraint, for the score audit, where a weight that goes below
    zero is the finding. Standardised first,
    so one penalty means the same on gold (thousands) and on the soul (plus or
    minus one); scaling by a positive number keeps each weight's sign.
    """
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    mean[0], scale[0] = 0.0, 1.0
    scale[scale == 0] = 1.0
    z = (x - mean) / scale
    penalty = ridge * np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    held = _held_non_negative(x.shape[1]) if non_negative else np.zeros(x.shape[1], dtype=bool)
    w = np.zeros(x.shape[1])
    loss = _loss(z, y, w, penalty)
    for _ in range(100):
        p = _sigmoid(z @ w)
        gradient = z.T @ (p - y) + penalty @ w
        hessian = (z * (p * (1 - p))[:, None]).T @ z + penalty
        pinned = held & (w <= 0) & (gradient > 0)
        free = ~pinned
        step = np.zeros_like(w)
        step[free] = np.linalg.solve(hessian[np.ix_(free, free)], gradient[free])
        size = 1.0
        while True:
            candidate = w - size * step
            candidate[held] = np.maximum(candidate[held], 0.0)
            new_loss = _loss(z, y, candidate, penalty)
            if new_loss <= loss + 1e-12 or size < 1e-6:
                break
            size /= 2
        moved = float(np.max(np.abs(candidate - w)))
        w, loss = candidate, new_loss
        if moved < 1e-8:
            break
    return Fitted(w, mean, scale)


@dataclass(slots=True)
class TrainingGame:
    match_id: str
    patch: str | None
    blue_won: bool
    rows: list[tuple[float, list[float]]]

    @property
    def fold(self) -> int:
        return zlib.crc32(self.match_id.encode()) % FOLDS


def _matrix(games: Sequence[TrainingGame]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    minutes = [m for g in games for m, _ in g.rows]
    features = [f for g in games for _, f in g.rows]
    labels = [1.0 if g.blue_won else 0.0 for g in games for _ in g.rows]
    minutes_arr = np.asarray(minutes, dtype=float)
    x = design(minutes_arr, np.asarray(features, dtype=float).reshape(-1, len(FEATURES)))
    return x, np.asarray(labels, dtype=float), minutes_arr


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    clipped = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "rows": int(len(y)),
        "accuracy": round(float(np.mean((p >= 0.5) == (y == 1))), 4),
        "brier": round(float(np.mean((p - y) ** 2)), 4),
        "log_loss": round(float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))), 4),
    }


def _reliability(y: np.ndarray, p: np.ndarray) -> tuple[list[dict], float]:
    bins = []
    ece = 0.0
    edges = np.linspace(0, 1, RELIABILITY_BINS + 1)
    for i in range(RELIABILITY_BINS):
        low, high = edges[i], edges[i + 1]
        mask = (p >= low) & ((p < high) if i < RELIABILITY_BINS - 1 else (p <= high))
        n = int(mask.sum())
        if not n:
            continue
        predicted, observed = float(p[mask].mean()), float(y[mask].mean())
        ece += n / len(y) * abs(predicted - observed)
        bins.append({
            "low": round(float(low), 2),
            "high": round(float(high), 2),
            "predicted": round(predicted, 4),
            "observed": round(observed, 4),
            "rows": n,
        })
    return bins, round(ece, 4)


def cross_validate(games: Sequence[TrainingGame]) -> dict[str, Any]:
    """Held-out predictions for every row, graded overall and by phase."""
    ys, ps, ms = [], [], []
    for k in range(FOLDS):
        train = [g for g in games if g.fold != k]
        test = [g for g in games if g.fold == k]
        if not train or not test:
            continue
        x_train, y_train, _ = _matrix(train)
        x_test, y_test, m_test = _matrix(test)
        if not len(y_train) or not len(y_test):
            continue
        model = fit(x_train, y_train)
        ys.append(y_test)
        ps.append(model.predict(x_test))
        ms.append(m_test)
    if not ys:
        return {"folds": FOLDS, "overall": None, "phases": [], "reliability": [], "ece": None}

    y, p, minutes = np.concatenate(ys), np.concatenate(ps), np.concatenate(ms)
    prior = float(y.mean())
    baseline = float(np.mean((prior - y) ** 2))
    overall = _metrics(y, p)
    overall["baseline_brier"] = round(baseline, 4)
    overall["skill"] = round(1 - overall["brier"] / baseline, 4) if baseline else 0.0
    phases = []
    for low, high, label in PHASES:
        mask = (minutes >= low) & (minutes < high)
        if mask.any():
            phases.append({"label": label, **_metrics(y[mask], p[mask])})
    reliability, ece = _reliability(y, p)
    return {
        "folds": FOLDS,
        "overall": overall,
        "phases": phases,
        "reliability": reliability,
        "ece": ece,
        "blue_win_rate": round(prior, 4),
    }


def gate(games: int, cv: dict[str, Any]) -> str | None:
    """Why the model may not be shown, or None when it may."""
    overall = cv.get("overall")
    if games < MIN_TRAIN_GAMES or overall is None:
        return f"trained on {games:,} games; it needs {MIN_TRAIN_GAMES:,} before it is graded"
    if overall["skill"] < MIN_SKILL:
        return (
            f"its held-out Brier skill is {overall['skill']:.2f}, under the "
            f"{MIN_SKILL:.2f} it must reach"
        )
    if cv["ece"] > MAX_ECE:
        return (
            f"its calibration error is {cv['ece'] * 100:.1f} points, over the "
            f"{MAX_ECE * 100:.0f} it is allowed"
        )
    return None


def _support(games: Sequence[TrainingGame], feature: int, minute: int) -> float:
    near = [f for g in games for m, f in g.rows if abs(m - minute) <= 5]
    if not near:
        return 0.0
    return sum(1 for f in near if f[feature]) / len(near)


def effects_table(model: Fitted, games: Sequence[TrainingGame] = ()) -> list[dict[str, Any]]:
    """What one unit of each feature is worth from an even game, by minute.

    The coefficients themselves are log-odds on standardised columns, which
    nobody can read. This is the same model said in points of win chance, and
    left out (None) where the training games never had the feature at that time.
    """
    out = []
    for i, name in enumerate(FEATURES):
        at: dict[str, float | None] = {}
        for minute in (10, 20, 30):
            if games and _support(games, i, minute) < MIN_SUPPORT:
                at[str(minute)] = None
                continue
            even = np.zeros((1, len(FEATURES)))
            ahead = even.copy()
            ahead[0, i] = 1.0
            m = np.asarray([float(minute)])
            base = float(model.predict(design(m, even))[0])
            moved = float(model.predict(design(m, ahead))[0])
            at[str(minute)] = round((moved - base) * 100, 1)
        label, unit = FEATURE_LABELS[name]
        out.append({"feature": name, "label": label, "unit": unit, "points": at})
    return out


# ------------------------------------------------------------------ training


async def training_games(session: AsyncSession, queue_id: int = TRAIN_QUEUE) -> list[TrainingGame]:
    blue_won = dict(
        (
            await session.execute(
                select(MatchParticipant.match_id, func.max(MatchParticipant.win))
                .join(Match, Match.match_id == MatchParticipant.match_id)
                .where(Match.queue_id == queue_id, MatchParticipant.team_id == BLUE)
                .group_by(MatchParticipant.match_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(MatchTimeline.match_id, MatchTimeline.extracted, Match.patch)
            .join(Match, Match.match_id == MatchTimeline.match_id)
            .where(Match.queue_id == queue_id, Match.is_remake.is_(False))
        )
    ).all()
    games = []
    for match_id, extracted, patch in rows:
        if not extracted or (extracted.get("v") or 0) < EXTRACT_VERSION:
            continue
        if match_id not in blue_won:
            continue
        frames = frame_rows(extracted)
        if frames:
            games.append(TrainingGame(match_id, patch, bool(blue_won[match_id]), frames))
    return games


async def train(session: AsyncSession) -> ModelReport:
    """Fit, grade and store the model. Storage only: no Riot call."""
    games = await training_games(session)
    cv = cross_validate(games) if games else {"overall": None, "phases": [], "reliability": [], "ece": None}
    withheld = gate(len(games), cv)

    payload: dict[str, Any] = {
        "features": list(FEATURES),
        "tau_minutes": TAU_MINUTES,
        "queue_id": TRAIN_QUEUE,
        "applies_to": list(MODEL_QUEUES),
        "trained_games": len(games),
        "trained_rows": sum(len(g.rows) for g in games),
        "patches": sorted({g.patch for g in games if g.patch}),
        "cv": cv,
        "gate": {"min_games": MIN_TRAIN_GAMES, "min_skill": MIN_SKILL, "max_ece": MAX_ECE},
        "published": withheld is None,
        "withheld": withheld,
    }
    if games:
        x, y, _ = _matrix(games)
        final = fit(x, y)
        payload["coef"] = [round(float(v), 6) for v in final.coef]
        payload["mean"] = [round(float(v), 6) for v in final.mean]
        payload["scale"] = [round(float(v), 6) for v in final.scale]
        payload["effects"] = effects_table(final, games)

    row = (
        await session.execute(select(ModelReport).where(ModelReport.kind == KIND))
    ).scalar_one_or_none()
    if row is None:
        row = ModelReport(kind=KIND, version=1, payload=payload, trained_games=len(games))
        session.add(row)
    else:
        # A new version only when what a reader would see changes, so a
        # nightly retrain on the same games does not mark every review stale.
        if (row.payload or {}).get("coef") != payload.get("coef") or (
            (row.payload or {}).get("published") != payload["published"]
        ):
            row.version += 1
        row.payload = payload
        row.trained_games = len(games)
    row.computed_at = utcnow()
    await session.commit()
    _cache.clear()
    log.info(
        "win model v%d: %d games, %s", row.version, len(games),
        "published" if withheld is None else f"withheld: {withheld}",
    )
    return row


# ---------------------------------------------------------------- prediction


@dataclass(slots=True)
class WinModel:
    version: int
    published: bool
    withheld: str | None
    fitted: Fitted | None
    payload: dict[str, Any]

    def probabilities(self, rows: Sequence[tuple[float, Sequence[float]]]) -> np.ndarray:
        if self.fitted is None or not rows:
            return np.zeros(len(rows))
        minutes = np.asarray([m for m, _ in rows], dtype=float)
        features = np.asarray([f for _, f in rows], dtype=float).reshape(-1, len(FEATURES))
        return self.fitted.predict(design(minutes, features))


_cache: dict[tuple[int, str], WinModel] = {}


async def current_model(session: AsyncSession) -> WinModel | None:
    row = (
        await session.execute(select(ModelReport).where(ModelReport.kind == KIND))
    ).scalar_one_or_none()
    if row is None:
        return None
    key = (row.version, str(row.computed_at))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    payload = row.payload or {}
    fitted = None
    if payload.get("coef"):
        fitted = Fitted(
            np.asarray(payload["coef"], dtype=float),
            np.asarray(payload["mean"], dtype=float),
            np.asarray(payload["scale"], dtype=float),
        )
    model = WinModel(
        version=row.version,
        published=bool(payload.get("published")) and fitted is not None,
        withheld=payload.get("withheld"),
        fitted=fitted,
        payload=payload,
    )
    _cache.clear()
    _cache[key] = model
    return model


# --------------------------------------------------------------- one game


@dataclass(slots=True)
class Effect:
    """One state event and what it did to blue's chance."""

    index: int
    event: list[Any]
    before: float
    after: float

    @property
    def ms(self) -> int:
        return int(self.event[0])

    @property
    def kind(self) -> str:
        return self.event[1]

    @property
    def team(self) -> int:
        return self.event[2]

    def gain(self, team: int) -> float:
        """What it did for ``team``, in win chance from 0 to 1."""
        delta = self.after - self.before
        return delta if team == BLUE else -delta


@dataclass(slots=True)
class Stretch:
    """Events closer than CHAIN_MS, and blue's chance around them."""

    effects: list[Effect]
    before: float
    after: float
    end_ms: int

    @property
    def swing(self) -> float:
        return self.after - self.before


@dataclass(slots=True)
class Story:
    # (ms, blue's chance, whether the point is a frame rather than an event)
    curve: list[tuple[int, float, bool]]
    effects: list[Effect]
    sequences: list[Stretch]


def evaluate(extracted: dict, model: WinModel) -> Story:
    """Blue's chance over the game, every state event's effect, and the
    sequences the events fall into.

    The curve has a point at every frame and just after every event, so a Baron
    at 25:30 shows as a step, not a slope to the next minute. Plates change no
    state the model reads (their gold arrives with the next frame), so they are
    left out of effects and sequences but kept for trades.
    """
    tf = extracted.get("tf") or []
    ev = extracted.get("ev") or []
    times = _frame_times(tf)
    if not tf:
        return Story([], [], [])
    end_ms = times[-1]

    # Sequences come from event times alone, so they are known before any
    # prediction, and their probes can join the one pass below.
    groups: list[list[int]] = []
    for idx, event in enumerate(ev):
        if event[1] == PLATE:
            continue
        if groups and event[0] - ev[groups[-1][-1]][0] <= CHAIN_MS:
            groups[-1].append(idx)
        else:
            groups.append([idx])
    probes: list[tuple[float, int, tuple[str, int]]] = []
    for g, group in enumerate(groups):
        first, last = ev[group[0]][0], ev[group[-1]][0]
        until = last + AFTERMATH_MS
        if g + 1 < len(groups):
            until = min(until, ev[groups[g + 1][0]][0] - 1)
        until = max(last, min(until, end_ms))
        probes.append((first - 1, 1, ("start", g)))
        probes.append((until, 1, ("end", g)))
    queries = sorted(
        [(float(times[i]), 0, ("frame", i)) for i in range(len(tf))] + probes,
        key=lambda q: (q[0], q[1]),
    )

    state = GameState()
    rows: list[tuple[float, list[float]]] = []
    slots: dict[tuple[str, int], int] = {}
    event_slots: dict[int, tuple[int, int]] = {}
    j = 0
    for t, _, tag in queries:
        while j < len(ev) and ev[j][0] <= t:
            event = ev[j]
            if event[1] != PLATE:
                gold, levels = _at(tf, times, event[0])
                before = len(rows)
                rows.append((event[0] / 60_000, state.features(event[0], gold, levels)))
                state.apply(event)
                if event[1] == KILL and event[8]:
                    # The bounty moved with the kill: it is part of what it did.
                    gold = (
                        (gold[0] + event[8], gold[1]) if event[2] == BLUE
                        else (gold[0], gold[1] + event[8])
                    )
                rows.append((event[0] / 60_000, state.features(event[0], gold, levels)))
                event_slots[j] = (before, before + 1)
            else:
                state.apply(event)
            j += 1
        if tag[0] == "frame":
            row = tf[tag[1]]
            gold, levels = (row[1], row[2]), (row[3], row[4])
        else:
            gold, levels = _at(tf, times, t)
        slots[tag] = len(rows)
        rows.append((max(t, 0) / 60_000, state.features(t, gold, levels)))

    p = model.probabilities(rows)
    effects = [
        Effect(idx, ev[idx], float(p[b]), float(p[a])) for idx, (b, a) in sorted(event_slots.items())
    ]
    by_index = {e.index: e for e in effects}
    sequences = [
        Stretch(
            effects=[by_index[idx] for idx in group if idx in by_index],
            before=float(p[slots[("start", g)]]),
            after=float(p[slots[("end", g)]]),
            end_ms=int(ev[group[-1]][0]),
        )
        for g, group in enumerate(groups)
    ]
    curve = sorted(
        [(times[i], float(p[slots[("frame", i)]]), True) for i in range(len(tf))]
        + [(e.ms, e.after, False) for e in effects]
    )
    return Story(curve, effects, sequences)


@dataclass(slots=True)
class Moment:
    start_ms: int
    end_ms: int
    # Blue's chance after minus before, summed over the sequence's events.
    swing: float
    kills: dict[int, int]
    objectives: dict[int, list[str]]
    text: str


def _name(kind: str, count: int) -> str:
    one, many = OBJECTIVE_NAMES[kind]
    return one if count == 1 else f"{count} {many}"


def describe(swing: float, kills: dict[int, int], objectives: dict[int, list[str]]) -> str:
    """ "Red won a fight 3 for 1 and took Baron" """
    winner = BLUE if swing > 0 else RED
    loser = RED if winner == BLUE else BLUE
    parts = []
    won, lost = kills.get(winner, 0), kills.get(loser, 0)
    if won or lost:
        if won > lost:
            parts.append(f"won a fight {won} for {lost}")
        elif won == lost:
            parts.append(f"traded {won} for {lost}")
        else:
            parts.append(f"lost a fight {won} for {lost}")
    taken = objectives.get(winner) or []
    if taken:
        counts: dict[str, int] = {}
        for kind in taken:
            counts[kind] = counts.get(kind, 0) + 1
        names = [_name(kind, n) for kind, n in counts.items()]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        parts.append(("and took " if parts else "took ") + joined)
    side = "Blue" if winner == BLUE else "Red"
    return f"{side} {' '.join(parts)}" if parts else f"{side} gained ground"


def moments(sequences: Sequence[Stretch], limit: int = MOMENTS) -> list[Moment]:
    """The sequences that moved the curve most, biggest first."""
    found = []
    for sequence in sequences:
        if not sequence.effects:
            continue
        kills = {BLUE: 0, RED: 0}
        objectives: dict[int, list[str]] = {BLUE: [], RED: []}
        for e in sequence.effects:
            if e.kind == KILL:
                kills[e.team] = kills.get(e.team, 0) + 1
            elif e.kind in OBJECTIVE_NAMES:
                objectives.setdefault(e.team, []).append(e.kind)
        found.append(Moment(
            start_ms=sequence.effects[0].ms,
            end_ms=sequence.end_ms,
            swing=sequence.swing,
            kills=kills,
            objectives=objectives,
            text=describe(sequence.swing, kills, objectives),
        ))
    found.sort(key=lambda m: -abs(m.swing))
    return found[:limit]
