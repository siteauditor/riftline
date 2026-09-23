import { describe, expect, it } from 'vitest'

import { lowerFloor } from './minGames'
import {
  championPageFix,
  championPath,
  MAX_MIN_GAMES,
  positionFromRole,
  positionParam,
  roleWord,
  sliceCorrections,
  sliceFromParams,
} from './searchParams'

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

describe('championPath', () => {
  const ahri = { id: 103, slug: 'ahri' }

  it('puts the role in the path as its word, and the slice in the query', () => {
    expect(championPath(ahri)).toBe('/champions/ahri')
    expect(championPath(ahri, 'UTILITY')).toBe('/champions/ahri/support')
    expect(championPath(ahri, 'middle')).toBe('/champions/ahri/mid')
    expect(championPath(ahri, 'BOTTOM', { patch: '16.18', queueId: 440, bracket: 'ALL' })).toBe(
      '/champions/ahri/bot?patch=16.18&queue=440',
    )
    expect(championPath(ahri, null, { queueId: 420 })).toBe('/champions/ahri')
  })

  it('links by id when there is no slug, and never names a role the site does not have', () => {
    expect(championPath({ id: 9999, slug: null }, 'TOP')).toBe('/champions/9999/top')
    expect(championPath('ahri', 'ARAM')).toBe('/champions/ahri')
  })

  it('reads the words back, and the API names a hand-typed address uses', () => {
    for (const position of ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']) {
      expect(positionFromRole(roleWord(position))).toBe(position)
    }
    expect(positionFromRole('Support')).toBe('UTILITY')
    expect(positionFromRole('middle')).toBe('MIDDLE')
    expect(positionFromRole('adc')).toBeNull()
    expect(positionFromRole(undefined)).toBeNull()
  })
})

describe('championPageFix', () => {
  const fix = (path: string, query: string, ref: string, role?: string) =>
    championPageFix(path, params(query), ref, role, 5)

  it('leaves a page at its own address alone', () => {
    expect(fix('/champions/ahri', '', 'ahri')).toBeNull()
    expect(fix('/champions/ahri/support', 'tab=runes&patch=16.18', 'ahri', 'support')).toBeNull()
  })

  it('moves an older link to the slug and the role into the path, in one step', () => {
    expect(fix('/champions/ahri', 'position=JUNGLE&tab=runes', 'ahri')).toBe('/champions/ahri/jungle?tab=runes')
    expect(fix('/champions/103', 'position=utility', 'ahri')).toBe('/champions/ahri/support')
    expect(fix('/champions/ahri/middle', 'queue_id=440', 'ahri', 'middle')).toBe('/champions/ahri/mid?queue=440')
  })

  it('lets the path win over a role in the query', () => {
    expect(fix('/champions/ahri/top', 'position=JUNGLE', 'ahri', 'top')).toBe('/champions/ahri/top')
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
