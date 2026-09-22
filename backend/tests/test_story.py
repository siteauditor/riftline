"""A game's story on the API: the on-demand timeline, the review, the curve.

Riot is mocked at the transport, as everywhere. The model is written straight
into `model_reports` where a test needs one, because training one needs
hundreds of games the suite does not hold.
"""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import ModelReport, ParticipantReview
from app.services import winchance
from app.services.winchance import FEATURES, KIND
from tests.test_integration import mock_riot
from tests.test_timeline_storage import (
    BLUE_MID,
    RED_MID,
    mock_timeline,
    paired_match,
    seed_match,
    timeline_payload,
)


def story_payload() -> dict:
    """The storage fixture's timeline, with a fight in it.

    Red's mid kills blue's mid at 5:00, and blue's top takes a kill back 30
    seconds later, so the death is traded.
    """
    payload = timeline_payload()
    frames = payload["info"]["frames"]
    frames[5]["events"].append({
        "type": "CHAMPION_KILL", "timestamp": 300_000, "killerId": RED_MID,
        "victimId": BLUE_MID, "assistingParticipantIds": [9], "bounty": 300,
        "shutdownBounty": 0, "position": {"x": 7000, "y": 7200},
    })
    frames[6]["events"].append({
        "type": "CHAMPION_KILL", "timestamp": 330_000, "killerId": 2,
        "victimId": 6, "assistingParticipantIds": [], "bounty": 300,
        "shutdownBounty": 0, "position": {"x": 2000, "y": 12000},
    })
    return payload


def published_model_payload() -> dict:
    width = 2 + 2 * len(FEATURES)
    coef = [0.0] * width
    for name, value in (("gold", 0.8), ("kills", 0.3)):
        i = FEATURES.index(name)
        coef[2 + i] = value
        coef[2 + len(FEATURES) + i] = value
    return {
        "coef": coef, "mean": [0.0] * width, "scale": [1.0] * width,
        "published": True, "withheld": None, "trained_games": 1234,
        "cv": {"overall": {"accuracy": 0.72}, "phases": [{"label": "0 to 10", "accuracy": 0.61}]},
    }


@respx.mock
async def test_a_story_fetches_a_missing_timeline_once_and_reads_the_deaths(client):
    match_id = "EUW1_6000000051"
    await seed_match(client, match_id)
    route = mock_timeline(story_payload())

    first = await client.get(f"/api/matches/{match_id}/story")
    assert first.status_code == 200
    body = first.json()
    assert body["available"] is True
    assert len(body["players"]) == 10

    victim = next(p for p in body["players"] if p["participant_index"] == BLUE_MID)
    assert (victim["deaths"], victim["untraded"]) == (1, 0), "blue took a kill back 30 s later"
    (death,) = victim["death_list"]
    assert death["killer"]["participant_index"] == RED_MID
    assert (death["x"], death["y"]) == (7000, 7200)
    assert route.call_count == 1

    again = await client.get(f"/api/matches/{match_id}/story")
    assert again.json()["available"] is True
    assert route.call_count == 1, "the timeline was kept"


@respx.mock
async def test_a_published_model_draws_the_curve_and_stores_the_reviews(client):
    match_id = "EUW1_6000000052"
    await seed_match(client, match_id)
    mock_timeline(story_payload())
    async with SessionLocal() as session:
        await session.execute(delete(ModelReport).where(ModelReport.kind == KIND))
        session.add(ModelReport(kind=KIND, version=7, payload=published_model_payload(), trained_games=1234))
        await session.commit()
    winchance._cache.clear()
    try:
        body = (await client.get(f"/api/matches/{match_id}/story")).json()

        assert body["model"]["published"] is True
        assert body["model"]["accuracy"] == 0.72
        assert body["curve"] and 1 <= len(body["moments"]) <= 3
        victim = next(p for p in body["players"] if p["participant_index"] == BLUE_MID)
        assert victim["death_list"][0]["cost"] > 0
        assert body["map_url"] is None or body["map_url"].endswith("/img/map/map11.png")

        async with SessionLocal() as session:
            stored = (
                await session.execute(
                    select(ParticipantReview).where(ParticipantReview.match_id == match_id)
                )
            ).scalars().all()
        assert len(stored) == 10
        assert {r.model_version for r in stored} == {7}
        assert next(r for r in stored if r.participant_index == BLUE_MID).deaths == 1
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(ModelReport).where(ModelReport.kind == KIND))
            await session.commit()
        winchance._cache.clear()


@respx.mock
async def test_without_a_model_the_story_still_reads_trades_and_says_why_no_curve(client):
    match_id = "EUW1_6000000054"
    await seed_match(client, match_id)
    mock_timeline(story_payload())
    body = (await client.get(f"/api/matches/{match_id}/story")).json()

    assert body["available"] is True
    assert body["curve"] == []
    assert "model" in body["reason"]
    victim = next(p for p in body["players"] if p["participant_index"] == BLUE_MID)
    assert victim["death_list"][0]["cost"] is None
    assert victim["death_list"][0]["traded"] is True


@respx.mock
async def test_a_busy_key_leaves_the_story_pending_with_a_retry(client):
    match_id = "EUW1_6000000053"
    await seed_match(client, match_id)
    respx.get(url__regex=r".*/lol/match/v5/matches/.*/timeline$").mock(
        # Short, because the client waits out each Retry-After before it
        # gives up, and a long one would only slow the suite.
        return_value=httpx.Response(429, headers={"Retry-After": "0.05"})
    )
    body = (await client.get(f"/api/matches/{match_id}/story")).json()

    assert body["available"] is False
    assert body["pending"] is True
    assert body["retry_after"] is not None


@respx.mock
async def test_a_game_from_another_queue_has_no_story_and_costs_nothing(client):
    match_id = "EUW1_6000000055"
    payload = paired_match(match_id)
    payload["info"]["queueId"] = 450
    mock_riot(matches=[payload], match_ids=[match_id])
    assert (await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1&queue=450")).status_code == 200
    route = mock_timeline(story_payload())

    body = (await client.get(f"/api/matches/{match_id}/story")).json()
    assert body["available"] is False
    assert "another queue" in body["reason"]
    assert route.call_count == 0


async def test_a_story_for_a_match_we_do_not_hold_is_a_404(client):
    response = await client.get("/api/matches/EUW1_6999999999/story")
    assert response.status_code == 404



@respx.mock
async def test_the_profile_lists_a_reviewed_role_and_says_when_it_has_too_few_games(client):
    from tests import fixtures as fx

    await seed_match(client, "EUW1_6000000056")
    async with SessionLocal() as session:
        session.add(ParticipantReview(
            match_id="EUW1_6000000056", participant_index=BLUE_MID, puuid=fx.PUUID,
            queue_id=420, team_position="MIDDLE", minutes=30.0, deaths=3, untraded=1,
            win_lost=0.1, takedowns=6, converted=2, win_gained=0.2, contests=1,
            contests_won=1, model_version=1,
        ))
        await session.commit()

    body = (await client.get("/api/summoner/euw1/Caps/EUW/analytics")).json()
    middle = next(r for r in body["review"] if r["position"] == "MIDDLE")
    assert middle["metrics"] == []
    assert middle["min_games"] == 10 and "10" in middle["withheld"]
    assert isinstance(body["lanes"], list)
