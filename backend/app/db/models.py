"""Database schema.

Shape of the data, and why:

* ``Player`` is keyed by PUUID, never by summoner name. Riot removed ``name``
  from summoner-v4 entirely, so the display name is a cached attribute of the
  account, not an identifier.
* ``Match`` keeps the **full raw payload** next to the normalized columns. On a
  rate-limited API the fetch is the expensive part; re-fetching 50k matches
  because we forgot to normalize a field would take weeks on a dev key. Disk is
  the cheap side of that trade.
* ``MatchParticipant`` is the workhorse: one row per player per match. Match
  history, champion stats, tier lists and draft matchups are all queries over
  this one table.
* ``ChampionStat`` / ``MatchupStat`` are rollups, recomputed from participants.
  They exist because scanning millions of participant rows per page view is not
  viable; they are derived data and can always be rebuilt.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Player(Base):
    __tablename__ = "players"

    puuid: Mapped[str] = mapped_column(String(78), primary_key=True)
    # Display name. Cached from account-v1 and refreshed on lookup, because
    # players rename and Riot IDs are not stable identifiers.
    game_name: Mapped[str | None] = mapped_column(String(64), index=True)
    # Cache key for lookups: lowercased with diacritics stripped. Riot matches
    # Riot IDs loosely -- searching "Caps" returns the account that displays as
    # "Cäps" -- so an exact-match cache never hits and every page view spends an
    # account-v1 call. See services.players.normalize_riot_name.
    search_name: Mapped[str | None] = mapped_column(String(64), index=True)
    tag_line: Mapped[str | None] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(8), index=True)
    profile_icon_id: Mapped[int | None] = mapped_column(Integer)
    summoner_level: Mapped[int | None] = mapped_column(Integer)
    revision_date: Mapped[int | None] = mapped_column(BigInteger)

    account_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summoner_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    league_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which shard the two caches above were filled from. A puuid is global but a
    # summoner record and a ranked entry are not: one account can hold a record
    # on several platforms, and holds none at all on most. Without these, the
    # level fetched for SG was served as the level on OCE.
    summoner_platform: Mapped[str | None] = mapped_column(String(8))
    league_platform: Mapped[str | None] = mapped_column(String(8))
    mastery_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Same reason, one endpoint later. Mastery is per shard too, and a lookup on
    # the wrong one answers 200 with an empty list, so without this the empty
    # answer was cached against the puuid and the real table stayed hidden for
    # the whole TTL. Measured on Veystrix#999, whose account is on SG2 and who
    # holds 100 champions there and none on the OCE route.
    mastery_platform: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # lazy="raise_on_sql": under asyncio an implicit lazy load does not just cost
    # a query, it fails with an opaque MissingGreenlet far from the cause. This
    # turns any accidental access into an error that names the attribute, and
    # forces call sites to load these explicitly. It also keeps a plain
    # `select(Player)` from dragging in ~170 mastery rows it does not need.
    ranks: Mapped[list[RankedEntry]] = relationship(
        back_populates="player", cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    masteries: Mapped[list[ChampionMastery]] = relationship(
        back_populates="player", cascade="all, delete-orphan", lazy="raise_on_sql"
    )

    __table_args__ = (
        # The index the cache lookup actually uses.
        Index("ix_players_search", "search_name", "tag_line", "platform"),
    )

    @property
    def riot_id(self) -> str:
        return f"{self.game_name}#{self.tag_line}"


class RankedEntry(Base):
    __tablename__ = "ranked_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    puuid: Mapped[str] = mapped_column(
        String(78), ForeignKey("players.puuid", ondelete="CASCADE"), index=True
    )
    queue_type: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str | None] = mapped_column(String(16))
    division: Mapped[str | None] = mapped_column(String(8))
    league_points: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    hot_streak: Mapped[bool] = mapped_column(Boolean, default=False)
    veteran: Mapped[bool] = mapped_column(Boolean, default=False)
    fresh_blood: Mapped[bool] = mapped_column(Boolean, default=False)
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    player: Mapped[Player] = relationship(back_populates="ranks")

    __table_args__ = (UniqueConstraint("puuid", "queue_type", name="uq_rank_puuid_queue"),)


class ChampionMastery(Base):
    __tablename__ = "champion_masteries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    puuid: Mapped[str] = mapped_column(
        String(78), ForeignKey("players.puuid", ondelete="CASCADE"), index=True
    )
    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    champion_level: Mapped[int] = mapped_column(Integer, default=0)
    champion_points: Mapped[int] = mapped_column(Integer, default=0)
    points_since_last_level: Mapped[int] = mapped_column(Integer, default=0)
    points_until_next_level: Mapped[int] = mapped_column(Integer, default=0)
    last_play_time: Mapped[int | None] = mapped_column(BigInteger)
    chest_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_earned: Mapped[int] = mapped_column(Integer, default=0)
    # Post-rework mastery: levels are uncapped and seasonal milestones carry
    # the per-game grades that drive marks.
    season_milestone: Mapped[int | None] = mapped_column(Integer)
    marks_required_next: Mapped[int | None] = mapped_column(Integer)
    milestone_grades: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    player: Mapped[Player] = relationship(back_populates="masteries")

    __table_args__ = (
        UniqueConstraint("puuid", "champion_id", name="uq_mastery_puuid_champ"),
    )


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    platform_id: Mapped[str] = mapped_column(String(8), index=True)
    queue_id: Mapped[int] = mapped_column(Integer, index=True)
    game_mode: Mapped[str | None] = mapped_column(String(24))
    game_type: Mapped[str | None] = mapped_column(String(24))
    game_version: Mapped[str | None] = mapped_column(String(32))
    # "15.18" -- derived from game_version, since stats are only comparable
    # within a patch.
    patch: Mapped[str | None] = mapped_column(String(12), index=True)
    map_id: Mapped[int | None] = mapped_column(Integer)
    game_creation: Mapped[int] = mapped_column(BigInteger, index=True)
    game_duration: Mapped[int] = mapped_column(Integer)
    game_end_timestamp: Mapped[int | None] = mapped_column(BigInteger)
    end_of_game_result: Mapped[str | None] = mapped_column(String(32))
    # Remakes and disconnects poison aggregates, so they are flagged at ingest.
    is_remake: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Which ladder the crawler was seeded from when it collected this match.
    # This is *provenance*, not a measurement: the ten players in a Challenger
    # -seeded game are not all Challenger, so the UI describes it as "crawled
    # from X" and never as "X games". The measured figure now lives in the
    # three lobby columns below, which are a different claim entirely.
    source_bracket: Mapped[str | None] = mapped_column(String(24), index=True)

    # Measured lobby rank: the **median** numeric_rank of this match's players.
    #
    # Median, not mean, because numeric_rank is ordinal with unequal steps (one
    # point from Diamond I to Master, six thousand from Master to Grandmaster).
    # A mean over that scale reports nine Gold players and one Challenger as
    # "Diamond III". The median is a rank somebody in the lobby actually holds.
    #
    # It is a measurement, unlike source_bracket, but it is measured *late*.
    # Riot exposes no historical rank anywhere, so this is every player's rank
    # on `lobby_rank_measured_at`, not their rank on the day they played. For a
    # game from three months ago that gap can be a whole tier, so the
    # measurement date travels with the number everywhere it is shown.
    lobby_rank_points: Mapped[float | None] = mapped_column(Float)
    lobby_ranked_players: Mapped[int | None] = mapped_column(Integer)
    lobby_rank_measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    teams: Mapped[list | None] = mapped_column(JSON)
    raw: Mapped[dict | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Ordered explicitly: without it the scoreboard's row order is whatever the
    # database happens to return, which can differ between two loads of the
    # same match.
    participants: Mapped[list[MatchParticipant]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        order_by="MatchParticipant.participant_index",
    )


class MatchTimeline(Base):
    """The per-minute record of one match.

    Kept in its own table, not as columns on ``Match``, because SQLAlchemy loads
    every column of a mapped row and match history loads twenty matches at a
    time. An 80 KB blob on ``Match`` would be dragged through the hottest query
    in the app for nothing.

    Two representations, deliberately:

    * ``extracted`` is the ~4 KB compact record every feature actually reads.
    * ``raw_gz`` is the whole payload, gzipped. Measured at 1.02 MB raw and 81 KB
      compressed, a 12.6x saving, which is what makes keeping it affordable at
      all. It is insurance: re-fetching a field we failed to extract would cost
      one Riot call per match, and we hold thousands.
    """

    __tablename__ = "match_timelines"

    match_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    extracted: Mapped[dict | None] = mapped_column(JSON)
    raw_gz: Mapped[bytes | None] = mapped_column(LargeBinary)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    # Which minute the laning comparison was actually taken at. Short games clamp
    # below 14, and saying so beats implying a measurement we did not make.
    laning_minute: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchParticipant(Base):
    __tablename__ = "match_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("matches.match_id", ondelete="CASCADE"), index=True
    )
    # Riot's participantId (1-10): blue team then red, in draft order.
    participant_index: Mapped[int] = mapped_column(Integer, default=0)
    puuid: Mapped[str] = mapped_column(String(78), index=True)
    # Denormalized from the match payload: match-v5 embeds riotIdGameName and
    # riotIdTagline for all ten players, so rendering a scoreboard costs zero
    # extra account-v1 calls.
    riot_id_game_name: Mapped[str | None] = mapped_column(String(64))
    riot_id_tagline: Mapped[str | None] = mapped_column(String(16))

    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    champion_name: Mapped[str | None] = mapped_column(String(32))
    team_id: Mapped[int] = mapped_column(Integer)
    # teamPosition is the matchmaking-assigned role and is the reliable one;
    # `lane`/`role` are legacy and frequently disagree with reality.
    team_position: Mapped[str | None] = mapped_column(String(16), index=True)
    individual_position: Mapped[str | None] = mapped_column(String(16))
    win: Mapped[bool] = mapped_column(Boolean, index=True)

    kills: Mapped[int] = mapped_column(Integer, default=0)
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    champ_level: Mapped[int] = mapped_column(Integer, default=0)
    gold_earned: Mapped[int] = mapped_column(Integer, default=0)
    total_minions: Mapped[int] = mapped_column(Integer, default=0)
    vision_score: Mapped[int] = mapped_column(Integer, default=0)
    damage_to_champions: Mapped[int] = mapped_column(Integer, default=0)
    damage_taken: Mapped[int] = mapped_column(Integer, default=0)
    heal_on_teammates: Mapped[int] = mapped_column(Integer, default=0)
    time_played: Mapped[int] = mapped_column(Integer, default=0)
    double_kills: Mapped[int] = mapped_column(Integer, default=0)
    triple_kills: Mapped[int] = mapped_column(Integer, default=0)
    quadra_kills: Mapped[int] = mapped_column(Integer, default=0)
    penta_kills: Mapped[int] = mapped_column(Integer, default=0)
    first_blood_kill: Mapped[bool] = mapped_column(Boolean, default=False)
    early_surrender: Mapped[bool] = mapped_column(Boolean, default=False)

    summoner1_id: Mapped[int | None] = mapped_column(Integer)
    summoner2_id: Mapped[int | None] = mapped_column(Integer)
    items: Mapped[list | None] = mapped_column(JSON)
    perks: Mapped[dict | None] = mapped_column(JSON)

    # --- derived from the match timeline -----------------------------------
    # All nullable: a match only has these once its timeline has been fetched,
    # and a lane with no opposite number (ARAM, Arena) never gets a score at all.
    # They live here rather than behind a join because match history, the
    # aggregations and the champion page all need them, exactly like `items`.
    #
    # laning_score is a 0..1 share of the lane pair's resources at minute 14,
    # which renders as op.gg's "48 : 52".
    laning_score: Mapped[float | None] = mapped_column(Float)
    opponent_champion_id: Mapped[int | None] = mapped_column(Integer)
    gold_at_14: Mapped[int | None] = mapped_column(Integer)
    xp_at_14: Mapped[int | None] = mapped_column(Integer)
    cs_at_14: Mapped[int | None] = mapped_column(Integer)
    gold_diff_14: Mapped[int | None] = mapped_column(Integer)
    xp_diff_14: Mapped[int | None] = mapped_column(Integer)
    cs_diff_14: Mapped[int | None] = mapped_column(Integer)
    # Skill slots 1-4 in the order they were levelled.
    skill_order: Mapped[list | None] = mapped_column(JSON)
    # Item ids in true purchase order, replayed against undos and sells.
    build_order: Mapped[list | None] = mapped_column(JSON)

    # --- lifted out of `Match.raw` --------------------------------------
    # Riot sends 155 participant fields plus 130 `challenges`; the ingest maps
    # the ones every page needs. These are the rest of what the performance
    # score, its badges and the scoreboard read. They come from storage, not
    # from Riot, so they are backfilled at disk speed by `scripts.ingest score`.
    #
    # Nullable on purpose: null means "not lifted yet", which is the cursor that
    # backfill walks, and it is a different fact from a zero.
    time_dead: Mapped[int | None] = mapped_column(Integer)
    turret_takedowns: Mapped[int | None] = mapped_column(Integer)
    turret_plates: Mapped[int | None] = mapped_column(Integer)
    # Dragon, baron and herald takedowns summed: one objective term, and the
    # three are never shown apart.
    epic_takedowns: Mapped[int | None] = mapped_column(Integer)
    objectives_stolen: Mapped[int | None] = mapped_column(Integer)
    solo_kills: Mapped[int | None] = mapped_column(Integer)
    # Riot's `effectiveHealAndShielding`, which counts what actually landed on
    # an ally rather than the raw number healed.
    heal_and_shield: Mapped[int | None] = mapped_column(Integer)
    wards_placed: Mapped[int | None] = mapped_column(Integer)
    wards_killed: Mapped[int | None] = mapped_column(Integer)
    control_wards: Mapped[int | None] = mapped_column(Integer)

    # --- the Riftline score ------------------------------------------------
    # Ours, not Riot's: six role-relative percentiles over our own corpus,
    # combined with published weights. See app/services/scores.py.
    #
    # Withheld (null) rather than guessed whenever the sample cannot carry it:
    # a lobby that is not ten players with known roles, a remake, or a role
    # whose distribution is under MIN_GAMES_FOR_SCORE.
    performance_score: Mapped[float | None] = mapped_column(Float)
    # Placement within the lobby, 1 (best) to 10.
    performance_rank: Mapped[int | None] = mapped_column(Integer)
    # {"components": {...}, "badges": [...], "sample": n, "weights": version}.
    # The components travel with the score so the UI can show why, and the
    # weights version makes a score computed under old weights visibly stale
    # instead of quietly inconsistent.
    performance_detail: Mapped[dict | None] = mapped_column(JSON)
    performance_scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    match: Mapped[Match] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("match_id", "puuid", name="uq_participant_match_puuid"),
        # Drives "this player's match history", the hottest query in the app.
        Index("ix_participant_puuid_match", "puuid", "match_id"),
        # Drives champion aggregates.
        Index("ix_participant_champ_pos", "champion_id", "team_position"),
    )

    @property
    def kda(self) -> float:
        return (self.kills + self.assists) / max(1, self.deaths)


class ChampionStat(Base):
    """Rollup of champion performance, recomputed from participants."""

    __tablename__ = "champion_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(String(12), index=True)
    queue_id: Mapped[int] = mapped_column(Integer, index=True)
    rank_bracket: Mapped[str] = mapped_column(String(24), index=True, default="ALL")
    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    team_position: Mapped[str] = mapped_column(String(16), default="ALL")

    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    # Denominator for pick/ban rate: total games in this slice.
    pool_games: Mapped[int] = mapped_column(Integer, default=0)
    bans: Mapped[int] = mapped_column(Integer, default=0)

    avg_kills: Mapped[float] = mapped_column(Float, default=0.0)
    avg_deaths: Mapped[float] = mapped_column(Float, default=0.0)
    avg_assists: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cs_per_min: Mapped[float] = mapped_column(Float, default=0.0)
    avg_gold: Mapped[float] = mapped_column(Float, default=0.0)
    avg_damage: Mapped[float] = mapped_column(Float, default=0.0)
    avg_vision: Mapped[float] = mapped_column(Float, default=0.0)

    # Laning averages cover only the rows that had a timeline. timeline_games
    # records how many that was, so a half-backfilled corpus reports an average
    # over what it measured instead of quietly over-claiming.
    timeline_games: Mapped[int] = mapped_column(Integer, default=0)
    avg_laning_score: Mapped[float | None] = mapped_column(Float)
    avg_gold_diff_14: Mapped[float | None] = mapped_column(Float)
    avg_cs_diff_14: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "patch", "queue_id", "rank_bracket", "champion_id", "team_position",
            name="uq_champion_stat_slice",
        ),
    )

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def pick_rate(self) -> float:
        return self.games / self.pool_games if self.pool_games else 0.0


class MatchupStat(Base):
    """Head-to-head record against an opponent. Feeds the draft assistant.

    Two scopes, because they answer different questions:

    * ``LANE`` is the player you stand next to for fifteen minutes, matched on
      the same ``team_position``. This is what "counters" usually means.
    * ``TEAM`` is the champion against every enemy regardless of lane. A pick can
      be fine against its laner and miserable against the enemy composition, and
      only this scope sees that. It is the factor the draft assistant was missing.
    """

    __tablename__ = "matchup_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(String(12), index=True)
    queue_id: Mapped[int] = mapped_column(Integer)
    rank_bracket: Mapped[str] = mapped_column(String(24), index=True, default="ALL")
    scope: Mapped[str] = mapped_column(String(8), index=True, default="LANE")
    team_position: Mapped[str] = mapped_column(String(16), index=True)
    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    enemy_champion_id: Mapped[int] = mapped_column(Integer, index=True)
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    # Turns "you lose this matchup" into "you lose this lane by 400 gold".
    timeline_games: Mapped[int] = mapped_column(Integer, default=0)
    avg_laning_score: Mapped[float | None] = mapped_column(Float)
    avg_gold_diff_14: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "patch", "queue_id", "rank_bracket", "scope",
            "team_position", "champion_id", "enemy_champion_id",
            name="uq_matchup_slice",
        ),
        Index(
            "ix_matchup_lookup",
            "patch", "queue_id", "scope", "team_position", "enemy_champion_id",
        ),
    )


class SynergyStat(Base):
    """How a champion performs alongside a given ally.

    Directed: a row for (me, ally) and another for (ally, me). That doubles the
    rows but keeps every lookup a single indexed filter, and this is derived data
    that is rebuilt wholesale anyway. Same choice as MatchupStat.
    """

    __tablename__ = "synergy_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(String(12), index=True)
    queue_id: Mapped[int] = mapped_column(Integer)
    rank_bracket: Mapped[str] = mapped_column(String(24), index=True, default="ALL")
    team_position: Mapped[str] = mapped_column(String(16), index=True)
    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    ally_position: Mapped[str] = mapped_column(String(16))
    ally_champion_id: Mapped[int] = mapped_column(Integer, index=True)
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "patch", "queue_id", "rank_bracket",
            "team_position", "champion_id", "ally_position", "ally_champion_id",
            name="uq_synergy_slice",
        ),
    )


class ChampionFacetStat(Base):
    """Everything a champion *took*: items, runes, summoner spells.

    One table rather than four, because they all share a shape -- a key, plus
    games and wins -- and a single aggregation pass and a single API shape is
    worth more than four narrowly-typed tables. Group B adds skill order as
    another ``facet`` value with no schema change.

    ``facet_key`` is built from **sorted** ids. That is not a detail: a
    participant's ``items`` array is inventory position, not purchase order (the
    same boots appear in all six slots across the corpus), so the only honest
    aggregation is an order-independent set. Build *paths* need match timelines.
    """

    __tablename__ = "champion_facet_stats"

    # build:     the complete set of legendary items held at the end
    # item:      one legendary, counted on its own (survives small samples best)
    # boots:     the boots worn
    # keystone:  the primary keystone
    # rune_page: full page signature, both trees plus shards
    # spells:    the summoner spell pair
    #
    # build_path:     the first three legendary completions, in purchase order
    # skill_priority: which abilities were maxed and in what order (Q then E then W)
    # skill_order:    the exact level-up sequence; high cardinality, useful at scale
    #
    # The last three arrive from match timelines. build_path is the ordered
    # answer that `build` could only approximate from a final inventory.
    FACETS = (
        "build", "item", "boots", "keystone", "rune_page", "spells",
        "build_path", "skill_priority", "skill_order",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(String(12), index=True)
    queue_id: Mapped[int] = mapped_column(Integer, index=True)
    rank_bracket: Mapped[str] = mapped_column(String(24), index=True, default="ALL")
    champion_id: Mapped[int] = mapped_column(Integer, index=True)
    team_position: Mapped[str] = mapped_column(String(16), default="ALL")

    facet: Mapped[str] = mapped_column(String(16), index=True)
    facet_key: Mapped[str] = mapped_column(String(128))
    facet_ids: Mapped[list | None] = mapped_column(JSON)

    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    # Games by this champion in this slice, so the UI can show a pick rate for
    # the facet rather than a bare count.
    champion_games: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "patch", "queue_id", "rank_bracket", "champion_id", "team_position",
            "facet", "facet_key",
            name="uq_facet_slice",
        ),
        Index(
            "ix_facet_lookup",
            "patch", "queue_id", "champion_id", "team_position", "facet",
        ),
    )

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def pick_rate(self) -> float:
        return self.games / self.champion_games if self.champion_games else 0.0


class LadderEntry(Base):
    """One rung of a ranked ladder, as of the last snapshot.

    Deliberately **not** foreign-keyed to ``players.puuid``, unlike
    :class:`RankedEntry`. A ladder is a snapshot of strangers: Master alone is
    ten thousand rows, and forcing a stub player row for each one to satisfy a
    constraint would make every refresh an order of magnitude more expensive
    and fill ``players`` with accounts nobody will ever look up. ``RankedEntry``
    is the opposite case, hanging off a player we are actively tracking.

    Names are therefore resolved by a LEFT JOIN at read time and may be absent.
    That is a real property of the data, not a gap to paper over: a ladder in a
    region we have never crawled is genuinely a list of anonymous PUUIDs until
    somebody pays to name it.
    """

    __tablename__ = "ladder_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)
    queue_type: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))
    # "I" for the apex tiers, which have no divisions, so the unique constraint
    # never has to compare NULLs.
    division: Mapped[str] = mapped_column(String(8), default="I")
    puuid: Mapped[str] = mapped_column(String(78), index=True)

    # 1-based, assigned by us from an LP sort. Riot does not promise the order
    # its ladder endpoints return, so trusting it would be a silent bug.
    position: Mapped[int] = mapped_column(Integer, default=0)
    league_points: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)

    hot_streak: Mapped[bool] = mapped_column(Boolean, default=False)
    veteran: Mapped[bool] = mapped_column(Boolean, default=False)
    fresh_blood: Mapped[bool] = mapped_column(Boolean, default=False)
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "platform", "queue_type", "tier", "division", "puuid",
            name="uq_ladder_slot",
        ),
        Index(
            "ix_ladder_page",
            "platform", "queue_type", "tier", "division", "position",
        ),
    )


class RoleMetricStat(Base):
    """Distribution of one performance metric within one role.

    The Riftline score is a percentile, so it needs the shape of the population
    it is a percentile of. This holds that shape as 101 breakpoints: the value
    at the 0th, 1st ... 100th percentile of every (queue, role, metric) we can
    measure. Scoring a game is then a bisect against a stored array rather than
    a scan of eighteen thousand rows.

    Deliberately not keyed by patch. A champion's win rate moves every patch and
    `ChampionStat` is keyed accordingly, but what a mid laner's damage share
    looks like does not, and slicing by patch would drop every role under the
    sample floor for no gain in accuracy.
    """

    __tablename__ = "role_metric_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, index=True)
    team_position: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(24))
    # 101 floats, ascending: index i is the value at the i-th percentile.
    breakpoints: Mapped[list] = mapped_column(JSON)
    # The sample behind the distribution, shown in the UI beside the score.
    games: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "queue_id", "team_position", "metric", name="uq_role_metric"
        ),
    )


class IngestCursor(Base):
    """Bookmark for the crawler so restarts resume instead of re-walking."""

    __tablename__ = "ingest_cursors"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
