"""Application settings, loaded from the environment or backend/.env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Riot ---------------------------------------------------------------
    riot_api_key: str = Field(default="", alias="RIOT_API_KEY")
    default_platform: str = Field(default="euw1", alias="DEFAULT_PLATFORM")

    # A development key is 20:1,100:120. Override once you hold a personal or
    # production key -- same syntax Riot uses in X-App-Rate-Limit.
    app_rate_limits: str = Field(default="20:1,100:120", alias="APP_RATE_LIMITS")

    riot_timeout_seconds: float = Field(default=10.0, alias="RIOT_TIMEOUT_SECONDS")
    riot_max_retries: int = Field(default=3, alias="RIOT_MAX_RETRIES")
    # How long one web request may spend waiting on the rate limiter, counted
    # from when it arrived. Past that it answers 429 with a Retry-After rather
    # than waiting on. Cloudflare abandons an origin at 100 seconds, and a
    # request also spends time on the calls themselves, so this sits well
    # inside that. The ingest CLI has no such limit and waits for the key.
    riot_wait_budget_seconds: float = Field(default=40.0, alias="RIOT_WAIT_BUDGET_SECONDS")

    # --- Storage ------------------------------------------------------------
    # SQLite by default so the project runs with no external services. The
    # schema and every query are written to move to Postgres by URL alone.
    # Relative paths are anchored to the project root by db.base.normalize_database_url,
    # not to the process CWD, so no "../" is needed here.
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/lol.db", alias="DATABASE_URL"
    )

    # --- Cache TTLs (seconds) ----------------------------------------------
    # Matches are immutable once played, so they are cached permanently in the
    # database and never re-fetched. These cover the mutable resources.
    ttl_account: int = Field(default=86_400, alias="TTL_ACCOUNT")
    ttl_summoner: int = Field(default=600, alias="TTL_SUMMONER")
    ttl_league: int = Field(default=300, alias="TTL_LEAGUE")
    ttl_mastery: int = Field(default=600, alias="TTL_MASTERY")
    ttl_match_ids: int = Field(default=120, alias="TTL_MATCH_IDS")
    ttl_static: int = Field(default=21_600, alias="TTL_STATIC")
    # The measured lobby ranks behind a slice: the tier list, champion pages and
    # the draft read them, and they change only when the nightly run measures.
    ttl_lobby_ranks: int = Field(default=3600, alias="TTL_LOBBY_RANKS")
    # The patches and queues held, and the corpus summary built on them: every
    # page's slice controls read them, and they move only when the nightly
    # aggregate runs, in another process.
    ttl_corpus: int = Field(default=300, alias="TTL_CORPUS")

    # --- Features -----------------------------------------------------------
    # Riot announced Spectator-V5's deactivation in Oct 2025 over player
    # anonymity. Live-game lookup stays behind this flag so its removal
    # degrades the draft tool instead of breaking it.
    enable_spectator: bool = Field(default=True, alias="ENABLE_SPECTATOR")

    # Ranks for the other nine people in a lobby, who nobody searched for.
    # Longer than ttl_league because twenty LP of drift on a stranger is
    # irrelevant, and because the alternative is nine Riot calls per page view.
    ttl_league_bulk: int = Field(default=900, alias="TTL_LEAGUE_BULK")
    # How long a live-game view will wait for those ranks before rendering
    # without them. Partial is the right answer: whatever landed is cached, so
    # the client's next poll completes the roster.
    spectator_rank_budget_seconds: float = Field(
        default=8.0, alias="SPECTATOR_RANK_BUDGET_SECONDS"
    )

    # Resolving a finished live game into its stored match is the only Riot call
    # the live page spends beyond the lookup itself, so both dials are settings:
    # production can widen them without a deploy, the way the rank budget can.
    # Riot publishes a match a minute or two after it ends, so asking more than
    # once every 45 seconds cannot make it arrive sooner, it only multiplies the
    # spend by the number of open tabs.
    live_result_cooldown_seconds: float = Field(
        default=45.0, alias="LIVE_RESULT_COOLDOWN_SECONDS"
    )
    # Three attempts per match id, which is the promise the page makes: at most
    # three Riot calls per finished game however many people are watching it.
    live_result_max_attempts: int = Field(default=3, alias="LIVE_RESULT_MAX_ATTEMPTS")

    # Ladder snapshots. A ladder is one Riot call, so these are short; Master is
    # ten thousand entries and a multi-megabyte transfer, so it is not.
    ttl_ladder: int = Field(default=900, alias="TTL_LADDER")
    ttl_ladder_master: int = Field(default=3600, alias="TTL_LADDER_MASTER")

    # --- Groups -------------------------------------------------------------
    # How far back a group reaches for each player: their newest N games, in
    # every queue, when they are added (new games are added as they are
    # played). Each costs one Riot call the first time and about 85 KB of
    # storage, 160 KB with a timeline, so this one number is the dial for both.
    group_history_cap: int = Field(default=300, alias="GROUP_HISTORY_CAP")
    # Riot calls the nightly `groups` stage may spend, most recently viewed
    # groups first. About 50 minutes of a development key.
    group_nightly_calls: int = Field(default=2000, alias="GROUP_NIGHTLY_CALLS")
    # Per visitor address, per hour. There is no login, so these are what stops
    # one script from filling the database with groups or the key with lookups.
    group_creates_per_hour: int = Field(default=10, alias="GROUP_CREATES_PER_HOUR")
    group_adds_per_hour: int = Field(default=60, alias="GROUP_ADDS_PER_HOUR")

    # Where the site lives, for the sitemap and the canonical links the
    # prerenderer writes. Absolute, because a sitemap must be.
    site_origin: str = Field(default="https://www.rhasta.space", alias="SITE_ORIGIN")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS"
    )

    @field_validator("default_platform")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def parsed_rate_limits(self) -> list[tuple[int, float]]:
        from app.riot.limiter import DEV_KEY_LIMITS, parse_limit_header

        return parse_limit_header(self.app_rate_limits) or DEV_KEY_LIMITS

    @property
    def has_key(self) -> bool:
        return bool(self.riot_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
