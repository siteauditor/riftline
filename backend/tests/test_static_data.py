"""Queue naming.

Riot's published queues.json was frozen years ago, so the ids players actually
queue for today ("Swiftplay", "Bravery Arena") are missing from it and reached
the match list as "Queue 1740". These pin the precedence that fixed it.
"""

from __future__ import annotations

from app.services.static_data import StaticDataService


def _service(*, live: object = None, riot: list | None = None) -> StaticDataService:
    service = StaticDataService()
    service._index({}, {}, {}, [], riot or [], live)
    return service


def test_our_own_label_wins_over_every_feed():
    """The queues players talk about daily are written by hand, because Riot
    calls 420 "5v5 Ranked Solo games" and nobody says that."""
    service = _service(live=[{"id": 420, "name": "Ranked Solo"}])
    assert service.queue_name(420) == "Ranked Solo/Duo"


def test_the_live_table_names_a_queue_riot_never_published():
    service = _service(
        live=[{"id": 1740, "name": "Bravery Arena"}],
        riot=[{"queueId": 420, "description": "5v5 Ranked Solo games"}],
    )
    assert service.queue_name(1740) == "Bravery Arena"


def test_live_table_is_read_as_a_list_or_as_an_id_keyed_object():
    """Community Dragon has shipped both shapes."""
    as_object = _service(live={"1740": {"id": 1740, "name": "Bravery Arena"}})
    assert as_object.queue_name(1740) == "Bravery Arena"


def test_riot_description_is_used_when_nothing_else_names_the_queue():
    service = _service(riot=[{"queueId": 1300, "description": "Nexus Blitz games"}])
    # 1300 has a hand-written label, so use an id that does not.
    service2 = _service(riot=[{"queueId": 9999, "description": "Snowdown Showdown games"}])
    assert service.queue_name(1300) == "Nexus Blitz"
    assert service2.queue_name(9999) == "Snowdown Showdown"


def test_the_games_suffix_is_stripped_whatever_its_case():
    """Riot writes "5v5 Ranked Solo games" in the old rows and "Swiftplay Games"
    in the newer ones, and the strip used to be case-sensitive."""
    service = _service(riot=[{"queueId": 9998, "description": "Swiftplay Games"}])
    assert service.queue_name(9998) == "Swiftplay"


def test_an_unnamed_queue_keeps_its_id_rather_than_inventing_a_name():
    """1760 is named by no source we have. A guess would be worse than a number."""
    assert _service().queue_name(1760) == "Queue 1760"
    assert _service().queue_name(None) == "Unknown"


def test_a_missing_live_feed_leaves_the_rest_of_static_data_intact():
    """Community Dragon is optional: it must never cost us champions or items."""
    service = _service(live=None, riot=[{"queueId": 450, "description": "ARAM games"}])
    assert service.queue_names == {}
    assert service.queue_name(450) == "ARAM"


# ------------------------------------------------------------------ chromas


def _with_jayce() -> StaticDataService:
    from app.services.static_data import Champion

    service = StaticDataService()
    service.champions_by_id[126] = Champion(
        id=126, key="Jayce", name="Jayce", title="", tags=[], partype=""
    )
    return service


def test_a_chroma_shows_the_skin_it_recolours():
    """Measured on a live game: Jayce skin 23 is "Resistance Jayce (Obsidian)",
    a chroma of skin 15, and Community Dragon answers 404 for its tile."""
    service = _with_jayce()
    service._index_chromas(
        {"126015": {"id": 126015, "chromas": [{"id": 126023}, {"id": 126024}]}}
    )
    assert service.champion_tile(126, 23).endswith("/126/tile/skin/15")
    assert service.champion_tile(126, 15).endswith("/126/tile/skin/15"), "a skin is itself"
    assert service.champion_tile(126, 7).endswith("/126/tile/skin/7"), "unknown passes through"
    assert service.champion_tile(126, None).endswith("/126/tile")
    assert service.champion_tile(126, 0).endswith("/126/tile")


def test_a_chroma_of_the_base_skin_shows_the_base_art():
    service = _with_jayce()
    service._index_chromas({"126000": {"id": 126000, "chromas": [{"id": 126030}]}})
    assert service.champion_tile(126, 30).endswith("/126/tile")


def test_a_malformed_skins_file_does_not_forget_the_chromas_we_had():
    """An empty result is a reshaped or broken file, not "no chromas exist"."""
    service = _with_jayce()
    service._index_chromas({"126015": {"id": 126015, "chromas": [{"id": 126023}]}})
    service._index_chromas({})
    assert service.chroma_parent == {126023: 126015}


def test_the_chroma_map_survives_the_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.static_data.CACHE_DIR", tmp_path)
    service = _with_jayce()
    service._index_chromas({"126015": {"id": 126015, "chromas": [{"id": 126023}]}})
    service._save_chroma_cache()

    fresh = StaticDataService()
    fresh._load_chroma_cache()
    # JSON object keys come back as strings; the lookup needs them as ints.
    assert fresh.chroma_parent == {126023: 126015}


# ------------------------------------------------------------- champion detail

# championFull.json's shape, cut down to one champion. The strings are Riot's
# own, including the markup, which is the point of several tests below.
AHRI_FULL = {
    "data": {
        "Ahri": {
            "key": "103",
            "partype": "Mana",
            "lore": "Innately connected to the magic of the spirit realm.",
            "allytips": ["Use Charm to set up combos."],
            "enemytips": [],
            "passive": {
                "name": "Essence Theft",
                "description": "After killing 9 minions, Ahri heals.<br>After a takedown, "
                "Ahri heals for a <font color='#ff0'>greater</font> amount.",
                "image": {"full": "Ahri_SoulEater2.png"},
            },
            "spells": [
                {
                    "name": "Orb of Deception", "description": "Throws her orb.",
                    "image": {"full": "AhriQ.png"}, "cooldownBurn": "7",
                    "costBurn": "55/65/75/85/95",
                    "resource": "{{ cost }} {{ abilityresourcename }}", "rangeBurn": "970",
                },
                {
                    "name": "Fox-Fire", "description": "Gains <status>speed</status>.",
                    "image": {"full": "AhriW.png"}, "cooldownBurn": "9/8/7/6/5",
                    "costBurn": "0", "resource": "No Cost", "rangeBurn": "700",
                },
                {
                    "name": "Charm", "description": "Blows a kiss.",
                    "image": {"full": "AhriE.png"}, "cooldownBurn": "12", "costBurn": "60",
                    "resource": "{{ hpcost*100 }}% of current Health", "rangeBurn": "975",
                },
                {
                    "name": "Spirit Rush", "description": "Dashes.",
                    "image": {"full": "AhriR.png"}, "cooldownBurn": "140/120/100",
                    "costBurn": "100", "resource": "{{ cost }} {{ abilityresourcename }}",
                    "rangeBurn": "25000",
                },
            ],
        }
    }
}


def _with_ahri() -> StaticDataService:
    service = StaticDataService()
    service.version = "16.18.1"
    service._index(
        {
            "data": {
                "Ahri": {
                    "key": "103", "name": "Ahri", "title": "the Nine-Tailed Fox",
                    "tags": ["Mage", "Assassin"], "partype": "Mana",
                    "blurb": "Innately <i>connected</i>.",
                    "info": {"attack": 3, "defense": 4, "magic": 8, "difficulty": 5},
                    "stats": {"hp": 590, "hpperlevel": 104, "movespeed": 330},
                }
            }
        },
        {}, {}, [], [],
    )
    return service


def test_the_ratings_and_base_stats_need_only_the_required_file():
    """championFull.json is optional. Without it a champion page keeps its
    ratings and base stats, which champion.json already carries."""
    service = _with_ahri()
    ahri = service.champion(103)
    assert service.lore_by_id == {}
    assert ahri.info == {"attack": 3, "defense": 4, "magic": 8, "difficulty": 5}
    assert ahri.stats["hp"] == 590.0
    assert ahri.blurb == "Innately connected.", "markup never reaches a page"


def _roster(size: int, ad_growth: float) -> dict:
    return {
        "data": {
            f"C{i}": {
                "key": str(1000 + i), "name": f"C{i}", "title": "",
                "stats": {
                    "attackdamage": 60, "attackdamageperlevel": ad_growth,
                    # Some champions really do have no mana growth.
                    "mpperlevel": 0 if i % 3 == 0 else 25,
                },
            }
            for i in range(size)
        }
    }


def test_a_growth_that_is_zero_on_every_champion_is_missing_not_zero():
    """Data Dragon 16.18.1 ships attackdamageperlevel 0 for all 173 champions.
    Taken at its word, every level 18 attack damage equals level 1."""
    service = StaticDataService()
    service._index(_roster(30, 0), {}, {}, [], [])
    assert service.unpublished_growth == {"attackdamageperlevel"}, "a real zero is never roster wide"

    healthy = StaticDataService()
    healthy._index(_roster(30, 3.5), {}, {}, [], [])
    assert healthy.unpublished_growth == set()


def test_a_small_roster_proves_nothing_about_growth():
    service = StaticDataService()
    service._index(_roster(3, 0), {}, {}, [], [])
    assert service.unpublished_growth == set()


def test_abilities_are_read_in_slot_order_with_their_markup_taken_out():
    service = _with_ahri()
    service._index_lore(AHRI_FULL)
    lore = service.champion_lore(103)
    assert [a.slot for a in lore.spells] == ["Q", "W", "E", "R"]
    assert lore.passive.description == (
        "After killing 9 minions, Ahri heals.\nAfter a takedown, Ahri heals for a greater amount."
    ), "a break is a newline and every other tag goes"
    assert lore.spells[1].description == "Gains speed."
    assert service.champion_ability(103, 1).name == "Orb of Deception"
    assert service.champion_ability(103, 5) is None


def test_ability_icons_come_from_two_folders():
    service = _with_ahri()
    service._index_lore(AHRI_FULL)
    lore = service.champion_lore(103)
    assert service.ability_icon(lore.passive).endswith("/16.18.1/img/passive/Ahri_SoulEater2.png")
    assert service.ability_icon(lore.spells[0]).endswith("/16.18.1/img/spell/AhriQ.png")


def test_a_cost_is_said_only_where_it_can_be_said():
    service = _with_ahri()
    service._index_lore(AHRI_FULL)
    q, w, e, r = service.champion_lore(103).spells
    assert q.cost == "55/65/75/85/95 Mana", "the template is costBurn in the champion's resource"
    assert w.cost == "No cost"
    assert e.cost is None, "a template over variables we do not hold is withheld, not half filled"
    assert r.range == "Global", "25000 is Data Dragon's sentinel for a global ability"
    assert q.range == "970"


def test_a_champion_without_a_resource_never_reads_as_costing_none():
    from app.services.static_data import _ability_cost

    spell = {"costBurn": "50", "resource": "{{ cost }} {{ abilityresourcename }}"}
    assert _ability_cost(spell, "None") is None
    assert _ability_cost(spell, "Energy") == "50 Energy"


def _skins() -> dict:
    return {
        "103000": {"id": 103000, "name": "Ahri", "rarity": "kNoRarity", "isLegacy": False},
        "103001": {
            "id": 103001, "name": "Dynasty Ahri", "rarity": "kEpic", "isLegacy": True,
            "skinLines": [{"id": 12}], "description": "Royal <b>blood</b>.",
            "chromas": [{"id": 103050}, {"id": 103051}],
        },
        "103086": {"id": 103086, "name": "Risen Legend Ahri", "rarity": "kShiny"},
    }


def test_the_catalogue_lists_skins_and_counts_chromas_on_their_parent():
    """Data Dragon lists Ahri's chromas as 74 more skins, each with no art."""
    service = _with_ahri()
    service._index_skins(_skins())
    skins = service.champion_skins(103)
    assert [s.num for s in skins] == [0, 1, 86], "base first, and no chroma is a skin"
    base, dynasty, risen = skins
    assert dynasty.chromas == 2
    assert (dynasty.rarity, dynasty.legacy, dynasty.lines) == ("Epic", True, [12])
    assert dynasty.description == "Royal blood."
    assert base.rarity is None, "no rarity is not a rarity called NoRarity"
    assert risen.rarity == "Shiny", "an enum we have not met yet keeps its word"


def test_a_skin_line_has_a_name_and_line_zero_does_not():
    service = _with_ahri()
    service._index_skin_lines([{"id": 0, "name": ""}, {"id": 12, "name": "Dynasty"}])
    assert service.skin_line_name(12) == "Dynasty"
    assert service.skin_line_name(0) is None


def test_a_skin_splash_is_the_centred_cut():
    service = _with_ahri()
    assert service.champion_skin_splash(103, 1).endswith("/103/splash-art/centered/skin/1")
    assert service.champion_skin_splash(103, 0).endswith("/103/splash-art/centered")


def test_the_detail_caches_survive_a_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.static_data.CACHE_DIR", tmp_path)
    service = _with_ahri()
    service._index_lore(AHRI_FULL)
    service._index_skins(_skins())
    service._index_skin_lines([{"id": 12, "name": "Dynasty"}])
    service._save_lore_cache()
    service._save_skin_cache()
    service._save_skin_line_cache()

    fresh = StaticDataService()
    fresh._load_lore_cache()
    fresh._load_skin_cache()
    fresh._load_skin_line_cache()
    assert fresh.lore_by_id == service.lore_by_id
    assert fresh.skins_by_champion == service.skins_by_champion
    assert fresh.skin_lines == {12: "Dynasty"}


def test_a_broken_detail_file_keeps_what_we_had():
    service = _with_ahri()
    service._index_lore(AHRI_FULL)
    service._index_skins(_skins())
    service._index_lore({"data": {}})
    service._index_skins({})
    assert 103 in service.lore_by_id
    assert len(service.champion_skins(103)) == 3
