"""Realistic Riot payloads, shaped exactly like the live API returns them.

These mirror the current DTOs -- notably a SummonerDTO with no ``name`` field
and a LeagueEntryDTO keyed by ``puuid`` -- so the tests fail if we ever drift
back to the pre-2024 shapes that most older code assumes.
"""

from __future__ import annotations

PUUID = "P" * 78
OTHER_PUUID = "Q" * 78


def account(game_name: str = "Caps", tag_line: str = "EUW") -> dict:
    return {"puuid": PUUID, "gameName": game_name, "tagLine": tag_line}


def summoner() -> dict:
    # No `name`, no `accountId`: Riot removed both.
    return {
        "puuid": PUUID,
        "profileIconId": 6090,
        "revisionDate": 1_726_000_000_000,
        "summonerLevel": 731,
    }


def league_entries() -> list[dict]:
    return [
        {
            "leagueId": "abc",
            "puuid": PUUID,
            "queueType": "RANKED_SOLO_5x5",
            "tier": "EMERALD",
            "rank": "II",
            "leaguePoints": 47,
            "wins": 63,
            "losses": 57,
            "hotStreak": True,
            "veteran": False,
            "freshBlood": False,
            "inactive": False,
        },
        {
            "leagueId": "def",
            "puuid": PUUID,
            "queueType": "RANKED_FLEX_SR",
            "tier": "GOLD",
            "rank": "I",
            "leaguePoints": 12,
            "wins": 8,
            "losses": 11,
            "hotStreak": False,
            "veteran": False,
            "freshBlood": True,
            "inactive": False,
        },
    ]


def masteries() -> list[dict]:
    return [
        {
            "puuid": PUUID,
            "championId": 103,
            "championLevel": 12,
            "championPoints": 184_320,
            "championPointsSinceLastLevel": 4_320,
            "championPointsUntilNextLevel": 7_680,
            "lastPlayTime": 1_725_900_000_000,
            "chestGranted": True,
            "tokensEarned": 0,
            "championSeasonMilestone": 3,
            "markRequiredForNextLevel": 2,
            "milestoneGrades": ["S-", "A+"],
        },
        {
            "puuid": PUUID,
            "championId": 62,
            "championLevel": 5,
            "championPoints": 31_100,
            "championPointsSinceLastLevel": 1_100,
            "championPointsUntilNextLevel": 900,
            "lastPlayTime": 1_720_000_000_000,
            "chestGranted": False,
            "tokensEarned": 1,
            "championSeasonMilestone": 1,
            "markRequiredForNextLevel": 2,
            "milestoneGrades": ["B"],
        },
    ]


def _participant(
    *,
    puuid: str,
    champion_id: int,
    champion_name: str,
    team_id: int,
    position: str,
    win: bool,
    k: int,
    d: int,
    a: int,
    name: str,
    tag: str,
) -> dict:
    return {
        "puuid": puuid,
        "riotIdGameName": name,
        "riotIdTagline": tag,
        "championId": champion_id,
        "championName": champion_name,
        "teamId": team_id,
        "teamPosition": position,
        "individualPosition": position,
        "win": win,
        "kills": k,
        "deaths": d,
        "assists": a,
        "champLevel": 16,
        "goldEarned": 13_240,
        "totalMinionsKilled": 190,
        "neutralMinionsKilled": 12,
        "visionScore": 28,
        "totalDamageDealtToChampions": 24_800,
        "totalDamageTaken": 19_100,
        "totalHealsOnTeammates": 0,
        "timePlayed": 1_820,
        "doubleKills": 1,
        "tripleKills": 0,
        "quadraKills": 0,
        "pentaKills": 0,
        "firstBloodKill": False,
        "gameEndedInEarlySurrender": False,
        "summoner1Id": 4,
        "summoner2Id": 12,
        "item0": 3153,
        "item1": 3006,
        "item2": 3031,
        "item3": 6673,
        "item4": 3072,
        "item5": 0,
        "item6": 3340,
        "perks": {
            "styles": [
                {"style": 8000, "selections": [{"perk": 8005}]},
                {"style": 8300, "selections": [{"perk": 8304}]},
            ]
        },
    }


def match(
    match_id: str = "EUW1_6000000001",
    *,
    win: bool = True,
    duration: int = 1820,
    queue: int = 420,
    champion_id: int = 103,
) -> dict:
    """A full match-v5 payload with ten participants."""
    participants = [
        _participant(
            puuid=PUUID,
            champion_id=champion_id,
            champion_name="Ahri",
            team_id=100,
            position="MIDDLE",
            win=win,
            k=9,
            d=3,
            a=11,
            name="Caps",
            tag="EUW",
        )
    ]
    for i in range(1, 10):
        participants.append(
            _participant(
                puuid=f"{i}" * 78,
                champion_id=200 + i,
                champion_name=f"Champ{i}",
                team_id=100 if i < 5 else 200,
                position=["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5],
                win=win if i < 5 else not win,
                k=5,
                d=5,
                a=5,
                name=f"Player{i}",
                tag="EUW",
            )
        )

    return {
        "metadata": {
            "matchId": match_id,
            "participants": [p["puuid"] for p in participants],
        },
        "info": {
            "gameCreation": 1_725_800_000_000,
            "gameDuration": duration,
            "gameEndTimestamp": 1_725_800_000_000 + duration * 1000,
            "gameMode": "CLASSIC",
            "gameType": "MATCHED_GAME",
            "gameVersion": "15.18.704.2255",
            "mapId": 11,
            "platformId": "EUW1",
            "queueId": queue,
            "endOfGameResult": "GameComplete",
            "participants": participants,
            "teams": [
                {"teamId": 100, "win": win, "bans": [{"championId": 64, "pickTurn": 1}]},
                {"teamId": 200, "win": not win, "bans": [{"championId": 157, "pickTurn": 2}]},
            ],
        },
    }
