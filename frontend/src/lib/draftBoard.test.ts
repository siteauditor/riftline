import { describe, expect, it } from 'vitest'

import {
  addTo,
  boardParams,
  clearBoard,
  DEFAULT_COMFORT,
  isFull,
  minGamesOptions,
  parseBoard,
  removeFrom,
  requestKey,
  setMinGames,
  toggleLane,
  unavailable,
  addCheck,
  removeCheck,
  setLaneUnknown,
} from './draftBoard'

const board = (query: string) => parseBoard(new URLSearchParams(query))

describe('parseBoard', () => {
  it('reads a shared link as it was written', () => {
    expect(board('role=TOP&allies=103,238&enemies=157,64&lane=157&bans=86&min=30&comfort=0.4')).toEqual({
      role: 'TOP',
      allies: [103, 238],
      enemies: [157, 64],
      bans: [86],
      lane: 157,
      laneUnknown: false,
      check: [],
      min: 30,
      comfort: 0.4,
    })
  })

  it('opens on Light mastery when the link says nothing about it, not Off', () => {
    expect(board('').comfort).toBe(DEFAULT_COMFORT)
    expect(board('comfort=0').comfort).toBe(0)
  })

  it('falls back instead of trusting a hand-edited link', () => {
    const b = board('role=foo&allies=1,1,x,-3,2.5&min=2.5&comfort=7&lane=999&enemies=64')
    expect(b.role).toBe('MIDDLE')
    expect(b.allies).toEqual([1])
    expect(b.min).toBe(20)
    expect(b.comfort).toBe(DEFAULT_COMFORT)
    // A lane opponent is one of the enemies or nobody.
    expect(b.lane).toBeNull()
  })

  it('reads the role in any case', () => {
    expect(board('role=top').role).toBe('TOP')
  })

  it('keeps a champion in one place and each side to its size', () => {
    const b = board('allies=1,2,3,4,5&enemies=1,6&bans=6,7')
    expect(b.allies).toEqual([1, 2, 3, 4])
    // 1 is an ally already; 6 is an enemy, so not a ban as well.
    expect(b.enemies).toEqual([6])
    expect(b.bans).toEqual([7])
  })
})

describe('the actions', () => {
  it('takes the lane mark off with the enemy it marked, in one write', () => {
    const before = board('enemies=157,64&lane=157')
    const after = removeFrom('enemies', 157)(before)
    expect(after.enemies).toEqual([64])
    expect(after.lane).toBeNull()
    expect(boardParams(after, new URLSearchParams('enemies=157,64&lane=157')).toString()).toBe('enemies=64')
  })

  it('adds a champion once and toggles the lane mark', () => {
    const b = addTo('allies', 103)(addTo('allies', 103)(board('')))
    expect(b.allies).toEqual([103])
    const marked = toggleLane(64)(board('enemies=64'))
    expect(marked.lane).toBe(64)
    expect(toggleLane(64)(marked).lane).toBeNull()
  })

  it('keeps parameters that are not the board, and the default view short', () => {
    const params = boardParams(clearBoard(board('allies=1&enemies=2&lane=2')), new URLSearchParams('utm=x&allies=1'))
    expect(params.toString()).toBe('utm=x')
  })

  it('does not add a champion who is elsewhere on the board, or to a full side', () => {
    const b = board('allies=1,2,3,4&enemies=5')
    expect(addTo('enemies', 1)(b)).toBe(b)
    expect(addTo('allies', 9)(b)).toBe(b)
    expect(unavailable(b).get(5)).toBe('on the enemy team')
    expect(isFull(b, 'allies')).toBe(true)
  })

  it('refuses a sample floor that is not a whole number of games', () => {
    expect(setMinGames(2.5)(board('min=30')).min).toBe(30)
    expect(setMinGames(10)(board('')).min).toBe(10)
  })
})

describe('the request', () => {
  it('asks the same question whatever order the board was filled in', () => {
    expect(requestKey(board('allies=2,1'), null)).toBe(requestKey(board('allies=1,2'), null))
  })

  it('sends a Riot ID only while mastery is weighed', () => {
    const riot = { platform: 'kr', name: 'Faker', tag: 'KR1' }
    expect(JSON.parse(requestKey(board('comfort=0.15'), riot)).game_name).toBe('Faker')
    expect(JSON.parse(requestKey(board('comfort=0'), riot)).game_name).toBeNull()
  })
})

describe('the lane and the checks', () => {
  it('reads "no lane opponent yet" and a mark clears it', () => {
    const unknown = board('enemies=64&lane=none')
    expect(unknown.laneUnknown).toBe(true)
    expect(unknown.lane).toBeNull()
    expect(JSON.parse(requestKey(unknown, null)).infer_lane).toBe(false)
    const marked = toggleLane(64)(unknown)
    expect(marked.laneUnknown).toBe(false)
    expect(boardParams(marked, new URLSearchParams('enemies=64&lane=none')).get('lane')).toBe('64')
    expect(boardParams(setLaneUnknown(true)(board('enemies=64')), new URLSearchParams('enemies=64')).get('lane')).toBe('none')
  })

  it('checks up to three champions, none of them already on the board', () => {
    const b = board('check=1,2,3,4&allies=2')
    expect(b.check).toEqual([1, 3, 4])
    expect(addCheck(9)(b)).toBe(b)
    expect(addCheck(5)(removeCheck(1)(b)).check).toEqual([3, 4, 5])
    // Adding a checked champion to the board takes it off the checks.
    expect(addTo('allies', 3)(board('check=3')).check).toEqual([])
  })
})

describe('minGamesOptions', () => {
  it('offers the presets, and a link’s own floor alongside them', () => {
    expect(minGamesOptions(20).map((o) => o.value)).toEqual(['5', '10', '20', '30', '50', '100'])
    expect(minGamesOptions(15).map((o) => o.value)).toEqual(['5', '10', '15', '20', '30', '50', '100'])
  })
})
