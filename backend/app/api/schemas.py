"""Response models.

These are the contract the frontend codes against, so they are deliberately
*presentation-shaped*: icon URLs are resolved here, not in React, and derived
numbers (KDA, CS/min, kill participation, win rate) are computed once on the
server rather than in five different components.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.db.models import ChampionMastery, Match, MatchParticipant, Player, RankedEntry
from app.services.homes import ShardView
from app.services.profile_stats import MIN_SCORED_FOR_PROFILE
from app.services.queues import QueueScope
from app.services.roles import CONFIDENT_AT, MEASURED_ACCURACY, MEASURED_PLAYERS
from app.services.scores import (
    BADGES_BY_ID,
    COMPONENT_LABELS,
    COMPONENTS,
    MIN_GAMES_FOR_SCORE,
    WEIGHTS,
    WEIGHTS_VERSION,
    ScoreWithheld,
    badge_detail,
    withheld_reason,
)
from app.services.static_data import StaticDataService, static_data

if TYPE_CHECKING:
    from app.services.live import PlayedRecord, PlayerRecord
    from app.services.matches import PlayedRow

# Ranked tiers, lowest to highest. Used for sorting and for the rank-bracket filter.
TIER_ORDER = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
    "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
DIVISION_ORDER = ["IV", "III", "II", "I"]

# Apex tiers, lowest to highest. They carry no division and their LP is
# unbounded, so `numeric_rank` scores them on their own scale starting just
# above the highest sub-apex value (Diamond I at 100 LP scores 2,799). The
# stride is comfortably wider than any attainable LP total, which keeps tier
# ahead of LP across tiers while LP still orders players within one.
APEX_TIERS = ("MASTER", "GRANDMASTER", "CHALLENGER")
APEX_BASE = 2800
# Headroom, not a snug fit. EUW's top Challenger was on 4,724 LP when this was
# written and that ceiling rises every split; at a stride of 6,000 a single
# record-breaking split would push a Master past the Grandmaster band and decode
# as the wrong tier with nothing to notice it.
APEX_STRIDE = 100_000
APEX_LP_CAP = APEX_STRIDE - 1

# Queues that have a rank of their own. Anything else shows solo-queue
# standing, which is useful but is a different claim and is labelled as one.
RANKED_QUEUE_BY_ID = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}

# The live view withholds a lobby label below this many identified players.
# Stored matches use the same floor, so the two cannot disagree about what
# counts as enough to label.
MIN_RANKED_FOR_LOBBY_RANK = 6

# The floors the live page applies to a player's own record. Declared here, and
# read by `app/services/live.py`, because that module imports this one: the
# import cannot run the other way.
MIN_RECORD_GAMES = 3
MIN_GAMES_FOR_WIN_RATE = 10

QUEUE_LABELS = {
    "RANKED_SOLO_5x5": "Ranked Solo/Duo",
    "RANKED_FLEX_SR": "Ranked Flex",
    "RANKED_FLEX_TT": "Ranked Flex 3v3",
}


# Fixed vocabularies, spelled as types so the OpenAPI document, and the
# frontend types generated from it, carry the words rather than "string".
LaneLabel = Literal["won_big", "won", "even", "lost", "lost_big"]
RecordBasis = Literal["role", "lane", "lane_pooled", "team"]
RankState = Literal["ranked", "unranked", "hidden", "bot", "unknown"]


class ChampionRef(BaseModel):
    id: int
    name: str
    icon_url: str | None = None

    # The name as a URL, computed here so every champion reference the API
    # sends links the same way, wherever it was built. It reads the loaded
    # static data; an unknown id (a test fixture, a champion newer than the
    # cache) simply has none and the page links by id.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str | None:
        return static_data.champion_slug(self.id)


class ItemRef(BaseModel):
    id: int
    name: str | None = None
    icon_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str | None:
        return static_data.item_slug(self.id)


class SpellRef(BaseModel):
    id: int | None = None
    name: str | None = None
    icon_url: str | None = None


class RuneRef(BaseModel):
    id: int | None = None
    # Riot's name, so a page can say which rune an icon is; icons alone left a
    # rune page as eleven unlabelled pictures.
    name: str | None = None
    icon_url: str | None = None


def rune_ref(rune_id: int, sd: StaticDataService) -> RuneRef:
    """A rune, tree or stat shard with its name and icon."""
    return RuneRef(id=rune_id, name=sd.rune_name(rune_id), icon_url=sd.rune_icon(rune_id))


class RankInfo(BaseModel):
    queue: str
    queue_label: str
    tier: str | None = None
    division: str | None = None
    league_points: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    games: int = 0
    hot_streak: bool = False
    inactive: bool = False
    # Sortable rank as a single number, for leaderboards and bracket filters.
    numeric_rank: int = 0


class LadderPositionOut(BaseModel):
    """Where the player stands on the stored solo ladder of their home shard."""

    tier: str
    tier_position: int
    # Across the whole region. Null when a higher tier's size is unknown.
    position: int | None = None
    platform: str
    platform_label: str
    # Epoch ms of the ladder snapshot this was read from.
    as_of: int


class RankPointOut(BaseModel):
    # Epoch ms.
    at: int
    tier: str | None = None
    division: str | None = None
    league_points: int = 0
    wins: int = 0
    losses: int = 0
    # One sortable scale across tiers, which is what a graph plots.
    numeric_rank: int = 0


class RankHistoryResponse(BaseModel):
    queue_type: str
    # Epoch ms of the first reading, null when there is none yet.
    tracking_since: int | None = None
    points: list[RankPointOut] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    puuid: str
    game_name: str | None = None
    tag_line: str | None = None
    riot_id: str
    # The shard in the URL, in its canonical spelling (th2 is sg2).
    platform: str
    platform_label: str
    # How the asked shard relates to the account: "home" is where it plays;
    # "second" is another shard where it holds a rank or stored games, read
    # live and stored nowhere; "absent" is a shard where it holds neither, and
    # everything below then describes the home shard.
    shard: Literal["home", "second", "absent"] = "home"
    # The shard the account plays on, as Riot's active-region lookup names it.
    home_platform: str
    home_platform_label: str
    summoner_level: int | None = None
    profile_icon_url: str | None = None
    ranks: list[RankInfo] = Field(default_factory=list)
    # Set only when `shard` is "absent": the level, the icon and the ranks are
    # the home shard's, and the page moves to that shard's address.
    plays_on: str | None = None
    plays_on_label: str | None = None
    # True when the level and icon above were read from `plays_on` rather than
    # from the platform in the URL, which the page has to say out loud.
    identity_from_plays_on: bool = False
    # Epoch ms of the rank reading shown, so the page can say how old it is.
    updated_at: int | None = None
    ladder: LadderPositionOut | None = None
    # "stored" when the answer was read from storage alone: asked for, or
    # given to a render that found the key too busy to spend on it.
    source: Literal["live", "stored"] = "live"


class BadgeOut(BaseModel):
    """A badge with the rule that earned it and this player's own figure.

    The detail is composed per request rather than stored, so the wording can
    improve without rescoring the corpus, and a badge can never appear with an
    explanation that no longer matches the rule that awarded it.
    """

    id: str
    label: str
    detail: str


class ScoreComponentOut(BaseModel):
    """One of the seven things the Riftline score is made of."""

    id: str
    label: str
    measures: str
    # Where this player fell in their role's distribution, 0 to 1.
    percentile: float
    # What that component is worth for this role, 0 to 1. Published so the
    # number can be checked rather than believed.
    weight: float


class ParticipantBrief(BaseModel):
    puuid: str
    riot_id: str | None = None
    champion: ChampionRef
    team_id: int
    position: str | None = None
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    win: bool = False
    # The Riftline score and where it placed in this lobby. Null together: a
    # placement without a score would be a ranking with nothing behind it.
    score: float | None = None
    placement: int | None = None
    badges: list[BadgeOut] = Field(default_factory=list)


class MatchSummary(BaseModel):
    """One row of match history, from the searched player's point of view."""

    match_id: str
    queue_id: int
    queue_name: str
    patch: str | None = None
    game_creation: int
    game_duration: int
    is_remake: bool = False

    win: bool
    champion: ChampionRef
    champ_level: int = 0
    position: str | None = None

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    kda: float = 0.0
    kill_participation: float = 0.0

    cs: int = 0
    cs_per_min: float = 0.0
    gold_earned: int = 0
    vision_score: int = 0
    damage_to_champions: int = 0
    damage_per_min: float = 0.0

    items: list[ItemRef] = Field(default_factory=list)
    trinket: ItemRef | None = None
    spells: list[SpellRef] = Field(default_factory=list)
    keystone: RuneRef | None = None
    secondary_tree: RuneRef | None = None

    multi_kill: str | None = None

    # From the match timeline, so null until that match has been backfilled.
    # The row renders the chip only when it is present: fetching a timeline on
    # demand would double the cost of the most common action in the product.
    laning_score: float | None = None
    laning_opponent: ChampionRef | None = None
    # By the lane's distance from even against the role's spread. Null with
    # no timeline or a thin role.
    laning_label: LaneLabel | None = None
    gold_diff_14: int | None = None
    cs_diff_14: int | None = None

    # Measured lobby rank, null until `scripts.ingest lobbyranks` has run.
    #
    # `lobby_rank_measured_at` is not decoration: this is every player's rank on
    # that date, not their rank on the day the game was played, because Riot
    # exposes no historical rank. The UI shows the date with the badge so the
    # claim stays the one we can actually support.
    lobby_rank_points: float | None = None
    lobby_rank_tier: str | None = None
    lobby_rank_division: str | None = None
    lobby_ranked_players: int | None = None
    lobby_players_total: int | None = None
    lobby_rank_measured_at: int | None = None
    # False for ARAM, Arena and normals, where the rank averaged is the players'
    # solo-queue standing and not a rank in the mode actually played. Without
    # this the badge on an Arena game reads as an Arena rank.
    lobby_queue_matches_game: bool = True

    # The Riftline score, null until `scripts.ingest score` has run and withheld
    # for good on any lobby it cannot measure: not ten players with lane roles, a
    # remake, or a queue our corpus is too thin to be a percentile of. A dash is
    # the honest rendering; a 5.0 would be a claim.
    score: float | None = None
    placement: int | None = None
    # Why `score` is null, when it is: the page words each reason, and says
    # "not scored yet" only when it is true.
    score_withheld: ScoreWithheld | None = None
    badges: list[BadgeOut] = Field(default_factory=list)
    # The seven components behind the score, and the sample they were measured
    # against, so the number can be taken apart in the UI.
    score_components: list[ScoreComponentOut] = Field(default_factory=list)
    score_sample: int | None = None

    teams: list[list[ParticipantBrief]] = Field(default_factory=list)


class ScoreboardPlayer(BaseModel):
    """One player on the expanded scoreboard.

    Everything the row cannot fit. Served from its own endpoint rather than in
    the history payload: twenty matches times ten players times this many fields
    is a page nobody asked for on every scroll.
    """

    puuid: str
    riot_id: str | None = None
    champion: ChampionRef
    team_id: int
    position: str | None = None
    win: bool = False
    champ_level: int = 0
    # The lane at minute 14, as on the match row, and its label.
    laning_score: float | None = None
    laning_label: LaneLabel | None = None

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    kill_participation: float = 0.0

    cs: int = 0
    cs_per_min: float = 0.0
    gold_earned: int = 0
    damage_to_champions: int = 0
    damage_taken: int = 0
    vision_score: int = 0
    wards_placed: int | None = None
    wards_killed: int | None = None
    control_wards: int | None = None

    items: list[ItemRef] = Field(default_factory=list)
    trinket: ItemRef | None = None
    spells: list[SpellRef] = Field(default_factory=list)
    keystone: RuneRef | None = None

    score: float | None = None
    placement: int | None = None
    badges: list[BadgeOut] = Field(default_factory=list)


class TeamObjectives(BaseModel):
    """What one side did. Kills and gold are summed from its own players.

    `objectives_known` is false when Riot's team objects do not line up with the
    sides on the scoreboard, which is the case in Arena. Then the structure and
    monster counts below are all zero because they are unknown, not because
    nothing was taken, and the UI omits them.
    """

    team_id: int
    win: bool = False
    kills: int = 0
    gold: int = 0
    objectives_known: bool = True
    baron: int = 0
    dragon: int = 0
    herald: int = 0
    tower: int = 0
    inhibitor: int = 0
    bans: list[ChampionRef] = Field(default_factory=list)



class PublishedComponentOut(BaseModel):
    """One of the things the score is made of, as the method page lists them."""

    id: str
    label: str
    measures: str

class ScoreModelOut(BaseModel):
    """How the Riftline score is computed, published with every scoreboard.

    itero exposes its draft model and it is the most trustworthy thing on their
    site. A rating that cannot be taken apart is a rating that has to be taken
    on faith, which is the opposite of what this whole project is for.
    """

    version: int
    components: list[PublishedComponentOut]
    weights: dict[str, dict[str, float]]
    samples: dict[str, int] = Field(default_factory=dict)
    note: str


class MatchDetailResponse(BaseModel):
    match_id: str
    queue_id: int
    queue_name: str
    patch: str | None = None
    game_creation: int
    game_duration: int
    is_remake: bool = False
    platform: str | None = None
    # Why a score is missing, when it is. Null when every player has one.
    score_withheld: str | None = None
    teams: list[list[ScoreboardPlayer]] = Field(default_factory=list)
    objectives: list[TeamObjectives] = Field(default_factory=list)
    model: ScoreModelOut | None = None


class MatchHistoryResponse(BaseModel):
    puuid: str
    matches: list[MatchSummary]
    start: int
    count: int
    # True when Riot returned a full page, meaning more history exists.
    has_more: bool = False
    # "riot" for history as Riot lists it; "stored" for a champion filter,
    # which Riot cannot do, read from the games we hold.
    source: str = "riot"
    # With "stored": how many games match in all.
    stored_total: int | None = None
    # The queues asked for, as a word; null for one queue id or for every queue.
    scope: QueueScope | None = None


class MasteryEntry(BaseModel):
    champion: ChampionRef
    level: int
    points: int
    points_since_last_level: int = 0
    points_until_next_level: int = 0
    progress_to_next: float = 0.0
    last_play_time: int | None = None
    tokens_earned: int = 0
    season_milestone: int | None = None
    milestone_grades: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    # False when Riot names a champion our static data does not list yet, which
    # happens for a day or two after a release. Measured on 2026-09-21: id 60016
    # with 665 points. The page used to build its grid from the static roster
    # alone and drop the champion, so it reported 165 where this said 166.
    champion_known: bool = True


class MasteryResponse(BaseModel):
    """Every champion this account has touched, newest Riot reading first.

    `champions_owned_ratio` and a `levels` histogram used to ride along here.
    Both are gone: the ratio divided by our static roster and so exceeded 1.0
    for as long as Data Dragon lagged a champion release, and the histogram was
    34 buckets of an unbounded scale that nothing read. The page holds the
    roster already and counts what it needs from `entries`.
    """

    puuid: str
    # The player's own spelling, so the tab can title itself from its answer.
    game_name: str | None = None
    tag_line: str | None = None
    total_points: int = 0
    total_champions_played: int = 0
    # The shard the table was actually read from, which is not always the one in
    # the URL: an OCE Riot ID resolves through `sea` while the account lives on
    # sg2, and mastery answers 200 with nothing on the wrong shard.
    platform: str | None = None
    # When we last asked Riot, so the page can say how old this is.
    fetched_at: int | None = None
    entries: list[MasteryEntry] = Field(default_factory=list)


class LiveMasteryOut(BaseModel):
    level: int
    points: int
    last_play_time: int | None = None


class CorpusRecordOut(BaseModel):
    """A record from the stored corpus. Always carries its size and its basis.

    `basis` says which step of the lane fallback produced it: "role" for the
    champion's own record, "lane" for this patch's head to head, "lane_pooled"
    when the previous patch had to be pooled in, and "team" when the only rows
    we hold are of the two champions in the same game rather than the same lane.
    The page must label anything below "lane", because a team scope record shown
    as a lane record is a claim the data does not support.
    """

    games: int
    wins: int
    win_rate: float
    gold_diff_14: float | None = None
    timeline_games: int = 0
    basis: RecordBasis = "lane"
    patches: list[str] = Field(default_factory=list)


class LiveBanOut(BaseModel):
    champion: ChampionRef
    team_id: int
    # How often this patch bans that champion, from the rows the tier list
    # reads. Null where the corpus holds too few games of them to say.
    ban_rate: float | None = None
    ban_rate_games: int = 0


class PositionModelOut(BaseModel):
    """How far an inferred position can be trusted, measured, not asserted."""

    accuracy: float
    players_tested: int
    confident_at: float


class PlayedRecordOut(BaseModel):
    """A player's own record from stored games, always with its size."""

    games: int
    wins: int
    losses: int
    # Null under ten games, where one game moves the figure by ten points. The
    # W-L above is always there, so a thin record reads as "2-1", never "67%".
    win_rate: float | None = None
    scored_games: int = 0
    avg_score: float | None = None
    # False when the average is published but thin, mirroring RoleScoreProfile.
    score_enough: bool = False
    last_played: int | None = None
    first_played: int | None = None


class PlayerRecordOut(BaseModel):
    """What Riftline holds about one player in a live lobby.

    Withheld rather than zeroed: a player we hold too little for has no record
    at all and `stored_games` on the participant says how little. A record full
    of zeroes would render as somebody who loses every game.

    These are the games **we have crawled**, not their season. The crawler walks
    outward from stored matches, so a player in a bracket we crawl has far more
    here than one outside it.
    """

    overall: PlayedRecordOut
    # Null means we hold no stored game of theirs on this champion. That is not
    # "they have never played it": mastery answers that, over their whole
    # history rather than over what we crawled.
    on_champion: PlayedRecordOut | None = None
    main_position: str | None = None
    main_position_games: int = 0
    positioned_games: int = 0
    # Null whenever either side of the comparison is unknown.
    on_main_position: bool | None = None
    min_games: int = MIN_RECORD_GAMES
    min_games_for_win_rate: int = MIN_GAMES_FOR_WIN_RATE


class LiveParticipantOut(BaseModel):
    """One player in a live game.

    ``state`` carries the honesty. ``hidden`` means Riot returned no account id
    for them because they opted out of third-party visibility, so there is no
    name, no rank and no profile to link to. ``unknown`` means we could not
    complete the rank lookup in time, which is a different thing from
    ``unranked``.
    """

    state: RankState
    puuid: str | None = None
    riot_id: str | None = None
    champion: ChampionRef
    team_id: int
    spells: list[SpellRef] = Field(default_factory=list)
    keystone: RuneRef | None = None
    secondary_tree: RuneRef | None = None
    profile_icon_url: str | None = None
    rank: RankInfo | None = None
    # The skin this player is actually wearing, as square art.
    skin_tile_url: str | None = None
    # Inferred, not reported: spectator carries no position. `basis` is "smite"
    # for a team's only Smite, which is certain, and "inferred" otherwise.
    position: str | None = None
    position_confidence: float | None = None
    position_basis: str | None = None
    # `mastery_known` false means we did not find out; true with no `mastery`
    # means Riot says they have never played this champion.
    mastery: LiveMasteryOut | None = None
    mastery_known: bool = False
    champion_record: CorpusRecordOut | None = None
    lane_record: CorpusRecordOut | None = None
    # Always present, including zero: "we hold nothing" is an answer.
    stored_games: int = 0
    record: PlayerRecordOut | None = None
    # Null on the searched player's own row and on anyone hidden.
    shared_games: SharedGamesOut | None = None


class LobbyRankOut(BaseModel):
    """A lobby's median rank, always shipping its own sample size.

    Around a third of a live lobby hides its identity, and that is not missing
    at random, so the counts are not optional detail: a number without them
    would be claiming a census it never took. Below the floor the rank is
    withheld outright rather than shown greyed out.

    ``extra="forbid"`` because this model is built by splatting a dataclass
    (``LobbyRankOut(**asdict(...))``). With the default behaviour a field
    renamed on one side is silently dropped and the other side quietly takes its
    default: renaming `average_points` to `median_points` served `null` beside a
    populated `tier`, and the UI reported "not enough identified players" for a
    lobby of eight. Forbidding extras turns that into an error at the boundary.
    """

    model_config = ConfigDict(extra="forbid")

    median_points: int | None = None
    tier: str | None = None
    division: str | None = None
    league_points: int | None = None
    ranked: int = 0
    unranked: int = 0
    hidden: int = 0
    bots: int = 0
    unknown: int = 0
    queue_type: str
    queue_matches_game: bool = True


class SharedGamesOut(BaseModel):
    """Earlier stored games a player and the searched player were both in.

    Counts only, at every sample size. These are single digit numbers, so a
    percentage here would be a figure nobody should quote back. The wins are
    always the searched player's.

    `basis` is "stored_matches" and it matters: the crawler walks outward from
    matches it already holds, so the people we hold games of are exactly the
    people who appear together in them. These figures are an upper bound on what
    a lobby outside the crawled bracket would show.
    """

    games: int
    same_side: int
    same_side_wins: int
    opposite_side: int
    opposite_side_wins: int
    last_played: int | None = None
    basis: str = "stored_matches"


class SameTeamPairOut(BaseModel):
    """Two players in this lobby who keep appearing on the same side.

    Not called a duo, here or anywhere else on the wire. Two players in the same
    small ranked pool meet constantly without ever pressing invite, so this is a
    pattern in stored games and nothing more. Nothing is persisted: the pairing
    is computed per request and lives in this response.
    """

    puuid_a: str
    puuid_b: str
    games: int
    wins: int
    last_played: int | None = None
    basis: str = "stored_matches"


class SideReadOut(BaseModel):
    """One side of a live lobby, summed from what the lobby already shows."""

    team_id: int
    median_points: int | None = None
    tier: str | None = None
    division: str | None = None
    league_points: int | None = None
    ranked: int = 0
    unranked: int = 0
    hidden: int = 0
    bots: int = 0
    unknown: int = 0
    # Tier boundaries from the searched player to this side's median. Valid
    # everywhere, which is why it exists beside the points gap.
    tier_gap: int | None = None
    # Published only when both ends are below Master: `numeric_rank` is ordinal
    # with a 100,000 apex stride, so subtracting across that boundary would tell
    # a Diamond I player they are one point behind a Master lobby.
    points_gap: int | None = None
    gap_basis: str = "withheld"
    lanes_favoured: int = 0
    off_champion: int = 0
    off_champion_known: int = 0
    off_role: int = 0
    off_role_known: int = 0


class LobbyCompareOut(BaseModel):
    """The two sides beside each other.

    Carries no win probability and no verdict, deliberately. The site holds no
    model that predicts a game, so a percentage here would be the only number on
    the page with nothing behind it, and about a third of a lobby hides its
    identity, which is not a third missing at random.
    """

    sides: list[SideReadOut] = Field(default_factory=list)
    you_team_id: int | None = None
    lanes_with_record: int = 0
    lanes_level: int = 0
    lanes_total: int = 0
    min_ranked_per_side: int = 3


class LiveGameOut(BaseModel):
    game_id: int
    platform_id: str
    # Riot's own id for this game once it finishes, built here rather than
    # concatenated in React: this codebase does not hand assemble identifiers.
    match_id: str
    queue_id: int
    queue_name: str
    game_mode: str | None = None
    map_id: int | None = None
    phase: str
    game_start_time: int
    game_length: int
    # Our clock when we asked Riot. The client advances the timer from this
    # locally instead of polling the server for a number it can compute.
    observed_at: int
    banned_champions: list[ChampionRef] = Field(default_factory=list)
    # The same bans with their side, in pick order.
    bans: list[LiveBanOut] = Field(default_factory=list)
    participants: list[LiveParticipantOut] = Field(default_factory=list)
    lobby_rank: LobbyRankOut | None = None
    you_identified: bool = True
    positions_inferred: bool = False
    position_model: PositionModelOut | None = None
    # The patch the champion and lane records were read from.
    corpus_patch: str | None = None
    # Every patch the lane fallback was allowed to read, newest first.
    corpus_patches: list[str] = Field(default_factory=list)
    # Which games each player's own record was counted over.
    record_basis: str = "all_queues"
    record_queue_id: int | None = None
    # The two sides beside each other. Null off Summoner's Rift.
    sides: LobbyCompareOut | None = None
    # Pairs that keep landing on the same side in stored games.
    same_team_pairs: list[SameTeamPairOut] = Field(default_factory=list)


class LastStoredGameOut(BaseModel):
    """The newest game we hold for a player, for the page they see when they are
    not playing."""

    match_id: str
    queue_id: int
    queue_name: str
    champion: ChampionRef
    position: str | None = None
    win: bool
    kills: int
    deaths: int
    assists: int
    game_creation: int
    game_duration: int
    performance_score: float | None = None


class IdleSummaryOut(BaseModel):
    """What we hold for a player who is not in a game.

    Measured on 2026-09-21: 31 live lookups against production, covering the
    active EUW and NA challengers and everyone in that week's best games, found
    nobody in a game. This is the live page's normal state, so it carries
    something rather than an empty box.

    ``last_game`` is the newest game **Riftline has stored**, which is not the
    newest game they played: the corpus is crawled, and for a player with five
    or more stored games the newest one is a median of four days old (p90
    seven). Anything rendering this has to word it that way.
    """

    stored_games: int
    last_game: LastStoredGameOut | None = None
    basis: str = "stored_matches"


class MatchResolveResponse(BaseModel):
    """Whether a finished live game has reached storage yet.

    Always 200, never a 404. The match will exist: the question is answerable
    and the answer is "not yet". A 404 here would render as "no such match",
    which is a different and false claim, the same reason the live endpoint
    answers 200 with ``in_game: false``.
    """

    match_id: str
    # "stored" once we hold it, "pending" while Riot has not published it, and
    # "gave_up" once this match id has used its attempts.
    status: str
    # Whether this request spent a Riot call. False on a storage hit, inside the
    # cooldown and past the cap, which is all but a handful of requests.
    attempted: bool = False
    # Seconds until the client should ask again. Null means stop asking.
    retry_after: int | None = None
    game_creation: int | None = None
    game_duration: int | None = None
    # The searched player's own line, once the match is stored. Null while it is
    # not, and null for a player whose row is not in it.
    win: bool | None = None
    # Null on a game the score was withheld for. Never rendered as 0.0.
    score: float | None = None
    placement: int | None = None
    hint: str | None = None


class LiveGameResponse(BaseModel):
    puuid: str
    platform: str
    # 200 with in_game=False, not 404. The player exists; the game does not, and
    # a 404 would render as "no player found".
    in_game: bool = False
    game: LiveGameOut | None = None
    # Only when they are not in a game, so the live path pays nothing for it.
    idle: IdleSummaryOut | None = None
    checked_at: int


class RateWindowOut(BaseModel):
    used: int
    limit: int
    period: float


class RateLimitOut(BaseModel):
    app: list[RateWindowOut] = Field(default_factory=list)
    methods_tracked: int = 0
    penalties: dict[str, float] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    riot_key_configured: bool
    # Whether Riot accepted the key on its latest answer: null until the API
    # has asked Riot anything since it started. A development key expires 24
    # hours after it is issued, and this is how the page learns live data is
    # paused without waiting for a lookup to fail.
    riot_key_ok: bool | None = None
    # Epoch ms of that answer.
    riot_key_checked_at: int | None = None
    static_data_version: str | None = None
    rate_limit: RateLimitOut = Field(default_factory=RateLimitOut)
    spectator_enabled: bool = True


# --------------------------------------------------------------------- mappers


class LobbyRankBucket(BaseModel):
    tier: str
    games: int


class LobbyRanksOut(BaseModel):
    """How the games behind this slice were ranked, by measured lobby median."""

    total: int
    measured: int
    # Highest first. MASTER+ merges the apex tiers, which cannot be told apart
    # from a points value alone.
    buckets: list[LobbyRankBucket] = Field(default_factory=list)
    # Epoch ms of the newest measurement. Riot keeps no historical rank, so this
    # is where those players stood then, not when they played.
    as_of: int | None = None


def lobby_ranks_out(mix) -> LobbyRanksOut:
    """`aggregate.LobbyRankMix` on the wire."""
    return LobbyRanksOut(
        total=mix.total,
        measured=mix.measured,
        buckets=[LobbyRankBucket(tier=t, games=n) for t, n in mix.buckets],
        as_of=epoch_ms(mix.as_of),
    )


def epoch_ms(stamp: datetime | None) -> int | None:
    """A stored timestamp as epoch milliseconds, for the browser.

    SQLite hands back **naive** datetimes, and `datetime.timestamp()` reads a
    naive value as *local* time. On a machine seven hours off UTC that silently
    reported a snapshot taken minutes ago as "7h ago". Everything here is stored
    in UTC, so that is what a missing tzinfo means.
    """
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return int(stamp.timestamp() * 1000)


def numeric_rank(tier: str | None, division: str | None, lp: int) -> int:
    """Collapse tier/division/LP into one sortable integer.

    Below Master, Riot caps LP at 100, so the 400-per-tier / 100-per-division
    scale never collides and LP can simply ride in the last two digits.

    **Apex is a different animal and used to break this.** Master, Grandmaster
    and Challenger have no divisions and unbounded LP: EUW's top Challenger is
    on 4,724. Clamping that to 99 made every Challenger compare exactly equal,
    which is fine for bucketing but makes a ladder impossible to order, and this
    value is what leaderboards sort on. So apex gets its own scale above the
    sub-apex range, wide enough that LP orders within a tier while the tier
    still outranks LP: a 99 LP Challenger stays above a 1,200 LP Master.
    """
    if not tier:
        return 0
    tier_upper = tier.upper()
    try:
        tier_index = TIER_ORDER.index(tier_upper)
    except ValueError:
        return 0

    if tier_upper in APEX_TIERS:
        # Capped so an implausible LP can never spill into the next tier's band,
        # where it would decode as a rank the player does not hold.
        return (
            APEX_BASE
            + APEX_TIERS.index(tier_upper) * APEX_STRIDE
            + min(max(lp, 0), APEX_LP_CAP)
        )

    try:
        division_index = DIVISION_ORDER.index((division or "IV").upper())
    except ValueError:
        division_index = 0
    # Clamped at both ends. The apex branch already guarded the low side; this
    # one did not, so a negative LP produced a negative sort key and decoded a
    # Gold player as Silver.
    return (tier_index * 400) + (division_index * 100) + min(max(lp, 0), 99)


def rank_from_points(points: int) -> tuple[str | None, str | None]:
    """Turn a numeric_rank back into a tier and division.

    The inverse of :func:`numeric_rank`, used to label an averaged rank. It is
    exact below Master, where the scale is a clean 400-per-tier grid.

    Above Master it is **not** exact and the caller has to know that. Which apex
    tier a given LP total lands in depends on that region's live cutoffs, which
    Riot only expresses as "the top 300 players", so a points value alone cannot
    say whether 1,800 LP is Grandmaster or Challenger today. This returns the
    tier whose band the value falls in and leaves the caller to prefer the modal
    tier of the real players it averaged, which is a measurement rather than a
    guess.
    """
    # `< 0`, not `<= 0`. Iron IV at 0 LP scores exactly 0, so treating 0 as
    # "no rank" made a real rank indistinguishable from an absent one. Callers
    # decide whether they have a rank at all; this only decodes a value they
    # already know is one.
    if points < 0:
        return None, None
    if points >= APEX_BASE:
        index = min((points - APEX_BASE) // APEX_STRIDE, len(APEX_TIERS) - 1)
        return APEX_TIERS[index], None
    tier_index = min(points // 400, TIER_ORDER.index("DIAMOND"))
    division_index = min((points % 400) // 100, len(DIVISION_ORDER) - 1)
    return TIER_ORDER[tier_index], DIVISION_ORDER[division_index]


def to_rank_info(entry: RankedEntry) -> RankInfo:
    games = entry.wins + entry.losses
    return RankInfo(
        queue=entry.queue_type,
        queue_label=QUEUE_LABELS.get(entry.queue_type, entry.queue_type.replace("_", " ").title()),
        tier=entry.tier,
        division=entry.division,
        league_points=entry.league_points,
        wins=entry.wins,
        losses=entry.losses,
        games=games,
        win_rate=entry.wins / games if games else 0.0,
        hot_streak=entry.hot_streak,
        inactive=entry.inactive,
        numeric_rank=numeric_rank(entry.tier, entry.division, entry.league_points),
    )


def to_profile(
    player: Player,
    ranks: list[RankedEntry],
    sd: StaticDataService,
    view: ShardView,
    *,
    summoner: dict | None = None,
    read_at: int | None = None,
    ladder: LadderPositionOut | None = None,
    source: Literal["live", "stored"] = "live",
) -> ProfileResponse:
    """The profile header for one view of a player.

    ``summoner`` and ``read_at`` are the second shard's record and the time its
    ranks were read, for a ``second`` view, which stores neither. Every other
    view shows the home shard's stored record, labelled when the URL named
    another shard: the player has one face and one level where they play, and
    a blank avatar would read as a fact about them.
    """
    infos = [to_rank_info(r) for r in ranks]
    # Solo queue first: it is the rank players mean when they say "my rank".
    infos.sort(key=lambda r: (r.queue != "RANKED_SOLO_5x5", -r.numeric_rank))
    second = view.role == "second"
    absent = view.role == "absent"
    record = summoner or {}
    return ProfileResponse(
        puuid=player.puuid,
        game_name=player.game_name,
        tag_line=player.tag_line,
        riot_id=f"{player.game_name}#{player.tag_line}",
        platform=view.asked.id,
        platform_label=view.asked.label,
        shard=view.role,
        home_platform=view.home.id,
        home_platform_label=view.home.label,
        summoner_level=record.get("summonerLevel") if second else player.summoner_level,
        profile_icon_url=sd.profile_icon(
            record.get("profileIconId") if second else player.profile_icon_id
        ),
        ranks=infos,
        plays_on=view.home.id if absent else None,
        plays_on_label=view.home.label if absent else None,
        identity_from_plays_on=absent,
        updated_at=(
            read_at
            if second
            else epoch_ms(player.league_fetched_at or player.summoner_fetched_at)
        ),
        ladder=ladder,
        source=source,
    )


def _champion_ref(champion_id: int, sd: StaticDataService) -> ChampionRef:
    return ChampionRef(
        id=champion_id,
        name=sd.champion_name(champion_id),
        icon_url=sd.champion_icon(champion_id),
    )


def _multi_kill(p: MatchParticipant) -> str | None:
    if p.penta_kills:
        return "Penta Kill"
    if p.quadra_kills:
        return "Quadra Kill"
    if p.triple_kills:
        return "Triple Kill"
    if p.double_kills:
        return "Double Kill"
    return None


def _style(perks: dict | None, description: str, fallback_index: int) -> dict | None:
    """Find a perk style by Riot's own label rather than by array position.

    Riot labels each style ``primaryStyle`` or ``subStyle``. Indexing blind
    works only as long as they never reorder, and a silently swapped keystone
    and secondary tree is the kind of wrongness nobody notices for months.
    """
    styles = (perks or {}).get("styles")
    if not isinstance(styles, list) or not styles:
        return None
    for style in styles:
        if isinstance(style, dict) and style.get("description") == description:
            return style
    # Payloads that omit `description` fall back to documented positional order.
    return styles[fallback_index] if len(styles) > fallback_index else None


def _keystone(perks: dict | None) -> RuneRef | None:
    """The first rune selected in the primary tree."""
    style = _style(perks, "primaryStyle", 0)
    try:
        return RuneRef(id=style["selections"][0]["perk"])  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None


def _keystone_art(perks: dict | None, sd: StaticDataService) -> RuneRef | None:
    """The keystone with its icon, for the surfaces that draw the rune.

    `_keystone` returns the id alone. The scoreboard shows the rune next to the
    champion, so a bare id renders as an empty circle, which is how it shipped.
    """
    rune = _keystone(perks)
    if rune and rune.id:
        rune.icon_url = sd.rune_icon(rune.id)
        rune.name = sd.rune_name(rune.id)
    return rune


def _secondary_tree(perks: dict | None) -> RuneRef | None:
    style = _style(perks, "subStyle", 1)
    try:
        return RuneRef(id=style["style"])  # type: ignore[index]
    except (KeyError, TypeError):
        return None


def _badges_out(participant, match) -> list[BadgeOut]:
    """The badges on a participant, each with its rule and their own figure."""
    detail = participant.performance_detail or {}
    out = []
    for badge_id in detail.get("badges") or []:
        badge = BADGES_BY_ID.get(badge_id)
        if badge is None:
            # A badge that no longer exists in the code. Dropping it beats
            # rendering an id, and the next scoring pass clears it.
            continue
        out.append(
            BadgeOut(
                id=badge.id,
                label=badge.label,
                detail=badge_detail(badge_id, participant, match),
            )
        )
    return out


def _score_components_out(participant) -> list[ScoreComponentOut]:
    """The seven components behind one score, with their weights for that role."""
    detail = participant.performance_detail or {}
    percentiles = detail.get("components") or {}
    weights = WEIGHTS.get(participant.team_position or "", {})
    out = []
    for component in COMPONENTS:
        if component not in percentiles:
            continue
        label, measures = COMPONENT_LABELS[component]
        out.append(
            ScoreComponentOut(
                id=component,
                label=label,
                measures=measures,
                percentile=percentiles[component],
                weight=weights.get(component, 0.0),
            )
        )
    return out


# (queue, role, laning score) -> lane label; see `app.services.lanes`.
LaneLabel = Callable[[int | None, str | None, float | None], str | None]



def withheld_sentence(reason: ScoreWithheld | None, players: int) -> str | None:
    """The scoreboard's line for a game with no score."""
    return {
        "remake": "This game was a remake, so there is nothing to score.",
        "not_ten": (
            f"This mode puts {players} players in a lobby, and the score is a percentile "
            "within a lane role, so there is no scale to place them on."
        ),
        "no_roles": (
            "This mode has no lane roles, and every component of the score is measured "
            "against a role, so it is withheld rather than guessed."
        ),
        "thin_queue": "Our corpus holds too few games in this queue to be a percentile of.",
        "not_scored_yet": "This game has not been scored yet.",
        None: None,
    }[reason]

def to_match_summary(
    match: Match, puuid: str, sd: StaticDataService, lanes: LaneLabel | None = None
) -> MatchSummary | None:
    me = next((p for p in match.participants if p.puuid == puuid), None)
    if me is None:
        return None

    minutes = max(1.0, match.game_duration / 60)
    team_kills = sum(p.kills for p in match.participants if p.team_id == me.team_id)

    items = [
        ItemRef(id=i, name=sd.item_name(i), icon_url=sd.item_icon(i))
        for i in (me.items or [])[:6]
    ]
    trinket_id = (me.items or [0] * 7)[6] if me.items and len(me.items) > 6 else 0
    trinket = (
        ItemRef(id=trinket_id, name=sd.item_name(trinket_id), icon_url=sd.item_icon(trinket_id))
        if trinket_id
        else None
    )

    keystone = _keystone(me.perks)
    if keystone and keystone.id:
        keystone.icon_url = sd.rune_icon(keystone.id)
        keystone.name = sd.rune_name(keystone.id)
    secondary = _secondary_tree(me.perks)
    if secondary and secondary.id:
        secondary.icon_url = sd.rune_icon(secondary.id)
        secondary.name = sd.rune_name(secondary.id)

    by_team: dict[int, list[ParticipantBrief]] = {}
    # Participants arrive in Riot's participantId order (see the relationship's
    # order_by), so each team's rows stay in a stable, meaningful sequence.
    for p in match.participants:
        brief = ParticipantBrief(
            puuid=p.puuid,
            riot_id=f"{p.riot_id_game_name}#{p.riot_id_tagline}"
            if p.riot_id_game_name
            else None,
            champion=_champion_ref(p.champion_id, sd),
            team_id=p.team_id,
            position=p.team_position,
            kills=p.kills,
            deaths=p.deaths,
            assists=p.assists,
            win=p.win,
            score=p.performance_score,
            placement=p.performance_rank,
            badges=_badges_out(p, match),
        )
        by_team.setdefault(p.team_id, []).append(brief)

    # `is not None`, not truthiness: an average of exactly 0.0 is a lobby of
    # Iron IV players at 0 LP, which is a measurement, not a missing one.
    # `round`, matching the live view. `int` truncates, so a stored 2799.9
    # rendered "Diamond I" in match history while the identical arithmetic
    # elsewhere called it Master.
    #
    # The label is withheld below the same floor the live view uses. Publishing
    # a tier derived from one player of ten, when the other endpoint refuses to,
    # is the server contradicting itself about what it considers measurable.
    measurable = (
        match.lobby_rank_points is not None
        and (match.lobby_ranked_players or 0) >= MIN_RANKED_FOR_LOBBY_RANK
    )
    lobby_tier, lobby_division = (
        rank_from_points(round(match.lobby_rank_points)) if measurable else (None, None)
    )
    return MatchSummary(
        match_id=match.match_id,
        queue_id=match.queue_id,
        queue_name=sd.queue_name(match.queue_id),
        patch=match.patch,
        game_creation=match.game_creation,
        game_duration=match.game_duration,
        is_remake=match.is_remake,
        win=me.win,
        champion=_champion_ref(me.champion_id, sd),
        champ_level=me.champ_level,
        position=me.team_position,
        kills=me.kills,
        deaths=me.deaths,
        assists=me.assists,
        kda=(me.kills + me.assists) / max(1, me.deaths),
        kill_participation=(me.kills + me.assists) / team_kills if team_kills else 0.0,
        cs=me.total_minions,
        cs_per_min=me.total_minions / minutes,
        gold_earned=me.gold_earned,
        vision_score=me.vision_score,
        damage_to_champions=me.damage_to_champions,
        damage_per_min=me.damage_to_champions / minutes,
        items=items,
        trinket=trinket,
        spells=[
            SpellRef(id=s, name=sd.spell_name(s), icon_url=sd.spell_icon(s))
            for s in (me.summoner1_id, me.summoner2_id)
            if s
        ],
        keystone=keystone,
        secondary_tree=secondary,
        multi_kill=_multi_kill(me),
        laning_score=me.laning_score,
        laning_opponent=(
            _champion_ref(me.opponent_champion_id, sd)
            if me.opponent_champion_id
            else None
        ),
        laning_label=(
            lanes(match.queue_id, me.team_position, me.laning_score) if lanes else None
        ),
        gold_diff_14=me.gold_diff_14,
        cs_diff_14=me.cs_diff_14,
        lobby_rank_points=match.lobby_rank_points,
        lobby_rank_tier=lobby_tier,
        lobby_rank_division=lobby_division,
        lobby_ranked_players=match.lobby_ranked_players,
        # The denominator. Arena runs eighteen, so "7 of 10" would be wrong
        # there, and a share without its denominator is not a measurement.
        lobby_players_total=len(match.participants) or None,
        lobby_rank_measured_at=epoch_ms(match.lobby_rank_measured_at),
        lobby_queue_matches_game=match.queue_id in RANKED_QUEUE_BY_ID,
        # Whatever teams the mode actually has: 100/200 on the Rift, but Arena
        # runs eight. Hardcoding two rendered Arena games with no players at all.
        score=me.performance_score,
        placement=me.performance_rank,
        score_withheld=withheld_reason(match, me),
        badges=_badges_out(me, match),
        score_components=_score_components_out(me),
        score_sample=(me.performance_detail or {}).get("sample"),
        teams=[by_team[team_id] for team_id in sorted(by_team)],
    )


def to_mastery_response(
    puuid: str,
    masteries: list[ChampionMastery],
    sd: StaticDataService,
    *,
    platform: str | None = None,
    fetched_at: int | None = None,
    game_name: str | None = None,
    tag_line: str | None = None,
) -> MasteryResponse:
    entries: list[MasteryEntry] = []

    for m in sorted(masteries, key=lambda x: x.champion_points, reverse=True):
        champ = sd.champion(m.champion_id)
        span = m.points_since_last_level + m.points_until_next_level
        entries.append(
            MasteryEntry(
                champion=_champion_ref(m.champion_id, sd),
                level=m.champion_level,
                points=m.champion_points,
                points_since_last_level=m.points_since_last_level,
                points_until_next_level=m.points_until_next_level,
                # Mastery is uncapped now, so "progress" is only meaningful when
                # Riot still reports points remaining to a next level.
                progress_to_next=(m.points_since_last_level / span) if span else 1.0,
                last_play_time=m.last_play_time,
                tokens_earned=m.tokens_earned,
                season_milestone=m.season_milestone,
                milestone_grades=m.milestone_grades,
                tags=champ.tags if champ else [],
                champion_known=champ is not None,
            )
        )

    return MasteryResponse(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        total_points=sum(m.champion_points for m in masteries),
        total_champions_played=len(masteries),
        platform=platform,
        fetched_at=fetched_at,
        entries=entries,
    )


# ------------------------------------------------------------------- analytics


class RoleShare(BaseModel):
    position: str
    games: int
    share: float
    win_rate: float


class ClassShare(BaseModel):
    """Champion class mix, from Data Dragon tags.

    A champion can carry several tags (Fighter *and* Tank), so shares are of
    total tag mentions and intentionally do not sum to the game count.
    """

    tag: str
    games: int
    share: float


class ChampionPlayed(BaseModel):
    champion: ChampionRef
    games: int
    wins: int
    win_rate: float
    kda: float
    cs_per_min: float
    avg_kills: float = 0.0
    avg_deaths: float = 0.0
    avg_assists: float = 0.0
    damage_per_min: float = 0.0
    main_position: str | None = None
    # Epoch ms.
    last_played: int | None = None
    # Each average below is over its own count, not over `games`: a champion
    # with two scored games of nine reports a score two games deep.
    scored_games: int = 0
    avg_score: float | None = None
    timeline_games: int = 0
    avg_gold_diff_14: float | None = None


class ComponentAverageOut(BaseModel):
    id: str
    label: str
    measures: str
    # Mean of this player's per-game percentiles in the role, 0 to 1.
    avg_percentile: float


class RoleScoreProfileOut(BaseModel):
    """What this player's scored games in one role add up to."""

    position: str
    scored_games: int
    # False below the floor: the page shows the count and no breakdown.
    enough: bool
    avg_score: float
    avg_placement: float
    mvp: int
    ace: int
    # Highest first.
    components: list[ComponentAverageOut] = Field(default_factory=list)
    # The smallest corpus any of the percentiles was measured against.
    sample: int | None = None
    min_scored: int


class PlayStyleTotals(BaseModel):
    win_rate: float = 0.0
    kda: float = 0.0
    avg_kills: float = 0.0
    avg_deaths: float = 0.0
    avg_assists: float = 0.0
    cs_per_min: float = 0.0
    vision_per_game: float = 0.0
    damage_per_min: float = 0.0


class ReviewMetricOut(BaseModel):
    metric: str
    label: str
    measures: str
    # The player's own rate over their reviewed games, pooled.
    value: float
    # Share of the role's games this player's did better than, averaged per
    # game. Null when the role's spread is too thin to place anyone.
    better_than: float | None = None
    lower_is_better: bool = False
    games: int = 0


class RoleReviewOut(BaseModel):
    position: str
    games: int
    min_games: int
    # Why the rates are not shown, when they are not.
    withheld: str | None = None
    metrics: list[ReviewMetricOut] = Field(default_factory=list)
    contests: int = 0
    contests_won: int = 0


class LaneRecordOut(BaseModel):
    """How this player's lanes went, per role, over games with a timeline."""

    position: str
    games: int
    won_big: int = 0
    won: int = 0
    even: int = 0
    lost: int = 0
    lost_big: int = 0


class ScopeGamesOut(BaseModel):
    scope: QueueScope
    label: str
    games: int


class AnalyticsResponse(BaseModel):
    """Play style over the matches we hold.

    ``basis`` is not decoration. This reads stored matches only, so it describes
    the games that have been fetched, not a whole season. Saying so is the
    difference between a useful summary and a wrong one.
    """

    puuid: str
    # The player's own spelling and the shard the games are from, so a tab can
    # title itself from its own answer.
    game_name: str | None = None
    tag_line: str | None = None
    platform: str | None = None
    # Which games every figure below covers. `scope` is the word the page's
    # chips use, null when one queue id was asked for; `queues` the ids behind
    # it, empty for every queue. Every panel reads the same window: the newest
    # `window` games in the scope, of `stored_total` held. A profile once
    # pooled every queue and read 62% and a 4.47 KDA where the ranked games
    # said 50% and 3.85.
    scope: QueueScope | None = "ranked"
    queues: list[int] = Field(default_factory=list)
    window: int = 0
    stored_total: int = 0
    # Stored games in each scope, for the chips' counts.
    scope_games: list[ScopeGamesOut] = Field(default_factory=list)
    basis: str = "stored_matches"
    games_analysed: int = 0
    roles: list[RoleShare] = Field(default_factory=list)
    classes: list[ClassShare] = Field(default_factory=list)
    # 24 buckets, UTC. The client shifts them into local time; the server has no
    # business guessing the viewer's timezone.
    activity_utc: list[int] = Field(default_factory=list)
    champions: list[ChampionPlayed] = Field(default_factory=list)
    totals: PlayStyleTotals = Field(default_factory=PlayStyleTotals)
    # Most scored games first.
    score_profile: list[RoleScoreProfileOut] = Field(default_factory=list)
    # The death and kill review against the role; most reviewed games first.
    review: list[RoleReviewOut] = Field(default_factory=list)
    # Won, even and lost lanes per role, by the lane labels.
    lanes: list[LaneRecordOut] = Field(default_factory=list)


def _corpus_record_out(record) -> CorpusRecordOut | None:
    if record is None:
        return None
    return CorpusRecordOut(
        games=record.games,
        wins=record.wins,
        win_rate=record.wins / record.games if record.games else 0.0,
        gold_diff_14=record.gold_diff_14,
        timeline_games=record.timeline_games,
        basis=record.basis,
        patches=list(record.patches),
    )


def to_idle_summary(
    row: PlayedRow | None, stored_games: int, sd: StaticDataService
) -> IdleSummaryOut:
    """The idle page's content, from storage only.

    A player we hold nothing for gets `stored_games: 0` and no game, never a
    zeroed one: "we hold nothing" and "they played badly" are different claims.
    """
    if row is None or row.match_id is None:
        return IdleSummaryOut(stored_games=stored_games, last_game=None)
    return IdleSummaryOut(
        stored_games=stored_games,
        last_game=LastStoredGameOut(
            match_id=row.match_id,
            queue_id=row.queue_id,
            queue_name=sd.queue_name(row.queue_id),
            champion=_champion_ref(row.champion_id, sd),
            position=row.team_position or None,
            win=row.win,
            kills=row.kills,
            deaths=row.deaths,
            assists=row.assists,
            game_creation=row.game_creation,
            game_duration=row.game_duration,
            performance_score=row.performance_score,
        ),
    )


def _played_record_out(record: PlayedRecord | None) -> PlayedRecordOut | None:
    if record is None:
        return None
    return PlayedRecordOut(
        games=record.games,
        wins=record.wins,
        losses=record.losses,
        win_rate=record.win_rate,
        scored_games=record.scored_games,
        avg_score=record.avg_score,
        score_enough=record.scored_games >= MIN_SCORED_FOR_PROFILE,
        last_played=record.last_played,
        first_played=record.first_played,
    )


def _player_record_out(record: PlayerRecord | None) -> PlayerRecordOut | None:
    if record is None:
        return None
    overall = _played_record_out(record.overall)
    assert overall is not None
    return PlayerRecordOut(
        overall=overall,
        on_champion=_played_record_out(record.on_champion),
        main_position=record.main_position,
        main_position_games=record.main_position_games,
        positioned_games=record.positioned_games,
        on_main_position=record.on_main_position,
    )


def to_live_game(game, sd: StaticDataService, queue_name: str) -> LiveGameOut:
    """Live game to wire format.

    Note the spells and runes are resolved here exactly as they are for match
    history, so the two views look identical, even though the upstream payloads
    disagree on how to spell "perks".
    """
    return LiveGameOut(
        game_id=game.game_id,
        platform_id=game.platform_id,
        match_id=f"{game.platform_id}_{game.game_id}",
        queue_id=game.queue_id,
        queue_name=queue_name,
        game_mode=game.game_mode,
        map_id=game.map_id,
        phase=game.phase,
        game_start_time=game.game_start_time,
        game_length=game.game_length,
        observed_at=game.observed_at,
        banned_champions=[
            ChampionRef(
                id=c, name=sd.champion_name(c), icon_url=sd.champion_icon(c)
            )
            for c in game.banned_champion_ids
        ],
        participants=[
            LiveParticipantOut(
                state=p.state,
                puuid=p.puuid,
                riot_id=f"{p.game_name}#{p.tag_line}" if p.game_name and p.tag_line else None,
                champion=ChampionRef(
                    id=p.champion_id,
                    name=sd.champion_name(p.champion_id),
                    icon_url=sd.champion_icon(p.champion_id),
                ),
                team_id=p.team_id,
                spells=[
                    SpellRef(id=s, name=sd.spell_name(s), icon_url=sd.spell_icon(s))
                    for s in (p.spell1_id, p.spell2_id)
                    if s
                ],
                keystone=rune_ref(p.keystone_id, sd) if p.keystone_id else None,
                secondary_tree=(
                    rune_ref(p.secondary_style_id, sd) if p.secondary_style_id else None
                ),
                profile_icon_url=sd.profile_icon(p.profile_icon_id),
                rank=to_rank_info(p.rank) if p.rank else None,
                skin_tile_url=sd.champion_tile(p.champion_id, p.skin_index),
                position=p.position,
                position_confidence=p.position_confidence,
                position_basis=p.position_basis,
                mastery=(
                    LiveMasteryOut(**dataclasses.asdict(p.mastery)) if p.mastery else None
                ),
                mastery_known=p.mastery_known,
                champion_record=_corpus_record_out(p.champion_record),
                lane_record=_corpus_record_out(p.lane_record),
                stored_games=p.stored_games,
                record=_player_record_out(p.record),
                shared_games=(
                    SharedGamesOut(**dataclasses.asdict(p.shared_games))
                    if p.shared_games
                    else None
                ),
            )
            for p in game.participants
        ],
        bans=[
            LiveBanOut(
                champion=ChampionRef(
                    id=c, name=sd.champion_name(c), icon_url=sd.champion_icon(c)
                ),
                team_id=team,
                ban_rate=(game.ban_rates[c].ban_rate if c in game.ban_rates else None),
                ban_rate_games=(game.ban_rates[c].games if c in game.ban_rates else 0),
            )
            for c, team in game.bans
        ],
        positions_inferred=game.positions_inferred,
        position_model=(
            PositionModelOut(
                accuracy=MEASURED_ACCURACY,
                players_tested=MEASURED_PLAYERS,
                confident_at=CONFIDENT_AT,
            )
            if game.positions_inferred
            else None
        ),
        corpus_patch=game.corpus_patch,
        corpus_patches=game.corpus_patches,
        record_basis=game.record_basis,
        record_queue_id=game.record_queue_id,
        same_team_pairs=[
            SameTeamPairOut(**dataclasses.asdict(pair)) for pair in game.same_team_pairs
        ],
        sides=(
            LobbyCompareOut(
                **{**dataclasses.asdict(game.sides), "sides": [
                    SideReadOut(**dataclasses.asdict(side)) for side in game.sides.sides
                ]}
            )
            if game.sides
            else None
        ),
        # asdict, not vars: LobbyRank is a slots dataclass and has no __dict__.
        lobby_rank=(
            LobbyRankOut(**dataclasses.asdict(game.lobby_rank))
            if game.lobby_rank
            else None
        ),
        # Was computed by the service and then silently dropped here, so the
        # field defaulted to True and the one case it exists for -- an
        # anonymised searcher, whose own row cannot be found in their own game
        # -- could never be reported.
        you_identified=game.you_identified,
    )


def _objectives_out(match: Match, sd: StaticDataService) -> list[TeamObjectives]:
    """What each side did, built from the players the scoreboard actually shows.

    Kills and gold are summed from the participants rather than read from
    Riot's team objects, because the two do not always agree: in Arena the
    object for team 100 claims 42 kills while the nine players carrying that id
    have 72 between them. Measured on a stored 1750 lobby.

    The structure and monster counts have no participant to sum, so they are
    published only when Riot's team objects line up one-for-one with the sides
    on the scoreboard. Arena sends ids 100 and 0 against participants on 100 and
    200, so half of them describe nobody; there `objectives_known` is false and
    the UI leaves that group out rather than showing one side's counts and not
    the other's.
    """
    sides: dict[int, TeamObjectives] = {}
    for p in match.participants:
        side = sides.get(p.team_id)
        if side is None:
            side = TeamObjectives(team_id=p.team_id, win=p.win)
            sides[p.team_id] = side
        side.kills += p.kills
        side.gold += p.gold_earned

    by_id = {
        int(team.get("teamId") or -1): team for team in match.teams or []
    }
    aligned = set(by_id) == set(sides)

    for team_id, side in sides.items():
        side.objectives_known = aligned
        if not aligned:
            continue
        team = by_id[team_id]
        objectives = team.get("objectives") or {}

        def count(name: str, objectives: dict = objectives) -> int:
            # Bound as a default: a closure over the loop variable would read
            # the last team's objectives for every team.
            return int((objectives.get(name) or {}).get("kills") or 0)

        side.baron = count("baron")
        side.dragon = count("dragon")
        side.herald = count("riftHerald")
        side.tower = count("tower")
        side.inhibitor = count("inhibitor")
        side.bans = [
            _champion_ref(int(b["championId"]), sd)
            for b in (team.get("bans") or [])
            # -1 is Riot's "no ban", from a dodge or a timeout.
            if int(b.get("championId") or -1) > 0
        ]

    return [sides[team_id] for team_id in sorted(sides)]


def _score_model_out(match: Match) -> ScoreModelOut:
    """The model behind the scores on this scoreboard, published in full."""
    samples: dict[str, int] = {}
    for p in match.participants:
        sample = (p.performance_detail or {}).get("sample")
        if sample and p.team_position:
            samples[p.team_position] = sample
    return ScoreModelOut(
        version=WEIGHTS_VERSION,
        components=[
            {
                "id": c,
                "label": COMPONENT_LABELS[c][0],
                "measures": COMPONENT_LABELS[c][1],
            }
            for c in COMPONENTS
        ],
        weights=WEIGHTS,
        samples=samples,
        note=(
            "The Riftline score is ours, not Riot's. Each component is a "
            "percentile within the player's own role across the matches we hold, "
            "combined with the weights above. It describes one game against our "
            f"corpus, and is withheld below {MIN_GAMES_FOR_SCORE} games in a role."
        ),
    )


def to_match_detail(
    match: Match,
    sd: StaticDataService,
    platform: str | None = None,
    lanes: LaneLabel | None = None,
) -> MatchDetailResponse:
    """The expanded scoreboard: every player, the objectives, and the model."""
    minutes = max(1.0, match.game_duration / 60)
    team_kills: dict[int, int] = {}
    for p in match.participants:
        team_kills[p.team_id] = team_kills.get(p.team_id, 0) + p.kills

    by_team: dict[int, list[ScoreboardPlayer]] = {}
    for p in match.participants:
        item_ids = list(p.items or [])
        kills = team_kills.get(p.team_id) or 0
        by_team.setdefault(p.team_id, []).append(
            ScoreboardPlayer(
                puuid=p.puuid,
                riot_id=f"{p.riot_id_game_name}#{p.riot_id_tagline}"
                if p.riot_id_game_name
                else None,
                champion=_champion_ref(p.champion_id, sd),
                team_id=p.team_id,
                position=p.team_position,
                win=p.win,
                champ_level=p.champ_level,
                laning_score=p.laning_score,
                laning_label=(
                    lanes(match.queue_id, p.team_position, p.laning_score) if lanes else None
                ),
                kills=p.kills,
                deaths=p.deaths,
                assists=p.assists,
                kill_participation=((p.kills + p.assists) / kills) if kills else 0.0,
                cs=p.total_minions,
                cs_per_min=p.total_minions / minutes,
                gold_earned=p.gold_earned,
                damage_to_champions=p.damage_to_champions,
                damage_taken=p.damage_taken,
                vision_score=p.vision_score,
                wards_placed=p.wards_placed,
                wards_killed=p.wards_killed,
                control_wards=p.control_wards,
                items=[
                    ItemRef(id=i, name=sd.item_name(i), icon_url=sd.item_icon(i))
                    for i in item_ids[:6]
                    if i
                ],
                trinket=(
                    ItemRef(
                        id=item_ids[6],
                        name=sd.item_name(item_ids[6]),
                        icon_url=sd.item_icon(item_ids[6]),
                    )
                    if len(item_ids) > 6 and item_ids[6]
                    else None
                ),
                spells=[
                    SpellRef(id=sid, name=sd.spell_name(sid), icon_url=sd.spell_icon(sid))
                    for sid in (p.summoner1_id, p.summoner2_id)
                    if sid
                ],
                keystone=_keystone_art(p.perks, sd),
                score=p.performance_score,
                placement=p.performance_rank,
                badges=_badges_out(p, match),
            )
        )

    # Say why, rather than showing a scoreboard of dashes with no explanation:
    # the same reasons, in the same order, as each row of a history.
    withheld: str | None = None
    if match.participants and all(p.performance_score is None for p in match.participants):
        withheld = withheld_sentence(
            withheld_reason(match, match.participants[0]), len(match.participants)
        )

    return MatchDetailResponse(
        match_id=match.match_id,
        queue_id=match.queue_id,
        queue_name=sd.queue_name(match.queue_id),
        patch=match.patch,
        game_creation=match.game_creation,
        game_duration=match.game_duration,
        is_remake=match.is_remake,
        platform=platform or match.platform_id,
        score_withheld=withheld,
        teams=[by_team[team_id] for team_id in sorted(by_team)],
        objectives=_objectives_out(match, sd),
        model=_score_model_out(match) if withheld is None else None,
    )


# ------------------------------------------------------------------ groups


class GroupQueueOut(BaseModel):
    key: str
    label: str


class GroupChampionOut(BaseModel):
    champion: ChampionRef
    games: int
    wins: int
    win_rate: float
    kda: float


class GroupHistoryOut(BaseModel):
    """How much of this player's history is stored, and whether more is coming."""

    # Stored games in every queue, remakes left out.
    stored: int = 0
    # Epoch ms of the oldest of them.
    oldest: int | None = None
    # Ids of the history read so far, toward the group's cap.
    read: int = 0
    # Riot's list ran out before the cap.
    exhausted: bool = False
    # Still being fetched: the rank has not been read, or the history is short
    # of the cap with more to read.
    pending: bool = True


class GroupMemberOut(BaseModel):
    puuid: str
    riot_id: str
    game_name: str | None = None
    tag_line: str | None = None
    platform: str
    platform_label: str
    profile_icon_url: str | None = None
    summoner_level: int | None = None
    label: str | None = None
    added_at: int | None = None
    # The official ranks on the shard played on. Empty until read, and
    # `rank_read_at` says whether "unranked" is known or just not asked yet.
    ranks: list[RankInfo] = Field(default_factory=list)
    rank_read_at: int | None = None

    # Stored games in the chosen queues, newest first, up to the cap.
    games: int = 0
    wins: int = 0
    # Why the averages below are empty, when they are: too few games.
    withheld: str | None = None
    win_rate: float | None = None
    kda: float | None = None
    avg_kills: float | None = None
    avg_deaths: float | None = None
    avg_assists: float | None = None
    cs_per_min: float | None = None
    damage_per_min: float | None = None
    vision_per_min: float | None = None
    avg_minutes: float | None = None
    main_position: str | None = None
    positions: list[RoleShare] = Field(default_factory=list)
    champions: list[GroupChampionOut] = Field(default_factory=list)
    # Newest first: True for a win.
    recent: list[bool] = Field(default_factory=list)
    # The Riftline score over every scored game in the filter, and its count.
    scored_games: int = 0
    avg_score: float | None = None
    score_profile: list[RoleScoreProfileOut] = Field(default_factory=list)
    review: list[RoleReviewOut] = Field(default_factory=list)
    lanes: list[LaneRecordOut] = Field(default_factory=list)
    history: GroupHistoryOut = Field(default_factory=GroupHistoryOut)


class GroupPairOut(BaseModel):
    a: str
    b: str
    games: int
    wins: int
    win_rate: float


class TogetherPlayerOut(BaseModel):
    puuid: str
    champion: ChampionRef
    position: str | None = None
    kills: int
    deaths: int
    assists: int


class TogetherGameOut(BaseModel):
    match_id: str
    queue_id: int
    queue_name: str
    game_creation: int
    game_duration: int
    win: bool
    players: list[TogetherPlayerOut]


class GroupTogetherOut(BaseModel):
    """Stored games where two or more of the group played on the same side."""

    games: int = 0
    wins: int = 0
    min_pair_games: int
    pairs: list[GroupPairOut] = Field(default_factory=list)
    recent: list[TogetherGameOut] = Field(default_factory=list)


class GroupResponse(BaseModel):
    slug: str
    name: str
    created_at: int | None = None
    updated_at: int | None = None
    # True when the request carried this group's edit key.
    can_edit: bool = False
    max_members: int
    history_cap: int
    min_games: int
    queue: str
    queues: list[GroupQueueOut]
    # False for ARAM and Arena: no lanes, so no score, review or lane labels.
    scored_mode: bool = True
    # Official rank first, as the page orders it by default.
    members: list[GroupMemberOut] = Field(default_factory=list)
    together: GroupTogetherOut
    # Players still being fetched from Riot.
    pending: int = 0
    # Whether fetching can go on at all: a key is set and Riot accepts it.
    fetching: bool = True


class GroupWarmResponse(BaseModel):
    """One bounded pass of fetching a group's missing games from Riot."""

    pending: int = 0
    fetching: bool = True
    # The pass stopped to leave the key's last calls for searches.
    key_busy: bool = False
    # Seconds until asking again can get somewhere, when that is known.
    retry_after: float | None = None
    calls: int = 0
    games: int = 0


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GroupCreatedResponse(BaseModel):
    slug: str
    name: str
    # The edit key. Shown once: only a hash of it is kept.
    key: str


class GroupRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GroupKeyResponse(BaseModel):
    key: str


class GroupMemberAddRequest(BaseModel):
    riot_id: str = Field(min_length=3, max_length=64)
    platform: str = Field(min_length=2, max_length=8)
    label: str | None = Field(default=None, max_length=100)


class GroupMemberLabelRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)


class GroupMemberAddedResponse(BaseModel):
    puuid: str
    riot_id: str
    platform: str
    platform_label: str
