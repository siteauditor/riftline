import { describe, expect, it } from 'vitest'

import { band, STRONG_FROM, strengthsClaim, WEAK_TO } from './strengths'

const parts = (values: Record<string, number>) =>
  Object.entries(values).map(([label, value]) => ({ label, avg_percentile: value / 100 }))

describe('band', () => {
  it('is strong from 65 and weak to 35, both inclusive', () => {
    expect([STRONG_FROM, WEAK_TO]).toEqual([65, 35])
    expect(band(65)).toBe('strong')
    expect(band(64)).toBe('middle')
    expect(band(36)).toBe('middle')
    expect(band(35)).toBe('weak')
  })
})

describe('strengthsClaim', () => {
  it("claims nothing for a bottom laner whose parts all sit between 42 and 51", () => {
    // Abner#EUW0's 46 scored bot games on the local corpus, 2026-09-24. The
    // old sentence called vision, at 42, their weakness.
    const abner = parts({
      Survival: 51, Objectives: 50, 'Damage share': 48, Economy: 46,
      'Kill participation': 46, 'Damage per gold': 45, Vision: 42,
    })
    expect(strengthsClaim(abner)).toBeNull()
  })

  it('names what falls outside the middle, and says the rest is noise', () => {
    const top = parts({ Objectives: 75, Vision: 72, Economy: 52, 'Kill participation': 35 })
    expect(strengthsClaim(top)).toBe(
      'Strong at objectives and vision, weak at kill participation. The rest sit in the middle band, where a gap is noise.',
    )
    expect(strengthsClaim(parts({ Vision: 70, Survival: 50 }))).toBe(
      'Strong at vision. The rest sit in the middle band, where a gap is noise.',
    )
    expect(strengthsClaim(parts({ Survival: 18, Vision: 27, Economy: 30 }))).toBe(
      'Weak at survival, vision and economy.',
    )
  })
})
