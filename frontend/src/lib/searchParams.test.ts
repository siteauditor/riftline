import { describe, expect, it } from 'vitest'

import { lowerFloor } from './minGames'
import { MAX_MIN_GAMES, positionParam, sliceCorrections, sliceFromParams } from './searchParams'

const params = (query: string) => new URLSearchParams(query)

describe('sliceFromParams', () => {
  it('takes a role in any case and drops one the API would refuse', () => {
    expect(positionParam('top')).toBe('TOP')
    expect(positionParam('Utility')).toBe('UTILITY')
    expect(positionParam('banana')).toBeNull()
    expect(positionParam(null)).toBeNull()
    expect(sliceFromParams(params('position=mid'), 20).position).toBeNull()
  })

  it('keeps the queue to the two ranked ones and the floor to what the API accepts', () => {
    expect(sliceFromParams(params('queue=440'), 20).queueId).toBe(440)
    expect(sliceFromParams(params('queue=999'), 20).queueId).toBe(420)
    expect(sliceFromParams(params('queue_id=440'), 20).queueId).toBe(440)
    expect(sliceFromParams(params('min_games=abc'), 20).minGames).toBe(20)
    expect(sliceFromParams(params('min_games=9000'), 20).minGames).toBe(MAX_MIN_GAMES)
    expect(sliceFromParams(params('min_games=2.5'), 5).minGames).toBe(2)
  })
})

describe('sliceCorrections', () => {
  it('leaves a clean address alone', () => {
    expect(sliceCorrections(params('position=TOP&min_games=10'), 20)).toBeNull()
    expect(sliceCorrections(params(''), 20)).toBeNull()
  })

  it('puts right what the page could not use, and keeps everything else', () => {
    expect(sliceCorrections(params('position=top&tab=runes'), 5)?.toString()).toBe('position=TOP&tab=runes')
    expect(sliceCorrections(params('position=banana&q=ahri'), 5)?.toString()).toBe('q=ahri')
    expect(sliceCorrections(params('queue_id=440'), 20)?.toString()).toBe('queue=440')
    expect(sliceCorrections(params('queue=999&min_games=20'), 20)?.toString()).toBe('')
  })

  it('leaves the patch for the API to answer', () => {
    expect(sliceCorrections(params('patch=16.9'), 20)).toBeNull()
  })
})

describe('lowerFloor', () => {
  it('offers the highest preset that still shows something, else the most games held', () => {
    expect(lowerFloor(35, 50)).toBe(30)
    expect(lowerFloor(4, 20)).toBe(4)
    expect(lowerFloor(0, 20)).toBeNull()
    expect(lowerFloor(100, 20)).toBe(10)
  })
})
