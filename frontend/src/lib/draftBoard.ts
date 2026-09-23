import { POSITIONS, type DraftRequest } from './api'
import { withParams } from './searchParams'

/**
 * The draft board, as it lives in the URL.
 *
 * The board is in the address so a draft can be shared or reloaded, and those
 * parameter names are a public contract: links already shared keep meaning what
 * they meant. Everything here is pure, so the page's actions are one board-to-
 * board transform and one URL write each. Two writes in one action lost the
 * first: removing the enemy marked as the lane opponent wrote the new enemy
 * list, then the lane, from the same stale URL, and the enemy came back
 * (measured on production 2026-09-24).
 */

export const COMFORT_LEVELS = [
  { value: 0, label: 'Off' },
  { value: 0.15, label: 'Light' },
  { value: 0.4, label: 'Strong' },
] as const

export type Role = DraftRequest['position']

export const DEFAULT_ROLE: Role = 'MIDDLE'
export const DEFAULT_MIN_GAMES = 20
export const MAX_MIN_GAMES = 500
export const DEFAULT_COMFORT = 0.15

/**
 * The sample floors offered. A select rather than a number box: the box could
 * not be emptied, so deleting "20" and typing "30" gave 130, and "2.5" went to
 * the API and came back as "Something went wrong".
 */
export const MIN_GAMES_PRESETS: readonly number[] = [5, 10, 20, 30, 50, 100]

/** The presets, plus the link's own floor when it is another number. */
export function minGamesOptions(current: number): { value: string; label: string }[] {
  const values = MIN_GAMES_PRESETS.includes(current)
    ? MIN_GAMES_PRESETS
    : [...MIN_GAMES_PRESETS, current].sort((a, b) => a - b)
  return values.map((v) => ({ value: String(v), label: `${v} games` }))
}

export interface Board {
  role: Role
  allies: number[]
  enemies: number[]
  bans: number[]
  /** The enemy in your lane, when you have said which one it is. */
  lane: number | null
  /** You have said the lane is unknown: no guess from the enemy picks (`lane=none`). */
  laneUnknown: boolean
  /** Champions checked by hand, ranked whatever their place (`check=`, up to three). */
  check: number[]
  min: number
  comfort: number
}

export const MAX_CHECKS = 3

export type Side = 'allies' | 'enemies' | 'bans'

/** Four others on your side, five on theirs, ten bans: the API refuses more. */
export const CAPS: Record<Side, number> = { allies: 4, enemies: 5, bans: 10 }

const WHERE: Record<Side, string> = {
  allies: 'on your team',
  enemies: 'on the enemy team',
  bans: 'banned',
}

/** Champion ids from a comma list: whole, positive, each once, in order. */
function ids(value: string | null): number[] {
  const out: number[] = []
  for (const part of (value ?? '').split(',')) {
    const id = Number(part)
    if (Number.isInteger(id) && id > 0 && !out.includes(id)) out.push(id)
  }
  return out
}

export function parseBoard(search: URLSearchParams): Board {
  const role = (search.get('role') ?? '').toUpperCase()
  // A champion is in one place: the first of allies, enemies, bans keeps it,
  // and each side keeps as many as a draft has room for. A hand-edited or old
  // link is read as the draft it could have been, not refused.
  const taken = new Set<number>()
  const side = (key: Side) => {
    const kept = ids(search.get(key)).filter((id) => !taken.has(id)).slice(0, CAPS[key])
    kept.forEach((id) => taken.add(id))
    return kept
  }
  const allies = side('allies')
  const enemies = side('enemies')
  const bans = side('bans')
  const check = ids(search.get('check'))
    .filter((id) => !taken.has(id))
    .slice(0, MAX_CHECKS)
  const lane = Number(search.get('lane'))
  const min = Number(search.get('min'))
  // `has` first: Number(null) is 0, which is the Off level, so a link without a
  // comfort parameter used to open with mastery off instead of on Light.
  const comfort = search.has('comfort') ? Number(search.get('comfort')) : DEFAULT_COMFORT
  return {
    role: POSITIONS.find((p) => p.id === role)?.id ?? DEFAULT_ROLE,
    allies,
    enemies,
    bans,
    lane: enemies.includes(lane) ? lane : null,
    laneUnknown: search.get('lane') === 'none',
    check,
    min: Number.isInteger(min) && min >= 1 ? Math.min(min, MAX_MIN_GAMES) : DEFAULT_MIN_GAMES,
    comfort: COMFORT_LEVELS.some((c) => c.value === comfort) ? comfort : DEFAULT_COMFORT,
  }
}

/** `base` with the board written over it; other parameters are kept. */
export function boardParams(board: Board, base: URLSearchParams): URLSearchParams {
  return withParams(
    base,
    {
      role: board.role,
      allies: board.allies.map(String),
      enemies: board.enemies.map(String),
      bans: board.bans.map(String),
      lane: board.lane ?? (board.laneUnknown ? 'none' : null),
      check: board.check.map(String),
      min: board.min,
      comfort: board.comfort,
    },
    {
      role: DEFAULT_ROLE,
      min: String(DEFAULT_MIN_GAMES),
      comfort: String(DEFAULT_COMFORT),
    },
  )
}

// --- the actions, each one transform -----------------------------------------

export const setRole =
  (role: Role) =>
  (board: Board): Board => ({ ...board, role })

/** Where a champion already is on the board, and so why it cannot be added. */
export function unavailable(board: Board): Map<number, string> {
  const out = new Map<number, string>()
  for (const side of ['allies', 'enemies', 'bans'] as const) {
    for (const id of board[side]) out.set(id, WHERE[side])
  }
  return out
}

export const isFull = (board: Board, side: Side) => board[side].length >= CAPS[side]

export const addTo =
  (side: Side, id: number) =>
  (board: Board): Board =>
    unavailable(board).has(id) || isFull(board, side)
      ? board
      : {
          ...board,
          [side]: [...board[side], id],
          // A champion on the board is not one to check any more.
          check: board.check.filter((c) => c !== id),
        }

export const removeFrom =
  (side: Side, id: number) =>
  (board: Board): Board => ({
    ...board,
    [side]: board[side].filter((c) => c !== id),
    // The lane opponent is an enemy; taking them off the board takes the mark.
    lane: side === 'enemies' && board.lane === id ? null : board.lane,
  })

export const toggleLane =
  (id: number) =>
  (board: Board): Board => ({ ...board, lane: board.lane === id ? null : id, laneUnknown: false })

/** "No lane opponent yet": stop guessing one from the enemy picks, or start again. */
export const setLaneUnknown =
  (unknown: boolean) =>
  (board: Board): Board => ({ ...board, lane: unknown ? null : board.lane, laneUnknown: unknown })

export const addCheck =
  (id: number) =>
  (board: Board): Board =>
    board.check.includes(id) || board.check.length >= MAX_CHECKS || unavailable(board).has(id)
      ? board
      : { ...board, check: [...board.check, id] }

export const removeCheck =
  (id: number) =>
  (board: Board): Board => ({ ...board, check: board.check.filter((c) => c !== id) })

export const setMinGames =
  (min: number) =>
  (board: Board): Board => ({
    ...board,
    min: Number.isInteger(min) && min >= 1 ? Math.min(min, MAX_MIN_GAMES) : board.min,
  })

export const setComfort =
  (comfort: number) =>
  (board: Board): Board => ({
    ...board,
    comfort: COMFORT_LEVELS.some((c) => c.value === comfort) ? comfort : board.comfort,
  })

export const clearBoard = (board: Board): Board => ({
  ...board,
  allies: [],
  enemies: [],
  bans: [],
  lane: null,
  laneUnknown: false,
})

export const boardIsSet = (board: Board) =>
  board.allies.length + board.enemies.length + board.bans.length > 0

// --- the request ---------------------------------------------------------------

export interface RiotIdChoice {
  platform: string
  name: string
  tag: string
}

/**
 * What the API is asked. Ids sorted, because the order a board was filled in
 * does not change the answer and should not change the cache key. The Riot ID
 * goes only with a mastery weight above Off: with the weight off it changes
 * nothing, and every lookup spends the Riot key.
 */
export function draftRequest(board: Board, riot: RiotIdChoice | null): DraftRequest {
  const sorted = (list: number[]) => [...list].sort((a, b) => a - b)
  const personal = riot !== null && board.comfort > 0
  return {
    position: board.role,
    allies: sorted(board.allies),
    enemies: sorted(board.enemies),
    bans: sorted(board.bans),
    enemy_laner: board.lane,
    infer_lane: !board.laneUnknown,
    include: sorted(board.check),
    min_games: board.min,
    comfort_weight: board.comfort,
    platform: personal ? riot.platform : null,
    game_name: personal ? riot.name : null,
    tag_line: personal ? riot.tag : null,
  }
}

/**
 * The request as a string: what the page debounces and keys its query by, so
 * two boards that ask the same question share an answer and a settled value
 * can never be a new object on every render.
 */
export const requestKey = (board: Board, riot: RiotIdChoice | null): string =>
  JSON.stringify(draftRequest(board, riot))
