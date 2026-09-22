"""Champion and item slugs: the name as a URL, resolved either way.

The static data in the suite is whatever a test puts there, so the champions
here are fixtures; the uniqueness check over the real Data Dragon cache runs
only where that cache exists (a workstation), and is skipped in CI.
"""

from __future__ import annotations

import pytest

from app.services.static_data import (
    CACHE_DIR,
    Champion,
    ItemInfo,
    StaticDataService,
    slugify,
    static_data,
)

WUKONG = 9_301
TESTY = 9_302


@pytest.fixture
def roster(monkeypatch):
    monkeypatch.setitem(
        static_data.champions_by_id,
        WUKONG,
        Champion(id=WUKONG, key="MonkeyKing", name="Wukong", title="the Monkey King"),
    )
    monkeypatch.setitem(
        static_data.champions_by_id,
        TESTY,
        Champion(id=TESTY, key="Testy", name="Testy Two", title="the Fixture", blurb="A story."),
    )


def test_a_slug_is_the_name_as_a_url():
    assert slugify("Doran's Blade") == "dorans-blade"
    assert slugify("Blade of The Ruined King") == "blade-of-the-ruined-king"
    assert slugify("Yun Tal Wildarrows") == "yun-tal-wildarrows"
    assert slugify("  Odd   spacing!! ") == "odd-spacing"


def test_champion_slugs_come_from_the_data_dragon_key(roster):
    """The key is stable across renames and already reads as a URL, except
    Wukong's, which nobody would type."""
    assert static_data.champion_slug(WUKONG) == "wukong"
    assert static_data.champion_slug(TESTY) == "testy"
    assert static_data.champion_slug(424242) is None

    # By key rather than id: when another test has loaded the real roster,
    # "wukong" finds the real Wukong first, whose key is the same one.
    assert static_data.champion_by_ref("wukong").key == "MonkeyKing"
    assert static_data.champion_by_ref("Testy").key == "Testy", "case does not matter"
    assert static_data.champion_by_ref(str(TESTY)).id == TESTY, "ids keep working"
    assert static_data.champion_by_ref("monkeyking") is None, "the raw key is not a URL"
    assert static_data.champion_by_ref("nobody") is None


def test_item_slugs_are_unique_with_the_guide_item_taking_the_plain_name():
    service = StaticDataService()
    service.item_infos = {
        3004: ItemInfo(id=3004, name="Manamune", plaintext="", cost=2900, combine_cost=0, sell=0,
                       purchasable=True, group="finished"),
        223004: ItemInfo(id=223004, name="Manamune", plaintext="", cost=2900, combine_cost=0, sell=0,
                         purchasable=True, group=None),
        1055: ItemInfo(id=1055, name="Doran's Blade", plaintext="", cost=450, combine_cost=0, sell=0,
                       purchasable=True, group="starter"),
    }
    service._index_item_slugs()

    assert service.item_slug(3004) == "manamune", "the guide's copy owns the plain slug"
    assert service.item_slug(223004) == "manamune-223004"
    assert service.item_slug(1055) == "dorans-blade"
    assert service.item_by_ref("manamune").id == 3004
    assert service.item_by_ref("manamune-223004").id == 223004
    assert service.item_by_ref("1055").id == 1055
    assert service.item_by_ref("nothing") is None


async def test_the_champion_routes_take_a_slug_or_an_id(client, roster):
    by_slug = await client.get("/api/champions/testy/profile")
    by_id = await client.get(f"/api/champions/{TESTY}/profile")
    assert by_slug.status_code == 200 and by_id.status_code == 200
    assert by_slug.json() == by_id.json()
    assert by_slug.json()["champion"]["slug"] == "testy", "every champion reference carries its slug"

    assert (await client.get("/api/champions/nobody/profile")).status_code == 404
    assert (await client.get("/api/champions/nobody/players")).status_code == 404
    assert (await client.get("/api/champions/nobody")).status_code == 404


@pytest.mark.skipif(not (CACHE_DIR / "champion.json").exists(), reason="needs the Data Dragon cache")
def test_every_real_champion_and_item_slug_is_unique():
    """Against the cached Data Dragon on a workstation: a duplicate slug would
    make two pages one address, and the site would find out from Google."""
    service = StaticDataService()
    assert service._load_disk_cache()
    champion_slugs = [service.champion_slug(c) for c in service.champions_by_id]
    assert len(set(champion_slugs)) == len(champion_slugs) == len(service.champions_by_id)
    assert all(s and s.isascii() and s == s.lower() and " " not in s for s in champion_slugs)
    assert service.champion_by_ref("wukong") is not None
    assert service.champion_by_ref("kaisa") is not None
    item_slugs = list(service.item_slugs.values())
    assert len(set(item_slugs)) == len(item_slugs) == len(service.item_infos)
    guide = [service.item_slug(i.id) for i in service.guide_items()]
    assert all("-" not in s or not s.rsplit("-", 1)[1].isdigit() for s in guide), (
        "a guide item never needs the id appended"
    )
