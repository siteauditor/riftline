import { describe, expect, it } from 'vitest'

import { compact, ordinal, parseRiotId, pct, shortDate, tierLabel, timeAgo } from './format'

const NOW = Date.UTC(2026, 8, 23, 12, 0, 0)
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

describe('timeAgo', () => {
  it('reads the clock it is given, so a prerendered page can say what was true when made', () => {
    expect(timeAgo(NOW - 30_000, NOW)).toBe('just now')
    expect(timeAgo(NOW - 5 * MINUTE, NOW)).toBe('5m ago')
    expect(timeAgo(NOW - 3 * HOUR, NOW)).toBe('3h ago')
    expect(timeAgo(NOW - 2 * DAY, NOW)).toBe('2d ago')
    expect(timeAgo(NOW - 45 * DAY, NOW)).toBe('1mo ago')
    expect(timeAgo(NOW - 400 * DAY, NOW)).toBe('1y ago')
  })

  it('never counts into the future', () => {
    expect(timeAgo(NOW + MINUTE, NOW)).toBe('just now')
  })
})

describe('shortDate', () => {
  it('is one locale and one zone, so the browser spells the day the server did', () => {
    expect(shortDate(Date.UTC(2026, 8, 20, 23, 30))).toBe('Sep 20')
    expect(shortDate(Date.UTC(2026, 0, 1, 0, 0))).toBe('Jan 1')
  })
})

describe('compact', () => {
  it('keeps one decimal below ten thousand and none above', () => {
    expect(compact(999)).toBe('999')
    expect(compact(1500)).toBe('1.5k')
    expect(compact(25_000)).toBe('25k')
    expect(compact(1_200_000)).toBe('1.2M')
  })
})

describe('ordinal', () => {
  it('handles the teens', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal)).toEqual([
      '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '101st', '111th',
    ])
  })
})

describe('pct', () => {
  it('rounds to the digits asked for', () => {
    expect(pct(0.5567)).toBe('56%')
    expect(pct(0.5567, 1)).toBe('55.7%')
    expect(pct(1)).toBe('100%')
  })
})

describe('tierLabel', () => {
  it('drops the division above Diamond and names the unranked', () => {
    expect(tierLabel(null)).toBe('Unranked')
    expect(tierLabel('GOLD', 'II')).toBe('Gold II')
    expect(tierLabel('MASTER', 'I')).toBe('Master')
    expect(tierLabel('CHALLENGER')).toBe('Challenger')
  })
})

describe('parseRiotId', () => {
  it('splits on the last hash and trims', () => {
    expect(parseRiotId('Caps#EUW')).toEqual({ name: 'Caps', tag: 'EUW' })
    expect(parseRiotId('  Hide on bush # KR1 ')).toEqual({ name: 'Hide on bush', tag: 'KR1' })
    expect(parseRiotId('a#b#c')).toEqual({ name: 'a#b', tag: 'c' })
  })

  it('refuses half an id', () => {
    expect(parseRiotId('Caps')).toBeNull()
    expect(parseRiotId('#EUW')).toBeNull()
    expect(parseRiotId('Caps#')).toBeNull()
    expect(parseRiotId('   ')).toBeNull()
  })
})
