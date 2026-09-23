"""The item guide's endpoints.

What an item is comes from Riot's item file, which the app loads as it does in
production. How it is used is seeded here on a private queue, so the patch the
page defaults to is this file's and nobody else's.
"""

from __future__ import annotations

import pytest

from app.db.base import SessionLocal
from app.services.aggregate import ALL_BRACKETS, rebuild_item_stats
from tests.test_aggregate import participant, seed

QUEUE = 4421
PATCH = "9.91"
TRINITY, INFINITY_EDGE, KRAKEN = 3078, 3031, 6672
MURAMANA, ARENA_MANAMUNE = 3042, 323004
CHAMPION = 9701


def buyer(won: bool, order: list[int]) -> dict:
    return participant(
        CHAMPION, "MIDDLE", 100, won,
        build_order=order, build_times=[600 + 480 * i for i in range(len(order))],
    )


async def _corpus() -> None:
    from sqlalchemy import func, select

    from app.db.models import Match

    async with SessionLocal() as session:
        if await session.scalar(select(func.count()).where(Match.queue_id == QUEUE)):
            return
    # 36 take Infinity Edge second and win 24; 12 take Kraken Slayer second
    # and win 3. Everyone opens with Trinity Force.
    players = (
        [buyer(i < 24, [TRINITY, INFINITY_EDGE]) for i in range(36)]
        + [buyer(i < 3, [TRINITY, KRAKEN]) for i in range(12)]
    )
    await seed(PATCH, [[p] for p in players], queue_id=QUEUE)
    async with SessionLocal() as session:
        await rebuild_item_stats(
            session, patch=PATCH, queue_id=QUEUE, rank_bracket=ALL_BRACKETS
        )


@pytest.fixture
async def corpus():
    await _corpus()


async def test_the_list_is_sectioned_and_leaves_out_what_is_not_sold(client):
    body = (await client.get("/api/items")).json()
    sections = {s["key"]: {i["id"] for i in s["items"]} for s in body["sections"]}
    assert list(sections) == [
        "finished", "boots", "starter", "support", "component", "consumable", "trinket",
    ]
    listed = set().union(*sections.values())
    assert INFINITY_EDGE in sections["finished"]
    assert 1036 in sections["component"], "Long Sword: a Lane tag, but a component"
    assert ARENA_MANAMUNE not in listed, "another mode's copy"
    assert MURAMANA not in listed, "listed under the Manamune that was bought"
    assert all(i["stats"] for i in body["sections"][0]["items"]), "every finished item has stats"


async def test_an_item_page_scores_each_slot_against_the_same_champion(client, corpus):
    body = (await client.get(f"/api/items/{INFINITY_EDGE}?queue_id={QUEUE}")).json()
    assert body["name"] == "Infinity Edge"
    assert any(s["label"] == "Critical Strike Damage" for s in body["stats"]), (
        "read from the description; Riot's stats object leaves it out"
    )
    assert "Pickaxe" in [r["name"] for r in body["builds_from"]]

    figures = body["figures"]
    assert figures["patch"] == PATCH
    assert figures["ordered_players"] == 48
    assert figures["buyers"] == 36
    (second,) = figures["slots"]
    assert (second["slot"], second["games"]) == (2, 36)
    # Infinity Edge wins 24 of 36; the champion's other 2nd item, Kraken, 3 of 12.
    assert second["delta"] == pytest.approx(24 / 36 - 3 / 12)
    assert figures["delta"] == pytest.approx(second["delta"])
    assert figures["minute_p50"] == pytest.approx(18.0)

    (row,) = figures["champions"]
    assert row["buyers"] == 36
    assert row["share"] == pytest.approx(36 / 48)
    assert row["usual_slot"] == 2


async def test_a_thin_slot_is_withheld_and_says_its_floor(client, corpus):
    """Kraken Slayer's 12 purchases are under the 30 a figure needs."""
    figures = (await client.get(f"/api/items/{KRAKEN}?queue_id={QUEUE}")).json()["figures"]
    (second,) = figures["slots"]
    assert second["games"] == 12
    assert second["delta"] is None
    assert figures["delta"] is None
    assert figures["slot_min_games"] == 30
    assert figures["champions"][0]["delta"] is None, "12 buyers, under the champion floor"


async def test_an_item_nobody_bought_gets_zero_against_a_real_denominator(client, corpus):
    body = (await client.get(f"/api/items/3157?queue_id={QUEUE}")).json()
    figures = body["figures"]
    assert figures["buyers"] == 0
    assert figures["ordered_players"] == 48
    assert figures["slots"] == [] and figures["champions"] == []


async def test_a_grown_item_points_at_the_item_that_was_bought(client, corpus):
    body = (await client.get(f"/api/items/{MURAMANA}?queue_id={QUEUE}")).json()
    assert body["group"] == "transformed"
    assert body["grows_from"]["name"] == "Manamune"
    assert body["figures"] is None
    assert "Manamune" in body["figures_note"]


async def test_another_modes_copy_has_a_page_but_no_figures(client):
    body = (await client.get(f"/api/items/{ARENA_MANAMUNE}")).json()
    assert body["on_rift"] is False
    assert body["figures"] is None
    assert "Summoner's Rift" in body["figures_note"]


async def test_an_unknown_item_is_a_404(client):
    assert (await client.get("/api/items/987654")).status_code == 404
