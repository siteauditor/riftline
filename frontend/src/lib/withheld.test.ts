import { describe, expect, it } from 'vitest'

import { WITHHELD, withheldText } from './withheld'

describe('withheldText', () => {
  it('has words for every reason the API gives, and none for a scored game', () => {
    expect(Object.keys(WITHHELD).sort()).toEqual(
      ['no_roles', 'not_scored_yet', 'not_ten', 'remake', 'thin_queue'].sort(),
    )
    expect(withheldText(null)).toBeNull()
    expect(withheldText(undefined)).toBeNull()
  })

  it('says "not scored yet" only when that is the reason', () => {
    expect(withheldText('thin_queue')?.short).toBe('Too few games to score')
    expect(withheldText('not_scored_yet')?.short).toBe('Not scored yet')
    for (const [reason, text] of Object.entries(WITHHELD)) {
      if (reason !== 'not_scored_yet') expect(`${text.short} ${text.long}`).not.toMatch(/yet/)
    }
  })
})
