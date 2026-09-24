import { describe, expect, it } from 'vitest'

import { missingTierReason, separationLine, tierLegend } from './tierlist'

describe('the tier list says what its letters are', () => {
  it('calls a letter a place in the role, among champions with the floor', () => {
    const legend = tierLegend(20)
    expect(legend).toContain('20 or more games')
    expect(legend).toContain('not a measured gap')
  })

  it('counts what the games separate from even, and says so when they separate nothing', () => {
    expect(separationLine({ patch: '16.18', separated_above: 8, separated_below: 8 }, 247)).toMatch(
      /^On patch 16\.18 the games show 8 of these 247 picks to be better than even and 8 to be worse/,
    )
    expect(separationLine({ patch: '16.18', separated_above: 0, separated_below: 0 }, 12)).toMatch(
      /do not yet show any of these 12 picks/,
    )
  })

  it('says why a row has no letter', () => {
    expect(missingTierReason(12, 20)).toBe('No letter: under 20 games')
    expect(missingTierReason(40, 20)).toBe('No letter: too few champions in this role to rank')
  })
})
