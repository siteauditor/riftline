import { describe, expect, it } from 'vitest'

import { busiestWindow, hourLabel } from './activity'

const day = (entries: Record<number, number>) => Array.from({ length: 24 }, (_, h) => entries[h] ?? 0)

describe('busiestWindow', () => {
  it('names the three hours with the most games', () => {
    const w = busiestWindow(day({ 9: 1, 20: 5, 21: 6, 22: 4, 23: 1 }))
    expect(w).toEqual({ start: 20, end: 23, games: 15, share: 15 / 17 })
    expect(`${hourLabel(w!.start)} to ${hourLabel(w!.end)}`).toBe('20:00 to 23:00')
  })

  it('wraps past midnight', () => {
    const w = busiestWindow(day({ 23: 4, 0: 4, 1: 4, 12: 5 }))
    expect([w?.start, w?.end, w?.games]).toEqual([23, 2, 12])
  })

  it('takes the earliest run on a tie, and says nothing of an empty day', () => {
    expect(busiestWindow(day({ 2: 3, 14: 3 }))?.start).toBe(0)
    expect(busiestWindow(day({}))).toBeNull()
  })
})
