import { describe, expect, it } from 'vitest'

import {
  DEFAULT_SCOPE,
  gamesCovered,
  legacyScope,
  SCOPES,
  scopeFromParam,
  scopeNoun,
  scopeParam,
} from './profileScope'

describe('the scope in the URL', () => {
  it('opens on ranked, and the bare address is ranked', () => {
    expect(DEFAULT_SCOPE).toBe('ranked')
    expect(scopeFromParam(null)).toBe('ranked')
    expect(scopeParam('ranked')).toBeNull()
    expect(scopeParam('aram')).toBe('aram')
  })

  it('reads a word, an older link\'s queue id, and falls back on anything else', () => {
    expect(scopeFromParam('all')).toBe('all')
    expect(scopeFromParam('420')).toBe('solo')
    expect(scopeFromParam('430')).toBe('normal')
    expect(scopeFromParam('2400')).toBe('aram')
    expect(scopeFromParam('1700')).toBe('ranked')
    expect(scopeFromParam('toString')).toBe('ranked')
    expect(legacyScope('440')).toBe('flex')
    expect(legacyScope('flex')).toBeNull()
    expect(legacyScope('constructor')).toBeNull()
  })

  it('offers every word the API knows, ranked first', () => {
    expect(SCOPES.map((s) => s.id)).toEqual(['ranked', 'solo', 'flex', 'normal', 'swiftplay', 'aram', 'all'])
  })
})

describe('gamesCovered', () => {
  it('names the games a figure covers', () => {
    expect(gamesCovered({ games: 182, total: 182, scope: 'ranked' })).toBe('182 ranked games')
    expect(gamesCovered({ games: 1, total: 1, scope: 'aram' })).toBe('1 ARAM game')
    expect(gamesCovered({ games: 19, total: 19, scope: 'all' })).toBe('19 games')
    expect(gamesCovered({ games: 1000, total: 1306, scope: 'ranked' })).toBe(
      'the newest 1,000 of 1,306 ranked games',
    )
    expect(gamesCovered({ games: 12, scope: null })).toBe('12 games')
    expect(scopeNoun('solo')).toBe('solo queue')
  })
})
