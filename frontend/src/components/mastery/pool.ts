import type { ChampionPlayed, ChampionStatic, MasteryEntry, MasteryResponse } from '../../lib/api'

/**
 * A player's champion pool, banded by how much of their mastery it holds.
 *
 * Measured on production on 2026-09-21 across four accounts: three to eleven
 * champions hold the first half of a career's mastery points, twenty four to
 * thirty three hold the next third, and a hundred or more sit in the last
 * fifteen percent. The old page drew all of them as one wall of 52px squares,
 * so none of that was visible.
 *
 * Pure, and called once from a memo, so typing in the name box re-filters
 * without re-banding.
 */
export type BandId = 'core' | 'middle' | 'tail' | 'unplayed'

export interface PoolChampion {
  id: number
  name: string
  iconUrl: string | null
  tags: string[]
  level: number
  points: number
  /** Share of this player's lifetime mastery points, 0 to 1. */
  share: number
  lastPlayed: number | null
  band: BandId
  /** False when Riot names a champion our static data does not list yet. */
  known: boolean
  entry: MasteryEntry | null
  /** What our own stored games say, when we hold any. */
  record: ChampionPlayed | null
}

export interface Band {
  id: BandId
  champions: PoolChampion[]
  /** Share of lifetime points this band holds, 0 to 1. */
  share: number
}

export interface Pool {
  champions: PoolChampion[]
  bands: Record<BandId, Band>
  totalPoints: number
  /** Every champion either Riot or Data Dragon knows about. */
  roster: number
  played: number
  /** Played in the last thirty days, by Riot's own last played time. */
  recent: number
  top: PoolChampion | null
  deepest: PoolChampion | null
  /** Champions we hold stored games for, and how many of those are in the core. */
  held: number
  heldInCore: number
  unknown: PoolChampion[]
}

/** Half a career, then the next third. The rest is the tail. */
const CORE_SHARE = 0.5
const MIDDLE_SHARE = 0.85
const RECENT_DAYS = 30

const EMPTY_BANDS: Record<BandId, Band> = {
  core: { id: 'core', champions: [], share: 0 },
  middle: { id: 'middle', champions: [], share: 0 },
  tail: { id: 'tail', champions: [], share: 0 },
  unplayed: { id: 'unplayed', champions: [], share: 0 },
}

export function buildPool({
  mastery,
  champions,
  records,
  now,
}: {
  mastery: MasteryResponse | undefined
  champions: ChampionStatic[]
  records: ChampionPlayed[]
  /** Injected so two calls in one render agree about "the last thirty days". */
  now: number
}): Pool {
  const entries = mastery?.entries ?? []
  const byId = new Map(champions.map((c) => [c.id, c]))
  const recordById = new Map(records.map((r) => [r.champion.id, r]))

  // Built from the entries first and the roster second. The other way round,
  // a champion Riot lists and Data Dragon does not is dropped: on 2026-09-21
  // that was id 60016 with 665 points, and the page said 165 played where the
  // API said 166.
  const played: PoolChampion[] = entries.map((entry) => {
    const stat = byId.get(entry.champion.id)
    return {
      id: entry.champion.id,
      name: stat?.name ?? entry.champion.name,
      iconUrl: stat?.icon_url ?? entry.champion.icon_url,
      tags: stat?.tags ?? entry.tags,
      level: entry.level,
      points: entry.points,
      share: 0,
      lastPlayed: entry.last_play_time,
      band: 'tail',
      known: entry.champion_known,
      entry,
      record: recordById.get(entry.champion.id) ?? null,
    }
  })
  const playedIds = new Set(played.map((c) => c.id))
  const unplayed: PoolChampion[] = champions
    .filter((c) => !playedIds.has(c.id))
    .map((c) => ({
      id: c.id,
      name: c.name,
      iconUrl: c.icon_url,
      tags: c.tags,
      level: 0,
      points: 0,
      share: 0,
      lastPlayed: null,
      band: 'unplayed' as const,
      known: true,
      entry: null,
      record: null,
    }))
    .sort((a, b) => a.name.localeCompare(b.name))

  const totalPoints = played.reduce((sum, c) => sum + c.points, 0)
  if (played.length === 0 || totalPoints === 0) {
    return {
      champions: [...played, ...unplayed],
      bands: { ...EMPTY_BANDS, unplayed: { id: 'unplayed', champions: unplayed, share: 0 } },
      totalPoints,
      roster: played.length + unplayed.length,
      played: 0,
      recent: 0,
      top: null,
      deepest: null,
      held: 0,
      heldInCore: 0,
      unknown: played.filter((c) => !c.known),
    }
  }

  // The server already sorts by points, but a tiebreak of our own keeps the
  // grid from reshuffling when a refetch returns equal values in a different
  // order.
  played.sort((a, b) => b.points - a.points || a.name.localeCompare(b.name))

  const core: PoolChampion[] = []
  const middle: PoolChampion[] = []
  const tail: PoolChampion[] = []
  let before = 0
  for (const champion of played) {
    champion.share = champion.points / totalPoints
    // Tested on the points *ahead* of this champion, not including it. Testing
    // the running total instead would push a champion holding more than half a
    // career out of the core band and leave that band empty.
    const bucket =
      before < CORE_SHARE * totalPoints
        ? core
        : before < MIDDLE_SHARE * totalPoints
          ? middle
          : tail
    champion.band = bucket === core ? 'core' : bucket === middle ? 'middle' : 'tail'
    bucket.push(champion)
    before += champion.points
  }

  const share = (band: PoolChampion[]) =>
    band.reduce((sum, c) => sum + c.points, 0) / totalPoints

  const recentSince = now - RECENT_DAYS * 86_400_000
  return {
    champions: [...played, ...unplayed],
    bands: {
      core: { id: 'core', champions: core, share: share(core) },
      middle: { id: 'middle', champions: middle, share: share(middle) },
      tail: { id: 'tail', champions: tail, share: share(tail) },
      unplayed: { id: 'unplayed', champions: unplayed, share: 0 },
    },
    totalPoints,
    roster: played.length + unplayed.length,
    played: played.length,
    recent: played.filter((c) => c.lastPlayed !== null && c.lastPlayed >= recentSince).length,
    top: played[0] ?? null,
    deepest: played.reduce((best, c) => (best && best.level >= c.level ? best : c), played[0]),
    held: played.filter((c) => c.record).length,
    heldInCore: core.filter((c) => c.record).length,
    unknown: played.filter((c) => !c.known),
  }
}
