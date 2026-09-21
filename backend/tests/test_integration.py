"""End-to-end tests through the real HTTP app.

Riot is mocked at the transport layer, but everything above it is the production
code path: routing, the rate limiter, the services, SQLAlchemy, and the response
mappers. That is what makes these worth having -- they catch the normalisation
bugs that unit tests on individual functions miss.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from tests import fixtures as fx


def mock_riot(*, matches: list[dict] | None = None, match_ids: list[str] | None = None):
    """Wire up the Riot endpoints this app actually calls."""
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(200, json=fx.account())
    )
    respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=fx.summoner())
    )
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=fx.league_entries())
    )
    respx.get(url__regex=r".*/lol/champion-mastery/v4/champion-masteries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=fx.masteries())
    )
    if match_ids is not None:
        respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
            return_value=httpx.Response(200, json=match_ids)
        )
    for payload in matches or []:
        mid = payload["metadata"]["matchId"]
        respx.get(url__regex=rf".*/lol/match/v5/matches/{mid}$").mock(
            return_value=httpx.Response(200, json=payload)
        )


# ------------------------------------------------------------------- profile


@respx.mock
async def test_profile_returns_identity_and_every_ranked_queue(client):
    mock_riot()
    response = await client.get("/api/summoner/euw1/Caps/EUW")
    assert response.status_code == 200
    body = response.json()

    assert body["riot_id"] == "Caps#EUW"
    assert body["platform_label"] == "EUW"
    assert body["summoner_level"] == 731
    assert body["profile_icon_url"].endswith("/profileicon/6090.png")

    # Solo queue must sort first: it is the rank people mean by "my rank".
    assert [r["queue"] for r in body["ranks"]] == ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]
    solo = body["ranks"][0]
    assert (solo["tier"], solo["division"], solo["league_points"]) == ("EMERALD", "II", 47)
    assert solo["win_rate"] == pytest.approx(63 / 120)
    assert solo["hot_streak"] is True


@respx.mock
async def test_unknown_riot_id_is_a_404_not_a_500(client):
    respx.get(url__regex=r".*by-riot-id.*").mock(return_value=httpx.Response(404))
    response = await client.get("/api/summoner/euw1/NoSuchPlayer/0000")
    assert response.status_code == 404


async def test_bad_platform_is_rejected_with_the_valid_list(client):
    response = await client.get("/api/summoner/narnia/Caps/EUW")
    assert response.status_code == 400
    assert "na1" in response.json()["detail"]


@respx.mock
async def test_expired_key_surfaces_as_an_actionable_503(client):
    """A dead key gets 401 from Riot, verified live. See test_riot_client."""
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(401))
    response = await client.get("/api/summoner/euw1/Caps/EUW")
    assert response.status_code == 503
    body = response.json()
    assert body["hint"] == "expired_api_key"
    assert "24 hours" in body["detail"]


@respx.mock
async def test_a_withdrawn_endpoint_does_not_blame_the_users_key(client):
    """The opposite failure, and the reason the two were split apart.

    Riot answers an endpoint this key may not call at its edge: 403 with no
    rate-limit headers. Reporting that as an expired key sends people to
    regenerate a key that works perfectly.
    """
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(403))
    response = await client.get("/api/summoner/euw1/Caps/EUW")
    assert response.status_code == 403
    body = response.json()
    assert body["hint"] == "endpoint_unavailable"
    assert "24 hours" not in body["detail"]


@respx.mock
async def test_rate_limit_is_reported_with_a_retry_after(client):
    respx.get(url__regex=r".*").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"})
    )
    response = await client.get("/api/summoner/euw1/Caps/EUW")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.json()["retry_after"] == pytest.approx(7.0)


# ------------------------------------------------------- riot id folding


def test_normalize_riot_name_folds_the_way_riot_matches():
    from app.services.players import normalize_riot_name as n

    # The live case that exposed this: searching "Caps" returns "Cäps".
    assert n("Caps") == n("Cäps") == "caps"
    assert n("HIDE ON BUSH") == n("hideonbush") == "hideonbush"
    assert n("  Faker  ") == "faker"
    assert n("Bjérgsen") == "bjergsen"
    assert n("") == ""


@respx.mock
async def test_a_folded_name_is_served_from_cache_on_the_second_lookup(client):
    """Regression: the most expensive bug possible on a rationed API.

    Riot returned ``Cäps`` for a search of ``Caps``. We stored ``Cäps`` and then
    looked it up by exact match, so the cache never hit and *every* profile view
    spent an account-v1 call. Live, the second lookup earned a real 429.
    """
    from app.config import Settings, get_settings
    from app.main import app

    # Identifiers unique to this test: the suite shares one database, and a
    # player cached by an earlier test would make this pass for the wrong reason.
    puuid = "Z" * 78
    account_route = respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Zöë", "tagLine": "TEST"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(200, json={**fx.summoner(), "puuid": puuid})
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(
        return_value=httpx.Response(200, json=[])
    )

    # The suite runs with zero TTLs so every test hits Riot deterministically;
    # caching is the behaviour under test here, so give it a real TTL.
    cached = Settings(
        RIOT_API_KEY="RGAPI-test-key",
        APP_RATE_LIMITS="1000:1",
        TTL_ACCOUNT=3600,
        TTL_SUMMONER=3600,
        TTL_LEAGUE=3600,
    )
    app.dependency_overrides[get_settings] = lambda: cached
    try:
        first = await client.get("/api/summoner/euw1/Zoe/TEST")
        second = await client.get("/api/summoner/euw1/Zoe/TEST")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == second.status_code == 200
    # Display name keeps Riot's own spelling...
    assert second.json()["riot_id"] == "Zöë#TEST"
    # ...but the plain spelling still finds it, without a second Riot call.
    assert account_route.call_count == 1


# ------------------------------------------------------------------- matches


@respx.mock
async def test_match_history_normalises_a_full_match(client):
    payload = fx.match("EUW1_6000000001", win=True, duration=1820)
    mock_riot(matches=[payload], match_ids=["EUW1_6000000001"])

    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    assert response.status_code == 200
    match = response.json()["matches"][0]

    assert match["win"] is True
    assert match["queue_name"] == "Ranked Solo/Duo"
    assert match["patch"] == "15.18"
    assert match["champion"]["name"] == "Ahri"
    assert (match["kills"], match["deaths"], match["assists"]) == (9, 3, 11)
    assert match["kda"] == pytest.approx(20 / 3)

    # CS must include jungle camps, and be per real minute.
    assert match["cs"] == 202
    assert match["cs_per_min"] == pytest.approx(202 / (1820 / 60))

    # Kill participation is against the player's own team only.
    assert match["kill_participation"] == pytest.approx(20 / (9 + 5 * 4))

    assert match["multi_kill"] == "Double Kill"
    assert [i["id"] for i in match["items"]] == [3153, 3006, 3031, 6673, 3072, 0]
    assert match["trinket"]["id"] == 3340
    assert [s["name"] for s in match["spells"]] == ["Flash", "Teleport"]
    assert match["keystone"]["icon_url"].endswith("PressTheAttack.png")

    # Both teams, five each, with Riot IDs taken from the match payload itself.
    assert [len(t) for t in match["teams"]] == [5, 5]
    assert match["teams"][0][0]["riot_id"] == "Caps#EUW"


@respx.mock
async def test_matches_are_fetched_once_then_served_from_storage(client):
    """The cache is what makes a development key usable, so it is asserted on."""
    payload = fx.match("EUW1_6000000009")
    mock_riot(matches=[payload], match_ids=["EUW1_6000000009"])
    detail_route = respx.routes[-1]

    first = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    calls_after_first = detail_route.call_count
    second = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")

    assert first.status_code == second.status_code == 200
    assert calls_after_first == 1
    # The second request must not have re-fetched the match detail.
    assert detail_route.call_count == 1
    assert second.json()["matches"][0]["match_id"] == "EUW1_6000000009"


@respx.mock
async def test_remakes_are_flagged(client):
    payload = fx.match("EUW1_6000000002", duration=210)
    mock_riot(matches=[payload], match_ids=["EUW1_6000000002"])
    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    assert response.json()["matches"][0]["is_remake"] is True


@respx.mock
async def test_one_broken_match_does_not_sink_the_page(client):
    good = fx.match("EUW1_7000000001")
    mock_riot(matches=[good], match_ids=["EUW1_7000000001", "EUW1_7000000002"])
    respx.get(url__regex=r".*/matches/EUW1_7000000002$").mock(
        return_value=httpx.Response(500)
    )

    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=2")
    assert response.status_code == 200
    ids = [m["match_id"] for m in response.json()["matches"]]
    assert ids == ["EUW1_7000000001"]


# ------------------------------------------------------------------- mastery


@respx.mock
async def test_mastery_response(client):
    mock_riot()
    response = await client.get("/api/summoner/euw1/Caps/EUW/mastery")
    assert response.status_code == 200
    body = response.json()

    assert body["total_points"] == 184_320 + 31_100
    assert body["total_champions_played"] == 2

    top = body["entries"][0]
    assert top["champion"]["name"] == "Ahri"
    assert top["level"] == 12
    assert top["milestone_grades"] == ["S-", "A+"]
    # 4320 / (4320 + 7680)
    assert top["progress_to_next"] == pytest.approx(0.36)

    # Wukong's Data Dragon key is "MonkeyKing"; the icon must use the key, not
    # the display name, or it 404s on the CDN.
    wukong = next(e for e in body["entries"] if e["champion"]["id"] == 62)
    assert wukong["champion"]["name"] == "Wukong"
    assert wukong["champion"]["icon_url"].endswith("/MonkeyKing.png")

    # The shard the table came from, and when. An OCE Riot ID's mastery is read
    # from sg2 while the URL says oc1, and the page has no other way to know.
    assert body["platform"] == "euw1"
    assert body["fetched_at"] > 0

    # Three fields are gone on purpose. `chest_granted` because Riot removed
    # chests in 2024 and it was false on 166 of 166 entries for a real account;
    # `levels` because it was 34 buckets of an unbounded scale that nothing
    # read; `champions_owned_ratio` because it divided by our static roster and
    # so exceeded 1.0 for as long as Data Dragon lagged a champion release.
    assert "chest_granted" not in top
    assert "levels" not in body
    assert "champions_owned_ratio" not in body


@respx.mock
async def test_a_champion_our_static_data_does_not_know_is_still_reported(client):
    """Riot returned champion id 60016 with 665 points on 2026-09-21, and Data
    Dragon does not list it. The entry has to survive, because the player really
    has played it, and `champion_known` is how the page knows to draw a
    placeholder instead of a broken image."""
    mock_riot()
    # Its own account: mastery rows are never deleted, so a puuid another test
    # has already fetched for carries that test's champions too.
    unknown_puuid = "mastery-unknown-champ".ljust(78, "0")
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": unknown_puuid, "gameName": "Newbie", "tagLine": "EUW"}
        )
    )
    respx.get(
        url__regex=r".*/lol/champion-mastery/v4/champion-masteries/by-puuid/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "championId": 103,
                    "championLevel": 4,
                    "championPoints": 20_000,
                    "championPointsSinceLastLevel": 100,
                    "championPointsUntilNextLevel": 900,
                    "lastPlayTime": 1_725_900_000_000,
                },
                {
                    "championId": 60016,
                    "championLevel": 1,
                    "championPoints": 665,
                    "championPointsSinceLastLevel": 665,
                    "championPointsUntilNextLevel": 0,
                    "lastPlayTime": 1_725_800_000_000,
                },
            ],
        )
    )

    body = (await client.get("/api/summoner/euw1/Newbie/EUW/mastery")).json()

    assert body["total_champions_played"] == 2
    unknown = next(e for e in body["entries"] if e["champion"]["id"] == 60016)
    assert unknown["champion_known"] is False
    assert unknown["champion"]["name"] == "Champion 60016"
    assert unknown["champion"]["icon_url"] is None
    assert unknown["tags"] == []
    assert unknown["points"] == 665
    # And a champion we do know still says so, or the flag would be useless.
    known = next(e for e in body["entries"] if e["champion"]["id"] == 103)
    assert known["champion_known"] is True


# -------------------------------------------------------------------- static


async def test_health_reports_budget_and_patch(client):
    response = await client.get("/api/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["riot_key_configured"] is True
    assert body["static_data_version"]
    assert body["rate_limit"]["app"][0]["limit"] == 1000


async def test_champion_list_is_complete_and_sorted(client):
    response = await client.get("/api/static/champions")
    champions = response.json()["champions"]
    assert len(champions) > 160
    assert champions[0]["name"] == "Aatrox"
    assert all(c["icon_url"] for c in champions)


# ------------------------------------------------- regressions from the review


@respx.mock
async def test_has_more_follows_riots_id_count_not_what_we_could_fetch(client):
    """A single unfetchable match must not truncate the rest of a history.

    ``has_more`` used to be ``len(rendered) >= count``. With one dead match in a
    full page that reads as "no more games", and every older page the player has
    becomes unreachable.
    """
    good = fx.match("EUW1_8000000001")
    mock_riot(matches=[good], match_ids=["EUW1_8000000001", "EUW1_8000000002"])
    respx.get(url__regex=r".*/matches/EUW1_8000000002$").mock(
        return_value=httpx.Response(404)
    )

    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=2")
    body = response.json()
    assert len(body["matches"]) == 1  # one really is gone
    assert body["has_more"] is True   # but Riot still returned a full page


@respx.mock
async def test_duplicate_ids_in_one_page_do_not_break_the_transaction(client):
    """Adding the same primary key twice rolls back the whole batch."""
    payload = fx.match("EUW1_8100000001")
    mock_riot(matches=[payload], match_ids=["EUW1_8100000001", "EUW1_8100000001"])

    response = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=2")
    assert response.status_code == 200
    assert [m["match_id"] for m in response.json()["matches"]] == [
        "EUW1_8100000001",
        "EUW1_8100000001",
    ]


@respx.mock
async def test_concurrent_requests_for_a_brand_new_player(client):
    """Several viewers hitting one uncached profile at once must all succeed.

    This is the real shape of the bug, and the weak two-request version of this
    test passed by luck. Every table a cold lookup writes is uniquely keyed --
    players, ranked_entries, champion_masteries, matches -- so simultaneous
    requests race on all of them. Worse, the *recovery* was booby-trapped:

    * a rollback expires every object in the session, so the route's `player`
      became unreadable and blew up with MissingGreenlet far from the cause;
    * reading `player.puuid` inside the exception handler, before rolling back,
      raised PendingRollbackError from the log line describing the failure.

    Eight at once, on all three cold endpoints.
    """
    puuid = "C" * 78
    respx.get(url__regex=r".*/riot/account/v1/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Racer", "tagLine": "EUW"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(200, json={**fx.summoner(), "puuid": puuid})
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(
        return_value=httpx.Response(200, json=fx.league_entries())
    )
    respx.get(url__regex=r".*/lol/champion-mastery/v4/.*").mock(
        return_value=httpx.Response(200, json=fx.masteries())
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["EUW1_8200000001"])
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/EUW1_8200000001$").mock(
        return_value=httpx.Response(200, json=fx.match("EUW1_8200000001"))
    )

    base = "/api/summoner/euw1/Racer/EUW"
    for path in (base, f"{base}/mastery", f"{base}/matches?count=1"):
        responses = await asyncio.gather(
            *(client.get(path) for _ in range(8)), return_exceptions=True
        )
        for r in responses:
            assert not isinstance(r, Exception), f"{path} raised {r!r}"
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


@respx.mock
async def test_keystone_is_found_by_label_not_array_position(client):
    """Riot labels styles; indexing blind swaps keystone and secondary tree."""
    payload = fx.match("EUW1_8300000001")
    me = payload["info"]["participants"][0]
    # Same data, subStyle listed first.
    me["perks"] = {
        "styles": [
            {"description": "subStyle", "style": 8300, "selections": [{"perk": 8304}]},
            {
                "description": "primaryStyle",
                "style": 8000,
                "selections": [{"perk": 8005}],
            },
        ]
    }
    mock_riot(matches=[payload], match_ids=["EUW1_8300000001"])

    match = (
        await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    ).json()["matches"][0]
    # 8005 is Press the Attack (a keystone), 8300 is Inspiration (a tree).
    assert match["keystone"]["id"] == 8005
    assert match["secondary_tree"]["id"] == 8300


@respx.mock
async def test_modes_with_more_than_two_teams_still_render_players(client):
    """Arena runs eight teams; hardcoding 100/200 rendered nobody."""
    payload = fx.match("EUW1_8400000001", queue=1700)
    for i, p in enumerate(payload["info"]["participants"]):
        p["teamId"] = 100 + (i // 2) * 100  # 100,100,200,200,300,300,400,400,500,500
        p["teamPosition"] = ""
    mock_riot(matches=[payload], match_ids=["EUW1_8400000001"])

    match = (
        await client.get("/api/summoner/euw1/Caps/EUW/matches?count=1")
    ).json()["matches"][0]
    assert [len(t) for t in match["teams"]] == [2, 2, 2, 2, 2]
    assert sum(len(t) for t in match["teams"]) == 10


@respx.mock
async def test_a_rename_retires_the_stale_cache_row(client):
    """Two rows folding to one search key would poison the cache permanently."""
    from sqlalchemy import select

    from app.db.base import SessionLocal
    from app.db.models import Player

    old_puuid, new_puuid = "O" * 78, "N" * 78
    respx.get(url__regex=r".*/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(200, json=fx.summoner())
    )
    respx.get(url__regex=r".*/lol/league/v4/.*").mock(
        return_value=httpx.Response(200, json=[])
    )

    route = respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*")
    route.mock(
        return_value=httpx.Response(
            200, json={"puuid": old_puuid, "gameName": "Renamer", "tagLine": "EUW"}
        )
    )
    assert (await client.get("/api/summoner/euw1/Renamer/EUW")).status_code == 200

    # Same Riot ID now belongs to a different account.
    route.mock(
        return_value=httpx.Response(
            200, json={"puuid": new_puuid, "gameName": "Renamer", "tagLine": "EUW"}
        )
    )
    assert (await client.get("/api/summoner/euw1/Renamer/EUW")).status_code == 200

    async with SessionLocal() as s:
        rows = (
            await s.execute(select(Player).where(Player.search_name == "renamer"))
        ).scalars().all()
    # Exactly one row may answer to this Riot ID.
    assert [r.puuid for r in rows] == [new_puuid]


def test_win_counting_sql_is_valid_on_postgres():
    """CAST(boolean AS INTEGER) is an error in Postgres, silently fine in SQLite."""
    from sqlalchemy.dialects import postgresql, sqlite

    from app.services.aggregate import win_as_int

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(win_as_int().compile(dialect=dialect))
        assert "CASE" in sql
        assert "CAST" not in sql


def test_tiers_are_withheld_when_the_slice_is_too_thin():
    """A one-row list makes its only champion "the top 10%", i.e. S tier.

    Live, a 72-match corpus left exactly one champion above min_games and the
    page stamped it S at a 29.9% defensible win rate. Percentiles need a
    distribution; below that we say nothing rather than something false.
    """
    from app.api.routes.meta import ChampionMetaRow, TierListChampion, assign_tiers
    from app.services.aggregate import MIN_ROWS_FOR_TIERS

    def row(wr: float) -> ChampionMetaRow:
        return ChampionMetaRow(
            champion=TierListChampion(id=1, name="X", icon_url=None),
            position="JUNGLE", games=20, wins=10, win_rate=wr,
            confidence_win_rate=wr, pick_rate=0.1, ban_rate=0.1,
            avg_kda=3.0, avg_cs_per_min=7.0, avg_damage=1.0, avg_vision=1.0,
        )

    thin = [row(0.3)]
    assign_tiers(thin)
    assert thin[0].tier is None

    wide = [row(0.6 - i * 0.01) for i in range(MIN_ROWS_FOR_TIERS)]
    assign_tiers(wide)
    assert wide[0].tier == "S"
    assert wide[-1].tier == "D"
    assert all(r.tier is not None for r in wide)


@respx.mock
async def test_a_profile_on_the_wrong_shard_says_where_the_account_lives(client):
    """A Riot ID resolves across a whole region, but a summoner record lives on
    one shard. Searching the wrong one rendered a hollow profile: no avatar,
    "Level -", and "Unranked this season" for an account that had simply never
    played there, which reads as three facts about the player.

    A match id is prefixed with the platform that hosted the game, and that is
    the only thing that can answer this: no endpoint maps a puuid to a shard.
    """
    # Its own puuid: the suite shares a database, and stored matches are the
    # first place `home_platform` looks.
    puuid = "W" * 78
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Shardless", "tagLine": "0403"}
        )
    )
    respx.get(url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            404, json={"status": {"message": "Data not found", "status_code": 404}}
        )
    )
    # Not scoped to oc1: the ranked lookup follows the account to the shard it
    # is actually on, so this has to answer for sg2 as well. This fixture has no
    # ranked entries anywhere, which is what keeps the test about the borrowed
    # identity rather than about ranks.
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    ids = respx.get(
        url__regex=r".*sea\.api\.riotgames\.com/lol/match/v5/matches/by-puuid/.*/ids.*"
    ).mock(return_value=httpx.Response(200, json=["SG2_7412345678"]))
    respx.get(url__regex=r".*sg2\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "puuid": puuid,
                "profileIconId": 4794,
                "revisionDate": 1_726_000_000_000,
                "summonerLevel": 72,
            },
        )
    )

    response = await client.get("/api/summoner/oc1/Shardless/0403")

    assert response.status_code == 200
    body = response.json()
    assert body["plays_on"] == "sg2"
    assert body["plays_on_label"] == "SG"
    assert ids.called
    # The account has one face and one level, and both live on that shard. A
    # blank avatar and a dash read as facts about the player, so they are read
    # from there and flagged as borrowed.
    assert body["identity_from_plays_on"] is True
    assert body["summoner_level"] == 72
    assert body["profile_icon_url"].endswith("/profileicon/4794.png")


@respx.mock
async def test_a_profile_on_the_right_shard_claims_nothing_about_other_shards(client):
    """The hint has to stay absent in the ordinary case, or every normal profile
    carries a puzzling line about another region."""
    mock_riot()
    response = await client.get("/api/summoner/euw1/Caps/EUW")

    assert response.status_code == 200
    body = response.json()
    assert body["summoner_level"] == 731
    assert body["plays_on"] is None
    assert body["plays_on_label"] is None


def test_every_sea_shard_is_reachable():
    """Every SEA name a player might type routes to a shard that still exists.

    The first version of this test put PH and TH on ph2 and th2 and checked only
    that the routing table said so. Neither host resolves: Riot folded both
    shards into SG2. So the table was consistent with itself and wrong about
    the world, and choosing TH on the leaderboard answered 502. They now route
    to sg2, which is where those accounts live.
    """
    from app.riot.routing import Regional, resolve_platform

    for name, platform_id in (
        ("oce", "oc1"), ("sg", "sg2"), ("tw", "tw2"), ("vn", "vn2"),
        ("ph", "sg2"), ("ph2", "sg2"), ("th", "sg2"), ("th2", "sg2"),
    ):
        platform = resolve_platform(name)
        assert platform.id == platform_id
        assert platform.regional is Regional.SEA
        # account-v1 has no SEA host; these collapse to asia.
        assert platform.account_region is Regional.ASIA


def test_no_offered_shard_is_one_riot_has_retired():
    """The leaderboard and search offer PLATFORMS, so nothing retired may be in it.

    Pinned by name rather than by DNS so the suite stays offline. Measured from
    the production host on 2026-09-18: ph2 and th2 do not resolve; sg2, tw2,
    vn2 and oc1 do.
    """
    from app.riot.routing import PLATFORMS

    assert "ph2" not in PLATFORMS
    assert "th2" not in PLATFORMS
    assert {"sg2", "tw2", "vn2", "oc1"} <= set(PLATFORMS)


@respx.mock
async def test_the_two_shards_do_not_overwrite_each_other(client):
    """A level belongs to a platform, and the player row holds one of each.

    Stamping the 404 as a fresh fetch cached "no level" against the puuid, so
    the same account then read as level-less on the shard it really plays on
    for the whole TTL. Measured on a live account that is on SG, not OCE.
    """
    puuid = "X" * 78
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Moved", "tagLine": "0001"}
        )
    )
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7412345678"])
    )
    oc1 = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*"
    ).mock(return_value=httpx.Response(404, json={"status": {"status_code": 404}}))
    sg2 = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/summoner/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "puuid": puuid,
                "profileIconId": 4794,
                "revisionDate": 1_726_000_000_000,
                "summonerLevel": 72,
            },
        )
    )

    # Alternating the two shards is the case that was broken live: whichever
    # page was loaded second overwrote the other one's cached level.
    for _ in range(2):
        wrong = (await client.get("/api/summoner/oc1/Moved/0001")).json()
        assert wrong["plays_on"] == "sg2"
        assert wrong["identity_from_plays_on"] is True
        assert wrong["summoner_level"] == 72
        assert wrong["ranks"] == []

        right = (await client.get("/api/summoner/sg2/Moved/0001")).json()
        assert right["plays_on"] is None
        # Its own record, not a borrowed one.
        assert right["identity_from_plays_on"] is False
        assert right["summoner_level"] == 72
        assert right["profile_icon_url"].endswith("/profileicon/4794.png")

    assert oc1.called and sg2.called


@respx.mock
async def test_the_summoner_cache_is_scoped_to_one_shard():
    """A cached level belongs to a platform, and the row is keyed by puuid.

    Without the scoping, the two shards fought over one cache: stamping the oc1
    miss cached "no level" for sg2, and stamping the sg2 hit then reported level
    72 on the oc1 page. Both were measured on a live account that plays on SG.

    The TTL is zeroed in the test settings, so an end-to-end request cannot tell
    a scoped cache from a cold one. This drives the service directly.
    """
    from app.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import Player, utcnow
    from app.riot.client import RiotClient
    from app.riot.routing import resolve_platform
    from app.services.players import PlayerService

    puuid = "Y" * 78
    oc1 = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*"
    ).mock(return_value=httpx.Response(404, json={"status": {"status_code": 404}}))
    sg2 = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/summoner/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "puuid": puuid,
                "profileIconId": 4794,
                "revisionDate": 1_726_000_000_000,
                "summonerLevel": 72,
            },
        )
    )

    async with SessionLocal() as session:
        session.add(
            Player(
                puuid=puuid,
                game_name="Stamped",
                tag_line="0002",
                search_name="stamped",
                platform="euw1",
                summoner_level=731,
                profile_icon_id=6090,
                summoner_platform="euw1",
                summoner_fetched_at=utcnow(),
            )
        )
        await session.commit()

        settings = get_settings()
        async with RiotClient(settings.riot_api_key) as client:
            service = PlayerService(session, client, settings)
            player = await session.get(Player, puuid)

            # A fresh stamp from another shard must not satisfy this lookup.
            await service.ensure_summoner(player, resolve_platform("oc1"))
            assert oc1.called
            assert player.summoner_level is None
            assert player.profile_icon_id is None
            assert player.summoner_platform == "oc1"
            # The miss is cached, but only against the shard it happened on.
            assert player.summoner_fetched_at is not None

            # And the miss must not be served for a different shard.
            await service.ensure_summoner(player, resolve_platform("sg2"))
            assert sg2.called
            assert player.summoner_level == 72
            assert player.summoner_platform == "sg2"


@respx.mock
async def test_mastery_reads_the_shard_the_account_is_on(client):
    """champion-mastery-v4 answers 200 with an empty list on the wrong shard.

    That is worse than the summoner-v4 404 next door, because there is nothing
    to catch: a real account with 100 champions rendered as one that had never
    touched a champion, and the page said so in good faith.

    Measured on an OCE Riot ID whose account is on SG2: 0 champions on the OCE
    route, 100 and 787,348 points on the SG2 one.
    """
    puuid = "M" * 78
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Mastered", "tagLine": "999"}
        )
    )
    respx.get(url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7412345678"])
    )
    wrong_shard = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(return_value=httpx.Response(200, json=[]))
    right_shard = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "championId": 45,
                    "championLevel": 25,
                    "championPoints": 249_708,
                    "championPointsSinceLastLevel": 9_108,
                    "championPointsUntilNextLevel": 1_892,
                    "lastPlayTime": 1_789_597_438_000,
                    "chestGranted": False,
                    "tokensEarned": 12,
                },
                {
                    "championId": 161,
                    "championLevel": 10,
                    "championPoints": 80_060,
                    "championPointsSinceLastLevel": 4_460,
                    "championPointsUntilNextLevel": 6_540,
                    "lastPlayTime": 1_789_000_000_000,
                    "chestGranted": False,
                    "tokensEarned": 0,
                },
            ],
        )
    )

    response = await client.get("/api/summoner/oc1/Mastered/999/mastery")

    assert response.status_code == 200
    body = response.json()
    assert right_shard.called
    assert not wrong_shard.called
    assert body["total_champions_played"] == 2
    assert body["total_points"] == 329_768
    assert [entry["champion"]["id"] for entry in body["entries"]] == [45, 161]


@respx.mock
async def test_a_live_lookup_asks_the_shard_the_account_is_on(client):
    """spectator-v5 is per shard too, and its answer is a 404 either way.

    "Not in a game" and "wrong shard" are the same response, so this one could
    not be noticed from the outside at all: the tab simply never showed a game.
    """
    puuid = "L" * 78
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Playing", "tagLine": "999"}
        )
    )
    respx.get(url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7412345678"])
    )
    wrong_shard = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/spectator/v5/.*"
    ).mock(return_value=httpx.Response(404, json={"status": {"status_code": 404}}))
    right_shard = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/spectator/v5/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "gameId": 7_412_345_678,
                "gameType": "MATCHED_GAME",
                "gameQueueConfigId": 420,
                "gameMode": "CLASSIC",
                "platformId": "SG2",
                "gameLength": 556,
                "gameStartTime": 1_789_600_000_000,
                "bannedChampions": [],
                "participants": [
                    {
                        "puuid": puuid,
                        "teamId": 100,
                        "championId": 45,
                        "spell1Id": 4,
                        "spell2Id": 14,
                        "perks": {
                            "perkIds": [8214],
                            "perkStyle": 8200,
                            "perkSubStyle": 8300,
                        },
                    }
                ],
            },
        )
    )
    # The rank and mastery lookups for the players in the game are per shard
    # too, so they must follow the account to sg2 as well. Mocked explicitly:
    # both are best-effort lookups that log a failure and carry on, so an
    # unmocked call would pass silently and hide exactly the bug this guards.
    respx.get(url__regex=r".*sg2\.api\.riotgames\.com/lol/league/v4/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    mastery_home = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(return_value=httpx.Response(200, json={"championLevel": 25, "championPoints": 249708}))
    mastery_away = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(return_value=httpx.Response(404, json={"status": {"status_code": 404}}))

    response = await client.get("/api/summoner/oc1/Playing/999/live")

    assert response.status_code == 200
    body = response.json()
    assert right_shard.called
    assert not wrong_shard.called
    assert mastery_home.called and not mastery_away.called
    assert body["game"]["participants"][0]["mastery"]["level"] == 25
    assert body["in_game"] is True
    # The shard actually asked, not the one in the URL. Reporting oc1 for an
    # answer that came from sg2 would be a quiet lie about its provenance.
    assert body["platform"] == "sg2"
    assert body["game"]["queue_id"] == 420


@respx.mock
async def test_ranks_come_from_the_shard_the_account_is_on(client):
    """league-v4 on the wrong shard is an empty list, which renders as unranked.

    The profile already borrowed the level and icon from the home shard, so the
    page showed a level-85 account with a face and "Unranked this season" over
    a real Bronze III. Two of the three facts were right, which is what made it
    convincing.
    """
    puuid = "R" * 78
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": puuid, "gameName": "Ranked", "tagLine": "999"}
        )
    )
    respx.get(url__regex=r".*oc1\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(404, json={"status": {"status_code": 404}})
    )
    respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7412345678"])
    )
    respx.get(url__regex=r".*sg2\.api\.riotgames\.com/lol/summoner/v4/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "puuid": puuid,
                "profileIconId": 7180,
                "revisionDate": 1_726_000_000_000,
                "summonerLevel": 85,
            },
        )
    )
    wrong_shard = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/league/v4/.*"
    ).mock(return_value=httpx.Response(200, json=[]))
    right_shard = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/league/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "queueType": "RANKED_SOLO_5x5",
                    "tier": "BRONZE",
                    "rank": "III",
                    "leaguePoints": 51,
                    "wins": 121,
                    "losses": 156,
                    "hotStreak": False,
                    "inactive": False,
                }
            ],
        )
    )

    response = await client.get("/api/summoner/oc1/Ranked/999")

    assert response.status_code == 200
    body = response.json()
    assert right_shard.called
    assert not wrong_shard.called
    assert body["plays_on"] == "sg2"
    assert body["summoner_level"] == 85
    assert [(r["tier"], r["division"], r["league_points"]) for r in body["ranks"]] == [
        ("BRONZE", "III", 51)
    ]


@respx.mock
async def test_the_mastery_cache_is_scoped_to_one_shard():
    """An empty mastery table read from the wrong shard must not be cached.

    Same shape as the summoner cache above, and the reason it needs its own
    test: the stamp said "fetched at", nothing said "from where", so the empty
    OCE answer satisfied the next SG2 lookup for the whole TTL. That is why
    this outlived the first fix.

    The TTL is zeroed in the test settings, so this drives the service directly
    rather than going through a request, which cannot tell a scoped cache from
    a cold one.
    """
    from app.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import Player, utcnow
    from app.riot.client import RiotClient
    from app.services.players import PlayerService

    # Named rather than the usual repeated letter: the suite shares one
    # database, "C" * 78 already belongs to a test above, and the collision
    # surfaces as a UNIQUE constraint failure a long way from the cause.
    puuid = "mastery-cache-scope".ljust(78, "0")
    oc1 = respx.get(
        url__regex=r".*oc1\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(return_value=httpx.Response(200, json=[]))
    sg2 = respx.get(
        url__regex=r".*sg2\.api\.riotgames\.com/lol/champion-mastery/v4/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[{"championId": 45, "championLevel": 25, "championPoints": 249_708}],
        )
    )

    async with SessionLocal() as session:
        session.add(
            Player(
                puuid=puuid,
                game_name="Cached",
                tag_line="0003",
                search_name="cached",
                platform="oc1",
            )
        )
        await session.commit()

        settings = get_settings()
        async with RiotClient(settings.riot_api_key) as riot:
            service = PlayerService(session, riot, settings)
            player = await session.get(Player, puuid)

            empty = await service.masteries(player, "oc1")
            assert oc1.called
            assert empty == []
            # The miss is stamped, but against the shard it happened on.
            assert player.mastery_platform == "oc1"
            assert player.mastery_fetched_at is not None

            # Freshly stamped a moment ago, and it must still not answer for
            # another shard.
            player.mastery_fetched_at = utcnow()
            found = await service.masteries(player, "sg2")
            assert sg2.called
            assert [m.champion_id for m in found] == [45]
            assert player.mastery_platform == "sg2"


@respx.mock
async def test_the_asked_shard_is_used_when_the_account_is_on_it():
    """The ordinary case must cost nothing.

    Every profile on the right shard would otherwise pay a regional match-ids
    call to be told what it already knew, and most traffic is on the right
    shard.
    """
    from app.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import Player
    from app.riot.client import RiotClient
    from app.riot.routing import resolve_platform
    from app.services.players import PlayerService

    puuid = "asked-shard-is-used".ljust(78, "0")
    ids = respx.get(url__regex=r".*/lol/match/v5/matches/by-puuid/.*/ids.*").mock(
        return_value=httpx.Response(200, json=["SG2_7412345678"])
    )

    async with SessionLocal() as session:
        session.add(
            Player(
                puuid=puuid,
                game_name="Local",
                tag_line="EUW",
                search_name="local",
                platform="euw1",
                summoner_level=731,
                summoner_platform="euw1",
            )
        )
        await session.commit()

        settings = get_settings()
        async with RiotClient(settings.riot_api_key) as riot:
            service = PlayerService(session, riot, settings)
            player = await session.get(Player, puuid)
            euw1 = resolve_platform("euw1")

            assert (await service.effective_platform(player, euw1)).id == "euw1"
            assert not ids.called

            # With no record on the asked shard it goes looking, and believes
            # what the match id says.
            player.summoner_level = None
            assert (await service.effective_platform(player, euw1)).id == "sg2"
            assert ids.called


# ------------------------------------------------------- champion filter


@respx.mock
async def test_a_champion_filter_reads_stored_games_and_calls_riot_for_no_match(client):
    """Riot's history cannot filter by champion, so the filter is the games we
    hold: newest first, paged by offset, with the total, and no match-v5 call.
    Neeko and Nidalee because the suite's other tests store Ahri for Caps."""
    neeko, nidalee = 518, 76
    specs = [
        ("EUW1_9100000001", neeko, 420),
        ("EUW1_9100000002", neeko, 420),
        ("EUW1_9100000003", neeko, 420),
        ("EUW1_9100000004", neeko, 440),
        ("EUW1_9100000005", nidalee, 420),
    ]
    payloads = [fx.match(mid, champion_id=champ, queue=queue) for mid, champ, queue in specs]
    mock_riot(matches=payloads, match_ids=[mid for mid, _, _ in specs])

    loaded = await client.get("/api/summoner/euw1/Caps/EUW/matches?count=5")
    assert loaded.status_code == 200
    assert loaded.json()["source"] == "riot"

    def match_calls() -> int:
        return sum(1 for call in respx.calls if "/lol/match/v5/" in str(call.request.url))

    before = match_calls()

    body = (await client.get(f"/api/summoner/euw1/Caps/EUW/matches?champion={neeko}")).json()
    assert body["source"] == "stored"
    assert body["stored_total"] == 4
    assert [m["match_id"] for m in body["matches"]] == [
        "EUW1_9100000004", "EUW1_9100000003", "EUW1_9100000002", "EUW1_9100000001",
    ]
    assert {m["champion"]["id"] for m in body["matches"]} == {neeko}
    assert body["has_more"] is False

    flex = (
        await client.get(f"/api/summoner/euw1/Caps/EUW/matches?champion={neeko}&queue=440")
    ).json()
    assert [m["match_id"] for m in flex["matches"]] == ["EUW1_9100000004"]
    assert flex["stored_total"] == 1

    first = (
        await client.get(f"/api/summoner/euw1/Caps/EUW/matches?champion={neeko}&count=2")
    ).json()
    second = (
        await client.get(
            f"/api/summoner/euw1/Caps/EUW/matches?champion={neeko}&count=2&start=2"
        )
    ).json()
    assert first["has_more"] is True
    assert second["has_more"] is False
    pages = [m["match_id"] for m in first["matches"] + second["matches"]]
    assert pages == [m["match_id"] for m in body["matches"]], "two pages, no overlap"

    assert match_calls() == before, "a champion filter spends no match call"

