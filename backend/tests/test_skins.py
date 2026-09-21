"""Skin sightings.

Riot publishes no skin for a finished game, so a skin board can only be built
from live lookups as they happen. These pin the rules that keep that board
honest: each player counts once per game however often the page polls, nothing
is counted before the game starts, bots are not players, a chroma counts as the
skin it recolours, and no per skin figure appears below the floor.
"""

from __future__ import annotations

from types import SimpleNamespace

import respx
from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.db.models import SkinSighting
from app.services.skins import (
    MIN_BOARD_SKINS,
    MIN_CHAMPION_SIGHTINGS,
    MIN_SKIN_SIGHTINGS,
    champion_skin_counts,
    record_sightings,
    top_skins,
)
from tests.test_live import PLATFORM, mock_spectator, service, spectator_game, spectator_participant

# Champion ids no other test seeds, so the counts below are ours alone.
LUX, JAYCE, SPARE = 9_001, 9_002, 9_003


def player(champion_id: int, skin: int | None, *, bot: bool = False):
    return SimpleNamespace(
        champion_id=champion_id, skin_index=skin, state="bot" if bot else "unknown"
    )


async def sightings(**where) -> list[SkinSighting]:
    async with SessionLocal() as session:
        stmt = select(SkinSighting)
        for column, value in where.items():
            stmt = stmt.where(getattr(SkinSighting, column) == value)
        return list((await session.execute(stmt)).scalars())


async def record(game_id: int, players, *, in_progress: bool = True, chromas=None) -> int:
    return await record_sightings(
        platform="EUW1",
        game_id=game_id,
        queue_id=420,
        in_progress=in_progress,
        participants=players,
        chroma_parent=chromas or {},
    )


async def test_each_player_counts_once_however_often_the_page_polls():
    game = 880_000_001
    lobby = [player(SPARE, n) for n in range(10)]
    assert await record(game, lobby) == 10
    # The live page polls. The same ten players must not become twenty.
    assert await record(game, lobby) == 0
    assert len(await sightings(game_id=game)) == 10


async def test_nothing_is_counted_before_the_game_starts():
    """A skin picked in champion select can still change before loading."""
    game = 880_000_002
    assert await record(game, [player(SPARE, 3)], in_progress=False) == 0
    assert await sightings(game_id=game) == []


async def test_a_bot_is_not_a_player():
    game = 880_000_003
    assert await record(game, [player(SPARE, 0, bot=True), player(SPARE, 2)]) == 1
    rows = await sightings(game_id=game)
    assert [r.participant_index for r in rows] == [1], "the slot keeps its place in the lobby"


async def test_a_player_with_no_skin_reported_is_skipped():
    game = 880_000_004
    assert await record(game, [player(SPARE, None)]) == 0


async def test_a_chroma_is_counted_as_the_skin_it_recolours():
    """Jayce 23 is "Resistance Jayce (Obsidian)", a chroma of skin 15, and has
    no art of its own: a board listing it would draw a broken image."""
    game = 880_000_005
    await record(game, [player(JAYCE, 23)], chromas={JAYCE * 1000 + 23: JAYCE * 1000 + 15})
    (row,) = await sightings(game_id=game)
    assert row.skin_num == 15
    assert row.platform == "euw1", "stored lower case, as every other platform column"


async def test_no_puuid_is_stored():
    """The board needs to know what was worn, never by whom."""
    assert "puuid" not in SkinSighting.__table__.columns


async def test_counts_are_withheld_below_the_floor():
    game = 880_000_100
    await record(game, [player(LUX, 1) for _ in range(MIN_CHAMPION_SIGHTINGS - 1)])
    async with SessionLocal() as session:
        thin = await champion_skin_counts(session, LUX)
    assert thin.total == MIN_CHAMPION_SIGHTINGS - 1
    assert thin.by_skin == {}, "19 sightings is whoever happened to be looked up"

    await record(game + 1, [player(LUX, 7)])
    async with SessionLocal() as session:
        enough = await champion_skin_counts(session, LUX)
    assert enough.total == MIN_CHAMPION_SIGHTINGS
    assert enough.by_skin == {1: MIN_CHAMPION_SIGHTINGS - 1, 7: 1}


async def test_the_site_board_skips_base_skins_and_thin_ones():
    async with SessionLocal() as session:
        before = await session.scalar(select(func.count()).select_from(SkinSighting))
    base = 880_000_200
    # Base skins everywhere, one real skin seen often, one seen once.
    await record(base, [player(SPARE, 0) for _ in range(10)])
    for i in range(MIN_BOARD_SKINS):
        await record(base + 1 + i, [player(SPARE, 40 + i) for _ in range(MIN_SKIN_SIGHTINGS)])
    await record(base + 9, [player(SPARE, 99)])

    async with SessionLocal() as session:
        total, board = await top_skins(session, limit=50)
    assert total == before + 10 + MIN_BOARD_SKINS * MIN_SKIN_SIGHTINGS + 1
    listed = {(s.champion_id, s.skin_num) for s in board}
    assert (SPARE, 0) not in listed, "the base skin is what a player wears by not choosing"
    assert (SPARE, 99) not in listed, "one sighting is not a ranking"
    assert {(SPARE, 40 + i) for i in range(MIN_BOARD_SKINS)} <= listed


@respx.mock
async def test_a_live_lookup_records_the_lobby():
    """The wiring: a real spectator payload, through the service."""
    payload = spectator_game(
        [
            {**spectator_participant(champion_id=SPARE, riot_id=f"P{i}#EUW"),
             "lastSelectedSkinIndex": i}
            for i in range(10)
        ],
        game_length=600,
    )
    payload["gameId"] = 880_000_300
    mock_spectator(payload)
    async with SessionLocal() as session:
        await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
        await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    rows = await sightings(game_id=880_000_300)
    assert sorted(r.skin_num for r in rows) == list(range(10))


@respx.mock
async def test_a_lookup_in_champion_select_records_nothing():
    payload = spectator_game(
        [{**spectator_participant(champion_id=SPARE), "lastSelectedSkinIndex": 4}],
        game_length=-28,
    )
    payload["gameId"] = 880_000_301
    mock_spectator(payload)
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert game.phase == "loading"
    assert await sightings(game_id=880_000_301) == []


async def test_the_board_endpoint_is_empty_rather_than_thin(client):
    body = (await client.get("/api/skins/top")).json()
    assert body["min_sightings"] == MIN_SKIN_SIGHTINGS
    assert all(s["sightings"] >= MIN_SKIN_SIGHTINGS for s in body["skins"])
    assert all(s["num"] != 0 for s in body["skins"])
