"""Timeline storage, backfill and the laning chip on the API.

The sibling module covers the parsing rules against hand-written payloads. This
one covers the parts that need a database: that a fetched timeline lands in the
same transaction as the participant columns it derives, that the backfill is
resumable and does not re-fetch what it holds, and that the match-history chip
appears only once a timeline exists, which was the whole point of not fetching
timelines on demand.
"""

from __future__ import annotations

import gzip
import json

import httpx
import pytest
import respx
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Match, MatchParticipant, MatchTimeline
from app.riot.client import RiotClient
from app.services.ingest import TimelineBackfill, corpus_summary
from app.services.timelines import TimelineService
from tests import fixtures as fx
from tests.test_integration import mock_riot

# Riot numbers participants 1-10 and `participant_index` follows it, so these
# are the same keys the timeline's `participantFrames` use.
BLUE_MID, RED_MID = 1, 8
LANES = ["MIDDLE", "TOP", "JUNGLE", "BOTTOM", "UTILITY",
         "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def paired_match(match_id: str) -> dict:
    """The shared fixture with a lineup that actually pairs off.

    The fixture gives team 100 two mid laners and no top, which laning_scores
    correctly refuses to score. A laning test needs one of each role per side.
    """
    payload = fx.match(match_id)
    for participant, lane in zip(payload["info"]["participants"], LANES, strict=True):
        participant["teamPosition"] = lane
        participant["individualPosition"] = lane
    return payload


def timeline_payload(*, frames: int = 30) -> dict:
    """Blue mid ahead 6000/7000/120 against red mid 4000/5000/80 at minute 14."""

    def people(minute: int) -> dict:
        out = {}
        for pid in range(1, 11):
            ahead = pid == BLUE_MID
            out[str(pid)] = {
                "totalGold": (430 if ahead else 290) * minute,
                "xp": (500 if ahead else 360) * minute,
                "minionsKilled": (8 if ahead else 5) * minute,
                "jungleMinionsKilled": 0,
                "level": 1 + minute // 2,
            }
        # Pin minute 14 to round numbers so the expected score is exact.
        if minute == 14:
            out[str(BLUE_MID)] = {"totalGold": 6000, "xp": 7000,
                                  "minionsKilled": 120, "jungleMinionsKilled": 0, "level": 11}
            out[str(RED_MID)] = {"totalGold": 4000, "xp": 5000,
                                 "minionsKilled": 80, "jungleMinionsKilled": 0, "level": 9}
        return out

    all_frames = []
    for minute in range(frames):
        events = []
        if 1 <= minute <= 5:
            events.append({
                "type": "SKILL_LEVEL_UP", "levelUpType": "NORMAL",
                "participantId": BLUE_MID, "skillSlot": 1,
            })
            events.append({
                "type": "ITEM_PURCHASED", "participantId": BLUE_MID,
                "itemId": 3000 + minute, "timestamp": minute * 60_000,
            })
        all_frames.append({"participantFrames": people(minute), "events": events})
    return {"info": {"frameInterval": 60000, "frames": all_frames}}


def mock_timeline(payload: dict | None = None, *, status: int = 200):
    return respx.get(url__regex=r".*/lol/match/v5/matches/.*/timeline$").mock(
        return_value=httpx.Response(status, json=payload)
    )


async def seed_match(client, match_id: str) -> None:
    """Store a match the way the product does, through the history endpoint."""
    mock_riot(matches=[paired_match(match_id)], match_ids=[match_id])
    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    assert response.status_code == 200


def service(session) -> TimelineService:
    return TimelineService(session, RiotClient("RGAPI-test-key"), get_settings())


async def stored_matches(session, match_id: str) -> list[Match]:
    stmt = select(Match).where(Match.match_id == match_id)
    return list((await session.execute(stmt)).scalars())


# The blend of three shares: 6000/10000, 7000/12000, 120/200.
EXPECTED_SCORE = (0.6 + 7 / 12 + 0.6) / 3


# ------------------------------------------------------------------- storage


@respx.mock
async def test_storing_a_timeline_fills_the_participant_columns(client):
    match_id = "EUW1_6000000030"
    await seed_match(client, match_id)
    mock_timeline(timeline_payload())

    async with SessionLocal() as session:
        matches = await stored_matches(session, match_id)
        assert await service(session).ensure_timelines(matches) == 1

    async with SessionLocal() as session:
        row = await session.get(MatchTimeline, match_id)
        assert row is not None
        assert row.frame_count == 30
        assert row.laning_minute == 14
        # The insurance copy has to be readable, or it is not insurance.
        assert json.loads(gzip.decompress(row.raw_gz))["info"]["frameInterval"] == 60000

        blue = (await session.execute(
            select(MatchParticipant).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.participant_index == BLUE_MID,
            )
        )).scalar_one()
        assert blue.laning_score == pytest.approx(EXPECTED_SCORE)
        assert blue.gold_at_14 == 6000
        assert blue.gold_diff_14 == 2000
        assert blue.cs_diff_14 == 40
        assert blue.skill_order == [1, 1, 1, 1, 1]
        assert blue.build_order == [3001, 3002, 3003, 3004, 3005]
        # Seconds, in step with the order: the item guide's "when" is read here.
        assert blue.build_times == [60, 120, 180, 240, 300]

        red = (await session.execute(
            select(MatchParticipant).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.participant_index == RED_MID,
            )
        )).scalar_one()
        # The two halves of a lane are the same measurement from both ends.
        assert red.laning_score == pytest.approx(1 - EXPECTED_SCORE)
        assert red.gold_diff_14 == -2000
        assert red.opponent_champion_id == blue.champion_id


@respx.mock
async def test_a_timeline_with_no_frames_is_not_stored(client):
    """An empty timeline would write a row that permanently hides the match
    from pending, so it has to be refused rather than recorded."""
    match_id = "EUW1_6000000031"
    await seed_match(client, match_id)
    mock_timeline({"info": {"frameInterval": 60000, "frames": []}})

    async with SessionLocal() as session:
        svc = service(session)
        assert await svc.ensure_timelines(await stored_matches(session, match_id)) == 0
        assert await session.get(MatchTimeline, match_id) is None
        assert match_id in {m.match_id for m in await svc.pending(limit=500)}


# ------------------------------------------------------------------ backfill


@respx.mock
async def test_purchase_times_are_filled_from_a_timeline_already_stored(client):
    """Timelines stored before `build_times` existed still hold every event,
    so the times come from disk, once, with no Riot call."""
    from sqlalchemy import null, update

    from app.services.timelines import backfill_buy_times

    match_id = "EUW1_6000000039"
    await seed_match(client, match_id)
    mock_timeline(timeline_payload())
    async with SessionLocal() as session:
        await service(session).ensure_timelines(await stored_matches(session, match_id))
        # As a row stored before the column existed looks: SQL NULL, which the
        # migration leaves, not the JSON `null` that assigning None writes.
        await session.execute(
            update(MatchParticipant)
            .where(MatchParticipant.match_id == match_id)
            .values(build_times=null())
        )
        await session.commit()

    async with SessionLocal() as session:
        first = await backfill_buy_times(session)
    async with SessionLocal() as session:
        second = await backfill_buy_times(session)
        blue = (await session.execute(
            select(MatchParticipant).where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.participant_index == BLUE_MID,
            )
        )).scalar_one()

    assert first.filled >= 1 and first.mismatched == 0
    assert blue.build_times == [60, 120, 180, 240, 300]
    assert second.filled == 0, "a second run has nothing left to do"


@respx.mock
async def test_reextract_brings_an_old_extract_up_to_date_once(client):
    """Timelines stored before version 2 hold every event in `raw_gz`, so the
    new keys come from disk, once, with no Riot call."""
    from app.services.timelines import EXTRACT_VERSION, backfill_extracts

    match_id = "EUW1_6000000041"
    await seed_match(client, match_id)
    route = mock_timeline(timeline_payload())
    async with SessionLocal() as session:
        await service(session).ensure_timelines(await stored_matches(session, match_id))
        stored = await session.get(MatchTimeline, match_id)
        # As a version 1 row looks: no `tf`, `ev` or `v`.
        stored.extracted = {
            k: v for k, v in stored.extracted.items() if k not in ("tf", "ev", "v")
        }
        await session.commit()
    calls = route.call_count

    async with SessionLocal() as session:
        first = await backfill_extracts(session)
    async with SessionLocal() as session:
        second = await backfill_extracts(session)
        upgraded = (await session.get(MatchTimeline, match_id)).extracted

    assert first.rows >= 1
    assert upgraded["v"] == EXTRACT_VERSION
    assert len(upgraded["tf"]) == 30
    assert upgraded["buys"], "the keys that were already there are kept"
    assert second.rows == 0, "a second run has nothing left to do"
    assert route.call_count == calls, "re-extraction reads storage, not Riot"


@respx.mock
async def test_backfill_skips_what_it_already_holds(client):
    match_id = "EUW1_6000000032"
    await seed_match(client, match_id)
    route = mock_timeline(timeline_payload())

    async with SessionLocal() as session:
        svc = service(session)
        matches = await stored_matches(session, match_id)
        assert await svc.ensure_timelines(matches) == 1
        calls_after_first = route.call_count

        # Re-running is the normal case: an interrupted backfill resumes by
        # asking the same question again.
        assert await svc.ensure_timelines(matches) == 0
        assert route.call_count == calls_after_first


@respx.mock
async def test_pending_hands_back_only_matches_without_a_timeline(client):
    first, second = "EUW1_6000000033", "EUW1_6000000034"
    await seed_match(client, first)
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=[second])
    )
    respx.get(url__regex=rf".*/lol/match/v5/matches/{second}$").mock(
        return_value=httpx.Response(200, json=paired_match(second))
    )
    assert (await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")).status_code == 200
    mock_timeline(timeline_payload())

    async with SessionLocal() as session:
        svc = service(session)
        outstanding = {m.match_id for m in await svc.pending(limit=500)}
        assert {first, second} <= outstanding

        await svc.ensure_timelines(
            [m for m in await svc.pending(limit=500) if m.match_id == first]
        )

        outstanding = {m.match_id for m in await svc.pending(limit=500)}
        assert first not in outstanding
        assert second in outstanding


@respx.mock
async def test_backfill_stops_instead_of_retrying_a_batch_nothing_came_back_for(client):
    """Matches that aged out of Riot's retention would otherwise be handed back
    by pending for ever, and the run would never end."""
    await seed_match(client, "EUW1_6000000035")
    route = mock_timeline(status=404)

    async with SessionLocal() as session:
        backfill = TimelineBackfill(session, RiotClient("RGAPI-test-key"), get_settings())
        stats = await backfill.run(target=50, batch=5)

    assert stats.matches_new == 0
    assert route.call_count <= 5  # one pass over one batch, then it gives up


# ----------------------------------------------------------------------- api


@respx.mock
async def test_match_history_omits_the_laning_chip_without_a_timeline(client):
    match_id = "EUW1_6000000036"
    mock_riot(matches=[paired_match(match_id)], match_ids=[match_id])
    body = (await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")).json()

    row = body["matches"][0]
    assert row["laning_score"] is None
    assert row["laning_opponent"] is None
    assert row["gold_diff_14"] is None


@respx.mock
async def test_match_history_shows_the_laning_chip_once_the_timeline_lands(client):
    match_id = "EUW1_6000000037"
    await seed_match(client, match_id)
    mock_timeline(timeline_payload())

    async with SessionLocal() as session:
        assert await service(session).ensure_timelines(
            await stored_matches(session, match_id)
        ) == 1

    body = (await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")).json()
    row = body["matches"][0]
    assert row["match_id"] == match_id
    assert row["laning_score"] == pytest.approx(EXPECTED_SCORE)
    assert row["gold_diff_14"] == 2000
    assert row["laning_opponent"]["name"]


# ------------------------------------------------------------------- summary


@respx.mock
async def test_corpus_summary_reports_timeline_coverage(client):
    """`ingest status` reads this to tell you whether laning data is missing,
    so the outstanding count has to shrink as timelines land."""
    match_id = "EUW1_6000000038"
    await seed_match(client, match_id)

    async with SessionLocal() as session:
        before = await corpus_summary(session)
    assert before["timelines"] + before["timelines_outstanding"] >= 1

    mock_timeline(timeline_payload())
    async with SessionLocal() as session:
        assert await service(session).ensure_timelines(
            await stored_matches(session, match_id)
        ) == 1
        after = await corpus_summary(session)

    assert after["timelines"] == before["timelines"] + 1
    assert after["timelines_outstanding"] == before["timelines_outstanding"] - 1
    # Held plus outstanding is the set of matches a timeline could exist for.
    assert (before["timelines"] + before["timelines_outstanding"]
            == after["timelines"] + after["timelines_outstanding"])
