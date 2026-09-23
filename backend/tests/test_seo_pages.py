"""The page manifest and the sitemap: one list, read two ways."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import ChampionStat, ItemStat
from app.services.seo import (
    INDEX_PATCH_MIN_MATCHES,
    Page,
    encode_path,
    pick_index_patch,
    sitemap_xml,
)
from app.services.static_data import Champion, ItemInfo, static_data

PATCH = "S1.00"
DEEP, THIN = 9_401, 9_402
BOUGHT, UNBOUGHT = 39_401, 39_402
COMPUTED = datetime(2026, 9, 20, 3, 20, tzinfo=UTC)


def test_the_index_patch_is_the_newest_settled_one():
    counts = {"16.18": 120, "16.17": 900, "16.9": 2000}
    aggregated = {"16.18", "16.17", "16.9"}
    assert pick_index_patch(counts, aggregated) == "16.17", "16.18 has not settled yet"
    counts["16.18"] = INDEX_PATCH_MIN_MATCHES
    assert pick_index_patch(counts, aggregated) == "16.18"
    # A thin corpus still gets a patch: the newest aggregated one.
    assert pick_index_patch({"16.18": 10}, {"16.18", "16.17"}) == "16.18"
    assert pick_index_patch({}, set()) is None
    # By number, not by text: 16.9 is older than 16.18.
    assert pick_index_patch({"16.9": 900, "16.18": 900}, {"16.9", "16.18"}) == "16.18"


def test_the_sitemap_lists_indexable_pages_only_and_dates_only_what_has_one():
    xml = sitemap_xml("https://example.test", [
        Page(path="/", kind="fixed", indexable=True, changefreq="daily"),
        Page(path="/champions/deep", kind="champion", indexable=True, lastmod=COMPUTED),
        Page(path="/champions/thin", kind="champion", indexable=False, reason="thin"),
    ])
    root = ET.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("s:url", ns)
    locs = [u.find("s:loc", ns).text for u in urls]
    assert locs == ["https://example.test/", "https://example.test/champions/deep"]
    assert urls[0].find("s:lastmod", ns) is None, "a fixed page claims no date"
    assert urls[1].find("s:lastmod", ns).text == "2026-09-20"


@pytest.fixture
async def seeded(monkeypatch):
    monkeypatch.setitem(static_data.champions_by_id, DEEP, Champion(id=DEEP, key="Deep", name="Deep", title=""))
    monkeypatch.setitem(static_data.champions_by_id, THIN, Champion(id=THIN, key="Thin", name="Thin", title=""))
    for item_id, name in ((BOUGHT, "Bought Blade"), (UNBOUGHT, "Unbought Blade")):
        monkeypatch.setitem(static_data.item_infos, item_id, ItemInfo(
            id=item_id, name=name, plaintext="", cost=1, combine_cost=0, sell=0,
            purchasable=True, group="finished",
        ))
    static_data._index_item_slugs()
    async with SessionLocal() as session:
        have = (await session.execute(
            select(ChampionStat.id).where(ChampionStat.patch == PATCH).limit(1)
        )).first()
        if not have:
            session.add_all([
                ChampionStat(patch=PATCH, queue_id=420, rank_bracket="ALL", champion_id=DEEP,
                             team_position="TOP", games=25, wins=13, pool_games=100, computed_at=COMPUTED),
                ChampionStat(patch=PATCH, queue_id=420, rank_bracket="ALL", champion_id=THIN,
                             team_position="MIDDLE", games=4, wins=2, pool_games=100, computed_at=COMPUTED),
                ItemStat(patch=PATCH, queue_id=420, rank_bracket="ALL", item_id=BOUGHT,
                         players=100, holders=40, ordered_players=100, buyers=45, computed_at=COMPUTED),
                ItemStat(patch=PATCH, queue_id=420, rank_bracket="ALL", item_id=UNBOUGHT,
                         players=100, holders=1, ordered_players=100, buyers=2, computed_at=COMPUTED),
            ])
            await session.commit()


async def test_the_manifest_gates_pages_on_the_corpus(client, seeded):
    body = (await client.get("/api/meta/pages")).json()
    by_path = {p["path"]: p for p in body["pages"]}

    for path in ("/", "/tierlist", "/method/score"):
        assert by_path[path]["indexable"] and by_path[path]["required"]

    # The suite's other tests aggregate other patches; whichever is the index
    # patch, these two champions are judged on it, and only the seeded patch
    # holds their rows.
    if body["index_patch"] == PATCH:
        assert by_path["/champions/deep"]["indexable"] is True
        assert by_path["/champions/deep"]["lastmod"] == int(COMPUTED.timestamp() * 1000)
        assert by_path["/items/bought-blade"]["indexable"] is True
    assert by_path["/champions/thin"]["indexable"] is False
    assert "needs 20" in by_path["/champions/thin"]["reason"]
    assert by_path["/items/unbought-blade"]["indexable"] is False
    assert not by_path["/champions/thin"]["required"]


async def test_the_sitemap_is_xml_and_agrees_with_the_manifest(client, seeded):
    response = await client.get("/api/meta/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "max-age=3600" in response.headers["cache-control"]
    root = ET.fromstring(response.text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = {u.find("s:loc", ns).text for u in root.findall("s:url", ns)}

    manifest = (await client.get("/api/meta/pages")).json()
    # The manifest holds the decoded path (a profile's name may hold a space);
    # the sitemap holds the URL.
    expected = {
        f"{manifest['origin']}{encode_path(p['path'])}" for p in manifest["pages"] if p["indexable"]
    }
    assert locs == expected
    assert f"{manifest['origin']}/champions/thin" not in locs
    assert manifest["origin"].startswith("https://")


async def test_a_champion_gets_a_page_for_each_role_the_tier_list_would_rank(client, seeded, monkeypatch):
    """"Pantheon support build" had no page of its own: roles were a query on
    one page, and only the main role was indexed. A role with the tier list's
    sample now has its own path; the main role's path is rendered for links
    but left to the bare page, which is its canonical."""
    flex = 9_403
    monkeypatch.setitem(static_data.champions_by_id, flex, Champion(id=flex, key="Flex", name="Flex", title=""))
    async with SessionLocal() as session:
        seeded_flex = (await session.execute(
            select(ChampionStat.id).where(ChampionStat.patch == PATCH, ChampionStat.champion_id == flex)
        )).first()
        if not seeded_flex:
            session.add_all([
                ChampionStat(patch=PATCH, queue_id=420, rank_bracket="ALL", champion_id=flex,
                             team_position=position, games=games, wins=games // 2, pool_games=100,
                             computed_at=COMPUTED)
                for position, games in (("MIDDLE", 40), ("UTILITY", 22), ("TOP", 5))
            ])
            await session.commit()

    async def the_seeded_patch(_session):
        return PATCH

    monkeypatch.setattr("app.services.seo.index_patch", the_seeded_patch)
    body = (await client.get("/api/meta/pages")).json()
    by_path = {p["path"]: p for p in body["pages"]}

    assert by_path["/champions/flex"]["indexable"] is True
    assert by_path["/champions/flex/support"]["indexable"] is True
    assert by_path["/champions/flex/mid"]["indexable"] is False, "the main role's page is the bare one"
    assert "/champions/flex/top" not in by_path, "five games is not a page"
    assert by_path["/champions"]["indexable"] and by_path["/champions"]["required"]

    sitemap = (await client.get("/api/meta/sitemap.xml")).text
    assert "/champions/flex/support<" in sitemap
    assert "/champions/flex/mid<" not in sitemap
