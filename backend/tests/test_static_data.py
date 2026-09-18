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
