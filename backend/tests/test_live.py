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
from app.db.models import ChampionStat, MatchupStat, RankedEntry
from app.riot.client import RiotClient
from app.services.live import (
    MIN_RANKED_FOR_AVERAGE as MIN_RANKED,
)
from app.services.live import (
    CorpusRecord,
    LiveGameService,
    LiveParticipant,
    clear_mastery_cache,
    lobby_rank,
    parse_participants,
    spectator_keystone,
    spectator_secondary_style,
    split_riot_id,
)
from app.services.roles import (
    CONFIDENT_AT,
    MEASURED_ACCURACY,
    MEASURED_PLAYERS,
    RolePriors,
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


# ------------------------------------------------ lanes, skins and records
#
# spectator-v5 carries no position, no gold, no items and no score (checked
# field by field on 2026-09-19), so everything below is either inferred from
# what it does carry or read from the stored corpus, and these pin both.

BLUE = [(266, "TOP"), (64, "JUNGLE"), (103, "MIDDLE"), (22, "BOTTOM"), (412, "UTILITY")]
RED = [(122, "TOP"), (254, "JUNGLE"), (238, "MIDDLE"), (51, "BOTTOM"), (117, "UTILITY")]
LANE_SPELLS = {
    "TOP": (4, 12), "JUNGLE": (4, 11), "MIDDLE": (4, 14), "BOTTOM": (4, 7), "UTILITY": (4, 3),
}
LEAGUE = r".*/lol/league/v4/entries/by-puuid/.*"
MASTERY = r".*/lol/champion-mastery/v4/champion-masteries/by-puuid/.*/by-champion/.*"


def full_roster(prefix: str | None = None):
    """Ten players in Riot's spectator shape, all wearing skin 7.

    ``prefix`` makes every puuid unique to one test: the suite shares one
    database, and rank lookups store what they find.
    """
    rows = []
    for team, lineup in ((100, BLUE), (200, RED)):
        for champion, role in lineup:
            puuid = f"{prefix}-{team}-{role}".ljust(78, "0") if prefix else None
            row = spectator_participant(
                puuid=puuid, champion_id=champion, team_id=team,
                riot_id=f"P{champion}#T" if prefix else "Champion",
            )
            row["spell1Id"], row["spell2Id"] = LANE_SPELLS[role]
            row["lastSelectedSkinIndex"] = 7
            rows.append(row)
    return rows


async def lane_priors(_session):
    champion = {c: {role: 100} for c, role in BLUE + RED}
    spell = {role: {a: 100, b: 100} for role, (a, b) in LANE_SPELLS.items()}
    return RolePriors(champion=champion, spell=spell, participants=1000)


@respx.mock
async def test_a_five_a_side_rift_game_is_laid_out_by_lane(monkeypatch):
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    mock_spectator(spectator_game(full_roster()))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)

    assert game.positions_inferred
    assert {p.champion_id: p.position for p in game.participants} == dict(BLUE + RED)
    junglers = [p for p in game.participants if p.position == "JUNGLE"]
    assert len(junglers) == 2
    assert all(p.position_basis == "smite" and p.position_confidence == 1.0 for p in junglers)


@respx.mock
async def test_lanes_are_not_invented_off_the_rift(monkeypatch):
    """ARAM is five a side too, and has no lanes at all."""
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    aram = spectator_game(full_roster())
    aram["mapId"] = 12
    mock_spectator(aram)
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)

    assert not game.positions_inferred
    assert all(p.position is None for p in game.participants)
    assert game.corpus_patch is None


def test_the_skin_a_player_picked_is_kept():
    rows = parse_participants(
        [{**spectator_participant(), "lastSelectedSkinIndex": 7}, spectator_participant()]
    )
    assert rows[0].skin_index == 7
    assert rows[1].skin_index is None, "no skin reported means the base art, not skin 0"


@respx.mock
async def test_bans_keep_their_side_and_pick_order():
    payload = spectator_game([spectator_participant()])
    payload["bannedChampions"] = [
        {"championId": 55, "teamId": 200, "pickTurn": 6},
        {"championId": 83, "teamId": 100, "pickTurn": 1},
        {"championId": -1, "teamId": 200, "pickTurn": 7},
    ]
    mock_spectator(payload)
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    assert game.bans == [(83, 100), (55, 200)]


@respx.mock
async def test_mastery_is_asked_once_per_player_then_cached(monkeypatch):
    """The tab polls every minute while a game runs; that must not cost ten
    mastery calls a minute."""
    clear_mastery_cache()
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    mock_spectator(spectator_game(full_roster("mastery-cache")))
    respx.get(url__regex=LEAGUE).mock(return_value=httpx.Response(200, json=[]))
    mastery = respx.get(url__regex=MASTERY).mock(
        return_value=httpx.Response(
            200, json={"championLevel": 7, "championPoints": 123456, "lastPlayTime": 1}
        )
    )

    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM)
    assert mastery.call_count == 10
    assert all(p.mastery_known and p.mastery.points == 123456 for p in game.participants)

    async with SessionLocal() as session:
        await service(session).for_puuid("z" * 78, PLATFORM)
    assert mastery.call_count == 10, "the second look was served from the cache"
    clear_mastery_cache()


@respx.mock
async def test_never_played_is_an_answer_and_a_failed_lookup_is_not(monkeypatch):
    """Riot's 404 means "no mastery on this champion", which is worth saying.
    A refusal means we did not find out, which must not be said as the same."""
    clear_mastery_cache()
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    roster = full_roster("mastery-answer")
    first_time, refused = roster[0]["puuid"], roster[1]["puuid"]

    def answer(request):
        if first_time in request.url.path:
            return httpx.Response(404, json={"status": {"status_code": 404}})
        if refused in request.url.path:
            # No rate-limit headers: an endpoint refusal, raised at once.
            return httpx.Response(403, json={"status": {"status_code": 403}})
        return httpx.Response(200, json={"championLevel": 3, "championPoints": 9000})

    mock_spectator(spectator_game(roster))
    respx.get(url__regex=LEAGUE).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__regex=MASTERY).mock(side_effect=answer)

    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM)
    by_puuid = {p.puuid: p for p in game.participants}

    assert by_puuid[first_time].mastery_known is True
    assert by_puuid[first_time].mastery is None
    assert by_puuid[refused].mastery_known is False
    assert by_puuid[refused].mastery is None
    clear_mastery_cache()


@respx.mock
async def test_corpus_records_follow_the_champion_page_floor(monkeypatch):
    """Records under the champion page's floor are withheld, a lane's gold lead
    needs enough timelines of its own, and a TEAM matchup is never passed off as
    the lane **without saying so**: it is offered only when no lane record
    clears the floor, and then it arrives labelled."""
    queue, patch = 99901, "T.9"
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)

    async def one_slice(_session):
        return [{"patch": patch, "queue_id": queue, "matches": 1}]

    monkeypatch.setattr("app.services.live.available_slices", one_slice)

    def stat(champion, role, games, wins):
        return ChampionStat(
            patch=patch, queue_id=queue, rank_bracket="ALL",
            champion_id=champion, team_position=role, games=games, wins=wins,
        )

    def lane(champion, enemy, role, games, wins, timelines=0, gold=None, scope="LANE"):
        return MatchupStat(
            patch=patch, queue_id=queue, rank_bracket="ALL", scope=scope,
            team_position=role, champion_id=champion, enemy_champion_id=enemy,
            games=games, wins=wins, timeline_games=timelines, avg_gold_diff_14=gold,
        )

    async with SessionLocal() as session:
        session.add_all([
            stat(266, "TOP", 20, 12),
            stat(103, "MIDDLE", 3, 3),                   # under the floor
            lane(266, 122, "TOP", 8, 5, timelines=6, gold=250.0),
            lane(266, 122, "TOP", 50, 40, scope="TEAM"),  # not the lane record
            lane(103, 238, "MIDDLE", 8, 2, timelines=2, gold=-400.0),
            lane(22, 51, "BOTTOM", 4, 4),                 # under the floor
        ])
        await session.commit()

    mock_spectator(spectator_game(full_roster(), queue_id=queue))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    by_champion = {p.champion_id: p for p in game.participants}

    assert game.corpus_patch == patch
    assert by_champion[266].champion_record == CorpusRecord(
        games=20, wins=12, basis="role", patches=(patch,)
    )
    assert by_champion[103].champion_record is None
    # The lane record wins over the fifty game TEAM row for the same pair.
    assert by_champion[266].lane_record == CorpusRecord(
        games=8, wins=5, gold_diff_14=250.0, timeline_games=6,
        basis="lane", patches=(patch,),
    )
    assert by_champion[103].lane_record.games == 8
    assert by_champion[103].lane_record.gold_diff_14 is None, "two timelines is not a lead"
    assert by_champion[22].lane_record is None


@respx.mock
async def test_the_live_endpoint_carries_lanes_skins_and_mastery(client, monkeypatch):
    """The whole contract, through the API, as the page will read it."""
    clear_mastery_cache()
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)
    roster = full_roster("api-contract")
    searcher = roster[0]["puuid"]
    respx.get(url__regex=r".*/riot/account/v1/accounts/by-riot-id/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": searcher, "gameName": "Contract", "tagLine": "LIVE"}
        )
    )
    respx.get(url__regex=r".*/lol/summoner/v4/summoners/by-puuid/.*").mock(
        return_value=httpx.Response(
            200, json={"puuid": searcher, "profileIconId": 1, "revisionDate": 1,
                       "summonerLevel": 30},
        )
    )
    mock_spectator(spectator_game(roster))
    respx.get(url__regex=LEAGUE).mock(return_value=httpx.Response(200, json=[]))
    respx.get(url__regex=MASTERY).mock(
        return_value=httpx.Response(200, json={"championLevel": 5, "championPoints": 40000})
    )

    response = await client.get("/api/summoner/euw1/Contract/LIVE/live")
    assert response.status_code == 200
    game = response.json()["game"]

    assert game["positions_inferred"] is True
    assert game["position_model"] == {
        "accuracy": MEASURED_ACCURACY, "players_tested": MEASURED_PLAYERS,
        "confident_at": CONFIDENT_AT,
    }
    first = game["participants"][0]
    assert first["position"] == "TOP"
    assert first["skin_tile_url"].endswith("/tile/skin/7")
    assert first["mastery"] == {"level": 5, "points": 40000, "last_play_time": None}
    assert first["mastery_known"] is True
    # A ban carries its own rate where the corpus holds enough of that
    # champion, and null rather than a zero where it does not.
    assert game["bans"] == [
        {
            "champion": game["bans"][0]["champion"],
            "team_id": 100,
            "ban_rate": None,
            "ban_rate_games": 0,
        },
    ]
    # Still true with all of the above added: the spectator key stays here.
    assert "secret-not-ours-to-relay" not in response.text
    clear_mastery_cache()


# ------------------------------------------------- the lane fallback ladder


async def _fallback_lobby(monkeypatch, rows, *, queue: int, patches: list[str]):
    """Drive one lobby against hand seeded matchup rows, and hand back the
    records by champion."""
    monkeypatch.setattr("app.services.live.load_priors", lane_priors)

    async def slices(_session):
        return [{"patch": patch, "queue_id": queue, "matches": 10} for patch in patches]

    monkeypatch.setattr("app.services.live.available_slices", slices)

    async with SessionLocal() as session:
        session.add_all(rows)
        await session.commit()

    mock_spectator(spectator_game(full_roster(), queue_id=queue))
    async with SessionLocal() as session:
        game = await service(session).for_puuid("z" * 78, PLATFORM, with_ranks=False)
    return game, {p.champion_id: p for p in game.participants}


def matchup(patch, queue, champion, enemy, role, games, wins, *, scope="LANE",
            timelines=0, gold=None):
    return MatchupStat(
        patch=patch, queue_id=queue, rank_bracket="ALL", scope=scope,
        team_position=role, champion_id=champion, enemy_champion_id=enemy,
        games=games, wins=wins, timeline_games=timelines, avg_gold_diff_14=gold,
    )


@respx.mock
async def test_a_current_patch_lane_record_is_not_diluted_by_an_older_one(monkeypatch):
    """A record labelled as this patch has to be this patch. Measured coverage
    is 26% on the newest patch alone, and buying the other 8% by mixing in older
    rows under the same label would not be a fair trade."""
    queue = 99903
    game, by_champion = await _fallback_lobby(
        monkeypatch,
        [
            matchup("T.11", queue, 266, 122, "TOP", 10, 7),
            matchup("T.10", queue, 266, 122, "TOP", 40, 20),
        ],
        queue=queue,
        patches=["T.11", "T.10"],
    )
    record = by_champion[266].lane_record
    assert record.basis == "lane"
    assert (record.games, record.wins) == (10, 7)
    assert record.patches == ("T.11",)
    assert game.corpus_patches == ["T.11", "T.10"]


@respx.mock
async def test_two_thin_patches_pool_into_one_record(monkeypatch):
    queue = 99913
    _, by_champion = await _fallback_lobby(
        monkeypatch,
        [
            matchup("T.11", queue, 266, 122, "TOP", 3, 2),
            matchup("T.10", queue, 266, 122, "TOP", 3, 1),
        ],
        queue=queue,
        patches=["T.11", "T.10"],
    )
    record = by_champion[266].lane_record
    assert record.basis == "lane_pooled"
    assert (record.games, record.wins) == (6, 3)
    assert record.patches == ("T.11", "T.10")


@respx.mock
async def test_pooling_applies_the_floor_to_the_total_not_to_each_patch(monkeypatch):
    """Three games on each of two patches is six games. The floor used to live
    in the WHERE clause, where neither row would have survived to be summed."""
    queue = 99923
    _, by_champion = await _fallback_lobby(
        monkeypatch,
        [
            matchup("T.11", queue, 266, 122, "TOP", 3, 2),
            matchup("T.10", queue, 266, 122, "TOP", 1, 0),
        ],
        queue=queue,
        patches=["T.11", "T.10"],
    )
    assert by_champion[266].lane_record is None


@respx.mock
async def test_the_pooled_gold_lead_is_weighted_by_its_timelines(monkeypatch):
    """300 over six timelines pooled with -100 over two is 200, not 100: a mean
    of means would let two games outvote six."""
    queue = 99933
    _, by_champion = await _fallback_lobby(
        monkeypatch,
        [
            matchup("T.11", queue, 266, 122, "TOP", 3, 2, timelines=6, gold=300.0),
            matchup("T.10", queue, 266, 122, "TOP", 3, 1, timelines=2, gold=-100.0),
        ],
        queue=queue,
        patches=["T.11", "T.10"],
    )
    assert by_champion[266].lane_record.gold_diff_14 == pytest.approx(200.0)


@respx.mock
async def test_a_team_scope_record_is_offered_last_and_never_carries_a_gold_lead(monkeypatch):
    """A TEAM row's gold lead is this champion's lead against its own laner in
    games where the named enemy was somewhere on the other team. It is not a
    lead against that enemy, so it is dropped rather than relabelled."""
    queue = 99943
    _, by_champion = await _fallback_lobby(
        monkeypatch,
        [matchup("T.11", queue, 266, 122, "TOP", 88, 50, scope="TEAM",
                 timelines=40, gold=500.0)],
        queue=queue,
        patches=["T.11"],
    )
    record = by_champion[266].lane_record
    assert record.basis == "team"
    assert record.games == 88
    assert record.gold_diff_14 is None
    assert record.timeline_games == 0


@respx.mock
async def test_a_distant_patch_is_never_pooled(monkeypatch):
    """The corpus is crawled rather than exhaustive, so the next patch held can
    be a number or two down. Past that the items and the kits have moved."""
    queue = 99953
    _, by_champion = await _fallback_lobby(
        monkeypatch,
        [
            matchup("T.11", queue, 266, 122, "TOP", 2, 1),
            matchup("T.4", queue, 266, 122, "TOP", 40, 30),
        ],
        queue=queue,
        patches=["T.11", "T.4"],
    )
    assert by_champion[266].lane_record is None
