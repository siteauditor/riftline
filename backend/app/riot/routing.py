"""Platform and regional routing for the Riot API.

Riot splits its hosts into two families and mixing them up is the single most
common source of 404s in third-party League code:

* **Platform hosts** (``na1``, ``euw1``, ``kr`` ...) serve per-shard player state:
  summoner-v4, league-v4, champion-mastery-v4, spectator-v5, champion-rotations.
* **Regional hosts** (``americas``, ``europe``, ``asia``, ``sea``) serve the
  cross-shard services: account-v1 and match-v5.

A PUUID is global, but the *platform* still decides which ladder a player sits on,
so we carry both through the whole stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Regional(StrEnum):
    AMERICAS = "americas"
    EUROPE = "europe"
    ASIA = "asia"
    SEA = "sea"


@dataclass(frozen=True, slots=True)
class Platform:
    """One League shard."""

    id: str           # host prefix used in api.riotgames.com URLs
    label: str        # what players actually call it
    regional: Regional
    # account-v1 only accepts americas/europe/asia, so SEA shards collapse to asia.
    account_region: Regional


def _p(id_: str, label: str, regional: Regional) -> Platform:
    account = Regional.ASIA if regional is Regional.SEA else regional
    return Platform(id=id_, label=label, regional=regional, account_region=account)


PLATFORMS: dict[str, Platform] = {
    p.id: p
    for p in (
        _p("na1", "NA", Regional.AMERICAS),
        _p("br1", "BR", Regional.AMERICAS),
        _p("la1", "LAN", Regional.AMERICAS),
        _p("la2", "LAS", Regional.AMERICAS),
        _p("euw1", "EUW", Regional.EUROPE),
        _p("eun1", "EUNE", Regional.EUROPE),
        _p("tr1", "TR", Regional.EUROPE),
        _p("ru", "RU", Regional.EUROPE),
        _p("me1", "ME", Regional.EUROPE),
        _p("kr", "KR", Regional.ASIA),
        _p("jp1", "JP", Regional.ASIA),
        _p("oc1", "OCE", Regional.SEA),
        _p("sg2", "SG", Regional.SEA),
        _p("ph2", "PH", Regional.SEA),
        _p("th2", "TH", Regional.SEA),
        _p("tw2", "TW", Regional.SEA),
        _p("vn2", "VN", Regional.SEA),
        _p("pbe1", "PBE", Regional.AMERICAS),
    )
}

# Accept what users actually type: "na", "NA1", "euw", "kr" ...
_ALIASES: dict[str, str] = {
    "na": "na1", "br": "br1", "lan": "la1", "las": "la2",
    "euw": "euw1", "eune": "eun1", "eun": "eun1", "tr": "tr1",
    "me": "me1", "mena": "me1", "jp": "jp1", "oce": "oc1", "oc": "oc1",
    "sg": "sg2", "ph": "ph2", "th": "th2", "tw": "tw2", "vn": "vn2",
    "pbe": "pbe1",
}


class UnknownPlatform(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(
            f"Unknown platform {value!r}. Valid: {', '.join(sorted(PLATFORMS))}"
        )
        self.value = value


def resolve_platform(value: Platform | str) -> Platform:
    """Normalise user input ("NA", "na1", "euw") into a Platform.

    Idempotent: an already-resolved Platform passes straight through. Several
    signatures in this codebase advertise ``Platform | str`` and then hand the
    value on to another that re-resolves it, so accepting both here removes a
    whole class of "'Platform' object has no attribute 'strip'".
    """
    if isinstance(value, Platform):
        return value
    key = (value or "").strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return PLATFORMS[key]
    except KeyError:
        raise UnknownPlatform(value) from None


def platform_host(platform: Platform | str) -> str:
    return f"https://{resolve_platform(platform).id}.api.riotgames.com"


def regional_host(regional: Regional | str) -> str:
    value = regional.value if isinstance(regional, Regional) else str(regional)
    return f"https://{value}.api.riotgames.com"
