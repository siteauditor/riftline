"""Live game parsing, and the honesty rules around a partly visible lobby.

The payload these run against mirrors a real spectator response measured on
2026-09-17, including the two things that differ from match-v5 and would
otherwise fail silently: the `perks` shape, and a negative `gameLength` during
champion select.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import RankedEntry
from app.riot.client import RiotClient
from app.services.live import (
    MIN_RANKED_FOR_AVERAGE as MIN_RANKED,
)
from app.services.live import (
    LiveGameService,
    LiveParticipant,
    lobby_rank,
    parse_participants,
    spectator_keystone,
    spectator_secondary_style,
    split_riot_id,
)

PLATFORM = "euw1"


def spectator_participant(
    *, puuid=None, champion_id=15, team_id=100, riot_id="Sivir", bot=False,
    keystone=8008,
):
    """One roster row, in Riot's spectator shape.

    Note `perks` here is `{perkIds, perkStyle, perkSubStyle}`, not the
    `{styles: [...]}` that match-v5 sends. That difference is the point of
    several of these tests.
    """
    row = {
        "championId": champion_id, "teamId": team_id, "riotId": riot_id,
        "spell1Id": 4, "spell2Id": 12, "profileIconId": 1234, "bot": bot,
        "perks": {"perkIds": [keystone, 9111], "perkStyle": 8000, "perkSubStyle": 8300},
    }
    if puuid:
        row["puuid"] = puuid
    return row


def spectator_game(participants, *, game_length=600, queue_id=420):
    return {
        "gameId": 7986457870, "platformId": "EUW1", "gameQueueConfigId": queue_id,
        "gameMode": "CLASSIC", "mapId": 11, "gameType": "MATCHED",
        "gameStartTime": 1789647584224, "gameLength": game_length,
        "bannedChampions": [
            {"championId": 83, "teamId": 100, "pickTurn": 1},
            {"championId": -1, "teamId": 200, "pickTurn": 2},
        ],
        "observers": {"encryptionKey": "secret-not-ours-to-relay"},
        "participants": participants,
    }


def ranked(tier="GOLD", division="II", lp=42, queue="RANKED_SOLO_5x5"):
    return RankedEntry(
        puuid="x", queue_type=queue, tier=tier, division=division,
        league_points=lp, wins=30, losses=20,
    )


def participant(state="ranked", *, tier="GOLD", lp=42, division="II"):
    return LiveParticipant(
        puuid="p" if state not in ("hidden", "bot") else None,
        champion_id=1, team_id=100, spell1_id=4, spell2_id=12,
        keystone_id=8008, secondary_style_id=8300, profile_icon_id=1,
        game_name="n" if state not in ("hidden", "bot") else None,
        tag_line="t" if state not in ("hidden", "bot") else None,
        state=state,
        rank=ranked(tier, division, lp) if state == "ranked" else None,
    )


# ------------------------------------------------------------------- perks


def test_the_spectator_perk_shape_is_read_correctly():
    perks = {"perkIds": [8008, 9111, 9104], "perkStyle": 8000, "perkSubStyle": 8300}
    assert spectator_keystone(perks) == 8008
    assert spectator_secondary_style(perks) == 8300


def test_the_match_v5_perk_shape_yields_nothing_here():
    """The bug this guards: match-v5 sends a completely different structure, and
    reusing its reader against a live payload returns None for every player with
    no error at all."""
    match_v5 = {
        "statPerks": {"offense": 5008},
        "styles": [{"description": "primaryStyle", "selections": [{"perk": 8005}]}],
    }
    assert spectator_keystone(match_v5) is None
    assert spectator_secondary_style(match_v5) is None


@pytest.mark.parametrize("perks", [None, {}, {"perkIds": []}, {"perkIds": ["x"]}])
def test_missing_or_malformed_perks_do_not_raise(perks):
    assert spectator_keystone(perks) is None


# ------------------------------------------------------------- participants


def test_an_identified_player_keeps_their_riot_id():
    rows = parse_participants([spectator_participant(puuid="LIVE-one".ljust(78, "z"), riot_id="Caps#EUW")])
    assert (rows[0].game_name, rows[0].tag_line) == ("Caps", "EUW")
    assert rows[0].state == "unknown", "no rank attached yet"


def test_an_anonymised_player_never_exposes_the_champion_name_as_a_person():
    """Riot puts the champion's own name in `riotId` for a hidden player.
    Rendering it would invent a person; linking it would 404."""
    rows = parse_participants([spectator_participant(riot_id="Sivir", champion_id=15)])
    assert rows[0].state == "hidden"
    assert rows[0].game_name is None
    assert rows[0].tag_line is None
    assert rows[0].puuid is None
    # The champion is still known, which is what the row actually shows.
    assert rows[0].champion_id == 15


def test_a_bot_is_not_a_hidden_human():
    """Both lack a puuid. Conflating them reports five hidden players in every
    co-op lobby."""
    rows = parse_participants([
        spectator_participant(bot=True, riot_id="Ashe"),
        spectator_participant(bot=False, riot_id="Ashe"),
    ])
    assert [r.state for r in rows] == ["bot", "hidden"]


@pytest.mark.parametrize(
    ("riot_id", "expected"),
    [("Caps#EUW", ("Caps", "EUW")), ("Sivir", (None, None)),
     (None, (None, None)), ("", (None, None)), ("Name#", ("Name", None))],
)
def test_split_riot_id(riot_id, expected):
    assert split_riot_id(riot_id) == expected


# -------------------------------------------------------------- lobby rank


def test_the_rank_is_withheld_below_the_floor():
    """Four of ten is a number that would mislead, so there is no number."""
    lobby = [participant("ranked") for _ in range(4)] + [
        participant("hidden") for _ in range(6)
    ]
    result = lobby_rank(lobby, 420)
    assert result.median_points is None
    assert result.tier is None
    assert (result.ranked, result.hidden) == (4, 6)


def test_the_rank_always_carries_its_denominator():
    lobby = (
        [participant("ranked") for _ in range(6)]
        + [participant("unranked")]
        + [participant("hidden") for _ in range(2)]
        + [participant("bot")]
    )
    result = lobby_rank(lobby, 420)
    assert result.median_points is not None
    assert (result.ranked, result.unranked, result.hidden, result.bots) == (6, 1, 2, 1)


def test_an_unranked_player_is_not_counted_as_rank_zero():
    """Counting 'unranked' as rank zero would drag a Challenger lobby to Iron."""
    all_gold = [participant("ranked", tier="GOLD") for _ in range(6)]
    with_unranked = all_gold + [participant("unranked") for _ in range(4)]
    assert lobby_rank(all_gold, 420).median_points == (
        lobby_rank(with_unranked, 420).median_points
    )


def test_one_outlier_cannot_move_the_label():
    """The reason this is a median. A mean over numeric_rank reports nine Gold
    players and one Challenger as 'Diamond III', and a smurf in a low-elo game
    is exactly what anybody looks at this number for."""
    lobby = [participant("ranked", tier="GOLD", division="IV", lp=0) for _ in range(9)]
    lobby.append(participant("ranked", tier="CHALLENGER", division=None, lp=1500))
    result = lobby_rank(lobby, 420)
    assert (result.tier, result.division) == ("GOLD", "IV")


def test_the_label_is_always_a_rank_somebody_in_the_lobby_holds():
    """An interpolated midpoint between Diamond I and Master lands in the gap
    between two tiers and decodes to a rank nobody present has."""
    lobby = [participant("ranked", tier="DIAMOND", division="I", lp=80) for _ in range(4)]
    lobby += [participant("ranked", tier="MASTER", division=None, lp=200) for _ in range(2)]
    result = lobby_rank(lobby, 420)
    held = {("DIAMOND", "I"), ("MASTER", None)}
    assert (result.tier, result.division) in held
    # Diamond has divisions and caps at 100 LP; a blended value had neither.
    if result.tier == "DIAMOND":
        assert result.division is not None
        assert result.league_points <= 100


def test_a_player_we_could_not_look_up_is_not_counted_as_unranked():
    """A failed lookup and a genuinely unranked player are different claims."""
    lobby = [participant("ranked") for _ in range(6)] + [participant("unknown")]
    result = lobby_rank(lobby, 420)
    assert result.ranked == 6
    assert result.unknown == 1
    assert result.unranked == 0, "we did not find out; that is not 'unranked'"


def test_the_label_is_stable_across_runs():
    """The old modal-tier tiebreak resolved by set iteration order, so the same
    lobby could label Master on one run and Grandmaster on the next."""
    lobby = [
        participant("ranked", tier="MASTER", lp=1540, division=None),
        participant("ranked", tier="MASTER", lp=1619, division=None),
        participant("ranked", tier="MASTER", lp=1552, division=None),
        participant("ranked", tier="GRANDMASTER", lp=2023, division=None),
        participant("ranked", tier="GRANDMASTER", lp=2234, division=None),
        participant("ranked", tier="GRANDMASTER", lp=1888, division=None),
    ]
    labels = {lobby_rank(lobby, 420).tier for _ in range(20)}
    assert len(labels) == 1, "the same lobby must label the same way every time"


def test_apex_reports_league_points_because_the_tier_alone_says_little():
    lobby = [
        participant("ranked", tier="CHALLENGER", lp=1000, division=None)
        for _ in range(MIN_RANKED)
    ]
    result = lobby_rank(lobby, 420)
    assert result.tier == "CHALLENGER"
    assert result.division is None
    assert result.league_points == 1000


def test_a_sub_apex_lobby_keeps_its_division():
    lobby = [
        participant("ranked", tier="PLATINUM", division="III", lp=50)
        for _ in range(MIN_RANKED)
    ]
    result = lobby_rank(lobby, 420)
    assert (result.tier, result.division) == ("PLATINUM", "III")


@pytest.mark.parametrize(
    ("queue_id", "queue_type", "matches"),
    [(420, "RANKED_SOLO_5x5", True), (440, "RANKED_FLEX_SR", True),
     (450, "RANKED_SOLO_5x5", False), (0, "RANKED_SOLO_5x5", False)],
)
def test_a_non_ranked_queue_says_so_rather_than_mislabelling(queue_id, queue_type, matches):
    """An ARAM lobby shows solo-queue standing. That is useful, but it is not a
    rank in the queue being played, and the response has to admit it."""
    result = lobby_rank([participant("ranked")], queue_id)
    assert result.queue_type == queue_type
    assert result.queue_matches_game is matches


# ----------------------------------------------------------------- service


def service(session):
    return LiveGameService(session, RiotClient("RGAPI-test-key"), get_settings())


def mock_spectator(payload, *, status=200):
    return respx.get(url__regex=r".*/lol/spectator/v5/active-games/.*").mock(
        return_value=httpx.Response(status, json=payload)
    )


@respx.mock
async def test_a_player_not_in_a_game_is_none_not_an_error():
    mock_spectator(None, status=404)
    async with SessionLocal() as session:
        assert await service(session).for_puuid("z" * 78, PLATFORM) is None


@respx.mock
async def test_champion_select_is_a_phase_not_a_negative_clock():
    """Measured live: gameLength comes back as -28 before the game starts."""
    mock_spectator(spectator_game([spectator_participant()], game_length=-28))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert game.phase == "loading"
    assert game.game_length == 0, "never hand the UI a negative clock"


@respx.mock
async def test_an_in_progress_game_keeps_its_clock():
    mock_spectator(spectator_game([spectator_participant()], game_length=773))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert (game.phase, game.game_length) == ("in_progress", 773)


@respx.mock
async def test_placeholder_bans_are_dropped():
    """Riot sends championId -1 for a skipped ban."""
    mock_spectator(spectator_game([spectator_participant()]))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert game.banned_champion_ids == [83]


@respx.mock
async def test_the_observer_key_never_leaves_the_service():
    """It invites a spectate button we cannot support, and it is not ours to
    relay."""
    mock_spectator(spectator_game([spectator_participant()]))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert "encryptionKey" not in repr(game)


@respx.mock
async def test_an_anonymised_searcher_is_flagged_rather_than_guessed_at():
    """Riot returns the game but no row can be attributed to them, so the view
    must not highlight an arbitrary player as 'you'."""
    mock_spectator(spectator_game([spectator_participant(riot_id="Sivir")]))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert game.you_identified is False


@respx.mock
async def test_the_feature_flag_is_load_bearing(monkeypatch):
    """ENABLE_SPECTATOR reported its state in /api/health and gated nothing.
    When Riot finishes withdrawing the endpoint, this is what turns it off."""
    from app.riot.errors import RiotForbidden

    settings = get_settings()
    monkeypatch.setattr(settings, "enable_spectator", False)
    route = mock_spectator(spectator_game([spectator_participant()]))
    async with SessionLocal() as session:
        with pytest.raises(RiotForbidden):
            await service(session).for_puuid("z" * 78, PLATFORM)
    assert route.call_count == 0, "the flag must short-circuit before Riot is called"


# --------------------------------------------------------------------- api


@respx.mock
async def test_the_api_reports_not_in_a_game_as_a_200(client):
    """A 404 would surface in the UI as "no player found", which is false."""
    from tests.test_integration import mock_riot

    mock_riot()
    mock_spectator(None, status=404)
    response = await client.get("/api/summoner/euw1/Caps/EUW/live")
    assert response.status_code == 200
    body = response.json()
    assert body["in_game"] is False
    assert body["game"] is None
    assert body["checked_at"] > 0


@respx.mock
async def test_the_api_renders_a_live_lobby_with_its_hidden_players(client):
    from tests.test_integration import mock_riot

    mock_riot()
    mock_spectator(spectator_game([
        spectator_participant(
            puuid="LIVE-named".ljust(78, "z"), riot_id="Caps#EUW", champion_id=103
        ),
        spectator_participant(riot_id="Sivir", champion_id=15),
        spectator_participant(bot=True, riot_id="Ashe", champion_id=22),
    ]))
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[{
            "queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND", "rank": "II",
            "leaguePoints": 55, "wins": 100, "losses": 90,
        }])
    )
    body = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()

    assert body["in_game"] is True
    game = body["game"]
    assert game["phase"] == "in_progress"
    assert [c["id"] for c in game["banned_champions"]] == [83]

    states = [p["state"] for p in game["participants"]]
    assert states == ["ranked", "hidden", "bot"]

    named, hidden, bot = game["participants"]
    assert named["riot_id"] == "Caps#EUW"
    assert named["rank"]["tier"] == "DIAMOND"
    assert named["champion"]["name"]

    # The whole point: a hidden row carries a champion and nothing that could be
    # mistaken for a person.
    assert hidden["riot_id"] is None
    assert hidden["puuid"] is None
    assert hidden["rank"] is None
    assert hidden["champion"]["name"] == "Sivir"
    assert bot["riot_id"] is None


@respx.mock
async def test_a_thin_lobby_gets_counts_but_no_rank(client):
    from tests.test_integration import mock_riot

    mock_riot()
    mock_spectator(spectator_game([
        # A puuid of its own: the suite shares one database, so reusing another
        # test's would serve that test's cached rank.
        spectator_participant(puuid="LIVE-thin".ljust(78, "z"), riot_id="Thin#EUW"),
        spectator_participant(riot_id="Sivir"),
        spectator_participant(riot_id="Camille"),
    ]))
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[])
    )
    body = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()
    lobby = body["game"]["lobby_rank"]
    assert lobby["median_points"] is None, "one identified player is not a lobby"
    assert lobby["hidden"] == 2
    assert lobby["ranked"] == 0


@respx.mock
async def test_the_disabled_flag_short_circuits_before_any_riot_call(client, monkeypatch):
    """The service checks the flag too, but by then the route has already spent
    an account-v1 and a summoner-v4 call resolving a player it will not use."""
    from tests.test_integration import mock_riot

    settings = get_settings()
    monkeypatch.setattr(settings, "enable_spectator", False)
    mock_riot()
    account = respx.routes[0]
    spectator = mock_spectator(spectator_game([spectator_participant()]))

    response = await client.get("/api/summoner/euw1/Caps/EUW/live")
    assert response.status_code == 403
    assert response.json()["hint"] == "endpoint_unavailable"
    assert spectator.call_count == 0
    assert account.call_count == 0, "not a single Riot call for a disabled feature"


@respx.mock
async def test_the_lobby_rank_survives_the_dataclass_to_wire_boundary(client):
    """The bridge is `LobbyRankOut(**asdict(...))`, which silently drops a field
    renamed on one side and serves the other side's default. That shipped a null
    rank beside a populated tier, and the UI read it as "not enough identified
    players" for a lobby of eight."""
    from tests.test_integration import mock_riot

    mock_riot()
    roster = [
        spectator_participant(
            puuid=f"WIRE-{i}".ljust(78, "z"), riot_id=f"P{i}#EUW", champion_id=1 + i
        )
        for i in range(10)
    ]
    mock_spectator(spectator_game(roster))
    respx.get(url__regex=r".*/lol/league/v4/entries/by-puuid/.*").mock(
        return_value=httpx.Response(200, json=[{
            "queueType": "RANKED_SOLO_5x5", "tier": "MASTER", "rank": "I",
            "leaguePoints": 400, "wins": 100, "losses": 90,
        }])
    )
    body = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()
    lobby = body["game"]["lobby_rank"]

    assert lobby["median_points"] is not None, "the number must reach the wire"
    assert lobby["tier"] == "MASTER"
    assert lobby["league_points"] == 400
    assert lobby["ranked"] == 10
    # The old names must be gone, not merely unused.
    assert "average_points" not in lobby
    assert "average_league_points" not in lobby


@respx.mock
async def test_an_anonymised_searcher_is_reported_as_such_on_the_wire(client):
    """The service computed `you_identified` and the mapper dropped it, so the
    field defaulted to True and the one case it exists for never reached the UI."""
    from tests.test_integration import mock_riot

    mock_riot()
    mock_spectator(spectator_game([spectator_participant(riot_id="Sivir")]))
    body = (await client.get("/api/summoner/euw1/Caps/EUW/live")).json()
    assert body["game"]["you_identified"] is False
