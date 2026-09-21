/**
 * Typed client for the analytics API.
 *
 * Field names are snake_case because that is what FastAPI serialises; keeping
 * them identical on both sides removes a whole class of "why is this undefined"
 * bugs that mapping layers introduce.
 */

export interface ChampionRef {
  id: number
  name: string
  icon_url: string | null
}

export interface ItemRef {
  id: number
  name: string | null
  icon_url: string | null
}

export interface SpellRef {
  id: number | null
  name: string | null
  icon_url: string | null
}

export interface RuneRef {
  id: number | null
  icon_url: string | null
}

export interface RankInfo {
  queue: string
  queue_label: string
  tier: string | null
  division: string | null
  league_points: number
  wins: number
  losses: number
  win_rate: number
  games: number
  hot_streak: boolean
  inactive: boolean
  numeric_rank: number
}

/**
 * What we know about one player in a live game.
 *
 * `state` is the honest part. Since 2025 players can hide their identity from
 * third-party tools, and roughly a third of a lobby does: those come back
 * `hidden` with no name, no rank and nothing to link to. `unknown` is different
 * again, meaning the rank lookup did not finish, which is not the same claim as
 * `unranked`.
 */
export type LiveState = 'ranked' | 'unranked' | 'hidden' | 'bot' | 'unknown'

export interface LiveParticipant {
  state: LiveState
  puuid: string | null
  riot_id: string | null
  champion: ChampionRef
  team_id: number
  spells: SpellRef[]
  keystone: RuneRef | null
  secondary_tree: RuneRef | null
  profile_icon_url: string | null
  rank: RankInfo | null
  /** The skin this player is wearing, as square art. */
  skin_tile_url: string | null
  /** Inferred: spectator carries no position. See `position_model` on the game. */
  position: Position | null
  position_confidence: number | null
  /** 'smite' for a team's only Smite, which is certain. */
  position_basis: 'smite' | 'inferred' | null
  mastery: LiveMastery | null
  /** False: we did not find out. True with no `mastery`: never played it. */
  mastery_known: boolean
  /** This champion in this position, from our stored games. */
  champion_record: CorpusRecord | null
  /** This champion against the lane opponent, from our stored games. */
  lane_record: CorpusRecord | null
  /** How many games we hold for this player. Always present, including zero:
   *  "we hold nothing" and "we hold two" are different facts. */
  stored_games: number
  /** What those games say about them, or null when we hold too few. */
  record: PlayerRecord | null
}

export type Position = 'TOP' | 'JUNGLE' | 'MIDDLE' | 'BOTTOM' | 'UTILITY'

/** A player's own record from the games Riftline has stored. Withheld rather
 *  than zeroed: `stored_games` on the participant says how little we hold. */
export interface PlayedRecord {
  games: number
  wins: number
  losses: number
  /** Null under 10 games: one game would move it ten points. */
  win_rate: number | null
  scored_games: number
  avg_score: number | null
  score_enough: boolean
  last_played: number | null
  first_played: number | null
}

export interface PlayerRecord {
  overall: PlayedRecord
  /** Null means we hold no stored game of theirs on this champion. That is not
   *  "they have never played it": mastery answers that. */
  on_champion: PlayedRecord | null
  main_position: Position | null
  main_position_games: number
  positioned_games: number
  /** Null whenever either side of the comparison is unknown. */
  on_main_position: boolean | null
  min_games: number
  min_games_for_win_rate: number
}

export interface LiveMastery {
  level: number
  points: number
  last_play_time: number | null
}

/** Which step of the lane fallback produced a record. A record always carries
 *  its size, and anything below `lane` also carries its basis. Anything below `lane`
 *  Anything below `lane` must be labelled where it is shown: a team scope
 *  record rendered as a lane record is a claim the data does not support. */
export type RecordBasis = 'role' | 'lane' | 'lane_pooled' | 'team'

export interface CorpusRecord {
  games: number
  wins: number
  win_rate: number
  /** Lane records only, and only with enough timelines behind it. */
  gold_diff_14: number | null
  timeline_games: number
  basis: RecordBasis
  /** The patches this record was summed over, newest first. */
  patches: string[]
}

export interface LiveBan {
  champion: ChampionRef
  team_id: number
}

/** How far an inferred position can be trusted. Measured on held-out games. */
export interface PositionModel {
  accuracy: number
  players_tested: number
  /** At or above this a position is shown plainly; below it, as "likely". */
  confident_at: number
}

export interface LobbyRank {
  /** The median, not the mean. See the backend note on why. */
  median_points: number | null
  tier: string | null
  division: string | null
  /** The median player's own LP. Apex tiers span thousands of it. */
  league_points: number | null
  ranked: number
  unranked: number
  hidden: number
  bots: number
  unknown: number
  queue_type: string
  queue_matches_game: boolean
}

/** One side of a live lobby, summed from what the lobby already shows. */
export interface SideRead {
  team_id: number
  median_points: number | null
  tier: string | null
  division: string | null
  league_points: number | null
  ranked: number
  unranked: number
  hidden: number
  bots: number
  unknown: number
  /** Tier boundaries from the searched player to this side's median. */
  tier_gap: number | null
  /** Only below Master, where the rank scale is uniform. */
  points_gap: number | null
  gap_basis: 'points' | 'tiers_only' | 'withheld'
  lanes_favoured: number
  off_champion: number
  off_champion_known: number
  off_role: number
  off_role_known: number
}

/** The two sides beside each other. Carries no win probability and no verdict:
 *  the site holds no model that predicts a game, and a third of every lobby
 *  hides its identity in a way that is not missing at random. */
export interface LobbyCompare {
  sides: SideRead[]
  you_team_id: number | null
  lanes_with_record: number
  lanes_level: number
  lanes_total: number
  min_ranked_per_side: number
}

export interface LiveGame {
  game_id: number
  platform_id: string
  queue_id: number
  queue_name: string
  game_mode: string | null
  map_id: number | null
  phase: 'loading' | 'in_progress'
  game_start_time: number
  game_length: number
  /** Our clock when Riot answered. The timer runs forward from this locally. */
  observed_at: number
  banned_champions: ChampionRef[]
  /** The same bans with their side, in pick order. */
  bans: LiveBan[]
  participants: LiveParticipant[]
  lobby_rank: LobbyRank | null
  you_identified: boolean
  /** True when every player has a position, so the game can be shown by lane. */
  positions_inferred: boolean
  position_model: PositionModel | null
  /** The patch the champion and lane records were read from. */
  corpus_patch: string | null
  /** Every patch the lane fallback was allowed to read, newest first. */
  corpus_patches: string[]
  /** Which games each player's own record was counted over. The crawl is nearly
   *  all solo queue, so a flex lobby is counted over every queue and says so. */
  record_basis: 'queue' | 'all_queues'
  record_queue_id: number | null
  /** Null off Summoner's Rift, where there are no two sides to compare. */
  sides: LobbyCompare | null
}

/** The newest game Riftline holds for a player, for the page they see when they
 *  are not playing. Not the newest game they played: the corpus is crawled, and
 *  for a player with 5+ stored games the newest is a median of 4 days old. */
export interface LastStoredGame {
  match_id: string
  queue_id: number
  queue_name: string
  champion: ChampionRef
  position: Position | null
  win: boolean
  kills: number
  deaths: number
  assists: number
  game_creation: number
  game_duration: number
  performance_score: number | null
}

export interface IdleSummary {
  stored_games: number
  last_game: LastStoredGame | null
  basis: string
}

export interface LiveGameResponse {
  puuid: string
  platform: string
  in_game: boolean
  game: LiveGame | null
  /** Only when they are not in a game. */
  idle: IdleSummary | null
  checked_at: number
}

export interface LeaderboardRow {
  position: number
  puuid: string
  /** Null where we have never seen the account: league-v4 carries no names. */
  riot_id: string | null
  tier: string
  division: string | null
  league_points: number
  wins: number
  losses: number
  games: number
  win_rate: number
  hot_streak: boolean
  veteran: boolean
  fresh_blood: boolean
  inactive: boolean
  numeric_rank: number
}

export interface LeaderboardResponse {
  platform: string
  platform_label: string
  queue_id: number
  queue_label: string
  tier: string
  division: string | null
  page: number
  per_page: number
  /** Rows we hold and can page through. */
  total: number
  /** The ladder's real size, or null when it is genuinely not known. */
  total_on_ladder: number | null
  /** The ladder continues past what we store. */
  truncated: boolean
  has_more: boolean
  named_on_page: number
  fetched_at: number | null
  rows: LeaderboardRow[]
}

export interface LeaderboardSlices {
  platforms: { id: string; label: string }[]
  queues: { id: number; label: string }[]
  tiers: string[]
  divisions: string[]
  apex_tiers: string[]
}

export interface Profile {
  puuid: string
  game_name: string | null
  tag_line: string | null
  riot_id: string
  platform: string
  platform_label: string
  summoner_level: number | null
  profile_icon_url: string | null
  ranks: RankInfo[]
  /** Set when this Riot ID has no summoner record on the platform asked for. */
  plays_on: string | null
  plays_on_label: string | null
  /** The level and icon above were read from `plays_on`, not from this region. */
  identity_from_plays_on: boolean
  /** Epoch ms of the rank reading shown. */
  updated_at: number | null
  /** Position on the stored solo ladder, when they are on one and it is fresh. */
  ladder: {
    tier: string
    tier_position: number
    /** Across the whole region; null when a higher tier's size is unknown. */
    position: number | null
    platform: string
    platform_label: string
    /** Epoch ms of the snapshot. */
    as_of: number
  } | null
}

/** A badge, with the rule that earned it and this player's own figure. */
export interface Badge {
  id: string
  label: string
  detail: string
}

/** One of the six things the Riftline score is made of. */
export interface ScoreComponent {
  id: string
  label: string
  measures: string
  /** Where this player fell in their role's distribution, 0 to 1. */
  percentile: number
  /** What the component is worth for that role, 0 to 1. */
  weight: number
}

export interface ParticipantBrief {
  puuid: string
  riot_id: string | null
  champion: ChampionRef
  team_id: number
  position: string | null
  kills: number
  deaths: number
  assists: number
  win: boolean
  /** Null together: a placement with no score behind it would be a ranking of nothing. */
  score: number | null
  placement: number | null
  badges: Badge[]
}

export interface MatchSummary {
  match_id: string
  queue_id: number
  queue_name: string
  patch: string | null
  game_creation: number
  game_duration: number
  is_remake: boolean
  win: boolean
  champion: ChampionRef
  champ_level: number
  position: string | null
  kills: number
  deaths: number
  assists: number
  kda: number
  kill_participation: number
  cs: number
  cs_per_min: number
  gold_earned: number
  vision_score: number
  damage_to_champions: number
  damage_per_min: number
  items: ItemRef[]
  trinket: ItemRef | null
  spells: SpellRef[]
  keystone: RuneRef | null
  secondary_tree: RuneRef | null
  multi_kill: string | null
  /** From the match timeline; null until that match has been backfilled. */
  laning_score: number | null
  laning_opponent: ChampionRef | null
  gold_diff_14: number | null
  /**
   * Measured lobby rank. `lobby_rank_measured_at` is not optional detail: this
   * is every player's rank on that date, not their rank on the day the game was
   * played, because Riot exposes no historical rank at all.
   */
  lobby_rank_points: number | null
  lobby_rank_tier: string | null
  lobby_rank_division: string | null
  lobby_ranked_players: number | null
  lobby_players_total: number | null
  lobby_rank_measured_at: number | null
  /** False for ARAM and Arena: the figure is solo-queue standing. */
  lobby_queue_matches_game: boolean
  cs_diff_14: number | null
  /**
   * The Riftline score: ours, not Riot's. Null until `scripts.ingest score` has
   * run, and null for good on any lobby it cannot measure (no lane roles, a
   * remake, a queue the corpus is too thin to be a percentile of).
   */
  score: number | null
  placement: number | null
  badges: Badge[]
  score_components: ScoreComponent[]
  score_sample: number | null
  teams: ParticipantBrief[][]
}

export interface ScoreboardPlayer {
  puuid: string
  riot_id: string | null
  champion: ChampionRef
  team_id: number
  position: string | null
  win: boolean
  champ_level: number
  kills: number
  deaths: number
  assists: number
  kill_participation: number
  cs: number
  cs_per_min: number
  gold_earned: number
  damage_to_champions: number
  damage_taken: number
  vision_score: number
  wards_placed: number | null
  wards_killed: number | null
  control_wards: number | null
  items: ItemRef[]
  trinket: ItemRef | null
  spells: SpellRef[]
  keystone: RuneRef | null
  score: number | null
  placement: number | null
  badges: Badge[]
}

export interface TeamObjectives {
  team_id: number
  win: boolean
  /** Summed from this side's own players, not read from Riot's team object. */
  kills: number
  gold: number
  /** False when Riot's team objects do not line up with the sides shown. */
  objectives_known: boolean
  baron: number
  dragon: number
  herald: number
  tower: number
  inhibitor: number
  bans: ChampionRef[]
}

/** How the score is computed, published with every scoreboard. */
export interface ScoreModel {
  version: number
  components: { id: string; label: string; measures: string }[]
  weights: Record<string, Record<string, number>>
  samples: Record<string, number>
  note: string
}

export interface MatchDetail {
  match_id: string
  queue_id: number
  queue_name: string
  patch: string | null
  game_creation: number
  game_duration: number
  is_remake: boolean
  platform: string | null
  /** Why there are no scores, when there are none. */
  score_withheld: string | null
  teams: ScoreboardPlayer[][]
  objectives: TeamObjectives[]
  model: ScoreModel | null
}

export interface MatchHistory {
  puuid: string
  matches: MatchSummary[]
  start: number
  count: number
  has_more: boolean
}

export interface MasteryEntry {
  champion: ChampionRef
  level: number
  points: number
  points_since_last_level: number
  points_until_next_level: number
  progress_to_next: number
  last_play_time: number | null
  chest_granted: boolean
  tokens_earned: number
  season_milestone: number | null
  milestone_grades: string[] | null
  tags: string[]
}

export interface MasteryResponse {
  puuid: string
  total_points: number
  total_champions_played: number
  champions_owned_ratio: number
  levels: Record<string, number>
  entries: MasteryEntry[]
}

export interface Health {
  status: string
  riot_key_configured: boolean
  static_data_version: string | null
  rate_limit: {
    app?: { used: number; limit: number; period: number }[]
    methods_tracked?: number
    penalties?: Record<string, number>
  }
  spectator_enabled: boolean
}

export interface ChampionStatic extends ChampionRef {
  key: string
  title: string
  tags: string[]
  splash_url: string | null
  /** Centred crop, for use as a page background. */
  art_url: string | null
  tile_url: string | null
}

/**
 * An API failure the UI can act on.
 *
 * `kind` matters: a 429 on a development key is an expected, temporary state
 * with a known wait, and an expired key is a fixable configuration problem.
 * Neither should surface as "something went wrong".
 */
export interface TierListChampion extends ChampionRef {
  /** Square key art. Only the tier list carries it; see the backend note. */
  tile_url: string | null
}

export interface ChampionMetaRow {
  champion: TierListChampion
  position: string
  games: number
  wins: number
  win_rate: number
  /** Low end of the range the sample supports; what the list is ranked by. */
  confidence_win_rate: number
  /** High end of the same range. */
  confidence_high: number
  pick_rate: number
  ban_rate: number
  // null when the role is too thin for percentile tiers to mean anything.
  // Banded within the champion's own role, also in the all-roles view.
  tier: string | null
  avg_kda: number
  avg_cs_per_min: number
  avg_damage: number
  avg_vision: number
  /** Over `timeline_games` only. */
  avg_gold_diff_14: number | null
  timeline_games: number
}

export interface MetaResponse {
  patch: string
  queue_id: number
  position: string | null
  /** Crawl provenance the rows were sliced by, not a measured lobby rank. */
  rank_bracket: string
  sample_matches: number
  min_games: number
  rows: ChampionMetaRow[]
  /** How the games behind this slice were ranked, by measured lobby median. */
  lobby_ranks: {
    total: number
    measured: number
    /** Highest first; MASTER+ merges the apex tiers. */
    buckets: { tier: string; games: number }[]
    /** Epoch ms of the newest measurement. */
    as_of: number | null
  } | null
}

export interface CorpusResponse {
  slices: { patch: string; queue_id: number; matches: number }[]
  /** Crawl provenances held, always starting with "ALL". Not measured ranks. */
  brackets: string[]
  total_matches: number
  /** Epoch ms: when the newest game held was played. */
  latest_game_at: number | null
  /** Epoch ms: when a game was last stored. */
  latest_ingest_at: number | null
}

// --- home page -----------------------------------------------------------------

/** A Riot ID we already hold, offered while somebody types. */
export interface PlayerSuggestion {
  riot_id: string
  game_name: string
  tag_line: string
  platform: string
  platform_label: string
  profile_icon_url: string | null
  summoner_level: number | null
  /** Solo queue as stored. Null means none held, which is not "unranked". */
  tier: string | null
  division: string | null
  league_points: number | null
}

export interface SuggestResponse {
  query: string
  players: PlayerSuggestion[]
}

/** The highest Riftline score in one role over the window. */
export interface BestGame {
  match_id: string
  /** Lower-case shard id, for the profile link. */
  platform: string
  puuid: string
  game_name: string | null
  tag_line: string | null
  champion: TierListChampion
  position: Position
  score: number
  placement: number | null
  kills: number
  deaths: number
  assists: number
  win: boolean
  badges: Badge[]
  game_creation: number
  game_duration: number
}

export interface BestGamesResponse {
  queue_id: number
  queue_name: string
  days: number
  since: number
  /** What the games were chosen from. */
  scored_players: number
  scored_games: number
  games: BestGame[]
}

// --- champion detail -------------------------------------------------------

export interface ChampionInfo extends ChampionRef {
  key: string | null
  title: string | null
  tags: string[]
  splash_url: string | null
  /** Centred crop, for use as a page background. */
  art_url: string | null
  tile_url: string | null
}

export interface PositionShare {
  position: string
  games: number
  share: number
  win_rate: number
}

/** One thing a champion took: an item set, a rune page, a spell pair. */
export interface FacetEntry {
  ids: number[]
  games: number
  wins: number
  win_rate: number
  /** Share of this champion's games, not of all games. */
  pick_rate: number
  items: ItemRef[]
  spells: SpellRef[]
  runes: RuneRef[]
}

export interface PairEntry {
  champion: ChampionRef
  games: number
  wins: number
  win_rate: number
  confidence_win_rate: number
  /** Only present on synergies: which lane the ally was in. */
  position: string | null
  /** From timelines; null until the matchup's games have been backfilled. */
  avg_laning_score: number | null
  avg_gold_diff_14: number | null
  timeline_games: number
}

export interface ChampionDetail {
  champion: ChampionInfo
  patch: string
  queue_id: number
  position: string
  rank_bracket: string
  sample_matches: number
  min_games: number
  positions: PositionShare[]
  overview: {
    games: number
    wins: number
    win_rate: number
    confidence_win_rate: number
    pick_rate: number
    ban_rate: number
    tier: string | null
    avg_kills: number
    avg_deaths: number
    avg_assists: number
    avg_kda: number
    avg_cs_per_min: number
    avg_gold: number
    avg_damage: number
    avg_vision: number
  }
  builds: {
    /**
     * "final_inventory" means these are the sets players finished with, because
     * item slots carry no purchase order. "purchase_order" means timelines gave
     * us the real thing and `path` is populated.
     */
    basis: string
    complete: FacetEntry[]
    items: FacetEntry[]
    boots: FacetEntry[]
    /** First three legendary completions, in the order they were bought. */
    path: FacetEntry[]
  }
  runes: { keystones: FacetEntry[]; pages: FacetEntry[] }
  /** Ability slots 1-4 are Q/W/E/R; these facets carry no icons. */
  skills: { priority: FacetEntry[]; order: FacetEntry[] }
  laning: {
    /** How many of the champion's games had a timeline, not its total games. */
    games: number
    avg_score: number | null
    avg_gold_diff: number | null
    avg_cs_diff: number | null
  }
  spells: FacetEntry[]
  counters: { lane: PairEntry[]; team: PairEntry[] }
  synergies: PairEntry[]
}

// --- player analytics ------------------------------------------------------

export interface Analytics {
  puuid: string
  /** "stored_matches": this describes games we hold, not a whole season. */
  basis: string
  games_analysed: number
  roles: { position: string; games: number; share: number; win_rate: number }[]
  classes: { tag: string; games: number; share: number }[]
  /** 24 buckets in UTC; the client shifts them into local time. */
  activity_utc: number[]
  champions: ChampionPlayed[]
  totals: {
    win_rate: number
    kda: number
    avg_kills: number
    avg_deaths: number
    avg_assists: number
    cs_per_min: number
    vision_per_game: number
    damage_per_min: number
  }
  /** Most scored games first. */
  score_profile: RoleScoreProfile[]
}

/** One champion over the stored games. Each average is over its own count. */
export interface ChampionPlayed {
  champion: ChampionRef
  games: number
  wins: number
  win_rate: number
  kda: number
  cs_per_min: number
  avg_kills: number
  avg_deaths: number
  avg_assists: number
  damage_per_min: number
  main_position: string | null
  /** Epoch ms. */
  last_played: number | null
  scored_games: number
  avg_score: number | null
  timeline_games: number
  avg_gold_diff_14: number | null
}

/** What a player's scored games in one role add up to. */
export interface RoleScoreProfile {
  position: Position
  scored_games: number
  /** False below `min_scored`: show the count, not a breakdown. */
  enough: boolean
  avg_score: number
  avg_placement: number
  mvp: number
  ace: number
  /** Highest first. */
  components: { id: string; label: string; measures: string; avg_percentile: number }[]
  /** The smallest corpus any of the percentiles was measured against. */
  sample: number | null
  min_scored: number
}

export interface RankHistory {
  queue_type: string
  /** Epoch ms of the first reading, null before there is one. */
  tracking_since: number | null
  points: {
    at: number
    tier: string | null
    division: string | null
    league_points: number
    wins: number
    losses: number
    numeric_rank: number
  }[]
}

export interface SliceQuery {
  patch?: string | null
  queueId?: number
  position?: string | null
  bracket?: string | null
  minGames?: number
}

/** One record behind a suggestion, with the sample it rests on. */
export interface DraftEvidence {
  kind: 'lane' | 'enemy' | 'ally'
  champion: ChampionRef
  games: number
  wins: number
  win_rate: number
  /** What the record claims, and the part its own sample supports. */
  lift: number
  credible_lift: number
  gold_diff_14: number | null
  laning_score: number | null
  timeline_games: number
}

export interface DraftSuggestion {
  champion: ChampionRef
  /** Baseline plus what the board supports plus comfort: the sort key. */
  score: number
  base_win_rate: number
  /** Baseline plus everything the records claim, uncapped: "if they hold". */
  adjusted_win_rate: number
  games: number
  matchup_win_rate: number | null
  matchup_games: number
  mastery_points: number
  comfort: number
  context_lift: number
  comfort_bonus: number
  evidence: DraftEvidence[]
  reasons: string[]
}

export interface DraftBanCandidate {
  champion: ChampionRef
  position: string
  base_win_rate: number
  games: number
  score: number
  reasons: string[]
}

/** The constants behind the score, so the page states them rather than guessing. */
export interface DraftModel {
  comfort_weight: number
  comfort_max_bonus: number
  lane_shrinkage: number
  team_shrinkage: number
  ally_shrinkage: number
  context_lift_cap: number
}

export interface DraftResponse {
  patch: string
  position: string
  enemy_laner: ChampionRef | null
  allies: ChampionRef[]
  enemies: ChampionRef[]
  personalised: boolean
  suggestions: DraftSuggestion[]
  /** False when no ally is locked in: then the bans are just the patch's best. */
  bans_read_the_draft: boolean
  ban_candidates: DraftBanCandidate[]
  model: DraftModel
}

export interface DraftRequest {
  position: string
  allies?: number[]
  enemies?: number[]
  bans?: number[]
  enemy_laner?: number | null
  patch?: string | null
  queue_id?: number
  min_games?: number
  platform?: string | null
  game_name?: string | null
  tag_line?: string | null
  comfort_weight?: number
}

export class ApiError extends Error {
  status: number
  kind:
    | 'not_found'
    | 'rate_limited'
    | 'expired_key'
    | 'gone'
    /** The endpoint is unavailable to our key. Nothing the user can fix. */
    | 'unavailable'
    | 'upstream'
    | 'unknown'
  retryAfter?: number

  constructor(status: number, detail: string, extra: Record<string, unknown> = {}) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = typeof extra.retry_after === 'number' ? extra.retry_after : undefined
    if (status === 404) this.kind = 'not_found'
    else if (status === 429) this.kind = 'rate_limited'
    else if (extra.hint === 'expired_api_key') this.kind = 'expired_key'
    else if (status === 410) this.kind = 'gone'
    else if (extra.hint === 'endpoint_unavailable') this.kind = 'unavailable'
    else if (status === 502 || status === 503) this.kind = 'upstream'
    else this.kind = 'unknown'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    let extra: Record<string, unknown> = {}
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
      extra = body ?? {}
    } catch {
      // Non-JSON error body; the status alone will have to do.
    }
    throw new ApiError(response.status, detail, extra)
  }
  return response.json() as Promise<T>
}

const enc = encodeURIComponent

/** Shared query string for every slice-filtered endpoint. */
function sliceParams(opts: SliceQuery, defaultMinGames: number): string {
  const params = new URLSearchParams()
  if (opts.patch) params.set('patch', opts.patch)
  params.set('queue_id', String(opts.queueId ?? 420))
  if (opts.position) params.set('position', opts.position)
  if (opts.bracket) params.set('bracket', opts.bracket)
  params.set('min_games', String(opts.minGames ?? defaultMinGames))
  return params.toString()
}

export const api = {
  health: () => request<Health>('/api/health'),

  champions: () =>
    request<{ version: string; champions: ChampionStatic[] }>('/api/static/champions'),

  queues: () => request<{ queues: { id: number; name: string }[] }>('/api/static/queues'),

  /** The full scoreboard for one stored match. Fetched when a row is expanded. */
  matchDetail: (matchId: string) => request<MatchDetail>(`/api/matches/${enc(matchId)}`),

  profile: (platform: string, name: string, tag: string, refresh = false) =>
    request<Profile>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}${refresh ? '?refresh=true' : ''}`,
    ),

  matches: (
    platform: string,
    name: string,
    tag: string,
    opts: { start?: number; count?: number; queue?: number | null } = {},
  ) => {
    const params = new URLSearchParams()
    if (opts.start) params.set('start', String(opts.start))
    if (opts.count) params.set('count', String(opts.count))
    if (opts.queue) params.set('queue', String(opts.queue))
    const qs = params.toString()
    return request<MatchHistory>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/matches${qs ? `?${qs}` : ''}`,
    )
  },

  mastery: (platform: string, name: string, tag: string) =>
    request<MasteryResponse>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/mastery`,
    ),

  corpus: () => request<CorpusResponse>('/api/meta/corpus'),

  /** Players we already hold whose Riot ID starts with `q`. Never calls Riot. */
  suggest: (q: string, platform: string, signal?: AbortSignal) =>
    request<SuggestResponse>(
      `/api/players/suggest?${new URLSearchParams({ q, platform }).toString()}`,
      { signal },
    ),

  bestGames: () => request<BestGamesResponse>('/api/highlights/best-games'),

  meta: (opts: SliceQuery = {}) =>
    request<MetaResponse>(`/api/meta/champions?${sliceParams(opts, 20)}`),

  champion: (championId: number, opts: SliceQuery = {}) =>
    request<ChampionDetail>(`/api/champions/${championId}?${sliceParams(opts, 5)}`),

  analytics: (
    platform: string,
    name: string,
    tag: string,
    opts: { queue?: number | null; limit?: number } = {},
  ) => {
    const params = new URLSearchParams()
    if (opts.queue) params.set('queue', String(opts.queue))
    if (opts.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return request<Analytics>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/analytics${qs ? `?${qs}` : ''}`,
    )
  },

  rankHistory: (platform: string, name: string, tag: string, queue: string) =>
    request<RankHistory>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/rank-history?queue=${enc(queue)}`,
    ),

  live: (platform: string, name: string, tag: string) =>
    request<LiveGameResponse>(
      `/api/summoner/${enc(platform)}/${enc(name)}/${enc(tag)}/live`,
    ),

  leaderboardSlices: () =>
    request<LeaderboardSlices>('/api/leaderboard/slices'),

  leaderboard: (
    platform: string,
    opts: {
      queueId?: number
      tier?: string
      division?: string
      page?: number
      perPage?: number
    } = {},
  ) => {
    const params = new URLSearchParams()
    params.set('queue_id', String(opts.queueId ?? 420))
    params.set('tier', opts.tier ?? 'CHALLENGER')
    params.set('division', opts.division ?? 'I')
    params.set('page', String(opts.page ?? 1))
    params.set('per_page', String(opts.perPage ?? 50))
    return request<LeaderboardResponse>(
      `/api/leaderboard/${enc(platform)}?${params.toString()}`,
    )
  },

  draft: (body: DraftRequest) =>
    request<DraftResponse>('/api/draft/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}

export const POSITIONS = [
  { id: 'TOP', label: 'Top' },
  { id: 'JUNGLE', label: 'Jungle' },
  { id: 'MIDDLE', label: 'Mid' },
  { id: 'BOTTOM', label: 'Bot' },
  { id: 'UTILITY', label: 'Support' },
] as const

export const PLATFORMS = [
  { id: 'euw1', label: 'EUW' },
  { id: 'na1', label: 'NA' },
  { id: 'kr', label: 'KR' },
  { id: 'eun1', label: 'EUNE' },
  { id: 'br1', label: 'BR' },
  { id: 'jp1', label: 'JP' },
  { id: 'la1', label: 'LAN' },
  { id: 'la2', label: 'LAS' },
  { id: 'oc1', label: 'OCE' },
  { id: 'tr1', label: 'TR' },
  { id: 'ru', label: 'RU' },
  { id: 'me1', label: 'ME' },
  { id: 'sg2', label: 'SG' },
  { id: 'tw2', label: 'TW' },
  { id: 'vn2', label: 'VN' },
] as const
